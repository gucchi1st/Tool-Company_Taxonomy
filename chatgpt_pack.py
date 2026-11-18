"""Tra cứu ChatGPT trên trình duyệt, tối đa 10 công ty mỗi pack."""
import json
import csv
import io
import unicodedata
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse

from google_overview import GoogleBrowser, external_links, parse_overview

PACK_SIZE=10
ANSWER_TIMEOUT_SECONDS=150
MAX_PACK_ATTEMPTS=2


class PackIncompleteError(RuntimeError):
    def __init__(self, coverage, partial_text='', attempts=MAX_PACK_ATTEMPTS):
        self.coverage=coverage
        self.partial_text=partial_text
        self.attempts=attempts
        super().__init__(f'Không đủ pack sau {attempts} lần mở tab: {coverage.get("matched",0)}/{coverage.get("total",PACK_SIZE)} công ty')

PACK_SCRIPT = r'''() => {
  const excluded = el => !!el.closest('[data-message-author-role="user"], [data-turn="user"], form, [contenteditable="true"]');
  // TSV có thể được ChatGPT render bằng code editor riêng, không có author-role.
  const snippets = [...document.querySelectorAll('pre code, pre, .cm-content, [data-language="tsv"], [class*="language-tsv"], [role="code"]')]
    .filter(el=>!excluded(el));
  const tsv = snippets.filter(el=>{
    const value=el.innerText || el.textContent || '';
    return /STT\s*[-–]?\s*No/i.test(value) && (value.includes('\t') || value.includes('Full Company Name'));
  }).pop();
  let nodes = [...document.querySelectorAll('[data-message-author-role="assistant"], [data-turn="assistant"], .agent-turn')];
  if (!nodes.length) {
    nodes = [...document.querySelectorAll('main article, main [data-testid^="conversation-turn-"]')]
      .filter(el => !el.matches('[data-turn="user"]') &&
        !el.querySelector('[data-message-author-role="user"]') &&
        (el.querySelector('[data-testid="copy-turn-action-button"], .markdown, .prose') ||
         /ChatGPT (said|đã nói)/i.test(el.getAttribute('aria-label') || '')));
  }
  if (!nodes.length) {
    nodes = [...document.querySelectorAll('main .markdown, main .prose')]
      .filter(el => !el.closest('[data-message-author-role="user"], [data-turn="user"], form, [contenteditable="true"]'));
  }
  if (!nodes.length && !tsv) return null;
  const el = nodes.length ? nodes[nodes.length-1] : tsv;
  const turn = el.closest('article, [data-testid^="conversation-turn-"], .agent-turn') || el;
  const finished = !!turn.querySelector('[data-testid="copy-turn-action-button"], [data-testid="good-response-turn-action-button"], [data-testid="bad-response-turn-action-button"], button[aria-label="Copy"], button[aria-label="Sao chép"], button[aria-label="Good response"], button[aria-label="Bad response"]');
  const selector='pre, .cm-content, [data-language="tsv"], [class*="language-tsv"], [role="code"]';
  const scope=nodes.length ? el : (tsv.closest('article, [data-testid^="conversation-turn-"], .agent-turn') || tsv.closest('pre')?.parentElement || tsv.parentElement);
  const blocks=[...scope.querySelectorAll(selector)].filter(c=>!excluded(c) && !c.parentElement?.closest(selector))
    .map(c=>{const raw=(c.querySelector('code') || c).textContent || '';return raw.includes('\t') ? raw : c.innerText;})
    .filter(value=>value.includes('\t'));
  const text = blocks.some(value=>/STT\s*[-–]?\s*No/i.test(value)) ?
    'TSV_RESPONSE_BEGIN\n'+blocks.map(value=>'TSV_BLOCK_BEGIN\n'+value+'\nTSV_BLOCK_END').join('\n')+'\nTSV_RESPONSE_END' : el.innerText;
  if (!text.trim()) return null;
  const streaming = !!document.querySelector('[data-testid="stop-button"],button[aria-label="Stop streaming"],button[aria-label="Dừng tạo"]');
  const match = text.match(/PACK_RESULT_BEGIN\s*([\s\S]*?)\s*PACK_RESULT_END/);
  if (!match) {
    const tables = [...el.querySelectorAll('table')];
    const table = tables.find(t=>t.querySelectorAll('tr')[0]?.querySelectorAll('th,td').length===32) || tables[0];
    if (!table) {
      if (text.includes('PACK_RESULT_BEGIN')) return null;
      return {text,answer:text,streaming,finished,links:[...el.querySelectorAll('a[href]')].map(a=>({url:a.href,title:a.innerText}))};
    }
    const markdown = [...table.querySelectorAll('tr')].map(tr=>'|'+[...tr.querySelectorAll('th,td')].map(td=>td.innerText.replace(/\n/g,'; ').replace(/\|/g,'\\|')).join('|')+'|').join('\n');
    return {text:markdown,answer:text,streaming,finished,links:[...el.querySelectorAll("a[href]")].map(a=>({url:a.href,title:a.innerText}))};
  }
  return {text:match[1].trim(),answer:text,streaming,finished,links:[...el.querySelectorAll('a[href]')].map(a=>({url:a.href,title:a.innerText}))};
}'''

