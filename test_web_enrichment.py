import tempfile
import unittest
from normalizer import HEADERS, folded
from web_enrichment import extract, enrich
from content_rules import match_taxonomy
from normalizer import Taxonomy, read_input
from pathlib import Path

HTML = '''<html><table><tr><td>Mã số thuế</td><td>3600224423-020</td></tr>
<tr><td>Tên quốc tế</td><td>CP VIETNAM BRANCH</td></tr>
<tr><td>Điện thoại</td><td>02723854120</td></tr>
<tr><td>Email</td><td>sales@example.com</td></tr>
<tr><td>Ngày hoạt động</td><td>2001-05-30</td></tr></table>
<footer>Email: operator@directory.com</footer>
<table><tr><td>Mã số thuế</td><td>6300226802</td></tr>
<tr><td>Email</td><td>another@example.com</td></tr></table></html>'''

class WebTests(unittest.TestCase):
    def test_farming_alias_fills_parent_levels_without_guessing_product(self):
        tax = Taxonomy(read_input('data/taxonomy.tsv'))
        row = [''] * 32
        row[3] = 'Chăn nuôi dê, cừu'
        match_taxonomy(row, tax, folded)
        self.assertEqual(row[4], 'LV01')
        self.assertEqual(row[8], 'LV01-DM09')
        self.assertEqual(row[10], 'LV01-DM09-PL01')
        self.assertFalse(row[12])
        self.assertTrue(row[9] and row[11])

    def test_specific_meat_production_and_main_activity_priority(self):
        tax = Taxonomy(read_input('data/taxonomy.tsv'))
        row = [''] * 32
        row[3], row[14] = 'Chăn nuôi gia cầm', 'Gà thịt; thức ăn chăn nuôi; gà giống'
        match_taxonomy(row, tax, folded)
        self.assertEqual(row[10], 'LV01-DM09-PL01')
        self.assertEqual(row[12], 'LV01-DM09-PL01-SP001')

    def test_visible_profile_content_without_table(self):
        html = '''<h1>3600224423-020 - CÔNG TY C.P.</h1>
        <div>Mã số thuế: 3600224423-020</div>
        <p>Email: branch@example.com</p><p>Ngành nghề chính: Chăn nuôi gia cầm</p>
        <div>Sản phẩm cung cấp: Phụ gia thức ăn</div>
        <h2>Đơn vị liên quan</h2><p>Email: other@example.com</p>
        <footer>Email: operator@example.com</footer>'''
        fields = extract(html, '3600224423-020', folded, 'CÔNG TY C.P.')
        self.assertEqual(fields[19][0], 'branch@example.com')
        self.assertEqual(fields[3][0], 'Chăn nuôi gia cầm')
        self.assertEqual(fields[14][0], 'Phụ gia thức ăn')
        self.assertFalse(extract(html, '3600224423', folded, 'CÔNG TY C.P.'))

    def test_discover_detail_link_from_raw_listing(self):
        row = [''] * 32
        row[1], row[27], row[24] = 'CÔNG TY C.P.', '3600224423-020', 'https://example.com/province'
        visited = []
        def loader(url, cache):
            visited.append(url)
            if url.endswith('/province'):
                return '<a href="/company/3600224423-020">C.P.</a>', url
            return HTML, url
        _, _, audit = enrich([row], HEADERS, folded, '.', finder=lambda q,c: ([], []), loader=loader)
        self.assertIn('https://example.com/company/3600224423-020', visited)
        self.assertEqual(audit[0]['raw_source_discovery'][0]['links_found'], 1)

    def test_taxonomy_matching_and_negative_evidence(self):
        tax = Taxonomy(read_input(Path('data/taxonomy.tsv')))
        # Một cụm sản phẩm đầy đủ, duy nhất trong một nhánh taxonomy.
        unique = next((code, next(iter(names))) for code,names in tax.maps[4].items()
                      if len(names)==1 and len(tax.parents.get(code,set()))==1
                      and len(next(iter(names)).split(' / ')[0])>=8)
        row = [''] * 32
        row[14] = unique[1].split(' / ')[0]
        matches = match_taxonomy(row, tax, folded)
        self.assertTrue(matches)
        self.assertEqual(row[12], unique[0])
        row = [''] * 32
        row[14] = 'Chưa xác minh ' + unique[1].split(' / ')[0]
        self.assertEqual(match_taxonomy(row, tax, folded), [])

    def test_exact_entity_table_and_no_footer_contacts(self):
        fields = extract(HTML, '3600224423-020', folded)
        self.assertEqual(fields[19][0], 'sales@example.com')
        self.assertEqual(fields[17][0], '02723854120')
        self.assertEqual(fields[29][0], '30/05/2001')
        self.assertEqual(extract(HTML, '1234567890', folded), {})

    def test_missing_fields_only_and_conflicts_retained(self):
        row = [''] * 32
        row[1], row[27], row[17] = 'CÔNG TY C.P.', '3600224423-020', '999999999'
        loader = lambda url, cache: (HTML, url)
        finder = lambda query, cache: (['https://example.com/company'], [])
        rows, evidence, audit = enrich([row], HEADERS, folded, '.', loader=loader, finder=finder)
        self.assertEqual(rows[0][17], '999999999')
        self.assertEqual(rows[0][19], 'sales@example.com')
        self.assertTrue(evidence[0]['quote'])
        self.assertGreater(audit[0]['fields_found'], 0)

    def test_failed_search_is_visible(self):
        row = [''] * 32
        row[1], row[27] = 'CÔNG TY TEST', '3600224423-020'
        def fail_loader(url, cache):
            raise OSError('Blocked test request')
        rows, _, audit = enrich([row], HEADERS, folded, '.', finder=lambda q, c: ([], ['CAPTCHA']), loader=fail_loader)
        self.assertIn('CAPTCHA', audit[0]['errors'])
        self.assertIn('Chưa lấy được', rows[0][25])

    def test_direct_lookup_when_search_fails(self):
        row = [''] * 32
        row[1], row[27] = 'CÔNG TY C.P.', '3600224423-020'
        rows, evidence, audit = enrich([row], HEADERS, folded, '.',
            finder=lambda q, c: ([], ['Search unavailable']), loader=lambda url, c: (HTML, url))
        self.assertEqual(rows[0][19], 'sales@example.com')
        self.assertIn('discovery', audit[0])
        self.assertTrue(evidence)

    def test_cancellation(self):
        with self.assertRaises(InterruptedError):
            enrich([[''] * 32], HEADERS, folded, '.', cancelled=lambda: True)

if __name__ == '__main__':
    unittest.main()
