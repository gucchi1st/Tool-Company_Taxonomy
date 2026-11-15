# Bản chuẩn hóa dùng GPT API

Đây là bản độc lập. Không thay đổi code, start.bat hay kết quả của bản cũ. Các file đọc raw và taxonomy đã được sao chép vào thư mục này; không import code của bản cũ.

## Chạy

1. Mở `start_gpt.bat` trong thư mục này.
2. Nhập OpenAI API key vào ô che ký tự, hoặc đặt biến môi trường `OPENAI_API_KEY`. Không gửi khóa trong chat. Khóa không được lưu vào log/file cấu hình.
3. Chọn raw TSV/CSV/XLSX và taxonomy. Có sẵn bản sao dữ liệu mẫu.
4. Giữ giới hạn 10 công ty để thử, chọn model mà tài khoản có quyền sử dụng và hỗ trợ web search/Structured Outputs. Model mặc định là `gpt-6.1-terra`, có thể thay ngay trong giao diện.
5. Nhấn **GPT tìm web và chuẩn hóa**.

Chỉ dùng thư viện chuẩn Python 3.10+, không cần pip. Cần Internet tới `api.openai.com`, tài khoản API có quyền dùng model, web search và thanh toán phù hợp. Lỗi key/model/quota sẽ hiển thị rõ; không chuyển về kết quả từ raw rồi báo đã tìm web.

## Quy trình

Mỗi công ty tối đa hai yêu cầu: bước nghiên cứu bắt buộc dùng công cụ `web_search`, tối đa 3 tool call; bước thứ hai trả JSON theo schema, dựa trên nghiên cứu và toàn bộ từ điển taxonomy rút gọn. Mỗi yêu cầu giới hạn 6.000 output token. Giá trị còn thiếu được để trống. Phần tìm kiếm là OpenAI web search, không đọc Google AI Overview.

Thông tin bổ sung phải gắn URL nằm trong nguồn API thực sự trả về và có mô tả bằng chứng. Đánh giá đúng pháp nhân do mô hình thực hiện, chưa phải xác nhận độc lập của cơ quan đăng ký. Dữ liệu công ty mẹ hoặc nguồn chưa chắc chỉ vào NOTE. Thông tin web xác định đúng pháp nhân được ưu tiên; giá trị raw khác được ghi trong NOTE và audit. Tool không tự xác nhận rằng mọi thông tin trên website đều đúng.

Mã taxonomy bị giới hạn bởi danh sách cho phép trong JSON Schema, sau đó kiểm tra quan hệ cha-con. Các loài và hoạt động là từ điển độc lập. Taxonomy có mã nhiều tên thì ghi cảnh báo; tên hợp lệ cũ được ưu tiên, nếu không có thì chọn một tên trong các tên taxonomy. Không tự tạo mã mới.

Điện thoại bỏ số 0 đầu theo yêu cầu. MST giữ nguyên, kể cả MST chi nhánh. DATE giữ dữ liệu gốc; ngày tra cứu ghi trong NOTE. Đặt cột MST thành Text khi nhập CSV vào Excel.

## Kết quả và tiếp tục chạy

Mỗi lần tạo thư mục `outputs/run_...` riêng, gồm `companies.csv`, `companies.tsv`, `audit.json`, `research_queue.csv` và `research_00001.json` cho từng công ty. File nghiên cứu chứa phản hồi API, nguồn, bằng chứng, usage và ID yêu cầu; không có API key. Audit ghi thay đổi cũ/mới, lỗi, validation và token usage. Các file này có dữ liệu công ty/contact như đầu vào.

Mỗi công ty xử lý xong được lưu checkpoint. Nút dừng có hiệu lực sau công ty đang xử lý; yêu cầu đã gửi vẫn có thể phát sinh phí. Lỗi API về key/quota/model dừng lô; kết quả trước đó vẫn nằm trong thư mục run. Các lỗi nghiên cứu/JSON khác giữ dòng raw kèm NOTE lỗi để rà soát, không loại bỏ công ty.

Mặc định dùng lại cache khi raw, model và taxonomy giống hệt; cache không tự cập nhật theo thời gian. Bỏ chọn dùng lại kết quả khi muốn tra cứu mới. API có phí token và web search. Usage được lưu để đối chiếu tài khoản; tool chưa tính hóa đơn USD hoặc áp ngân sách USD cứng. Nếu timeout sau khi API nhận yêu cầu, chạy lại có thể phát sinh phí lần nữa.

## Dòng lệnh

```powershell
cd C:\python\chuanhoatax\gpt_api
python gpt_pipeline.py --raw data/raw.tsv --taxonomy data/taxonomy.tsv --limit 10
python -m unittest -v
```

## Kiểm chứng

Đã kiểm thử tự động bằng phản hồi API giả lập: bắt buộc có web search/nguồn, không lấy contact công ty mẹ vào cột của chi nhánh, kiểm tra taxonomy, giữ MST, xuất 32 cột và dùng lại cache. Chưa chạy API thật vì chưa có API key trong phiên làm việc. Việc tài khoản/model hỗ trợ đầy đủ hai yêu cầu cần kiểm tra bằng lần chạy thử đầu tiên.

Tài liệu: https://developers.openai.com/api/docs/guides/tools-web-search và https://developers.openai.com/api/docs/guides/structured-outputs
