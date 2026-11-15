import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from normalizer import run, HEADERS, normalize, Taxonomy, read_input, folded
from google_overview import parse_overview

class CheckpointTests(unittest.TestCase):
    def test_multiple_emails_split_and_keep_identifiers(self):
        row = [''] * 32
        row[0], row[1], row[27] = '1', 'CÔNG TY TNHH TEST', '0312345678'
        row[19] = 'sales@example.com; info@example.com, SALES@example.com'
        tax = Taxonomy(read_input('data/taxonomy.tsv'))
        rows, report = normalize('\t'.join(row), tax)
        self.assertEqual([r[19] for r in rows], ['sales@example.com','info@example.com'])
        self.assertTrue(all(r[27] == '0312345678' and r[0]=='1' for r in rows))
        self.assertEqual(report['processed_companies'], 1)
        self.assertEqual(report['output_rows'], 2)

    def test_overview_multiple_email_labels(self):
        row = [''] * 32
        row[1], row[27] = 'CÔNG TY TNHH TEST', '0312345678'
        fields, _ = parse_overview('Tên công ty: CÔNG TY TNHH TEST\nMã số thuế: 0312345678\nEmail: a@example.com; b@example.com\nEmail: c@example.com', row, folded)
        self.assertEqual(fields[19][0], 'a@example.com; b@example.com; c@example.com')

    def test_saved_after_first_company_and_cancel_preserves_csv(self):
        with tempfile.TemporaryDirectory() as folder:
            def fake_enrich(rows, *args, checkpoint=None, **kwargs):
                rows[0][19] = 'a@example.com; b@example.com'
                entries = [{'tax_id':rows[0][27], 'fields_found':2, 'fields_added':[HEADERS[19]],
                            'pages':[{'matched_identity':True}], 'errors':[]}]
                checkpoint(rows[:1], [], entries)
                with (Path(folder)/'companies.csv').open(encoding='utf-8-sig') as handle:
                    records = list(csv.reader(handle))
                self.assertEqual(len(records), 3)
                self.assertEqual(records[1][19], 'a@example.com')
                self.assertEqual(records[2][19], 'b@example.com')
                entries.append({'tax_id':rows[1][27], 'fields_found':0, 'pages':[], 'errors':[]})
                raise InterruptedError('Stop during next company')
            with patch('google_overview.enrich_google', side_effect=fake_enrich):
                rows, report = run('data/raw.tsv', 'data/taxonomy.tsv', folder, web=True)
            self.assertEqual(len(rows), 2)
            self.assertTrue(report['stopped'])
            self.assertEqual(report['processed_companies'], 1)
            self.assertEqual(len(report['web_research']), 1)
            saved = json.loads((Path(folder)/'audit.json').read_text(encoding='utf-8'))
            self.assertTrue(saved['stopped'])

if __name__ == '__main__':
    unittest.main()
