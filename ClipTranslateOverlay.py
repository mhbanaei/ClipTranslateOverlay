import wx
import wx.html2
import time
import threading
import keyboard
import os
from PIL import ImageGrab, Image

# Dependencies:
# pip install wxPython pillow keyboard

class ClipboardTranslator(wx.Frame):
    def __init__(self):
        super().__init__(None, title="Clipboard Image Translator", size=(800, 600), style=wx.DEFAULT_FRAME_STYLE)
        self.browser = wx.html2.WebView.New(self)
        self.translate_url = "https://translate.google.com/?sl=auto&tl=fa&op=images"
        self.browser.Bind(wx.html2.EVT_WEBVIEW_LOADED, self.on_webview_load)
        
        self.overlay = None
        self.overlay_timer = None

        self.monitor_active = True
        self.last_hash = None
        self.processing = False
        self.pending_paste = False
        self.last_image = None

        self.download_folder = r"C:\Users\hosse\Downloads"

        self.start_monitor()
        keyboard.add_hotkey('shift+space', self.clear_overlay)
        self.Bind(wx.EVT_CLOSE, self.on_close)

    def start_monitor(self):
        def monitor():
            while self.monitor_active:
                try:
                    if self.processing:
                        time.sleep(0.5)
                        continue
                    img = ImageGrab.grabclipboard()
                    if isinstance(img, Image.Image):
                        cur_hash = self.hash_image(img)
                        if cur_hash and cur_hash != self.last_hash:
                            self.last_hash = cur_hash
                            self.last_image = img.copy()
                            self.processing = True
                            wx.CallAfter(self.process_image, img)
                    elif isinstance(img, list):
                        for f in img:
                            if f.lower().endswith((".png", ".jpg", ".jpeg", ".bmp")):
                                try:
                                    img_file = Image.open(f)
                                    cur_hash = self.hash_image(img_file)
                                    if cur_hash and cur_hash != self.last_hash:
                                        self.last_hash = cur_hash
                                        self.last_image = img_file.copy()
                                        self.processing = True
                                        wx.CallAfter(self.process_image, img_file)
                                except Exception as e:
                                    print(f"Error opening image file from clipboard: {e}")
                except Exception as e:
                    print(f"Error in clipboard monitor: {e}")
                time.sleep(0.5)
        threading.Thread(target=monitor, daemon=True).start()
    
    def hash_image(self, img: Image.Image):
        if not img:
            return None
        data = img.resize((64, 64)).tobytes()
        return hash(data)
    
    def process_image(self, img):
        self.clear_overlay()
        self.pending_paste = True
        self.browser.LoadURL(self.translate_url)
    
    def on_webview_load(self, event):
        if self.pending_paste:
            def try_paste():
                if self.browser.IsBusy():
                    wx.CallLater(500, try_paste)
                else:
                    self.pending_paste = False
                    wx.CallAfter(self.paste_image)
            try_paste()
    
    def paste_image(self):
        # هیچ عملی انجام نمی‌شود؛ صرفاً می‌رویم سراغ مرحله بعد
        wx.CallLater(10000, self.fetch_translated)
    
    def fetch_translated(self):
        js = r'''
        (function(){
            var xpath = '//*[@id="yDmH0d"]/c-wiz/div/div[2]/c-wiz/div[5]/c-wiz/div[2]/c-wiz/div/div[1]/div[2]/div[2]/button/span[2]';
            var result = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
            var downloadButton = result.singleNodeValue;
            if (downloadButton) {
                downloadButton.click();
            }
            return "clicked";
        })()
        '''
        self.browser.RunScript(js)
        self.poll_for_download(start_time=time.time())
    
    def poll_for_download(self, start_time):
        def get_image_files():
            valid_exts = (".png", ".jpg", ".jpeg")
            files = []
            try:
                for file in os.listdir(self.download_folder):
                    if file.lower().endswith(valid_exts):
                        full_path = os.path.join(self.download_folder, file)
                        files.append(full_path)
            except Exception as e:
                print(f"Error listing download folder: {e}")
            return files

        files = get_image_files()
        recent_files = []
        for filepath in files:
            try:
                mod_time = os.path.getmtime(filepath)
                if mod_time >= start_time:
                    recent_files.append((filepath, mod_time))
            except Exception as e:
                print(f"Error getting modification time for {filepath}: {e}")

        if recent_files:
            recent_files.sort(key=lambda x: x[1], reverse=True)
            downloaded_file = recent_files[0][0]
            try:
                img = Image.open(downloaded_file)
                wx.CallAfter(self.show_overlay, img)
                self.processing = False
                self.browser.LoadURL("about:blank")
            except Exception as e:
                print(f"Error processing downloaded file: {e}")
                self.processing = False
        else:
            print("Downloaded file not detected, retrying...")
            wx.CallLater(2000, self.poll_for_download, start_time)
    
    def show_overlay(self, img: Image.Image):
        self.clear_overlay()
        self.overlay = wx.Frame(None, style=wx.FRAME_SHAPED | wx.STAY_ON_TOP)
        bmp = wx.Bitmap.FromBuffer(img.width, img.height, img.convert('RGB').tobytes())
        panel = wx.Panel(self.overlay)
        static = wx.StaticBitmap(panel, bitmap=bmp)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(static, 0, wx.ALL, 5)
        panel.SetSizer(sizer)
        screen_width, screen_height = wx.GetDisplaySize()
        self.overlay.SetPosition((0, screen_height - img.height))
        self.overlay.SetSize((img.width, img.height))
        self.overlay.Show()
        self.overlay_timer = threading.Timer(60, self.clear_overlay)
        self.overlay_timer.start()
    
    def clear_overlay(self):
        if self.overlay_timer:
            self.overlay_timer.cancel()
            self.overlay_timer = None
        if self.overlay:
            self.overlay.Destroy()
            self.overlay = None
    
    def on_close(self, evt):
        self.monitor_active = False
        keyboard.unhook_all_hotkeys()
        self.Destroy()

if __name__ == '__main__':
    app = wx.App()
    frame = ClipboardTranslator()
    frame.Show()
    app.MainLoop()