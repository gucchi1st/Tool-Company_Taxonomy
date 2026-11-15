"""Kiểm tra kết nối tìm kiếm thực tế, không sửa file kết quả công ty."""
from web_enrichment import search, fetch, extract
from normalizer import folded
import sys
sys.stdout.reconfigure(encoding='utf-8')

if __name__ == '__main__':
    urls, errors = search('"3600224423-020"', 'outputs/.web_cache')
    print('Search URLs:', len(urls))
    for error in errors:
        print(error)
    if urls:
        try:
            html, url = fetch(urls[0], 'outputs/.web_cache')
            fields = extract(html, '3600224423-020', folded)
            print('First page fields matched:', len(fields))
            print('URL:', url)
        except Exception as exc:
            print(type(exc).__name__ + ': ' + str(exc))
    for url in ['https://masothue.com/1900694514-cong-ty-tnhh-xuat-nhap-khau-thuy-san-bao-ngoc',
                'https://thuvienphapluat.vn/ma-so-thue/cong-ty-tnhh-xuat-nhap-khau-thuy-san-bao-ngoc-mst-1900694514.html']:
        try:
            html, final = fetch(url, 'outputs/.web_cache')
            print('Direct lookup fields:', len(extract(html, '1900694514', folded)), final)
        except Exception as exc:
            print('Direct lookup:', type(exc).__name__, str(exc))
