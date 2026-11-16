"""Giao diện desktop: python app.py"""
import json
import tkinter as tk
import queue
import threading
import math
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from normalizer import run, HEADERS

BASE = Path(__file__).resolve().parent

def main():
    root = tk.Tk()
    root.title('THUANDZ')
    logo_path = BASE / 'logo.png'
    if logo_path.exists():
        root.logo_original = tk.PhotoImage(file=str(logo_path))
        scale = max(1, math.ceil(max(root.logo_original.width(), root.logo_original.height()) / 48))
        root.logo_small = root.logo_original.subsample(scale, scale)
        root.iconphoto(True, root.logo_small)
    root.geometry('1250x760')
    panel = ttk.Frame(root, padding=16)
    panel.pack(fill='both', expand=True)
    actions = ttk.Frame(panel)
    actions.pack(fill='x', pady=(0, 12))
    start_button = ttk.Button(actions, text='Tra cứu web và chuẩn hóa', command=lambda: process())
    start_button.pack(side='left')
    stop = threading.Event()
    resume_event = threading.Event()
    ttk.Button(actions, text='Dừng tra cứu', command=stop.set).pack(side='left', padx=8)
    def resume_browser():
        resume_event.set()
        resume_button.configure(state='disabled')
    resume_button = ttk.Button(actions, text='Tiếp tục sau thao tác Chrome', command=resume_browser, state='disabled')
    resume_button.pack(side='left', padx=4)
    use_web = tk.BooleanVar(value=True)
    ttk.Checkbutton(actions, text='Tìm thêm thông tin trên web', variable=use_web).pack(side='left')
    brand = ttk.Frame(panel)
    brand.pack(fill='x')
    if hasattr(root, 'logo_small'):
        ttk.Label(brand, image=root.logo_small).pack(side='left', padx=(0, 10))
    ttk.Label(brand, text='Chuẩn hóa danh bạ công ty', font=('Segoe UI', 18, 'bold')).pack(side='left')
    ttk.Label(panel, text='Raw → hỏi Google Chế độ AI trong Chrome → lấy câu trả lời → chuẩn hóa 32 cột. Không dùng GPT API.').pack(anchor='w', pady=(4, 16))
    mode_frame = ttk.Frame(panel)
    mode_frame.pack(fill='x', pady=4)
    ttk.Label(mode_frame, text='Cách tra cứu / Trình duyệt', width=43).pack(side='left')
    mode = tk.StringVar(value='google_ai_mode')
    ttk.Combobox(mode_frame, textvariable=mode, values=['google_ai_mode','google_overview','website','chatgpt_pack5'], state='readonly', width=22).pack(side='left')
    channel = tk.StringVar(value='chrome')
    ttk.Combobox(mode_frame, textvariable=channel, values=['chrome','msedge','chromium'], state='readonly', width=15).pack(side='left', padx=8)
    connection_frame = ttk.Frame(panel)
    connection_frame.pack(fill='x', pady=4)
    ttk.Label(connection_frame, text='Profile / Kết nối CDP', width=43).pack(side='left')
    connection = tk.StringVar(value='existing')
    ttk.Combobox(connection_frame, textvariable=connection, values=['existing','separate'], state='readonly', width=22).pack(side='left')
    endpoint = tk.StringVar(value='chrome')
    ttk.Entry(connection_frame, textvariable=endpoint, width=40).pack(side='left', padx=8)
    def check_connection():
        target, selected_channel = endpoint.get().strip() or channel.get(), channel.get()
        status.set('Đang kiểm tra kết nối Chrome; chấp nhận kết nối trong Chrome nếu có…')
        def worker():
            try:
                from google_overview import GoogleBrowser
                with GoogleBrowser(BASE / 'outputs/google_overview/chrome_profile',
                    connection='existing', endpoint=target, channel=selected_channel):
                    pass
                messages.put(('connection_ok', 'Đã kết nối được Chrome đang mở. Bạn có thể bắt đầu tra cứu.'))
            except Exception as exc:
                messages.put(('error', str(exc)))
        threading.Thread(target=worker, daemon=True).start()
    ttk.Button(connection_frame, text='Kiểm tra kết nối', command=check_connection).pack(side='left')
    ttk.Label(panel, text='existing = dùng Chrome đang đăng nhập. Bật Remote Debugging tại chrome://inspect/#remote-debugging (Chrome 144+), rồi chấp nhận kết nối.', wraplength=1200).pack(anchor='w', pady=3)
    paths = {}
    search_key = tk.StringVar()
    key_frame = ttk.Frame(panel)
    key_frame.pack(fill='x', pady=4)
    ttk.Label(key_frame, text='Serper key (chỉ chế độ website, tùy chọn)', width=43).pack(side='left')
    ttk.Entry(key_frame, textvariable=search_key, show='*').pack(side='left', fill='x', expand=True)
    default_raw = 'data/raw_tax_reviewed.tsv' if (BASE / 'data/raw_tax_reviewed.tsv').exists() else 'data/raw.tsv'
    for key, label, default in [('raw', 'Dữ liệu raw', default_raw),
                                ('taxonomy', 'Taxonomy', 'data/taxonomy.tsv'),
                                ('evidence', 'Bằng chứng bổ sung JSON (tùy chọn)', ''),
                                ('output', 'Thư mục xuất', 'outputs')]:
        frame = ttk.Frame(panel)
        frame.pack(fill='x', pady=4)
        ttk.Label(frame, text=label, width=43).pack(side='left')
        var = tk.StringVar(value=str(BASE / default) if default else '')
        paths[key] = var
        ttk.Entry(frame, textvariable=var).pack(side='left', fill='x', expand=True)
        def browse(k=key, v=var):
            path = filedialog.askdirectory() if k == 'output' else filedialog.askopenfilename()
            if path:
                v.set(path)
        ttk.Button(frame, text='Chọn…', command=browse).pack(side='left', padx=(8, 0))
    status = tk.StringVar(value='Chưa xử lý')
    tabs = ttk.Notebook(panel)
    tabs.pack(fill='both', expand=True, pady=12)
    preview = ttk.Frame(tabs)
    tabs.add(preview, text='Dữ liệu chuẩn hóa')
    columns = HEADERS
    tree = ttk.Treeview(preview, columns=columns, show='headings')
    for col in columns:
        tree.heading(col, text=col)
        tree.column(col, width=70 if col == HEADERS[0] else 250)
    sy = ttk.Scrollbar(preview, orient='vertical', command=tree.yview)
    sx = ttk.Scrollbar(preview, orient='horizontal', command=tree.xview)
    tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
    sy.pack(side='right', fill='y')
    sx.pack(side='bottom', fill='x')
    tree.pack(fill='both', expand=True)
    detail = tk.Text(tabs, wrap='word', font=('Consolas', 10))
    tabs.add(detail, text='Báo cáo kiểm tra')
    live_log = tk.Text(tabs, wrap='word', font=('Consolas', 10))
    tabs.add(live_log, text='Nhật ký tra cứu web')
    messages = queue.Queue()
    def process():
        options = {k: v.get() or None for k, v in paths.items()}
        options['web'] = use_web.get()
        options['search_api_key'] = search_key.get().strip() or None
        options['search_mode'] = mode.get()
        options['browser_channel'] = channel.get()
        options['browser_connection'] = connection.get()
        options['cdp_endpoint'] = endpoint.get().strip() or channel.get()
        def wait_for_browser(reason):
            resume_event.clear()
            messages.put(('manual', reason))
            while not resume_event.wait(0.2):
                if stop.is_set():
                    raise InterruptedError('Đã dừng chờ thao tác trình duyệt')
        options['manual_wait'] = wait_for_browser
        stop.clear()
        live_log.delete('1.0', 'end')
        if options['web']:
            tabs.select(live_log)
            live_log.insert('end', 'Chế độ: ' + options['search_mode'] + '. ChatGPT pack5 dùng tài khoản ChatGPT trong Chrome, mỗi lượt tối đa 5 công ty.\n')
        start_button.configure(state='disabled')
        status.set('Đang xử lý…')
        def worker():
            try:
                result = run(**options, progress=lambda text: messages.put(('progress', text)), cancelled=stop.is_set)
                messages.put(('done', result))
            except Exception as exc:
                messages.put(('error', str(exc)))
        threading.Thread(target=worker, daemon=True).start()
    def poll():
        try:
            while True:
                kind, value = messages.get_nowait()
                if kind == 'progress':
                    status.set(value)
                    live_log.insert('end', value + '\n')
                    live_log.see('end')
                elif kind == 'manual':
                    status.set(value)
                    live_log.insert('end', 'CHỜ BẠN: ' + value + '\n')
                    live_log.see('end')
                    resume_button.configure(state='normal')
                elif kind == 'connection_ok':
                    status.set(value)
                    messagebox.showinfo('Kết nối Chrome', value)
                elif kind == 'error':
                    start_button.configure(state='normal')
                    status.set(value)
                    messagebox.showerror('Không thể xử lý', value)
                else:
                    rows, report = value
                    tree.delete(*tree.get_children())
                    for row in rows:
                        tree.insert('', 'end', values=row)
                    detail.delete('1.0', 'end')
                    detail.insert('1.0', json.dumps(report, ensure_ascii=False, indent=2))
                    processed = report.get('processed_companies', report.get('input_rows', len(rows)))
                    web_status = (f' Nguồn có thông tin nhận diện: {report["web_companies_matched"]}/{processed} công ty; '
                                  f'điền mới {report.get("web_fields_added", 0)} trường; '
                                  f'{report["web_companies_failed"]} công ty chưa lấy được nguồn.' if 'web_research' in report else '')
                    prefix = 'Đã dừng và lưu' if report.get('stopped') else 'Đã lưu'
                    status.set(f'{prefix} {processed} công ty → {len(rows)} dòng email, {len(report["issues"])} mục cần rà soát.' + web_status)
                    start_button.configure(state='normal')
                    if 'web_research' in report and report['web_companies_matched'] == 0:
                        errors = list(dict.fromkeys(error for entry in report['web_research'] for error in entry['errors']))
                        messagebox.showwarning('Chưa lấy được thông tin web',
                            'Đã thử tra cứu nhưng chưa lấy được nguồn khớp MST cho công ty nào. '
                            'Kết quả xuất hiện chỉ dựa vào raw/taxonomy.\n\n'
                            + '\n'.join(errors[:4]) + '\n\nXem tab Nhật ký tra cứu web. '
                            'Với google_overview: kiểm tra Google có hiển thị Overview và tab Nhật ký. '
                            'Với website: có thể nhập Serper API key.')
        except queue.Empty:
            pass
        root.after(100, poll)
    ttk.Label(panel, textvariable=status, wraplength=1150).pack(anchor='w', pady=8)
    poll()
    root.mainloop()

if __name__ == '__main__':
    main()
