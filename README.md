# Tool chuẩn hóa danh bạ công ty

Chạy bằng Python 3.10 trở lên. Luồng Google AI Overview cần Playwright; chế độ website theo quy tắc chỉ dùng thư viện chuẩn.

## Logo, lưu từng công ty và email

Đối chiếu taxonomy hỗ trợ thêm các cách diễn đạt tương đương: chăn nuôi/nuôi gia cầm, gia súc, dê/cừu… → nhánh trang trại; con giống → nhánh giống; thức ăn/phụ gia/nguyên liệu → nhánh dinh dưỡng tương ứng. Có thể điền riêng danh mục/danh mục phụ mà chưa điền sản phẩm. Chỉ mô tả rõ như gà thịt, trứng thương phẩm hoặc gia cầm giống một ngày tuổi mới đủ cho các mã sản phẩm tương ứng. Nếu nhiều nhánh cùng phù hợp, tool điền tổ tiên chung hoặc ưu tiên ngành chính chăn nuôi đã nêu rõ; không tự chọn một sản phẩm bất kỳ. Các tên có xung đột trong taxonomy vẫn ghi cảnh báo trong audit.

App dùng `logo.png` cạnh `start.bat` cho biểu tượng cửa sổ và logo ở tiêu đề. Mỗi khi tra cứu xong một công ty, tool chuẩn hóa và cập nhật ngay `companies.csv`, `companies.tsv`, `audit.json` cùng báo cáo nguồn. Ghi file thông qua tệp tạm rồi thay thế, tránh để file CSV bị ghi dở. Nếu Excel đang khóa file, tool báo cần đóng file; bản lưu trước đó giữ nguyên.

Nếu công ty có nhiều email nhận diện được, mỗi email được xuất thành một dòng, các cột khác giống nhau (STT và MST vẫn là cùng công ty). Loại trùng email không phân biệt hoa/thường; công ty không có email vẫn xuất một dòng với ô email trống. Ví dụ 1 công ty có 3 email tạo 3 dòng. Thống kê trong giao diện phân biệt số công ty đã xử lý và số dòng email xuất ra.

Nút Dừng giữ kết quả các công ty đã hoàn tất; công ty đang xử lý dở chưa được thêm. Nếu dừng trước công ty đầu tiên, file cũ không thay đổi. Lần chạy mới bắt đầu lại từ raw và chưa tự bỏ qua các công ty đã lưu; hãy dùng raw còn lại hoặc thư mục xuất khác để giữ các lô riêng.

## Mặc định hiện tại: hỏi Google Chế độ AI

Câu hỏi tra cứu đã mở rộng để làm rõ hoạt động thực tế, vai trò sản xuất/phân phối/dịch vụ, loài nuôi, mục đích nuôi, sản phẩm cụ thể, nhóm/dạng sản phẩm và nhãn hàng. Ưu tiên trang sản phẩm, catalogue và hồ sơ hiệp hội/triển lãm; yêu cầu phân biệt sản phẩm đang cung cấp với ngành đăng ký, kèm URL bằng chứng. Các chi tiết có nguồn được nối vào cột Sản phẩm tiêu biểu để đối chiếu taxonomy, kể cả khi cột đã có mô tả gốc. Giá trị Chưa xác minh không được dùng để điền mã. Tác động từ lần tra cứu mới, không tự thay nội dung các file kết quả đã lưu trước đây.

Chọn `google_ai_mode` trong tool. Sau khi kết nối Chrome profile có sẵn, tool nhập câu hỏi cho từng công ty/MST rồi bấm tab **Chế độ AI / AI Mode** trên Google. Câu hỏi yêu cầu thông tin liên hệ, email, website, lĩnh vực, sản phẩm và nguồn, theo các nhãn rõ ràng. Tool chờ câu trả lời có dấu kết thúc và ổn định rồi lấy nội dung để chuẩn hóa; không lấy cả câu hỏi hoặc danh sách kết quả tìm kiếm thông thường làm câu trả lời.

Nếu tab AI không có hoặc Google yêu cầu CAPTCHA/cookie, thao tác trong Chrome rồi bấm Tiếp tục. Nếu Google không trả lời đúng mẫu, có thể bôi đen riêng câu trả lời rồi bấm Tiếp tục. Không bảo đảm AI Mode khả dụng với mọi tài khoản hoặc lúc nào cũng nhận diện đúng DOM. Đã kiểm tra bộ lấy câu trả lời bằng Chrome với HTML cục bộ, chưa xác nhận luồng hỏi/đáp thành công trên Google thật trong phiên này. Nội dung AI vẫn cần đối chiếu nguồn; bản này chuẩn hóa bằng quy tắc, không gọi API GPT.

