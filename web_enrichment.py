"""Tra cứu web theo MST; chỉ tự lấy trường từ bảng xác định đúng pháp nhân."""
import hashlib
import ipaddress
import json
import os
import re
import socket
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote_plus, urlparse, parse_qs, unquote, urljoin
from urllib.request import Request, urlopen

from raw_import import tax_id, date_text
from email_utils import emails

class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.links = [], []
        self.table = None
        self.row = None
        self.cell = None
        self.depth = 0
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {'script', 'style'}:
            self.skip += 1
        if tag == 'a' and attrs.get('href'):
            self.links.append(attrs['href'])
        if tag == 'table':
            self.depth += 1
            if self.depth == 1:
                self.table = []
        elif tag == 'tr' and self.table is not None:
            self.row = []
        elif tag in {'td', 'th'} and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None and not self.skip:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in {'script', 'style'}:
            self.skip = max(0, self.skip - 1)
        if tag in {'td', 'th'} and self.cell is not None:
            self.row.append(re.sub(r'\s+', ' ', ' '.join(self.cell)).strip())
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            if self.table is not None:
                self.table.append(self.row)
            self.row = None
        elif tag == 'table':
            self.depth = max(0, self.depth - 1)
            if self.depth == 0 and self.table is not None:
                self.tables.append(self.table)
                self.table = None

def public_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username:
        raise ValueError('URL phải là trang web công khai http/https')
    for result in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80)):
        if not ipaddress.ip_address(result[4][0]).is_global:
            raise ValueError('Không tải địa chỉ mạng nội bộ')

def fetch(url, cache, timeout=12):
    public_url(url)
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    key = cache / (hashlib.sha256(url.encode()).hexdigest() + '.json')
    if key.exists():
        saved = json.loads(key.read_text(encoding='utf-8'))
        if time.time() - saved['time'] < 86400:
            return saved['body'], saved['url']
    request = Request(url, headers={'User-Agent': 'CompanyTaxonomyTool/1.0 (public company research)', 'Accept': 'text/html,application/xml,text/xml'})
    # Kiểm tra lại mọi redirect, không cho chuyển vào mạng nội bộ.
    from urllib.request import HTTPRedirectHandler, build_opener
    class Redirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            public_url(newurl)
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    with build_opener(Redirect()).open(request, timeout=timeout) as response:
        body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise ValueError('Trang vượt giới hạn 2 MB')
        if response.headers.get_content_type() not in {'text/html', 'text/xml', 'application/xml', 'application/rss+xml'}:
            raise ValueError('Trang không phải HTML/XML')
        text = body.decode(response.headers.get_content_charset() or 'utf-8', errors='replace')
        final = response.url
    key.write_text(json.dumps({'time': time.time(), 'url': final, 'body': text}, ensure_ascii=False), encoding='utf-8')
    return text, final

def search(query, cache, api_key=None):
    errors = []
    identifier = re.search(r'\b\d{10}(?:-\d{3})?\b', query)
    identifier = identifier.group() if identifier else ''
    api_key = api_key or os.environ.get('SERPER_API_KEY', '')
    if api_key:
        try:
            request = Request('https://google.serper.dev/search',
                data=json.dumps({'q': query, 'gl': 'vn', 'hl': 'vi', 'num': 5}).encode(),
                headers={'X-API-KEY': api_key, 'Content-Type': 'application/json'}, method='POST')
            with urlopen(request, timeout=15) as response:
                result = json.loads(response.read(2_000_000))
            urls = [item['link'] for item in result.get('organic', [])
                    if item.get('link', '').startswith(('http://', 'https://'))]
            if urls:
                return urls[:5], errors
            errors.append('Serper: không trả kết quả')
        except Exception as exc:
            errors.append('Serper: ' + str(exc))
    try:
        body, _ = fetch('https://www.bing.com/search?format=rss&q=' + quote_plus(query), cache)
        root = ET.fromstring(body)
        urls = [item.findtext('link') for item in root.findall('.//item')
                if item.findtext('link') and (not identifier or identifier in ' '.join(item.itertext()))]
        if urls:
            return urls[:5], errors
        errors.append('Bing: không có kết quả chứa đúng MST')
    except Exception as exc:
        errors.append('Bing: ' + str(exc))
    try:
        body, _ = fetch('https://html.duckduckgo.com/html/?q=' + quote_plus(query), cache)
        page = Page()
        page.feed(body)
        urls = []
        for link in page.links:
            if 'uddg=' in link:
                target = parse_qs(urlparse(link).query).get('uddg', [''])[0]
                if target.startswith(('http://', 'https://')) and target not in urls and (not identifier or identifier in target):
                    urls.append(target)
        if not urls:
            errors.append('DuckDuckGo: không trả liên kết hoặc yêu cầu CAPTCHA')
        return urls[:5], errors
    except Exception as exc:
        errors.append('DuckDuckGo: ' + str(exc))
    return [], errors

