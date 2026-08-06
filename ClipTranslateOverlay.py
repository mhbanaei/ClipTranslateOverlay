# -*- coding: utf-8 -*-
"""
42OCR Overlay — ترجمه‌ی تصویر در پس‌زمینه + Overlay + تنظیمات
=============================================================

با این نسخه، برنامه کاملاً در پس‌زمینه کار می‌کند و دیگر پنجره‌ی Google Translate
روی صفحه دیده نمی‌شود:

  1) با هر اسکرین‌شات (PrintScreen / Win+Shift+S / Ctrl+C روی یک عکس)، ابزار
     اسکرین‌شات داخلی (کلید پیش‌فرض F3، قابل تغییر از تنظیمات) یا انتخاب
     «ترجمه با فایل…» از منوی تسک‌بار:
       - عکس به‌صورت خودکار (با تزریق رویداد paste در سطح صفحه، بدون نیاز به
         فوکوس پنجره) داخل صفحه‌ی مخفی Google Translate (حالت تصویر) بارگذاری می‌شود
       - تصویر ترجمه‌شده از داخل همان صفحه استخراج و در پوشه‌ی انتخابی شما ذخیره می‌شود
       - بلافاصله به‌صورت یک Overlay شناور (بالای همه‌ی پنجره‌ها) به شما نشان داده می‌شود
  2) کلید میانبر قابل‌تنظیم (پیش‌فرض F2) → بستن Overlay — و زوم روی خروجی ترجمه
  3) منوی تسک‌بار (شیشه‌ای و راست‌چین): تنظیمات / اسکرین‌شات / ترجمه با فایل… / خروج
  4) پنجره‌ی تنظیمات کامل: کلید میانبر، زبان مقصد، پوشه‌ی ذخیره، بستن خودکار،
     اعلان‌ها و اجرای خودکار با شروع ویندوز (ریجستری)

وابستگی‌ها:
    pip install wxPython pillow keyboard
نیازمند Microsoft Edge WebView2 Runtime (روی اغلب ویندوزهای ۱۰/۱۱ از قبل نصب است)

استفاده:
    python ClipTranslateOverlay.py
    python ClipTranslateOverlay.py --selftest   (تست خودکار کل مسیر ترجمه بدون نیاز به کلیپ‌بورد)
"""

import base64
import ctypes
import ctypes.wintypes
import hashlib
import io
import json
import os
import shutil
import sys
import threading
import time
import webbrowser
from datetime import datetime

import wx
import wx.adv
import wx.html2
import keyboard
from PIL import Image, ImageDraw, ImageFont, ImageGrab

if sys.stdout is None:  # در exe بدون کنسول (PyInstaller windowed) print خراب نمی‌شود
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ----------------------------------------------------------------------
# رنگ‌ها و ثابت‌های ظاهری (سبک 42LEVEL)
# ----------------------------------------------------------------------
BG       = wx.Colour(14, 12, 14)      # پس‌زمینه اصلی (مشکی-سرخ، سبک 42LEVEL)
PANEL    = wx.Colour(26, 22, 26)      # کارت/پنل
CARD     = wx.Colour(33, 27, 32)      # کارت تیره‌تر
BORDER   = wx.Colour(58, 44, 50)      # خط مرز
ACCENT   = wx.Colour(255, 45, 60)     # قرمز نئونی اصلی
ACCENT_D = wx.Colour(196, 28, 44)     # قرمز تیره (hover)
TEXT     = wx.Colour(240, 236, 238)
MUTED    = wx.Colour(168, 152, 158)
SUCCESS  = wx.Colour(52, 201, 142)
DANGER   = wx.Colour(255, 93, 108)
WARN     = wx.Colour(255, 184, 77)


def hover_bg():
    """رنگ پس‌زمینه‌ی hover (قرمز تیره برای تم اصلی)."""
    return ACCENT.ChangeLightness(88)


# ----------------------------------------------------------------------
# فونت وزیر (Vazirmatn) — فارسی‌دوست و راست‌چین، با جایگزین امن
# ----------------------------------------------------------------------
_VAZIR_FACE = None
_VAZIR_TRY = False
_FONT_CACHE = {}
_ADDED_FONTS = set()


def _font_candidates():
    win_dir = os.environ.get("WINDIR") or r"C:\Windows"
    local = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts")
    names = ("Vazirmatn-Regular.ttf", "Vazirmatn-Medium.ttf", "Vazir-Regular.ttf")
    out = []
    for n in names:
        out.append(os.path.join(ASSETS_DIR, "fonts", n))
        out.append(os.path.join(win_dir, "Fonts", n))
        out.append(os.path.join(local, n))
    out.append(os.path.join(win_dir, "Fonts", "LMU Vazir.ttf"))
    return out


def _find_vazir_file():
    for p in _font_candidates():
        if p and os.path.isfile(p):
            return p
    try:
        for base in (os.path.join(os.environ.get("WINDIR") or r"C:\Windows", "Fonts"),
                     os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts")):
            if os.path.isdir(base):
                for fn in os.listdir(base):
                    low = fn.lower()
                    if low.startswith(("vazir", "vazirmatn")) and low.endswith((".ttf", ".otf")):
                        return os.path.join(base, fn)
    except Exception:
        pass
    return None


def _download_vazir():
    """اگر فونت وزیر در سیستم نبود، یک نسخه دانلود و در پوشه‌ی برنامه نگه می‌دارد."""
    try:
        dst_dir = os.path.join(ASSETS_DIR, "fonts")
        os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, "Vazirmatn-Regular.ttf")
        if os.path.isfile(dst) and os.path.getsize(dst) > 100000:
            return dst
        import urllib.request
        url = ("https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@v33.003/"
               "fonts/ttf/Vazirmatn-Regular.ttf")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r, open(dst, "wb") as f:
            f.write(r.read())
        return dst if os.path.getsize(dst) > 100000 else None
    except Exception:
        return None


def _ensure_vazir_face():
    global _VAZIR_FACE, _VAZIR_TRY
    if _VAZIR_TRY:
        return _VAZIR_FACE
    _VAZIR_TRY = True
    path = _find_vazir_file() or _download_vazir()
    if not path:
        return None
    try:
        if path not in _ADDED_FONTS:
            if ctypes.windll.gdi32.AddFontResourceW(path):
                _ADDED_FONTS.add(path)
        base = os.path.basename(path).lower()
        _VAZIR_FACE = "Vazirmatn" if "vazirmatn" in base else "Vazir"
    except Exception:
        _VAZIR_FACE = None
    return _VAZIR_FACE


def ui_font(size, bold=False, italic=False):
    """فونت رابط: وزیر (Vazirmatn) و در نبودش Segoe UI — کش‌شده برای کارایی."""
    key = (size, bold, italic)
    f = _FONT_CACHE.get(key)
    if f is None:
        f = wx.Font(size, wx.FONTFAMILY_DEFAULT,
                    wx.ITALIC if italic else wx.NORMAL,
                    wx.BOLD if bold else wx.NORMAL,
                    False, _ensure_vazir_face() or "Segoe UI")
        _FONT_CACHE[key] = f
    return f


# ----------------------------------------------------------------------
# افکت شیشه‌ای (Acrylic ویندوز ۱۰/۱۱) با جایگزین امن
# ----------------------------------------------------------------------
GLASS_ACRYLIC = False


def enable_acrylic(hwnd, rgb, opacity=0xB8):
    """Acrylic/Blur پشت پنجره؛ اگر پشتیبانی نشود False برمی‌گردد."""
    global GLASS_ACRYLIC
    try:
        if not hwnd:
            return False

        class ACCENT_POLICY(ctypes.Structure):
            _fields_ = [("AccentState", ctypes.c_int), ("AccentFlags", ctypes.c_int),
                        ("GradientColor", ctypes.c_uint), ("AnimationId", ctypes.c_int)]

        class WCA_DATA(ctypes.Structure):
            _fields_ = [("Attribute", ctypes.c_int), ("Data", ctypes.c_void_p),
                        ("SizeOfData", ctypes.c_size_t)]

        accent = ACCENT_POLICY()
        accent.AccentFlags = 2
        accent.GradientColor = ((opacity & 0xFF) << 24) | \
                               ((rgb[0] & 0xFF) | ((rgb[1] & 0xFF) << 8) | ((rgb[2] & 0xFF) << 16))
        data = WCA_DATA()
        data.Attribute = 19                       # WCA_ACCENT_POLICY
        data.Data = ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p)
        data.SizeOfData = ctypes.sizeof(accent)
        set_accent = ctypes.windll.user32.SetWindowCompositionAttribute
        for state in (4, 3):                      # Acrylic (Win11) → Blur (Win10)
            accent.AccentState = state
            if set_accent(ctypes.c_void_p(hwnd), ctypes.byref(data)):
                if state == 4:
                    GLASS_ACRYLIC = True
                return True
        return False
    except Exception:
        return False


def apply_glass(win, opacity=0xB8):
    """روی پنجره افکت شیشه‌ای می‌گذارد؛ برمی‌گرداند: آلفای رنگ پس‌زمینه (۲۵۵ = بدون شیشه)."""
    try:
        hwnd = win.GetHandle()
    except Exception:
        hwnd = None
    if hwnd and enable_acrylic(hwnd, (BG.Red(), BG.Green(), BG.Blue()), opacity):
        return 238
    try:
        win.SetTransparent(246)                   # جایگزین: شفافیت ملایم کل پنجره
    except Exception:
        pass
    return 255


def glass_color(bg, alpha=238):
    """رنگ شیشه‌ای؛ اگر Acrylic در دسترس نباشد رنگ توپر برمی‌گردد."""
    if GLASS_ACRYLIC:
        return wx.Colour(bg.Red(), bg.Green(), bg.Blue(), alpha)
    return bg


def draw_rounded_glass(dc, w, h, radius, bg, border=None, border_w=1, alpha=238):
    """مستطیل گرد با پس‌زمینه‌ی شیشه‌ای + حاشیه (برای منوها و پاپ‌آپ‌ها)."""
    gc = wx.GraphicsContext.Create(dc)
    gc.SetAntialiasMode(wx.ANTIALIAS_DEFAULT)
    gc.SetBrush(wx.Brush(glass_color(bg, alpha)))
    gc.SetPen(wx.Pen(border, border_w) if border else wx.TRANSPARENT_PEN)
    gc.DrawRoundedRectangle(0, 0, max(1, w), max(1, h), radius)