Các chế độ `google_overview` và `website` vẫn có thể chọn lại. Profile `existing` và endpoint `chrome` giữ nguyên.

## Luồng mặc định mới: Google AI Overview bằng Playwright

**Dùng profile Chrome có sẵn:** lựa chọn `Profile / Kết nối CDP = existing` là mặc định. Mở Chrome đúng profile đang đăng nhập Google, vào `chrome://inspect/#remote-debugging`, bật Remote Debugging. Trong tool giữ ô CDP là `chrome`, rồi chạy và chấp nhận kết nối khi Chrome hỏi. Cách tự phát hiện này cần Chrome 144+ và Playwright mới. Có thể nhập URL HTTP/WebSocket CDP nếu đã cấu hình cổng riêng. Tool không khởi động lại Chrome, không sao chép profile; chỉ mở một tab tra cứu trong phiên được kết nối và đóng tab đó khi hoàn tất. Không đóng browser/context của bạn. Remote debugging cho phép điều khiển phiên trình duyệt; tắt lại khi không dùng.

Nếu dùng nhiều profile, kiểm tra tab tra cứu được mở đúng tài khoản mong muốn. Kết nối tự động chọn browser context có sẵn đầu tiên, không tự chuyển tài khoản Google. Nếu Chrome chưa hỗ trợ hoặc chính sách máy chặn, tool báo lỗi thay vì âm thầm mở profile khác. Giới hạn cổng debug với thư mục mặc định từ Chrome 136 không có nghĩa là phải sao chép profile; dùng cơ chế cho phép kết nối của Chrome 144+ ở trên.

Mở `start.bat`; chọn `google_overview`. Tool tìm từng tên công ty + MST + thông tin liên hệ/email/lĩnh vực/sản phẩm, nhận diện AI Overview và mở rộng nội dung nếu có nút tương ứng. Không dùng GPT API/Serper cho chế độ này. Tên công ty và MST được đưa vào truy vấn Google.

Playwright đã được cài trong môi trường riêng `.venv-playwright`. Trên máy mới, chạy `setup_playwright.bat` một lần. Nếu chọn `separate`, tool mở profile riêng trong thư mục kết quả `google_overview/chrome_profile`, giữ cookie/đăng nhập thực hiện tại đó. Chrome/Edge cần cài sẵn. Nếu chọn `chromium` cho chế độ separate, cần cài browser bằng `.venv-playwright\Scripts\python.exe -m playwright install chromium`.

Khi có CAPTCHA hoặc yêu cầu chọn cookie, tool chờ bạn xử lý trực tiếp trong cửa sổ Chrome rồi nhấn **Tiếp tục sau thao tác Chrome**. Tool không tự vượt CAPTCHA. Khi chưa nhận diện Overview, bạn có thể mở rộng và bôi đen riêng phần đó rồi nhấn Tiếp tục. Nếu không có Overview, nhấn Tiếp tục để thử lại; vẫn không có thì ghi NOTE và giữ raw. Nút Dừng hủy bước chờ/tra cứu và giữ các công ty đã lưu. Đóng Chrome trong lúc chạy sẽ làm bước đang đọc báo lỗi.

Nội dung AI Overview và liên kết trích dẫn được lưu thành JSON trong `outputs/google_overview/`. Chỉ điền các trường có nhãn nhận diện được và khớp tên đầy đủ hoặc MST; không coi đoạn nhiều công ty là dữ liệu chung. Trường đã có giữ raw và ghi sai khác để đối chiếu. Contact công ty mẹ/tổng đài hoặc email bị che không tự gán cho chi nhánh. Quy tắc taxonomy vẫn đối chiếu cụm từ đã có trong raw và trường Overview trích được; chưa có GPT đọc hiểu để phân loại mọi mô tả tự do.

SOURCE chứa liên kết truy vấn Google; các liên kết gốc Overview trích dẫn ghi riêng trong NOTE/JSON. **Kết quả lấy từ AI Overview chưa được xác minh độc lập với website gốc.** Google có thể không tạo Overview hoặc thay đổi cấu trúc trang; tool không bảo đảm luôn đọc tự động được. Đã kiểm thử parser và Playwright/Chrome với HTML cục bộ; chưa xác nhận tự lấy Overview thành công trên Google thật trong phiên này.

Luồng tra cứu website trước đây vẫn có trong lựa chọn `website`. Bản GPT API độc lập trong `gpt_api/` không thay đổi.

## Tra cứu web tự động

