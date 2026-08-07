<p align="center">
  <img src="assets/banner.jpg" alt="ClipTranslateOverlay Banner" width="100%" style="max-width:1200px; border-radius:12px;">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/42LEVEL-ClipTranslateOverlay-8A2BE2?style=for-the-badge&logo=github" alt="42LEVEL Badge"/>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.8+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/Windows-10%2F11-0078D6?style=flat-square&logo=windows&logoColor=white" alt="Windows"/>
  <img src="https://img.shields.io/badge/WebView2-Ready-1E90FF?style=flat-square&logo=microsoftedge" alt="WebView2"/>
  <img src="https://img.shields.io/badge/Status-Active-success?style=flat-square" alt="Status"/>
</p>

<p align="center">
  <img src="assets/typing-demo.gif" alt="Typing Effect Demo" width="600">
</p>

<h1 align="center">ClipTranslateOverlay</h1>

<p align="center">
  <strong>Background Clipboard Image Translator</strong><br>
  <em>مترجم تصویر کلیپ‌بورد در پس‌زمینه</em>
</p>

<p align="center">
  Instantly translate any image from your clipboard with a modern, glassy overlay — designed for gamers, researchers, and power users.
</p>
- [بخش 
---

## 🚀 Features

| Feature | Description |
|---------|-------------|
| **Automatic Image Translation** | Detects any image copied to the clipboard (`PrintScreen`, `Win+Shift+S`, or `Ctrl+C` on an image) and translates it instantly. |
| **Built-in Snipping Tool** | Press **F3** (customizable) to capture any part of the screen without leaving your workflow. |
| **Glassy Floating Overlay** | Displays the translated image with a modern acrylic design. Supports **zoom** and **pan**. |
| **Smart Badge** | Shows a discreet in-game badge that auto-hides after a few seconds. |
| **Process / Window Manager** | Select a specific game or window and capture it directly. |
| **Auto-start with Windows** | Optional setting to launch the tool when your PC boots. |
| **Clean Exit** | Automatically wipes the temporary save folder on exit (enabled by default). |
| **Full Settings UI** | Categorized into: Language, Hotkeys, Translation, Display, System, and Advanced. |

---

## 🎥 Demo

<p align="center">
  <img src="assets/demo.gif" alt="Demo" width="80%">
</p>

---

## 📦 Installation

### Prerequisites

- **Windows 10 or 11** (WebView2 Runtime is usually pre-installed)
- **Python 3.8+**

### Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/mhbanaei/ClipTranslateOverlay.git
cd ClipTranslateOverlay

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the application
python ClipTranslateOverlay.py