def extract(html, expected_tax, fold, company=''):
    page = Page()
    page.feed(html)
    fields = {}
    structured = []
    for script in re.findall(r'<script\b[^>]*type=[\"\']application/ld\+json[\"\'][^>]*>(.*?)</script>', html, re.I | re.S):
        try:
            data = json.loads(script)
            nodes = data if isinstance(data, list) else [data]
            for node in nodes:
                if isinstance(node, dict):
                    structured.extend(node.get('@graph', [node]))
        except (ValueError, TypeError):
            continue
    for org in structured:
        if not isinstance(org, dict) or tax_id(org.get('taxID', org.get('vatID', ''))) != expected_tax:
            continue
        for ci, key in [(19, 'email'), (23, 'url')]:
            value = org.get(key)
            if isinstance(value, str) and ((ci == 19 and re.fullmatch(r'[^\s@*]+@[^\s@*]+\.[^\s@*]+', value))
                                         or (ci == 23 and value.startswith(('http://', 'https://')))):
                fields[ci] = (value, 'JSON-LD ' + key + ': ' + value)
        products = [node.get('name') for node in structured if isinstance(node, dict)
                    and node.get('@type') == 'Product' and isinstance(node.get('name'), str)]
        if products:
            value = '; '.join(dict.fromkeys(products))[:1000]
            fields[14] = (value, 'JSON-LD Product.name: ' + value)
    # Bảng phải có nhãn MST và đúng giá trị, không lấy email/hotline footer.
    for table in page.tables:
        identity = any(len(r) >= 2 and fold(r[0]).strip(' :') in {'ma so thue', 'ma so doanh nghiep', 'mst'}
                       and tax_id(r[1]) == expected_tax for r in table)
        if not identity:
            continue
        labels = {2: {'ten quoc te', 'ten tieng anh'}, 15: {'nguoi dai dien', 'nguoi dai dien phap luat'},
                  20: {'dia chi thue', 'dia chi'}, 30: {'tinh trang', 'trang thai'},
                  29: {'ngay hoat dong', 'ngay bat dau hoat dong'}, 28: {'ngay cap', 'ngay cap giay phep'},
                  19: {'email', 'e-mail'}, 23: {'website'}, 3: {'nganh nghe chinh'}}
        for row in table:
            if len(row) < 2:
                continue
            label, value = fold(row[0]).strip(' :'), row[1].strip()
            if not value:
                continue
            quote = (row[0] + ': ' + value)[:500]
            for ci, choices in labels.items():
                if label in choices and ci not in fields:
                    if ci == 19:
                        if not emails(value):
                            continue
                        value = '; '.join(emails(value))
                    if ci == 23 and not value.startswith(('http://', 'https://')):
                        continue
                    if ci in {28, 29}:
                        value = date_text(value)
                    fields[ci] = (value, quote)
            if label in {'dien thoai', 'so dien thoai', 'mobile', 'telephone'}:
                numbers = re.findall(r'(?<!\d)(?:\+84|0)[\d .()-]{8,18}\d(?!\d)', value)
                for number in numbers:
                    number = re.sub(r'[\s.()-]', '', number)
                    ci = 17 if number.startswith(('02', '+842')) or (number.startswith('0') and len(number) == 11) else 18
                    fields.setdefault(ci, (number, quote))
        break
    from content_rules import extract_text_fields
    text_fields, _ = extract_text_fields(html, expected_tax, company, fold)
    for ci, value in text_fields.items():
        fields.setdefault(ci, value)
    return fields