def pack_prompt(pack, tax, headers, offset=0, raw_pack=None):
    def tsv(rows):
        return '\n'.join('\t'.join(str(v).replace('\n',' ').replace('\t',' ') for v in row) for row in rows)
    return (
        'RAW\n' + tsv(raw_pack if raw_pack is not None else pack) +
        '\n\nTAXONOMY\n' + tax.source_text +
        '\n\nĐỐI CHIẾU STT TRONG PACK (giữ đúng STT khi trả kết quả)\n' +
        tsv([[str(i+1),row[1]] for i,row in enumerate(pack)]) +
        '\n\nTìm thêm thông tin, dựa vào taxonomy chuẩn hóa theo cột\n' +
        tsv([headers]) +
        '\nNOTE đề cập liên quan hay không đến chăn nuôi, mỗi mail 1 dòng.'
        '\nƯu tiên tìm email liên hệ của từng công ty từ website chính thức và các nguồn công khai; không tự đoán email. Không tìm được thì để trống và ghi NOTE.'
        f'\nBẮT BUỘC trả đủ {len(pack)} công ty đã gửi trong pack này, không bỏ sót hoặc thêm công ty khác. '
        'Công ty chưa tìm được thông tin vẫn phải có dòng kết quả với tên và MST gốc, ghi rõ trong NOTE. '
        'Một công ty có nhiều email thì tách nhiều dòng; số công ty phải đủ, số dòng có thể nhiều hơn.'
        ' Các dòng RAW trùng tên vẫn phải trả riêng từng dòng, dùng STT theo thứ tự 1 đến số dòng trong pack; các dòng tách email giữ cùng STT.'
        '\nChỉ in kết quả TSV trực tiếp trong câu trả lời, có dòng tên cột; không tạo hoặc gửi file.'
    )


def company_key(value):
    value=unicodedata.normalize('NFD',value).casefold().replace('đ','d')
    value=''.join(c for c in value if c.isalnum() and not unicodedata.combining(c))
    for long,short in [('congtytrachnhiemhuuhan','congtytnhh'),
                       ('congtycophan','congtycp'),('motthanhvien','mtv')]:
        value=value.replace(long,short)
    if value.startswith('cty'): value='congty'+value[3:]
    return value


def group_pack_rows(rows, pack):
    groups={i:[] for i in range(len(pack))}
    ids={r[0] for r in rows}
    original_ids={r[0] for r in pack}
    local=bool(ids-original_ids) and ids <= {str(i+1) for i in range(len(pack))}
    unmatched=[]
    for row in rows:
        # STT xác định bản ghi; tên chuẩn hóa dùng để xác nhận đúng công ty.
        candidates=[i for i,r in enumerate(pack) if row[0]==(str(i+1) if local else r[0])]
        matches=[i for i in candidates if company_key(pack[i][1])==company_key(row[1])]
        if not matches:
            matches=[i for i,r in enumerate(pack) if company_key(r[1])==company_key(row[1])]
            if len(matches)>1:
                matches=[i for i in matches if i in candidates]
        if len(matches)!=1:
            unmatched.append(row)
        else:
            groups[matches[0]].append(row)
    return groups,unmatched