# ----------------------------------------------------------------------
# نوتیفیکیشن شیشه‌ای پایین صفحه (Toast)
# ----------------------------------------------------------------------
class Toast(wx.Frame):
    W, H = 336, 68
    SHOW_MS = 4200
    FADE_STEPS = 16
    FADE_TICK_MS = 26

    def __init__(self, app):
        style = (wx.FRAME_NO_TASKBAR | wx.STAY_ON_TOP | wx.FRAME_SHAPED |
                 wx.BORDER_NONE | wx.POPUP_WINDOW)
        super().__init__(None, size=(self.W, self.H), style=style)
        self.app = app
        self._timer = None
        self._fade_timer = None
        self._fade = 0
        self._title = ""
        self._subtitle = ""
        self._icon_bmp = make_app_bitmap(30)
        self._glass_alpha = apply_glass(self)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        try:
            self.SetShape(rounded_region(self.W, self.H, 14))
        except Exception:
            pass
        self.Hide()

    def _on_paint(self, evt):
        dc = wx.PaintDC(self)
        w, h = self.GetSize()
        draw_rounded_glass(dc, w, h, 14, PANEL, border=ACCENT, border_w=1,
                           alpha=self._glass_alpha)
        dc.DrawBitmap(self._icon_bmp, w - 48, (h - 30) // 2)
        dc.SetFont(ui_font(11, bold=True))
        dc.SetTextForeground(TEXT)
        tw = dc.GetTextExtent(self._title)[0]
        dc.DrawText(self._title, w - 62 - tw, 12)
        if self._subtitle:
            dc.SetFont(ui_font(9))
            dc.SetTextForeground(MUTED)
            sw_ = dc.GetTextExtent(self._subtitle)[0]
            dc.DrawText(self._subtitle, w - 62 - sw_, 38)

    def show_toast(self, title, subtitle=""):
        self._stop_timers()
        self._title = title
        self._subtitle = subtitle
        sw, sh = wx.GetDisplaySize()
        self.SetPosition((sw - self.W - 24, sh - self.H - 56))
        self.Refresh()
        self.Show()
        self.Raise()
        if GLASS_ACRYLIC:
            try:
                self.SetTransparent(255)
            except Exception:
                pass
        self._timer = wx.CallLater(self.SHOW_MS, self._start_fade)

    def _start_fade(self):
        self._fade = self.FADE_STEPS
        self._fade_timer = wx.CallLater(self.FADE_TICK_MS, self._fade_tick)

    def _fade_tick(self):
        if self._fade <= 0:
            self.hide_toast()
            return
        try:
            self.SetTransparent(int(255 * (self._fade / self.FADE_STEPS)))
        except Exception:
            pass
        self._fade -= 1
        self._fade_timer = wx.CallLater(self.FADE_TICK_MS, self._fade_tick)

    def hide_toast(self):
        self._stop_timers()
        if self.IsShown():
            self.Hide()

    def _stop_timers(self):
        for t in (self._timer, self._fade_timer):
            if t is not None:
                try:
                    if t.IsRunning():
                        t.Stop()
                except Exception:
                    pass
        self._timer = self._fade_timer = None

HIDDEN_POS = (-32000, -32000)          # موقعیت «خارج از صفحه» برای مرورگر مخفی
POLL_INTERVAL_MS = 900                 # فاصله‌ی چک‌کردن نتیجه در مرورگر مخفی
TRANSLATE_TIMEOUT_S = 30               # حداکثر انتظار برای ترجمه (بعدش با خطای قابل‌تلاش بسته می‌شود)

LANGUAGES = [
    ("fa",    "فارسی"),
    ("en",    "انگلیسی"),
    ("ar",    "عربی"),
    ("tr",    "ترکی استانبولی"),
    ("de",    "آلمانی"),
    ("fr",    "فرانسوی"),
    ("es",    "اسپانیایی"),
    ("ru",    "روسی"),
    ("it",    "ایتالیایی"),
    ("hi",    "هندی"),
    ("ur",    "اردو"),
    ("az",    "آذربایجانی"),
    ("zh-CN", "چینی ساده‌شده"),
    ("ja",    "ژاپنی"),
    ("ko",    "کرِه‌ای"),
]

DEFAULT_AUTO_CLOSE_S = 60


# ----------------------------------------------------------------------
# زبان رابط (فارسی / انگلیسی) — ترجمه‌ی تمام متن‌های کاربری
# ----------------------------------------------------------------------
UI_LANG = "fa"   # زبان جاری رابط (fa یا en)

# ترجمه‌های انگلیسی: کلید = متن فارسی (دقیقاً همان که در کد است)؛
# اگر کلیدی در این جدول نبود، متن فارسی خودش برمی‌گردد (هیچ‌وقت خطا نمی‌دهد)
EN_TEXTS = {
    # --- پنجره‌ی تنظیمات ---
    "تنظیمات Level Translator": "Level Translator Settings",
    "میانبرها": "Hotkeys",
    "ترجمه و ذخیره‌سازی": "Translation & Saving",
    "نمایش و اسکرین‌شات": "Display & Screenshot",
    "سیستم": "System",
    "پیشرفته": "Advanced",
    "زبان رابط": "Interface Language",
    "زبان رابط برنامه": "App Interface Language",
    "فارسی / English — کل برنامه به زبان انتخابی درمی‌آید": "Persian / English — the whole app switches instantly",
    "بستن عکس ترجمه — برای تغییر کلیک کنید و کلید جدید را بزنید": "Close translated image — click and press a new key",
    "گرفتن اسکرین‌شات — برای تغییر کلیک کنید و کلید جدید را بزنید": "Take a screenshot — click and press a new key",
    "زبان مقصد ترجمه": "Target language",
    "تشخیص خودکار زبان مبدأ": "Source language is auto-detected",
    "باز کردن": "Open",
    "انتخاب پوشه…": "Choose folder…",
    "بستن خودکار پس از": "Auto-close after",
    "مخفی شدن خودکار نشانک بازی پس از": "Auto-hide the game badge after",
    "نوار «42OCR فعال است» بالای بازی بعد از این مدت خودکار مخفی می‌شود": "The '42OCR active' bar above the game hides automatically after this",
    "ثانیه (۰ = خاموش)": "seconds (0 = off)",
    "انتخاب پنجره…": "Pick a window…",
    "مثلاً بازی فول‌اسکرین خود را انتخاب کنید؛ با {0} فقط از همان پنجره عکس کامل گرفته می‌شود": "e.g. pick your fullscreen game; {0} will capture that window only",
    "نمایش اعلان هنگام آماده‌شدن ترجمه": "Show a notification when the translation is ready",
    "اجرای برنامه با هر بار استارت ویندوز": "Run the app at Windows startup",
    "با تیک زدن، یک ورودی در ریجستری استارت‌آپ ویندوز ساخته می‌شود": "Checking this adds an entry to the Windows startup registry",
    "پاک‌سازی کامل پوشه‌ی ذخیره هنگام بستن برنامه": "Permanently wipe the save folder when the app closes",
    "همه‌ی عکس‌های ترجمه‌شده حذف دائمی می‌شوند (بدون بازیابی، مثل Shift+Delete)": "All translated images are permanently deleted (no recovery, like Shift+Delete)",
    "باز کردن پوشه‌ی تنظیمات": "Open the settings folder",
    "ذخیره تنظیمات": "Save Settings",
    "انصراف": "Cancel",
    "… کلید را بزنید": "… press a key",
    "در حال ضبط… (Esc = انصراف)": "Recording… (Esc = cancel)",
    "برای تغییر کلیک کنید و کلید (یا ترکیب) جدید را بزنید": "Click and press a new key (or combination)",
    "پوشه‌ی ذخیره‌ی ترجمه‌ها": "Translation save folder",
    "هیچ پنجره‌ای انتخاب نشده — {0} حالت مربع‌کشی دارد": "No window selected — {0} uses rectangle mode",
    # --- مدیریت فرآیندها ---
    "مدیریت فرآیندها — انتخاب پنجره‌ی هدف": "Process Manager — pick a target window",
    "پنجره‌ی بازی/برنامه‌ای که می‌خواهید اسکرین‌شات فقط از آن گرفته شود را انتخاب کنید؛\nبعد از انتخاب، با زدن {0} عکس کامل همان پنجره به کلیپ‌بورد می‌رود و ترجمه می‌شود.": "Pick the game/app window that screenshots should be taken only from;\nafter that, pressing {0} copies a full capture of that window and translates it.",
    "پنجره": "Window",
    "فرآیند": "Process",
    "تازه‌سازی": "Refresh",
    "حذف انتخاب": "Clear selection",
    "انتخاب": "Select",
    "تزریق به بازی": "Inject into game",
    "تزریق = انتخاب پنجره + آوردن بازی به جلو + فعال‌شدن منوی شناور 42OCR داخل بازی": "Inject = pick a window + bring the game to front + enable the 42OCR floating menu inside the game",
    "(بدون عنوان)": "(no title)",
    # --- منوی تسک‌بار ---
    "توقف موقت پایش کلیپ‌بورد": "Pause clipboard monitoring",
    "ادامه‌ی پایش کلیپ‌بورد": "Resume clipboard monitoring",
    "پایش کلیپ‌بورد: روشن": "Clipboard monitoring: ON",
    "پایش کلیپ‌بورد: متوقف": "Clipboard monitoring: paused",
    "تنظیمات…": "Settings…",
    "گرفتن اسکرین‌شات ({0})": "Take a screenshot ({0})",
    "مدیریت فرآیندها…": "Process manager…",
    "خروج": "Exit",
    "42 Level Translator — ترجمه‌ی تصویر در پس‌زمینه": "42 Level Translator — background image translation",
    "Level Translator — پایش روشن": "Level Translator — monitoring ON",
    "Level Translator — پایش متوقف است": "Level Translator — monitoring paused",
    # --- منوی داخل بازی ---
    "پایش: روشن": "Monitor: ON",
    "ترجمه از بازی": "Translate from the game",
    "اسکرین‌شات ({0})": "Screenshot ({0})",
    "در حال ترجمه…": "Translating…",
    "ترجمه آماده ✓": "Translation ready ✓",
    "خطا — دوباره تلاش کنید": "Error — try again",
    "42OCR فعال است  •  PrtSc = اسکرین‌شات از بازی": "42OCR active  •  PrtSc = capture from the game",
    # --- پاپ‌آپ خوش‌آمدگویی ---
    "از همراهی شما سپاسگزاریم ♥ — با فالو کردن از ما حمایت کنید:": "Thank you for joining us ♥ — support us by following:",
    "کلیک روی هر مورد، پیوند را در مرورگر باز می‌کند": "Clicking any item opens the link in your browser",
    "درگاه حمایت مالی": "Support page",
    "کانال یوتیوب": "YouTube channel",
    "گیت‌هاب": "GitHub",
    "کانال توییچ": "Twitch channel",
    "برنامه کوچک شد — در تسک‌بار است": "App minimized — it's in the tray",
    "من اینجا (کنار ساعت ویندوز) هستم؛ با کلیک راست روی آیکون، منو باز می‌شود": "I'm here (next to the Windows clock); right-click the icon to open the menu",
    "42 Level Translator — ترجمه‌ی تصویر در پس‌زمینه": "42 Level Translator — background image translation",
    # --- Overlay ترجمه ---
    "کپی": "Copy",
    "ترجمه آماده است": "Translation ready",
    "خطا": "Error",
    "کپی شد ✓": "Copied ✓",
    "برای بستن: {0}  |  قابلیت جابه‌جایی با درگ": "Close: {0}  |  Draggable",
    "ذخیره شد: {0}": "Saved: {0}",
    "یک ترجمه در حال انجام است؛ کمی صبر کنید.": "A translation is already running; please wait.",
    "ترجمه آماده شد": "Translation ready",
    "تصویر ترجمه‌شده در پوشه‌ی ذخیره ثبت شد.": "The translated image was saved to the save folder.",
    "خطا در ذخیره‌ی تصویر: {0}": "Error saving the image: {0}",
    # --- ابزار اسکرین‌شات ---
    "برای انتخاب، کلیک کنید و بکشید   —   Esc = انصراف": "Click and drag to select   —   Esc = cancel",
    "گرفتن عکس صفحه ممکن نشد": "Couldn't capture the screen",
    "دوباره با {0} تلاش کنید": "Try again with {0}",
    "اسکرین‌شات گرفته شد": "Screenshot taken",
    "تصویر به کلیپ‌بورد رفت و در حال ترجمه است…": "Image copied to the clipboard and translating…",
    "اسکرین‌شات از پنجره گرفته شد": "Window screenshot taken",
    "تصویر کامل پنجره به کلیپ‌بورد رفت و در حال ترجمه است…": "Full window image copied to the clipboard and translating…",
    # --- کارگر ترجمه / وضعیت‌ها ---
    "خطا در بارگذاری صفحه‌ی گوگل": "Error loading the Google page",
    "در حال بارگذاری Google Translate…": "Loading Google Translate…",
    "خطا در بارگذاری صفحه‌ی گوگل؛ اتصال اینترنت را بررسی کنید.": "Error loading the Google page; check your internet connection.",
    "بارگذاری مجدد Google Translate… ({0}/4)": "Reloading Google Translate… ({0}/4)",
    "در حال ارسال تصویر…": "Sending image…",
    "خطا در تزریق تصویر: {0}": "Error injecting the image: {0}",
    "در حال ترجمه توسط گوگل…": "Translating by Google…",
    "گوگل تصویر را نپذیرفت؛ دوباره تلاش کنید.": "Google rejected the image; try again.",
    "گوگل پاسخ نداد؛ اتصال اینترنت را بررسی کنید.": "Google didn't respond; check your internet connection.",
    "ترجمه انجام نشد (زمان‌بندی گوگل طول کشید). دوباره تلاش کنید.": "Translation failed (Google timed out). Try again.",
    # --- پیام‌های برنامه‌ی اصلی ---
    "خطای پایش کلیپ‌بورد: {0}": "Clipboard monitor error: {0}",
    "پنجره‌ی هدف پیدا نشد": "Target window not found",
    "بازی بسته شده؛ دوباره از «مدیریت فرآیندها» انتخاب کنید": "The game is closed; pick it again from the Process Manager",
    "پنجره‌ی هدفی انتخاب نشده": "No target window selected",
    "از منوی تسک‌بار → «مدیریت فرآیندها» یک پنجره انتخاب کنید": "From the tray menu → Process Manager, pick a window",
    "تزریق به پروسس انجام شد": "Injected into the process",
    "بازی به جلو آمد؛ منوی شناور 42OCR داخل بازی فعال است — PrtSc = عکس از بازی": "Game brought to front; the 42OCR floating menu is active — PrtSc = capture from the game",
    "پنجره‌ی هدف انتخاب شد": "Target window selected",
    "حالا PrtSc یا F3 عکس کامل همان پنجره را می‌گیرد و ترجمه می‌کند": "Now PrtSc or F3 captures that window fully and translates it",
    "روشن": "ON",
    "متوقف": "paused",
    "کلید بستن": "Close key",
    "زبان مقصد": "Target language",
    # --- نام زبان‌ها (کامبوی زبان مقصد) ---
    "فارسی": "Persian",
    "انگلیسی": "English",
    "عربی": "Arabic",
    "ترکی استانبولی": "Turkish",
    "آلمانی": "German",
    "فرانسوی": "French",
    "اسپانیایی": "Spanish",
    "روسی": "Russian",
    "ایتالیایی": "Italian",
    "هندی": "Hindi",
    "اردو": "Urdu",
    "آذربایجانی": "Azerbaijani",
    "چینی ساده‌شده": "Chinese (Simplified)",
    "ژاپنی": "Japanese",
    "کرِه‌ای": "Korean",
}


def set_ui_lang(lang):
    """زبان رابط را عوض می‌کند (fa یا en)."""
    global UI_LANG
    if lang in ("fa", "en"):
        UI_LANG = lang


def T(text):
    """متن رابط به زبان جاری؛ در انگلیسی از جدول ترجمه برمی‌گرداند."""
    if UI_LANG == "en":
        return EN_TEXTS.get(text, text)
    return text


# ----------------------------------------------------------------------
# ابزارهای کمکی
# ----------------------------------------------------------------------
def build_translate_url(target_lang):
    return f"https://translate.google.com/?sl=auto&tl={target_lang}&op=images&hl=fa"


MAX_UPLOAD_PX = 1600   # حداکثر بلندترین ضلع عکس ارسالی به گوگل


def pil_to_data_url(img):
    """تصویر PIL → data URL (PNG). عکس‌های خیلی بزرگ کمی کوچک می‌شوند تا
    سرویس گوگل محدودیت اندازه را رد نکند و رشته‌ی تزریق هم سنگین نشود."""
    buf = io.BytesIO()
    try:
        if max(img.size) > MAX_UPLOAD_PX:
            k = MAX_UPLOAD_PX / float(max(img.size))
            img = img.resize((max(1, int(img.width * k)),
                              max(1, int(img.height * k))), Image.LANCZOS)
    except Exception:
        pass
    img.convert("RGBA").save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def data_url_to_pil(data_url):
    raw = base64.b64decode(data_url.split(",", 1)[1])
    return Image.open(io.BytesIO(raw)).convert("RGBA")


def image_hash(img):
    try:
        return hashlib.md5(img.convert("RGB").resize((96, 96)).tobytes()).hexdigest()
    except Exception:
        return None


def rounded_region(w, h, radius):
    """یک Region گردشده برای پنجره‌های شناور بدون قاب."""
    bmp = wx.Bitmap(max(1, w), max(1, h))
    dc = wx.MemoryDC(bmp)
    dc.SetBackground(wx.Brush(wx.Colour(0, 0, 0)))
    dc.Clear()
    dc.SetBrush(wx.Brush(wx.Colour(255, 255, 255)))
    dc.SetPen(wx.TRANSPARENT_PEN)
    dc.DrawRoundedRectangle(0, 0, w, h, radius)
    dc.SelectObject(wx.NullBitmap)
    return wx.Region(bmp, wx.Colour(0, 0, 0))


def _resource_path(rel):
    """مسیر فایل‌ها: هم در حالت عادی و هم در exe فریز (PyInstaller) درست کار می‌کند."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


APP_DIR = _resource_path("")
ASSETS_DIR = os.path.join(APP_DIR, "assets")
LOGO_PATH = os.path.join(ASSETS_DIR, "42logo.png")
BANNER_PATH = os.path.join(ASSETS_DIR, "banner.jpg")

_LOGO_CACHE = {}
def load_logo_bitmap(size):
    """لوگوی 42LEVEL را از پوشه‌ی assets بارگذاری و در اندازه‌ی خواسته‌شده برمی‌گرداند.
    (فقط در پاپ‌آپ خوش‌آمدگویی استفاده می‌شود؛ آیکون برنامه همان طرح قبلی است.)"""
    try:
        if size in _LOGO_CACHE:
            return _LOGO_CACHE[size]
        if os.path.isfile(LOGO_PATH):
            bmp = wx.Bitmap(LOGO_PATH, wx.BITMAP_TYPE_PNG)
            if bmp.IsOk():
                img = bmp.ConvertToImage().Scale(size, size, wx.IMAGE_QUALITY_HIGH)
                out = wx.Bitmap(img)
                _LOGO_CACHE[size] = out
                return out
    except Exception:
        pass
    return None


def load_banner_bitmap(width):
    """بنر 42LEVEL (banner.jpg از پوشه‌ی assets) را با عرض دلخواه برمی‌گرداند؛
    نسبت ابعاد حفظ می‌شود. اگر فایل نبود None برمی‌گردد."""
    try:
        if not os.path.isfile(BANNER_PATH):
            return None
        bmp = wx.Bitmap(BANNER_PATH, wx.BITMAP_TYPE_JPEG)
        if not bmp.IsOk() or bmp.GetHeight() <= 0:
            return None
        height = max(1, int(bmp.GetHeight() * (width / bmp.GetWidth())))
        img = bmp.ConvertToImage().Scale(width, height, wx.IMAGE_QUALITY_HIGH)
        return wx.Bitmap(img)
    except Exception:
        return None


def make_app_bitmap(size=32):
    """بیت‌مپ آیکون برنامه (مربع گرد با «A⇄ف» — همان طرح قبلی برنامه).
    فونت این آیکون عمداً سیستم است تا گلیف «⇄» درست رسم شود (فونت وزیر آن را ندارد)."""
    bmp = wx.Bitmap(size, size)
    dc = wx.MemoryDC(bmp)
    dc.SetBackground(wx.Brush(ACCENT))
    dc.Clear()
    dc.SetBrush(wx.Brush(ACCENT))
    dc.SetPen(wx.TRANSPARENT_PEN)
    dc.DrawRoundedRectangle(0, 0, size, size, 8)
    dc.SetTextForeground(wx.Colour(255, 255, 255))
    font = wx.Font(max(9, int(size * 0.42)), wx.FONTFAMILY_SWISS, wx.NORMAL, wx.BOLD)
    dc.SetFont(font)
    label = "A\u21c4\u0641"
    tw, th = dc.GetTextExtent(label)
    dc.DrawText(label, (size - tw) // 2, (size - th) // 2 - 1)
    dc.SelectObject(wx.NullBitmap)
    return bmp


def make_app_icon():
    """آیکون تسک‌بار / اعلان‌ها: لوگوی 42LEVEL (و در نبودش آیکون رسمی «A⇄ف»)."""
    bmp = load_logo_bitmap(32)
    if bmp is not None and bmp.IsOk():
        return wx.Icon(bmp)
    return wx.Icon(make_app_bitmap())


def pil_to_wx_bitmap(img):
    return wx.Bitmap.FromBufferRGBA(img.width, img.height, img.convert("RGBA").tobytes())


def copy_pil_to_clipboard(img):
    bmp = pil_to_wx_bitmap(img)
    clip = wx.Clipboard()
    if clip.Open():
        clip.SetData(wx.BitmapDataObject(bmp))
        clip.Flush()
        clip.Close()


# ----------------------------------------------------------------------
# اجرای خودکار با شروع ویندوز (ریجستری HKCU Run)
# ----------------------------------------------------------------------
RUN_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "42OCR"


def _startup_command():
    """دستوری که ویندوز هنگام ورود اجرا می‌کند (exe یا اسکریپت پایتون)."""
    if getattr(sys, "frozen", False):
        return '"%s"' % sys.executable
    exe = sys.executable
    alt = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.isfile(alt):
        exe = alt
    return '"%s" "%s"' % (exe, os.path.abspath(__file__))


def set_run_on_startup(enabled):
    """روشن/خاموش کردن اجرای خودکار برنامه با شروع ویندوز."""
    try:
        import winreg
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_REG_KEY, 0,
                                 winreg.KEY_SET_VALUE)
        except OSError:
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_REG_KEY)
        try:
            if enabled:
                winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ,
                                  _startup_command())
            else:
                try:
                    winreg.DeleteValue(key, RUN_VALUE_NAME)
                except OSError:
                    pass
        finally:
            winreg.CloseKey(key)
        return True
    except Exception:
        return False


# ----------------------------------------------------------------------
# ابزارهای مدیریت پنجره‌ها / فرآیندها (برای اسکرین‌شات پنجره‌ی انتخابی)
# ----------------------------------------------------------------------
def _user32():
    """user32 با آرگ‌تایپ‌های درست تا HWND (۶۴بیتی) بریده نشود."""
    u = ctypes.windll.user32
    u.IsWindowVisible.argtypes = [ctypes.c_void_p]
    u.GetWindowTextLengthW.argtypes = [ctypes.c_void_p]
    u.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    u.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    u.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.wintypes.RECT)]
    u.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    u.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
                               ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    u.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    u.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
    u.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
    u.GetClientRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.wintypes.RECT)]
    u.PrintWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    u.GetDC.argtypes = [ctypes.c_void_p]
    u.GetDC.restype = ctypes.c_void_p
    u.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    return u


def _kernel32():
    k = ctypes.windll.kernel32
    k.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    k.OpenProcess.restype = ctypes.c_void_p
    k.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                             ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    return k


def enum_visible_windows():
    """لیست پنجره‌های قابل مشاهده: [(hwnd, عنوان, pid, نام فرآیند)]."""
    out = []
    try:
        u = _user32()

        def _cb(hwnd, _):
            if not u.IsWindowVisible(hwnd):
                return True
            length = u.GetWindowTextLengthW(hwnd)
            title = ""
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                u.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value.strip()
            pid = ctypes.wintypes.DWORD()
            u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            exe = process_name_for_pid(pid.value)
            if not exe:
                return True
            out.append((hwnd, title, pid.value, exe))
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        u.EnumWindows(WNDENUMPROC(_cb), 0)
    except Exception:
        pass
    return out


def process_name_for_pid(pid):
    """نام فایل فرآیند (مثلاً game.exe) از روی PID."""
    try:
        k = _kernel32()
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return None
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = ctypes.c_ulong(1024)
            if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value)
        finally:
            k.CloseHandle(h)
    except Exception:
        pass
    return None


def find_window_by_pid(pid):
    """اولین پنجره‌ی قابل مشاهده‌ی یک فرآیند را برمی‌گرداند (یا None)."""
    for hwnd, _t, p, _e in enum_visible_windows():
        if p == pid:
            return hwnd
    return None


def bring_window_front(hwnd):
    """پنجره (مثلاً بازی) را به جلو و فوکوس می‌آورد تا عکس کاملش گرفته شود.
    با AllowSetForegroundWindow مجوز فورگراند می‌گیریم (وقتی از یک کلید میانبر
    جهانی صدا زده می‌شود، ویندوز به‌طور پیش‌فرض اجازه‌ی SetForegroundWindow نمی‌دهد)
    و پنجره را Restore می‌کنیم تا بازی که کوچک/پشت است دیده شود."""
    try:
        u = _user32()
        try:
            u.AllowSetForegroundWindow.argtypes = [ctypes.c_ulong]
            u.AllowSetForegroundWindow(-1)   # ASFW_ANY
        except Exception:
            pass
        u.ShowWindow(hwnd, 9)                                   # SW_RESTORE
        u.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)   # TOPMOST+SHOW
        u.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x0001 | 0x0002)           # NOTOPMOST
        u.SetForegroundWindow(hwnd)
        try:
            u.BringWindowToTop.argtypes = [ctypes.c_void_p]
            u.BringWindowToTop(hwnd)
        except Exception:
            pass
        # یک بار دیگر هم با کمی تأخیر صدا بزنید تا برای بازی‌های تمام‌صفحه جواب دهد
        def _retry():
            try:
                u.ShowWindow(hwnd, 9)
                u.SetForegroundWindow(hwnd)
            except Exception:
                pass
        try:
            t = threading.Timer(0.12, _retry)
            t.daemon = True
            t.start()
        except Exception:
            pass
    except Exception:
        pass


def window_rect(hwnd):
    """مستطیل پنجره به‌صورت (چپ، بالا، راست، پایین)."""
    try:
        r = ctypes.wintypes.RECT()
        if _user32().GetWindowRect(hwnd, ctypes.byref(r)):
            return (r.left, r.top, r.right, r.bottom)
    except Exception:
        pass
    return None


def set_no_activate(hwnd):
    """پنجره بدون گرفتن فوکوس و بدون دیده‌شدن در Alt+Tab
    (تا Overlay ترجمه روی بازی فول‌اسکرین بدون Alt-Tab دیده شود)."""
    try:
        GWL_EXSTYLE = -20
        WS_EX_NOACTIVATE = 0x08000000
        WS_EX_TOOLWINDOW = 0x00000080
        u = _user32()
        style = u.GetWindowLongW(hwnd, GWL_EXSTYLE)
        u.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
    except Exception:
        pass


def set_toolwindow(hwnd):
    """فقط از Alt+Tab و تسک‌بار مخفی می‌کند ولی کلیک‌پذیر/فعال‌شدنی می‌ماند
    (برای منوی تعاملی داخل بازی که کاربر باید رویش کلیک کند)."""
    try:
        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        u = _user32()
        style = u.GetWindowLongW(hwnd, GWL_EXSTYLE)
        u.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TOOLWINDOW)
    except Exception:
        pass


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32)]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint32 * 3)]


def print_window_bitmap(hwnd):
    """عکس کاملِ محتوای یک پنجره با API ویندوز PrintWindow.
    برخلاف ImageGrab، برای بازی‌های DirectX (حتی فول‌اسکرین قدیمی) هم جواب می‌دهد
    چون با PW_RENDERFULLCONTENT از خودِ موتور بازی درخواست رندر می‌کند.
    اگر موفق نشود None برمی‌گرداند تا جایگزین (ImageGrab) استفاده شود."""
    try:
        u = _user32()
        r = ctypes.wintypes.RECT()
        if not u.GetClientRect(hwnd, ctypes.byref(r)):
            return None
        width, height = r.right - r.left, r.bottom - r.top
        if width < 4 or height < 4:
            return None

        g = ctypes.windll.gdi32
        g.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
        g.CreateCompatibleDC.restype = ctypes.c_void_p
        g.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        g.CreateCompatibleBitmap.restype = ctypes.c_void_p
        g.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        g.SelectObject.restype = ctypes.c_void_p
        g.DeleteObject.argtypes = [ctypes.c_void_p]
        g.DeleteDC.argtypes = [ctypes.c_void_p]
        g.GetDIBits.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
                                ctypes.c_uint, ctypes.c_void_p,
                                ctypes.POINTER(_BITMAPINFO), ctypes.c_uint]
        g.GetDIBits.restype = ctypes.c_int

        win_dc = u.GetDC(hwnd)
        if not win_dc:
            return None
        mem_dc = g.CreateCompatibleDC(win_dc)
        hbmp = g.CreateCompatibleBitmap(win_dc, width, height)
        old = g.SelectObject(mem_dc, hbmp)
        img = None
        try:
            # ۱) PW_RENDERFULLCONTENT (Win 8.1+) — محتوای DirectX را می‌گیرد
            ok = bool(u.PrintWindow(hwnd, mem_dc, 0x00000002))
            if not ok:
                ok = bool(u.PrintWindow(hwnd, mem_dc, 0))           # حالت عادی
            if not ok:
                ok = bool(u.PrintWindow(hwnd, mem_dc, 0x00000001))   # فقط کلاینت
            if ok:
                # خواندن پیکسل‌ها با GetDIBits (در حالی که بیت‌مپ هنوز انتخاب است)
                bmi = _BITMAPINFO()
                bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
                # مرحله‌ی ۱: پرس‌وجو تا سربرگ کامل پر شود (biWidth/biPlanes/…)
                g.GetDIBits(mem_dc, hbmp, 0, height, None, ctypes.byref(bmi), 0)
                # مرحله‌ی ۲: درخواست ۲۴ بیتی BGR از بالا به پایین
                bmi.bmiHeader.biBitCount = 24          # خروجی ۲۴ بیتی BGR
                bmi.bmiHeader.biCompression = 0        # BI_RGB
                bmi.bmiHeader.biHeight = -height       # از بالا به پایین (برای PIL)
                row = ((width * 24 + 31) // 32) * 4    # هر ردیف ۴ بایتی پد می‌شود
                total = row * height
                buf = ctypes.create_string_buffer(total)
                if g.GetDIBits(mem_dc, hbmp, 0, height, buf,
                               ctypes.byref(bmi), 0):
                    try:
                        img = Image.frombytes("RGB", (width, height),
                                              buf.raw[:total], "raw", "BGR", 0, row)
                    except Exception:
                        img = None
        finally:
            g.SelectObject(mem_dc, old)
            u.ReleaseDC(hwnd, win_dc)
            g.DeleteObject(hbmp)
            g.DeleteDC(mem_dc)
        return img
    except Exception:
        return None


# ----------------------------------------------------------------------
# مدیریت پیکربندی (config.json در %APPDATA%\42OCR)
# ----------------------------------------------------------------------
class Config:
    DEFAULTS = {
        "hotkey": "f2",
        "snip_hotkey": "f3",   # کلید اسکرین‌شات (پیش‌فرض F3) — قابل تغییر از تنظیمات
        "target_lang": "fa",
        "ui_lang": "fa",     # زبان رابط برنامه (fa یا en)
        "save_dir": "",
        "auto_close_seconds": DEFAULT_AUTO_CLOSE_S,
        "badge_timeout_seconds": 30,   # مخفی‌شدن خودکار نوار «42OCR فعال است» (۰ = خاموش)
        "notifications": True,
        "overlay_pos": None,   # موقعیت آخرِ Overlay روی صفحه (پس از درگ)
        "first_run": True,     # اولین اجرا — پاپ‌آپ خوش‌آمدگویی فقط یک بار نشان داده می‌شود
        "welcome_pos": None,   # موقعیت پاپ‌آپ خوش‌آمدگویی (پس از جابه‌جایی)
        "run_on_startup": False,  # اجرای خودکار با شروع ویندوز (ریجستری)
        "wipe_on_exit": True,  # پاک‌سازی دائمی پوشه‌ی ذخیره هنگام خروج (بدون بازیابی)
        "focus_pid": None,     # پنجره/فرآیند هدف برای اسکرین‌شات (مثلاً بازی)
        "focus_name": "",
        "focus_title": "",
    }

    def __init__(self):
        base_dir = os.environ.get("APPDATA") or os.path.expanduser("~")
        self.dir = os.path.join(base_dir, "42OCR")
        self.path = os.path.join(self.dir, "config.json")
        self._migrate_old_config(base_dir)
        self.data = dict(self.DEFAULTS)
        self.load()
        # پوشه‌ی ذخیره‌ی قبلی «PantyOCR» به «42OCR» تغییر نام می‌دهد
        sd = self.data.get("save_dir")
        if sd:
            head, tail = os.path.split(sd.rstrip("\\/"))
            if tail == "PantyOCR":
                self.data["save_dir"] = os.path.join(head, "42OCR")
        if not self.data.get("save_dir"):
            self.data["save_dir"] = os.path.join(os.path.expanduser("~"), "Pictures", "42OCR")
        self.ensure_dirs()

    def _migrate_old_config(self, base_dir):
        """اگر تنظیمات قبلی در پوشه‌ی قدیمی (PantyOCR) بود، به 42OCR منتقل می‌شود."""
        old = os.path.join(base_dir, "PantyOCR", "config.json")
        try:
            if os.path.isfile(old) and not os.path.isfile(self.path):
                os.makedirs(self.dir, exist_ok=True)
                shutil.copy2(old, self.path)
        except Exception:
            pass

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                stored = json.load(f)
            for k, v in stored.items():
                if k in self.DEFAULTS:
                    self.data[k] = v
        except Exception:
            pass

    def save(self):
        try:
            os.makedirs(self.dir, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("خطا در ذخیره‌ی تنظیمات:", e)

    def ensure_dirs(self):
        try:
            os.makedirs(self.data["save_dir"], exist_ok=True)
        except Exception:
            pass

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value

    def get(self, key, default=None):
        return self.data.get(key, default)


# ----------------------------------------------------------------------
# دکمه‌ی تخت با افکت‌های hover / فشار (برای ظاهر مدرن)
# ----------------------------------------------------------------------
class FlatButton(wx.Control):
    def __init__(self, parent, label, on_click=None, kind="accent", size=None):
        self.kind = kind
        self.hovered = False
        self.pressed = False
        self._on_click = on_click
        super().__init__(parent, size=size or (-1, 34), style=wx.BORDER_NONE)
        self.SetLabel(label)
        self.SetBackgroundColour(parent.GetBackgroundColour())
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ENTER_WINDOW, lambda e: self._set_hover(True))
        self.Bind(wx.EVT_LEAVE_WINDOW, lambda e: self._set_hover(False))
        self.Bind(wx.EVT_LEFT_DOWN, lambda e: self._set_pressed(True))
        self.Bind(wx.EVT_LEFT_UP, self._on_up)
        self.Bind(wx.EVT_LEFT_DCLICK, lambda e: None)

    def _base_color(self):
        if self.kind == "accent":
            return ACCENT_D if self.hovered else ACCENT
        if self.kind == "ghost":
            return PANEL if self.hovered else CARD
        if self.kind == "danger":
            return DANGER
        return CARD

    def _set_hover(self, v):
        self.hovered = v
        self.Refresh()

    def _set_pressed(self, v):
        self.pressed = v
        self.Refresh()

    def _on_up(self, evt):
        self.pressed = False
        self.Refresh()
        if self._on_click:
            self._on_click(evt)

    def _on_paint(self, evt):
        dc = wx.PaintDC(self)
        w, h = self.GetSize()
        color = self._base_color()
        if self.pressed:
            color = color.ChangeLightness(88)
        dc.SetBrush(wx.Brush(color))
        dc.SetPen(wx.Pen(color))
        dc.DrawRoundedRectangle(0, 0, w, h, h // 2)

        label = self.GetLabel()
        if self.kind == "ghost":
            dc.SetTextForeground(TEXT if self.hovered else MUTED)
        elif self.kind == "danger":
            dc.SetTextForeground(wx.Colour(255, 255, 255))
        else:
            dc.SetTextForeground(wx.Colour(255, 255, 255))
        font = ui_font(10)
        if self.kind == "accent":
            font = ui_font(10, bold=True)
        dc.SetFont(font)
        tw, th = dc.GetTextExtent(label)
        dc.DrawText(label, (w - tw) // 2, (h - th) // 2 - 1)
        evt.Skip()

    def DoGetBestSize(self):
        label = self.GetLabel()
        dc = wx.MemoryDC(wx.Bitmap(1, 1))
        dc.SetFont(ui_font(10))
        tw, th = dc.GetTextExtent(label)
        return wx.Size(tw + 36, 34)


# ----------------------------------------------------------------------
# مرورگر مخفی Google Translate (کاملاً پشت‌صحنه)
# ----------------------------------------------------------------------
class TranslateWorker(wx.Frame):
    """یک پنجره‌ی بدون‌فریم در موقعیت خارج از صفحه که فقط برای اجرای
    Google Translate استفاده می‌شود؛ هرگز دیده نمی‌شود."""

    INJECT_JS = r"""
(function(dataUrl){
  try {
    var m = dataUrl.match(/^data:([^;,]+)[;,]/);
    var mime = m ? m[1] : 'image/png';
    var bin = atob(dataUrl.split(',')[1]);
    var u8 = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
    var file = new File([u8], 'clip.png', {type: mime});
    var dt = new DataTransfer();
    dt.items.add(file);
    var ev = new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true});
    document.dispatchEvent(ev);
    document.body.dispatchEvent(ev);
    var targets = document.querySelectorAll('[jsaction*="drop"],[jsaction*="paste"],[jsaction*="input"],[data-drop],[role="button"]');
    for (var j = 0; j < targets.length; j++) {
      try {
        var drop = new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true});
        targets[j].dispatchEvent(drop);
      } catch (e) {}
    }
    var inputs = document.querySelectorAll('input[type=file]');
    for (var k = 0; k < inputs.length; k++) {
      try {
        Object.defineProperty(inputs[k], 'files', {value: dt.files, configurable: true});
        inputs[k].dispatchEvent(new Event('change', {bubbles: true}));
      } catch (e) {}
    }
    return 'OK';
  } catch (e) { return 'ERR:' + (e && e.message || e); }
})"""

    EXTRACT_JS = r"""
