import tempfile
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
from google_overview import parse_overview, external_links, enrich_google, GoogleBrowser
from normalizer import HEADERS, Taxonomy, read_input, folded

NAME = 'CÔNG TY TNHH MỘT THÀNH VIÊN VINH LỘC'
TEXT = f'''AI Overview
{NAME}
Mã số thuế: 6300226802
Địa chỉ: Số 130, Xã Thạnh Hòa, Cần Thơ
Điện thoại: 07113848764
Email: sales@vinhloc.example
Ngành nghề chính: Chăn nuôi gia cầm
Sản phẩm: Chưa công khai
'''

class OverviewTests(unittest.TestCase):
    def test_activity_and_specific_product_details_are_kept(self):
        row = self.row()
        text = (f'Tên công ty: {NAME}\nMã số thuế: 6300226802\n'
                'Hoạt động thực tế: Sản xuất con giống gia cầm\n'
                'Sản phẩm: Gà giống\nSản phẩm cụ thể: Gia cầm giống một ngày tuổi\n'
                'Loài hoặc đối tượng: Gà\nNhãn hàng: Chưa xác minh\n'
                'Bằng chứng hoạt động và sản phẩm: https://example.com/products')
        fields, _ = parse_overview(text, row, folded)
        self.assertIn('Hoạt động thực tế: Sản xuất con giống gia cầm', fields[14][0])
        self.assertIn('Sản phẩm cụ thể: Gia cầm giống một ngày tuổi', fields[14][0])
        self.assertNotIn('Nhãn hàng', fields[14][0])
        row[14] = fields[14][0]
        from content_rules import match_taxonomy
        tax = Taxonomy(read_input('data/taxonomy.tsv'))
        match_taxonomy(row,tax,folded)
        self.assertEqual(row[12], 'LV01-DM01-PL01-SP002')

    def test_existing_profile_disconnect_does_not_close_user_browser(self):
        runtime = MagicMock()
        browser = MagicMock()
        context = MagicMock()
        tab = MagicMock()
        tab.is_closed.return_value = False
        browser.contexts = [context]
        context.new_page.return_value = tab
        runtime.chromium.connect_over_cdp.return_value = browser
        manager = MagicMock()
        manager.start.return_value = runtime
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder) / 'not-created'
            with patch('playwright.sync_api.sync_playwright', return_value=manager):
                with GoogleBrowser(profile, connection='existing', endpoint='chrome'):
                    pass
            self.assertFalse(profile.exists())
        runtime.chromium.connect_over_cdp.assert_called_once_with('chrome', no_defaults=True, timeout=30000)
        runtime.chromium.launch_persistent_context.assert_not_called()
        tab.close.assert_called_once()
        context.close.assert_not_called()
        browser.close.assert_not_called()
        runtime.stop.assert_called_once()

    def row(self):
        row = [''] * 32
        row[0], row[1], row[27] = '1', NAME, '6300226802'
        return row

    def test_fields_and_no_placeholder(self):
        fields, identity = parse_overview(TEXT, self.row(), folded)
        self.assertEqual(fields[19][0], 'sales@vinhloc.example')
        self.assertNotIn(14, fields)
        self.assertIn('MST', identity)

    def test_other_company_and_parent_tax_rejected(self):
        row = self.row()
        row[27] = '6300226802-001'
        fields, _ = parse_overview(TEXT, row, folded)
        self.assertEqual(fields, {})
        row[1] = 'CÔNG TY KHÁC'
        fields, _ = parse_overview(TEXT.replace('6300226802', '1234567890'), row, folded)
        self.assertEqual(fields, {})

    def test_multiple_companies_not_mixed(self):
        text = '1. CÔNG TY KHÁC\nEmail: other@example.com\n2. ' + TEXT.replace('AI Overview\n','')
        fields, _ = parse_overview(text, self.row(), folded)
        self.assertEqual(fields[19][0], 'sales@vinhloc.example')

    def test_parent_or_shared_email_not_assigned(self):
        fields, _ = parse_overview(TEXT.replace('sales@vinhloc.example', 'info@parent.example (tổng đài chung của công ty mẹ)'), self.row(), folded)
        self.assertNotIn(19, fields)

    def test_sources_and_fake_browser_pipeline(self):
        self.assertEqual(external_links([{'url':'https://www.google.com/url?q=https%3A%2F%2Fexample.com%2Fprofile'}]), ['https://example.com/profile'])
        class FakeBrowser:
            def __init__(self, *args, **kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, row):
                return {'status':'captured','text':TEXT,'search_url':'https://www.google.com/search?q=test','sources':['https://example.com/profile']}
        tax = Taxonomy(read_input('data/taxonomy.tsv'))
        with tempfile.TemporaryDirectory() as directory:
            rows, evidence, audit = enrich_google([self.row()],HEADERS,folded,directory,tax,browser_factory=FakeBrowser)
            self.assertEqual(rows[0][19], 'sales@vinhloc.example')
            self.assertIn('chưa xác minh độc lập', rows[0][25])
            self.assertTrue(evidence)
            self.assertEqual(audit[0]['fields_found'], 4)
            self.assertTrue(list(Path(directory).glob('*.json')))

if __name__ == '__main__':
    unittest.main()
