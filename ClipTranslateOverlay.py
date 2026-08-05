# -*- coding: utf-8 -*-
"""
PantyOCR Overlay — نسخه‌ی پس‌زمینه + Overlay + تنظیمات
=============================================================

با این نسخه، برنامه کاملاً در پس‌زمینه کار می‌کند و دیگر پنجره‌ی Google Translate
روی صفحه دیده نمی‌شود:

  1) با هر اسکرین‌شات (PrintScreen / Win+Shift+S / Ctrl+C روی یک عکس) یا انتخاب
     «ترجمه با فایل…» از منوی System Tray:
       - عکس به‌صورت خودکار (با تزریق رویداد paste در سطح صفحه، بدون نیاز به
         فوکوس پنجره) داخل صفحه‌ی مخفی Google Translate (حالت تصویر) بارگذاری می‌شود
       - تصویر ترجمه‌شده از داخل همان صفحه استخراج و در پوشه‌ی انتخابی شما ذخیره می‌شود
       - بلافاصله به‌صورت یک Overlay شناور (بالای همه‌ی پنجره‌ها) به شما نشان داده می‌شود
  2) کلید میانبر قابل‌تنظیم (پیش‌فرض F2) → بستن Overlay
  3) منوی System Tray: تنظیمات / توقف موقت پایش / ترجمه با فایل… / خروج
  4) پنجره‌ی تنظیمات کامل: تغییر کلید میانبر، زبان مقصد، پوشه‌ی ذخیره، بستن خودکار، اعلان‌ها

وابستگی‌ها:
    pip install wxPython pillow keyboard
نیازمند Microsoft Edge WebView2 Runtime (روی اغلب ویندوزهای ۱۰/۱۱ از قبل نصب است)

استفاده:
    python PantyOCROverlay.py
    python PantyOCROverlay.py --selftest   (تست خودکار کل مسیر ترجمه بدون نیاز به کلیپ‌بورد)
"""

import base64
import hashlib
import io
import json
import os
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
# رنگ‌ها و ثابت‌های ظاهری
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

HIDDEN_POS = (-32000, -32000)          # موقعیت «خارج از صفحه» برای مرورگر مخفی
POLL_INTERVAL_MS = 900                 # فاصله‌ی چک‌کردن نتیجه در مرورگر مخفی
TRANSLATE_TIMEOUT_S = 60               # حداکثر انتظار برای ترجمه

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
# ابزارهای کمکی
# ----------------------------------------------------------------------
def build_translate_url(target_lang):
    return f"https://translate.google.com/?sl=auto&tl={target_lang}&op=images&hl=fa"


def pil_to_data_url(img):
    """تصویر PIL → data URL (PNG)."""
    buf = io.BytesIO()
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


