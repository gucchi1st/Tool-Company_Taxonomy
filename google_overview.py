"""Google AI Overview qua Playwright, không gọi GPT/Serper."""
import html as html_lib
import json
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote_plus, urlparse, parse_qs

from content_rules import extract_text_fields, match_taxonomy, merge_highlights

OVERVIEW_SCRIPT = r'''() => {
  const visible = el => !!(el.getClientRects().length) && getComputedStyle(el).visibility !== 'hidden';
  const marker = /^(AI Overview|Tổng quan do AI|Thông tin tổng quan do AI|AI tổng quan)$/i;
  const candidates = [...document.querySelectorAll('[data-attrid="AIOverview"], [data-ai-overview], [aria-label="AI Overview"]')].filter(visible);
  if (!candidates.length) {
    const labels = [...document.querySelectorAll('h1,h2,h3,span,div')].filter(el => visible(el) && marker.test(el.innerText.trim()) && el.children.length < 5);
    for (const label of labels) {
      let el = label;
      for (let i=0; i<7 && el.parentElement; i++,el=el.parentElement) {
        const text = el.innerText.trim();
        if (text.length > 180 && text.length < 22000 && !el.querySelector('#search,#rso') && el.querySelector('a[href]')) {
          candidates.push(el); break;
        }
      }
    }
  }
  const block = candidates.sort((a,b)=>b.innerText.length-a.innerText.length)[0];
  if (!block) return null;
  document.querySelectorAll('[data-tax-tool-overview]').forEach(el=>el.removeAttribute('data-tax-tool-overview'));
  block.setAttribute('data-tax-tool-overview','true');
  return {text:block.innerText, html:block.outerHTML, links:[...block.querySelectorAll('a[href]')].map(a=>({url:a.href,title:a.innerText}))};
}'''

def external_links(links):
    result = []
    for item in links:
        url = item.get('url', '') if isinstance(item, dict) else item
        parsed = urlparse(url)
        if parsed.hostname and (parsed.hostname == 'google.com' or parsed.hostname.endswith('.google.com')):
            url = parse_qs(parsed.query).get('q', parse_qs(parsed.query).get('url', ['']))[0]
            parsed = urlparse(url)
        if parsed.scheme in {'http','https'} and parsed.hostname and 'google.' not in parsed.hostname and url not in result:
            result.append(url)
    return result

def parse_overview(text, row, fold):
    """Không tự nhận nội dung nhiều công ty là của pháp nhân đang tra cứu."""
    mst, name = row[27], row[1]
    compact = lambda value: re.sub(r'[^a-z0-9]+', '', fold(value))
    blocks = re.split(r'(?m)(?=^\s*(?:\d+[.)]\s*)?(?:CÔNG TY|CHI NHÁNH|DOANH NGHIỆP|HỢP TÁC XÃ)\b)', text)
    company_blocks = [b for b in blocks if re.match(r'^\s*(?:\d+[.)]\s*)?(?:CÔNG TY|CHI NHÁNH|DOANH NGHIỆP|HỢP TÁC XÃ)\b', b)]
    if company_blocks:
        matches = [b for b in company_blocks if re.search(r'(?<!\d)' + re.escape(mst) + r'(?![\d-])', b)
                   or compact(name) in compact(b.splitlines()[0])]
        if len(matches) != 1:
            return {}, 'Overview có nhiều pháp nhân hoặc chưa khớp tên/MST; cần rà soát'
        text = matches[0]
    exact_tax = bool(re.search(r'(?<!\d)' + re.escape(mst) + r'(?![\d-])', text))
    # Tên có thể xuất hiện trong đoạn văn; vẫn yêu cầu nguyên tên pháp nhân.
    if not exact_tax and compact(name) not in compact(text):
        return {}, 'Chưa khớp tên đầy đủ hoặc MST trong AI Overview'
    listed_ids = re.findall(r'(?<!\d)\d{10}(?:-\d{3})?(?!\d)', text)
    if listed_ids and mst not in listed_ids and re.search(r'mã số thuế|MST', text, re.I):
        return {}, 'MST trong Overview khác raw'
    # Dùng bộ đọc nhãn chung; nhãn định danh bổ sung chỉ phục vụ parser,
    # không coi là bằng chứng MST từ Google. Mức khớp thực tế ghi riêng.
    lines = [re.sub(r'^\s*[•*\-]\s*', '', line.strip()) for line in text.splitlines() if line.strip()]
    scoped_html = '<h1>' + html_lib.escape(name) + '</h1><div>Mã số thuế: ' + html_lib.escape(mst) + '</div>'
    scoped_html += ''.join('<p>' + html_lib.escape(line) + '</p>' for line in lines)
    fields, _ = extract_text_fields(scoped_html, mst, name, fold)
    # Không lấy contact công ty mẹ, tổng đài hoặc địa chỉ email bị che.
    for ci in list(fields):
        value, quote = fields[ci]
        if re.search(r'công ty mẹ|tổng đài|chung của|không công khai|chưa công khai', value + ' ' + quote, re.I):
            del fields[ci]
    return fields, ('Khớp MST trong Overview' if exact_tax else 'Khớp tên đầy đủ; Overview chưa nêu MST')