def enrich(rows, headers, fold, cache, progress=None, cancelled=None, loader=fetch, finder=search, taxonomy=None, checkpoint=None):
    evidence, audit = [], []
    checked = datetime.now(timezone(timedelta(hours=7))).strftime('%d/%m/%Y')
    for index, row in enumerate(rows, 1):
        if cancelled and cancelled():
            raise InterruptedError('Đã dừng tra cứu. Chưa ghi đè kết quả.')
        mst = tax_id(row[27])
        if progress:
            progress(f'Tra cứu {index}/{len(rows)}: {row[1]} ({mst})')
        entry = {'tax_id': mst, 'company': row[1], 'pages': [], 'errors': [], 'fields_found': 0}
        audit.append(entry)
        if not mst:
            entry['errors'].append('MST không hợp lệ, không tra cứu để tránh nhầm pháp nhân')
            continue
        urls, errors = finder('"' + mst + '" "' + row[1] + '"', cache)
        entry['errors'].extend(errors)
        if progress:
            progress(f'{mst}: tìm được {len(urls)} liên kết.' + (' ' + ' | '.join(errors) if errors else ''))
        # Có thể đọc trực tiếp nguồn raw nếu tìm kiếm bị chặn; bỏ trang danh sách tỉnh.
        for source in row[24].split('; '):
            if source.startswith(('http://', 'https://')) and mst in source and source not in urls:
                urls.insert(0, source)
            elif source.startswith(('http://', 'https://')) and mst not in source:
                try:
                    if progress:
                        progress(f'{mst}: tìm hồ sơ trong nguồn raw {source}')
                    body, final = loader(source, cache)
                    listing = Page()
                    listing.feed(body)
                    discovered = [urljoin(final, link) for link in listing.links
                                  if re.search(r'(?<!\d)' + re.escape(mst) + r'(?![\d-])', unquote(link))]
                    for link in dict.fromkeys(discovered):
                        if link not in urls:
                            urls.insert(0, link)
                    entry.setdefault('raw_source_discovery', []).append({'url': final, 'links_found': len(discovered)})
                except Exception as exc:
                    entry['errors'].append('Nguồn raw ' + source + ': ' + str(exc))
        # URL chỉ là ứng viên; vẫn phải xác nhận MST trong nội dung trang.
        slug = re.sub(r'[^a-z0-9]+', '-', fold(row[1])).strip('-')
        fallbacks = [
                f'https://masothue.com/{mst}-{slug}',
                f'https://thuvienphapluat.vn/ma-so-thue/{slug}-mst-{mst}.html',
            ]
        if not urls:
            entry['discovery'] = 'Thử URL hồ sơ trực tiếp vì tìm kiếm không có kết quả'
        urls = list(dict.fromkeys(urls[:6] + fallbacks))
        found = {}
        documents = []
        for url in urls[:8]:
            if cancelled and cancelled():
                raise InterruptedError('Đã dừng tra cứu. Chưa ghi đè kết quả.')
            try:
                if progress:
                    progress(f'{mst}: đang đọc {url}')
                html, final = loader(url, cache)
                fields = extract(html, mst, fold, row[1])
                if progress:
                    if fields:
                        progress(f'{mst}: đọc được {len(fields)} trường khớp MST: ' + ', '.join(headers[ci] for ci in fields))
                    else:
                        progress(f'{mst}: tải được trang nhưng chưa trích được trường khớp MST từ {final}')
                from content_rules import extract_text_fields
                _, content = extract_text_fields(html, mst, row[1], fold)
                if content:
                    documents.append({'url': final, 'content': '\n'.join(content)[:20000]})
                entry['pages'].append({'url': final, 'matched_identity': bool(fields), 'fields': len(fields)})
                for ci, (value, quote) in fields.items():
                    found.setdefault(ci, set()).add(value)
                    evidence.append({'tax_id': mst, 'field': headers[ci], 'value': value,
                                     'source': final, 'quote': quote, 'checked_at': checked})
            except Exception as exc:
                entry['errors'].append(url + ': ' + str(exc))
                if progress:
                    progress(f'{mst}: không đọc được {url}: {exc}')
        entry['fields_found'] = len(found)
        entry['documents'] = documents
        entry['conflicting_fields'] = [headers[ci] for ci, values in found.items() if len(values) > 1]
        entry['differences_from_raw'] = [{'field': headers[ci], 'raw': row[ci], 'web': sorted(values)}
                                         for ci, values in found.items() if row[ci] and row[ci] not in values]
        entry['fields_added'] = []
        # Chỉ tự điền trường trống có nguồn nhất quán; khác raw để báo cáo đối chiếu.
        for ci, values in found.items():
            if len(values) != 1:
                continue
            value = next(iter(values))
            if row[ci].strip() in {'', '.', '-'} or (ci == 3 and fold(row[ci]) == fold(value)):
                if row[ci].strip() in {'', '.', '-'}:
                    entry['fields_added'].append(headers[ci])
                row[ci] = value
        if taxonomy:
            from content_rules import match_taxonomy
            entry['taxonomy_matches'] = match_taxonomy(row, taxonomy, fold)
        matched = [p['url'] for p in entry['pages'] if p['matched_identity']]
        if matched:
            row[24] = '; '.join(dict.fromkeys(filter(None, [*row[24].split('; '), *matched])))
            row[25] += f' Đã tra cứu nguồn web theo MST ngày {checked}; xem web_research.json để đối chiếu.'
        else:
            row[25] += f' Chưa lấy được thông tin web xác định đúng MST ngày {checked}; xem lỗi tra cứu.'
        if progress:
            progress(f'{mst}: hoàn tất — {len(matched)} trang khớp MST, {len(found)} trường tìm thấy, '
                     f'{len(entry["fields_added"])} trường điền mới, {len(entry["differences_from_raw"])} trường khác raw để đối chiếu.')
        if checkpoint:
            checkpoint(rows[:index], evidence, audit)
    return rows, evidence, audit
