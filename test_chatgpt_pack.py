import json
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call
from chatgpt_pack import parse_pack, enrich_chatgpt, extract_research, pack_prompt, complete_tsv_from_page, ChatGPTBrowser
from normalizer import HEADERS, Taxonomy, read_input, folded


class PackTests(unittest.TestCase):
    def test_timeout_opens_new_page_and_resubmits_same_pack(self):
        browser=ChatGPTBrowser.__new__(ChatGPTBrowser)
        browser.cancelled=lambda:False
        browser.progress=Mock()
        browser._submit_pack=Mock()
        result={'text':'complete result'}
        browser.wait_answer=Mock(side_effect=[TimeoutError(),TimeoutError(),result])
        old,second,third=Mock(),Mock(),Mock()
        old.is_closed.return_value=second.is_closed.return_value=False
        browser.page=old
        browser.context=Mock()
        browser.context.new_page.side_effect=[second,third]
        self.assertEqual(browser.ask_pack('same five raw rows and taxonomy'),result)
        self.assertEqual(browser._submit_pack.call_args_list,[call('same five raw rows and taxonomy')]*3)
        self.assertEqual(browser.context.new_page.call_count,2)
        old.close.assert_called_once()
        second.close.assert_called_once()
        third.close.assert_not_called()
        self.assertEqual(browser.answer_timeout,180)

    def test_timeout_retry_stops_when_cancelled(self):
        browser=ChatGPTBrowser.__new__(ChatGPTBrowser)
        browser.cancelled=Mock(side_effect=[False,True])
        browser._submit_pack=Mock()
        browser.wait_answer=Mock(side_effect=TimeoutError())
        browser.context=Mock()
        with self.assertRaises(InterruptedError): browser.ask_pack('same pack')
        browser.context.new_page.assert_not_called()

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

    def test_pack_counts_names_even_when_tax_ids_missing(self):
        rows=[list(r) for r in self.rows[:5]]
        for row in rows:
            row[1]=row[1].lower()
            row[27]=''
        text='\n'.join('\t'.join(r) for r in [HEADERS,*rows])
        complete,count=complete_tsv_from_page(text,self.rows[:5])
        self.assertEqual(count,5)
        self.assertIsNotNone(complete)
        parsed=parse_pack(complete,self.rows[:5],self.tax,HEADERS)
        self.assertEqual([r[27] for r in parsed],[r[27] for r in self.rows[:5]])
        rows[4]=list(rows[0])
        text='\n'.join('\t'.join(r) for r in [HEADERS,*rows])
        self.assertEqual(complete_tsv_from_page(text,self.rows[:5]),(None,4))

    def test_company_name_punctuation_and_branch_distinction(self):
        original=list(self.rows[0])
        original[1]='CHI NHÁNH CÔNG TY TNHH PETPLUS – CƠ SỞ 2 LÊ ĐẠI HÀNH'
        result=list(original)
        result[1]='Chi nhánh Công ty TNHH Petplus - Cơ sở 2 Lê Đại Hành'
        result[27]=''
        text='\n'.join('\t'.join(r) for r in [HEADERS,result])
        self.assertIsNotNone(complete_tsv_from_page(text,[original])[0])
        result[1]='CHI NHÁNH CÔNG TY TNHH PETPLUS – CƠ SỞ 3 LÊ ĐẠI HÀNH'
        text='\n'.join('\t'.join(r) for r in [HEADERS,result])
        self.assertEqual(complete_tsv_from_page(text,[original]),(None,0))

    def test_duplicate_companies_count_as_two_input_slots(self):
        pack=[list(r) for r in self.rows[:5]]
        pack[1][1]=pack[0][1]
        pack[1][27]=pack[0][27]
        rows=[list(r) for r in pack]
        rows[0][19]='first@example.com'
        extra=list(rows[0]); extra[19]='second@example.com'
        text='\n'.join('\t'.join(r) for r in [HEADERS,*rows,extra])
        complete,count=complete_tsv_from_page(text,pack)
        self.assertEqual(count,5)
        parsed=parse_pack(complete,pack,self.tax,HEADERS)
        self.assertEqual(len(parsed),5)
        self.assertEqual(parsed[0][19],'first@example.com; second@example.com')
        self.assertEqual(parsed[1][19],'')
        missing='\n'.join('\t'.join(r) for r in [HEADERS,rows[0],*rows[2:],extra])
        self.assertEqual(complete_tsv_from_page(missing,pack),(None,4))

    def test_duplicate_names_with_local_pack_numbering(self):
        pack=[list(r) for r in self.rows[:5]]
        pack[1][1]=pack[0][1]
        for i,row in enumerate(pack): row[0]=str(31+i)
        rows=[list(r) for r in pack]
        for i,row in enumerate(rows): row[0]=str(i+1)
        text='\n'.join('\t'.join(r) for r in [HEADERS,*rows])
        complete,count=complete_tsv_from_page(text,pack)
        self.assertEqual(count,5)
        parsed=parse_pack(complete,pack,self.tax,HEADERS)
        self.assertEqual([r[0] for r in parsed],['31','32','33','34','35'])

    def test_ai_taxonomy_repaired_against_selected_dictionary(self):
        row=list(self.rows[0])
        product=next(code for code in self.tax.maps[4] if len(self.tax.parents[code])==1)
        row[12],row[13]=product,'AI invented product label'
        row[4],row[5]='INVALID','Unknown industry'
        row[6],row[7]='UNKNOWN','Unknown species'
        row[3]='Hoạt động AI tự viết: mô tả sản phẩm'
        text='\n'.join('\t'.join(r) for r in [HEADERS,row])
        result=parse_pack(text,self.rows[:1],self.tax,HEADERS,repair_taxonomy=True)[0]
        for ci,mapping in zip([4,6,8,10,12],self.tax.maps):
            self.assertTrue(not result[ci] or result[ci] in mapping)
            self.assertTrue(not result[ci] or result[ci+1] in mapping[result[ci]])
        for child,parent in [(12,10),(10,8),(8,4)]:
            self.assertTrue(not result[child] or result[parent] in self.tax.parents[result[child]])
        self.assertEqual(result[6:8],['',''])
        self.assertTrue(all(a in self.tax.activities for a in result[3].split('; ') if a))
        self.assertIn('mô tả sản phẩm',result[14])

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