Bản quy tắc hiện đọc thêm nội dung văn bản có nhãn (ngoài bảng HTML/JSON-LD): email, địa chỉ, ngành chính và sản phẩm. Nếu SOURCE trong raw là trang danh sách tỉnh/xã, tool đọc trang đó để tìm liên kết chứa đúng MST rồi mở hồ sơ chi tiết. Tối đa 8 trang chi tiết/công ty; URL hồ sơ trực tiếp luôn được thêm làm phương án dự phòng. Nội dung văn bản đã xác định đúng pháp nhân được lưu trong `web_research.json` để đối chiếu.

Đối chiếu taxonomy dùng cụm từ đầy đủ trong ngành/sản phẩm của raw và thông tin web đã trích, có kiểm tra cha-con. Một nhánh khớp duy nhất và không xung đột mã gốc mới được điền; nhiều nhánh chỉ ghi ứng viên trong `taxonomy_matches`. Không gán mã chỉ từ tên công ty. Trang thiếu nhãn/MST, bị chặn hoặc nội dung không nhận diện được vẫn cần rà soát. Bản GPT API trong `gpt_api/` không thay đổi.

Với chế độ `website`: mở lại `start.bat`, giữ chọn **Tìm thêm thông tin trên web**, chọn raw và nhấn **Tra cứu web và chuẩn hóa**. Tool tìm theo MST và tên công ty, lấy thông tin từ bảng/văn bản có đúng MST hoặc dữ liệu JSON-LD gắn đúng MST. Có tiến độ, lưu sau mỗi công ty và nút dừng. Raw được gửi dưới dạng truy vấn gồm tên công ty và MST tới nhà cung cấp tìm kiếm.

Có thể nhập key của Serper vào ô che ký tự, hoặc dùng biến môi trường `SERPER_API_KEY`. Khóa không lưu vào file. Khi có key, tool gọi Google Search qua Serper; tùy tài khoản có thể phát sinh phí truy vấn. Không có key thì thử Bing RSS/DuckDuckGo. Kiểm tra kết nối thực tế trong phiên này: Bing không trả kết quả đúng MST mẫu, DuckDuckGo không trả liên kết; đường miễn phí chưa được xác nhận hoạt động thành công. Đường Serper chưa được kiểm tra với key thật. Không khẳng định đã xác minh nếu chưa đọc được nguồn.

```powershell
python normalizer.py --raw data/raw.tsv --taxonomy data/taxonomy.tsv --web --search-mode website --output outputs/web
```

Ngoài CSV/TSV, chế độ web xuất `web_research.json` (URL, lỗi, sai khác với raw, trường xung đột) và `web_evidence.json` (giá trị, URL, trích đoạn, ngày kiểm tra). Cache trang công khai giữ tối đa 24 giờ trong `.web_cache` của thư mục xuất. Trường trống có các nguồn nhất quán sẽ được điền; giá trị khác raw được giữ để đối chiếu. Không tự thay người đại diện hoặc trạng thái khi nguồn khác nhau.

Bộ đọc hỗ trợ bảng thông tin doanh nghiệp, văn bản có nhãn và JSON-LD có MST. Chưa đọc được mọi bố cục website, trang cần JavaScript/đăng nhập/CAPTCHA; chưa phân tích văn bản sản phẩm tự do bằng AI. Taxonomy dùng quy tắc đối chiếu cụm từ, chưa phải mô hình AI phân loại mọi ngành. Website/email không có bằng chứng gắn đúng pháp nhân sẽ để trống.

## Bản sửa ánh xạ raw

Kết quả hiện tại trong `outputs/` là 10 công ty từ lô Hồng Nguyên đến GEPIMEX, đã ánh xạ và đối chiếu nguồn ngày 13/11/2026. Bản đầu vào lỗi được giữ trong `data/raw_tax_previous_output.csv`; dữ liệu sau rà soát nằm trong `data/raw_tax_reviewed.tsv`; hồ sơ URL và thay đổi từng trường nằm trong `data/reviewed_profiles.json` và `outputs/audit.json`.

Giao diện mặc định chọn lô đã rà soát và hiển thị đủ 32 cột. Có thể tái tạo kết quả đã rà soát bằng `python review_batch.py`; chế độ tra cứu web cho lô mới được mô tả phía trên.

Đầu vào hỗ trợ: mẫu đích 32 cột đúng thứ tự, raw có header nhận diện được (tên doanh nghiệp, MST, địa chỉ, điện thoại...), hoặc mẫu thuế 16 trường như lô vừa gửi. File XLSX đọc sheet đầu tiên; file XLS cũ cần lưu lại XLSX. Với cấu trúc chưa nhận diện, tool báo lỗi thay vì gán vị trí nhầm. MST dạng số khoa học trong mẫu thuế được chuyển bằng Decimal và đối chiếu cột MST văn bản; ngày serial Excel chỉ dùng cho ngày hoạt động nếu thiếu ngày văn bản, không tự coi là ngày cấp.