def complete_tsv_from_page(text, pack, diagnostic=None):
    """Lấy bảng kết quả cuối cùng; không nhận raw/taxonomy trong prompt."""
    from normalizer import HEADERS
    canonical=lambda s:re.sub(r'\s+',' ',s.strip().replace('**','')).casefold()
    expected=list(map(canonical,HEADERS))
    # Chỉ ghép block trong câu trả lời mới nhất, không ghép hai lần trả lời.
    if 'TSV_RESPONSE_BEGIN' in text:
        text=text.rsplit('TSV_RESPONSE_BEGIN',1)[1].split('TSV_RESPONSE_END',1)[0]
    blocks=re.findall(r'TSV_BLOCK_BEGIN\r?\n([\s\S]*?)\r?\nTSV_BLOCK_END',text)
    if not blocks:
        blocks=re.findall(r'```(?:tsv|text)?[^\S\r\n]*\r?\n([\s\S]*?)\r?\n```',text)
    lines=text.splitlines()
    starts=[i for i,line in enumerate(lines) if list(map(canonical,line.split('\t')))==expected]
    if not starts:
        if diagnostic is not None:
            diagnostic.update({'reason':'Chưa thấy header TSV đủ 32 cột','matched':0,'total':len(pack)})
        return None,0
    # Plain text giữ hành vi header cuối. Block đã có ranh giới câu trả lời
    # thì ghép tất cả block, kể cả block sau không nhắc lại header.
    if blocks:
        lines='\n'.join(blocks).splitlines()
        start=next(i for i,line in enumerate(lines) if list(map(canonical,line.split('\t')))==expected)
    else:
        start=starts[-1]
    rows=[]
    malformed=False
    for line in lines[start+1:]:
        if not line.strip():
            if rows and not blocks: break
            continue
        if blocks and list(map(canonical,line.split('\t')))==expected:
            continue
        cells=next(csv.reader([line],delimiter='\t'))
        if len(cells)!=32:
            if diagnostic is not None and cells[0].strip().isdigit():
                diagnostic['reason']=f'Dòng STT {cells[0]} có {len(cells)} cột, cần 32'
            malformed=bool(cells[0].strip().isdigit())
            break
        rows.append(cells)
    groups,unmatched=group_pack_rows(rows,pack)
    count=sum(bool(group) for group in groups.values())
    if diagnostic is not None:
        diagnostic.update({'matched':count,'total':len(pack),'result_rows':len(rows),
            'missing':[{'stt':i+1,'name':pack[i][1]} for i,g in groups.items() if not g],
            'unmatched':[{'stt':r[0],'name':r[1]} for r in unmatched]})
    if not rows or malformed or unmatched or count!=len(pack): return None,count
    return '\n'.join(['\t'.join(HEADERS),*['\t'.join(r) for r in rows]]),count


