"""Ánh xạ raw sang cấu trúc đích trước khi kiểm tra taxonomy."""
import re
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta

def tax_id(value):
    value = str(value).strip()
    if re.fullmatch(r'\d{10}(?:-\d{3})?', value):
        return value
    try:
        number = Decimal(value)
        if number == number.to_integral_value() and 0 <= number < 10**10:
            return str(int(number)).zfill(10)
    except InvalidOperation:
        pass
    return ''

def date_text(value):
    value = str(value).strip()
    for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%Y-%m-%d %H:%M:%S'):
        try:
            return datetime.strptime(value, fmt).strftime('%d/%m/%Y')
        except ValueError:
            pass
    if re.fullmatch(r'\d{5}(?:\.0+)?', value):
        return (datetime(1899, 12, 30) + timedelta(days=float(value))).strftime('%d/%m/%Y')
    return value

def company_name(value):
    return bool(re.match(r'(?i)^(công ty|chi nhánh|doanh nghiệp|hợp tác xã|cong ty|chi nhanh)', value.strip()))

def map_rows(raw_rows, headers, fold, allow_missing_tax=False):
    """Hỗ trợ schema đích, header raw, và schema 16 trường từ bản xuất thuế."""
    aliases = {fold(h): i for i, h in enumerate(headers)}
    for i, names in {
        0: ['stt', 'no'], 1: ['tên công ty', 'tên doanh nghiệp', 'company name', 'tên đầy đủ'],
        2: ['tên quốc tế', 'tên tiếng anh', 'international name'],
        3: ['ngành nghề', 'ngành nghề chính', 'lĩnh vực', 'hoạt động kinh doanh'],
        15: ['người đại diện', 'người đại diện pháp luật', 'contact name'],
        16: ['chức danh', 'chức vụ'], 18: ['điện thoại', 'số điện thoại', 'phone', 'mobile'],
        19: ['email'], 20: ['địa chỉ', 'địa chỉ thuế', 'address'],
        21: ['tỉnh/thành phố', 'tỉnh thành', 'tỉnh / thành phố', 'tỉnh', 'province'],
        22: ['quốc gia', 'country'], 23: ['website'], 24: ['source', 'nguồn', 'url'],
        27: ['mst', 'mã số thuế', 'tax id'], 28: ['ngày cấp', 'ngày cấp giấy phép'],
        29: ['ngày hoạt động', 'ngày bắt đầu hoạt động'], 30: ['trạng thái', 'tình trạng'],
        31: ['date', 'ngày cập nhật'],
    }.items():
        aliases.update({fold(name): i for name in names})
    header_map = None
    if raw_rows:
        candidates = {j: aliases[fold(v.strip())] for j, v in enumerate(raw_rows[0]) if fold(v.strip()) in aliases}
        if 1 in candidates.values() and 27 in candidates.values():
            header_map = candidates
            raw_rows = raw_rows[1:]
    mapped, log = [], []
    for line, raw in enumerate(raw_rows, 1):
        raw = [str(value).strip() for value in raw]
        # Nhận diện cả kết quả lỗi cũ: header đích nhưng nội dung vẫn là raw 16 trường.
        # URL có thể thiếu; tên pháp nhân có thể bắt đầu bằng Xí nghiệp,
        # Văn phòng đại diện... Dùng MST lặp lại để xác nhận đúng schema.
        raw_tax_shape = (len(raw) >= 13 and bool(raw[0]) and bool(tax_id(raw[1]))
                         and ((tax_id(raw[8]) == tax_id(raw[1]))
                              or (company_name(raw[0]) and raw[5].startswith(('http://', 'https://')))))
        known_tax_raw = bool(raw_tax_shape)
        if known_tax_raw:
            raw.extend([''] * max(0, 16 - len(raw)))
            row = [''] * 32
            row[0], row[1] = str(line), raw[0]
            row[3], row[20], row[21], row[24] = raw[2], raw[3], raw[4], raw[5]
            row[27] = tax_id(raw[8]) or tax_id(raw[1])
            if tax_id(raw[8]) and tax_id(raw[8]) != tax_id(raw[1]):
                raise ValueError(f'Dòng {line}: hai cột MST không khớp, cần đối chiếu.')
            row[29] = date_text(raw[10] or raw[6])
            row[30], row[31], row[15] = raw[11], date_text(raw[12]), raw[15]
            number = re.sub(r'[\s.()-]', '', raw[13])
            landline = number.startswith(('02', '+842', '842')) or (len(number) == 11 and number.startswith('0'))
            row[17 if landline else 18] = number
            row[22] = 'Vietnam'
            row[16] = 'Người đại diện theo dữ liệu gốc' if row[15] else ''
            log.append({'line': line, 'schema': 'raw_tax_16', 'message': 'Ánh xạ raw thuế sang 32 cột; ngày serial chỉ dùng khi thiếu ngày hoạt động; chưa suy diễn ngày cấp.'})
        elif header_map is not None:
            row = [''] * 32
            for source, target in header_map.items():
                if source < len(raw):
                    row[target] = raw[source]
            if not row[0]:
                row[0] = str(line)
            if not row[1] or (not row[27] and not allow_missing_tax):
                raise ValueError(f'Dòng {line}: thiếu tên công ty hoặc MST sau ánh xạ header.')
        else:
            raw = raw[:32] if len(raw) > 32 and not any(c.strip() for c in raw[32:]) else raw
            if len(raw) != 32 or not raw[0].strip().isdigit() or not company_name(raw[1]):
                sample = ' | '.join(f'{i+1}: {value[:100]}' for i, value in enumerate(raw[:6]))
                raise ValueError(f'Dòng {line}: chưa nhận diện được cấu trúc raw ({len(raw)} cột). '
                                 f'Cần header tên công ty/MST hoặc mẫu raw thuế.\n'
                                 f'6 ô đầu: {sample}\n'
                                 'Kiểm tra dòng này trong file nguồn; chưa xuất để tránh lệch cột.')
            row = raw
        mapped.append(row)
    return mapped, log

def classify_registered(row, taxonomy, fold):
    """Quy tắc rõ nghĩa cho hoạt động đã mô tả, không đoán sản phẩm thương mại."""
    text = fold(row[3])
    if text.strip() == 'chan nuoi gia cam':
        original = row[3]
        row[3] = 'Sản xuất / Production / Manufacturing'
        row[4] = row[4] or 'LV01'
        row[6] = row[6] or 'LO0066'
        if not row[14]:
            row[14] = 'Theo dữ liệu đăng ký: chăn nuôi gia cầm; chưa xác minh loài cụ thể, con giống, thịt hay trứng'
        return original
    if re.search(r'che bien.*(?:thuy san|hai san)', text):
        original = row[3]
        row[3] = 'Sơ chế & chế biến / Primary & Further Processing'
        row[4] = row[4] or 'LV07'
        row[8] = row[8] or 'LV07-DM01'
        if not row[9] and row[8] == 'LV07-DM01':
            row[9] = 'Chế biến thủy sản / Seafood Processing'
        if not row[14]:
            row[14] = 'Theo dữ liệu đăng ký: ' + original + '; chưa xác minh sản phẩm thương mại cụ thể'
        return original
    return None
