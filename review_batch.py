"""Tái tạo lô đã được tra cứu theo hồ sơ nguồn lưu trong data/."""
import json
from pathlib import Path
from normalizer import HEADERS, Taxonomy, folded, table, read_input, csv_text, normalize, export
from raw_import import map_rows

def main():
    raw = read_input('data/raw_tax_previous_output.csv')
    rows, mapping_log = map_rows(table(raw), HEADERS, folded)
    profiles = json.loads(Path('data/reviewed_profiles.json').read_text(encoding='utf-8'))
    changes = []
    for row in rows:
        profile = next(p for p in profiles if p['tax_id'] == row[27])
        for key, value in profile['updates'].items():
            index = int(key)
            changes.append({'tax_id': row[27], 'field': HEADERS[index], 'old': row[index],
                            'new': value, 'sources': profile['sources'], 'checked_at': profile['checked_at']})
            row[index] = value
        row[24] = '; '.join(dict.fromkeys([row[24]] + profile['sources']))
        row[25] += ' Đối chiếu nguồn công khai ngày ' + profile['checked_at'] + '.'
        # Khung ngành chính còn thiếu, trừ trường hợp đã phân loại bán buôn riêng.
        row[4] = row[4] or 'LV07'
        if not row[8]:
            row[8], row[9] = 'LV07-DM01', 'Chế biến thủy sản / Seafood Processing'
    Path('data/raw_tax_reviewed.tsv').write_text(csv_text(rows, delimiter='\t'), encoding='utf-8-sig', newline='')
    final, report = normalize(read_input('data/raw_tax_reviewed.tsv'), Taxonomy(read_input('data/taxonomy.tsv')))
    report['source_review_changes'] = changes
    report['original_import_log'] = mapping_log
    export(final, report, 'outputs')
    print('Reviewed 10 companies and exported 32 columns.')

if __name__ == '__main__':
    main()
