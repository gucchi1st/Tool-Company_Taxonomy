"""Sửa cột raw bằng cách căn chỉnh chuỗi trường và các dấu hiệu dữ liệu."""
import argparse
import re
import sys
from pathlib import Path
from functools import lru_cache

from normalizer import HEADERS, Taxonomy, read_input, table, clean, folded, normalize, csv_text, export, atomic_text
from raw_import import date_text
from email_utils import emails
import json

CODE_FIELDS={4:0,6:1,8:2,10:3,12:4}
NAME_FIELDS={5:0,7:1,9:2,11:3,13:4}
COUNTRIES={'china','trung quoc','vietnam','viet nam','thailand','thai lan','taiwan','dai loan',
           'india','an do','japan','nhat ban','korea','south korea','han quoc','germany','duc',
           'usa','united states','united kingdom','uk','singapore','malaysia','indonesia',
           'france','italy','netherlands','australia','canada','hong kong','turkey'}


def value_text(value):
    return clean(re.sub(r'\[([^\]]*)\]\((https?://[^)]+)\)',r'\2',str(value)))


def phone_kind(value):
    digits=re.sub(r'[\s()+.\-]','',value)
    if not re.fullmatch(r'\d{8,15}',digits): return None
    if re.match(r'^(?:\+?84|0)?[35789]\d{8}$',digits) or re.match(r'^86(?:1[3-9])\d{9}$',digits):
        return 'mobile'
    return 'telephone'


@lru_cache(maxsize=32768)
def field_score(value, field, tax, foreign=False):
    if not value: return 0.4
    low=folded(value)
    urls=re.findall(r'https?://[^\s;]+',value)
    is_email=bool(emails(value))
    is_date=bool(re.fullmatch(r'(?:\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})',value))
    code=re.fullmatch(r'(?:LV\d+(?:-DM\d+)?(?:-PL\d+)?(?:-SP\d+)?|LO\d+)',value,re.I)
    if field==0: return 15 if value.isdigit() and len(value)<7 else -20
    if field in CODE_FIELDS:
        return 18 if value in tax.maps[CODE_FIELDS[field]] else -18
    if field in NAME_FIELDS:
        names={folded(n) for group in tax.maps[NAME_FIELDS[field]].values() for n in group}
        return 14 if low in names else -8
    if field==19: return 22 if is_email else -20
    if field in {23,24}:
        if not urls: return -16
        return (19 if len(urls)==1 else 9) if field==23 else (24 if len(urls)>1 else 12)
    if field==22: return 20 if low in COUNTRIES else -13
    if field in {28,29,31}: return (19 if field==31 else 12) if is_date else -18
    if field==27:
        return (3 if foreign else 13) if re.fullmatch(r'\d{10}(?:-\d{3})?',value) else -18
    if field in {17,18}:
        kind=phone_kind(value)
        if not kind or is_date: return -17
        return 17 if kind==('mobile' if field==18 else 'telephone') else 10
    if field==30:
        return 17 if re.search(r'dang hoat dong|ngung hoat dong|giai the|active|inactive|dissolved',low) else -13
    if code or is_email or is_date or urls or phone_kind(value) or low in COUNTRIES: return -15
    if field==1:
        return 15 if re.search(r'cong ty|company|co\.,?|limited|ltd\.?|corporation|chi nhanh|doanh nghiep',low) else 3
    if field==2: return 5 if len(value)<90 and ';' not in value else -7
    if field==3:
        return 15 if any(word in low for word in ['san xuat','manufacturing','thuong mai','trading','nghien cuu','r&d','xuat khau','export','distribution','service']) else -5
    if field==14:
        return 12 if ';' in value or re.search(r'equipment|dryer|pump|parts|san pham|thiet bi|may |engine|incubator|homogenizer',low) else 2
    if field==16:
        return 17 if re.search(r'contact|sales|manager|director|giam doc|truong phong|dai dien|general|foreign trade',low) else -8
    if field==15:
        return 8 if 2<=len(value.split())<=5 and ';' not in value and not re.search(r'\d|equipment|products|parts|laboratory|road|street|contact|sales|manager',low) else -7
    if field==20:
        return 15 if re.search(r'\b(no\.?|road|street|industrial|zone|district|duong|khu|so|ap|thon|ward|garden)\b',low) else 2
    if field==21:
        return 8 if len(value)<85 and ';' not in value else -8
    if field==25:
        return 22 if re.search(r'lien quan|chua xac|khong lien|chua tim|can xac|potential|not related|unconfirmed|verified|evidence',low) else (5 if len(value)>100 else -5)
    if field==26: return 4 if re.search(r'association|hiep hoi|expo|exhibition|vietstock|vietshrimp',low) else -7
    return -5


