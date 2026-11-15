import unittest
import tempfile
import zipfile
from pathlib import Path
from normalizer import Taxonomy, normalize, table, phone, HEADERS, csv_text, read_input

class NormalizerTests(unittest.TestCase):
    def test_product_evidence_enriches_existing_description(self):
        from normalizer import HEADERS, csv_text
        row = table(self.raw)[0]
        row[14] = 'Mô tả sản phẩm gốc'
        ev = [{'tax_id':row[27], 'field':HEADERS[14], 'value':'Sản phẩm cụ thể đã tra cứu',
               'source':'https://example.com/products', 'quote':'Sản phẩm cụ thể đã tra cứu', 'checked_at':'15/11/2026'}]
        rows, _ = normalize(csv_text([row], delimiter='\t'), self.tax, ev)
        self.assertIn('Mô tả sản phẩm gốc', rows[0][14])
        self.assertIn('Sản phẩm cụ thể đã tra cứu', rows[0][14])

    def test_tax_schema_missing_url_and_nonstandard_company_name(self):
        raw = ['XÍ NGHIỆP CHĂN NUÔI TEST', '3600224423-020', 'Chăn nuôi gia cầm',
               'Phường Trung An', 'Đồng Tháp', '', '30/05/2001', '',
               '3600224423-020', '.', '30/05/2001', 'Đang hoạt động', '10/11/2026']
        rows, _ = normalize('\t'.join(raw), self.tax)
        self.assertEqual(rows[0][1], raw[0])
        self.assertEqual(rows[0][4], 'LV01')
        self.assertEqual(rows[0][6], 'LO0066')

    def test_tax_raw_mapping_and_scientific_tax_id(self):
        raw = ['CÔNG TY TNHH THỦY SẢN NHẬT HẠ', '1.900694401E9',
               'Chế biến, bảo quản thuỷ sản và các sản phẩm từ thuỷ sản',
               'Xã Phong Thạnh', 'Cà Mau', 'https://example.com/source',
               '45482.0', '', '1900694401', '', '09/07/2024', 'Đang hoạt động',
               '10/11/2026', '0947 744 474', '', 'TRẦN TRÍ LINH']
        rows, report = normalize('\t'.join(raw), self.tax)
        row = rows[0]
        self.assertEqual(row[0], '1')
        self.assertEqual(row[1], raw[0])
        self.assertEqual(row[27], '1900694401')
        self.assertEqual(row[18], '947744474')
        self.assertEqual(row[29], '09/07/2024')
        self.assertEqual(row[28], '')
        self.assertEqual(row[4], 'LV07')
        self.assertEqual(row[8], 'LV07-DM01')
        self.assertIn('Thủy sản: có liên quan', row[25])
        self.assertEqual(report['import_log'][0]['schema'], 'raw_tax_16')

    def test_wrong_32_column_shape_cannot_pass_as_target(self):
        with self.assertRaises(ValueError):
            normalize('\t'.join(['CÔNG TY TNHH TEST', '1234567890'] + [''] * 30), self.tax)

    def test_header_mapping(self):
        rows, _ = normalize('MST\tTên doanh nghiệp\tEmail\n0318606226\tCÔNG TY TNHH TEST\tcontact@example.com', self.tax)
        self.assertEqual(rows[0][27], '0318606226')
        self.assertEqual(rows[0][1], 'CÔNG TY TNHH TEST')
        self.assertEqual(rows[0][19], 'contact@example.com')

    def test_input_encodings_and_excel(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.tsv'
            for encoding, text in [('utf-8-sig', 'Công ty'), ('utf-16', 'Công ty'), ('cp1252', 'Company • contact')]:
                path.write_bytes(text.encode(encoding))
                self.assertEqual(read_input(path), text)
            path = Path(directory) / 'input.xlsx'
            with zipfile.ZipFile(path, 'w') as book:
                book.writestr('xl/workbook.xml', '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Data" sheetId="1" r:id="rId1"/></sheets></workbook>')
                book.writestr('xl/_rels/workbook.xml.rels', '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
                book.writestr('xl/worksheets/sheet1.xml', '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Công ty</t></is></c><c r="AB1" t="inlineStr"><is><t>0312345678</t></is></c></row></sheetData></worksheet>')
            rows = table(read_input(path))
            self.assertEqual(rows[0][0], 'Công ty')
            self.assertEqual(rows[0][27], '0312345678')
            self.assertEqual(len(rows[0]), 32)

    @classmethod
    def setUpClass(cls):
        cls.tax = Taxonomy(Path('data/taxonomy.tsv').read_text(encoding='utf-8-sig'))
        cls.raw = Path('data/raw.tsv').read_text(encoding='utf-8-sig')

    def test_sample_preserves_rows_and_branch_ids(self):
        rows, report = normalize(self.raw, self.tax)
        self.assertEqual(len(rows), 10)
        self.assertTrue(all(len(row) == 32 for row in rows))
        self.assertEqual(rows[1][27], '3500798216-001')
        self.assertEqual(rows[3][18], '384111441')
        self.assertEqual(rows[-1][17], '2773761356')
        self.assertEqual(rows[0][31], '10/11/2026')
        self.assertTrue(report['taxonomy_conflicts'])

    def test_bad_shape_rejected(self):
        with self.assertRaises(ValueError):
            normalize('1\tExample', self.tax)

    def test_does_not_infer_species_from_taxonomy_row(self):
        rows, _ = normalize(self.raw, self.tax)
        self.assertEqual(rows[0][6], 'LO0000')
        self.assertFalse(rows[0][12])

    def test_conflicting_evidence_not_overwritten(self):
        ev = [{'tax_id': '2100688337', 'field': HEADERS[18], 'value': '0999999999',
               'source': 'https://example.com/company', 'quote': '0999999999', 'checked_at': '13/11/2026'}]
        rows, report = normalize(self.raw, self.tax, ev)
        self.assertEqual(rows[3][18], '384111441')
        self.assertTrue(any('Nguồn bổ sung khác' in i['message'] for i in report['issues']))

    def test_negative_statement_not_positive_evidence(self):
        row = table(self.raw)[0]
        row[3], row[4], row[14] = '', '', 'Chưa xác minh sản phẩm thức ăn chăn nuôi'
        rows, _ = normalize('\t'.join(row), self.tax)
        self.assertIn('Chăn nuôi: chưa đủ bằng chứng', rows[0][25])

    def test_foreign_phone_and_formula(self):
        self.assertEqual(phone('0912345678; 02812345678', 'Vietnam'), '912345678; 2812345678')
        self.assertEqual(phone('909939139', 'USA'), '909939139')
        self.assertEqual(phone('+84909939139', 'Vietnam'), '+84909939139')
        self.assertIn("'=HYPERLINK", csv_text([['=HYPERLINK("x")']], ['name']))

if __name__ == '__main__':
    unittest.main()
