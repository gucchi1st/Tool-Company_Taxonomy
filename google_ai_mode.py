"""Hỏi Google AI Mode trên trình duyệt đã kết nối, nhận câu trả lời có nhãn."""
import re
import time
from urllib.parse import quote_plus

AI_MODE_SCRIPT = r'''() => {
  const roots = [...document.querySelectorAll('main,[role="main"]')];
  for (const root of roots) {
    const text = root.innerText;
    const regex = /(?:^|\n)KET_QUA_CONG_TY_BEGIN\s*\n([\s\S]*?)\n\s*KET_QUA_CONG_TY_END(?:\s|$)/g;
    const matches = [...text.matchAll(regex)];
    if (!matches.length) continue;
    const answer = matches[matches.length-1][1].trim();
    if (!/Mã số thuế\s*:/i.test(answer) || !/Tên công ty\s*:/i.test(answer)) continue;
    return {text:answer, html:'',links:[...root.querySelectorAll('a[href]')].map(a=>({url:a.href,title:a.innerText})),capture:'ai_mode_markers'};
  }
  return null;
}'''

def build_question(row):
    missing = ', '.join(label for index,label in [(8,'danh mục'),(10,'danh mục phụ'),(12,'sản phẩm/giải pháp')]
                        if row[index].strip() in {'','.','-'}) or 'kiểm chứng phân loại hiện có'
    return (f'Tra cứu duy nhất doanh nghiệp {row[1]}, mã số thuế {row[27]}, địa phương {row[21]}. '
        'Tìm thông tin liên hệ, email, website chính thức, lĩnh vực, hoạt động và sản phẩm từ nguồn web. '
        'Đối chiếu đúng MST và chi nhánh; không lấy contact công ty mẹ hoặc hotline/email của website tra cứu. '
        'Không suy đoán; thông tin không tìm thấy ghi Chưa xác minh. Dẫn liên kết nguồn. '
        f'Cần thêm căn cứ để xác định {missing}. Tìm kỹ hoạt động thực tế và danh mục sản phẩm từ '
        'website chính thức, trang sản phẩm, catalogue, hồ sơ triển lãm hoặc hiệp hội. '
        'Phân biệt ngành nghề đăng ký với sản phẩm thực sự đang cung cấp; không lấy mô tả chung VSIC làm sản phẩm. '
        'Nêu loài/đối tượng nuôi cụ thể; mục đích nuôi giống, nuôi thịt, sữa, trứng hay dịch vụ. '
        'Nếu có nguồn xác nhận, làm rõ giống một ngày tuổi, giống bố mẹ, hậu bị; thức ăn hoàn chỉnh, đậm đặc, '
        'nguyên liệu hay phụ gia; máy móc, thiết bị, thuốc thú y hoặc giải pháp kỹ thuật cụ thể. '
        'Nêu tên sản phẩm/nhãn hàng, dạng sản phẩm và vai trò công ty: sản xuất, nuôi, phân phối, xuất nhập khẩu '
        'hay cung cấp dịch vụ. Mỗi nhận định về sản phẩm/hoạt động phải có URL bằng chứng; chưa tìm được thì ghi Chưa xác minh. '
        'Trả lời văn bản từng dòng, không dùng bảng, không Markdown. '
        'Mở đầu bằng dòng riêng KET_QUA_CONG_TY_BEGIN, kết thúc bằng dòng riêng KET_QUA_CONG_TY_END. '
        'Các nhãn bắt buộc: Tên công ty:; Mã số thuế:; Tên quốc tế:; Địa chỉ:; Người đại diện:; '
        'Chức danh:; Điện thoại:; Email:; Website:; Ngành nghề chính:; Hoạt động thực tế:; '
        'Vai trò kinh doanh:; Loài hoặc đối tượng:; Mục đích chăn nuôi:; Sản phẩm:; '
        'Sản phẩm cụ thể:; Nhóm sản phẩm:; Dạng sản phẩm:; Nhãn hàng:; '
        'Sản phẩm đăng ký:; Bằng chứng hoạt động và sản phẩm:; '
        'Ngày cấp:; Ngày hoạt động:; Trạng thái:; Liên quan chăn nuôi:; Liên quan thủy sản:; Nguồn:. '
        f'MST cần đối chiếu là {row[27]}.')

def read_ai_mode(browser, row):
    from google_overview import external_links
    question = build_question(row)
    page = browser.page
    browser.progress('Hỏi Google Chế độ AI: ' + row[1])
    page.goto('https://www.google.com/search?hl=vi&q=' + quote_plus(question), wait_until='domcontentloaded', timeout=45000)
    # Bấm đúng tab AI Mode trên trang Google, lấy URL thực tế thay vì tự dựng endpoint.
    ai_tab = page.get_by_role('link', name=re.compile(r'^(Chế độ AI|AI Mode)$', re.I))
    if ai_tab.count() and ai_tab.first.is_visible():
        ai_tab.first.click(timeout=10000)
    else:
        browser.wait_user('Chưa thấy tab Chế độ AI. Hãy chọn Chế độ AI trong Google, xử lý cookie/CAPTCHA nếu có rồi bấm Tiếp tục.')
    last = ''
    stable = 0
    for attempt in range(2):
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if browser.cancelled():
                raise InterruptedError('Đã dừng Google Chế độ AI')
            if page.is_closed():
                raise RuntimeError('Tab Chế độ AI đã đóng')
            body = page.locator('body').inner_text(timeout=4000)
            if '/sorry/' in page.url or re.search(r'unusual traffic|lưu lượng truy cập bất thường|verify you are human', body,re.I):
                browser.wait_user('Google yêu cầu CAPTCHA. Xử lý trong Chrome rồi bấm Tiếp tục.')
                deadline = time.monotonic()+90
                continue
            block = page.evaluate(AI_MODE_SCRIPT)
            if block:
                if block['text'] == last:
                    stable += 1
                else:
                    last, stable = block['text'], 0
                if stable >= 3:
                    block.update({'query':question,'search_url':page.url,'sources':external_links(block['links']),
                                  'status':'captured','mode':'ai_mode'})
                    return block
            page.wait_for_timeout(700)
        if attempt == 0:
            browser.wait_user('Chế độ AI chưa trả kết quả đúng mẫu. Nếu đã có câu trả lời, bôi đen riêng câu trả lời '
                              'rồi bấm Tiếp tục; nếu chưa có hãy chờ Google trả lời. Có thể bấm Dừng để hủy.')
            selected = page.evaluate('() => window.getSelection()?.toString() || ""')
            if len(selected.strip()) > 50:
                return {'text':selected,'html':'','links':[],'sources':[],'query':question,
                        'search_url':page.url,'capture':'user_selection','mode':'ai_mode','status':'captured'}
    return {'text':'','html':'','sources':[],'query':question,'search_url':page.url,'mode':'ai_mode','status':'no_answer'}
