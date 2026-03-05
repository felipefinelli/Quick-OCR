# Quick-OCR

> ⚠️ **Under Development** — Personal project, initial version, still incomplete. Use at your own risk.

A simple tool to extract text from images directly on your computer — no internet required.

Printscreen → `Ctrl+V` → click **"Process OCR"** → text ready to use.


---


## 📦 Download 

Don't want to install Python and dependencies? Grab the ready-to-use executable:

**→ [Download Quick-OCR.exe](https://github.com/felipefinelli/Quick-OCR/releases/download/V1_Initial-Version/Quick-OCR.exe)**



---


## ✨ Features
- **Automatic preprocessing:** black and white, 3× upscaling, noise removal
- **Horizontal cut editor with undo/redo** *(experimental)* – can be useful for tables but may affect indentation
- **Code mode** *(experimental)* – better preservation of indentation with snapping to multiples of 4 spaces; works best for Python code, may affect indentation in other languages


-----


## ⚙️ Development Setup

###  📋 Requirements

- Windows
- Python 3.9+
- Tesseract OCR installed locally
##
### 1. Install Tesseract OCR

Download and install from the [Tesseract-OCR](https://github.com/tesseract-ocr/tesseract).

> **Note:** The script expects Tesseract at `C:\Program Files\Tesseract-OCR\` by default. Adjust the path at the top of the script if needed.
##
### 2. Clone the repo and install dependencies

```bash
git clone https://github.com/felipefinelli/Quick-OCR.git
cd Quick-OCR

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```
##
### 3. Run

```bash
python quick_ocr_V1.py
```