(function(){
  var best = null, bestArea = 0;
  document.querySelectorAll('img').forEach(function(im){
    var s = im.src || '';
    if (s.indexOf('blob:') !== 0 && s.indexOf('data:image/') !== 0) return;
    var a = (im.naturalWidth || 0) * (im.naturalHeight || 0);
    if (a > bestArea) { bestArea = a; best = im; }
  });
  if (!best || bestArea < 100) return 'NOT_READY';
  try {
    var c = document.createElement('canvas');
    c.width = best.naturalWidth;
    c.height = best.naturalHeight;
    c.getContext('2d').drawImage(best, 0, 0);
    var d = c.toDataURL('image/png');
    if (d && d.length > 300) return d;
    return 'NOT_READY';
  } catch (e) { return 'NOT_READY'; }
})()"""

    def __init__(self, on_result, on_error, on_state):
        style = wx.FRAME_NO_TASKBAR | wx.STAY_ON_TOP | wx.FRAME_SHAPED | wx.BORDER_NONE
        super().__init__(None, title="", size=(560, 800), style=style)
        self.SetPosition(HIDDEN_POS)
        self.Show()  # پنجره در بیرون از صفحه ساخته می‌شود؛ هیچ‌وقت دیده نمی‌شود اما WebView فعال است
        self.on_result = on_result        # callable(data_url, source_img)
        self.on_error = on_error          # callable(message)
        self.on_state = on_state          # callable(state_str)

        self.browser = wx.html2.WebView.New(self)
        self.browser.Bind(wx.html2.EVT_WEBVIEW_LOADED, self._on_loaded)
        self.browser.Bind(wx.html2.EVT_WEBVIEW_SCRIPT_RESULT, self._on_script)
        self.browser.Bind(wx.html2.EVT_WEBVIEW_ERROR, lambda e: self._fail(T("خطا در بارگذاری صفحه‌ی گوگل")))

        self._busy = False
        self._data_url = None
        self._source_hash = None
        self._start_ts = 0
        self._re_injected = False
        self._fails = 0
        self._lang = "fa"
        self._poll_timer = None
        self._timeout_timer = None
        self._inject_timer = None
        self._load_watch = None     # مراقب لود صفحه (اگر لود نشد، دوباره بارگذاری کن)
        self._load_ok = False       # آیا صفحه بعد از آخرین LoadURL واقعاً لود شد؟
        self._load_retries = 0

    # -------------------------------------------------------------
    def start_upload(self, img, lang):
        """بارگذاری عکس جدید در مرورگر مخفی.
        اگر ترجمه‌ی قبلی گیر کرده باشد، اول صفر و از نو شروع می‌شود تا برنامه
        هیچ‌وقت برای همیشه روی «در حال ترجمه…» نماند."""
        if self._busy:
            self._force_reset()
        self._lang = lang
        self._busy = True
        self._fails = 0
        self._load_ok = False
        self._load_retries = 0
        self._data_url = pil_to_data_url(img)
        self._source_hash = image_hash(img)
        self._re_injected = False
        self._start_ts = time.time()

        self._clear_timers()
        self.on_state(T("در حال بارگذاری Google Translate…"))
        try:
            self.browser.LoadURL(build_translate_url(lang))
        except Exception:
            pass   # اگر مرورگر آماده نبود، واتچ‌داگ دوباره تلاش می‌کند
        # مراقب: اگر صفحه تا ۷ ثانیه لود نشد (مثلاً LoadURL موقع لودِ قبلی صدا زده شده
        # و رویداد لود گم شده)، دوباره بارگذاری می‌کنیم — وگرنه هیچ تزریقی انجام
        # نمی‌شد و بعد از ۳۰ ثانیه بی‌دلیل خطای «زمان‌بندی گوگل طول کشید» می‌آمد.
        self._load_watch = wx.CallLater(7000, self._check_load_watch)
        return True

    def _check_load_watch(self):
        """اگر صفحه‌ی گوگل بعد از LoadURL لود نشد، دوباره بارگذاری کن (حداکثر ۴ بار)."""
        if not self._busy:
            return
        if self._load_ok:
            return
        self._load_retries += 1
        if self._load_retries > 4:
            self._fail(T("خطا در بارگذاری صفحه‌ی گوگل؛ اتصال اینترنت را بررسی کنید."))
            return
        self.on_state(T("بارگذاری مجدد Google Translate… ({0}/4)").format(self._load_retries))
        try:
            self.browser.LoadURL(build_translate_url(self._lang))
        except Exception:
            pass
        self._load_watch = wx.CallLater(7000, self._check_load_watch)

    def _force_reset(self):
        """ترجمه‌ی گیرکرده را صفر می‌کند (تایمرها، وضعیت و صفحه)."""
        self._busy = False
        self._data_url = None
        self._source_hash = None
        self._load_ok = False
        self._clear_timers()
        try:
            self.browser.LoadURL(build_translate_url(self._lang))
        except Exception:
            pass

    # -------------------------------------------------------------
    def _on_loaded(self, event):
        self._load_ok = True
        if not self._busy:
            return
        self.on_state(T("در حال ارسال تصویر…"))
        self._inject_timer = wx.CallLater(900, self._inject)

    def _inject(self):
        if not self._busy or self._data_url is None:
            return
        # تایمرهای قبلی را خالی کن تا در تزریقِ مجدد، تایمر تایم‌اوت دوبل نشود
        self._clear_timers()
        try:
            self.browser.RunScriptAsync(self.INJECT_JS + "('" + self._data_url + "')")
        except Exception as e:
            self._fail(T("خطا در تزریق تصویر: {0}").format(e))
            return
        self.on_state(T("در حال ترجمه توسط گوگل…"))
        self._timeout_timer = wx.CallLater(TRANSLATE_TIMEOUT_S * 1000, self._on_timeout)
        self._schedule_poll()

    def _schedule_poll(self):
        self._poll_timer = wx.CallLater(POLL_INTERVAL_MS, self._poll_once)

    def _poll_once(self):
        if not self._busy:
            return
        try:
            self.browser.RunScriptAsync(self.EXTRACT_JS)
        except Exception:
            self._schedule_poll()

    def _on_script(self, event):
        if not self._busy:
            return
        result = event.GetString() or ""
        result = _unquote_json(result)

        if result.startswith("ERR"):
            # تزریق ناموفق — چند بار تلاش می‌کنیم، بعد خطای واضح می‌دهیم تا گیر نکنیم
            self._fails += 1
            if self._fails > 3:
                self._fail(T("گوگل تصویر را نپذیرفت؛ دوباره تلاش کنید."))
                return
            if not self._re_injected and time.time() - self._start_ts < 20:
                self._re_injected = True
                self._inject_timer = wx.CallLater(1500, self._inject)
            return

        if result.startswith("NOT_READY"):
            self._fails = 0   # صفحه زنده است؛ فقط منتظر ترجمه‌ی گوگل هستیم
            if time.time() - self._start_ts > TRANSLATE_TIMEOUT_S:
                self._on_timeout()
                return
            # اگر صفحه هیچ تصویری نشان نداد، یک بار دوباره تزریق می‌کنیم
            if not self._re_injected and time.time() - self._start_ts > 12:
                self._re_injected = True
                self._inject()
                return
            self._schedule_poll()
            return

        if result.startswith("data:image/"):
            try:
                out = data_url_to_pil(result)
            except Exception as e:
                self._schedule_poll()
                return
            # اگر تصویرِ استخراج‌شده همان عکسِ مبدأ باشد (هنوز ترجمه‌ای ساخته نشده)، منتظر می‌مانیم
            if self._source_hash and image_hash(out) == self._source_hash:
                self._schedule_poll()
                return
            self._fails = 0
            self._finish_success(result, out)
            return

        # نتیجه‌ی خالی (اسکریپت جواب نداده) — چند بار تحمل می‌کنیم بعد خطا؛
        # اگر صفحه لود شده ولی هیچ جوابی نمی‌دهد، یک بار دوباره تزریق می‌کنیم
        self._fails += 1
        if not self._re_injected and time.time() - self._start_ts > 8:
            self._re_injected = True
            self._inject()
            return
        if self._fails > 6:
            self._fail(T("گوگل پاسخ نداد؛ اتصال اینترنت را بررسی کنید."))
            return
        self._schedule_poll()

    # -------------------------------------------------------------
    def _finish_success(self, data_url, img):
        self._busy = False
        self._data_url = None
        self._source_hash = None
        self._clear_timers()
        self.on_result(data_url, img)

    def _fail(self, message):
        self._busy = False
        self._data_url = None   # جلوگیری از تزریقِ کهنه در بارگذاری بعدی
        self._source_hash = None
        self._clear_timers()
        self.on_error(message)
        # صفحه را از نو بارگذاری کن تا تلاشِ بعدی روی صفحه‌ی سالم شروع شود
        try:
            self.browser.LoadURL(build_translate_url(self._lang))
        except Exception:
            pass

    def _on_timeout(self):
        if self._busy:
            self._fail(T("ترجمه انجام نشد (زمان‌بندی گوگل طول کشید). دوباره تلاش کنید."))

    def _clear_timers(self):
        for t in (self._poll_timer, self._timeout_timer, self._inject_timer, self._load_watch):
            if t is not None:
                try:
                    if t.IsRunning():
                        t.Stop()
                except Exception:
                    pass
        self._poll_timer = None
        self._timeout_timer = None
        self._inject_timer = None
        self._load_watch = None

    def shutdown(self):
        self._busy = False
        self._clear_timers()
        try:
            self.Destroy()
        except Exception:
            pass


def _unquote_json(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        try:
            return json.loads(s)
        except Exception:
            return s[1:-1]
    return s


# ----------------------------------------------------------------------
# پاپ‌آپ خوش‌آمدگویی با لوگو و پیوندهای 42LEVEL
# ----------------------------------------------------------------------
class NeonPanel(wx.Panel):
    """پنل شیشه‌ای با حاشیه‌ی قرمز نئونی (سبک لوگوی 42LEVEL)."""

    def __init__(self, parent, glass_alpha=255):
        super().__init__(parent)
        self._glass_alpha = glass_alpha
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetBackgroundColour(BG)
        self.Bind(wx.EVT_PAINT, self._on_paint)

    def _on_paint(self, evt):
        dc = wx.PaintDC(self)
        w, h = self.GetSize()
        draw_rounded_glass(dc, w, h, 16, BG, alpha=self._glass_alpha)
        dc.SetBrush(wx.TRANSPARENT_BRUSH)
        dc.SetPen(wx.Pen(ACCENT, 2))
        dc.DrawRoundedRectangle(3, 3, max(1, w - 6), max(1, h - 6), 13)


class LinkRow(wx.Panel):
    """یک ردیف پیوند تک‌خطی: نشانک متنی کوچک سمت راست، نام فارسی کنارش،
    آدرس انگلیسی سمت چپ و پیکان؛ با کلیک در مرورگر باز می‌شود."""

    H = 72

    def __init__(self, parent, label, url, img_file=None, badge=None):
        super().__init__(parent, style=wx.BORDER_NONE)
        self.url = url
        self.hovered = False
        self.SetBackgroundColour(CARD)
        self.SetMinSize((-1, self.H))
        self.SetToolTip(url)

        s = wx.BoxSizer(wx.HORIZONTAL)
        # نشانک متنی کوچک (بدون لوگو) — مثلاً «GH» برای گیت‌هاب
        self.badge_widget = wx.StaticText(self, label=badge or "")
        self.badge_widget.SetForegroundColour(ACCENT)
        self.badge_widget.SetFont(ui_font(10, bold=True))
        self.badge_widget.SetMinSize((28, -1))

        self.label_lbl = wx.StaticText(self, label=label)   # فارسی — کنار لوگو
        self.label_lbl.SetForegroundColour(TEXT)
        self.label_lbl.SetFont(ui_font(11, bold=True))
        self.url_lbl = wx.StaticText(self, label=url)       # انگلیسی — سمت چپ
        self.url_lbl.SetForegroundColour(MUTED)
        self.url_lbl.SetFont(ui_font(9))
        self.url_lbl.SetMaxSize((190, -1))

        self.arrow_lbl = wx.StaticText(self, label="\u2197")
        self.arrow_lbl.SetForegroundColour(MUTED)
        self.arrow_lbl.SetFont(ui_font(13, bold=True))

        # راست‌چین تک‌خطی: پیکان چپ، آدرس انگلیسی بعدش، نام فارسی، نشانک متن راست
        s.Add(self.arrow_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 12)
        s.Add(self.url_lbl, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 10)
        s.Add(self.label_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        s.Add(self.badge_widget, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
        self.SetSizer(s)

        for w in (self, self.badge_widget, self.label_lbl, self.url_lbl, self.arrow_lbl):
            w.Bind(wx.EVT_ENTER_WINDOW, lambda e: self._set_hover(True))
            w.Bind(wx.EVT_LEAVE_WINDOW, lambda e: self._set_hover(False))
            w.Bind(wx.EVT_LEFT_DOWN, self._open_url)
            w.Bind(wx.EVT_MOTION, lambda e: self.SetCursor(wx.Cursor(wx.CURSOR_HAND)))

    def _set_hover(self, v):
        if self.hovered == v:
            return
        self.hovered = v
        bg = hover_bg() if v else CARD
        self.label_lbl.SetForegroundColour(ACCENT if v else TEXT)
        self.url_lbl.SetForegroundColour(ACCENT if v else MUTED)
        self.arrow_lbl.SetForegroundColour(ACCENT if v else MUTED)
        for w in (self, self.badge_widget, self.label_lbl, self.url_lbl, self.arrow_lbl):
            w.SetBackgroundColour(bg)
        self.Refresh()

    def _open_url(self, evt):
        try:
            webbrowser.open(self.url)
        except Exception:
            pass


class NeonText(wx.Panel):
    """متن بدون نوارِ پس‌زمینه: اول هم‌رنگِ پنلِ مادر رنگ می‌زند و بعد خود متن را می‌کشد.
    (زیر متن‌های StaticText در پنجره‌ی شیشه‌ای، نوارِ روشن‌ترِ پیش‌فرض ویندوز دیده می‌شد؛
    این کنترل آن نوار را ندارد و متن روی پس‌زمینه‌ی یکدست مشکی می‌نشیند.)"""

    def __init__(self, parent, label="", color=TEXT, font=None, align="right",
                 glass_alpha=255):
        super().__init__(parent, style=wx.BORDER_NONE)
        self._label = label
        self._color = color
        self._font = font or ui_font(10)
        self._align = align
        self._glass_alpha = glass_alpha
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)

    def SetLabel(self, label):
        self._label = label
        self.Refresh()

    def GetLabel(self):
        return self._label

    def DoGetBestSize(self):
        """اندازه‌ی طبیعی را از روی متن محاسبه کن تا در سایزر جمع نشود."""
        dc = wx.MemoryDC(wx.Bitmap(1, 1))
        dc.SetFont(self._font)
        tw, th = dc.GetTextExtent(self._label)
        return wx.Size(max(tw + 8, 20), th + 4)

    def _on_paint(self, evt):
        dc = wx.PaintDC(self)
        w, h = self.GetSize()
        # هم‌رنگِ پنلِ شیشه‌ایِ مادر رنگ بزن تا نوارِ روشن‌تر دیده نشود
        dc.SetBrush(wx.Brush(glass_color(BG, self._glass_alpha)))
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.DrawRectangle(0, 0, max(1, w), max(1, h))
        dc.SetFont(self._font)
        dc.SetTextForeground(self._color)
        tw, th = dc.GetTextExtent(self._label)
        if self._align == "right":
            x = max(0, w - tw)
        elif self._align == "center":
            x = max(0, (w - tw) // 2)
        else:
            x = 0
        y = max(0, (h - th) // 2)
        dc.DrawText(self._label, x, y)


class WelcomePopup(wx.Frame):
    """جعبه‌ی 42OCR: با کلیک راست روی آیکون تسک‌بار باز می‌شود (نه در اجرای برنامه)،
    گوشه‌ی بالا-راست مانیتور و قابل جابه‌جایی. دکمه‌ی ضربدر برنامه را نمی‌بندد؛
    فقط جعبه را مخفی می‌کند و نوتیف می‌دهد که برنامه همچنان در تسک‌بار فعال است."""

    W, H = 432, 680
    AUTO_CLOSE_MS = 60 * 1000

    @staticmethod
    def _links():
        """پیوندها (در هر بار ساخت، به زبان جاری رابط)."""
        return [
            ("\u2665", T("درگاه حمایت مالی"), "https://reymit.ir/42level"),
            ("YT",     T("کانال یوتیوب"),     "https://www.youtube.com/@42LEVEL"),
            ("GH",     T("گیت‌هاب"),          "https://github.com/mhbanaei"),
            ("GH",     T("گیت‌هاب"),          "https://github.com/AghaErfan"),
            ("TW",     T("کانال توییچ"),      "https://www.twitch.tv/42level"),
        ]

    def __init__(self, app):
        style = wx.FRAME_NO_TASKBAR | wx.STAY_ON_TOP | wx.FRAME_SHAPED | wx.BORDER_NONE
        super().__init__(None, title="42LEVEL", size=(self.W, self.H), style=style)
        self.app = app
        self._auto_timer = None
        self._dragging = False
        self._drag_start = (0, 0)
        self._frame_pos = (0, 0)
        self._glass_alpha = apply_glass(self)
        # بدون erase توپُرِ فریم، شیشه (Acrylic) از پشت پنل دیده می‌شود
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetBackgroundColour(BG)
        self._build_ui()
        try:
            self.SetShape(rounded_region(self.W, self.H, 16))
        except Exception:
            pass

    def _build_ui(self):
        outer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(outer)

        panel = NeonPanel(self, glass_alpha=self._glass_alpha)
        outer.Add(panel, 1, wx.EXPAND)
        ps = wx.BoxSizer(wx.VERTICAL)
        panel.SetSizer(ps)

        # بنر 42LEVEL بالای پاپ‌آپ؛ اگر فایل نبود، به هدر قبلی (لوگو + عنوان) برمی‌گردیم
        banner_bmp = load_banner_bitmap(self.W - 32)
        if banner_bmp is not None and banner_bmp.IsOk():
            # دکمه‌ی بستن ✕ را «روی خودِ بنر» می‌کشیم (نه یک کنترل جداگانه‌ی روی آن).
            # دلیل: در پنجره‌ی شیشه‌ای، بنرِ StaticBitmap روی کنترلِ هم‌سطحِ خودش می‌افتاد
            # و دکمه پشت عکس گم می‌شد. حالا ✕ جزئی از خودِ تصویر بنر است و هیچ‌وقت
            # پشت آن قرار نمی‌گیرد؛ کلیک هم با ناحیه‌ی دکمه روی خودِ بنر تشخیص داده می‌شود.
            self.banner = wx.StaticBitmap(panel,
                                          bitmap=self._banner_with_close_btn(banner_bmp))
            self._close_rect = wx.Rect(8, 8, 34, 34)   # محل دکمه روی بنر (هم‌خانواده با رسم)
            ps.Add(self.banner, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 14)
            self.banner.Bind(wx.EVT_LEFT_DOWN, self._on_banner_click)
            self.banner.Bind(wx.EVT_MOTION, self._on_banner_motion)
            # بنر خودش کلیک/درگ را مدیریت می‌کند؛ نباید دوباره در حلقه‌ی درگ بایند شود
            drag_targets = []
            self.x_btn = None   # با کنترل جداگانه دیگر کار نمی‌کنیم
        else:
            self.banner = None
            top = wx.BoxSizer(wx.HORIZONTAL)
            self.x_btn = FlatButton(panel, "\u2715", self._on_close, kind="danger",
                                    size=(30, 30))
            logo_bmp = load_logo_bitmap(60) or make_app_bitmap(60)
            self.logo_bmp = wx.StaticBitmap(panel, bitmap=logo_bmp)

            titles = wx.BoxSizer(wx.VERTICAL)
            t1 = wx.StaticText(panel, label="42LEVEL")
            t1.SetForegroundColour(ACCENT)
            t1.SetFont(ui_font(17, bold=True))
            t2 = wx.StaticText(panel, label=T("42 Level Translator — ترجمه‌ی تصویر در پس‌زمینه"))
            t2.SetForegroundColour(MUTED)
            t2.SetFont(ui_font(9))
            for _t in (t1, t2):
                _t.SetBackgroundColour(BG)
            titles.Add(t1, 0, wx.ALIGN_RIGHT)
            titles.Add(t2, 0, wx.ALIGN_RIGHT | wx.TOP, 3)

            top.Add(self.x_btn, 0, wx.ALIGN_CENTER_VERTICAL)
            top.AddStretchSpacer(1)
            top.Add(titles, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
            top.Add(self.logo_bmp, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 12)
            ps.Add(top, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 16)
            drag_targets = [self.logo_bmp, t1, t2]

        # پیام سپاسگزاری — کنترل متنِ بدون نوارِ پس‌زمینه
        hint = NeonText(panel, T("از همراهی شما سپاسگزاریم \u2665 — با فالو کردن از ما حمایت کنید:"),
                        color=TEXT, font=ui_font(10), align="right",
                        glass_alpha=self._glass_alpha)
        ps.Add(hint, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 16)

        for badge, label, url in self._links():
            ps.Add(LinkRow(panel, label, url, badge=badge),
                   0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 8)

        ps.AddStretchSpacer(1)

        footer = NeonText(panel, T("کلیک روی هر مورد، پیوند را در مرورگر باز می‌کند"),
                          color=MUTED, font=ui_font(8), align="center",
                          glass_alpha=self._glass_alpha)
        # با حاشیه‌ی کناری تا حاشیه‌ی قرمز نئونی پوشانده نشود
        ps.Add(footer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        # چیدمانِ اولیه را همین‌جا انجام می‌دهیم تا اگر رویداد تغییر اندازه نرسید،
        # محتوا با اندازه‌های درست ساخته شود (بدون آن، پاپ‌آپ خالی/سیاه دیده می‌شد)
        self.Layout()
        # و در تغییر اندازه‌ها هم دوباره مرتب می‌کنیم
        self.Bind(wx.EVT_SIZE, self._on_size)

        # جابه‌جایی: از روی بنر (یا نوار عنوان قبلی) می‌توان پاپ‌آپ را درگ کرد
        panel.Bind(wx.EVT_LEFT_DOWN, self._on_drag_start)
        for w in drag_targets:
            w.Bind(wx.EVT_LEFT_DOWN, self._on_drag_start)
        self.Bind(wx.EVT_MOTION, self._on_drag_move)
        self.Bind(wx.EVT_LEFT_UP, self._on_drag_end)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, self._on_drag_end)

    @staticmethod
    def _banner_with_close_btn(banner_bmp):
        """کپیِ بنر + دکمه‌ی بستن ✕ روی گوشه‌ی آن. دکمه روی خودِ تصویر رسم می‌شود
        تا در پنجره‌ی شیشه‌ای زیر بنر گم نشود و همیشه بالای آن دیده شود."""
        try:
            bmp = banner_bmp.ConvertToImage().ConvertToBitmap()
        except Exception:
            return banner_bmp
        dc = wx.MemoryDC(bmp)
        # دکمه‌ی قرمز گرد با ✕ سفید
        dc.SetBrush(wx.Brush(DANGER))
        dc.SetPen(wx.Pen(DANGER))
        dc.DrawRoundedRectangle(8, 8, 34, 34, 10)
        dc.SetPen(wx.Pen(wx.Colour(255, 255, 255), 3))
        dc.DrawLine(15, 15, 35, 35)
        dc.DrawLine(35, 15, 15, 35)
        dc.SelectObject(wx.NullBitmap)
        return bmp

    def _on_banner_click(self, evt):
        """کلیک روی بنر: داخلِ دکمه‌ی ✕ → بستن؛ بیرون → درگ (جابه‌جایی پاپ‌آپ)."""
        pos = evt.GetPosition()
        if self._close_rect.Contains(pos):
            self._on_close(evt)
        else:
            self._on_drag_start(evt)

    def _on_banner_motion(self, evt):
        """روی دکمه‌ی ✕ کرسر دست می‌شود تا کاربر بداند کلیک‌پذیر است."""
        pos = evt.GetPosition()
        if self._close_rect.Contains(pos):
            self.banner.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        else:
            self.banner.SetCursor(wx.Cursor(wx.CURSOR_DEFAULT))
        evt.Skip()

    def _on_size(self, evt):
        self.Layout()
        evt.Skip()

    def show_welcome(self):
        self._position_top_right()
        self.Show()
        self.Raise()
        self._stop_timer()
        self._auto_timer = wx.CallLater(self.AUTO_CLOSE_MS, self._on_auto_close)

    def _position_top_right(self):
        """گوشه‌ی بالا-راست مانیتور (یا آخرین موقعیتِ درگ‌شده)."""
        try:
            sw, sh = wx.GetDisplaySize()
            w, h = self.GetSize()
            pos = self.app.cfg["welcome_pos"]
            if isinstance(pos, (list, tuple)) and len(pos) == 2:
                x, y = int(pos[0]), int(pos[1])
            else:
                x, y = max(20, sw - w - 20), 20
            x = min(max(x, 0), max(0, sw - w - 10))
            y = min(max(y, 0), max(0, sh - h - 10))
            self.SetPosition((x, y))
        except Exception:
            pass

    # ---------------- درگ ----------------
    def _on_drag_start(self, evt):
        if self._dragging:
            return
        # فقط از ناحیه‌ی بالای پاپ‌آپ (بنر یا نوار عنوان) درگ شروع می‌شود
        obj = evt.GetEventObject()
        if obj is not self.banner and evt.GetPosition().y > 84:
            return
        self._dragging = True
        self._drag_start = wx.GetMousePosition()
        self._frame_pos = self.GetPosition()
        self.CaptureMouse()

    def _on_drag_move(self, evt):
        if not self._dragging:
            return
        mx, my = wx.GetMousePosition()
        self.SetPosition((self._frame_pos[0] + mx - self._drag_start[0],
                          self._frame_pos[1] + my - self._drag_start[1]))

    def _on_drag_end(self, evt=None):
        if self._dragging:
            self._dragging = False
            if self.HasCapture():
                self.ReleaseMouse()
            self._save_position()

    def _save_position(self):
        try:
            self.app.cfg["welcome_pos"] = [int(v) for v in self.GetPosition()]
            self.app.cfg.save()
        except Exception:
            pass

    # ---------------- بستن ----------------
    def _on_close(self, evt):
        # ضربدر برنامه را نمی‌بندد؛ فقط پاپ‌آپ را مخفی می‌کند و با نوتیف پایین صفحه
        # به کاربر می‌گوید برنامه کوچک شده و در تسک‌بار (کنار ساعت ویندوز) است
        self.Hide()
        self._stop_timer()
        self.app.show_toast(T("برنامه کوچک شد — در تسک‌بار است"),
                            T("من اینجا (کنار ساعت ویندوز) هستم؛ با کلیک راست روی آیکون، منو باز می‌شود"))

    def _on_auto_close(self):
        if self.IsShown():
            self.Hide()

    def _stop_timer(self):
        if self._auto_timer is not None:
            try:
                if self._auto_timer.IsRunning():
                    self._auto_timer.Stop()
            except Exception:
                pass
            self._auto_timer = None

    def shutdown(self):
        self._stop_timer()
        try:
            self.Destroy()
        except Exception:
            pass


# ----------------------------------------------------------------------
# پنجره‌ی Overlay شناور برای نمایش نتیجه
# ----------------------------------------------------------------------
class ImageOverlay(wx.Frame):
    PAD = 18
    HEADER_H = 46
    FOOTER_H = 34
    MIN_W = 370        # حداقل عرض پنجره تا دکمه‌های کپی و بستن در نوار بالا همیشه دیده شوند
    MIN_DISPLAY_W = 480  # حداقل عرض نمایشی عکس (برای بزرگ‌نمایی عکس‌های کوچک)
    MIN_DISPLAY_H = 360  # حداقل ارتفاع نمایشی عکس
    ZOOM_CAP = 3.0       # حداکثر ضریب بزرگ‌نمایی (برای جلوگیری از تارشدن بیش از حد)

    def __init__(self, app):
        style = (wx.FRAME_NO_TASKBAR | wx.STAY_ON_TOP | wx.FRAME_SHAPED | wx.BORDER_NONE)
        super().__init__(None, title="42OCR", size=(560, 420), style=style)
        self.app = app
        self._current_img = None
        self._zoom = 1.0             # ضریب زوم کاربر (روی خروجی ترجمه)
        self._auto_timer = None
        self._dragging = False
        self._drag_off_screen = (0, 0)
        self._drag_frame_pos = (0, 0)
        self._positioned = False
        self._pan = (0, 0)           # جابه‌جایی تصویر در زوم بالا (پن با درگ موس)
        self._pan_start = None

        self.SetBackgroundColour(BG)
        # بدون گرفتن فوکوس → بالای بازی فول‌اسکرین (بدون Alt-Tab) نمایش داده می‌شود
        set_no_activate(self.GetHandle())
        self._build_ui()
        self.Bind(wx.EVT_SIZE, self._on_size)
        self._apply_shape()
        self._apply_initial_position()

    # ---------------- ساخت رابط ----------------
    def _build_ui(self):
        outer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(outer)

        # نوار بالا (قابل درگ)
        self.header = wx.Panel(self)
        self.header.SetBackgroundColour(PANEL)
        hs = wx.BoxSizer(wx.HORIZONTAL)

        # لوگوی 42LEVEL در پنجره‌ی نمایش نتیجه (آیکون برنامه در تسک‌بار همان «A⇄ف» می‌ماند)
        self.icon_bmp = wx.StaticBitmap(self.header,
                                        bitmap=load_logo_bitmap(28) or make_app_bitmap())
        self.title_lbl = wx.StaticText(self.header, label="Level Translator")
        self.title_lbl.SetForegroundColour(TEXT)
        self.title_lbl.SetFont(ui_font(11, bold=True))

        self.state_lbl = wx.StaticText(self.header, label="")
        self.state_lbl.SetForegroundColour(WARN)
        self.state_lbl.SetFont(ui_font(10))

        self.copy_btn = FlatButton(self.header, T("کپی"), self._on_copy, kind="ghost", size=(58, 30))
        self.close_btn = FlatButton(self.header, "\u2715", self._on_close, kind="danger", size=(34, 30))

        # راست‌چین: دکمه‌های بستن/کپی سمت چپ، لوگو و عنوان سمت راست
        hs.Add(self.close_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 10)
        hs.Add(self.copy_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 6)
        hs.Add(self.state_lbl, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 14)
        hs.Add(self.title_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        hs.Add(self.icon_bmp, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
        self.header.SetSizer(hs)
        self.header.SetMinSize((-1, self.HEADER_H))

        # ناحیه‌ی تصویر (پنل ساده؛ در زوم‌های بالا با درگِ موس پن می‌شود)
        self.image_panel = wx.Panel(self)
        self.image_panel.SetBackgroundColour(CARD)
        ips = wx.BoxSizer(wx.VERTICAL)
        self.image_ctrl = wx.StaticBitmap(self.image_panel)
        self.placeholder_lbl = wx.StaticText(self.image_panel, label="")
        self.placeholder_lbl.SetForegroundColour(MUTED)
        self.placeholder_lbl.SetFont(ui_font(12))
        ips.AddStretchSpacer(1)
        ips.Add(self.placeholder_lbl, 0, wx.ALIGN_CENTER | wx.TOP, 8)
        ips.AddStretchSpacer(1)
        self.image_panel.SetSizer(ips)
        self.image_panel.Bind(wx.EVT_SIZE, self._on_panel_size)

        # نوار پایین
        self.footer = wx.Panel(self)
        self.footer.SetBackgroundColour(PANEL)
        fs = wx.BoxSizer(wx.HORIZONTAL)
        self.hint_lbl = wx.StaticText(self.footer, label="")
        self.hint_lbl.SetForegroundColour(MUTED)
        self.hint_lbl.SetFont(ui_font(9))
        self.path_lbl = wx.StaticText(self.footer, label="")
        self.path_lbl.SetForegroundColour(MUTED)
        self.path_lbl.SetFont(ui_font(9))
        # کنترل زوم روی خروجی ترجمه
        self.zoom_out_btn = FlatButton(self.footer, "−", self._on_zoom_out, kind="ghost", size=(26, 24))
        self.zoom_lbl = wx.StaticText(self.footer, label="100٪")
        self.zoom_lbl.SetForegroundColour(MUTED)
        self.zoom_lbl.SetFont(ui_font(9))
        self.zoom_in_btn = FlatButton(self.footer, "+", self._on_zoom_in, kind="ghost", size=(26, 24))
        fs.Add(self.zoom_out_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 10)
        fs.Add(self.zoom_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 6)
        fs.Add(self.zoom_in_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 2)
        fs.Add(self.path_lbl, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 10)
        fs.Add(self.hint_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 14)
        self.footer.SetSizer(fs)
        self.footer.SetMinSize((-1, self.FOOTER_H))

        outer.Add(self.header, 0, wx.EXPAND)
        # خط قرمز نئونی زیر نوار بالا (سبک 42LEVEL)
        self.neon_line = wx.Panel(self)
        self.neon_line.SetBackgroundColour(ACCENT)
        self.neon_line.SetMinSize((-1, 2))
        outer.Add(self.neon_line, 0, wx.EXPAND)
        outer.Add(self.image_panel, 1, wx.EXPAND)
        outer.Add(self.footer, 0, wx.EXPAND)

        # درگ از نوار بالا: روی خود هدر و تک‌تک اجزای داخل آن (آیکون/عنوان/وضعیت)
        # مستقیم بایند می‌کنیم، چون در ویندوز رویداد ماوسِ فرزند به فریم منتشر نمی‌شود.
        # حرکت و رهاکردن حین درگ از طریق CaptureMouse روی خود فریم دریافت می‌شود.
        for w in (self.header, self.icon_bmp, self.title_lbl, self.state_lbl):
            w.Bind(wx.EVT_LEFT_DOWN, self._on_drag_start)
        self.Bind(wx.EVT_MOTION, self._on_drag_move)
        self.Bind(wx.EVT_LEFT_UP, self._on_drag_end)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, self._on_capture_lost)
        # زوم با چرخ‌ی موس روی تصویر خروجی
        # چرخ موس = زوم (هم روی عکس هم روی پنل)؛ درگ موس = پن کردن در زوم بالا
        for w in (self.image_panel, self.image_ctrl):
            w.Bind(wx.EVT_MOUSEWHEEL, self._on_wheel)
            w.Bind(wx.EVT_LEFT_DOWN, self._on_pan_down)
            w.Bind(wx.EVT_MOTION, self._on_pan_move)
            w.Bind(wx.EVT_LEFT_UP, self._on_pan_up)
        self.image_panel.Bind(wx.EVT_MOUSE_CAPTURE_LOST, lambda e: self._on_pan_up())

    # ---------------- شکل و موقعیت ----------------
    def _on_size(self, evt):
        self._apply_shape()
        evt.Skip()

    def _apply_shape(self):
        try:
            w, h = self.GetSize()
            self.SetShape(rounded_region(w, h, 16))
        except Exception:
            pass

    def _position_top_right(self):
        sw, sh = wx.GetDisplaySize()
        self.SetPosition((max(20, sw - self.GetSize()[0] - 24), 24))

    def _center_over_focus(self, pid):
        """وسطِ پنجره‌ی هدف (بازی) را می‌گیرد تا ترجمه «داخل بازی» دیده شود."""
        try:
            hwnd = find_window_by_pid(pid)
            if not hwnd:
                return
            rect = window_rect(hwnd)
            if not rect:
                return
            w, h = self.GetSize()
            x = (rect[0] + rect[2]) // 2 - w // 2
            y = (rect[1] + rect[3]) // 2 - h // 2
            self.SetPosition((max(0, x), max(0, y)))
            self._clamp_to_screen()
        except Exception:
            pass

    def _apply_initial_position(self):
        """اولین نمایش: موقعیت ذخیره‌شده (اگر هست) یا گوشه‌ی بالا-راست."""
        pos = self.app.cfg["overlay_pos"]
        if isinstance(pos, (list, tuple)) and len(pos) == 2:
            try:
                self.SetPosition((int(pos[0]), int(pos[1])))
            except Exception:
                self._position_top_right()
        else:
            self._position_top_right()
        if not self._clamp_to_screen():
            # موقعیت ذخیره‌شده روی مانیتوری بود که دیگر در دسترس نیست → پیش‌فرض
            self._position_top_right()
            self._clamp_to_screen()
        self._positioned = True

    def _clamp_to_screen(self):
        """بعد از تغییر اندازه، پنجره را در محدوده‌ی همان نمایشگر نگاه می‌دارد؛
        موقعیت درگ‌شده را حفظ می‌کند و فقط اگر از صفحه بیرون زد اصلاحش می‌کند."""
        try:
            idx = wx.Display.GetFromWindow(self)
            if idx == wx.NOT_FOUND:
                return False
            rect = wx.Display(idx).GetClientArea()
            w, h = self.GetSize()
            x, y = self.GetPosition()
            m = 14
            min_x = rect.GetLeft() + m
            max_x = max(min_x, rect.GetRight() - w - m)
            min_y = rect.GetTop() + m
            max_y = max(min_y, rect.GetBottom() - h - m)
            x = min(max(x, min_x), max_x)
            y = min(max(y, min_y), max_y)
            if (x, y) != self.GetPosition():
                self.SetPosition((x, y))
            return True
        except Exception:
            return False

    def _save_position(self):
        try:
            self.app.cfg["overlay_pos"] = [int(v) for v in self.GetPosition()]
            self.app.cfg.save()
        except Exception:
            pass

    # ---------------- حالت‌ها ----------------
    def set_hotkey_text(self, hotkey):
        self.hint_lbl.SetLabel(T("برای بستن: {0}  |  قابلیت جابه‌جایی با درگ").format(hotkey.upper()))

    def apply_language(self):
        """بعد از تغییر زبان رابط، برچسب‌های ثابت Overlay را به‌روز می‌کند."""
        self.copy_btn.SetLabel(T("کپی"))
        self.set_hotkey_text(self.app.cfg["hotkey"])

    def show_translating(self, state_text):
        self._stop_auto()
        self._zoom = 1.0
        self._pan = (0, 0)
        self._set_zoom_label()
        self.state_lbl.SetForegroundColour(WARN)
        self.state_lbl.SetLabel(state_text)
        self.placeholder_lbl.SetLabel(T("در حال ترجمه…"))
        self.placeholder_lbl.SetForegroundColour(WARN)
        self.image_ctrl.SetBitmap(wx.Bitmap(1, 1))
        self.path_lbl.SetLabel("")
        self._size_for_image(None)
        self.Show()
        self.Raise()

    def show_result(self, img, path, auto_close_s, hotkey):
        self._stop_auto()
        self._current_img = img
        self._zoom = 1.0
        self._pan = (0, 0)
        self.state_lbl.SetForegroundColour(SUCCESS)
        self.state_lbl.SetLabel(T("ترجمه آماده است"))
        self.placeholder_lbl.SetLabel("")
        self.set_hotkey_text(hotkey)
        self.path_lbl.SetLabel(T("ذخیره شد: {0}").format(path))
        self.path_lbl.SetToolTip(path)
        # عکس‌های کوچک را بزرگ‌نمایی می‌کنیم تا هم راحت‌تر دیده شوند و هم
        # پنجره همیشه آن‌قدر بزرگ باشد که دکمه‌های «کپی» و «✕» دیده شوند
        self._render_image()
        self.Show()
        self.Raise()
        # اگر پنجره‌ی هدف (بازی) انتخاب شده باشد و هنوز هیچ موقعیت دستی (درگ) ذخیره‌ای
        # وجود ندارد، نتیجه روی همان پنجره نمایش داده می‌شود. بعد از اینکه کاربر
        # پنجره را جابه‌جا کرد، موقعیت درگ‌شده حفظ می‌شود و دیگر به وسط بازی برنمی‌گردد
        pid = self.app.cfg.get("focus_pid")
        saved = self.app.cfg.get("overlay_pos")
        if pid and not (isinstance(saved, (list, tuple)) and len(saved) == 2):
            self._center_over_focus(pid)

        if auto_close_s and auto_close_s > 0:
            self._auto_timer = wx.CallLater(auto_close_s * 1000, self._on_auto_close)

    def show_error(self, message):
        self._stop_auto()
        self._zoom = 1.0
        self._pan = (0, 0)
        self._set_zoom_label()
        self.state_lbl.SetForegroundColour(DANGER)
        self.state_lbl.SetLabel(T("خطا"))
        self.placeholder_lbl.SetLabel(message)
        self.placeholder_lbl.SetForegroundColour(DANGER)
        self.image_ctrl.SetBitmap(wx.Bitmap(1, 1))
        self.path_lbl.SetLabel("")
        self._size_for_image(None)
        self.Show()
        self.Raise()

    def _display_size_for(self, img):
        """اندازه‌ی نمایش عکس در پنجره؛ عکس‌های کوچک بزرگ‌نمایی می‌شوند تا
        پنجره همیشه به‌اندازه‌ی کافی بزرگ باشد و دکمه‌های کپی/بستن دیده شوند."""
        sw, sh = wx.GetDisplaySize()
        max_w = int(sw * 0.66) - 40
        max_h = int(sh * 0.72) - self.HEADER_H - self.FOOTER_H - 40
        if img is None:
            return min(420, max_w), min(180, max_h)
        scale = min(max_w / img.width, max_h / img.height, 1.0)
        min_scale = min(self.MIN_DISPLAY_W / img.width, self.MIN_DISPLAY_H / img.height)
        scale = max(scale, min(min_scale, self.ZOOM_CAP))
        scale = min(scale, min(max_w / img.width, max_h / img.height))
        return int(img.width * scale), int(img.height * scale)

    def _size_for_image(self, img):
        w, h = self._display_size_for(img)
        # حداقل عرض را رعایت کن تا حتی برای عکس‌های خیلی کوچک،
        # دکمه‌های «کپی» و «✕» در نوار بالا بیرون نزنند
        self.SetClientSize((max(w + self.PAD * 2, self.MIN_W),
                            self.HEADER_H + h + self.FOOTER_H))
        # موقعیت را بعد از تغییر اندازه حفظ کن؛ فقط بار اول جای پیش‌فرض را می‌گذاریم
        if not self._positioned:
            self._apply_initial_position()
        else:
            self._clamp_to_screen()

    # ---------------- زوم روی خروجی ترجمه ----------------
    def _set_zoom_label(self):
        self.zoom_lbl.SetLabel(f"{int(round(self._zoom * 100))}٪")

    def _render_image(self):
        """تصویر ترجمه‌شده را با زوم جاری رسم و پنجره را هم‌اندازه می‌کند.
        (قبلاً زوم به ۶۶٪ صفحه کلمپ می‌شد و عملاً کار نمی‌کرد؛ حالا عکس واقعاً
        بزرگ می‌شود — تا سقف پیکسل ۳۲۰۰ — و اگر از پنجره بزرگ‌تر شد، با درگ موس
        می‌شود پن کرد تا همه‌ی جزئیات دیده شود.)"""
        img = self._current_img
        if img is None:
            return
        base_w, base_h = self._display_size_for(img)
        zw = max(1, int(base_w * self._zoom))
        zh = max(1, int(base_h * self._zoom))
        # سقف پیکسلِ بیت‌مپ رسم‌شده (تا زوم ۴x روی عکس بزرگ، بیت‌مپ ۱۰۰ مگابایتی
        # روی نخ اصلی نسازد و رابط یخ نزند؛ برچسب زوم درصد واقعی را نشان می‌دهد)
        zw = min(zw, 3200)
        zh = min(zh, 2400)
        disp = img if (zw, zh) == (img.width, img.height) else img.resize((zw, zh), Image.LANCZOS)
        self.image_ctrl.SetBitmap(pil_to_wx_bitmap(disp))
        sw, sh = wx.GetDisplaySize()
        win_w = min(max(zw + self.PAD * 2, self.MIN_W), max(self.MIN_W, sw - 40))
        win_h = min(self.HEADER_H + zh + self.FOOTER_H, sh - 60)
        self.SetClientSize((win_w, win_h))
        self._reposition_image()
        self._set_zoom_label()
        if self._positioned:
            self._clamp_to_screen()
        else:
            self._apply_initial_position()

    def _reposition_image(self):
        """عکس را در پنل جای می‌دهد: اگر جا دارد وسط‌چین، وگرنه طبق پنِ کاربر."""
        try:
            aw = max(1, self.image_panel.GetClientSize().width)
            ah = max(1, self.image_panel.GetClientSize().height)
            zw = self.image_ctrl.GetBitmap().GetWidth()
            zh = self.image_ctrl.GetBitmap().GetHeight()
            max_px = max(0, zw - aw)
            max_py = max(0, zh - ah)
            pan_x = min(max(0, self._pan[0]), max_px)
            pan_y = min(max(0, self._pan[1]), max_py)
            self._pan = (pan_x, pan_y)
            x = -pan_x if zw > aw else (aw - zw) // 2
            y = -pan_y if zh > ah else (ah - zh) // 2
            self.image_ctrl.SetPosition((x, y))
        except Exception:
            pass

    def _on_panel_size(self, evt):
        self._reposition_image()
        evt.Skip()

    # ---------------- پن با درگ موس (در زوم بالا) ----------------
    def _on_pan_down(self, evt):
        if self._current_img is None:
            return
        self._pan_start = (wx.GetMousePosition(), self._pan)
        try:
            self.image_panel.CaptureMouse()
        except Exception:
            pass

    def _on_pan_move(self, evt):
        if self._pan_start is None:
            return
        (mx0, my0), (px, py) = self._pan_start
        mx, my = wx.GetMousePosition()
        self._pan = (px + (mx0 - mx), py + (my0 - my))
        self._reposition_image()

    def _on_pan_up(self, evt=None):
        if self._pan_start is not None:
            self._pan_start = None
            try:
                if self.image_panel.HasCapture():
                    self.image_panel.ReleaseMouse()
            except Exception:
                pass

    def _on_zoom_in(self, evt):
        if self._current_img is None:
            return
        self._zoom = min(4.0, self._zoom * 1.25)
        self._render_image()

    def _on_zoom_out(self, evt):
        if self._current_img is None:
            return
        self._zoom = max(0.4, self._zoom / 1.25)
        self._render_image()

    def _on_wheel(self, evt):
        if self._current_img is None:
            return
        factor = 1.15 if evt.GetWheelRotation() > 0 else 1 / 1.15
        self._zoom = min(4.0, max(0.4, self._zoom * factor))
        self._render_image()

    # ---------------- اکشن‌ها ----------------
    def _on_copy(self, evt):
        if self._current_img is not None:
            # جلوگیری از لوپِ «کپی ← ترجمه‌ی دوباره»:
            # ۱) هش تصویر را به مونیتور می‌دهیم  ۲) پایش را موقتاً قفل می‌کنیم
            h = image_hash(self._current_img)
            if h:
                self.app.last_hash = h
            self.app.processing = True
            wx.CallLater(2000, self.app._release_lock)
            copy_pil_to_clipboard(self._current_img)
            self.state_lbl.SetForegroundColour(SUCCESS)
            self.state_lbl.SetLabel(T("کپی شد ✓"))

    def _on_close(self, evt):
        self.hide_overlay()

    def _on_auto_close(self):
        if self.IsShown():
            self.hide_overlay()

    def hide_overlay(self):
        self._stop_auto()
        if self._dragging:
            self._dragging = False
            if self.HasCapture():
                self.ReleaseMouse()
        self.Hide()

    def _stop_auto(self):
        if self._auto_timer is not None:
            try:
                if self._auto_timer.IsRunning():
                    self._auto_timer.Stop()
            except Exception:
                pass
            self._auto_timer = None

    # ---------------- درگ ----------------
    def _on_drag_start(self, evt):
        if self._dragging:
            return
        # فقط از نوار بالا (هدر) قابل درگ است؛ از مختصات صفحه استفاده می‌کنیم تا
        # بدون توجه به اینکه روی کدام فرزند کلیک شده، آفست دقیق بماند
        pt = self.ScreenToClient(wx.GetMousePosition())
        if pt.y > self.HEADER_H:
            return
        self._dragging = True
        self._drag_off_screen = wx.GetMousePosition()
        self._drag_frame_pos = self.GetPosition()
        self.CaptureMouse()

    def _on_drag_move(self, evt):
        if not self._dragging:
            return
        mx, my = wx.GetMousePosition()
        dx = mx - self._drag_off_screen[0]
        dy = my - self._drag_off_screen[1]
        self.SetPosition((self._drag_frame_pos[0] + dx, self._drag_frame_pos[1] + dy))

    def _on_drag_end(self, evt):
        if self._dragging:
            self._dragging = False
            if self.HasCapture():
                self.ReleaseMouse()
            self._save_position()

    def _on_capture_lost(self, evt):
        self._dragging = False
        self._save_position()

    def shutdown(self):
        self._stop_auto()
        try:
            self.Destroy()
        except Exception:
            pass


# ----------------------------------------------------------------------
# پنجره‌ی تنظیمات
# ----------------------------------------------------------------------
class SettingsDialog(wx.Dialog):
    def __init__(self, parent, cfg):
        super().__init__(parent, title=T("تنظیمات Level Translator"), size=(560, 760),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.app = parent
        self.cfg = cfg
        self.recording = False
        self._rec_target = "close"
        self._down = set()
        self._hook = None
        self._pending_close = None   # کلید ضبط‌شده‌ی «بستن عکس» (پیش از ذخیره)
        self._pending_snip = None    # کلید ضبط‌شده‌ی «اسکرین‌شات» (پیش از ذخیره)

        self.SetFont(ui_font(10))
        self.SetBackgroundColour(BG)
        self._build_ui()

    def _group(self, parent, bs, icon, title):
        """یک دسته‌بندی می‌سازد: آیکون + عنوان قرمز + خط جداکننده + کارتِ محتوا.
        برمی‌گرداند: (کارت، سایزرِ داخل کارت). کنترل‌های هر دسته باید با
        «کارت» به‌عنوان والد ساخته شوند تا چیدمان درست بماند."""
        head = wx.BoxSizer(wx.HORIZONTAL)
        line = wx.Panel(parent, size=(-1, 2), style=wx.BORDER_NONE)
        line.SetBackgroundColour(BORDER)
        head.Add(line, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 12)
        box = wx.Panel(parent, size=(26, 26), style=wx.BORDER_NONE)
        box.SetBackgroundColour(ACCENT)
        icon_lbl = wx.StaticText(box, label=icon)
        icon_lbl.SetForegroundColour(wx.Colour(255, 255, 255))
        icon_lbl.SetFont(ui_font(11, bold=True))
        bx = wx.BoxSizer(wx.VERTICAL)
        bx.Add(icon_lbl, 0, wx.ALIGN_CENTER)
        box.SetSizer(bx)
        head.Add(box, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        lbl = wx.StaticText(parent, label=title)
        lbl.SetForegroundColour(TEXT)
        lbl.SetFont(ui_font(11, bold=True))
        head.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 2)
        bs.Add(head, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 26)
        card = wx.Panel(parent)
        card.SetBackgroundColour(CARD)
        card.SetFont(ui_font(10))
        gs = wx.BoxSizer(wx.VERTICAL)
        card.SetSizer(gs)
        bs.Add(card, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)
        return card, gs

    def _build_ui(self):
        root = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(root)

        # هدر: بنر 42LEVEL + عنوان
        header = wx.Panel(self)
        header.SetBackgroundColour(PANEL)
        header.SetFont(ui_font(10))
        self.header = header
        hs = wx.BoxSizer(wx.VERTICAL)
        banner_bmp = load_banner_bitmap(int(self.GetSize()[0] * 0.72))
        if banner_bmp is not None and banner_bmp.IsOk():
            hs.Add(wx.StaticBitmap(header, bitmap=banner_bmp), 0,
                   wx.ALIGN_CENTER | wx.TOP, 10)
        tr = wx.BoxSizer(wx.HORIZONTAL)
        t = wx.StaticText(header, label=T("تنظیمات Level Translator"))
        t.SetForegroundColour(TEXT)
        t.SetFont(ui_font(14, bold=True))
        tr.AddStretchSpacer(1)
        tr.Add(t, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
        tr.Add(wx.StaticBitmap(header, bitmap=load_logo_bitmap(32) or make_app_bitmap(32)),
               0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 16)
        hs.Add(tr, 0, wx.EXPAND | wx.TOP | wx.BOTTOM, 8)
        header.SetSizer(hs)
        root.Add(header, 0, wx.EXPAND)

        # پنل اسکرول‌دار تا در صفحه‌های کوچک هم همه‌ی بخش‌ها دیده شود
        body = wx.ScrolledWindow(self)
        body.SetScrollRate(0, 12)
        body.SetBackgroundColour(BG)
        body.SetFont(ui_font(10))
        self.body = body
        bs = wx.BoxSizer(wx.VERTICAL)

        # ---------- دسته‌بندی‌ها (هر کدام با عنوان + خط جداکننده + کارت) ----------
        # --- دسته‌ی ۰: زبان رابط (فارسی/انگلیسی) ---
        card, g = self._group(body, bs, "\u21c6", T("زبان رابط"))
        ui_row = wx.BoxSizer(wx.HORIZONTAL)
        ui_note = wx.StaticText(card, label=T("زبان رابط برنامه"))
        ui_note.SetForegroundColour(TEXT)
        ui_note.SetFont(ui_font(10, bold=True))
        ui_sub = wx.StaticText(card, label=T("فارسی / English — کل برنامه به زبان انتخابی درمی‌آید"))
        ui_sub.SetForegroundColour(MUTED)
        ui_sub.SetFont(ui_font(9))
        ui_box = wx.BoxSizer(wx.VERTICAL)
        ui_box.Add(ui_note, 0, wx.ALIGN_RIGHT)
        ui_box.Add(ui_sub, 0, wx.ALIGN_RIGHT | wx.TOP, 2)
        self.ui_lang_combo = wx.ComboBox(card, choices=["فارسی", "English"],
                                         style=wx.CB_READONLY, size=(170, -1))
        self.ui_lang_combo.SetBackgroundColour(PANEL)
        self.ui_lang_combo.SetForegroundColour(TEXT)
        self.ui_lang_combo.SetSelection(0 if UI_LANG == "fa" else 1)
        ui_row.Add(ui_box, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 6)
        ui_row.Add(self.ui_lang_combo, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        g.Add(ui_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 12)
        self.ui_lang_combo.Bind(wx.EVT_COMBOBOX, self._on_ui_lang)
        g.AddSpacer(10)

        # --- دسته‌ی ۱: میانبرها ---
        card, g = self._group(body, bs, "\u2328", T("میانبرها"))
        # بستن عکس ترجمه
        hotkey_row = wx.BoxSizer(wx.HORIZONTAL)
        self.hotkey_btn = FlatButton(card, self._hotkey_display(),
                                     lambda e: self._start_recording(e, "close"),
                                     kind="ghost", size=(170, 38))
        self.hotkey_hint = wx.StaticText(card, label=T("بستن عکس ترجمه — برای تغییر کلیک کنید و کلید جدید را بزنید"))
        self.hotkey_hint.SetForegroundColour(MUTED)
        hotkey_row.Add(self.hotkey_hint, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 6)
        hotkey_row.Add(self.hotkey_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        g.Add(hotkey_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 12)
        # گرفتن اسکرین‌شات
        snip_row = wx.BoxSizer(wx.HORIZONTAL)
        self.snip_btn = FlatButton(card, self._snip_display(),
                                   lambda e: self._start_recording(e, "snip"),
                                   kind="ghost", size=(170, 38))
        self.snip_hint = wx.StaticText(card, label=T("گرفتن اسکرین‌شات — برای تغییر کلیک کنید و کلید جدید را بزنید"))
        self.snip_hint.SetForegroundColour(MUTED)
        snip_row.Add(self.snip_hint, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 6)
        snip_row.Add(self.snip_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        g.Add(snip_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 8)
        g.AddSpacer(10)

        # --- دسته‌ی ۲: ترجمه و ذخیره‌سازی ---
        card, g = self._group(body, bs, "\u21c4", T("ترجمه و ذخیره‌سازی"))
        lang_row = wx.BoxSizer(wx.HORIZONTAL)
        lang_note = wx.StaticText(card, label=T("زبان مقصد ترجمه"))
        lang_note.SetForegroundColour(TEXT)
        lang_note.SetFont(ui_font(10, bold=True))
        lang_sub = wx.StaticText(card, label=T("تشخیص خودکار زبان مبدأ"))
        lang_sub.SetForegroundColour(MUTED)
        lang_sub.SetFont(ui_font(9))
        lang_box = wx.BoxSizer(wx.VERTICAL)
        lang_box.Add(lang_note, 0, wx.ALIGN_RIGHT)
        lang_box.Add(lang_sub, 0, wx.ALIGN_RIGHT | wx.TOP, 2)
        self.lang_combo = wx.ComboBox(card, choices=[T(name) for _, name in LANGUAGES],
                                      style=wx.CB_READONLY, size=(200, -1))
        self.lang_combo.SetBackgroundColour(PANEL)
        self.lang_combo.SetForegroundColour(TEXT)
        cur_idx = next((i for i, (c, _) in enumerate(LANGUAGES)
                        if c == self.cfg["target_lang"]), 0)
        self.lang_combo.SetSelection(cur_idx)
        lang_row.Add(lang_box, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 6)
        lang_row.Add(self.lang_combo, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        g.Add(lang_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 12)
        # پوشه‌ی ذخیره
        dir_row = wx.BoxSizer(wx.HORIZONTAL)
        self.dir_ctrl = wx.TextCtrl(card, value=self.cfg["save_dir"])
        self.dir_ctrl.SetBackgroundColour(CARD)
        self.dir_ctrl.SetForegroundColour(TEXT)
        self.dir_ctrl.SetEditable(False)
        dir_row.Add(FlatButton(card, T("باز کردن"), self._open_dir, kind="ghost", size=(90, 34)),
                    0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 6)
        dir_row.Add(FlatButton(card, T("انتخاب پوشه…"), self._pick_dir, kind="ghost", size=(120, 34)),
                    0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 6)
        dir_row.Add(self.dir_ctrl, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 6)
        g.Add(dir_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 8)
        g.AddSpacer(10)

        # --- دسته‌ی ۳: نمایش و اسکرین‌شات ---
        card, g = self._group(body, bs, "\u25a3", T("نمایش و اسکرین‌شات"))
        auto_row = wx.BoxSizer(wx.HORIZONTAL)
        self.auto_chk = wx.CheckBox(card, label=T("بستن خودکار پس از"))
        self.auto_chk.SetForegroundColour(TEXT)
        self.auto_chk.SetBackgroundColour(CARD)
        self.auto_spin = wx.SpinCtrl(card, min=5, max=600, initial=60)
        self.auto_spin.SetBackgroundColour(PANEL)
        self.auto_spin.SetForegroundColour(TEXT)
        auto_note = wx.StaticText(card, label=T("ثانیه (۰ = خاموش)"))
        auto_note.SetForegroundColour(MUTED)
        auto_row.Add(auto_note, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 6)
        auto_row.Add(self.auto_spin, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        auto_row.Add(self.auto_chk, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        g.Add(auto_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 12)
        acs = self.cfg["auto_close_seconds"]
        if acs and acs > 0:
            self.auto_chk.SetValue(True)
            self.auto_spin.SetValue(acs)
        else:
            self.auto_chk.SetValue(False)
            self.auto_spin.Disable()
        # نوار «42OCR فعال است»: مخفی‌شدن خودکار پس از N ثانیه
        badge_row = wx.BoxSizer(wx.HORIZONTAL)
        self.badge_chk = wx.CheckBox(card, label=T("مخفی شدن خودکار نشانک بازی پس از"))
        self.badge_chk.SetForegroundColour(TEXT)
        self.badge_chk.SetBackgroundColour(CARD)
        self.badge_spin = wx.SpinCtrl(card, min=5, max=600, initial=30)
        self.badge_spin.SetBackgroundColour(PANEL)
        self.badge_spin.SetForegroundColour(TEXT)
        badge_note = wx.StaticText(card, label=T("ثانیه (۰ = خاموش)"))
        badge_note.SetForegroundColour(MUTED)
        badge_row.Add(badge_note, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 6)
        badge_row.Add(self.badge_spin, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        badge_row.Add(self.badge_chk, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        g.Add(badge_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 12)
        bts = int(self.cfg.get("badge_timeout_seconds", 30) or 0)
        if bts > 0:
            self.badge_chk.SetValue(True)
            self.badge_spin.SetValue(bts)
        else:
            self.badge_chk.SetValue(False)
            self.badge_spin.Disable()
        badge_hint = wx.StaticText(card, label=T("نوار «42OCR فعال است» بالای بازی بعد از این مدت خودکار مخفی می‌شود"))
        badge_hint.SetForegroundColour(MUTED)
        badge_hint.SetFont(ui_font(9))
        g.Add(badge_hint, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 4)
        # پنجره‌ی هدف اسکرین‌شات
        focus_row = wx.BoxSizer(wx.HORIZONTAL)
        self.focus_lbl = wx.StaticText(card, label=self._focus_display())
        self.focus_lbl.SetForegroundColour(TEXT)
        self.focus_lbl.SetFont(ui_font(9))
        focus_row.Add(self.focus_lbl, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 6)
        focus_row.Add(FlatButton(card, T("انتخاب پنجره…"), lambda e: self._pick_focus(),
                                 kind="ghost", size=(130, 34)),
                      0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        g.Add(focus_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 8)
        snip_key = self.cfg.get("snip_hotkey", "f3").upper()
        focus_hint = wx.StaticText(card,
                                   label=T("مثلاً بازی فول‌اسکرین خود را انتخاب کنید؛ با {0} فقط از همان پنجره عکس کامل گرفته می‌شود").format(snip_key))
        focus_hint.SetForegroundColour(MUTED)
        focus_hint.SetFont(ui_font(9))
        g.Add(focus_hint, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 4)
        g.AddSpacer(10)

        # --- دسته‌ی ۴: سیستم ---
        card, g = self._group(body, bs, "\u2699", T("سیستم"))
        self.notif_chk = wx.CheckBox(card, label=T("نمایش اعلان هنگام آماده‌شدن ترجمه"))
        self.notif_chk.SetValue(bool(self.cfg["notifications"]))
        self.notif_chk.SetForegroundColour(TEXT)
        self.notif_chk.SetBackgroundColour(CARD)
        g.Add(self.notif_chk, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 12)
        self.startup_chk = wx.CheckBox(card, label=T("اجرای برنامه با هر بار استارت ویندوز"))
        self.startup_chk.SetValue(bool(self.cfg["run_on_startup"]))
        self.startup_chk.SetForegroundColour(TEXT)
        self.startup_chk.SetBackgroundColour(CARD)
        g.Add(self.startup_chk, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 8)
        startup_hint = wx.StaticText(card, label=T("با تیک زدن، یک ورودی در ریجستری استارت‌آپ ویندوز ساخته می‌شود"))
        startup_hint.SetForegroundColour(MUTED)
        startup_hint.SetFont(ui_font(9))
        g.Add(startup_hint, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 4)
        self.wipe_chk = wx.CheckBox(card, label=T("پاک‌سازی کامل پوشه‌ی ذخیره هنگام بستن برنامه"))
        self.wipe_chk.SetValue(bool(self.cfg["wipe_on_exit"]))
        self.wipe_chk.SetForegroundColour(TEXT)
        self.wipe_chk.SetBackgroundColour(CARD)
        g.Add(self.wipe_chk, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 8)
        wipe_hint = wx.StaticText(card, label=T("همه‌ی عکس‌های ترجمه‌شده حذف دائمی می‌شوند (بدون بازیابی، مثل Shift+Delete)"))
        wipe_hint.SetForegroundColour(MUTED)
        wipe_hint.SetFont(ui_font(9))
        g.Add(wipe_hint, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 4)
        g.AddSpacer(10)

        # --- دسته‌ی ۵: پیشرفته ---
        card, g = self._group(body, bs, "\u2630", T("پیشرفته"))
        cfg_row = wx.BoxSizer(wx.HORIZONTAL)
        cfg_note = wx.StaticText(card, label=self.cfg.path)
        cfg_note.SetForegroundColour(MUTED)
        cfg_note.SetFont(ui_font(9))
        cfg_row.Add(cfg_note, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 6)
        cfg_row.Add(FlatButton(card, T("باز کردن پوشه‌ی تنظیمات"), lambda e: self._open_cfg_dir(),
                               kind="ghost", size=(150, 34)),
                    0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        g.Add(cfg_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 12)
        g.AddSpacer(10)

        bs.AddStretchSpacer(1)

        # دکمه‌ها (راست‌چین: ذخیره پایین-چپ، انصراف پایین-راست)
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        save_btn = FlatButton(body, T("ذخیره تنظیمات"), self._on_save, kind="accent", size=(150, 38))
        cancel_btn = FlatButton(body, T("انصراف"), self._on_cancel, kind="ghost", size=(110, 38))
        btn_row.Add(save_btn, 0, wx.RIGHT, 20)
        btn_row.AddStretchSpacer(1)
        btn_row.Add(cancel_btn, 0, wx.RIGHT, 20)
        bs.Add(btn_row, 0, wx.EXPAND | wx.BOTTOM | wx.TOP, 20)

        body.SetSizer(bs)
        root.Add(body, 1, wx.EXPAND)
        body.FitInside()

        self.auto_chk.Bind(wx.EVT_CHECKBOX, self._on_auto_toggle)
        self.badge_chk.Bind(wx.EVT_CHECKBOX, self._on_badge_toggle)
        self.Bind(wx.EVT_CLOSE, self._on_cancel)


    def _hotkey_display(self):
        return (self._pending_close or self.cfg["hotkey"]).replace("+", " + ").upper()

    def _snip_display(self):
        return (self._pending_snip or self.cfg.get("snip_hotkey", "f3")).replace("+", " + ").upper()

    # ---------------- زبان رابط (فارسی/انگلیسی) ----------------
    def _snapshot(self):
        """وضعیت فعلی کنترل‌ها را برمی‌دارد تا بعد از بازسازی UI (تغییر زبان) بازیابی شود."""
        return {
            "lang_idx": self.lang_combo.GetSelection(),
            "dir": self.dir_ctrl.GetValue(),
            "auto_on": self.auto_chk.GetValue(),
            "auto_val": self.auto_spin.GetValue(),
            "badge_on": self.badge_chk.GetValue(),
            "badge_val": self.badge_spin.GetValue(),
            "notif": self.notif_chk.GetValue(),
            "startup": self.startup_chk.GetValue(),
            "wipe": self.wipe_chk.GetValue(),
        }

    def _restore(self, snap):
        self.lang_combo.SetSelection(snap["lang_idx"])
        self.dir_ctrl.SetValue(snap["dir"])
        self.auto_chk.SetValue(snap["auto_on"])
        self.auto_spin.SetValue(snap["auto_val"])
        self.auto_spin.Enable(snap["auto_on"])
        self.badge_chk.SetValue(snap["badge_on"])
        self.badge_spin.SetValue(snap["badge_val"])
        self.badge_spin.Enable(snap["badge_on"])
        self.notif_chk.SetValue(snap["notif"])
        self.startup_chk.SetValue(snap["startup"])
        self.wipe_chk.SetValue(snap["wipe"])
        self.ui_lang_combo.SetSelection(0 if UI_LANG == "fa" else 1)

    def _on_ui_lang(self, evt):
        """تغییر زبان رابط: کلیدهای ضبط‌شده حفظ و UI از نو ساخته می‌شود."""
        sel = self.ui_lang_combo.GetSelection()
        new_lang = "en" if sel == 1 else "fa"
        if new_lang == UI_LANG:
            return
        set_ui_lang(new_lang)
        # بعد از پایان رویداد، UI را از نو می‌سازیم (این رویداد داخلِ کامبو است)
        wx.CallAfter(self._rebuild_ui)

    def _rebuild_ui(self):
        """کل بدنه‌ی تنظیمات را با زبان جدید از نو می‌سازد (بدون از دست رفتن مقادیر)."""
        # اگر دیالوگ در همین فاصله بسته شده (ذخیره/انصراف زودهنگام)، کاری نکن
        if not self or self.IsBeingDeleted() or not self.GetSizer():
            return
        if self._hook is not None:
            try:
                keyboard.unhook(self._hook)
            except Exception:
                pass
            self._hook = None
            self.recording = False
        snap = self._snapshot()
        try:
            for ch in list(self.GetChildren()):
                try:
                    ch.Destroy()
                except Exception:
                    pass
        except Exception:
            pass
        self.SetSizer(None)
        self._build_ui()
        self._restore(snap)
        self.Layout()
        self.Refresh()

    # ---------------- ضبط کلید میانبر ----------------
    def _start_recording(self, evt, target="close"):
        if self.recording:
            return
        self.recording = True
        self._rec_target = target
        self._down.clear()
        btn = self.hotkey_btn if target == "close" else self.snip_btn
        hint = self.hotkey_hint if target == "close" else self.snip_hint
        btn.SetLabel(T("… کلید را بزنید"))
        btn.Refresh()
        hint.SetLabel(T("در حال ضبط… (Esc = انصراف)"))
        hint.SetForegroundColour(WARN)
        self._hook = keyboard.hook(self._record_handler)

    def _record_handler(self, e):
        if self._hook is None:
            return
        name = e.name or ""
        norm = name.lower()
        for mod in ("ctrl", "alt", "shift", "windows"):
            if norm.startswith("left " + mod) or norm.startswith("right " + mod):
                norm = mod
        if e.event_type == "down":
            self._down.add(norm)
            if norm in ("ctrl", "alt", "shift", "windows"):
                return
            if norm == "esc":
                wx.CallAfter(self._apply_recorded, None)
                return
            mods = [m for m in ("ctrl", "alt", "shift", "windows") if m in self._down]
            combo = "+".join(mods + [norm]) if mods else norm
            wx.CallAfter(self._apply_recorded, combo)
        else:
            self._down.discard(norm)

    def _apply_recorded(self, combo):
        if self._hook is not None:
            try:
                keyboard.unhook(self._hook)
            except Exception:
                pass
            self._hook = None
        self.recording = False
        target = self._rec_target
        btn = self.hotkey_btn if target == "close" else self.snip_btn
        hint = self.hotkey_hint if target == "close" else self.snip_hint
        hint.SetLabel(T("برای تغییر کلیک کنید و کلید (یا ترکیب) جدید را بزنید"))
        hint.SetForegroundColour(MUTED)
        if combo:
            if target == "close":
                self._pending_close = combo
            else:
                self._pending_snip = combo
            btn.SetLabel(combo.replace("+", " + ").upper())
            btn.Refresh()

    # ---------------- اکشن‌های دیگر ----------------
    def _on_auto_toggle(self, evt):
        self.auto_spin.Enable(self.auto_chk.GetValue())

    def _on_badge_toggle(self, evt):
        self.badge_spin.Enable(self.badge_chk.GetValue())

    def _pick_dir(self, evt):
        dlg = wx.DirDialog(self, T("پوشه‌ی ذخیره‌ی ترجمه‌ها"), self.cfg["save_dir"])
        if dlg.ShowModal() == wx.ID_OK:
            self.dir_ctrl.SetValue(dlg.GetPath())
        dlg.Destroy()

    def _open_dir(self, evt):
        d = self.dir_ctrl.GetValue()
        if os.path.isdir(d):
            os.startfile(d)

    def _focus_display(self):
        name = self.cfg["focus_name"]
        title = self.cfg["focus_title"]
        if name:
            return f"{title}  ({name})"
        return T("هیچ پنجره‌ای انتخاب نشده — {0} حالت مربع‌کشی دارد").format(
            self.cfg.get('snip_hotkey', 'f3').upper())

    def _pick_focus(self):
        dlg = ProcessManagerDialog(self, self.cfg)
        try:
            dlg.ShowModal()
        finally:
            dlg.Destroy()
        self.focus_lbl.SetLabel(self._focus_display())

    def _open_cfg_dir(self):
        try:
            os.makedirs(self.cfg.dir, exist_ok=True)
            os.startfile(self.cfg.dir)
        except Exception:
            pass

    def _on_save(self, evt):
        if self.recording:
            self._apply_recorded(None)
        # کلیدهای میانبر (فقط در صورت ضبط‌شدنِ کلید جدید)
        if self._pending_close:
            self.cfg["hotkey"] = self._pending_close
        if self._pending_snip:
            self.cfg["snip_hotkey"] = self._pending_snip
        # زبان مقصد ترجمه
        sel = self.lang_combo.GetSelection()
        if 0 <= sel < len(LANGUAGES):
            self.cfg["target_lang"] = LANGUAGES[sel][0]
        # زبان رابط
        self.cfg["ui_lang"] = "en" if self.ui_lang_combo.GetSelection() == 1 else "fa"
        # پوشه
        d = self.dir_ctrl.GetValue().strip()
        if d and os.path.isdir(d):
            self.cfg["save_dir"] = d
        # بستن خودکار
        if self.auto_chk.GetValue():
            self.cfg["auto_close_seconds"] = int(self.auto_spin.GetValue())
        else:
            self.cfg["auto_close_seconds"] = 0
        # مخفی‌شدن خودکار نوار بازی
        if self.badge_chk.GetValue():
            self.cfg["badge_timeout_seconds"] = int(self.badge_spin.GetValue())
        else:
            self.cfg["badge_timeout_seconds"] = 0
        self.cfg["notifications"] = bool(self.notif_chk.GetValue())
        self.cfg["run_on_startup"] = bool(self.startup_chk.GetValue())
        self.cfg["wipe_on_exit"] = bool(self.wipe_chk.GetValue())
        self.cfg.save()
        set_run_on_startup(self.cfg["run_on_startup"])
        self.EndModal(wx.ID_OK)

    def _on_cancel(self, evt=None):
        if self.recording:
            self._apply_recorded(None)
        self.EndModal(wx.ID_CANCEL)


# ----------------------------------------------------------------------
# ابزار اسکرین‌شات (شبیه Snipping Tool ویندوز) — کلید F3
# ----------------------------------------------------------------------
class SnipOverlay(wx.Frame):
    """با زدن F3 باز می‌شود؛ کاربر با موس مربع می‌کشد و بخش انتخاب‌شده
    به کلیپ‌بورد می‌رود تا همان‌جا ترجمه شود. Esc = انصراف."""

    SNIP_TIMEOUT_MS = 30000   # بدون انتخاب، بعد از این مدت خودکار بسته می‌شود

    def __init__(self, app):
        style = wx.FRAME_NO_TASKBAR | wx.STAY_ON_TOP | wx.BORDER_NONE
        super().__init__(None, style=style)
        self.app = app
        self._start = None
        self._current = None
        self._screen = None
        self._geom = (0, 0, 0, 0)
        self._bg_bmp = None        # عکس تیره‌شده‌ی کل صفحه (پس‌زمینه)
        self._full_bmp = None      # عکس اصلی (برای نمایش روشنِ بخش انتخاب‌شده)
        self._scale = (1.0, 1.0)   # نسبت عکسِ فیزیکی به پنجره‌ی منطقی (اصلاح DPI)
        self._starting = False     # در حال گرفتن عکس صفحه در نخ جدا
        self._cancelled = False    # انصراف قبل از آماده‌شدن عکس
        self._timeout = None       # اگر کاربر در ۳۰ ثانیه انتخاب نکند، خودکار بسته می‌شود
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetBackgroundColour(wx.Colour(10, 10, 12))
        self.SetCursor(wx.Cursor(wx.CURSOR_CROSS))
        # کرسر همیشه «بعلاوه» بماند (نه آیکون لودینگ/در حال بارگذاری)
        self.Bind(wx.EVT_SET_CURSOR, self._on_set_cursor)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_LEFT_DOWN, self._on_down)
        self.Bind(wx.EVT_MOTION, self._on_motion)
        self.Bind(wx.EVT_LEFT_UP, self._on_up)
        self.Bind(wx.EVT_KEY_DOWN, self._on_key)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, self._on_cancel)
        self.Hide()

    def _on_set_cursor(self, evt):
        evt.SetCursor(wx.Cursor(wx.CURSOR_CROSS))

    def start(self):
        if self.IsShown() or self._starting:
            return   # اگر همین حالا باز/در حال آماده‌شدن است، دوباره باز نمی‌شود
        self._starting = True
        self._cancelled = False
        self.SetCursor(wx.Cursor(wx.CURSOR_CROSS))
        try:
            g = wx.Display(0).GetGeometry()
            self._geom = (g.x, g.y, g.width, g.height)
        except Exception:
            self._geom = (0, 0) + tuple(wx.GetDisplaySize())
        ox, oy, sw, sh = self._geom
        self.SetPosition((ox, oy))
        self.SetSize((sw, sh))
        self._start = None
        self._current = None
        self._screen = None
        self._bg_bmp = None
        self._full_bmp = None
        # عکس صفحه در نخِ جدا گرفته می‌شود (قبل از نمایش پنجره تا خودِ overlay در عکس
        # نیفتد). چون نخ اصلی هرگز بلاک نمی‌شود، کرسر حالت «لودینگ» نمی‌گیرد و
        # پنجره با کرسر «بعلاوه» باز می‌شود.
        threading.Thread(target=self._grab_and_build, args=(sw, sh), daemon=True).start()

    def _grab_and_build(self, w, h):
        """در نخ جدا: گرفتن عکس صفحه + تغییر اندازه + تیره‌کردن (بدون دست زدن به wx)."""
        try:
            img = ImageGrab.grab()
        except Exception:
            img = None
        if img is None:
            wx.CallAfter(self._finish_build, None, None, None, (1.0, 1.0))
            return
        try:
            w, h = max(1, w), max(1, h)
            if img.size != (w, h):
                scale = (img.width / float(w), img.height / float(h))
                disp = img.resize((w, h), Image.BILINEAR)
            else:
                scale = (1.0, 1.0)
                disp = img
            rgb = disp.convert("RGB")
            # تیره‌کردن با جدول رنگ (سریع؛ بدون گرافیکس آلفا که لگ می‌آورد)
            lut = [int(i * 0.45) for i in range(256)] * 3
            dark = rgb.point(lut)
            wx.CallAfter(self._finish_build, img, rgb.tobytes(), dark.tobytes(), scale)
        except Exception:
            wx.CallAfter(self._finish_build, None, None, None, (1.0, 1.0))

    def _finish_build(self, screen, full_bytes, dark_bytes, scale):
        """روی نخ اصلی: حالا پنجره را نشان می‌دهیم (عکس قبلاً گرفته شده؛ پس خودِ
        پنجره در عکس نیست) و بیت‌مپ‌ها را می‌سازیم (سریع)."""
        self._starting = False
        if self._cancelled:
            return   # در همین فاصله انصراف داده شده
        if screen is None:
            # گرفتن عکس ناموفق بود — پنجره‌ی خالی/سیاه نشان نده، توست بده
            try:
                self.app.show_toast(T("گرفتن عکس صفحه ممکن نشد"),
                                    T("دوباره با {0} تلاش کنید").format(
                                        self.app.cfg.get('snip_hotkey', 'f3').upper()))
            except Exception:
                pass
            return
        self.Show()
        self.Raise()
        try:
            self.SetFocus()
        except Exception:
            pass
        self._screen = screen
        self._scale = scale
        w, h = self.GetSize()
        self._full_bmp = None
        self._bg_bmp = None
        if full_bytes and dark_bytes:
            try:
                self._full_bmp = wx.Bitmap.FromBuffer(w, h, full_bytes)
                self._bg_bmp = wx.Bitmap.FromBuffer(w, h, dark_bytes)
            except Exception:
                self._full_bmp = None
                self._bg_bmp = None
        self._restart_timeout()
        self.Refresh()

    # ---------------- رسم ----------------
    def _on_paint(self, evt):
        """نمای اسنیپ‌تول: عکسِ واقعیِ صفحه (تیره‌شده) + بخشِ انتخاب‌شده روشن.
        همه با BitBlt سریع رسم می‌شود (نه آلفای گرافیکس) تا روان باشد."""
        dc = wx.PaintDC(self)
        w, h = self.GetSize()
        if self._bg_bmp is not None and self._bg_bmp.IsOk():
            dc.DrawBitmap(self._bg_bmp, 0, 0)
        else:
            dc.SetBackground(wx.Brush(wx.Colour(10, 10, 12)))
            dc.Clear()

        # راهنمای بالای صفحه
        hint = T("برای انتخاب، کلیک کنید و بکشید   —   Esc = انصراف")
        dc.SetFont(ui_font(10, bold=True))
        tw, th = dc.GetTextExtent(hint)
        hx = (w - tw) // 2 - 14
        dc.SetBrush(wx.Brush(wx.Colour(14, 12, 14)))
        dc.SetPen(wx.Pen(ACCENT, 1))
        dc.DrawRoundedRectangle(hx, 16, tw + 28, th + 12, 8)
        dc.SetTextForeground(TEXT)
        dc.DrawText(hint, hx + 14, 20)

        # بخش انتخاب‌شده: همان‌جا روشن و بدون تیرگی دیده می‌شود + کادر قرمز
        if self._start is not None and self._current is not None:
            x1 = min(self._start.x, self._current.x)
            y1 = min(self._start.y, self._current.y)
            x2 = max(self._start.x, self._current.x)
            y2 = max(self._start.y, self._current.y)
            cw, ch = x2 - x1, y2 - y1
            if cw > 0 and ch > 0 and self._full_bmp is not None and self._full_bmp.IsOk():
                mem = wx.MemoryDC(self._full_bmp)
                dc.Blit(x1, y1, cw, ch, mem, x1, y1)
                mem.SelectObject(wx.NullBitmap)
            dc.SetPen(wx.Pen(ACCENT, 2))
            dc.SetBrush(wx.TRANSPARENT_BRUSH)
            dc.DrawRectangle(x1, y1, cw, ch)
            size_text = "%d × %d" % (cw, ch)
            dc.SetFont(ui_font(9, bold=True))
            stw, sth = dc.GetTextExtent(size_text)
            chip_w = stw + 16
            chip_h = sth + 8
            # برچسب اندازه را داخل پنجره نگه می‌داریم (برای انتخاب‌های خیلی کوچک)
            cx = min(x1 + 6, max(0, w - chip_w - 6))
            cy = min(y1 + 6, max(0, h - chip_h - 6))
            dc.SetBrush(wx.Brush(wx.Colour(14, 12, 14)))
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.DrawRoundedRectangle(cx, cy, chip_w, chip_h, 6)
            dc.SetTextForeground(wx.Colour(255, 255, 255))
            dc.DrawText(size_text, cx + 8, cy + 4)

    # ---------------- انتخاب با موس ----------------
    def _restart_timeout(self):
        """تایمر بسته‌شدن خودکار: اگر کاربر در ۳۰ ثانیه انتخاب نکند، اسنیپ بسته می‌شود."""
        self._stop_timeout()
        self._timeout = wx.CallLater(self.SNIP_TIMEOUT_MS, self._on_timeout)

    def _on_timeout(self):
        self._timeout = None
        if self.IsShown():
            self._on_cancel(None)

    def _stop_timeout(self):
        if self._timeout is not None:
            try:
                if self._timeout.IsRunning():
                    self._timeout.Stop()
            except Exception:
                pass
            self._timeout = None

    def _on_down(self, evt):
        self._start = evt.GetPosition()
        self._current = self._start
        self._stop_timeout()   # کاربر انتخاب را شروع کرد — دیگر بستن خودکار لازم نیست

    def _on_motion(self, evt):
        if self._start is not None:
            self._current = evt.GetPosition()
            self.Refresh()

    def _on_up(self, evt):
        if self._start is None:
            return
        self._current = evt.GetPosition()
        self._finish()

    def _finish(self):
        start, end = self._start, self._current
        self._stop()
        if start is None or end is None:
            return
        x1 = min(start.x, end.x)
        y1 = min(start.y, end.y)
        x2 = max(start.x, end.x)
        y2 = max(start.y, end.y)
        ox, oy = self._geom[0], self._geom[1]
        if (x2 - x1) < 4 or (y2 - y1) < 4:   # انتخاب خیلی کوچک → انصراف
            return
        if self._screen is not None:
            try:
                # مختصات موس (منطقی/DPI) را به پیکسل‌های فیزیکی عکس تبدیل می‌کنیم
                sx, sy = self._scale
                left = max(0, int((x1 + ox) * sx))
                top = max(0, int((y1 + oy) * sy))
                right = min(self._screen.width, int((x2 + ox) * sx))
                bottom = min(self._screen.height, int((y2 + oy) * sy))
                img = self._screen.crop((left, top, right, bottom))
                copy_pil_to_clipboard(img)
                # عکس اسنیپ هم در همان مسیر ذخیره‌ی برنامه ذخیره می‌شود
                try:
                    folder = self.app.cfg["save_dir"]
                    os.makedirs(folder, exist_ok=True)
                    name = "snip_" + datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ".png"
                    img.save(os.path.join(folder, name), "PNG")
                except Exception:
                    pass
                # ترجمه‌ی مستقیم (بدون اتکا به مونیتور کلیپ‌بورد) تا دیگر خطای
                # «پاسخ گوگل» بعد از اسنیپ دیده نشود — دقیقاً مثل مسیر PrtSc
                try:
                    self.app.on_snip_image(img)
                except Exception:
                    pass
                self.app.show_toast(T("اسکرین‌شات گرفته شد"),
                                    T("تصویر به کلیپ‌بورد رفت و در حال ترجمه است…"))
            except Exception:
                pass

    def _on_key(self, evt):
        if evt.GetKeyCode() == wx.WXK_ESCAPE:
            self._on_cancel(None)
        else:
            evt.Skip()

    def _on_cancel(self, evt=None):
        self._stop()

    def _stop(self):
        self._starting = False
        self._cancelled = True
        self._stop_timeout()
        try:
            if self.HasCapture():
                self.ReleaseMouse()
        except Exception:
            pass
        self._start = None
        self._current = None
        if self.IsShown():
            self.Hide()


# ----------------------------------------------------------------------
# مدیریت فرآیندها / پنجره‌ها — انتخاب پنجره‌ی هدف برای اسکرین‌شات
# ----------------------------------------------------------------------
class ProcessManagerDialog(wx.Dialog):
    """لیست پنجره‌های باز را نشان می‌دهد تا کاربر پنجره‌ی هدف (مثلاً بازی)
    را برای اسکرین‌شات انتخاب کند؛ بعد از آن F3 فقط از همان پنجره عکس کامل می‌گیرد."""

    def __init__(self, parent, cfg):
        super().__init__(parent, title=T("مدیریت فرآیندها — انتخاب پنجره‌ی هدف"),
                         size=(600, 470), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.cfg = cfg
        self._windows = []
        self.SetFont(ui_font(10))
        self.SetBackgroundColour(BG)
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        root = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(root)

        snip_key = self.cfg.get("snip_hotkey", "f3").upper()
        hint = wx.StaticText(self,
                             label=T("پنجره‌ی بازی/برنامه‌ای که می‌خواهید اسکرین‌شات فقط از آن گرفته شود را انتخاب کنید؛\n"
                                     "بعد از انتخاب، با زدن {0} عکس کامل همان پنجره به کلیپ‌بورد می‌رود و ترجمه می‌شود.").format(snip_key))
        hint.SetForegroundColour(MUTED)
        hint.SetFont(ui_font(9))
        root.Add(hint, 0, wx.LEFT | wx.RIGHT | wx.TOP, 14)

        self.list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.list.InsertColumn(0, T("پنجره"), width=360)
        self.list.InsertColumn(1, T("فرآیند"), width=150)
        self.list.SetBackgroundColour(CARD)
        self.list.SetForegroundColour(TEXT)
        root.Add(self.list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 12)
        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda e: self._on_select())

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        btn_row.Add(FlatButton(self, T("تازه‌سازی"), lambda e: self._refresh(),
                               kind="ghost", size=(110, 34)), 0, wx.RIGHT, 8)
        btn_row.Add(FlatButton(self, T("حذف انتخاب"), lambda e: self._on_clear(),
                               kind="ghost", size=(120, 34)), 0, wx.RIGHT, 8)
        btn_row.AddStretchSpacer(1)
        btn_row.Add(FlatButton(self, T("انتخاب"), lambda e: self._on_select(),
                               kind="ghost", size=(100, 34)), 0, wx.RIGHT, 8)
        btn_row.Add(FlatButton(self, T("تزریق به بازی"), lambda e: self._on_inject(),
                               kind="accent", size=(130, 34)), 0, wx.RIGHT, 16)
        root.Add(btn_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.TOP, 14)

        inject_note = wx.StaticText(
            self,
            label=T("تزریق = انتخاب پنجره + آوردن بازی به جلو + فعال‌شدن منوی شناور 42OCR داخل بازی"))
        inject_note.SetForegroundColour(MUTED)
        inject_note.SetFont(ui_font(8))
        root.Add(inject_note, 0, wx.ALIGN_LEFT | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

        self.Bind(wx.EVT_CLOSE, lambda e: self.EndModal(wx.ID_CANCEL))

    def _refresh(self):
        self._windows = enum_visible_windows()
        self.list.DeleteAllItems()
        cur_pid = self.cfg["focus_pid"]
        sel_idx = -1
        for i, (_hwnd, title, pid, exe) in enumerate(self._windows):
            idx = self.list.InsertItem(self.list.GetItemCount(), title or T("(بدون عنوان)"))
            self.list.SetItem(idx, 1, exe)
            if pid == cur_pid:
                sel_idx = idx
        if sel_idx >= 0:
            self.list.Select(sel_idx)
            self.list.Focus(sel_idx)

    def _on_select(self):
        idx = self.list.GetFirstSelected()
        if idx < 0 or idx >= len(self._windows):
            return
        _hwnd, title, pid, exe = self._windows[idx]
        self.cfg["focus_pid"] = pid
        self.cfg["focus_name"] = exe
        self.cfg["focus_title"] = title
        self.cfg.save()
        self.EndModal(wx.ID_OK)

    def _on_inject(self):
        """«تزریق»: انتخاب + آوردن بازی به جلو + اعلام موفقیت به برنامه‌ی اصلی."""
        idx = self.list.GetFirstSelected()
        if idx < 0 or idx >= len(self._windows):
            return
        _hwnd, title, pid, exe = self._windows[idx]
        self.cfg["focus_pid"] = pid
        self.cfg["focus_name"] = exe
        self.cfg["focus_title"] = title
        self.cfg.save()
        # آوردن بازی به جلو بعد از بستن دیالوگ انجام می‌شود (در manage_processes)
        self.EndModal(wx.ID_YES)

    def _on_clear(self):
        self.cfg["focus_pid"] = None
        self.cfg["focus_name"] = ""
        self.cfg["focus_title"] = ""
        self.cfg.save()
        self.EndModal(wx.ID_OK)


# ----------------------------------------------------------------------
# نشانک بالای بازی (وقتی پنجره‌ی هدف انتخاب شده)
# ----------------------------------------------------------------------
class GameBadge(wx.Frame):
    """نشانک شیشه‌ای کوچک بالای بازی: «42OCR فعال است — PrtSc = اسکرین‌شات از بازی».
    بدون گرفتن فوکوس (WS_EX_NOACTIVATE) و قابل کلیک‌عبور (WS_EX_TRANSPARENT) ساخته می‌شود
    تا بازی اذیت نشود. موقعیتش هر ۱.۵ ثانیه روی پنجره‌ی هدف نگه داشته می‌شود؛
    اگر بازی بسته شود، نشانک خودش مخفی می‌شود."""

    W, H = 292, 30
    AUTO_HIDE_MS = 30000   # پیش‌فرض مخفی‌شدن خودکار (از تنظیمات قابل تغییر است)

    def __init__(self, app):
        style = (wx.FRAME_NO_TASKBAR | wx.STAY_ON_TOP | wx.FRAME_SHAPED |
                 wx.BORDER_NONE | wx.POPUP_WINDOW)
        super().__init__(None, size=(self.W, self.H), style=style)
        self.app = app
        self._poll = None
        self._hide_timer = None   # تایمر مخفی‌شدن خودکار (مدت از تنظیمات خوانده می‌شود)
        self._glass_alpha = apply_glass(self)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_LEFT_DOWN, self._on_click)
        self.Bind(wx.EVT_ENTER_WINDOW, lambda e: self.SetCursor(wx.Cursor(wx.CURSOR_HAND)))
        self.Bind(wx.EVT_LEAVE_WINDOW, lambda e: self.SetCursor(wx.Cursor(wx.CURSOR_ARROW)))
        try:
            self.SetShape(rounded_region(self.W, self.H, 12))
        except Exception:
            pass
        self._set_overlay_style()
        self.Hide()

    def _btn_rect(self):
        """مستطیل دکمه‌ی کوچک‌سازی «—» در سمت راست نشانک."""
        size = 22
        return (self.W - 8 - size, (self.H - size) // 2, size, size)

    def _on_click(self, evt):
        bx, by, bw, bh = self._btn_rect()
        p = evt.GetPosition()
        if bx <= p.x <= bx + bw and by <= p.y <= by + bh:
            self.app.dismiss_game_overlay()
            return
        self.app.toggle_game_menu()

    def _set_overlay_style(self):
        """بدون فوکوس + خارج از Alt+Tab (ولی کلیک‌پذیر — موس به نشانک می‌رسد
        تا با کلیک، منوی شناور باز/بسته شود)."""
        try:
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            u = _user32()
            style = u.GetWindowLongW(self.GetHandle(), GWL_EXSTYLE)
            u.SetWindowLongW(self.GetHandle(), GWL_EXSTYLE, style | WS_EX_LAYERED)
        except Exception:
            pass
        set_no_activate(self.GetHandle())
        try:
            self.SetTransparent(255)
        except Exception:
            pass

    def _on_paint(self, evt):
        dc = wx.PaintDC(self)
        w, h = self.GetSize()
        draw_rounded_glass(dc, w, h, 12, PANEL, border=ACCENT, border_w=1,
                           alpha=self._glass_alpha)
        text = T("42OCR فعال است  •  PrtSc = اسکرین‌شات از بازی")
        dc.SetFont(ui_font(9, bold=True))
        dc.SetTextForeground(TEXT)
        tw, th = dc.GetTextExtent(text)
        # دکمه‌ی «—» در سمت راست هست؛ متن در فضای باقی‌مانده وسط‌چین می‌شود
        bx, by, bw, bh = self._btn_rect()
        avail = bx - 8   # از لبه‌ی چپ تا دکمه (با ۸ پیکسل فاصله)
        dc.DrawText(text, max(8, (avail - tw) // 2), (h - th) // 2 - 1)
        dc.SetBrush(wx.Brush(wx.Colour(10, 8, 10)))
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.DrawRoundedRectangle(bx, by, bw, bh, 6)
        dc.SetFont(ui_font(9, bold=True))
        dc.SetTextForeground(wx.Colour(255, 255, 255))
        gw, gh = dc.GetTextExtent("\u2014")
        dc.DrawText("\u2014", bx + (bw - gw) // 2, by + (bh - gh) // 2)

    def show_badge(self):
        self.Show()
        self.Raise()
        self._restart_hide_timer()
        self._tick()

    def _restart_hide_timer(self):
        """تایمر مخفی‌شدن خودکار را از نو شروع می‌کند.
        مدت از تنظیمات خوانده می‌شود (badge_timeout_seconds؛ ۰ = خاموش)."""
        self._stop_hide_timer()
        try:
            secs = int(self.app.cfg.get("badge_timeout_seconds",
                                         self.AUTO_HIDE_MS // 1000) or 0)
        except Exception:
            secs = self.AUTO_HIDE_MS // 1000
        if secs <= 0:
            return   # خاموش — نشانک می‌ماند تا کاربر کوچک/ببنددش
        self._hide_timer = wx.CallLater(secs * 1000, self._auto_hide)

    def _auto_hide(self):
        """بعد از مدت تنظیم‌شده نشانک مخفی می‌شود و دیگر تا فعال‌شدن دوباره برنمی‌گردد
        (حلقه‌ی جای‌دهی هم متوقف می‌شود تا بازی اذیت نشود). مثل دکمه‌ی «—» با
        حالت dismissed هماهنگ می‌شود تا همگام‌سازی دوباره نشانش ندهد."""
        self._hide_timer = None
        self._stop_poll()
        try:
            self.app._game_minimized = True
        except Exception:
            pass
        if self.IsShown():
            self.Hide()

    def _stop_hide_timer(self):
        if self._hide_timer is not None:
            try:
                if self._hide_timer.IsRunning():
                    self._hide_timer.Stop()
            except Exception:
                pass
            self._hide_timer = None

    def hide_badge(self):
        self._stop_poll()
        self._stop_hide_timer()
        if self.IsShown():
            self.Hide()

    def _tick(self):
        """جای نشانک را روی پنجره‌ی هدف نگه می‌دارد؛ بازی بسته شد → مخفی."""
        self._stop_poll()
        pid = self.app.cfg.get("focus_pid")
        hwnd = find_window_by_pid(pid) if pid else None
        if hwnd:
            rect = window_rect(hwnd)
            if rect:
                w, h = self.GetSize()
                x = (rect[0] + rect[2]) // 2 - w // 2
                y = rect[1] + 14
                if not self.IsShown():
                    self.Show()
                    self.Raise()
                self.SetPosition((max(0, x), max(0, y)))
            else:
                if self.IsShown():
                    self.Hide()
        else:
            if self.IsShown():
                self.Hide()
        self._poll = wx.CallLater(1500, self._tick)

    def _stop_poll(self):
        if self._poll is not None:
            try:
                if self._poll.IsRunning():
                    self._poll.Stop()
            except Exception:
                pass
            self._poll = None

    def shutdown(self):
        self.hide_badge()
        try:
            self.Destroy()
        except Exception:
            pass


# ----------------------------------------------------------------------
# منوی شناور «داخل بازی» (بعد از تزریق) — شبیه خود نرم‌افزار
# ----------------------------------------------------------------------
class GameMenu(wx.Frame):
    """منوی شناور کوچک که بعد از «تزریق به بازی» بالای پنجره‌ی بازی دیده می‌شود
    و دقیقاً مثل خود نرم‌افزار طراحی شده است (شیشه‌ای، راست‌چین، با لوگو و فونت وزیر).
    دکمه‌ی «—» همه‌چیز را در همان صفحه‌ی بازی کوچک می‌کند؛ با کلیک روی نشانکِ
    «42OCR» بالای بازی، منو دوباره باز می‌شود. فوکوس را از بازی نمی‌گیرد
    (WS_EX_NOACTIVATE) تا بازی به کارش ادامه دهد."""

    W, H = 226, 306
    HEADER_H = 42
    ROW_H = 38
    ROW_GAP = 6
    FOOTER_H = 32
    PAD = 12
    BTN = 24

    def __init__(self, app):
        style = (wx.FRAME_NO_TASKBAR | wx.STAY_ON_TOP | wx.FRAME_SHAPED |
                 wx.BORDER_NONE | wx.POPUP_WINDOW)
        super().__init__(None, size=(self.W, self.H), style=style)
        self.app = app
        self._poll = None
        self._hover = -1
        self._status = T("پایش: روشن")
        self._row_rects = []
        self._glass_alpha = apply_glass(self)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetBackgroundColour(BG)
        self._logo = load_logo_bitmap(20) or make_app_bitmap(20)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_MOTION, self._on_motion)
        self.Bind(wx.EVT_LEAVE_WINDOW, lambda e: self._set_hover(-1))
        # کلیک = فوکوس‌گرفتن (کپچر موسِ بازی می‌شکند) + اجرای کلیک
        self.Bind(wx.EVT_LEFT_DOWN, self._on_click_activate)
        # هاور = فقط بالاآوردن منو (فوکوس نمی‌گیریم تا بازی اذیت نشود)
        self.Bind(wx.EVT_ENTER_WINDOW, self._on_enter)
        try:
            self.SetShape(rounded_region(self.W, self.H, 14))
        except Exception:
            pass
        # برای کلیک‌شدن، NOACTIVATE نمی‌گذاریم (فقط از Alt+Tab مخفی می‌شود)
        set_toolwindow(self.GetHandle())
        self.Hide()

    def _rows(self):
        return [
            (T("ترجمه از بازی"), "\u21C4", self.app._on_prtsc),
            (T("اسکرین‌شات ({0})").format(self.app.cfg.get('snip_hotkey', 'f3').upper()), "\u2702", self.app.start_snip),
            (T("تنظیمات…"), "\u2699", self.app.open_settings),
            (T("مدیریت فرآیندها…"), "\u25A3", self.app.manage_processes),
        ]

    def _compute_row_rects(self):
        """مستطیل ردیف‌ها را بدون نیاز به رویداد paint محاسبه می‌کند تا کلیک
        حتی قبل از اولین کشیدنِ پنجره هم درست کار کند."""
        rects = []
        y = 8 + self.HEADER_H + 8
        for _i in range(len(self._rows())):
            rects.append((8, y, self.W - 16, self.ROW_H))
            y += self.ROW_H + self.ROW_GAP
        return rects

    # ---------------- نمایش / پنهان ----------------
    def show_menu(self):
        self._row_rects = self._compute_row_rects()
        # اگر زبان رابط عوض شده، متن وضعیتِ پیش‌فرض را هم به‌روز کن
        if self._status in ("پایش: روشن", "Monitor: ON"):
            self._status = T("پایش: روشن")
        self.Show()
        self.Raise()
        self._assert_topmost()
        self._tick()

    def _assert_topmost(self):
        """منو را بالای همه (از جمله بازی) نگه می‌دارد تا کلیک‌پذیر بماند."""
        try:
            u = _user32()
            u.SetWindowPos(self.GetHandle(), -1, 0, 0, 0, 0,
                           0x0001 | 0x0002 | 0x0010)   # NOMOVE|NOSIZE|NOACTIVATE → TOPMOST
        except Exception:
            pass

    def _on_enter(self, evt):
        """وقتی موس وارد منو می‌شود فقط آن را بالای بازی می‌آوریم
        (فوکوس نمی‌گیریم تا بازی اذیت نشود)."""
        self._assert_topmost()

    def _on_click_activate(self, evt):
        """موقع کلیک، منو فوکوس می‌گیرد (کپچر موسِ بازی می‌شکند) و بعد کلیک اجرا می‌شود."""
        try:
            u = _user32()
            try:
                u.AllowSetForegroundWindow.argtypes = [ctypes.c_ulong]
                u.AllowSetForegroundWindow(-1)
            except Exception:
                pass
            u.SetForegroundWindow(self.GetHandle())
        except Exception:
            pass
        try:
            self.SetFocus()
        except Exception:
            pass
        self._on_click(evt)

    def hide_menu(self):
        self._stop_poll()
        if self.IsShown():
            self.Hide()

    def set_status(self, text):
        """نوار وضعیت پایین منو (مثلاً «در حال ترجمه…»)."""
        if text != self._status:
            self._status = text
            if self.IsShown():
                self.Refresh()

    def _tick(self):
        """جای منو را زیر نشانکِ بالای بازی نگه می‌دارد؛ بازی بسته شد → مخفی."""
        self._stop_poll()
        pid = self.app.cfg.get("focus_pid")
        hwnd = find_window_by_pid(pid) if pid else None
        if hwnd:
            rect = window_rect(hwnd)
            if rect:
                w, h = self.GetSize()
                # گوشه‌ی بالا-راستِ تصویر بازی (به‌جای وسط‌چین)
                x = rect[2] - w - 12
                y = rect[1] + 12
                try:
                    sw, sh = wx.GetDisplaySize()
                    x = max(0, min(x, max(0, sw - w - 8)))
                    y = max(0, min(y, max(0, sh - h - 8)))
                except Exception:
                    pass
                if not self.IsShown():
                    self.Show()
                    self.Raise()
                self.SetPosition((x, y))
                self._assert_topmost()
            else:
                if self.IsShown():
                    self.Hide()
        else:
            if self.IsShown():
                self.Hide()
        self._poll = wx.CallLater(1500, self._tick)

    def _stop_poll(self):
        if self._poll is not None:
            try:
                if self._poll.IsRunning():
                    self._poll.Stop()
            except Exception:
                pass
            self._poll = None

    # ---------------- ماوس ----------------
    def _on_motion(self, evt):
        self._set_hover(self._hit_row(evt.GetPosition()))

    def _hit_row(self, pos):
        for i, rect in enumerate(self._row_rects):
            x, y, w, h = rect
            if x <= pos.x <= x + w and y <= pos.y <= y + h:
                return i
        return -1

    def _set_hover(self, idx):
        if idx != self._hover:
            self._hover = idx
            self.Refresh()

    def _on_click(self, evt):
        pos = evt.GetPosition()
        # دکمه‌های هدر (چپ): «—» = حذف کامل رابط داخل بازی، «×» = بستن منو
        by = 8 + (self.HEADER_H - self.BTN) // 2
        bx1 = 8
        if bx1 <= pos.x <= bx1 + self.BTN and by <= pos.y <= by + self.BTN:
            self.app.dismiss_game_overlay()
            return
        bx2 = bx1 + self.BTN + 4
        if bx2 <= pos.x <= bx2 + self.BTN and by <= pos.y <= by + self.BTN:
            self.app.close_game_menu()
            return
        idx = self._hit_row(pos)
        if 0 <= idx < len(self._rows()):
            _label, _icon, cb = self._rows()[idx]
            if cb:
                wx.CallAfter(cb)

    # ---------------- رسم ----------------
    def _on_paint(self, evt):
        dc = wx.PaintDC(self)
        w, h = self.GetSize()
        draw_rounded_glass(dc, w, h, 14, PANEL, border=ACCENT, border_w=1,
                           alpha=self._glass_alpha)
        y = 8
        # هدر (نوار قرمز): لوگو + عنوان سمت راست، دکمه‌های «—» و «×» سمت چپ
        dc.SetBrush(wx.Brush(ACCENT))
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.DrawRoundedRectangle(6, y, w - 12, self.HEADER_H, 10)
        dc.DrawBitmap(self._logo, w - 12 - 20, y + (self.HEADER_H - 20) // 2)
        dc.SetFont(ui_font(11, bold=True))
        dc.SetTextForeground(wx.Colour(255, 255, 255))
        tw, th = dc.GetTextExtent("42OCR")
        dc.DrawText("42OCR", w - 12 - 20 - 6 - tw, y + (self.HEADER_H - th) // 2)
        by = y + (self.HEADER_H - self.BTN) // 2
        self._draw_mini_btn(dc, 8, by, "\u2014")
        self._draw_mini_btn(dc, 8 + self.BTN + 4, by, "\u2715")
        y += self.HEADER_H + 8
        # ردیف‌ها (راست‌چین: آیکون سمت راست، برچسب کنارش)
        self._row_rects = []
        for i, (label, icon, _cb) in enumerate(self._rows()):
            hover = (i == self._hover)
            rect = (8, y, w - 16, self.ROW_H)
            self._row_rects.append(rect)
            if hover:
                dc.SetBrush(wx.Brush(ACCENT))
                dc.SetPen(wx.TRANSPARENT_PEN)
                dc.DrawRoundedRectangle(rect[0], rect[1], rect[2], rect[3], 9)
            dc.SetFont(ui_font(12))
            iw = dc.GetTextExtent(icon)[0]
            dc.SetTextForeground(wx.Colour(255, 255, 255) if hover else ACCENT)
            dc.DrawText(icon, rect[0] + rect[2] - self.PAD - iw,
                        rect[1] + (rect[3] - dc.GetTextExtent(icon)[1]) // 2)
            dc.SetFont(ui_font(10, bold=True))
            tw2, th2 = dc.GetTextExtent(label)
            dc.SetTextForeground(wx.Colour(255, 255, 255) if hover else TEXT)
            dc.DrawText(label, rect[0] + rect[2] - self.PAD - iw - 8 - tw2,
                        rect[1] + (rect[3] - th2) // 2)
            y += self.ROW_H + self.ROW_GAP
        # نوار وضعیت پایین
        y += 2
        dc.SetPen(wx.Pen(BORDER, 1))
        dc.DrawLine(14, y, w - 14, y)
        y += 8
        dc.SetFont(ui_font(9))
        dc.SetTextForeground(MUTED)
        stw, sth = dc.GetTextExtent(self._status)
        dc.DrawText(self._status, (w - stw) // 2, y)

    def _draw_mini_btn(self, dc, x, y, glyph):
        dc.SetBrush(wx.Brush(wx.Colour(10, 8, 10)))
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.DrawRoundedRectangle(x, y, self.BTN, self.BTN, 6)
        dc.SetFont(ui_font(10, bold=True))
        dc.SetTextForeground(wx.Colour(255, 255, 255))
        gw, gh = dc.GetTextExtent(glyph)
        dc.DrawText(glyph, x + (self.BTN - gw) // 2, y + (self.BTN - gh) // 2)

    def shutdown(self):
        self.hide_menu()
        try:
            self.Destroy()
        except Exception:
            pass


# ----------------------------------------------------------------------
# منوی شیشه‌ای راست‌چین تسک‌بار
# ----------------------------------------------------------------------
class GlassMenu(wx.Frame):
    """منوی مدرن و شیشه‌ای آیکون تسک‌بار؛ راست‌چین با فونت وزیر."""

    ROW_H = 40
    HEADER_H = 30
    SEP_H = 9
    PAD_X = 16

    def __init__(self, app):
        style = (wx.FRAME_NO_TASKBAR | wx.STAY_ON_TOP | wx.FRAME_SHAPED |
                 wx.BORDER_NONE | wx.POPUP_WINDOW)
        super().__init__(None, style=style)
        self.app = app
        self.items = []
        self._hover = -1
        self._open = False
        self._poll = None
        self._glass_alpha = apply_glass(self)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_MOTION, self._on_motion)
        self.Bind(wx.EVT_LEAVE_WINDOW, lambda e: self._set_hover(-1))
        self.Bind(wx.EVT_LEFT_DOWN, self._on_click)
        self.Hide()

    # ---------------- ساخت آیتم‌ها ----------------
    def build_items(self):
        pause = ({"icon": "\u23F8", "label": T("توقف موقت پایش کلیپ‌بورد")}
                 if self.app.monitor_active else
                 {"icon": "\u25B6", "label": T("ادامه‌ی پایش کلیپ‌بورد")})
        pause["cb"] = self.app.toggle_monitor
        self.items = [
            {"header": True, "label": (T("پایش کلیپ‌بورد: روشن") if self.app.monitor_active
                                        else T("پایش کلیپ‌بورد: متوقف"))},
            {"sep": True},
            {"icon": "\u2699", "label": T("تنظیمات…"), "cb": self.app.open_settings},
            # «اسکرین‌شات» منو را نمی‌بندد (keep_open) — به خواست کاربر، منو باز می‌ماند
            {"icon": "\u2702",
             "label": T("گرفتن اسکرین‌شات ({0})").format(self.app.cfg.get('snip_hotkey', 'f3').upper()),
             "keep_open": True, "cb": self.app.start_snip},
            {"icon": "\u25A3", "label": T("مدیریت فرآیندها…"), "cb": self.app.manage_processes},
            {"sep": True},
            pause,
            {"sep": True},
            {"icon": "\u2715", "label": T("خروج"), "danger": True,
             "cb": lambda: wx.CallAfter(self.app.quit)},
        ]
        self._compute_size()

    def _compute_size(self):
        dc = wx.MemoryDC(wx.Bitmap(1, 1))
        dc.SetFont(ui_font(10))
        h, w = 8, 0
        for it in self.items:
            if it.get("sep"):
                h += self.SEP_H
                continue
            tw = dc.GetTextExtent(it["label"])[0]
            w = max(w, tw)
            h += self.HEADER_H if it.get("header") else self.ROW_H
        width = max(252, w + 88)
        self.SetSize((width, h))
        try:
            self.SetShape(rounded_region(width, h, 14))
        except Exception:
            pass

    # ---------------- نمایش / بستن ----------------
    def show_menu(self):
        self.build_items()
        mx, my = wx.GetMousePosition()
        idx = wx.Display.GetFromPoint((mx, my))
        if idx != wx.NOT_FOUND:
            rect = wx.Display(idx).GetClientArea()
            ox, oy = rect.x, rect.y
            sw, sh = rect.width, rect.height
        else:
            ox, oy, sw, sh = 0, 0, *wx.GetDisplaySize()
        w, h = self.GetSize()
        x = min(max(mx - 12, ox + 4), ox + sw - w - 8)
        y = min(max(my - 8, oy + 4), oy + sh - h - 8)
        self.SetPosition((x, y))
        self._hover = -1
        self._open = True
        self.Show()
        self.Raise()
        self._start_poll()

    def close_menu(self):
        self._open = False
        if self._poll is not None:
            try:
                if self._poll.IsRunning():
                    self._poll.Stop()
            except Exception:
                pass
            self._poll = None
        if self.IsShown():
            self.Hide()

    def _start_poll(self):
        self._poll = wx.CallLater(60, self._poll_tick)

    def _poll_tick(self):
        """منو دیگر خودکار بسته نمی‌شود (نه با بیرون‌رفتن ماوس، نه بعد از اسکرین‌شات).
        فقط وقتی بسته می‌شود که کاربر بیرون از منو کلیک کند."""
        if not self._open:
            return
        try:
            mx, my = wx.GetMousePosition()
            x, y = self.GetPosition()
            w, h = self.GetSize()
            inside = (x <= mx <= x + w) and (y <= my <= y + h)
            ms = wx.GetMouseState()
            any_down = ms.LeftIsDown() or ms.RightIsDown() or ms.MiddleIsDown()
            # وقتی ابزار اسکرین‌شات باز است، کلیک‌های آن نباید منو را ببندد
            snip_open = bool(getattr(self.app, "snip", None) and self.app.snip.IsShown())
            if not inside and any_down and not snip_open:
                self.close_menu()
                return
        except Exception:
            self.close_menu()
            return
        self._start_poll()

    # ---------------- ماوس ----------------
    def _on_motion(self, evt):
        self._set_hover(self._hit_index(evt.GetPosition()))

    def _hit_index(self, pos):
        y = pos.y - 6
        for i, it in enumerate(self.items):
            if it.get("sep"):
                y -= self.SEP_H
                continue
            rh = self.HEADER_H if it.get("header") else self.ROW_H
            if 0 <= y < rh:
                return i if not it.get("header") else -1
            y -= rh
        return -1

    def _set_hover(self, idx):
        if idx != self._hover:
            self._hover = idx
            self.Refresh()

    def _on_click(self, evt):
        idx = self._hit_index(evt.GetPosition())
        cb = None
        keep = False
        if 0 <= idx < len(self.items):
            it = self.items[idx]
            cb = it.get("cb")
            keep = bool(it.get("keep_open", False))
        if not keep:
            self.close_menu()
        if cb:
            wx.CallAfter(cb)

    # ---------------- رسم ----------------
    def _on_paint(self, evt):
        dc = wx.PaintDC(self)
        w, h = self.GetSize()
        draw_rounded_glass(dc, w, h, 14, PANEL, border=ACCENT, border_w=1,
                           alpha=self._glass_alpha)
        y = 6
        for i, it in enumerate(self.items):
            if it.get("sep"):
                dc.SetPen(wx.Pen(BORDER, 1))
                dc.DrawLine(14, y + self.SEP_H // 2, w - 14, y + self.SEP_H // 2)
                y += self.SEP_H
                continue
            rh = self.HEADER_H if it.get("header") else self.ROW_H
            if it.get("header"):
                dc.SetFont(ui_font(9))
                dc.SetTextForeground(MUTED)
                tw = dc.GetTextExtent(it["label"])[0]
                dc.DrawText(it["label"], w - self.PAD_X - tw,
                            y + (rh - dc.GetTextExtent(it["label"])[1]) // 2)
                y += rh
                continue
            hover = (i == self._hover)
            danger = it.get("danger", False)
            if hover:
                dc.SetBrush(wx.Brush(ACCENT))
                dc.SetPen(wx.TRANSPARENT_PEN)
                dc.DrawRoundedRectangle(8, y, w - 16, rh - 4, 9)
            icon = it.get("icon", "")
            icon_w = 0
            if icon:
                dc.SetFont(ui_font(11))
                iw = dc.GetTextExtent(icon)[0]
                ix = w - self.PAD_X - iw
                dc.SetTextForeground(wx.Colour(255, 255, 255) if hover else ACCENT)
                dc.DrawText(icon, ix, y + (rh - dc.GetTextExtent(icon)[1]) // 2)
                icon_w = iw
            dc.SetFont(ui_font(10, bold=danger))
            tw = dc.GetTextExtent(it["label"])[0]
            dc.SetTextForeground(wx.Colour(255, 255, 255) if hover else TEXT)
            dc.DrawText(it["label"], w - self.PAD_X - icon_w - 12 - tw,
                        y + (rh - dc.GetTextExtent(it["label"])[1]) // 2)
            y += rh


# ----------------------------------------------------------------------
# آیکون System Tray
# ----------------------------------------------------------------------
class TrayIcon(wx.adv.TaskBarIcon):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.SetIcon(make_app_icon(), self.app._tray_tooltip())
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DCLICK, lambda e: self.app.open_settings())
        # منوی سفارشی شیشه‌ای به‌جای منوی پیش‌فرض ویندوز
        self.Bind(wx.adv.EVT_TASKBAR_RIGHT_UP, lambda e: self.app.show_tray_menu())

    def CreatePopupMenu(self):
        # منوی شیشه‌ای سفارشی جایگزین این شده؛ None یعنی منوی پیش‌فرض نشان داده نشود
        return None


# ----------------------------------------------------------------------
# برنامه‌ی اصلی: پایش کلیپ‌بورد + مدیریت همه‌چیز
# ----------------------------------------------------------------------
class OCR42App(wx.Frame):
    def __init__(self, selftest=False):
        super().__init__(None)  # فریم نامرئی، فقط برای زنده نگه‌داشتن اپ

        self.cfg = Config()
        set_ui_lang(self.cfg.get("ui_lang", "fa"))   # زبان رابط از تنظیمات ذخیره‌شده
        self._selftest = selftest
        if not selftest and self.cfg["run_on_startup"]:
            set_run_on_startup(True)   # اگر ورودی ریجستری حذف شده بود، دوباره ساخته شود
        self.monitor_active = True
        self.processing = False
        self.last_hash = None
        self._hotkey_handle = None
        self._snip_hotkey = None
        self._snip_timer = None
        self._busy = False

        self.toast = Toast(self)
        self._menu = None
        self.snip = SnipOverlay(self)
        self.worker = TranslateWorker(self._on_translate_result,
                                      self._on_translate_error,
                                      self._on_translate_state)
        self.overlay = ImageOverlay(self)
        self.tray = TrayIcon(self)
        self.game_badge = GameBadge(self)
        self.game_menu = GameMenu(self)     # منوی شناور داخل بازی (بعد از تزریق)
        self._game_minimized = False        # همه‌چیز داخل بازی کوچک شده؟

        self.overlay.set_hotkey_text(self.cfg["hotkey"])
        self._register_hotkey(self.cfg["hotkey"])
        self._register_snip_hotkey()

        self._prtsc_hotkey = None
        self.welcome = None   # جعبه‌ی 42OCR — با باز شدن برنامه هم نمایش داده می‌شود
        if not selftest:
            # تا برنامه بعد از بازشدن، عکسِ کهنه‌ی کلیپ‌بورد را خودکار ترجمه نکند
            self._seed_clipboard_state()
            self._start_clipboard_monitor()
            self._sync_game_mode()
            # جعبه‌ی 42OCR با باز شدن برنامه نمایش داده می‌شود (و با راست‌کلیک روی
            # تسک‌بار هم دوباره می‌آید)
            wx.CallLater(600, self.show_welcome_box)
        self._status_line()

    # ---------------- پایش کلیپ‌بورد ----------------
    def _start_clipboard_monitor(self):
        def monitor():
            while self.monitor_active:
                try:
                    if not self.processing and not self._busy:
                        candidate = self._extract_clipboard_image()
                        if candidate is not None:
                            h = image_hash(candidate)
                            if h and h != self.last_hash:
                                self.last_hash = h
                                self.processing = True
                                wx.CallAfter(self._on_new_screenshot, candidate)
                except Exception as e:
                    print(T("خطای پایش کلیپ‌بورد: {0}").format(e))
                time.sleep(0.5)
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

    def _on_new_screenshot(self, img):
        self.processing = False
        self._begin_translation(img)
        wx.CallLater(1500, self._release_lock)

    def _release_lock(self):
        self.processing = False

    # ---------------- اجرای ترجمه ----------------
    def _begin_translation(self, img):
        # کارگرِ ترجمه خودش ترجمه‌ی گیرکرده را صفر می‌کند (نگاه کن به start_upload)؛
        # پس برنامه هیچ‌وقت روی «در حال ترجمه…» گیر نمی‌کند و هر بار که دکمه زده شد
        # (F3 / PrtSc / فایل) یک ترجمه‌ی تازه شروع می‌شود.
        self._busy = True
        self.overlay.show_translating(T("در حال ترجمه…"))
        self.game_menu.set_status(T("در حال ترجمه…"))
        if not self.worker.start_upload(img, self.cfg["target_lang"]):
            self._busy = False
            self.overlay.show_error(T("یک ترجمه در حال انجام است؛ کمی صبر کنید."))

    def on_snip_image(self, img):
        """عکس اسنیپ‌شده را مستقیم ترجمه می‌کند (نه از طریق مونیتور کلیپ‌بورد)
        تا خطای «پاسخ گوگل» بعد از اسنیپ دیگر رخ ندهد. مونیتور همان هش را می‌بیند
        و ترجمه‌ی تکراری انجام نمی‌دهد."""
        h = image_hash(img)
        if h:
            self.last_hash = h
        self._begin_translation(img)

    def _on_translate_state(self, state_text):
        if self._busy:
            self.overlay.state_lbl.SetLabel(state_text)
        self.game_menu.set_status(state_text)

    def _on_translate_result(self, data_url, img):
        self._busy = False
        self.game_menu.set_status(T("ترجمه آماده ✓"))
        try:
            path = self._save_image(img)
        except Exception as e:
            self.overlay.show_error(T("خطا در ذخیره‌ی تصویر: {0}").format(e))
            return
        self.overlay.show_result(img, path, self.cfg["auto_close_seconds"], self.cfg["hotkey"])
        if self.cfg["notifications"]:
            self._notify(T("ترجمه آماده شد"), T("تصویر ترجمه‌شده در پوشه‌ی ذخیره ثبت شد."))

    def _on_translate_error(self, message):
        self._busy = False
        self.game_menu.set_status(T("خطا — دوباره تلاش کنید"))
        self.overlay.show_error(message)

    def _save_image(self, img):
        folder = self.cfg["save_dir"]
        try:
            os.makedirs(folder, exist_ok=True)
        except Exception:
            folder = os.path.expanduser("~")
        name = "translate_" + datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ".png"
        path = os.path.join(folder, name)
        img.convert("RGB").save(path, "PNG")
        return path

    def _notify(self, title, message):
        try:
            n = wx.adv.NotificationMessage(title, message, self,
                                           wx.ICON_INFORMATION)
            n.SetIcon(make_app_icon())
            n.Show()
        except Exception:
            pass

    # ---------------- کلید میانبر ----------------
    def _register_hotkey(self, combo):
        try:
            if self._hotkey_handle is not None:
                keyboard.remove_hotkey(self._hotkey_handle)
        except Exception:
            pass
        self._hotkey_handle = None
        try:
            self._hotkey_handle = keyboard.add_hotkey(
                combo, lambda: wx.CallAfter(self.overlay.hide_overlay))
        except Exception as e:
            print("خطا در ثبت کلید میانبر:", e)

    def _unregister_hotkey(self):
        try:
            if self._hotkey_handle is not None:
                keyboard.remove_hotkey(self._hotkey_handle)
        except Exception:
            pass
        self._hotkey_handle = None

    # ---------------- ابزار اسکرین‌شات (پیش‌فرض F3) ----------------
    def _register_snip_hotkey(self):
        """کلید اسکرین‌شات (پیش‌فرض F3، قابل تغییر از تنظیمات) → باز شدن ابزار اسکرین‌شات."""
        combo = self.cfg.get("snip_hotkey", "f3")
        try:
            self._snip_hotkey = keyboard.add_hotkey(
                combo, lambda: wx.CallAfter(self.start_snip))
        except Exception as e:
            print("خطا در ثبت کلید میانبر اسکرین‌شات:", e)

    def _unregister_snip_hotkey(self):
        try:
            if self._snip_hotkey is not None:
                keyboard.remove_hotkey(self._snip_hotkey)
        except Exception:
            pass
        self._snip_hotkey = None

    # ---------------- حالت «هدف بازی»: PrtSc + نشانک بالای بازی ----------------
    def _seed_clipboard_state(self):
        """تا برنامه بعد از بازشدن، عکسِ کهنه‌ی کلیپ‌بورد را خودکار ترجمه نکند
        (ترجمه فقط وقتی دکمه زده شد یا عکس تازه‌ای کپی شد شروع می‌شود)."""
        try:
            img = self._extract_clipboard_image()
            if img is not None:
                h = image_hash(img)
                if h:
                    self.last_hash = h
        except Exception:
            pass

    def _sync_game_mode(self):
        """اگر پنجره‌ی هدف انتخاب شده باشد: کلید PrtSc عکس کامل از همان پنجره می‌گیرد،
        نشانک «42OCR فعال است» بالای بازی ظاهر می‌شود و منوی شناور باز می‌شود.
        اگر کاربر با «—» رابط را حذف کرده باشد (dismissed)، چیزی دوباره باز نمی‌شود
        تا دوباره از «مدیریت فرآیندها» انتخاب کند."""
        pid = self.cfg["focus_pid"]
        if pid:
            self._register_prtsc_hotkey()
            if not self._game_minimized:
                try:
                    self.game_badge.show_badge()
                except Exception:
                    pass
                try:
                    self.game_menu.show_menu()
                except Exception:
                    pass
        else:
            self._game_minimized = False
            self._unregister_prtsc_hotkey()
            try:
                self.game_badge.hide_badge()
            except Exception:
                pass
            try:
                self.game_menu.hide_menu()
            except Exception:
                pass

    # ---------------- منوی شناور داخل بازی ----------------
    def toggle_game_menu(self):
        """کلیک روی نشانکِ بالای بازی: منوی شناور را باز/بسته می‌کند."""
        if self.game_menu.IsShown():
            self.game_menu.hide_menu()
        else:
            self._game_minimized = False
            try:
                self.game_badge.show_badge()
                self.game_menu.show_menu()
            except Exception:
                pass

    def dismiss_game_overlay(self):
        """دکمه‌ی «—» (روی نشانک یا منوی شناور): کل رابط داخل بازی (نشانک + منو)
        کاملاً مخفی می‌شود و دیگر نه با تایمر، نه با همگام‌سازی، خودش برنمی‌گردد.
        فقط با انتخاب دوباره‌ی پنجره‌ی هدف از «مدیریت فرآیندها» دوباره می‌آید."""
        self._game_minimized = True
        try:
            self.game_menu.hide_menu()
            self.game_badge.hide_badge()
        except Exception:
            pass

    def close_game_menu(self):
        """دکمه‌ی «×»: منوی شناور بسته می‌شود؛ نشانک بالای بازی می‌ماند."""
        try:
            self.game_menu.hide_menu()
        except Exception:
            pass

    def _register_prtsc_hotkey(self):
        try:
            if self._prtsc_hotkey is None:
                self._prtsc_hotkey = keyboard.add_hotkey(
                    "print screen", lambda: wx.CallAfter(self._on_prtsc))
        except Exception as e:
            print("خطا در ثبت کلید PrtSc:", e)

    def _unregister_prtsc_hotkey(self):
        try:
            if self._prtsc_hotkey is not None:
                keyboard.remove_hotkey(self._prtsc_hotkey)
        except Exception:
            pass
        self._prtsc_hotkey = None

    def _on_prtsc(self):
        """با PrtSc، عکس کاملِ پنجره‌ی هدف (بازی) گرفته و ترجمه می‌شود."""
        pid = self.cfg["focus_pid"]
        if pid:
            hwnd = find_window_by_pid(pid)
            if hwnd:
                self._capture_window(hwnd)
                return
            self.show_toast(T("پنجره‌ی هدف پیدا نشد"),
                            T("بازی بسته شده؛ دوباره از «مدیریت فرآیندها» انتخاب کنید"))
            return
        self.show_toast(T("پنجره‌ی هدفی انتخاب نشده"),
                        T("از منوی تسک‌بار → «مدیریت فرآیندها» یک پنجره انتخاب کنید"))

    def start_snip(self):
        """اگر پنجره‌ی هدف (بازی) انتخاب شده باشد، عکس کامل همان پنجره گرفته می‌شود؛
        وگرنه حالت مربع‌کشی تعاملی مثل Snipping Tool."""
        pid = self.cfg["focus_pid"]
        if pid:
            hwnd = find_window_by_pid(pid)
            if hwnd:
                self._capture_window(hwnd)
                return
        try:
            self.snip.start()
        except Exception:
            pass

    def _capture_window(self, hwnd):
        if not window_rect(hwnd):
            try:
                self.snip.start()
            except Exception:
                pass
            return
        bring_window_front(hwnd)
        # کمی صبر تا پنجره جلوی صفحه قرار بگیرد؛ مستطیل بعد از آن دوباره گرفته می‌شود.
        # اگر تایمر قبلی هنوز در انتظار است (PrtSc/F3 پشت سر هم)، اول متوقفش می‌کنیم
        # تا دو عکس هم‌زمان گرفته نشود.
        if self._snip_timer is not None:
            try:
                if self._snip_timer.IsRunning():
                    self._snip_timer.Stop()
            except Exception:
                pass
            self._snip_timer = None
        # ۵۰۰ms صبر می‌کنیم تا بازی واقعاً جلو بیاید (بازی‌های سنگین کندترند)
        self._snip_timer = wx.CallLater(500, lambda: self._do_capture_window(hwnd))

    def _do_capture_window(self, hwnd):
        self._snip_timer = None
        try:
            # اول با PrintWindow (PW_RENDERFULLCONTENT) — برای بازی‌ها و پنجره‌های
            # DirectX کار می‌کند که ImageGrab عکس‌شان را سیاه برمی‌گرداند
            img = print_window_bitmap(hwnd)
            if img is None:
                rect = window_rect(hwnd)
                if rect:
                    img = ImageGrab.grab(rect)
            if img is None:
                raise RuntimeError("capture failed")
            copy_pil_to_clipboard(img)
            self.show_toast(T("اسکرین‌شات از پنجره گرفته شد"),
                            T("تصویر کامل پنجره به کلیپ‌بورد رفت و در حال ترجمه است…"))
        except Exception:
            try:
                self.snip.start()
            except Exception:
                pass

    def manage_processes(self):
        dlg = ProcessManagerDialog(self, self.cfg)
        try:
            result = dlg.ShowModal()
        finally:
            dlg.Destroy()
        # انتخاب/تزریقِ تازه → رابطِ داخل بازی دوباره فعال می‌شود
        if self.cfg["focus_pid"]:
            self._game_minimized = False
        self._sync_game_mode()
        if result == wx.ID_YES:
            # بازی را بعد از بستن دیالوگ به جلو می‌آوریم
            try:
                hwnd = find_window_by_pid(self.cfg["focus_pid"])
                if hwnd:
                    bring_window_front(hwnd)
            except Exception:
                pass
            self.show_toast(T("تزریق به پروسس انجام شد"),
                            T("بازی به جلو آمد؛ منوی شناور 42OCR داخل بازی فعال است — PrtSc = عکس از بازی"))
        elif self.cfg["focus_pid"]:
            self.show_toast(T("پنجره‌ی هدف انتخاب شد"),
                            T("حالا PrtSc یا F3 عکس کامل همان پنجره را می‌گیرد و ترجمه می‌کند"))

    # ---------------- تنظیمات ----------------
    def open_settings(self):
        self._unregister_hotkey()
        self._unregister_snip_hotkey()
        self._unregister_prtsc_hotkey()   # تا با ضبط‌کننده‌ی کلید در تنظیمات تداخل نکند
        dlg = SettingsDialog(self, self.cfg)
        dlg.CenterOnScreen()
        try:
            dlg.ShowModal()
        finally:
            dlg.Destroy()
        self._register_hotkey(self.cfg["hotkey"])
        self._register_snip_hotkey()
        self.overlay.set_hotkey_text(self.cfg["hotkey"])
        self.overlay.apply_language()
        self.tray.SetIcon(make_app_icon(), self._tray_tooltip())
        self._sync_game_mode()

    # ---------------- جعبه‌ی 42OCR (فقط با راست‌کلیک روی تسک‌بار) ----------------
    def show_welcome_box(self):
        """جعبه‌ی 42OCR (بنر + پیوندها) را باز می‌کند. با باز شدن برنامه نمایش داده
        می‌شود و با کلیک راست روی آیکون تسک‌بار هم دوباره می‌آید
        (موقعیتِ درگ‌شده حفظ می‌شود)."""
        try:
            if self.welcome is None:
                self.welcome = WelcomePopup(self)
            self.welcome.show_welcome()
        except Exception:
            pass

    def show_toast(self, title, subtitle=""):
        try:
            self.toast.show_toast(title, subtitle)
        except Exception:
            pass

    # ---------------- منوی Tray ----------------
    def show_tray_menu(self):
        if self._menu is None:
            self._menu = GlassMenu(self)
        if self._menu._open:
            self._menu.close_menu()
        else:
            self._menu.show_menu()
            # با راست‌کلیک روی آیکون، جعبه‌ی 42OCR هم باز می‌شود (فقط موقع بازکردن منو)
            self.show_welcome_box()

    def _tray_tooltip(self):
        """نکته‌ی آیکون تسک‌بار به زبان جاری."""
        if self.monitor_active:
            return T("Level Translator — پایش روشن")
        return T("Level Translator — پایش متوقف است")

    def toggle_monitor(self):
        self.monitor_active = not self.monitor_active
        if self.monitor_active:
            self.last_hash = None
        self._status_line()
        self.tray.SetIcon(make_app_icon(), self._tray_tooltip())

    def _status_line(self):
        mode = T("روشن") if self.monitor_active else T("متوقف")
        lang_name = dict(LANGUAGES).get(self.cfg['target_lang'], '?')
        print(f"Level Translator — {T('پایش کلیپ‌بورد: روشن') if self.monitor_active else T('پایش کلیپ‌بورد: متوقف')} "
              f"| {T('کلید بستن')}: {self.cfg['hotkey'].upper()} | "
              f"{T('زبان مقصد')}: {T(lang_name)}")

    # ---------------- پاک‌سازی پوشه‌ی ذخیره ----------------
    def _wipe_save_dir(self):
        """پاک‌سازی دائمی پوشه‌ی ذخیره (مثل Shift+Delete — بدون سطل زباله/بازیابی)."""
        folder = self.cfg["save_dir"]
        if not folder:
            return
        try:
            if os.path.isdir(folder):
                for name in os.listdir(folder):
                    p = os.path.join(folder, name)
                    try:
                        if os.path.isdir(p):
                            shutil.rmtree(p, ignore_errors=True)
                        else:
                            os.remove(p)
                    except Exception:
                        pass
                os.makedirs(folder, exist_ok=True)
        except Exception:
            pass

    # ---------------- خروج ----------------
    def quit(self):
        self.monitor_active = False
        self._unregister_hotkey()
        self._unregister_prtsc_hotkey()
        try:
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass
        if self._menu is not None:
            try:
                self._menu.close_menu()
            except Exception:
                pass
        try:
            self.tray.RemoveIcon()
            self.tray.Destroy()
        except Exception:
            pass
        self.worker.shutdown()
        self.overlay.shutdown()
        w = getattr(self, "welcome", None)
        if w is not None:
            w.shutdown()
            self.welcome = None
        try:
            self.toast.hide_toast()
            self.toast.Destroy()
        except Exception:
            pass
        s = getattr(self, "snip", None)
        if s is not None:
            try:
                s._stop()
                s.Destroy()
            except Exception:
                pass
        b = getattr(self, "game_badge", None)
        if b is not None:
            try:
                b.shutdown()
            except Exception:
                pass
        gm = getattr(self, "game_menu", None)
        if gm is not None:
            try:
                gm.shutdown()
            except Exception:
                pass
        if self._snip_timer is not None:
            try:
                if self._snip_timer.IsRunning():
                    self._snip_timer.Stop()
            except Exception:
                pass
            self._snip_timer = None
        if (self.cfg["wipe_on_exit"] and not getattr(self, "_selftest", False)
                and not self._busy):
            self._wipe_save_dir()
        self.Destroy()


# ----------------------------------------------------------------------
# تست خودکار بدون نیاز به کلیپ‌بورد
# ----------------------------------------------------------------------
def run_selftest():
    print(">> تست خودکار 42OCR در حال اجرا…", flush=True)
    app = wx.App(False)
    ctrl = OCR42App(selftest=True)

    # ساخت تصویر نمونه
    img = Image.new("RGB", (900, 500), "white")
    d = ImageDraw.Draw(img)
    try:
        f = ImageFont.truetype("arial.ttf", 52)
    except Exception:
        f = None
    d.text((40, 90), "Hello World, this is a test", fill="black", font=f)
    d.text((40, 200), "The quick brown fox jumps over", fill="black", font=f)

    def start():
        print(">> ارسال تصویر نمونه به ترجمه…", flush=True)
        ctrl._begin_translation(img)
        wx.CallLater(75 * 1000, force_quit)

    def force_quit():
        print(">> TIMEOUT در تست خودکار", flush=True)
        ctrl.quit()
        wx.GetApp().ExitMainLoop()

    def _orig_result(data_url, res_img):
        print(">> نتیجه دریافت شد: %dx%d" % (res_img.width, res_img.height), flush=True)
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_selftest_result.png")
        res_img.convert("RGB").save(out, "PNG")
        print(">> ذخیره شد:", out, flush=True)
        print(">> SELFTEST-OK", flush=True)
        ctrl.quit()
        wx.GetApp().ExitMainLoop()

    ctrl.worker.on_result = _orig_result
    wx.CallLater(800, start)
    app.MainLoop()


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        run_selftest()
    else:
        app = wx.App(False)
        controller = OCR42App()
        app.MainLoop()
