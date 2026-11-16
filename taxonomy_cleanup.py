"""Chuẩn hóa mã/tên trả về từ AI bằng taxonomy được người dùng chọn."""
import re


def cleanup_taxonomy(row, tax, fold):
    notes=[]
    key=lambda value:re.sub(r'[^a-z0-9]','',fold(value).replace('&','va'))
    def find_name(value,mapping):
        exact=[code for code,names in mapping.items() if any(key(value)==key(name) for name in names)]
        if exact: return exact
        parts={key(p) for p in value.split('/') if len(key(p))>=5}
        return [code for code,names in mapping.items() if any(parts & {key(p) for p in name.split('/') if len(key(p))>=5} for name in names)]
    def canonical(ci,mapping):
        names=mapping[row[ci]]
        row[ci+1]=row[ci+1] if row[ci+1] in names else sorted(names)[0]
    for ci,mapping in zip([4,6,8,10,12],tax.maps):
        code,name=row[ci].strip(),row[ci+1].strip()
        matches=find_name(name,mapping) if name and name not in {'.','-'} else []
        if code not in mapping:
            if code and code not in {'.','-'}:
                notes.append(f'Mã AI ngoài taxonomy: {code}.')
            row[ci]=matches[0] if len(matches)==1 else ''
        if row[ci]:
            canonical(ci,mapping)
        else:
            if name and name not in {'.','-'}:
                notes.append(f'Tên AI chưa khớp duy nhất taxonomy: {name}.')
            row[ci+1]=''
    # Mã cấp dưới hợp lệ quyết định tổ tiên; không suy ra loài từ cùng hàng.
    for child,parent in [(12,10),(10,8),(8,4)]:
        if not row[child]: continue
        parents=tax.parents.get(row[child],set())
        if row[parent] not in parents:
            if len(parents)==1:
                previous=row[parent]
                row[parent]=next(iter(parents))
                canonical(parent,tax.maps[[4,6,8,10,12].index(parent)])
                if previous: notes.append(f'Sửa quan hệ taxonomy: {row[child]} → {row[parent]}.')
            else:
                notes.append(f'Chưa xác định được cha hợp lệ cho {row[child]}; để trống cấp này.')
                row[child]=row[child+1]=''
    activities=[]
    for activity in filter(None,map(str.strip,row[3].split(';'))):
        label,_,detail=activity.partition(':')
        mapping={name:{name} for name in tax.activities}
        matches=find_name(label,mapping)
        if len(matches)==1:
            activities.append(matches[0])
            description=detail.strip()
        else:
            other=[a for a in tax.activities if fold(a).startswith('khac')]
            if len(other)==1: activities.append(other[0])
            description=activity
            notes.append(f'Hoạt động AI được chuyển sang mô tả: {activity}.')
        if description and description not in row[14]:
            row[14]='; '.join(filter(None,[row[14],description]))
    row[3]='; '.join(dict.fromkeys(activities))
    if notes:
        row[25]=' '.join(filter(None,[row[25],*notes]))
    return notes