## Giao diện

```powershell
python app.py
```

Chọn raw, taxonomy, bằng chứng JSON nếu có và thư mục xuất. Nhấn **Chuẩn hóa và xuất CSV / TSV**. Giao diện có bảng xem trước và báo cáo kiểm tra. File mẫu của bạn nằm trong `data/`.

## Dòng lệnh

```powershell
python normalizer.py --raw data/raw.tsv --taxonomy data/taxonomy.tsv --evidence data/evidence.json --output outputs
python -m unittest -v
```

Raw hỗ trợ TSV, CSV hoặc XLSX với các cấu trúc mô tả ở trên; văn bản UTF-8, UTF-16 có BOM và Windows ANSI. Chấp nhận các cột trống thừa ở cuối. Các cột trống hàng trăm ô trong mẫu không được xuất.

Kết quả:

- `companies.csv`: UTF-8 BOM, đúng 32 cột.
- `companies.tsv`: cùng dữ liệu, tiện nhập vào Excel/Sheets.
- `audit.json`: lỗi mã, xung đột tên taxonomy, thay đổi số điện thoại và bằng chứng theo trường.
- `research_queue.csv`: công ty, cột còn thiếu và liên kết tìm kiếm theo MST.

Điện thoại bàn và di động được bỏ số 0 đầu theo yêu cầu; mã quốc tế như +84 giữ nguyên. MST vẫn giữ số 0 đầu. Trong Excel, dùng **Data → From Text/CSV**, đặt cột MST và mã taxonomy thành **Text**. Các giá trị có thể được Excel hiểu thành công thức được thêm dấu nháy đơn khi xuất.

## Quy tắc phân loại

Danh sách hoạt động và loài trong taxonomy là các từ điển độc lập. Chỉ quan hệ ngành → danh mục → danh mục phụ → sản phẩm được kiểm tra theo mã. Không coi loài nằm cùng dòng với sản phẩm là một ràng buộc.

Mã có tên duy nhất được bổ sung tên nếu ô tên trống. Tên khớp duy nhất được bổ sung mã. Có nhiều tên cho cùng mã thì ghi xung đột, giữ dữ liệu gốc. Có mã con sẽ bổ sung tổ tiên duy nhất còn thiếu. Mô tả đăng ký chế biến thủy sản được ánh xạ sang LV07/LV07-DM01; xung đột tên của mã này vẫn ghi audit. Không tự gán loài, danh mục phụ hay sản phẩm từ tên doanh nghiệp. Không tự gộp doanh nghiệp cùng MST hoặc chi nhánh với công ty mẹ.

NOTE ghi riêng chăn nuôi và thủy sản: **có liên quan theo dữ liệu đầu vào, chưa xác minh độc lập** hoặc **chưa đủ bằng chứng**. Chưa đủ bằng chứng không đồng nghĩa với không liên quan. Quy tắc dùng hoạt động, mô tả sản phẩm và ngành đã gán; đây là bộ lọc từ khóa bảo thủ, cần rà soát với câu phức tạp. NOTE gốc vẫn được giữ. DATE giữ ngày dữ liệu gốc; thời điểm chạy nằm trong audit, ngày đối chiếu nằm cạnh nguồn bổ sung.

## Bổ sung thông tin có nguồn

Ngoài tra cứu web tự động, mỗi dòng trong `research_queue.csv` mở truy vấn theo MST để rà soát thủ công. Đối chiếu đúng pháp nhân/chi nhánh, ưu tiên website công ty cho sản phẩm/contact; ngành nghề đăng ký chỉ là bằng chứng về đăng ký. Không lấy email/hotline của trang tra cứu làm contact công ty.

Ghi thông tin xác minh vào JSON theo mẫu `data/evidence.json`: `tax_id`, `field` (tên header chính xác), `value`, `source` (URL), `quote` (trích đoạn), `checked_at`. Sau đó chạy lại với `--evidence`. Tool chỉ điền ô trống hoặc xác nhận giá trị giống nhau; khác giá trị sẽ ghi vào audit để đối chiếu. JSON là bằng chứng do người rà soát nhập, tool không tự xác nhận nội dung URL. Thay đổi taxonomy phải sửa raw rồi chạy lại kiểm tra.

