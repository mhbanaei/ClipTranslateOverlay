# 📋 ClipTranslateOverlay

A Python-based desktop utility that monitors your clipboard for image content and automatically opens Google Translate's **image translation page** to process it. Once translated, the result is downloaded and displayed as a floating overlay on your screen for 60 seconds.

## ✨ Features

- 🖼️ Automatically detects images in clipboard
- 🌐 Opens Google Translate's image translation interface
- 📥 Auto-downloads translated result
- 📌 Displays translated image as an overlay for 60 seconds
- ⌨️ Allows manual closing with `Shift + Space`
- 💡 Works with copied screenshots or saved image files

---

## 🔧 Requirements

- Python 3.8+
- Dependencies:

```bash
pip install wxPython pillow keyboard
