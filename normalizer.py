"""Chuẩn hóa danh bạ theo taxonomy. Python 3.10+, không cần thư viện ngoài."""
import argparse
import csv
import io
import json
import re
import sys
import os
import tempfile
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote_plus, urlparse
from raw_import import map_rows, classify_registered
from email_utils import emails, split_company_emails

HEADERS = [
    'STT - No', 'Tên đầy đủ của công ty - Full Company Name',
    'Tên công ty - Company Name', 'Hoạt động của công ty / Business Activities',
    'Mã lĩnh vực / Industry Code', 'Lĩnh vực / Parent Industry',
    'Mã loài hoặc đối tượng / Species or Target Group Code',
    'Loài hoặc đối tượng / Species or Target Group',
    'Mã danh mục / Category Code', 'Danh mục / Category',
    'Mã danh mục phụ / Subcategory Code', 'Danh mục phụ / Subcategory',
    'Mã sản phẩm hoặc giải pháp / Product or Solution Code',
    'Sản phẩm hoặc giải pháp / Product or Solution',
    'Sản phẩm tiêu biểu của công ty / Company Product Highlights',
    'Tên thành viên công ty - Contact Name', 'Chức danh - Job Title',
    'Số điện thoại bàn / Telephone', 'Số di động / Mobile',
    'Email liên hệ / Contact Email', 'Địa chỉ - Address',
    'Tỉnh / Thành phố - Province / City', 'Quốc Gia - Country',
    'Website', 'SOURCE', 'NOTE', 'show / association', 'Mã số thuế',
    'Ngày cấp giấy phép', 'Ngày hoạt động', 'Trạng thái', 'DATE',
]
PAIRS = [(4, 5), (6, 7), (8, 9), (10, 11), (12, 13)]
TAX_PAIRS = [(1, 2), (3, 4), (5, 6), (7, 8), (9, 10)]

def clean(value):
    value = unicodedata.normalize('NFC', str(value)).strip()
    return '' if value in {'.', '-', 'N/A', 'n/a', 'null'} else value

def folded(value):
    value = unicodedata.normalize('NFD', value.lower().replace('đ', 'd'))
    return ''.join(c for c in value if not unicodedata.combining(c))

def table(text):
    lines = text.lstrip('\ufeff').splitlines()
    nonempty = [line.strip() for line in lines if line.strip()]
    if nonempty and all(line.startswith('|') and line.endswith('|') for line in nonempty):
        rows = []
        for line in nonempty:
            row = [cell.strip() for cell in line[1:-1].split('|')]
            if all(re.fullmatch(r':?-+:?', cell) for cell in row):
                continue
            rows.append([re.sub(r'\[([^\]]+)\]\((https?://[^)]+)\)', r'\2', cell) for cell in row])
        return rows
    sample = '\n'.join(lines[:10])
    delimiter = '\t' if '\t' in sample else ','
    return [r for r in csv.reader(io.StringIO(text.lstrip('\ufeff')), delimiter=delimiter)
            if any(c.strip() for c in r)]

class Taxonomy:
    def __init__(self, text):
        self.source_text = text
        self.maps = [defaultdict(set) for _ in TAX_PAIRS]
        self.activities = set()
        self.parents = defaultdict(set)
        for row in table(text):
            row += [''] * max(0, 11 - len(row))
            if not re.fullmatch(r'LV\d+', row[1].strip()):
                continue
            if clean(row[0]):
                self.activities.add(clean(row[0]))
            for mapping, (ci, ni) in zip(self.maps, TAX_PAIRS):
                code, name = clean(row[ci]), clean(row[ni])
                if code and name:
                    mapping[code].add(name)
            for ci, pi in [(5, 1), (7, 5), (9, 7)]:
                if clean(row[ci]) and clean(row[pi]):
                    self.parents[clean(row[ci])].add(clean(row[pi]))

    def conflicts(self):
        return [{'code': code, 'names': sorted(names)} for mapping in self.maps
                for code, names in mapping.items() if len(names) > 1]

def phone(value, country):
    """Bỏ số 0 đầu mỗi số điện thoại; giữ nguyên mã quốc tế +84."""
    return re.sub(r'(^|[;,/]|\s[-–]\s)(\s*)0+(?=\d)', r'\1\2', value)