Lô mẫu ban đầu Cua Cơ Bắp/Trường Giang vẫn nằm trong `data/raw.tsv`, bằng chứng điện thoại nằm trong `data/evidence.json`. Lô đang hiển thị dùng `data/raw_tax_reviewed.tsv`. Chưa có nguồn đủ chắc để bổ sung email, website hoặc sản phẩm thương mại cụ thể cho lô này; ô thiếu được giữ trống. Các mô tả trong cột sản phẩm ghi rõ khi chỉ là ngành đăng ký.
# Tra cứu ChatGPT theo pack 10 công ty

Nếu sau 4 phút kể từ lúc gửi prompt vẫn chưa lấy đủ kết quả, tool tự mở tab ChatGPT mới và gửi lại nguyên prompt của pack hiện tại. Tool chưa chuyển sang pack kế tiếp hoặc lưu pack thiếu. Mỗi lượt thử lại tiếp tục có hạn chờ 4 phút; nút Dừng kết thúc việc chờ/thử lại và giữ các công ty đã lưu. Tab tra cứu cũ do tool tạo được đóng khi chuyển sang tab mới.

Pack được kiểm tra theo từng dòng đầu vào: tên trùng nhau được phân biệt bằng STT (STT gốc hoặc STT theo thứ tự trong pack). Ví dụ 5 dòng raw có 2 tên trùng nhau vẫn cần nhận đủ 5 bản ghi; nhiều email cùng tên và cùng STT chỉ tính một bản ghi. Sau khi nhận ChatGPT, bộ chuẩn hóa kiểm tra lại mã/tên và quan hệ cha–con theo file taxonomy đã chọn; mã không xác định được được bỏ khỏi cột phân loại và ghi vào NOTE. Taxonomy cập nhật ngày 16/11/2026 được lưu trong `data/taxonomy.tsv` và `data/taxonomy_chatgpt.tsv`; bản trước được giữ riêng trong thư mục `data`.

Khi bộ đọc DOM chưa nhận được TSV, tool đặt focus ra ngoài ô nhập rồi dùng Ctrl+A/Ctrl+C để copy toàn trang. Chỉ bảng kết quả cuối cùng có đủ tên công ty của pack mới được chuẩn hóa (pack cuối có thể dưới 10 công ty). Tên được đối chiếu không phân biệt hoa/thường, khoảng trắng và dấu câu, giữ phân biệt chi nhánh/cơ sở. Nhiều dòng email của một công ty chỉ tính một tên. MST thiếu hoặc khác trong kết quả không chặn đếm pack: code giữ MST raw và ghi khác biệt vào NOTE. Tool chờ nội dung ổn định và hết trạng thái đang tạo; thiếu công ty thì tiếp tục đợi. Nhật ký hiển thị số tên công ty đã nhận. Nội dung trang vừa copy lưu tại `chatgpt_packs/last_page_copy.txt` để rà soát. Thao tác này dùng clipboard Windows và đưa tab ChatGPT ra trước.

Mở `start.bat`, bật tra cứu web và chọn `chatgpt_pack10`. Dùng kết nối `existing` tới Chrome đã bật remote debugging như chế độ Google; đăng nhập ChatGPT trên trình duyệt đó. Chọn raw, taxonomy và thư mục lưu rồi chạy. Taxonomy mới được lưu riêng tại `data/taxonomy_chatgpt.tsv`; tool dùng file taxonomy đang chọn trong giao diện.

Mỗi lượt gửi tối đa 10 công ty cùng taxonomy vào một cuộc trò chuyện ChatGPT mới, yêu cầu tìm web, trả đúng 32 cột và NOTE về liên quan chăn nuôi/thủy sản. Chế độ này dùng tài khoản ChatGPT trên web, không dùng API key. Việc tìm web phụ thuộc tính năng/quyền và giới hạn tài khoản; bật Search trong ChatGPT khi cần. Tool không đảm bảo mọi câu trả lời đã thực sự tìm web và luôn ghi rõ nội dung AI chưa được xác minh độc lập.

Tool kiểm tra MST, số cột, mã và quan hệ taxonomy trước khi đưa kết quả qua bộ chuẩn hóa hiện có. Một công ty có nhiều email được tách thành nhiều dòng. Sau khi nhận đủ một pack hợp lệ, tool lưu lần lượt từng công ty vào CSV/TSV; dừng giữa lúc ChatGPT đang trả lời sẽ giữ các công ty đã lưu trước đó, chưa lưu pack chưa hoàn chỉnh. Prompt và câu trả lời được lưu trong `chatgpt_packs/` bên trong thư mục đầu ra để đối chiếu. Nếu JSON không hợp lệ, sửa câu trả lời trên tab ChatGPT theo thông báo rồi bấm **Tiếp tục sau thao tác Chrome** trong app.