def align_row(raw, tax, line=1):
    values=[value_text(v) for v in raw]
    while values and not values[-1]: values.pop()
    if not values: return None,None
    n=len(values)
    foreign=any(folded(v) in COUNTRIES-{'vietnam','viet nam'} for v in values)
    # Global sequence alignment: cho phép ô thiếu/thừa, giữ thứ tự dữ liệu.
    dp=[[float('-inf')]*33 for _ in range(n+1)]
    previous={}
    dp[0][0]=0
    for i in range(n+1):
        for j in range(33):
            base=dp[i][j]
            if base==float('-inf'): continue
            transitions=[]
            if j<32: transitions.append((i,j+1,base-1.3,('missing',i,j)))
            if i<n: transitions.append((i+1,j,base-(0.5 if not values[i] else 11),('unassigned',i,j)))
            if i<n and j<32:
                score=field_score(values[i],j,tax,foreign)
                positional=0.15 if i==j else 0
                transitions.append((i+1,j+1,base+score+positional,('match',i,j)))
            for ni,nj,total,action in transitions:
                if total>dp[ni][nj]:
                    dp[ni][nj]=total
                    previous[ni,nj]=(i,j,action)
    row=['']*32
    assignments=[]
    unassigned=[]
    i,j=n,32
    while (i,j)!=(0,0):
        pi,pj,(kind,source,target)=previous[i,j]
        if kind=='match':
            row[target]=values[source]
            if values[source]:
                assignments.append({'source_column':source+1,'target_column':target+1,
                    'field':HEADERS[target],'value':values[source],
                    'score':field_score(values[source],target,tax,foreign)})
        elif kind=='unassigned' and values[source]:
            unassigned.append({'source_column':source+1,'value':values[source]})
        i,j=pi,pj
    if not row[0]: row[0]=str(line)
    for ci in [28,29,31]: row[ci]=date_text(row[ci])
    warnings=[]
    if not row[1]: warnings.append('Chưa nhận diện được tên đầy đủ công ty')
    uncertain=[a for a in assignments if a['score']<5]
    if uncertain: warnings.append('Cần rà soát các trường có độ chắc chắn thấp trong repair_audit.json')
    if unassigned:
        warnings.append('Có giá trị chưa xác định cột, đã giữ trong repair_audit.json')
        row[25]='; '.join(filter(None,[row[25],'Chưa xác định cột: '+' | '.join(v['value'] for v in reversed(unassigned))]))
    audit={'line':line,'original_columns':len(raw),'original_values':raw,
           'assignments':list(reversed(assignments)),'unassigned':list(reversed(unassigned)),
           'needs_review':bool(warnings),'warnings':warnings}
    return row,audit


def repair_file(raw, taxonomy='data/taxonomy.tsv', output='outputs/column_repaired', progress=None, cancelled=None):
    progress=progress or (lambda message:None)
    cancelled=cancelled or (lambda:False)
    source=Path(raw).resolve()
    out=Path(output).resolve()
    # Không ghi đè file nguồn kể cả khi người dùng chọn nó trong thư mục xuất.
    if source in {out/'companies.csv',out/'companies.tsv'}:
        raise ValueError('Chọn thư mục xuất khác để giữ nguyên file raw.')
    tax=Taxonomy(read_input(taxonomy))
    raw_rows=table(read_input(raw))
    rows,audits=[],[]
    for line,values in enumerate(raw_rows,1):
        if cancelled(): raise InterruptedError('Đã dừng sửa cột; file raw được giữ nguyên')
        if not any(value_text(v) for v in values): continue
        if folded(str(values[0])).strip() in {'stt','stt - no','no'}: continue
        row,audit=align_row(values,tax,line)
        if row is not None:
            rows.append(row);audits.append(audit)
            progress(f'Đã sửa cột dòng {line}: {row[1] or "cần rà soát tên"}')
    if not rows: raise ValueError('Không tìm được dòng dữ liệu trong file raw.')
    normalized,report=normalize(csv_text(rows,delimiter='\t'),tax,strict_taxonomy=True,allow_missing_tax=True)
    report.update({'mode':'column_repair','source':str(source),'output':str(out),
        'processed_companies':len(rows),'output_rows':len(normalized),'column_repairs':audits})
    for audit in audits:
        report['issues'].extend({'line':audit['line'],'message':warning} for warning in audit['warnings'])
    export(normalized,report,out)
    atomic_text(out/'repair_audit.json',json.dumps(audits,ensure_ascii=False,indent=2))
    progress(f'Đã lưu {len(normalized)} dòng, đủ 32 cột tại {out}')
    return normalized,report


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description='Sửa dữ liệu raw lệch cột, không tra cứu web')
    parser.add_argument('raw')
    parser.add_argument('--taxonomy',default='data/taxonomy.tsv')
    parser.add_argument('--output',default='outputs/column_repaired')
    args=parser.parse_args()
    repair_file(args.raw,args.taxonomy,args.output,progress=print)
