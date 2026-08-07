<p align="center">
  <img src="assest/banner.jpg" alt="Banner" width="100%">
</p>

<div align="center">
  <h1><strong>🖼️ ClipTranslateOverlay</strong></h1>
  <p><strong>Background Clipboard Image Translator · مترجم تصویر کلیپ‌بورد در پس‌زمینه</strong></p>
  <p>
    <img src="https://img.shields.io/badge/42LEVEL-ClipTranslateOverlay-8A2BE2?style=for-the-badge&logo=github" alt="42LEVEL Badge"/>
  </p>
  <p>
    <img src="https://img.shields.io/badge/Python-3.8+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python"/>
    <img src="https://img.shields.io/badge/Windows-10%2F11-0078D6?style=flat-square&logo=windows&logoColor=white" alt="Windows"/>
    <img src="https://img.shields.io/badge/WebView2-Ready-1E90FF?style=flat-square&logo=microsoftedge" alt="WebView2"/>
  </p>
  <p>
    <a href="https://github.com/mhbanaei/ClipTranslateOverlay">📁 GitHub Repository</a>
  </p>
</div>

---

## 📑 Table of Contents
- [🚀 Features](#-features)
- [📦 Installation](#-installation)
- [📖 Detailed Usage & Hotkeys](#-detailed-usage--hotkeys)
- [📁 Code Structure](#-code-structure)
- [⚙️ Configuration](#️-configuration)
- [🔧 Troubleshooting](#-troubleshooting)

---

## 🚀 Features

- **Automatic image translation** – detects any image copied to the clipboard (`PrintScreen`, `Win+Shift+S`, or `Ctrl+C` on an image) and translates it instantly.
- **Built‑in snipping tool** – press **F3** (customizable) to launch a screen capture tool without leaving your workflow.
- **Glassy floating overlay** – displays the translated image with a modern acrylic design, supporting **zoom & pan**.
- **One‑click copy** – copy the translated image back to your clipboard with a single button.
- **Smart badge** – shows a discreet in‑game badge that auto‑hides after a few seconds.
- **Process / Window manager** – select a specific game or window and capture it directly.
- **Auto‑start with Windows** – optional, start the tool when your PC boots.
- **Clean exit** – automatically wipes the temporary save folder on exit (optional, enabled by default).
- **Full settings UI** – categorized into: Language, Hotkeys, Translation, Display, System, and Advanced.
- **Bilingual interface** – instantly switch between **Persian (RTL)** and **English (LTR)**.

---

## 📦 Installation

### Prerequisites
- **Windows 10 or 11** (with **WebView2 Runtime** – usually pre‑installed)
- **Python 3.8+**

### Steps
```bash
# 1. Clone the repository
git clone https://github.com/mhbanaei/ClipTranslateOverlay.git
cd ClipTranslateOverlay

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the application
python ClipTranslateOverlay.py