def parse_pack(text, pack, tax, headers, offset=0, repair_taxonomy=False):
    text = text.strip(' \r\n')
    if 'TSV_BLOCK_BEGIN' in text or len(re.findall(r'```(?:tsv|text)?[^\S\r\n]*\r?\n',text))>1:
        combined,count=complete_tsv_from_page(text,pack)
        if combined is None:
            raise ValueError(f'Các khối TSV chưa đủ pack: {count}/{len(pack)}')
        text=combined
    if 'PACK_RESULT_BEGIN' in text:
        match = re.search(r'PACK_RESULT_BEGIN\s*([\s\S]*?)\s*PACK_RESULT_END', text)
        if not match:
            raise ValueError('Câu trả lời pack chưa có dấu kết thúc')
        text = match.group(1).strip()
    fenced = re.search(r'```(?:tsv|text|json)?[^\S\r\n]*\r?\n([\s\S]*?)\r?\n```',text)
    if fenced:
        text=fenced.group(1)
    if text.lstrip().startswith('{'):
        data = json.loads(text)
    else:
        lines = [line.strip() for line in text.splitlines() if line.strip().startswith('|')]
        cells = [[v.strip().replace('<br>', '; ').replace('<br/>', '; ').replace('\\|','|') for v in re.split(r'(?<!\\)\|', line[1:-1])] for line in lines]
        cells = [row for row in cells if not all(re.fullmatch(r':?-+:?', v) for v in row)]
        if not cells and '\t' in text:
            cells = [row for row in csv.reader(io.StringIO(text),delimiter='\t') if any(v.strip() for v in row)]
        if cells:
            canonical = lambda value: re.sub(r'\s+', ' ', value.replace('**','').strip()).casefold()
            if list(map(canonical,cells[0])) == list(map(canonical,headers)):
                cells[0] = headers
        if not cells or cells[0] != headers:
            raise ValueError('Bảng kết quả chưa đúng 32 cột yêu cầu')
        if any(len(row)!=32 for row in cells[1:]):
            raise ValueError('Dòng kết quả không đủ 32 cột')
        grouped,unmatched=group_pack_rows(cells[1:],pack)
        if unmatched:
            raise ValueError('Không khớp duy nhất tên và STT công ty trong pack')
        companies = []
        for i, original in enumerate(pack):
            group = grouped[i]
            if not group:
                raise ValueError('Kết quả thiếu công ty trong pack')
            merged = list(group[0])
            for other in group[1:]:
                if any(other[j] != merged[j] for j in range(32) if j != 19):
                    raise ValueError('Các dòng cùng công ty có thông tin khác nhau ngoài email')
            merged[19] = '; '.join(dict.fromkeys(row[19] for row in group if row[19]))
            if merged[27] != original[27]:
                merged[25] += f' MST ChatGPT trả về: {merged[27] or "trống"}; giữ MST raw: {original[27]}.'
                merged[27] = original[27]
            companies.append({'input_id':offset+i,'tax_id':original[27],'values':merged})
        data = {'headers':headers,'companies':companies}
    if not isinstance(data,dict) or data.get('headers') != headers:
        raise ValueError('ChatGPT trả header khác 32 cột yêu cầu')
    items = data.get('companies')
    if not isinstance(items,list) or len(items)!=len(pack):
        raise ValueError('Số công ty trả về không đúng pack')
    by_id = {}
    for item in items:
        if not isinstance(item,dict) or type(item.get('input_id')) is not int or item['input_id'] in by_id:
            raise ValueError('input_id thiếu/trùng trong pack')
        by_id[item['input_id']] = item
    if set(by_id) != set(range(offset,offset+len(pack))):
        raise ValueError('ChatGPT trả input_id không thuộc pack')
    result = []
    for i,original in enumerate(pack):
        item = by_id[offset+i]
        row = item.get('values')
        if item.get('tax_id')!=original[27] or not isinstance(row,list) or len(row)!=32 or not all(isinstance(x,str) for x in row):
            raise ValueError(f'{original[27]}: sai MST hoặc không đủ 32 giá trị chuỗi')
        if row[27]!=original[27]:
            raise ValueError(f'{original[27]}: MST tại cột 28 không đúng raw')
        row = [value.strip() if value.strip() not in {'.','-'} else '' for value in row]
        if repair_taxonomy:
            from taxonomy_cleanup import cleanup_taxonomy
            from normalizer import folded
            cleanup_taxonomy(row,tax,folded)
        for ci,mapping in zip([4,6,8,10,12],tax.maps):
            code = row[ci]
            if code and code not in mapping:
                raise ValueError(f'{original[27]}: mã ngoài taxonomy {code}')
            if code:
                names = mapping[code]
                row[ci+1] = row[ci+1] if row[ci+1] in names else sorted(names)[0]
            elif row[ci+1]:
                matches = [key for key,names in mapping.items() if row[ci+1] in names]
                if len(matches)==1:
                    row[ci] = matches[0]
                else:
                    raise ValueError(f'{original[27]}: tên taxonomy không có mã duy nhất')
        for child,parent in [(12,10),(10,8),(8,4)]:
            if row[child]:
                parents = tax.parents.get(row[child],set())
                if not row[parent] and len(parents)==1:
                    row[parent]=next(iter(parents))
                    names=tax.maps[[4,6,8,10,12].index(parent)][row[parent]]
                    row[parent+1]=sorted(names)[0]
                elif row[parent] not in parents:
                    raise ValueError(f'{original[27]}: sai quan hệ taxonomy {row[child]} → {row[parent]}')
        activities=[]
        for activity in filter(None,map(str.strip,row[3].split(';'))):
            if activity not in tax.activities:
                label, separator, detail=activity.partition(':')
                if separator and label.strip() in tax.activities:
                    activities.append(label.strip())
                    if detail.strip():
                        row[14]='; '.join(dict.fromkeys(filter(None,[row[14],detail.strip()])))
                else:
                    raise ValueError(f'{original[27]}: hoạt động chưa theo nhãn taxonomy: {activity}')
            else:
                activities.append(activity)
        row[3]='; '.join(dict.fromkeys(activities))
        for ci in [0,1,27,31]:
            row[ci]=original[ci]
        result.append(row)
    return result