def relevance(row):
    # Không dùng tên công ty hoặc NOTE cũ làm bằng chứng dương tính.
    text = folded(row[3] + '; ' + row[14])
    clauses = re.split(r'[;\n]', text)
    usable = ' '.join(c for c in clauses if not re.search(
        r'chua (xac minh|co bang chung)|khong co bang chung|loai tru|khong san xuat', c))
    livestock = bool(re.search(r'chan nuoi|gia suc|gia cam|thu y|livestock', usable)) or row[4] == 'LV01'
    aqua = bool(re.search(r'thuy san|hai san|aquaculture|seafood', usable)) or row[4] in {'LV02', 'LV06', 'LV07'}
    level = 'theo dữ liệu đầu vào, chưa xác minh độc lập'
    return (f'Chăn nuôi: {"có liên quan" if livestock else "chưa đủ bằng chứng"}; '
            f'Thủy sản: {"có liên quan" if aqua else "chưa đủ bằng chứng"} ({level}). '
            'Ngành đăng ký không chứng minh sản phẩm đang bán.')

def normalize(text, taxonomy, evidence=None, strict_taxonomy=False):
    rows, issues, changes = [], [], []
    raw_rows = table(text)
    raw_rows, import_log = map_rows(raw_rows, HEADERS, folded)
    seen = set()
    for line, raw in enumerate(raw_rows, 1):
        if len(raw) > 32 and not any(c.strip() for c in raw[32:]):
            raw = raw[:32]
        if len(raw) != 32:
            raise ValueError(f'Dòng {line}: có {len(raw)} cột, cần đúng 32. Không tự dịch cột.')
        row = list(map(clean, raw))
        registered = classify_registered(row, taxonomy, folded)
        if registered:
            changes.append({'line': line, 'reason': 'Phân loại theo mô tả ngành đăng ký đầu vào', 'original_activity': registered})
        from content_rules import match_taxonomy
        previous_codes = row[4:14]
        taxonomy_matches = match_taxonomy(row, taxonomy, folded)
        if strict_taxonomy:
            from taxonomy_cleanup import cleanup_taxonomy
            cleanup_taxonomy(row,taxonomy,folded)
        if row[4:14] != previous_codes:
            changes.append({'line':line, 'tax_id':row[27], 'reason':'Đối chiếu taxonomy từ ngành/sản phẩm',
                            'old':previous_codes, 'new':row[4:14], 'matches':taxonomy_matches})
        def issue(message):
            issues.append({'line': line, 'stt': row[0], 'tax_id': row[27], 'message': message})
        if row[27] and not re.fullmatch(r'\d{10}(?:-\d{3})?', row[27]):
            issue('MST không đúng định dạng 10 số hoặc 10 số-3 số; giữ nguyên để đối chiếu')
        if row[27] in seen and row[27]:
            issue('Trùng MST; giữ nguyên dòng, chưa gộp')
        seen.add(row[27])
        for (ci, ni), mapping in zip(PAIRS, taxonomy.maps):
            code, name = row[ci], row[ni]
            if not code and name:
                matches = [k for k, names in mapping.items() if name in names]
                if len(matches) == 1:
                    row[ci] = code = matches[0]
                else:
                    issue(f'Cột {ni+1}: tên không xác định được một mã duy nhất')
            if code:
                names = mapping.get(code, set())
                if not names:
                    issue(f'Mã ngoài taxonomy: {code}')
                elif len(names) > 1:
                    issue(f'Taxonomy có nhiều tên cho {code}: ' + ' | '.join(sorted(names)))
                elif not name:
                    row[ni] = next(iter(names))
                elif name not in names:
                    issue(f'Tên không khớp mã {code}; giữ dữ liệu gốc')
        # Kiểm tra và bổ sung tổ tiên duy nhất. Không gán loài theo cùng hàng taxonomy.
        for ci, pi in [(12, 10), (10, 8), (8, 4)]:
            if row[ci]:
                parents = taxonomy.parents.get(row[ci], set())
                if len(parents) == 1 and not row[pi]:
                    row[pi] = next(iter(parents))
                    pair_index = [p[0] for p in PAIRS].index(pi)
                    names = taxonomy.maps[pair_index].get(row[pi], set())
                    if len(names) == 1:
                        row[pi+1] = next(iter(names))
                elif row[pi] and row[pi] not in parents:
                    issue(f'Quan hệ cha-con không hợp lệ: {row[ci]} -> {row[pi]}')
        for activity in filter(None, map(str.strip, row[3].split(';'))):
            if activity not in taxonomy.activities:
                issue('Hoạt động ngoài danh sách taxonomy: ' + activity)
        for ci in [17, 18]:
            updated = phone(row[ci], row[22])
            if updated != row[ci]:
                changes.append({'tax_id': row[27], 'field': HEADERS[ci], 'old': row[ci],
                                'new': updated, 'reason': 'Bỏ số 0 đầu điện thoại theo yêu cầu'})
                row[ci] = updated
        for ci in [28, 29, 31]:
            if row[ci]:
                try:
                    datetime.strptime(row[ci], '%d/%m/%Y')
                except ValueError:
                    issue(f'Cột {ci+1}: ngày không đúng dd/mm/yyyy')
        if row[19] and not emails(row[19]):
            issue('Email cần kiểm tra định dạng')
        if row[23] and urlparse(row[23]).scheme not in {'http', 'https'}:
            issue('Website cần URL http/https')
        if 'người đại diện' in row[16].lower() or 'giám đốc' in row[16].lower():
            issue('Contact hiện là người đại diện/giám đốc theo nguồn; chưa xác minh đầu mối bán hàng')
        for item in evidence or []:
            if item.get('tax_id') != row[27]:
                continue
            field, value = item.get('field'), clean(item.get('value', ''))
            source = item.get('source', '')
            if field not in HEADERS or not value or not item.get('quote') or not item.get('checked_at') or urlparse(source).scheme not in {'http', 'https'}:
                issue('Bằng chứng bổ sung thiếu field/value/source/quote/checked_at hợp lệ')
                continue
            ci = HEADERS.index(field)
            if ci in {17, 18}:
                value = phone(value, row[22])
            # Bổ sung có nguồn vào ô trống, hoặc xác nhận giá trị hiện có; xung đột giữ để rà soát.
            if ci == 25:
                row[25] = ' '.join(filter(None, [row[25], value]))
            elif ci in {0, 27, 31} or ci in range(4, 14):
                issue('Bằng chứng cho cột định danh/taxonomy/NOTE/DATE cần chỉnh raw và chạy kiểm tra lại')
                continue
            elif ci == 19 and emails(value):
                value = '; '.join(emails(row[ci] + '; ' + value))
            elif ci == 14:
                from content_rules import merge_highlights
                if value not in row[ci]:
                    value = merge_highlights(row[ci], value)
                else:
                    value = row[ci]
            elif row[ci] and row[ci] != value and item.get('mode') != 'replace':
                issue(f'Nguồn bổ sung khác dữ liệu gốc tại {field}: {value} ({source})')
                continue
            changes.append(dict(item, old=row[ci], new=value, reason='Bằng chứng bổ sung do người dùng/người rà soát cung cấp'))
            if ci != 25:
                row[ci] = value
            if source not in row[24].split('; '):
                row[24] = '; '.join(filter(None, [row[24], source]))
            row[25] += f' Đối chiếu {field}: {source} (ngày {item["checked_at"]}).'
        row[25] = relevance(row) + (' Ghi chú: ' + row[25] if row[25] else '')
        rows.append(row)
    expanded = split_company_emails(rows)
    return expanded, {'issues': issues, 'changes': changes, 'taxonomy_conflicts': taxonomy.conflicts(),
                  'processed_at': datetime.now(timezone(timedelta(hours=7))).isoformat(),
                  'input_rows': len(raw_rows), 'processed_companies': len(rows), 'output_rows': len(expanded), 'import_log': import_log}

