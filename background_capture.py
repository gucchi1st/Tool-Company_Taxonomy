"""Đọc trang và khối TSV bằng DOM, không đổi focus hay dùng clipboard."""

PAGE_TEXT_SCRIPT = r'''() => {
  const texts = [document.body?.innerText || ''];
  const turns=[...document.querySelectorAll('[data-message-author-role="assistant"], [data-turn="assistant"], .agent-turn')];
  const scope=turns.length ? turns[turns.length-1] : document;
  const blocks=[];
  function collect(root) {
    const selector='pre, .cm-content, [data-language="tsv"], [class*="language-tsv"], [role="code"]';
    for (const el of root.querySelectorAll(selector)) {
      if(el.parentElement?.closest(selector))continue;
      if (el.closest('[data-message-author-role="user"], [data-turn="user"], form, [contenteditable="true"]')) continue;
      const raw = (el.querySelector('code') || el).textContent || '';
      const text = raw.includes('\t') ? raw : (el.innerText || raw);
      if (text.includes('\t')) blocks.push(text);
    }
    for (const el of root.querySelectorAll('*')) {
      if (el.shadowRoot) collect(el.shadowRoot);
    }
  }
  collect(scope);
  if(blocks.some(text=>/STT\s*[-–]?\s*No/i.test(text))) {
    texts.push('TSV_RESPONSE_BEGIN\n'+blocks.map(text=>'TSV_BLOCK_BEGIN\n'+text+'\nTSV_BLOCK_END').join('\n')+'\nTSV_RESPONSE_END');
  }
  return texts.join('\n\n');
}'''


def read_page_text(page, cancelled=lambda:False):
    if cancelled(): raise InterruptedError('Đã dừng đọc ChatGPT')
    texts=[page.evaluate(PAGE_TEXT_SCRIPT)]
    for frame in page.frames:
        if frame == page.main_frame: continue
        if cancelled(): raise InterruptedError('Đã dừng đọc ChatGPT')
        try:
            texts.append(frame.evaluate(PAGE_TEXT_SCRIPT))
        except Exception:
            continue
    return '\n\n'.join(texts)