def extract_research(text, pack, fold):
    """Đọc thông tin tự do theo từng pháp nhân, để normalize gán taxonomy sau."""
    compact = lambda value: re.sub(r'[^a-z0-9]', '', fold(value))
    sections = [[] for _ in pack]
    current = None
    for line in text.splitlines():
        names = [i for i,row in enumerate(pack) if compact(row[1]) and compact(row[1]) in compact(line)]
        ids = [i for i,row in enumerate(pack) if row[27] and re.search(r'(?<!\d)'+re.escape(row[27])+r'(?![\d-])',line)]
        matches = names or ids
        if len(matches) == 1:
            current = matches[0]
        elif len(matches)>1:
            current = None
        if current is not None:
            sections[current].append(line)
    result = []
    for original,lines in zip(pack,sections):
        row = list(original)
        block = '\n'.join(lines).replace('**','')
        fields, identity = parse_overview(block, original, fold) if block else ({},'Không tách được thông tin riêng của công ty')
        for ci,(value,quote) in fields.items():
            if ci in {0,1,27,31} or ci in range(4,14):
                continue
            if ci in {3,14,19,24}:
                row[ci] = '; '.join(dict.fromkeys(filter(None,[row[ci],value])))
            elif value:
                row[ci] = value
        row[25] += ' ' + identity + '; code trích xuất từ nội dung ChatGPT.'
        if not fields:
            row[25] += ' Chưa trích xuất được trường bổ sung; giữ dữ liệu raw để rà soát.'
        result.append(row)
    return result

def chatgpt_composer(page):
    # Snapshot DOM: no locator retry against a textarea React has removed.
    handle=page.evaluate_handle(r'''() => {
      const selectors=['#prompt-textarea[contenteditable="true"]',
        '[contenteditable="true"][role="textbox"]','[contenteditable="true"].ProseMirror',
        'textarea#prompt-textarea','textarea'];
      for (const selector of selectors) {
        for (const el of document.querySelectorAll(selector)) {
          if (!el.isConnected || el.disabled || el.readOnly || !el.getClientRects().length ||
              getComputedStyle(el).visibility==='hidden' ||
              el.hasAttribute('data-pending-input-initialized') ||
              el.getAttribute('data-testid')==='pending-home-input') continue;
          return el;
        }
      }
      return null;
    }''')
    element=handle.as_element()
    if element is None: handle.dispose()
    return element


def send_chatgpt_prompt(page, prompt, cancelled=lambda:False):
    if cancelled():
        raise InterruptedError('Stopped')
    box=chatgpt_composer(page)
    if box is None:
        raise RuntimeError('ChatGPT input is not ready')
    focused=box.evaluate('(el)=>{if(!el.isConnected)return false;el.focus();return document.activeElement===el;}')
    if not focused:
        box=chatgpt_composer(page)
        if box is None or not box.evaluate('(el)=>{el.focus();return document.activeElement===el;}'):
            raise RuntimeError('ChatGPT input changed; please wait for the page to finish loading')
    page.keyboard.press('Control+a')
    page.keyboard.insert_text(prompt)
    page.wait_for_timeout(500)
    if cancelled():
        raise InterruptedError('Stopped')
    page.keyboard.press('Enter')


