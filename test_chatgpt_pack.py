import json
import csv
import tempfile
import unittest
from pathlib import Path
from chatgpt_pack import parse_pack, enrich_chatgpt, extract_research, pack_prompt, complete_tsv_from_page
from normalizer import HEADERS, Taxonomy, read_input, folded


class PackTests(unittest.TestCase):
    def setUp(self):
        self.tax = Taxonomy(read_input('data/taxonomy.tsv'))
        self.rows = []
        for i in range(6):
            row = [''] * 32
            row[0], row[1], row[27] = str(i+1), 'COMPANY '+str(i), '031234567'+str(i)
            self.rows.append(row)

    def payload(self, rows, offset=0):
        return {'headers':HEADERS, 'companies':[
            {'input_id':offset+i,'tax_id':row[27],'values':list(row)}
            for i,row in enumerate(rows)]}

    def test_order_and_identity(self):
        data = self.payload(self.rows[:5])
        data['companies'].reverse()
        self.assertEqual(parse_pack(json.dumps(data),self.rows[:5],self.tax,HEADERS), self.rows[:5])
        data['companies'][0]['values'][27] = 'WRONG'
        with self.assertRaises(ValueError):
            parse_pack(json.dumps(data),self.rows[:5],self.tax,HEADERS)

    def test_prompt_uses_original_raw_then_taxonomy_then_request(self):
        original = [['Original company','0312345670','Original activity']]
        prompt = pack_prompt(self.rows[:1],self.tax,HEADERS,raw_pack=original)
        self.assertTrue(prompt.startswith('RAW\nOriginal company\t0312345670\tOriginal activity\n\nTAXONOMY\n'))
        self.assertIn(self.tax.source_text,prompt)
        self.assertIn('NOTE đề cập liên quan hay không đến chăn nuôi, mỗi mail 1 dòng.',prompt)
        self.assertIn('không tạo hoặc gửi file',prompt)
        self.assertNotIn('Trả kết quả dạng bảng',prompt)

    def test_table_with_one_email_per_row(self):
        first = list(self.rows[0])
        second = list(first)
        first[19], second[19] = 'a@example.com', 'b@example.com'
        text = '\n'.join('|'+'|'.join(row)+'|' for row in [HEADERS,['---']*32,first,second])
        result = parse_pack(text,self.rows[:1],self.tax,HEADERS)
        self.assertEqual(result[0][19],'a@example.com; b@example.com')

    def test_tsv_code_block_preserves_empty_columns_and_multiple_emails(self):
        first=list(self.rows[0])
        second=list(first)
        first[19],second[19]='a@example.com','b@example.com'
        text='```tsv\n'+'\n'.join('\t'.join(row) for row in [HEADERS,first,second])+'\n```'
        parsed=parse_pack(text,self.rows[:1],self.tax,HEADERS)
        self.assertEqual(parsed[0][19],'a@example.com; b@example.com')
        self.assertEqual(len(parsed[0]),32)

    def test_actual_chatgpt_sample_keeps_contacts_and_activity_detail(self):
        text=Path('tests/fixtures/chatgpt_sample.tsv').read_text(encoding='utf-8')
        original=list(csv.reader(text.splitlines(),delimiter='\t'))[1:]
        parsed=parse_pack(text,original,self.tax,HEADERS)
        self.assertEqual(len(parsed),5)
        self.assertTrue(all(len(row)==32 for row in parsed))
        self.assertEqual(parsed[0][18],'907262762')
        self.assertEqual(parsed[0][3],'Khác (ghi rõ) / Other (please specify)')
        self.assertIn('Đăng ký chăn nuôi dê, cừu, hươu, nai',parsed[0][14])
        self.assertEqual(parsed[3][27],'3600224423-020')
        self.assertTrue(all(row[19]=='' for row in parsed))

    def test_page_copy_requires_entire_pack_and_ignores_prompt_and_footer(self):
        sample=Path('tests/fixtures/chatgpt_sample.tsv').read_text(encoding='utf-8')
        lines=sample.splitlines()
        pack=list(csv.reader(lines,delimiter='\t'))[1:]
        partial='Prompt\n'+'\t'.join(HEADERS)+'\nNOTE each email\n'+ '\n'.join(lines[:-1])
        self.assertEqual(complete_tsv_from_page(partial,pack),(None,4))
        copied='Sidebar\n'+partial+'\n'+sample+'\nCopy\nChatGPT can make mistakes'
        result,count=complete_tsv_from_page(copied,pack)
        self.assertEqual(count,5)
        self.assertEqual(len(list(csv.reader(result.splitlines(),delimiter='\t'))),6)

    def test_new_incomplete_result_does_not_accept_old_complete_result(self):
        sample=Path('tests/fixtures/chatgpt_sample.tsv').read_text(encoding='utf-8')
        pack=list(csv.reader(sample.splitlines(),delimiter='\t'))[1:]
        self.assertEqual(complete_tsv_from_page(sample+'\n'+sample.splitlines()[0]+'\n',pack),(None,0))

    def test_free_response_extracts_contacts_without_mixing_companies(self):
        text = ('COMPANY 0\nMã số thuế: 0312345670\nEmail: first@example.com\n'
                'COMPANY 1\nMã số thuế: 0312345671\nEmail: second@example.com')
        result = extract_research(text,self.rows[:2],folded)
        self.assertEqual(result[0][19],'first@example.com')
        self.assertEqual(result[1][19],'second@example.com')
        self.assertEqual(result[0][27],self.rows[0][27])

    def test_unmatched_response_preserves_raw(self):
        result = extract_research('Email: unrelated@example.com',self.rows[:1],folded)
        self.assertEqual(result[0][19],'')
        self.assertIn('Chưa trích xuất',result[0][25])

    def test_reject_invalid_schema_and_taxonomy(self):
        for kind in ['header','code','count']:
            data = self.payload(self.rows[:1])
            if kind == 'header': data['headers'] = HEADERS[:-1]
            if kind == 'code': data['companies'][0]['values'][12] = 'INVALID'
            if kind == 'count': data['companies'] = []
            with self.assertRaises(ValueError):
                parse_pack(json.dumps(data),self.rows[:1],self.tax,HEADERS)

    def test_packs_five_and_one_checkpoint_each_company(self):
        owner = self
        sizes, saved = [], []
        class FakeBrowser:
            def __init__(self,*args,**kwargs): pass
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def ask_pack(self,prompt):
                lines = prompt.split('RAW\n',1)[1].split('\n\nTAXONOMY\n',1)[0].splitlines()
                raw = [line.split('\t') for line in lines]
                sizes.append(len(raw))
                data = owner.payload(raw,int(raw[0][0])-1)
                return {'text':json.dumps(data),'chat_url':'https://chatgpt.com/c/test','sources':[]}
        with tempfile.TemporaryDirectory() as directory:
            rows, _, audit = enrich_chatgpt(self.rows,HEADERS,folded,directory,self.tax,
                browser_factory=FakeBrowser,checkpoint=lambda rows,ev,audit:saved.append(len(rows)))
            self.assertTrue((Path(directory)/'pack_00002_response.json').exists())
        self.assertEqual(sizes,[5,1])
        self.assertEqual(saved,[1,2,3,4,5,6])
        self.assertEqual(len(rows),6)
        self.assertEqual(len(audit),6)


if __name__ == '__main__':
    unittest.main()
