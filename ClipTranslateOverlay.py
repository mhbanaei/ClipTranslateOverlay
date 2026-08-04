# -*- coding: utf-8 -*-
"""
ClipTranslate Popup — نسخه ساده و بهینه‌شده

با هر اسکرین‌شات (PrintScreen، Win+Shift+S یا Ctrl+C روی یک عکس):
  1) یک پنجره‌ی کوچک پاپ‌آپ باز می‌شود و صفحه Google Translate (حالت تصویر) را نشان می‌دهد
  2) عکس با یک Ctrl+V واقعی (نه با اسکریپت جاوااسکریپتی) داخل صفحه Paste می‌شود
  3) ترجمه مستقیماً همان‌جا داخل صفحه‌ی خودِ گوگل نمایش داده می‌شود
  4) Alt+Q → پنهان‌کردن پاپ‌آپ (برنامه در پس‌زمینه/System Tray فعال می‌ماند)

تغییرات نسبت به نسخه قبل:
  - رفع خطای:
        TypeError: WebView.RunScriptAsync(): argument 2 has unexpected type 'str'
    با حذف کامل تزریق اسکریپت برای چک‌کردن دکمه دانلود؛ دیگر لازم نیست چون
    ترجمه مستقیم در همان صفحه گوگل دیده می‌شود.
  - رفع پاپ‌آپ آزاردهنده‌ی "اجازه دسترسی به کلیپ‌بورد" کروم/ادج:
    علت اصلی این بود که browser.Paste() از طریق execCommand('paste') در جاوااسکریپت
    اجرا می‌شد که کرومیوم آن را غیرقابل‌اعتماد می‌داند و درخواست permission می‌کند.
    در نسخه جدید به‌جای آن از wx.UIActionSimulator برای کلیک + فشردن واقعی Ctrl+V
    در سطح سیستم‌عامل استفاده شده (دقیقاً مثل این‌که خودتان دستی Ctrl+V بزنید)
    که از دید مرورگر کاملاً "trusted" است و permission نمی‌خواهد.
  - زبان مبدا = تشخیص خودکار (auto) و زبان مقصد = فارسی (fa)، هر دو ثابت.
  - پنجره اصلی دیگر Iconize/مخفی نمی‌شود (چون فوکوس واقعی برای Ctrl+V لازم دارد)،
    به‌جایش یک آیکون کوچک در System Tray برای نمایش دوباره یا خروج تمیز اضافه شده.
  - حذف کامل منطق دانلود فایل/پارس پوشه Downloads/ساخت Overlay دستی از تصویر
    (نیازی به آن نبود چون گوگل خودش تصویر ترجمه‌شده را داخل صفحه نشان می‌دهد).

وابستگی‌ها:
    pip install wxPython pillow keyboard
نیازمند Microsoft Edge WebView2 Runtime (روی اغلب ویندوزهای ۱۰/۱۱ از قبل نصب است)
"""

import time
import threading
import hashlib

import wx
import wx.html2
import wx.adv
import keyboard
from PIL import ImageGrab, Image

# زبان مبدا: تشخیص خودکار / زبان مقصد: فارسی (طبق درخواست، ثابت و غیرقابل تغییر)
SOURCE_LANG = "auto"
TARGET_LANG = "fa"
TRANSLATE_URL = f"https://translate.google.com/?sl={SOURCE_LANG}&tl={TARGET_LANG}&op=images&hl=fa"

POPUP_SIZE = (520, 720)
PASTE_DELAY_MS = 900       # فاصله بین لود صفحه و پیست، تا دراپ‌زون تصویر آماده تعامل شود
CLIPBOARD_POLL_SEC = 0.5