class ChatGPTBrowser(GoogleBrowser):
    answer_timeout=ANSWER_TIMEOUT_SECONDS

    def ask_pack(self, prompt):
        retries=0
        while True:
            if self.cancelled(): raise InterruptedError('Đã dừng ChatGPT')
            self.last_capture_text=''
            self.last_coverage={'matched':0,'total':len(getattr(self,'expected_rows',[])) or PACK_SIZE}
            self._submit_pack(prompt)
            try:
                return self.wait_answer()
            except TimeoutError:
                if self.cancelled(): raise InterruptedError('Đã dừng ChatGPT')
                retries+=1
                if retries>=MAX_PACK_ATTEMPTS:
                    raise PackIncompleteError(self.last_coverage,self.last_capture_text,retries)
                self.progress(f'Sau 2 phút 30 giây chưa lấy đủ pack. Mở trang ChatGPT mới và gửi lại đúng pack hiện tại (lần thử lại {retries}).')
                old_page=self.page
                self.page=self.context.new_page()
                self.page.set_default_timeout(4000)
                # Chỉ đóng tab tra cứu do tool tạo, không đóng tab cá nhân.
                if not old_page.is_closed():
                    old_page.close()

    def _submit_pack(self, prompt):
        page=self.page
        self.progress(f'Mở cuộc trò chuyện ChatGPT mới và gửi pack {PACK_SIZE} công ty hoặc ít hơn')
        page.goto('https://chatgpt.com/',wait_until='domcontentloaded',timeout=45000)
        def composer():
            return chatgpt_composer(page)
        deadline=time.monotonic()+15
        box=composer()
        while box is None and time.monotonic()<deadline:
            if self.cancelled(): raise InterruptedError('Đã dừng ChatGPT')
            page.wait_for_timeout(500)
            box=composer()
        if box is None:
            self.wait_user('Đăng nhập ChatGPT hoặc xử lý yêu cầu trên tab ChatGPT, mở chat mới rồi bấm Tiếp tục.')
            box=composer()
        if box is None:
            raise RuntimeError('Chưa tìm được ô nhập ChatGPT')
        send_chatgpt_prompt(page,prompt,self.cancelled)
        self.progress('Đã dán prompt và nhấn Enter, đang chờ ChatGPT trả lời.')

    def wait_answer(self):
        last,stable='',0
        next_read=0
        background_answer=None
        next_log=time.monotonic()+15
        self.progress('Đang chờ và đọc câu trả lời ChatGPT…')
        for attempt in range(1):
            deadline=time.monotonic()+self.answer_timeout
            while time.monotonic()<deadline:
                if self.cancelled(): raise InterruptedError('Đã dừng chờ ChatGPT; pack trước đã được lưu')
                if self.page.is_closed(): raise RuntimeError('Tab ChatGPT đã đóng')
                answer=self.page.evaluate(PACK_SCRIPT)
                # Một số phiên ChatGPT đặt nội dung trong frame.
                if not answer:
                    for frame in self.page.frames:
                        if frame == self.page.main_frame: continue
                        try:
                            answer=frame.evaluate(PACK_SCRIPT)
                        except Exception:
                            continue
                        if answer: break
                if not answer and getattr(self,'expected_rows',None):
                    # Cho phép lấy lại kết quả nếu ChatGPT mở câu trả lời ở tab khác.
                    for candidate in self.context.pages:
                        if candidate == self.page or candidate.is_closed() or urlparse(candidate.url).hostname not in {'chatgpt.com','chat.openai.com'}:
                            continue
                        try:
                            found=candidate.evaluate(PACK_SCRIPT)
                            if not found: continue
                            if not complete_tsv_from_page(found['text'],self.expected_rows)[0]:
                                continue
                            answer=found
                            answer['chat_url']=candidate.url
                            break
                        except Exception:
                            continue
                expected=getattr(self,'expected_rows',None)
                if expected:
                    if answer:
                        self.last_capture_text=answer['text']
                        coverage={}
                        candidate_text,count=complete_tsv_from_page(answer['text'],expected,coverage)
                        self.last_coverage=coverage
                    else:
                        candidate_text,count=None,0
                    if candidate_text:
                        answer['text']=candidate_text
                    else:
                        answer=None
                    if not answer and time.monotonic()>=next_read:
                        from background_capture import read_page_text
                        try:
                            page_text=read_page_text(self.page,self.cancelled)
                            self.last_capture_text=page_text
                            self.profile.parent.mkdir(parents=True,exist_ok=True)
                            (self.profile.parent/'last_page_read.txt').write_text(page_text,encoding='utf-8')
                            diagnostic={}
                            tsv,count=complete_tsv_from_page(page_text,expected,diagnostic)
                            self.last_coverage=diagnostic
                            self.progress(f'Đọc nền: đã nhận {count}/{len(expected)} dòng công ty theo tên và STT; chỉ chuẩn hóa khi đủ pack.')
                            if diagnostic.get('missing'):
                                self.progress('Chưa khớp: '+'; '.join(f'{item["stt"]}. {item["name"]}' for item in diagnostic['missing']))
                            if diagnostic.get('reason'):
                                self.progress(diagnostic['reason'])
                            (self.profile.parent/'pack_coverage.json').write_text(json.dumps(diagnostic,ensure_ascii=False,indent=2),encoding='utf-8')
                            background_answer={'text':tsv,'answer':tsv,'links':[],'finished':False} if tsv else None
                        except InterruptedError:
                            raise
                        except Exception as exc:
                            background_answer=None
                            self.progress(f'Chưa đọc được trang ChatGPT: {exc}')
                        next_read=time.monotonic()+5
                    if not answer and background_answer:
                        answer=dict(background_answer)
                        answer['streaming']=self.page.evaluate('''()=>[...document.querySelectorAll('[data-testid="stop-button"],button[aria-label="Stop streaming"],button[aria-label="Dừng tạo"]')].some(el=>el.getClientRects().length)''')
                if answer:
                    if answer['text']==last: stable+=1
                    else: last,stable=answer['text'],0
                    if stable>=(3 if answer.get('finished') else 15) and not answer.get('streaming'):
                        answer.setdefault('chat_url',self.page.url)
                        answer['sources']=external_links(answer['links'])
                        self.progress(f'Đã lấy câu trả lời ChatGPT ({len(answer["text"])} ký tự), đang kiểm tra và chuẩn hóa.')
                        return answer
                else:
                    last,stable='',0
                if time.monotonic()>=next_log:
                    self.progress('Đã thấy nội dung ChatGPT, chờ trả lời hoàn tất…' if answer else 'Chưa đọc được câu trả lời trên tab ChatGPT đang tra cứu…')
                    if not answer:
                        try:
                            self.profile.parent.mkdir(parents=True,exist_ok=True)
                            (self.profile.parent/'unread_chatgpt.html').write_text(self.page.content(),encoding='utf-8')
                            diagnostic=self.page.evaluate('''()=>({url:location.href,assistant:document.querySelectorAll('[data-message-author-role="assistant"]').length,code:document.querySelectorAll('pre,code,.cm-content').length})''')
                            self.progress('Chẩn đoán tab: '+json.dumps(diagnostic,ensure_ascii=False))
                        except Exception:
                            pass
                    next_log=time.monotonic()+15
                self.page.wait_for_timeout(800)
        raise TimeoutError('Sau 2 phút 30 giây chưa lấy đủ kết quả ChatGPT của pack hiện tại')

