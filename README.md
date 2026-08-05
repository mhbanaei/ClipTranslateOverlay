# 📋 ClipTranslateOverlay

A Python-based desktop utility that monitors your clipboard for image content, translates it **in the background** using Google Translate's image translation, saves the translated image to a folder of your choice, and shows it as a floating always-on-top overlay.

## 🎨 42LEVEL Branding

- **Icon**: the app keeps its original icon (rounded square with «A⇄ف»); the 42LEVEL logo (`assets/42logo.png`) is used inside the welcome popup and as the header icon of the result overlay
- **Theme**: dark + red-neon style matching the logo (near-black background, neon-red accents, a red neon underline under the overlay header)
- **Welcome popup**: on every startup a small popup appears at the top of the screen with the 42LEVEL logo and clickable links (support page, YouTube, GitHub ×2, Twitch) — it closes itself after 60 seconds or with the ✕ button

| | |
|---|---|
| درگاه حمایت مالی | https://reymit.ir/42level |
| کانال یوتیوب | https://www.youtube.com/@42LEVEL |
| گیت‌هاب | https://github.com/mhbanaei |
| گیت‌هاب | https://github.com/AghaErfan |
| کانال توییچ | https://www.twitch.tv/42level |

## ✨ Features

- 🕶️ **Fully background operation** — the Google Translate window is never shown; everything happens in a hidden off-screen browser
- 🖼️ Auto-detects images in clipboard (`PrintScreen`, `Win+Shift+S`, `Ctrl+C` on an image)
- 📥 Saves the translated result into your chosen folder (default: `Pictures\ClipTranslate`)
- 📌 Shows the result as a beautiful floating overlay (rounded corners, dark theme, draggable, position remembered between runs); small images are auto-zoomed so the copy/close buttons always stay visible
- ⌨️ **Customizable hotkey** (default `F2`) to close the overlay — change it in settings (supports combos like `Ctrl+K`)
- ⚙️ Full **settings UI**: hotkey, target language, save folder, auto-close timer, notifications
- 🗂️ Tray menu: Settings / Translate a file… / Pause monitoring / Exit
- 📋 One-click **copy** of the translated image back to the clipboard from the overlay (no re-translation loop)
- 🔔 Optional system notification when the translation is ready

## 🔧 Requirements

- Python 3.8+
- Dependencies:

```bash
pip install wxPython pillow keyboard
```

```
py -m pip install wxPython
py -m pip install pillow
py -m pip install keyboard
```

- Microsoft Edge **WebView2 Runtime** (already installed on most Windows 10/11)

## 🚀 Usage

```bash
python ClipTranslateOverlay.py
```

- Copy a screenshot or image → the overlay appears with the translated image
- Press **F2** (or your custom hotkey) to close the overlay
- Right-click the tray icon for settings and options
- Run `python ClipTranslateOverlay.py --selftest` to verify the whole translation pipeline without a clipboard image

Settings are stored in `%APPDATA%\PantyOCR\config.json`.

## 📦 Building the .exe

Requires PyInstaller:

```bash
pip install pyinstaller
python -m PyInstaller --noconfirm ClipTranslateOverlay.spec
```

The result is `dist\ClipTranslateOverlay.exe` (one-file, no console, 42 logo icon).

> **Important**: the spec bundles `WebView2Loader.dll` (from your wxPython package) into the exe. Without it, the hidden Google Translate browser silently falls back to the old IE engine and the in-page translation stops working — do not build without that binary.

## Credits

- Erfan Shariat / Hossein Banaei
