"""Kiểm tra trình duyệt và bộ nhận diện bằng HTML cục bộ, không gọi Google."""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
from google_overview import OVERVIEW_SCRIPT
from google_ai_mode import AI_MODE_SCRIPT
from chatgpt_pack import PACK_SCRIPT, chatgpt_composer, send_chatgpt_prompt

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        try:
            page = browser.new_page()
            page.set_content('''<main><section data-ai-overview><h2>AI Overview</h2>
                <p>CÔNG TY TNHH MỘT THÀNH VIÊN VINH LỘC</p><p>Mã số thuế: 6300226802</p>
                <p>Email: sales@example.com</p><a href="https://example.com/company">Nguồn</a></section>
                <div id="rso"><h3>Kết quả thường</h3><p>Email: unrelated@example.com</p></div></main>''')
            block = page.evaluate(OVERVIEW_SCRIPT)
            assert block and 'sales@example.com' in block['text']
            assert 'unrelated@example.com' not in block['text']
            assert len(block['links']) == 1
            print('Chrome + Playwright: local Overview extraction OK')
            page.set_content('''<main><p>Câu hỏi: hãy tra cứu công ty, không lấy nội dung câu hỏi.</p>
                <section>KET_QUA_CONG_TY_BEGIN<br>Tên công ty: CÔNG TY TNHH VINH LỘC<br>
                Mã số thuế: 6300226802<br>Email: sales@example.com<br>KET_QUA_CONG_TY_END</section>
                <a href="https://example.com/source">Nguồn</a></main>''')
            answer = page.evaluate(AI_MODE_SCRIPT)
            assert answer and 'sales@example.com' in answer['text']
            assert 'Câu hỏi:' not in answer['text']
            page.set_content('<main>KET_QUA_CONG_TY_BEGIN<br>Tên công ty: CÔNG TY TNHH VINH LỘC</main>')
            assert page.evaluate(AI_MODE_SCRIPT) is None
            print('Chrome + Playwright: local AI Mode complete-answer extraction OK')
            page.set_content('''<div data-message-author-role="user">PACK_RESULT_BEGIN bad PACK_RESULT_END</div>
                <div data-message-author-role="assistant">PACK_RESULT_BEGIN {"companies":[]} PACK_RESULT_END</div>''')
            assert page.evaluate(PACK_SCRIPT)['text'] == '{"companies":[]}'
            page.set_content('<div data-message-author-role="assistant">PACK_RESULT_BEGIN incomplete</div>')
            assert page.evaluate(PACK_SCRIPT) is None
            page.set_content('<div class="custom-answer"><pre><code></code></pre></div>')
            sample=Path('tests/fixtures/chatgpt_sample.tsv').read_text(encoding='utf-8')
            page.locator('code').evaluate('(el,text)=>el.textContent=text',sample)
            answer=page.evaluate(PACK_SCRIPT)
            assert answer and answer['text']==sample
            page.set_content('''<div data-message-author-role="user">Ignore this prompt</div>
                <div data-message-author-role="assistant"><table><tr><th>STT</th><th>Company</th></tr>
                <tr><td>1</td><td>Test company</td></tr></table></div>''')
            answer = page.evaluate(PACK_SCRIPT)
            assert answer and '|STT|Company|' in answer['text']
            assert 'Ignore this prompt' not in answer['text']
            page.set_content('<div data-message-author-role="assistant">Answer without a table</div><button data-testid="stop-button">Stop</button>')
            assert page.evaluate(PACK_SCRIPT)['streaming'] is True
            page.locator('button').evaluate('(el)=>el.remove()')
            assert page.evaluate(PACK_SCRIPT)['streaming'] is False
            page.set_content('''<main><article data-turn="user"><div class="markdown">Prompt to ignore</div></article>
              <article><div class="markdown">Company answer without author-role attribute</div>
              <button data-testid="copy-turn-action-button">Copy</button></article></main>''')
            answer=page.evaluate(PACK_SCRIPT)
            assert 'Company answer' in answer['text'] and 'Prompt to ignore' not in answer['text']
            assert answer['finished'] is True
            page.set_content('''<main><article data-turn="assistant"><pre><code>STT - No\tName\tEmail\t\n1\tCompany\ta@example.com\t</code></pre>
                <button data-testid="copy-turn-action-button">Copy</button></article></main>''')
            answer=page.evaluate(PACK_SCRIPT)
            assert answer['finished'] and '\t' in answer['text']
            assert answer['text'].endswith('\t')
            page.set_content('''<div class="custom-answer"><pre><code>STT - No\tFull Company Name\t\n1\tTest\t</code></pre></div>''')
            answer=page.evaluate(PACK_SCRIPT)
            assert answer and answer['text'].endswith('\t')
            page.set_content('''<div data-message-author-role="user"><pre><code>STT - No\tFull Company Name\t\n1\tPrompt\t</code></pre></div>''')
            assert page.evaluate(PACK_SCRIPT) is None
            print('Chrome + Playwright: local ChatGPT complete-pack extraction OK')
            page.set_content('''<textarea style="display:none"></textarea>
                <textarea id="initial"></textarea><button data-testid="send-button" disabled>Send</button>
                <script>document.querySelector('#initial').addEventListener('input', e=>{
                  const replacement=document.createElement('div');
                  replacement.id='prompt-textarea'; replacement.contentEditable='true';
                  replacement.textContent=e.target.value; e.target.replaceWith(replacement);
                  document.querySelector('button').disabled=false;
                });document.querySelector('button').onclick=()=>{
                  document.body.dataset.sent='yes';
                  const message=document.createElement('div');message.dataset.messageAuthorRole='user';
                  message.textContent='Test prompt';document.body.append(message);
                };document.addEventListener('keydown',e=>{
                  if(e.key==='Enter') {e.preventDefault();document.querySelector('button').click();}
                });</script>''')
            assert chatgpt_composer(page).get_attribute('id') == 'initial'
            page.locator('#initial').evaluate('''el=>{
                el.setAttribute('data-testid','pending-home-input');
                el.setAttribute('data-pending-input-initialized','');
                setTimeout(()=>{el.removeAttribute('data-testid');el.removeAttribute('data-pending-input-initialized');},500);
            }''')
            assert chatgpt_composer(page) is None
            page.wait_for_timeout(600)
            send_chatgpt_prompt(page,'Test prompt')
            assert page.locator('body').get_attribute('data-sent') == 'yes'
            assert chatgpt_composer(page).get_attribute('id') == 'prompt-textarea'
            print('Chrome + Playwright: ChatGPT composer rerender and hidden textarea OK')
        finally:
            browser.close()

if __name__ == '__main__':
    main()
