"""Đọc nội dung HTML và đối chiếu cụm từ taxonomy, không dùng API AI."""
import re
from html.parser import HTMLParser
from urllib.parse import urlparse
from raw_import import date_text, tax_id
from email_utils import emails

DETAIL_LABELS = ['hoat dong thuc te', 'vai tro kinh doanh', 'loai hoac doi tuong',
                 'muc dich chan nuoi', 'san pham cu the', 'nhom san pham', 'dang san pham',
                 'nhan hang', 'san pham dang ky', 'bang chung hoat dong va san pham']

def merge_highlights(old, new):
    values = []
    for value in [old, new]:
        if value and value.strip() not in {'','.','-'} and value.strip() not in values:
            values.append(value.strip())
    return '; '.join(values)

class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.headings = [], []
        self.skip = 0
        self.heading = None

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style', 'nav', 'footer'}:
            self.skip += 1
        if tag in {'h1', 'h2', 'h3'} and not self.skip:
            self.parts.append('\n')
            self.heading = []
        if tag in {'p', 'div', 'li', 'dt', 'dd', 'br', 'tr', 'td', 'section'} and not self.skip:
            self.parts.append('\n')

    def handle_data(self, text):
        if not self.skip:
            self.parts.append(text)
            if self.heading is not None:
                self.heading.append(text)

    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'nav', 'footer'}:
            self.skip = max(0, self.skip - 1)
        if tag in {'h1', 'h2', 'h3'} and self.heading is not None:
            self.headings.append(' '.join(self.heading).strip())
            self.heading = None
        if tag in {'p', 'div', 'li', 'dt', 'dd', 'h1', 'h2', 'h3', 'tr', 'td', 'section'}:
            self.parts.append('\n')

def extract_text_fields(html, mst, company, fold):
    parser = VisibleText()
    parser.feed(html)
    # Xác định hồ sơ chính bằng heading chứa MST đầy đủ hoặc tên pháp nhân.
    identity = any(re.search(r'(?<!\d)' + re.escape(mst) + r'(?![\d-])', h)
                   or (company and fold(company) in fold(h)) for h in parser.headings[:3])
    lines = [re.sub(r'\s+', ' ', x).strip() for x in ''.join(parser.parts).splitlines() if x.strip()]
    if not identity:
        return {}, []
    # Heading khớp tên vẫn phải có trường MST đúng; không lấy contact công ty mẹ.
    labelled_tax = False
    for index, line in enumerate(lines):
        if re.match(r'^(ma so thue|ma so doanh nghiep|mst)\s*[:：]?$', fold(line)):
            labelled_tax = index+1 < len(lines) and tax_id(lines[index+1]) == mst
            if labelled_tax:
                break
        if re.match(r'^(ma so thue|ma so doanh nghiep|mst)\b', fold(line)) and re.search(r'(?<!\d)' + re.escape(mst) + r'(?![\d-])', line):
            labelled_tax = True
            break
    if not labelled_tax:
        return {}, []
    start = next((i for i,l in enumerate(lines) if any(l == h for h in parser.headings[:3]) and (mst in l or fold(company) in fold(l))), 0)
    scoped = []
    stop = ('ma so thue chi nhanh', 'don vi lien quan', 'doanh nghiep lien quan', 'nguoi dai dien cung',
            'tra cuu ma so thue cong ty tai', 'nhom nay gom', 'loai tru', 'co the ban quan tam')
    for line in lines[start:]:
        if any(fold(line).startswith(s) for s in stop):
            break
        scoped.append(line)
    labels = {2: ['ten quoc te', 'ten tieng anh'], 3: ['nganh nghe chinh', 'linh vuc kinh doanh chinh'],
              14: ['san pham tieu bieu', 'san pham cung cap', 'san pham', 'dich vu cung cap'] + DETAIL_LABELS,
              15: ['nguoi dai dien phap luat', 'nguoi dai dien theo phap luat', 'nguoi dai dien'],
              16: ['chuc vu', 'chuc danh'], 20: ['dia chi tru so', 'dia chi thue', 'dia chi'],
              19: ['email', 'e-mail'], 23: ['website'], 28: ['ngay cap giay phep', 'ngay cap'],
              29: ['ngay hoat dong', 'ngay bat dau hoat dong'], 30: ['tinh trang', 'trang thai'],
              18: ['dien thoai', 'so dien thoai', 'hotline', 'mobile']}
    fields = {}
    for index, line in enumerate(scoped):
        for ci, names in labels.items():
            for label in names:
                match = re.match(r'^' + re.escape(label) + r'\s*[:：]\s*(.+)$', fold(line))
                if match:
                    value = re.split(r'[:：]', line, maxsplit=1)[1].strip()
                elif fold(line).strip(' :：') == label and index+1 < len(scoped):
                    value = scoped[index+1].strip()
                else:
                    continue
                if len(value) > (4000 if ci==14 else 1000) or any(p in fold(value) for p in ['dang cap nhat', 'chua cong khai', 'chua xac minh', 'khong tim thay', 'email protected', 'chua co thong tin']):
                    continue
                if ci == 19:
                    addresses = emails(value)
                    if not addresses:
                        continue
                    value = '; '.join(addresses)
                if ci == 23 and urlparse(value).scheme not in {'http', 'https'}:
                    continue
                if ci in {28,29}:
                    value = date_text(value)
                    if not re.fullmatch(r'\d{2}/\d{2}/\d{4}', value):
                        continue
                target = ci
                if ci == 18:
                    value = re.sub(r'[\s.()-]', '', value)
                    if not re.fullmatch(r'(?:\+84|0)\d{8,11}', value):
                        continue
                    target = 17 if value.startswith(('02','+842')) or (len(value)==11 and value.startswith('0')) else 18
                if target == 14:
                    if label in DETAIL_LABELS:
                        original_label = re.split(r'[:：]', line, maxsplit=1)[0]
                        value = original_label + ': ' + value
                    previous, quote = fields.get(14, ('',''))
                    fields[14] = (merge_highlights(previous, value), merge_highlights(quote, line)[:4000])
                elif target == 19 and target in fields:
                    value = '; '.join(emails(fields[target][0] + '; ' + value))
                    fields[target] = (value, (fields[target][1] + '; ' + line)[:1000])
                else:
                    fields.setdefault(target, (value, (line + ': ' + value)[:500]))
    return fields, scoped