# ----------------------------------------------------------------------
# پنجره‌ی پاپ‌آپ حاوی مرورگر گوگل ترنسلیت
# ----------------------------------------------------------------------
class TranslatePopup(wx.Frame):
    def __init__(self):
        style = (wx.DEFAULT_FRAME_STYLE | wx.STAY_ON_TOP) & ~wx.MAXIMIZE_BOX
        super().__init__(None, title="ترجمه تصویر  —  Alt+Q برای بستن",
                          size=POPUP_SIZE, style=style)

        panel = wx.Panel(self)
        self.status = wx.StaticText(panel, label="")
        self.browser = wx.html2.WebView.New(panel)
        self.browser.Bind(wx.html2.EVT_WEBVIEW_LOADED, self.on_loaded)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.status, 0, wx.ALL | wx.EXPAND, 6)
        sizer.Add(self.browser, 1, wx.EXPAND)
        panel.SetSizer(sizer)

        self._pasted_once = False
        self.Bind(wx.EVT_CLOSE, self.on_close_attempt)
        self._position_top_right()

    def _position_top_right(self):
        screen_w, _ = wx.GetDisplaySize()
        self.SetPosition((max(0, screen_w - POPUP_SIZE[0] - 20), 20))

    def start_translation(self):
        """صفحه گوگل ترنسلیت را بارگذاری می‌کند و پس از لود، عکس را پیست می‌کند."""
        self._pasted_once = False
        self.status.SetLabel("در حال بارگذاری Google Translate...")
        self.Show()
        self.Raise()
        self.browser.LoadURL(TRANSLATE_URL)

    def on_loaded(self, event):
        if self._pasted_once:
            return
        wx.CallLater(PASTE_DELAY_MS, self._real_paste)

    def _real_paste(self):
        if self._pasted_once or not self.IsShown():
            return
        self._pasted_once = True

        self.Raise()
        self.browser.SetFocus()

        sim = wx.UIActionSimulator()
        bx, by = self.browser.GetScreenPosition()
        bw, bh = self.browser.GetSize()
        # کلیک روی نیمه‌ی بالایی مرورگر تا فوکوس واقعی روی دراپ‌زون تصویر بیفتد
        sim.MouseMove(bx + bw // 2, by + bh // 3)
        sim.MouseClick()
        wx.MilliSleep(200)

        # Ctrl+V واقعی در سطح سیستم‌عامل (نه اجرای execCommand جاوااسکریپتی)
        # همین تفاوت باعث می‌شود کروم/ادج دیگر پاپ‌آپ "اجازه دسترسی کلیپ‌بورد" ندهد
        sim.Char(ord('V'), wx.MOD_CONTROL)

        self.status.SetLabel("در حال ترجمه توسط گوگل...")
        wx.CallLater(2500, lambda: self.status.SetLabel("آماده — Alt+Q برای بستن"))

    def on_close_attempt(self, event):
        # به‌جای بستن کامل، فقط مخفی می‌شود تا پایش کلیپ‌بورد در پس‌زمینه ادامه پیدا کند
        self.Hide()


# ----------------------------------------------------------------------
# آیکون System Tray برای مدیریت ساده برنامه (نمایش دوباره / خروج)
# ----------------------------------------------------------------------
class TrayIcon(wx.adv.TaskBarIcon):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        bmp = wx.ArtProvider.GetBitmap(wx.ART_TIP, wx.ART_OTHER, (16, 16))
        self.SetIcon(wx.Icon(bmp), "ClipTranslate — در حال پایش کلیپ‌بورد")
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DCLICK, lambda e: self.controller.show_popup())

    def CreatePopupMenu(self):
        menu = wx.Menu()

        item_show = menu.Append(wx.ID_ANY, "نمایش پنجره ترجمه")
        self.Bind(wx.EVT_MENU, lambda e: self.controller.show_popup(), item_show)

        menu.AppendSeparator()
        item_exit = menu.Append(wx.ID_EXIT, "خروج")
        self.Bind(wx.EVT_MENU, lambda e: self.controller.quit(), item_exit)

        return menu


# ----------------------------------------------------------------------
# کنترلر اصلی: پایش کلیپ‌بورد + مدیریت پاپ‌آپ و Tray
# ----------------------------------------------------------------------
class ClipTranslateApp(wx.Frame):
    def __init__(self):
        super().__init__(None)  # فریم نامرئی، فقط برای زنده نگه‌داشتن اپ

        self.popup = TranslatePopup()
        self.tray = TrayIcon(self)

        self.monitor_active = True
        self.processing = False
        self.last_hash = None

        keyboard.add_hotkey("alt+q", lambda: wx.CallAfter(self.popup.Hide))
        self._start_clipboard_monitor()

    # ---------------- پایش کلیپ‌بورد ----------------
    def _start_clipboard_monitor(self):
        def monitor():
            while self.monitor_active:
                try:
                    if not self.processing:
                        candidate = self._extract_clipboard_image()
                        if candidate is not None:
                            h = self._hash_image(candidate)
                            if h and h != self.last_hash:
                                self.last_hash = h
                                self.processing = True
                                wx.CallAfter(self._on_new_screenshot)
                except Exception as e:
                    print(f"خطای پایش کلیپ‌بورد: {e}")
                time.sleep(CLIPBOARD_POLL_SEC)

        threading.Thread(target=monitor, daemon=True).start()

    @staticmethod
    def _extract_clipboard_image():
        img = ImageGrab.grabclipboard()
        if isinstance(img, Image.Image):
            return img
        if isinstance(img, list):
            for f in img:
                if f.lower().endswith((".png", ".jpg", ".jpeg", ".bmp")):
                    try:
                        return Image.open(f)
                    except Exception:
                        continue
        return None

    @staticmethod
    def _hash_image(img):
        try:
            data = img.convert("RGB").resize((64, 64)).tobytes()
            return hashlib.md5(data).hexdigest()
        except Exception:
            return None

    def _on_new_screenshot(self):
        self.popup.start_translation()
        # کمی بعد قفل پردازش را آزاد می‌کنیم تا اسکرین‌شات بعدی هم شناسایی شود
        wx.CallLater(1500, self._release_lock)

    def _release_lock(self):
        self.processing = False

    # ---------------- کنترل پنجره ----------------
    def show_popup(self):
        self.popup.Show()
        self.popup.Raise()

    def quit(self):
        self.monitor_active = False
        keyboard.unhook_all_hotkeys()
        self.tray.RemoveIcon()
        self.tray.Destroy()
        self.popup.Destroy()
        self.Destroy()


if __name__ == "__main__":
    app = wx.App()
    controller = ClipTranslateApp()
    app.MainLoop()