def csv_text(rows, headers=HEADERS, delimiter=','):
    buf = io.StringIO(newline='')
    writer = csv.writer(buf, delimiter=delimiter)
    # CSV không có kiểu dữ liệu: chặn công thức khi mở bằng bảng tính.
    safe = lambda v: "'" + str(v) if str(v).lstrip().startswith(('=', '+', '-', '@')) else v
    writer.writerow(headers)
    writer.writerows([[safe(v) for v in row] for row in rows])
    return buf.getvalue()

def atomic_text(path, value, encoding='utf-8'):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding=encoding, newline='', dir=path.parent, delete=False, suffix='.tmp') as handle:
            temporary = Path(handle.name)
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except PermissionError as exc:
        raise PermissionError(f'Không lưu được {path.name}. Đóng file đang mở trong Excel rồi chạy tiếp; bản đã lưu trước đó vẫn giữ nguyên.') from exc
    finally:
        if temporary and temporary.exists():
            temporary.unlink()

def export(rows, report, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    for filename, delimiter in [('companies.csv', ','), ('companies.tsv', '\t')]:
        atomic_text(output / filename, csv_text(rows, delimiter=delimiter), encoding='utf-8-sig')
    atomic_text(output / 'audit.json', json.dumps(report, ensure_ascii=False, indent=2))
    research = []
    for row in rows:
        missing = [HEADERS[i] for i in [10, 12, 19, 23] if not row[i]]
        query = f'"{row[27]}" "{row[1]}" sản phẩm liên hệ website'
        research.append([row[0], row[27], row[1], '; '.join(missing),
                         'https://www.google.com/search?q=' + quote_plus(query)])
    atomic_text(output / 'research_queue.csv', csv_text(research,
        ['STT', 'MST', 'Công ty', 'Cột còn thiếu', 'Tìm kiếm']), encoding='utf-8-sig')

def read_input(path, spreadsheet=True):
    path = Path(path)
    data = path.read_bytes()
    if data.startswith(b'PK'):
        if not spreadsheet:
            raise ValueError(f'{path.name}: cần file JSON văn bản, không phải Excel/ZIP.')
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as book:
                ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
                strings = []
                if 'xl/sharedStrings.xml' in book.namelist():
                    strings = [''.join(t.text or '' for t in si.findall('.//s:t', ns))
                               for si in ET.fromstring(book.read('xl/sharedStrings.xml')).findall('s:si', ns)]
                workbook = ET.fromstring(book.read('xl/workbook.xml'))
                sheet = workbook.find('s:sheets/s:sheet', ns)
                rid = sheet.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']
                rels = ET.fromstring(book.read('xl/_rels/workbook.xml.rels'))
                target = next(r.attrib['Target'] for r in rels if r.attrib['Id'] == rid)
                import posixpath
                target = target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/' + target)
                rows = []
                for element in ET.fromstring(book.read(target)).findall('.//s:sheetData/s:row', ns):
                    row = []
                    for cell in element.findall('s:c', ns):
                        col = re.match(r'[A-Z]+', cell.attrib['r']).group()
                        index = 0
                        for char in col:
                            index = index * 26 + ord(char) - 64
                        row.extend([''] * max(0, index - len(row)))
                        value = cell.find('s:v', ns)
                        text = value.text or '' if value is not None else ''
                        if cell.attrib.get('t') == 's':
                            text = strings[int(text)]
                        elif cell.attrib.get('t') == 'inlineStr':
                            text = ''.join(t.text or '' for t in cell.findall('.//s:t', ns))
                        row[index-1] = text
                    if any(row):
                        if len(row) <= 32 and path.suffix.lower() == '.xlsx':
                            row.extend([''] * (32-len(row)))
                        rows.append(row)
                buf = io.StringIO(newline='')
                csv.writer(buf, delimiter='\t').writerows(rows)
                return buf.getvalue()
        except (KeyError, ValueError, ET.ParseError, zipfile.BadZipFile, StopIteration, AttributeError) as exc:
            raise ValueError(f'{path.name}: không đọc được workbook XLSX. Hãy xuất sheet cần xử lý thành TSV UTF-8.') from exc
    if data.startswith(b'\xd0\xcf\x11\xe0'):
        raise ValueError(f'{path.name}: định dạng Excel .xls cũ. Hãy Save As .xlsx hoặc CSV UTF-8.')
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        return data.decode('utf-16')
    try:
        return data.decode('utf-8-sig')
    except UnicodeDecodeError:
        pass
    # Windows ANSI thường gặp trong file xuất Excel; không bỏ byte lỗi.
    for encoding in ('cp1258', 'cp1252'):
        try:
            text = data.decode(encoding)
            if '\x00' not in text:
                return unicodedata.normalize('NFC', text)
        except UnicodeDecodeError:
            continue
    raise ValueError(f'{path.name}: không nhận diện được encoding. Hãy lưu lại thành CSV UTF-8 hoặc TSV UTF-8.')

def run(raw='data/raw.tsv', taxonomy='data/taxonomy.tsv', output='outputs', evidence=None,
        web=False, progress=None, cancelled=None, search_api_key=None,
        search_mode='google_ai_mode', manual_wait=None, browser_channel='chrome',
        browser_connection='existing', cdp_endpoint='chrome'):
    ev = json.loads(read_input(evidence, spreadsheet=False)) if evidence else []
    if not isinstance(ev, list):
        raise ValueError('Evidence phải là danh sách JSON')
    raw_text = read_input(raw)
    tax = Taxonomy(read_input(taxonomy))
    research, web_ev, original_log = [], [], []
    last_saved = None
    total_companies = 0
    def save_progress(partial, collected, entries, stopped=False):
        nonlocal last_saved
        saved_rows, saved_report = normalize(csv_text(partial, delimiter='\t'), tax, ev + collected,
            strict_taxonomy=search_mode in {'chatgpt_pack10','chatgpt_pack5'})
        saved_report.update({'web_research': json.loads(json.dumps(entries, ensure_ascii=False)), 'search_mode': search_mode,
            'original_import_log': original_log, 'total_companies': total_companies,
            'processed_companies': len(partial), 'output_rows': len(saved_rows),
            'partial': len(partial) < total_companies, 'stopped': stopped,
            'web_fields_found': sum(entry['fields_found'] for entry in entries),
            'web_fields_added': sum(len(entry.get('fields_added', [])) for entry in entries),
            'web_companies_matched': sum(any(p['matched_identity'] for p in entry['pages']) for entry in entries),
            'web_companies_failed': sum(not any(p['matched_identity'] for p in entry['pages']) for entry in entries)})
        export(saved_rows, saved_report, output)
        atomic_text(Path(output) / 'web_research.json', json.dumps(entries, ensure_ascii=False, indent=2))
        atomic_text(Path(output) / 'web_evidence.json', json.dumps(collected, ensure_ascii=False, indent=2))
        last_saved = (saved_rows, saved_report)
        if progress:
            progress(f'Đã lưu {len(partial)}/{total_companies} công ty → {len(saved_rows)} dòng (mỗi dòng một email).')
        return last_saved
    if web:
        mapped, original_log = map_rows(table(raw_text), HEADERS, folded)
        total_companies = len(mapped)
        try:
            if search_mode in {'google_overview','google_ai_mode'}:
                from google_overview import enrich_google
                mapped, web_ev, research = enrich_google(mapped, HEADERS, folded,
                    Path(output) / 'google_overview', tax, progress, cancelled, manual_wait, browser_channel,
                    connection=browser_connection, endpoint=cdp_endpoint,
                    response_mode='ai_mode' if search_mode == 'google_ai_mode' else 'overview', checkpoint=save_progress)
            elif search_mode in {'chatgpt_pack10','chatgpt_pack5'}:
                from chatgpt_pack import enrich_chatgpt
                mapped, web_ev, research = enrich_chatgpt(mapped, HEADERS, folded,
                    Path(output) / 'chatgpt_packs', tax, progress, cancelled, manual_wait, browser_channel,
                    connection=browser_connection, endpoint=cdp_endpoint, checkpoint=save_progress,
                    raw_rows=table(raw_text)[-len(mapped):] if mapped else [])
            elif search_mode == 'website':
                from web_enrichment import enrich, search
                mapped, web_ev, research = enrich(mapped, HEADERS, folded,
                    Path(output) / '.web_cache', progress, cancelled,
                    finder=lambda query, cache: search(query, cache, search_api_key), taxonomy=tax, checkpoint=save_progress)
            else:
                raise ValueError('Chế độ tìm kiếm không hợp lệ')
            return save_progress(mapped, web_ev, research, bool(cancelled and cancelled()))
        except InterruptedError:
            if last_saved:
                saved_rows, saved_report = last_saved
                saved_report['stopped'] = True
                export(saved_rows, saved_report, output)
                if progress:
                    progress(f'Đã dừng. File đã giữ {saved_report["processed_companies"]} công ty / {len(saved_rows)} dòng.')
                return saved_rows, saved_report
            raise InterruptedError('Đã dừng trước khi lưu công ty đầu tiên; file kết quả cũ không thay đổi.')
    rows, report = normalize(raw_text, tax, ev + web_ev)
    export(rows, report, output)
    return rows, report

def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw', default='data/raw.tsv')
    parser.add_argument('--taxonomy', default='data/taxonomy.tsv')
    parser.add_argument('--output', default='outputs')
    parser.add_argument('--evidence', help='JSON thông tin bổ sung kèm nguồn và trích đoạn')
    parser.add_argument('--web', action='store_true', help='Tìm web theo MST trước khi chuẩn hóa')
    parser.add_argument('--search-mode', choices=['google_ai_mode','google_overview','website','chatgpt_pack10','chatgpt_pack5'], default='google_ai_mode')
    parser.add_argument('--browser', choices=['chrome','msedge','chromium'], default='chrome')
    parser.add_argument('--browser-connection', choices=['existing','separate'], default='existing')
    parser.add_argument('--cdp-endpoint', default='chrome')
    args = parser.parse_args()
    rows, report = run(args.raw, args.taxonomy, args.output, args.evidence, web=args.web, progress=print,
                       search_mode=args.search_mode, browser_channel=args.browser,
                       browser_connection=args.browser_connection, cdp_endpoint=args.cdp_endpoint)
    print(f'{len(rows)} công ty; {len(report["issues"])} mục cần rà soát; xuất tại {args.output}')

if __name__ == '__main__':
    main()