def match_taxonomy(row, tax, fold):
    """Chỉ so cụm từ trong mô tả ngành/sản phẩm, không dùng tên doanh nghiệp."""
    text = fold(row[3] + '; ' + row[14])
    clauses = [c for c in re.split(r'[;\n]', text)
               if not re.search(r'chua (xac minh|co bang chung)|khong (san xuat|kinh doanh)|loai tru', c)]
    text = ' '.join(clauses)
    candidates = []
    # Tìm mã sản phẩm/danh mục phụ khớp nguyên cụm; nhiều nhánh thì chỉ gợi ý.
    for mapping, ci in [(tax.maps[4],12),(tax.maps[3],10)]:
        found = set()
        for code, names in mapping.items():
            for name in names:
                phrase = fold(name.split(' / ')[0]).strip()
                if len(phrase) >= 8 and re.search(r'(?<!\w)' + re.escape(phrase) + r'(?!\w)', text):
                    found.add(code)
        if found:
            candidates.append({'column': ci, 'codes': sorted(found)})
    # Từ đồng nghĩa chỉ hướng vào mã đã có trong taxonomy. Mức rộng không
    # tự suy ra mã sản phẩm: nuôi gia cầm chỉ đủ căn cứ cho trang trại.
    primary = fold(row[3]).strip()
    semantic = []
    farm = r'(?<!an )\b(?:chan nuoi|nuoi)\s+(?:gia cam|gia suc|ga|vit|heo|lon|bo|de|cuu|huou|nai|tho)\b'
    rules = [
        (10, 'LV01-DM09-PL01', farm),
        (12, 'LV01-DM09-PL01-SP001', r'\b(?:ga|vit|heo|lon|bo|de|cuu|tho)\s+(?:thuong pham|thit)\b|\btrung thuong pham\b|\bchan nuoi lay (?:thit|sua|trung)\b'),
        (10, 'LV01-DM01-PL01', r'\b(?:ga|vit|heo|lon|bo|de|cuu|huou|nai|tho|gia cam)\s+giong\b|\bcon giong\b'),
        (12, 'LV01-DM01-PL01-SP002', r'\b(?:gia cam|ga|vit) giong (?:mot ngay|1 ngay) tuoi\b'),
        (8, 'LV01-DM02', r'\bthuc an (?:chan nuoi|gia suc|gia cam)\b'),
        (10, 'LV01-DM02-PL01', r'\bthuc an (?:hon hop )?hoan chinh\b'),
        (10, 'LV01-DM02-PL02', r'\bthuc an dam dac\b'),
        (10, 'LV01-DM02-PL03', r'\bnguyen lieu thuc an (?:chan nuoi|gia suc|gia cam)\b'),
        (10, 'LV01-DM02-PL05', r'\bphu gia thuc an\b'),
    ]
    main_farm = bool(re.search(farm, primary))
    for ci, code, pattern in rules:
        mapping = tax.maps[[4,6,8,10,12].index(ci)]
        match = re.search(pattern, text)
        if code not in mapping or not match:
            continue
        semantic.append({'column':ci, 'codes':[code], 'method':'synonym', 'evidence':match.group(), 'applied':False})
    candidates.extend(semantic)
    def path(ci, code):
        values = {ci:code}
        while ci > 4:
            parents = tax.parents.get(code, set())
            if len(parents) != 1:
                return None
            code = next(iter(parents))
            ci = {12:10, 10:8, 8:4}[ci]
            values[ci] = code
        return values
    paths = []
    for item in candidates:
        for code in item['codes']:
            values = path(item['column'], code)
            if values and not any(row[i] and row[i] not in {'.','-'} and row[i] != value for i,value in values.items()):
                paths.append((item, values))
    if main_farm:
        # Ngành chính chăn nuôi ưu tiên nhánh trang trại; phụ phẩm/hoạt động
        # phụ như thức ăn và con giống chỉ giữ làm ứng viên.
        paths = [(item, values) for item,values in paths if values.get(10)=='LV01-DM09-PL01']
    if not paths:
        return candidates
    # Chỉ điền các tổ tiên chung khi có nhiều nhánh hợp lệ.
    for ci in [4,8,10,12]:
        values = {p[ci] for _,p in paths if ci in p}
        if len(values) != 1:
            continue
        value = next(iter(values))
        parent_ci = {12:10, 10:8, 8:4}.get(ci)
        if parent_ci and any(parent_ci not in p or p[parent_ci] != row[parent_ci] for _,p in paths if ci in p):
            continue
        row[ci] = value
        names = tax.maps[[4,6,8,10,12].index(ci)][value]
        if row[ci+1] not in names:
            row[ci+1] = sorted(names)[0]
        for item,values_path in paths:
            if values_path.get(ci)==value:
                item['applied'] = True
    # Đánh dấu lý do các cấp cụ thể chưa thể điền để rà soát.
    for item in candidates:
        if not item.get('applied'):
            item['reason'] = 'Có nhiều nhánh hoặc không phù hợp ngành chính/mã gốc'
    return candidates
