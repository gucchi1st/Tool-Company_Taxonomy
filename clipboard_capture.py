"""Copy toàn trang bằng bàn phím, chỉ đọc clipboard vừa được cập nhật."""
import ctypes
from ctypes import wintypes


def windows_clipboard():
    user=ctypes.WinDLL('user32',use_last_error=True)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    user.GetClipboardSequenceNumber.restype=wintypes.DWORD
    user.OpenClipboard.argtypes=[wintypes.HWND]
    user.GetClipboardData.argtypes=[wintypes.UINT]
    user.GetClipboardData.restype=wintypes.HANDLE
    kernel.GlobalLock.argtypes=[wintypes.HGLOBAL]
    kernel.GlobalLock.restype=ctypes.c_void_p
    kernel.GlobalUnlock.argtypes=[wintypes.HGLOBAL]
    return user,kernel


def copy_page_text(page, cancelled=lambda:False):
    user,kernel=windows_clipboard()
    before=user.GetClipboardSequenceNumber()
    page.bring_to_front()
    # Bỏ focus ô nhập để Ctrl+A chọn trang thay vì chọn prompt.
    page.evaluate('''()=>{
      document.activeElement?.blur();
      const body=document.body;
      const old=body.getAttribute('tabindex');
      body.setAttribute('tabindex','-1');body.focus();
      if(old===null)body.removeAttribute('tabindex');else body.setAttribute('tabindex',old);
    }''')
    page.keyboard.press('Control+a')
    page.keyboard.press('Control+c')
    try:
        for _ in range(20):
            if cancelled(): raise InterruptedError('Đã dừng copy ChatGPT')
            if user.GetClipboardSequenceNumber()!=before and user.OpenClipboard(None):
                try:
                    handle=user.GetClipboardData(13)  # CF_UNICODETEXT
                    address=kernel.GlobalLock(handle) if handle else None
                    if address:
                        try: return ctypes.wstring_at(address)
                        finally: kernel.GlobalUnlock(handle)
                finally:
                    user.CloseClipboard()
            page.wait_for_timeout(100)
        return ''
    finally:
        page.evaluate('()=>window.getSelection()?.removeAllRanges()')