def enrich_chatgpt(rows, headers, fold, cache, taxonomy, progress=None, cancelled=None,
                   manual_wait=None, channel='chrome', connection='existing', endpoint='chrome',
                   checkpoint=None, browser_factory=ChatGPTBrowser, raw_rows=None):
    progress=progress or (lambda message:None)
    cancelled=cancelled or (lambda:False)
    folder=Path(cache)
    folder.mkdir(parents=True,exist_ok=True)
    evidence,audit,completed=[],[],[]
    checked=datetime.now(timezone(timedelta(hours=7))).strftime('%d/%m/%Y')
    with browser_factory(folder/'chrome_profile',progress,cancelled,manual_wait,channel,
                         connection=connection,endpoint=endpoint) as browser:
        for offset in range(0,len(rows),PACK_SIZE):
            if cancelled(): raise InterruptedError('Đã dừng ChatGPT')
            pack=rows[offset:offset+PACK_SIZE]
            pack_no=offset//PACK_SIZE+1
            prompt=pack_prompt(pack,taxonomy,headers,offset,
                raw_pack=raw_rows[offset:offset+PACK_SIZE] if raw_rows is not None else None)
            (folder/f'pack_{pack_no:05d}_prompt.txt').write_text(prompt,encoding='utf-8')
            progress(f'ChatGPT pack {pack_no}: {len(pack)} công ty, dòng {offset+1}–{offset+len(pack)}')
            browser.expected_rows=pack
            try:
                answer=browser.ask_pack(prompt)
            except PackIncompleteError as exc:
                reason=f'BỎ QUA TRA CỨU: pack {pack_no}; {exc}. Giữ dữ liệu raw, cần tra cứu lại.'
                (folder/f'pack_{pack_no:05d}_skipped.json').write_text(json.dumps({
                    'status':'skipped','pack':pack_no,'attempts':exc.attempts,
                    'coverage':exc.coverage,'reason':reason,
                    'companies':[{'stt':r[0],'name':r[1],'tax_id':r[27]} for r in pack],
                    'partial_text':exc.partial_text},ensure_ascii=False,indent=2),encoding='utf-8')
                for original in pack:
                    if cancelled(): raise InterruptedError('Đã dừng; các dòng đã lưu vẫn được giữ')
                    row=list(original)
                    row[25]=' '.join(filter(None,[row[25],reason]))
                    completed.append(row)
                    audit.append({'tax_id':row[27],'pack':pack_no,'status':'skipped',
                        'attempts':exc.attempts,'fields_found':0,'fields_added':[],
                        'pages':[],'errors':[reason],'sources':[],'changes':[]})
                    if checkpoint: checkpoint(completed,evidence,audit)
                progress(reason+' Chuyển sang pack kế tiếp.')
                continue
            for attempt in range(2):
                (folder/f'pack_{pack_no:05d}_response.json').write_text(json.dumps(answer,ensure_ascii=False,indent=2),encoding='utf-8')
                try:
                    parsed=parse_pack(answer['text'],pack,taxonomy,headers,offset,repair_taxonomy=True)
                    break
                except (ValueError,TypeError,KeyError) as exc:
                    progress('Code đang trích xuất thông tin từ câu trả lời tự do và chuẩn hóa lại theo taxonomy.')
                    parsed=extract_research(answer.get('answer') or answer['text'],pack,fold)
                    break
            for original,row in zip(pack,parsed):
                if cancelled(): raise InterruptedError('Đã dừng; các công ty đã hoàn tất vẫn được lưu')
                sources=[s.strip() for s in row[24].split(';') if urlparse(s.strip()).scheme in {'http','https'}]
                changed=[headers[i] for i in range(32) if row[i]!=original[i]]
                added=[headers[i] for i in range(32) if not original[i].strip(' .-') and row[i]]
                if 'chan nuoi' not in fold(row[25]):
                    row[25]+=' Chăn nuôi: chưa đủ bằng chứng trong câu trả lời.'
                row[25]+=f' ChatGPT trình duyệt pack {pack_no}, ngày {checked}; nội dung AI chưa xác minh độc lập với website gốc.'
                if not sources:
                    row[25]+=' Chưa có URL nguồn hợp lệ trong kết quả.'
                row[24]='; '.join(dict.fromkeys([*sources,answer['chat_url']]))
                completed.append(row)
                audit.append({'tax_id':row[27],'pack':pack_no,'fields_found':len(changed),'fields_added':added,
                    'pages':[{'url':answer['chat_url'],'matched_identity':True,'fields':len(changed)}],
                    'errors':[] if sources else ['ChatGPT chưa trả URL nguồn hợp lệ'],
                    'sources':sources,'changes':[{'field':headers[i],'raw':original[i],'chatgpt':row[i]}
                        for i in range(32) if row[i]!=original[i]]})
                if checkpoint: checkpoint(completed,evidence,audit)
                progress(f'Đã chuẩn hóa ChatGPT: {row[27]} ({len(completed)}/{len(rows)} công ty)')
    return completed,evidence,audit
