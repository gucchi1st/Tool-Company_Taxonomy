"""Giao diện bản GPT API độc lập."""
import json
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox
from gpt_pipeline import run_gpt, BASE, DEFAULT_MODEL, HEADERS

def main():
    root = tk.Tk()
    root.title('Chuẩn hóa công ty — GPT API (bản riêng)')
    root.geometry('1280x850')
    panel = ttk.Frame(root, padding=14)
    panel.pack(fill='both', expand=True)
    actions = ttk.Frame(panel)
    actions.pack(fill='x')
    stop = threading.Event()
    start = ttk.Button(actions, text='GPT tìm web và chuẩn hóa', command=lambda: process())
    start.pack(side='left')
    ttk.Button(actions, text='Dừng sau công ty đang xử lý', command=stop.set).pack(side='left', padx=8)
    ttk.Label(panel, text='Bản GPT API — tìm thông tin có nguồn, xuất 32 cột', font=('Segoe UI', 17, 'bold')).pack(anchor='w', pady=10)
    ttk.Label(panel, text='Tên công ty, MST, raw và taxonomy được gửi tới OpenAI. Có phí API và tìm kiếm web. Kết quả nằm trong thư mục run riêng.').pack(anchor='w')
    variables = {}
    specs = [('api_key', 'OpenAI API key (không lưu)', ''), ('model', 'Model (cần hỗ trợ web search và JSON Schema)', DEFAULT_MODEL),
             ('raw', 'Dữ liệu raw', str(BASE / 'data/raw.tsv')), ('taxonomy', 'Taxonomy', str(BASE / 'data/taxonomy.tsv')),
             ('output', 'Thư mục kết quả bản GPT', str(BASE / 'outputs')), ('limit', 'Số công ty tối đa lần này (mặc định 10)', '10')]
    for name, label, default in specs:
        frame = ttk.Frame(panel)
        frame.pack(fill='x', pady=3)
        ttk.Label(frame, text=label, width=49).pack(side='left')
        var = tk.StringVar(value=default)
        variables[name] = var
        ttk.Entry(frame, textvariable=var, show='*' if name == 'api_key' else '').pack(side='left', fill='x', expand=True)
        if name in {'raw', 'taxonomy', 'output'}:
            def browse(n=name, v=var):
                choice = filedialog.askdirectory() if n == 'output' else filedialog.askopenfilename()
                if choice:
                    v.set(choice)
            ttk.Button(frame, text='Chọn…', command=browse).pack(side='left', padx=5)
    resume = tk.BooleanVar(value=True)
    ttk.Checkbutton(panel, text='Dùng lại kết quả đã lưu nếu raw, taxonomy và model giống nhau (không gọi API lại)', variable=resume).pack(anchor='w', pady=5)
    status = tk.StringVar(value='Sẵn sàng. Nhập API key hoặc đặt biến môi trường OPENAI_API_KEY.')
    ttk.Label(panel, textvariable=status, wraplength=1200).pack(anchor='w', pady=5)
    tabs = ttk.Notebook(panel)
    tabs.pack(fill='both', expand=True)
    log = tk.Text(tabs, wrap='word')
    tabs.add(log, text='Nhật ký GPT')
    preview = ttk.Frame(tabs)
    tabs.add(preview, text='Kết quả 32 cột')
    tree = ttk.Treeview(preview, columns=HEADERS, show='headings')
    for header in HEADERS:
        tree.heading(header, text=header)
        tree.column(header, width=260)
    sx = ttk.Scrollbar(preview, orient='horizontal', command=tree.xview)
    sy = ttk.Scrollbar(preview, orient='vertical', command=tree.yview)
    tree.configure(xscrollcommand=sx.set, yscrollcommand=sy.set)
    sx.pack(side='bottom', fill='x')
    sy.pack(side='right', fill='y')
    tree.pack(fill='both', expand=True)
    audit_view = tk.Text(tabs, wrap='word')
    tabs.add(audit_view, text='Nguồn, thay đổi và usage')
    messages = queue.Queue()
    def process():
        options = {name: var.get().strip() for name, var in variables.items()}
        try:
            options['limit'] = int(options['limit'])
            if options['limit'] < 1:
                raise ValueError()
        except ValueError:
            messagebox.showerror('Số công ty không hợp lệ', 'Nhập số nguyên lớn hơn 0.')
            return
        if not options['api_key'] and not os.environ.get('OPENAI_API_KEY'):
            messagebox.showerror('Thiếu API key', 'Nhập OpenAI API key trong ô che ký tự hoặc đặt OPENAI_API_KEY. Không gửi key trong chat.')
            return
        options['resume'] = resume.get()
        stop.clear()
        start.configure(state='disabled')
        log.delete('1.0', 'end')
        tabs.select(log)
        status.set('Đang xử lý…')
        def worker():
            try:
                result = run_gpt(**options, progress=lambda text: messages.put(('log', text)), cancelled=stop.is_set)
                messages.put(('done', result))
            except Exception as exc:
                messages.put(('error', str(exc)))
        threading.Thread(target=worker, daemon=True).start()
    def poll():
        try:
            while True:
                kind, value = messages.get_nowait()
                if kind == 'log':
                    status.set(value)
                    log.insert('end', value + '\n')
                    log.see('end')
                elif kind == 'error':
                    start.configure(state='normal')
                    status.set(value)
                    log.insert('end', 'LỖI: ' + value + '\n')
                    messagebox.showerror('GPT API', value)
                else:
                    rows, report, folder = value
                    start.configure(state='normal')
                    tree.delete(*tree.get_children())
                    for row in rows:
                        tree.insert('', 'end', values=row)
                    audit_view.delete('1.0', 'end')
                    audit_view.insert('1.0', json.dumps(report, ensure_ascii=False, indent=2))
                    status.set(f'Đã lưu {len(rows)} công ty tại {folder}. Lỗi cần rà soát: {len(report["issues"])}.')
        except queue.Empty:
            pass
        root.after(100, poll)
    poll()
    root.mainloop()

if __name__ == '__main__':
    main()