def make_app_bitmap(size=32):
    """بیت‌مپ آیکون برنامه (مربع گرد با «A⇄ف» — همان طرح قبلی برنامه)."""
    bmp = wx.Bitmap(size, size)
    dc = wx.MemoryDC(bmp)
    dc.SetBackground(wx.Brush(ACCENT))
    dc.Clear()
    dc.SetBrush(wx.Brush(ACCENT))
    dc.SetPen(wx.TRANSPARENT_PEN)
    dc.DrawRoundedRectangle(0, 0, size, size, 8)
    dc.SetTextForeground(wx.Colour(255, 255, 255))
    font = wx.Font(13, wx.FONTFAMILY_SWISS, wx.NORMAL, wx.BOLD)
    dc.SetFont(font)
    label = "A\u21c4\u0641"
    tw, th = dc.GetTextExtent(label)
    dc.DrawText(label, (size - tw) // 2, (size - th) // 2 - 1)
    dc.SelectObject(wx.NullBitmap)
    return bmp


def make_app_icon():
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
# مدیریت پیکربندی (config.json در %APPDATA%\PantyOCR)
# ----------------------------------------------------------------------
class Config:
    DEFAULTS = {
        "hotkey": "f2",
        "target_lang": "fa",
        "save_dir": "",
        "auto_close_seconds": DEFAULT_AUTO_CLOSE_S,
        "notifications": True,
        "overlay_pos": None,   # موقعیت آخرِ Overlay روی صفحه (پس از درگ)
    }

    def __init__(self):
        base_dir = os.environ.get("APPDATA") or os.path.expanduser("~")
        self.dir = os.path.join(base_dir, "PantyOCR")
        self.path = os.path.join(self.dir, "config.json")
        self.data = dict(self.DEFAULTS)
        self.load()
        if not self.data.get("save_dir"):
            self.data["save_dir"] = os.path.join(os.path.expanduser("~"), "Pictures", "PantyOCR")
        self.ensure_dirs()

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
        font = wx.Font(10, wx.FONTFAMILY_SWISS, wx.NORMAL, wx.NORMAL)
        if self.kind == "accent":
            font = wx.Font(10, wx.FONTFAMILY_SWISS, wx.NORMAL, wx.BOLD)
        dc.SetFont(font)
        tw, th = dc.GetTextExtent(label)
        dc.DrawText(label, (w - tw) // 2, (h - th) // 2 - 1)
        evt.Skip()

    def DoGetBestSize(self):
        label = self.GetLabel()
        dc = wx.MemoryDC(wx.Bitmap(1, 1))
        dc.SetFont(wx.Font(10, wx.FONTFAMILY_SWISS, wx.NORMAL, wx.NORMAL))
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
        self.browser.Bind(wx.html2.EVT_WEBVIEW_ERROR, lambda e: self._fail("خطا در بارگذاری صفحه‌ی گوگل"))

        self._busy = False
        self._data_url = None
        self._source_hash = None
        self._start_ts = 0
        self._re_injected = False
        self._poll_timer = None
        self._timeout_timer = None
        self._inject_timer = None

    # -------------------------------------------------------------
    def start_upload(self, img, lang):
        """بارگذاری عکس جدید در مرورگر مخفی."""
        if self._busy:
            self.on_state("در حال پردازش ترجمه‌ی قبلی…")
            return False
        self._busy = True
        self._data_url = pil_to_data_url(img)
        self._source_hash = image_hash(img)
        self._re_injected = False
        self._start_ts = time.time()

        self._clear_timers()
        self.on_state("در حال بارگذاری Google Translate…")
        self.browser.LoadURL(build_translate_url(lang))
        return True

    # -------------------------------------------------------------
    def _on_loaded(self, event):
        if not self._busy:
            return
        self.on_state("در حال ارسال تصویر…")
        self._inject_timer = wx.CallLater(900, self._inject)

    def _inject(self):
        if not self._busy or self._data_url is None:
            return
        try:
            self.browser.RunScriptAsync(self.INJECT_JS + "('" + self._data_url + "')")
        except Exception as e:
            self._fail(f"خطا در تزریق تصویر: {e}")
            return
        self.on_state("در حال ترجمه توسط گوگل…")
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
            # تزریق ناموفق — یک بار دیگر تلاش می‌کنیم
            if not self._re_injected and time.time() - self._start_ts < 20:
                self._re_injected = True
                self._inject_timer = wx.CallLater(1500, self._inject)
            return

        if result.startswith("NOT_READY"):
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
            self._finish_success(result, out)
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

    def _on_timeout(self):
        if self._busy:
            self._fail("ترجمه انجام نشد (زمان‌بندی گوگل طول کشید). دوباره تلاش کنید.")

    def _clear_timers(self):
        for t in (self._poll_timer, self._timeout_timer, self._inject_timer):
            if t is not None:
                try:
                    if t.IsRunning():
                        t.Stop()
                except Exception:
                    pass
        self._poll_timer = None
        self._timeout_timer = None
        self._inject_timer = None

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
    """پنل تیره با حاشیه‌ی قرمز نئونی دوتایی (سبک لوگوی 42LEVEL)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.SetBackgroundColour(BG)
        self.Bind(wx.EVT_PAINT, self._on_paint)

    def _on_paint(self, evt):
        dc = wx.PaintDC(self)
        w, h = self.GetSize()
        dc.SetBrush(wx.Brush(BG))
        dc.SetPen(wx.Pen(BG))
        dc.DrawRoundedRectangle(0, 0, w, h, 16)
        # هاله‌ی نئونی (لایه‌ی بیرونی کمرنگ) + خط قرمز پررنگ
        dc.SetBrush(wx.TRANSPARENT_BRUSH)
        dc.SetPen(wx.Pen(wx.Colour(120, 30, 40), 6))
        dc.DrawRoundedRectangle(3, 3, max(1, w - 6), max(1, h - 6), 13)
        dc.SetPen(wx.Pen(ACCENT, 2))
        dc.DrawRoundedRectangle(3, 3, max(1, w - 6), max(1, h - 6), 13)


class LinkRow(wx.Panel):
    """یک ردیف پیوند: نشانک + عنوان + آدرس؛ با کلیک در مرورگر باز می‌شود."""

    H = 50

    def __init__(self, parent, badge, label, url):
        super().__init__(parent, style=wx.BORDER_NONE)
        self.url = url
        self.hovered = False
        self.SetBackgroundColour(CARD)
        self.SetMinSize((-1, self.H))

        s = wx.BoxSizer(wx.HORIZONTAL)
        self.badge_lbl = wx.StaticText(self, label=badge)
        self.badge_lbl.SetForegroundColour(ACCENT)
        self.badge_lbl.SetFont(wx.Font(12, wx.FONTFAMILY_SWISS, wx.NORMAL, wx.BOLD))
        self.badge_lbl.SetMinSize((34, -1))

        col = wx.BoxSizer(wx.VERTICAL)
        self.label_lbl = wx.StaticText(self, label=label)
        self.label_lbl.SetForegroundColour(TEXT)
        self.label_lbl.SetFont(wx.Font(10, wx.FONTFAMILY_SWISS, wx.NORMAL, wx.BOLD))
        self.url_lbl = wx.StaticText(self, label=url)
        self.url_lbl.SetForegroundColour(MUTED)
        self.url_lbl.SetFont(wx.Font(9, wx.FONTFAMILY_SWISS, wx.NORMAL, wx.NORMAL))
        col.Add(self.label_lbl, 0)
        col.Add(self.url_lbl, 0, wx.TOP, 2)

        self.arrow_lbl = wx.StaticText(self, label="\u2197")
        self.arrow_lbl.SetForegroundColour(wx.Colour(120, 104, 110))
        self.arrow_lbl.SetFont(wx.Font(13, wx.FONTFAMILY_SWISS, wx.NORMAL, wx.BOLD))

        s.Add(self.badge_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 12)
        s.Add(col, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 6)
        s.Add(self.arrow_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
        self.SetSizer(s)

        for w in (self, self.badge_lbl, self.label_lbl, self.url_lbl, self.arrow_lbl):
            w.Bind(wx.EVT_ENTER_WINDOW, lambda e: self._set_hover(True))
            w.Bind(wx.EVT_LEAVE_WINDOW, lambda e: self._set_hover(False))
            w.Bind(wx.EVT_LEFT_DOWN, self._open_url)
            w.Bind(wx.EVT_MOTION, lambda e: self.SetCursor(wx.Cursor(wx.CURSOR_HAND)))

    def _set_hover(self, v):
        if self.hovered == v:
            return
        self.hovered = v
        bg = wx.Colour(62, 27, 34) if v else CARD
        self.label_lbl.SetForegroundColour(ACCENT if v else TEXT)
        self.url_lbl.SetForegroundColour(ACCENT if v else MUTED)
        self.arrow_lbl.SetForegroundColour(ACCENT if v else wx.Colour(120, 104, 110))
        for w in (self, self.badge_lbl, self.label_lbl, self.url_lbl, self.arrow_lbl):
            w.SetBackgroundColour(bg)
        self.Refresh()

    def _open_url(self, evt):
        try:
            webbrowser.open(self.url)
        except Exception:
            pass


class WelcomePopup(wx.Frame):
    """پاپ‌آپی که هنگام اجرای برنامه بالای صفحه ظاهر می‌شود و پیوندهای 42LEVEL را نشان می‌دهد."""

    W, H = 386, 440
    AUTO_CLOSE_MS = 60 * 1000

    LINKS = [
        ("\u2665", "درگاه حمایت مالی",  "https://reymit.ir/42level"),
        ("YT",      "کانال یوتیوب",     "https://www.youtube.com/@42LEVEL"),
        ("GH",      "گیت‌هاب",          "https://github.com/mhbanaei"),
        ("GH",      "گیت‌هاب",          "https://github.com/AghaErfan"),
        ("TW",      "کانال توییچ",      "https://www.twitch.tv/42level"),
    ]

    def __init__(self, app):
        style = wx.FRAME_NO_TASKBAR | wx.STAY_ON_TOP | wx.FRAME_SHAPED | wx.BORDER_NONE
        super().__init__(None, title="42LEVEL", size=(self.W, self.H), style=style)
        self.app = app
        self._auto_timer = None
        self.SetBackgroundColour(BG)
        self._build_ui()
        try:
            self.SetShape(rounded_region(self.W, self.H, 16))
        except Exception:
            pass

    def _build_ui(self):
        outer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(outer)

        panel = NeonPanel(self)
        outer.Add(panel, 1, wx.EXPAND)
        ps = wx.BoxSizer(wx.VERTICAL)
        panel.SetSizer(ps)

        # نوار بالا: لوگو + عنوان + دکمه‌ی بستن
        top = wx.BoxSizer(wx.HORIZONTAL)
        logo_bmp = load_logo_bitmap(60) or make_app_bitmap(60)
        top.Add(wx.StaticBitmap(panel, bitmap=logo_bmp), 0, wx.ALIGN_CENTER_VERTICAL)

        titles = wx.BoxSizer(wx.VERTICAL)
        t1 = wx.StaticText(panel, label="42LEVEL")
        t1.SetForegroundColour(ACCENT)
        t1.SetFont(wx.Font(17, wx.FONTFAMILY_SWISS, wx.NORMAL, wx.BOLD))
        t2 = wx.StaticText(panel, label="42 Level Translator — ترجمه‌ی تصویر در پس‌زمینه")
        t2.SetForegroundColour(MUTED)
        t2.SetFont(wx.Font(9, wx.FONTFAMILY_SWISS, wx.NORMAL, wx.NORMAL))
        titles.Add(t1)
        titles.Add(t2, 0, wx.TOP, 3)
        top.Add(titles, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 12)
        top.Add(FlatButton(panel, "\u2715", self._on_close, kind="danger", size=(30, 30)),
                0, wx.ALIGN_CENTER_VERTICAL)
        ps.Add(top, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 16)

        hint = wx.StaticText(panel, label="از همراهی شما سپاسگزاریم \u2665 — با فالو کردن از ما حمایت کنید:")
        hint.SetForegroundColour(TEXT)
        hint.SetFont(wx.Font(10, wx.FONTFAMILY_SWISS, wx.NORMAL, wx.NORMAL))
        ps.Add(hint, 0, wx.LEFT | wx.RIGHT | wx.TOP, 16)

        for badge, label, url in self.LINKS:
            ps.Add(LinkRow(panel, badge, label, url), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 8)

        ps.AddStretchSpacer(1)
        footer = wx.StaticText(panel, label="کلیک روی هر مورد، پیوند را در مرورگر باز می‌کند")
        footer.SetForegroundColour(MUTED)
        footer.SetFont(wx.Font(8, wx.FONTFAMILY_SWISS, wx.NORMAL, wx.NORMAL))
        ps.Add(footer, 0, wx.ALIGN_CENTER | wx.BOTTOM, 12)
        # چیدمانِ اولیه را همین‌جا انجام می‌دهیم تا اگر رویداد تغییر اندازه نرسید،
        # محتوا با اندازه‌های درست ساخته شود (بدون آن، پاپ‌آپ خالی/سیاه دیده می‌شد)
        self.Layout()
        # و در تغییر اندازه‌ها هم دوباره مرتب می‌کنیم
        self.Bind(wx.EVT_SIZE, self._on_size)

    def _on_size(self, evt):
        self.Layout()
        evt.Skip()

    def show_welcome(self):
        self._position_top()
        self.Show()
        self.Raise()
        self._stop_timer()
        self._auto_timer = wx.CallLater(self.AUTO_CLOSE_MS, self._on_auto_close)

    def _position_top(self):
        try:
            sw, sh = wx.GetDisplaySize()
            w, h = self.GetSize()
            self.SetPosition((max(20, (sw - w) // 2), 24))
        except Exception:
            pass

    def _on_close(self, evt):
        self.Hide()
        self._stop_timer()

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
        super().__init__(None, title="PantyOCR", size=(560, 420), style=style)
        self.app = app
        self._current_img = None
        self._auto_timer = None
        self._dragging = False
        self._drag_off_screen = (0, 0)
        self._drag_frame_pos = (0, 0)
        self._positioned = False

        self.SetBackgroundColour(BG)
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
        self.title_lbl.SetFont(wx.Font(11, wx.FONTFAMILY_SWISS, wx.NORMAL, wx.BOLD))

        self.state_lbl = wx.StaticText(self.header, label="")
        self.state_lbl.SetForegroundColour(WARN)
        self.state_lbl.SetFont(wx.Font(10, wx.FONTFAMILY_SWISS, wx.NORMAL, wx.NORMAL))

        self.copy_btn = FlatButton(self.header, "کپی", self._on_copy, kind="ghost", size=(58, 30))
        self.close_btn = FlatButton(self.header, "\u2715", self._on_close, kind="danger", size=(34, 30))

        hs.Add(self.icon_bmp, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 12)
        hs.Add(self.title_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 10)
        hs.Add(self.state_lbl, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 14)
        hs.Add(self.copy_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        hs.Add(self.close_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        self.header.SetSizer(hs)
        self.header.SetMinSize((-1, self.HEADER_H))

        # ناحیه‌ی تصویر
        self.image_panel = wx.Panel(self)
        self.image_panel.SetBackgroundColour(CARD)
        ips = wx.BoxSizer(wx.VERTICAL)
        self.image_ctrl = wx.StaticBitmap(self.image_panel)
        self.placeholder_lbl = wx.StaticText(self.image_panel, label="")
        self.placeholder_lbl.SetForegroundColour(MUTED)
        self.placeholder_lbl.SetFont(wx.Font(12, wx.FONTFAMILY_SWISS, wx.NORMAL, wx.NORMAL))
        ips.AddStretchSpacer(1)
        ips.Add(self.image_ctrl, 0, wx.ALIGN_CENTER)
        ips.Add(self.placeholder_lbl, 0, wx.ALIGN_CENTER | wx.TOP, 8)
        ips.AddStretchSpacer(1)
        self.image_panel.SetSizer(ips)

        # نوار پایین
        self.footer = wx.Panel(self)
        self.footer.SetBackgroundColour(PANEL)
        fs = wx.BoxSizer(wx.HORIZONTAL)
        self.hint_lbl = wx.StaticText(self.footer, label="")
        self.hint_lbl.SetForegroundColour(MUTED)
        self.hint_lbl.SetFont(wx.Font(9, wx.FONTFAMILY_SWISS, wx.NORMAL, wx.NORMAL))
        self.path_lbl = wx.StaticText(self.footer, label="")
        self.path_lbl.SetForegroundColour(MUTED)
        self.path_lbl.SetFont(wx.Font(9, wx.FONTFAMILY_SWISS, wx.NORMAL, wx.NORMAL))
        fs.Add(self.hint_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 14)
        fs.Add(self.path_lbl, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 14)
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
        self.hint_lbl.SetLabel(f"برای بستن: {hotkey.upper()}  |  قابلیت جابه‌جایی با درگ")

    def show_translating(self, state_text):
        self._stop_auto()
        self.state_lbl.SetForegroundColour(WARN)
        self.state_lbl.SetLabel(state_text)
        self.placeholder_lbl.SetLabel("در حال ترجمه…")
        self.placeholder_lbl.SetForegroundColour(WARN)
        self.image_ctrl.SetBitmap(wx.Bitmap(1, 1))
        self.path_lbl.SetLabel("")
        self._size_for_image(None)
        self.Show()
        self.Raise()

    def show_result(self, img, path, auto_close_s, hotkey):
        self._stop_auto()
        self._current_img = img
        self.state_lbl.SetForegroundColour(SUCCESS)
        self.state_lbl.SetLabel("ترجمه آماده است")
        self.placeholder_lbl.SetLabel("")
        self.set_hotkey_text(hotkey)
        self.path_lbl.SetLabel(f"ذخیره شد: {path}")
        self.path_lbl.SetToolTip(path)

        # عکس‌های کوچک را بزرگ‌نمایی می‌کنیم تا هم راحت‌تر دیده شوند و هم
        # پنجره همیشه آن‌قدر بزرگ باشد که دکمه‌های «کپی» و «✕» دیده شوند
        disp_w, disp_h = self._display_size_for(img)
        if (disp_w, disp_h) != (img.width, img.height):
            img = img.resize((disp_w, disp_h), Image.LANCZOS)
        bmp = pil_to_wx_bitmap(img)
        self.image_ctrl.SetBitmap(bmp)
        # پنجره را بر اساس تصویر اصلی (نه بزرگ‌نمایی‌شده) اندازه بگیر
        self._size_for_image(self._current_img)
        self.Show()
        self.Raise()

        if auto_close_s and auto_close_s > 0:
            self._auto_timer = wx.CallLater(auto_close_s * 1000, self._on_auto_close)

    def show_error(self, message):
        self._stop_auto()
        self.state_lbl.SetForegroundColour(DANGER)
        self.state_lbl.SetLabel("خطا")
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
            self.state_lbl.SetLabel("کپی شد ✓")

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
        super().__init__(parent, title="تنظیمات Level Translator", size=(470, 560),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.cfg = cfg
        self.recording = False
        self._down = set()
        self._hook = None

        self.SetBackgroundColour(BG)
        self._build_ui()

    def _build_ui(self):
        root = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(root)

        # هدر
        header = wx.Panel(self)
        header.SetBackgroundColour(PANEL)
        hs = wx.BoxSizer(wx.HORIZONTAL)
        hs.Add(wx.StaticBitmap(header, bitmap=make_app_bitmap()), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 16)
        t = wx.StaticText(header, label="تنظیمات Level Translator")
        t.SetForegroundColour(TEXT)
        t.SetFont(wx.Font(14, wx.FONTFAMILY_SWISS, wx.NORMAL, wx.BOLD))
        hs.Add(t, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 12)
        header.SetSizer(hs)
        header.SetMinSize((-1, 64))
        root.Add(header, 0, wx.EXPAND)

        body = wx.Panel(self)
        body.SetBackgroundColour(BG)
        bs = wx.BoxSizer(wx.VERTICAL)

        # --- کلید میانبر ---
        bs.Add(self._section_title(body, "کلید میانبر بستن عکس"), 0, wx.LEFT | wx.TOP, 20)
        hotkey_row = wx.BoxSizer(wx.HORIZONTAL)
        self.hotkey_btn = FlatButton(body, self._hotkey_display(), self._start_recording,
                                     kind="ghost", size=(170, 38))
        self.hotkey_hint = wx.StaticText(body, label="برای تغییر کلیک کنید و کلید (یا ترکیب) جدید را بزنید")
        self.hotkey_hint.SetForegroundColour(MUTED)
        hotkey_row.Add(self.hotkey_btn, 0, wx.ALIGN_CENTER_VERTICAL)
        hotkey_row.Add(self.hotkey_hint, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 14)
        bs.Add(hotkey_row, 0, wx.LEFT | wx.TOP, 12)

        # --- زبان مقصد ---
        bs.Add(self._section_title(body, "زبان مقصد ترجمه"), 0, wx.LEFT | wx.TOP, 20)
        lang_row = wx.BoxSizer(wx.HORIZONTAL)
        self.lang_combo = wx.ComboBox(body, choices=[name for _, name in LANGUAGES],
                                      style=wx.CB_READONLY)
        self.lang_combo.SetBackgroundColour(PANEL)
        self.lang_combo.SetForegroundColour(TEXT)
        self.lang_combo.SetValue(self._lang_name())
        lang_row.Add(self.lang_combo, 0, wx.ALIGN_CENTER_VERTICAL)
        lang_row.Add(wx.StaticText(body, label="تشخیص خودکار زبان مبدأ"),
                     0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 16)
        bs.Add(lang_row, 0, wx.LEFT | wx.TOP, 12)

        # --- پوشه ذخیره ---
        bs.Add(self._section_title(body, "پوشه‌ی ذخیره‌ی ترجمه‌ها"), 0, wx.LEFT | wx.TOP, 20)
        dir_row = wx.BoxSizer(wx.HORIZONTAL)
        self.dir_ctrl = wx.TextCtrl(body, value=self.cfg["save_dir"])
        self.dir_ctrl.SetBackgroundColour(CARD)
        self.dir_ctrl.SetForegroundColour(TEXT)
        self.dir_ctrl.SetEditable(False)
        dir_row.Add(self.dir_ctrl, 1, wx.ALIGN_CENTER_VERTICAL)
        dir_row.Add(FlatButton(body, "انتخاب پوشه…", self._pick_dir, kind="ghost", size=(120, 34)),
                    0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        dir_row.Add(FlatButton(body, "باز کردن", self._open_dir, kind="ghost", size=(90, 34)),
                    0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        bs.Add(dir_row, 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)

        # --- بستن خودکار ---
        bs.Add(self._section_title(body, "بستن خودکار Overlay"), 0, wx.LEFT | wx.TOP, 20)
        auto_row = wx.BoxSizer(wx.HORIZONTAL)
        self.auto_chk = wx.CheckBox(body, label="بستن خودکار پس از")
        self.auto_chk.SetForegroundColour(TEXT)
        self.auto_chk.SetBackgroundColour(BG)
        self.auto_spin = wx.SpinCtrl(body, min=5, max=600, initial=60)
        self.auto_spin.SetBackgroundColour(PANEL)
        self.auto_spin.SetForegroundColour(TEXT)
        auto_row.Add(self.auto_chk, 0, wx.ALIGN_CENTER_VERTICAL)
        auto_row.Add(self.auto_spin, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 10)
        auto_row.Add(wx.StaticText(body, label="ثانیه (۰ = خاموش)"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 10)
        bs.Add(auto_row, 0, wx.LEFT | wx.TOP, 12)
        acs = self.cfg["auto_close_seconds"]
        if acs and acs > 0:
            self.auto_chk.SetValue(True)
            self.auto_spin.SetValue(acs)
        else:
            self.auto_chk.SetValue(False)
            self.auto_spin.Disable()

        # --- اعلان‌ها ---
        bs.Add(self._section_title(body, "اعلان‌ها"), 0, wx.LEFT | wx.TOP, 20)
        self.notif_chk = wx.CheckBox(body, label="نمایش اعلان هنگام آماده‌شدن ترجمه")
        self.notif_chk.SetValue(bool(self.cfg["notifications"]))
        self.notif_chk.SetForegroundColour(TEXT)
        self.notif_chk.SetBackgroundColour(BG)
        bs.Add(self.notif_chk, 0, wx.LEFT | wx.TOP, 12)

        bs.AddStretchSpacer(1)

        # دکمه‌ها
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        save_btn = FlatButton(body, "ذخیره تنظیمات", self._on_save, kind="accent", size=(150, 38))
        cancel_btn = FlatButton(body, "انصراف", self._on_cancel, kind="ghost", size=(110, 38))
        btn_row.AddStretchSpacer(1)
        btn_row.Add(save_btn, 0, wx.RIGHT, 10)
        btn_row.Add(cancel_btn, 0, wx.RIGHT, 20)
        bs.Add(btn_row, 0, wx.EXPAND | wx.BOTTOM | wx.TOP, 20)

        body.SetSizer(bs)
        root.Add(body, 1, wx.EXPAND)

        self.auto_chk.Bind(wx.EVT_CHECKBOX, self._on_auto_toggle)
        self.Bind(wx.EVT_CLOSE, self._on_cancel)

    def _section_title(self, parent, text):
        lbl = wx.StaticText(parent, label=text)
        lbl.SetForegroundColour(ACCENT)
        lbl.SetFont(wx.Font(10, wx.FONTFAMILY_SWISS, wx.NORMAL, wx.BOLD))
        return lbl

    def _lang_name(self):
        for code, name in LANGUAGES:
            if code == self.cfg["target_lang"]:
                return name
        return "فارسی"

    def _hotkey_display(self):
        return self.cfg["hotkey"].replace("+", " + ").upper()

    # ---------------- ضبط کلید میانبر ----------------
    def _start_recording(self, evt):
        if self.recording:
            return
        self.recording = True
        self._down.clear()
        self.hotkey_btn.SetLabel("… کلید را بزنید")
        self.hotkey_btn.Refresh()
        self.hotkey_hint.SetLabel("در حال ضبط… (Esc = انصراف)")
        self.hotkey_hint.SetForegroundColour(WARN)
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
        self.hotkey_hint.SetLabel("برای تغییر کلیک کنید و کلید (یا ترکیب) جدید را بزنید")
        self.hotkey_hint.SetForegroundColour(MUTED)
        if combo:
            self.hotkey_btn.SetLabel(combo.replace("+", " + ").upper())
            self.hotkey_btn.Refresh()

    # ---------------- اکشن‌های دیگر ----------------
    def _on_auto_toggle(self, evt):
        self.auto_spin.Enable(self.auto_chk.GetValue())

    def _pick_dir(self, evt):
        dlg = wx.DirDialog(self, "پوشه‌ی ذخیره‌ی ترجمه‌ها", self.cfg["save_dir"])
        if dlg.ShowModal() == wx.ID_OK:
            self.dir_ctrl.SetValue(dlg.GetPath())
        dlg.Destroy()

    def _open_dir(self, evt):
        d = self.dir_ctrl.GetValue()
        if os.path.isdir(d):
            os.startfile(d)

    def _on_save(self, evt):
        if self.recording:
            self._apply_recorded(None)
        # زبان
        sel = self.lang_combo.GetSelection()
        if 0 <= sel < len(LANGUAGES):
            self.cfg["target_lang"] = LANGUAGES[sel][0]
        # پوشه
        d = self.dir_ctrl.GetValue().strip()
        if d and os.path.isdir(d):
            self.cfg["save_dir"] = d
        # بستن خودکار
        if self.auto_chk.GetValue():
            self.cfg["auto_close_seconds"] = int(self.auto_spin.GetValue())
        else:
            self.cfg["auto_close_seconds"] = 0
        self.cfg["notifications"] = bool(self.notif_chk.GetValue())
        self.cfg.save()
        self.EndModal(wx.ID_OK)

    def _on_cancel(self, evt=None):
        if self.recording:
            self._apply_recorded(None)
        self.EndModal(wx.ID_CANCEL)


# ----------------------------------------------------------------------
# آیکون System Tray
# ----------------------------------------------------------------------
class TrayIcon(wx.adv.TaskBarIcon):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.SetIcon(make_app_icon(), "42 Level Translator — ترجمه‌ی تصویر در پس‌زمینه")
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DCLICK, lambda e: self.app.open_settings())

    def CreatePopupMenu(self):
        menu = wx.Menu()

        item_settings = menu.Append(wx.ID_ANY, "تنظیمات…")
        self.Bind(wx.EVT_MENU, lambda e: self.app.open_settings(), item_settings)

        item_file = menu.Append(wx.ID_ANY, "ترجمه با فایل…")
        self.Bind(wx.EVT_MENU, lambda e: self.app.translate_file(), item_file)

        menu.AppendSeparator()

        self.pause_item = menu.Append(wx.ID_ANY,
                                      "توقف موقت پایش کلیپ‌بورد" if self.app.monitor_active
                                      else "ادامه‌ی پایش کلیپ‌بورد")
        self.Bind(wx.EVT_MENU, lambda e: self.app.toggle_monitor(), self.pause_item)

        menu.AppendSeparator()
        item_exit = menu.Append(wx.ID_EXIT, "خروج")
        self.Bind(wx.EVT_MENU, lambda e: self.app.quit(), item_exit)
        return menu


# ----------------------------------------------------------------------
# برنامه‌ی اصلی: پایش کلیپ‌بورد + مدیریت همه‌چیز
# ----------------------------------------------------------------------
class PantyOCRApp(wx.Frame):
    def __init__(self, selftest=False):
        super().__init__(None)  # فریم نامرئی، فقط برای زنده نگه‌داشتن اپ

        self.cfg = Config()
        self.monitor_active = True
        self.processing = False
        self.last_hash = None
        self._hotkey_handle = None
        self._busy = False

        self.worker = TranslateWorker(self._on_translate_result,
                                      self._on_translate_error,
                                      self._on_translate_state)
        self.overlay = ImageOverlay(self)
        self.tray = TrayIcon(self)

        self.overlay.set_hotkey_text(self.cfg["hotkey"])
        self._register_hotkey(self.cfg["hotkey"])

        self._welcome_timer = None
        if not selftest:
            self.welcome = WelcomePopup(self)
            self._start_clipboard_monitor()
            self._welcome_timer = wx.CallLater(600, self.welcome.show_welcome)
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
                    print(f"خطای پایش کلیپ‌بورد: {e}")
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
        if self._busy:
            return
        self._busy = True
        self.overlay.show_translating("در حال ترجمه…")
        if not self.worker.start_upload(img, self.cfg["target_lang"]):
            self._busy = False
            self.overlay.show_error("یک ترجمه در حال انجام است؛ کمی صبر کنید.")

    def _on_translate_state(self, state_text):
        if self._busy:
            self.overlay.state_lbl.SetLabel(state_text)

    def _on_translate_result(self, data_url, img):
        self._busy = False
        try:
            path = self._save_image(img)
        except Exception as e:
            self.overlay.show_error(f"خطا در ذخیره‌ی تصویر: {e}")
            return
        self.overlay.show_result(img, path, self.cfg["auto_close_seconds"], self.cfg["hotkey"])
        if self.cfg["notifications"]:
            self._notify("ترجمه آماده شد", f"تصویر ترجمه‌شده در پوشه‌ی ذخیره ثبت شد.")

    def _on_translate_error(self, message):
        self._busy = False
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

    # ---------------- تنظیمات ----------------
    def open_settings(self):
        self._unregister_hotkey()
        dlg = SettingsDialog(self, self.cfg)
        dlg.CenterOnScreen()
        try:
            dlg.ShowModal()
        finally:
            dlg.Destroy()
        self._register_hotkey(self.cfg["hotkey"])
        self.overlay.set_hotkey_text(self.cfg["hotkey"])

    # ---------------- منوی Tray ----------------
    def toggle_monitor(self):
        self.monitor_active = not self.monitor_active
        if self.monitor_active:
            self.last_hash = None
        self._status_line()
        self.tray.SetIcon(make_app_icon(),
                          "Level Translator — پایش روشن" if self.monitor_active
                          else "Level Translator — پایش متوقف است")

    def translate_file(self):
        dlg = wx.FileDialog(self, "انتخاب تصویر برای ترجمه",
                            wildcard="Images (*.png;*.jpg;*.jpeg;*.bmp;*.gif)|*.png;*.jpg;*.jpeg;*.bmp;*.gif",
                            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            try:
                img = Image.open(path)
                self.last_hash = None
                self._begin_translation(img)
            except Exception as e:
                self.overlay.show_error(f"نمی‌توان فایل را باز کرد: {e}")
        dlg.Destroy()

    def _status_line(self):
        mode = "روشن" if self.monitor_active else "متوقف"
        print(f"Level Translator — پایش کلیپ‌بورد: {mode} | کلید بستن: {self.cfg['hotkey'].upper()} | "
              f"زبان مقصد: {dict(LANGUAGES).get(self.cfg['target_lang'], '?')}")

    # ---------------- خروج ----------------
    def quit(self):
        self.monitor_active = False
        self._unregister_hotkey()
        try:
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass
        try:
            self.tray.RemoveIcon()
            self.tray.Destroy()
        except Exception:
            pass
        if self._welcome_timer is not None:
            try:
                if self._welcome_timer.IsRunning():
                    self._welcome_timer.Stop()
            except Exception:
                pass
            self._welcome_timer = None
        self.worker.shutdown()
        self.overlay.shutdown()
        w = getattr(self, "welcome", None)
        if w is not None:
            w.shutdown()
        self.Destroy()


# ----------------------------------------------------------------------
# تست خودکار بدون نیاز به کلیپ‌بورد
# ----------------------------------------------------------------------
def run_selftest():
    print(">> تست خودکار PantyOCR در حال اجرا…", flush=True)
    app = wx.App(False)
    ctrl = PantyOCRApp(selftest=True)

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
        controller = PantyOCRApp()
        app.MainLoop()