class GoogleBrowser:
    def __init__(self, profile, progress=None, cancelled=None, manual_wait=None, channel='chrome',
                 connection='existing', endpoint='chrome', response_mode='overview'):
        self.profile = Path(profile)
        self.progress = progress or (lambda text: None)
        self.cancelled = cancelled or (lambda: False)
        self.manual_wait = manual_wait
        self.channel = channel
        self.connection = connection
        self.endpoint = endpoint.strip() or channel
        self.owns_browser = connection == 'separate'
        self.response_mode = response_mode

    def __enter__(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError('Chưa cài Playwright. Chạy setup_playwright.bat rồi mở lại start.bat.') from None
        self.runtime = sync_playwright().start()
        try:
            if self.connection == 'existing':
                self.progress('Đang kết nối Chrome đang mở. Chấp nhận hộp thoại cho phép kết nối trong Chrome nếu có.')
                self.browser = self.runtime.chromium.connect_over_cdp(self.endpoint, no_defaults=True, timeout=30000)
                if not self.browser.contexts:
                    raise RuntimeError('Chrome không có browser context đang mở')
                self.context = self.browser.contexts[0]
            elif self.connection == 'separate':
                self.profile.mkdir(parents=True, exist_ok=True)
                self.context = self.runtime.chromium.launch_persistent_context(str(self.profile),
                    channel=self.channel, headless=False, locale='vi-VN', viewport={'width':1280,'height':900})
            else:
                raise ValueError('Kiểu kết nối Chrome không hợp lệ')
            self.page = self.context.new_page()
            self.page.set_default_timeout(4000)
            return self
        except Exception as exc:
            self.runtime.stop()
            if self.connection == 'existing':
                if 'DevToolsActivePort file not found' in str(exc):
                    raise RuntimeError(
                        'Chrome đang mở nhưng chưa bật Remote Debugging, hoặc tool đang tìm sai thư mục Chrome.\n\n'
                        '1. Trong chính cửa sổ Chrome đang đăng nhập Google, mở:\n'
                        'chrome://inspect/#remote-debugging\n'
                        '2. Bật “Allow remote debugging for this browser instance”.\n'
                        '3. Giữ Chrome mở, quay lại tool và bấm Kiểm tra kết nối.\n'
                        '4. Chấp nhận hộp thoại kết nối nếu Chrome hỏi.\n\n'
                        'Nếu đã bật mà vẫn lỗi: mở chrome://version và kiểm tra Profile Path. '
                        'Không cần tạo hay sao chép profile mới.') from exc
                raise RuntimeError('Chưa kết nối được profile Chrome đang dùng. Mở Chrome đúng profile, '
                    'vào chrome://inspect/#remote-debugging, bật Remote Debugging và chấp nhận kết nối. '
                    'Cách tự kết nối cần Chrome 144+; có thể nhập URL CDP nếu bạn đã bật cổng riêng. '
                    'Tool không tự khởi động lại hay sao chép profile cá nhân. Chi tiết: ' + str(exc)) from exc
            raise RuntimeError('Không mở được Chrome profile riêng. Đóng cửa sổ cùng profile của tool, '
                               'hoặc chọn msedge/chromium. Chi tiết: ' + str(exc)) from exc

    def __exit__(self, *args):
        try:
            if self.owns_browser:
                self.context.close()
            elif hasattr(self, 'page') and not self.page.is_closed():
                self.page.close()
        finally:
            self.runtime.stop()

    def wait_user(self, reason):
        self.progress(reason)
        if self.manual_wait:
            return self.manual_wait(reason)
        raise RuntimeError(reason + ' Chạy giao diện để có nút Tiếp tục sau khi xử lý trên trình duyệt.')

    def read(self, row):
        if self.response_mode == 'ai_mode':
            from google_ai_mode import read_ai_mode
            return read_ai_mode(self, row)
        query = f'{row[1]} {row[27]} thông tin liên hệ email lĩnh vực sản phẩm'
        url = 'https://www.google.com/search?hl=vi&q=' + quote_plus(query)
        self.progress('Mở Google: ' + query)
        self.page.goto(url, wait_until='domcontentloaded', timeout=45000)
        for attempt in range(2):
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                if self.cancelled():
                    raise InterruptedError('Đã dừng tra cứu Google')
                if self.page.is_closed():
                    raise RuntimeError('Cửa sổ Google đã đóng')
                body = self.page.locator('body').inner_text(timeout=4000)
                if '/sorry/' in self.page.url or re.search(r'unusual traffic|lưu lượng truy cập bất thường|verify you are human', body, re.I):
                    self.wait_user('Google yêu cầu CAPTCHA. Hãy xử lý trực tiếp trong Chrome rồi bấm Tiếp tục trong tool.')
                    deadline = time.monotonic() + 25
                    continue
                if urlparse(self.page.url).hostname == 'consent.google.com':
                    self.wait_user('Google yêu cầu chọn cookie. Hãy lựa chọn trong Chrome rồi bấm Tiếp tục.')
                    deadline = time.monotonic() + 25
                    continue
                block = self.page.evaluate(OVERVIEW_SCRIPT)
                if block:
                    # Chỉ bấm nút mở rộng bên trong vùng Overview đã phát hiện.
                    for label in ['Show more', 'Hiện thêm', 'Xem thêm', 'Hiển thị thêm']:
                        buttons = self.page.locator('[data-tax-tool-overview]').get_by_role('button', name=re.compile('^' + label + '$', re.I))
                        if buttons.count() == 1 and buttons.first.is_visible():
                            try:
                                buttons.first.click(timeout=2000)
                                self.page.wait_for_timeout(800)
                                block = self.page.evaluate(OVERVIEW_SCRIPT) or block
                            except Exception:
                                pass
                            break
                    block.update({'query': query, 'search_url': self.page.url, 'sources': external_links(block.get('links', [])),
                                  'capture': 'automatic', 'status': 'captured'})
                    return block
                self.page.wait_for_timeout(500)
            if attempt == 0:
                self.wait_user('Chưa tự nhận diện AI Overview. Nếu Google có hiển thị, hãy mở rộng và bôi đen riêng phần Overview, '
                               'rồi bấm Tiếp tục. Nếu không có, bấm Tiếp tục để thử lại hoặc Dừng.')
                selection = self.page.evaluate('() => window.getSelection()?.toString() || ""')
                if len(selection.strip()) > 30:
                    return {'text':selection,'html':'','links':[],'sources':[], 'query':query,
                            'search_url':self.page.url,'capture':'user_selection','status':'captured'}
        return {'text':'','html':'','sources':[],'query':query,'search_url':self.page.url,'status':'no_overview'}

def enrich_google(rows, headers, fold, cache, taxonomy, progress=None, cancelled=None,
                  manual_wait=None, channel='chrome', browser_factory=GoogleBrowser,
                  connection='existing', endpoint='chrome', response_mode='overview', checkpoint=None):
    progress = progress or (lambda text: None)
    cancelled = cancelled or (lambda: False)
    evidence, audit = [], []
    checked = datetime.now(timezone(timedelta(hours=7))).strftime('%d/%m/%Y')
    folder = Path(cache)
    folder.mkdir(parents=True, exist_ok=True)
    with browser_factory(folder / 'chrome_profile', progress, cancelled, manual_wait, channel,
                         connection=connection, endpoint=endpoint, response_mode=response_mode) as browser:
        for index, row in enumerate(rows, 1):
            if cancelled():
                raise InterruptedError('Đã dừng; chưa ghi đè file công ty')
            label = 'Google Chế độ AI' if response_mode == 'ai_mode' else 'Google AI Overview'
            progress(f'{label} {index}/{len(rows)} — {row[1]}')
            entry = {'tax_id':row[27], 'company':row[1], 'pages':[], 'errors':[], 'fields_found':0, 'fields_added':[]}
            audit.append(entry)
            finished = False
            try:
                overview = browser.read(row)
                finished = True
                entry['overview'] = overview
                capture_file = folder / (re.sub(r'[^\w-]', '_', row[27]) + f'_{index:05d}.json')
                capture_file.write_text(json.dumps(overview, ensure_ascii=False, indent=2), encoding='utf-8')
                if overview['status'] != 'captured':
                    entry['errors'].append(f'{label} chưa trả nội dung đọc được')
                    row[25] += f' Chưa lấy được {label}; giữ dữ liệu raw.'
                    continue
                fields, identity = parse_overview(overview['text'], row, fold)
                entry['identity'] = identity
                entry['fields_found'] = len(fields)
                entry['pages'] = [{'url':overview['search_url'], 'matched_identity':bool(fields), 'fields':len(fields)}]
                entry['differences_from_raw'] = []
                for ci, (value, quote) in fields.items():
                    evidence.append({'tax_id':row[27], 'field':headers[ci], 'value':value,
                                     'source':overview['search_url'], 'quote':quote, 'checked_at':checked})
                    if ci == 14:
                        original = row[ci]
                        row[ci] = merge_highlights(original, value)
                        if original.strip() in {'','.','-'}:
                            entry['fields_added'].append(headers[ci])
                        elif row[ci] != original:
                            entry.setdefault('fields_enriched', []).append(headers[ci])
                    elif row[ci].strip() in {'','.','-'}:
                        row[ci] = value
                        entry['fields_added'].append(headers[ci])
                    elif fold(row[ci]) != fold(value):
                        entry['differences_from_raw'].append({'field':headers[ci], 'raw':row[ci], 'overview':value})
                entry['taxonomy_matches'] = match_taxonomy(row, taxonomy, fold)
                row[25] += f' {label} ngày {checked}: {identity}; nội dung AI chưa xác minh độc lập với website gốc.'
                if overview.get('sources'):
                    row[25] += ' Nguồn Overview trích dẫn (chưa đối chiếu): ' + '; '.join(overview['sources'][:8])
                row[24] = '; '.join(dict.fromkeys(filter(None, [*row[24].split('; '), overview['search_url']])))
                progress(f'{row[27]}: đã lấy Overview, {len(fields)} trường nhận diện, {len(entry["fields_added"])} trường điền mới. {identity}')
            except InterruptedError:
                raise
            except Exception as exc:
                finished = True
                entry['errors'].append(str(exc))
                row[25] += ' Tra cứu Google chưa thành công: ' + str(exc)
                progress(f'{row[27]}: lỗi Google — {exc}')
            finally:
                if finished and checkpoint:
                    checkpoint(rows[:index], evidence, audit)
    return rows, evidence, audit
