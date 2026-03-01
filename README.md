# Quick OCR ⚠️ Work in Progress

Ferramenta desktop para extrair texto de imagens via OCR local (sem internet).  
Cole uma imagem com `Ctrl+V`, rode o OCR, copie o texto.

**Projeto pessoal, versão inicial, incompleto. Use por sua conta e risco.**

---

## Setup

1. Instale o [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki)
2. Clone o repositório e instale as dependências:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python quick_ocr_V1.py
```

> Se o Tesseract não estiver em `C:\Program Files\Tesseract-OCR\`, edite o caminho no topo do script.

---

## Funcionalidades

- `Ctrl+V` para colar imagem
- Pré-processamento automático (grayscale + upscale 3x + denoise)
- (experimental) Editor de cortes horizontais com undo/redo ; geralmente funciona bem para tabelas, mas pode comprometer a indentação
- (experimental) Modo código - preserva a indentação com snap para múltiplos de 4 espaços ; funciona melhor para código Python, para outras linguagens pode comprometer a indentação
