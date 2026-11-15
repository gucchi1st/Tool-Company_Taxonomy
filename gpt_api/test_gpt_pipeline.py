import copy
import json
import tempfile
import unittest
from pathlib import Path
from gpt_pipeline import BASE, HEADERS, Taxonomy, read_input, map_rows, table, folded, schema, research_company, apply_profile, run_gpt, APIError

SOURCE = 'https://example.com/company/0318375321'

def response(text, web=False):
    output = [{'type': 'message', 'content': [{'type': 'output_text', 'text': text,
        'annotations': [{'type': 'url_citation', 'url': SOURCE}] if web else []}]}]
    if web:
        output.insert(0, {'type': 'web_search_call', 'action': {'type': 'search', 'sources': [{'url': SOURCE}]}})
    return {'status': 'completed', 'id': 'test_response', 'output': output,
            'usage': {'input_tokens': 100, 'output_tokens': 50}}

class GPTTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tax = Taxonomy(read_input(BASE / 'data/taxonomy.tsv'))
        cls.row = map_rows(table(read_input(BASE / 'data/raw.tsv')), HEADERS, folded)[0][0]

    def profile(self):
        return {'tax_id': self.row[27], 'entity_match': True, 'identity_reason': 'MST khớp',
            'facts': [{'column': 19, 'value': 'sales@example.com', 'source': SOURCE, 'evidence': 'Email liên hệ công ty', 'scope': 'exact_entity'}],
            'classification': {'industry': 'LV07', 'species': '', 'category': 'LV07-DM01', 'subcategory': '', 'product': '', 'source': SOURCE, 'evidence': 'Chế biến thủy sản'},
            'livestock': 'chưa đủ bằng chứng', 'aquaculture': 'có liên quan', 'relation_source': SOURCE, 'notes': 'Chưa xác minh sản phẩm cụ thể.'}

    def test_research_payload_and_json_schema(self):
        calls = []
        def call(payload, key):
            calls.append(payload)
            return response('Nghiên cứu có nguồn', True) if len(calls) == 1 else response(json.dumps(self.profile()))
        result = research_company(self.row, self.tax, 'test', 'test-model', lambda x: None, call)
        self.assertEqual(calls[0]['tools'][0]['type'], 'web_search')
        self.assertEqual(calls[0]['max_tool_calls'], 3)
        self.assertEqual(calls[1]['text']['format']['type'], 'json_schema')
        row, audit = apply_profile(self.row, result, self.tax)
        self.assertEqual(row[19], 'sales@example.com')
        self.assertEqual(row[27], self.row[27])
        self.assertTrue(audit['changes'])

    def test_requires_actual_sources(self):
        with self.assertRaises(APIError):
            research_company(self.row, self.tax, 'test', 'test', lambda x: None, lambda p,k: response('No source'))

    def test_parent_contact_not_applied_and_fake_url_rejected(self):
        profile = self.profile()
        profile['facts'][0]['scope'] = 'parent_company'
        profile['facts'].append({'column': 23, 'value': 'https://fake.example', 'source': 'https://invented.example', 'evidence': 'fake', 'scope': 'exact_entity'})
        result = {'profile': profile, 'sources': [SOURCE], 'response_ids': []}
        row, audit = apply_profile(self.row, result, self.tax)
        self.assertEqual(row[19], self.row[19])
        self.assertIn('parent_company', row[25])
        self.assertTrue(audit['warnings'])

    def test_identity_and_taxonomy_checks(self):
        profile = self.profile()
        profile['tax_id'] = '1234567890'
        with self.assertRaises(ValueError):
            apply_profile(self.row, {'profile': profile, 'sources': [SOURCE], 'response_ids': []}, self.tax)
        profile['tax_id'] = self.row[27]
        profile['classification']['category'] = 'LV01-DM01'
        _, audit = apply_profile(self.row, {'profile': profile, 'sources': [SOURCE], 'response_ids': []}, self.tax)
        self.assertTrue(any('Từ chối' in x for x in audit['warnings']))

    def test_export_and_resume_do_not_call_api_twice(self):
        calls = []
        def call(payload, key):
            calls.append(payload)
            return response('Nghiên cứu', True) if len(calls) == 1 else response(json.dumps(self.profile()))
        with tempfile.TemporaryDirectory() as out:
            options = dict(raw=BASE / 'data/raw.tsv', taxonomy=BASE / 'data/taxonomy.tsv', output=out,
                           api_key='test-not-real', model='test', limit=1, progress=lambda x: None, call=call)
            rows, audit, folder = run_gpt(**options)
            self.assertEqual(len(rows), 1)
            self.assertEqual(len(rows[0]), 32)
            self.assertEqual(rows[0][19], 'sales@example.com')
            self.assertTrue((Path(folder) / 'companies.csv').exists())
            run_gpt(**options)
            self.assertEqual(len(calls), 2)
            self.assertNotIn('test-not-real', (Path(folder) / 'audit.json').read_text(encoding='utf-8'))

    def test_stop_before_first_company(self):
        with tempfile.TemporaryDirectory() as out:
            rows, audit, _ = run_gpt(BASE / 'data/raw.tsv', BASE / 'data/taxonomy.tsv', out,
                api_key='test', cancelled=lambda: True, progress=lambda x: None)
            self.assertFalse(rows)
            self.assertTrue(audit['stopped'])

if __name__ == '__main__':
    unittest.main()
