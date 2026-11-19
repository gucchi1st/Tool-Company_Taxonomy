import csv
import json
import tempfile
import unittest
from pathlib import Path
from column_repair import align_row, repair_file
from normalizer import Taxonomy,read_input,HEADERS,csv_text


class ColumnRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.tax=Taxonomy(read_input('data/taxonomy.tsv'))

    def compact_lab(self, contact='.', email='info@sjialab.com'):
        return ['6','Ningbo Sjia Lab Equipment Co., Ltd.','Ningbo SJIA Lab',
            'Sản xuất / Manufacturing; Nghiên cứu & phát triển / R&D; Thương mại / Trading',
            '.','.','.','.','.','.','.','.','.',
            'Vacuum Freeze Dryer; Lyophilizer; Ultrasonic Homogenizer; Laboratory Equipment',
            contact,'General Contact' if contact=='.' else 'Contact',
            '.' if contact=='.' else '8657463097062','.',email,
            'No. 389 Binhai 1st Road, Hangzhou Bay New District, Ningbo, Zhejiang, China',
            'Ningbo, Zhejiang','China','https://www.sjialab.com/',
            'Liên quan tiềm năng đến chăn nuôi và nuôi trồng thủy sản qua thiết bị xét nghiệm; chưa xác nhận sản phẩm chuyên dụng',
            '.','18/11/2026']+['']*200

    def test_missing_product_column_does_not_shift_contact(self):
        row,audit=align_row(self.compact_lab('Maria Han','mariahan@sjialab.com'),self.tax)
        self.assertEqual(len(row),32)
        self.assertEqual(row[1],'Ningbo Sjia Lab Equipment Co., Ltd.')
        self.assertIn('Lyophilizer',row[14])
        self.assertEqual(row[15],'Maria Han')
        self.assertEqual(row[16],'Contact')
        self.assertEqual(row[17],'8657463097062')
        self.assertEqual(row[19],'mariahan@sjialab.com')
        self.assertTrue(row[20].startswith('No. 389'))
        self.assertEqual(row[21],'Ningbo, Zhejiang')
        self.assertEqual(row[22],'China')
        self.assertEqual(row[23],'https://www.sjialab.com/')
        self.assertIn('Liên quan',row[25])
        self.assertEqual(row[31],'18/11/2026')
        self.assertEqual(audit['original_columns'],226)

    def test_repair_keeps_contact_rows_and_source_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'raw.tsv'
            with source.open('w',encoding='utf-8',newline='') as handle:
                csv.writer(handle,delimiter='\t').writerows([
                    self.compact_lab(),self.compact_lab('Maria Han','mariahan@sjialab.com')])
            before=source.read_bytes()
            output=Path(directory)/'repaired'
            rows,report=repair_file(source,output=output)
            self.assertEqual(len(rows),2)
            self.assertEqual({r[19] for r in rows},{'info@sjialab.com','mariahan@sjialab.com'})
            self.assertEqual(rows[1][15],'Maria Han')
            self.assertEqual(source.read_bytes(),before)
            records=list(csv.reader((output/'companies.csv').read_text(encoding='utf-8-sig').splitlines()))
            self.assertTrue(all(len(r)==32 for r in records))
            self.assertEqual(records[0],HEADERS)
            self.assertEqual(len(json.loads((output/'repair_audit.json').read_text(encoding='utf-8'))),2)

    def test_correct_32_columns_preserve_contact(self):
        original=['']*32
        original[0],original[1],original[2]='1','Example Equipment Co., Ltd.','Example'
        original[3]='Thương mại / Trading'
        original[15],original[16],original[19]='Alice Smith','Sales Manager','alice@example.com'
        original[20],original[21],original[22]='No. 1 Industrial Road','Ningbo, Zhejiang','China'
        original[23],original[24],original[25]='https://example.com/','https://example.com/about','Chưa xác minh liên quan chăn nuôi'
        original[31]='2026-11-18'
        repaired,_=align_row(original,self.tax)
        for ci in [15,16,19,20,21,22,23,24,25]: self.assertEqual(repaired[ci],original[ci])
        self.assertEqual(repaired[31],'18/11/2026')

    def test_compact_27_columns_keep_product_address_note_and_date(self):
        original=['7','Zhejiang Juxiang Industrial Co., Limited','Zhejiang Juxiang',
            'Sản xuất / Manufacturing; Thương mại / Trading; Xuất khẩu / Export',
            'LV02','Nuôi trồng thủy sản / Aquaculture','LO0000','Dùng chung / General Use',
            'LV02-DM06','Thiết bị nuôi / Aquaculture Equipment','LV02-DM06-PL02',
            'Cho ăn & bơm nước / Feeding & Water Pumping','LV02-DM06-PL02-SP001',
            'Máy cho ăn tự động, máy bơm / Automatic feeders and pumps',
            'Water Pump Set; Gasoline Engine; Generator Set; Generator Spare Parts',
            'Newis Zhou','Foreign Trade Manager','.','.','.',
            'Garden of Golden Collar, Taizhou, Zhejiang, China','Taizhou, Zhejiang','China',
            'https://juxiang.en.made-in-china.com/',
            'Có liên quan tiềm năng đến nuôi trồng thủy sản; chưa xác nhận máy bơm chuyên dụng',
            '.','2026-11-18']
        repaired,_=align_row(original,self.tax)
        self.assertEqual(repaired[12],'LV02-DM06-PL02-SP001')
        self.assertIn('Generator Set',repaired[14])
        self.assertEqual(repaired[15],'Newis Zhou')
        self.assertEqual(repaired[16],'Foreign Trade Manager')
        self.assertTrue(repaired[20].startswith('Garden of'))
        self.assertEqual(repaired[21],'Taizhou, Zhejiang')
        self.assertEqual(repaired[23],original[23])
        self.assertIn('Có liên quan',repaired[25])
        self.assertEqual(repaired[31],'18/11/2026')

    def test_markdown_extra_empty_columns_and_multiple_emails(self):
        row=self.compact_lab(email='info@sjialab.com; sales@sjialab.com')
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'pasted.txt'
            source.write_text('| '+' | '.join(row)+' |\n| '+ ' | '.join(['---']*len(row))+' |',encoding='utf-8')
            rows,_=repair_file(source,output=Path(directory)/'out')
            self.assertEqual(len(rows),2)
            self.assertEqual({r[19] for r in rows},{'info@sjialab.com','sales@sjialab.com'})


if __name__=='__main__': unittest.main()
