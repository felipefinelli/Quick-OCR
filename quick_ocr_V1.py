"""
OCR App
Dependências: pip install pillow pytesseract numpy tkinterdnd2
Tesseract:    https://github.com/UB-Mannheim/tesseract/wiki
"""

import re
import copy
import tkinter as tk
from tkinter import ttk, messagebox
from collections import defaultdict
import numpy as np
import pytesseract
from PIL import ImageGrab, ImageTk, Image, ImageFilter

# ── Drag-and-drop (tkinterdnd2 opcional) ──────────────────────────────────────
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _DND_AVAILABLE = True
except ImportError:
    _DND_AVAILABLE = False

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# ── Helpers ───────────────────────────────────────────────────────────────────

_VALID_TOKEN = re.compile(
    r"[a-zA-Z0-9\u00C0-\u024F_\.\(\)\[\]\{\}:=,+\-\*/<>\"\'#@!%&;\\]"
)

def is_valid_token(w):
    return bool(_VALID_TOKEN.search(w))

def preprocess(img):
    """Grayscale → 3x upscale → denoise."""
    img = img.convert("L")
    img = img.resize((img.width * 3, img.height * 3), Image.LANCZOS)
    img = img.filter(ImageFilter.MedianFilter(size=3))
    return img

def detect_h_lines(img, threshold=50.0, min_gap=8):
    """Detecta linhas horizontais separadoras por variância de pixel."""
    gray = np.array(img.convert("L"), dtype=np.float32)
    h = gray.shape[0]
    row_var = np.var(gray, axis=1)
    cuts, in_band, start = [], False, 0
    for y in range(h):
        if row_var[y] < threshold and not in_band:
            in_band, start = True, y
        elif row_var[y] >= threshold and in_band:
            in_band = False
            cuts.append((start + y) // 2)
    if in_band:
        cuts.append((start + h) // 2)
    margin = int(h * 0.02)
    cuts = [c for c in cuts if margin < c < h - margin]
    filtered = []
    for c in cuts:
        if not filtered or (c - filtered[-1]) >= min_gap:
            filtered.append(c)
    return filtered

def crop_by_h_lines(img, h_lines):
    """Divide imagem horizontalmente."""
    w, h = img.size
    ys = [0] + sorted(h_lines) + [h]
    return [img.crop((0, ys[i], w, ys[i+1]))
            for i in range(len(ys)-1) if ys[i+1] - ys[i] > 2]

def rebuild_text(data, min_conf, code_mode=False):
    """
    Reconstrói texto com indentação baseada em posição X.
    code_mode=True: snap para múltiplos de 4 espaços (tab size 4).
    """
    lines = defaultdict(list)
    char_widths, skipped = [], 0
    for i in range(len(data["text"])):
        word = data["text"][i].strip()
        conf = int(data["conf"][i])
        if not word or conf < 0:
            continue
        if conf < min_conf or not is_valid_token(word):
            skipped += 1
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines[key].append((data["left"][i], word))
        if len(word) > 0:
            char_widths.append(data["width"][i] / len(word))
    if not lines:
        return "", skipped
    char_w = max(1, sum(char_widths) / len(char_widths)) if char_widths else 10
    keys = sorted(lines.keys())
    x_min = min(x for k in keys for (x, _) in lines[k])
    result = []
    for k in keys:
        wl = sorted(lines[k], key=lambda t: t[0])
        raw = (wl[0][0] - x_min) / char_w
        indent = round(raw / 4) * 4 if code_mode else int(round(raw))
        result.append(" " * indent + " ".join(w for _, w in wl))
    return "\n".join(result), skipped

def run_ocr_on(img, lang, min_conf, code_mode=False):
    """Pré-processa e roda OCR numa imagem."""
    processed = preprocess(img)
    data = pytesseract.image_to_data(
        processed, config=f"--psm 6 -l {lang}",
        output_type=pytesseract.Output.DICT
    )
    return rebuild_text(data, min_conf, code_mode=code_mode)

def load_image_from_path(path):
    """Carrega imagem a partir de caminho (lida com paths do tkinterdnd2)."""
    # tkinterdnd2 pode retornar paths entre chaves: {C:/foo/bar.png}
    path = path.strip().strip("{").strip("}")
    return Image.open(path)


# ══════════════════════════════════════════════════════════════════════════════
# Editor de cortes horizontais
# ══════════════════════════════════════════════════════════════════════════════

SNAP   = 8        # px para detectar clique numa linha
C_LINE = "#ff4444" # cor das linhas
C_SEL  = "#f9e2af" # cor da linha selecionada


class CutEditor(tk.Toplevel):
    """
    Janela para editar linhas de corte horizontais.
    - Detectar automaticamente
    - Adicionar clicando no canvas
    - Selecionar + mover arrastando
    - Deletar com Delete/Backspace ou duplo clique
    - Undo/Redo com Ctrl+Z / Ctrl+Y
    - Restaurar (limpar tudo)
    - Realizar OCR → fecha e dispara OCR na janela principal
    """

    def __init__(self, master, img, on_ocr):
        super().__init__(master)
        self.title("Cortes horizontais")
        self.configure(bg="#1e1e2e")
        self.resizable(True, True)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self._img    = img
        self._on_ocr = on_ocr

        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        W = min(img.width + 20,  int(sw * 0.9))
        H = min(img.height + 110, int(sh * 0.88))
        self.geometry(f"{W}x{H}")

        self._lines      = []   # lista de y (int) na escala da imagem
        self._undo_stack = []
        self._redo_stack = []
        self._selected   = None  # índice selecionado
        self._dragging   = False
        self._drag_orig  = None  # y original antes do drag

        self._build_ui()
        self._render()

        self.bind("<Delete>",    lambda e: self._delete_selected())
        self.bind("<BackSpace>", lambda e: self._delete_selected())
        self.bind("<Control-z>", lambda e: self._undo())
        self.bind("<Control-Z>", lambda e: self._undo())
        self.bind("<Control-y>", lambda e: self._redo())
        self.bind("<Control-Y>", lambda e: self._redo())

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        tb = tk.Frame(self, bg="#181825", pady=5)
        tb.pack(fill="x")

        def B(text, cmd, fg="#cdd6f4"):
            return tk.Button(tb, text=text, command=cmd,
                             font=("Consolas", 10, "bold"), fg=fg, bg="#313244",
                             activebackground="#45475a", relief="flat",
                             padx=10, pady=4, cursor="hand2", bd=0)

        B("🔍 Auto-detectar",  self._auto_detect,  "#f9e2af").pack(side="left", padx=(8,2))
        B("↩ Undo",            self._undo,         "#cba6f7").pack(side="left", padx=2)
        B("↪ Redo",            self._redo,         "#cba6f7").pack(side="left", padx=2)
        B("🔄 Limpar linhas",  self._clear_lines,  "#89b4fa").pack(side="left", padx=2)
        B("▶ Realizar OCR",   self._do_ocr,       "#a6e3a1").pack(side="right", padx=(2,8))

        hint = tk.Frame(self, bg="#1e1e2e")
        hint.pack(fill="x", padx=10, pady=(3,0))
        self._hint = tk.StringVar(value=
            "Clique no canvas para adicionar linha  •  "
            "Arraste para mover  •  Delete ou duplo-clique para remover"
        )
        tk.Label(hint, textvariable=self._hint, fg="#6c7086",
                 bg="#1e1e2e", font=("Consolas", 8), anchor="w").pack(fill="x")

        # Canvas
        cf = tk.Frame(self, bg="#1e1e2e")
        cf.pack(fill="both", expand=True, padx=8, pady=6)

        self._cv = tk.Canvas(cf, bg="#181825", highlightthickness=0)
        sb_y = tk.Scrollbar(cf, orient="vertical",   command=self._cv.yview)
        sb_x = tk.Scrollbar(cf, orient="horizontal", command=self._cv.xview)
        self._cv.configure(yscrollcommand=sb_y.set, xscrollcommand=sb_x.set)
        sb_x.pack(side="bottom", fill="x")
        sb_y.pack(side="right",  fill="y")
        self._cv.pack(side="left", fill="both", expand=True)

        self._cv.configure(scrollregion=(0, 0, self._img.width, self._img.height))
        self._tk_img = ImageTk.PhotoImage(self._img)
        self._cv.create_image(0, 0, anchor="nw", image=self._tk_img)

        self._cv.bind("<ButtonPress-1>",   self._on_press)
        self._cv.bind("<B1-Motion>",       self._on_motion)
        self._cv.bind("<ButtonRelease-1>", self._on_release)
        self._cv.bind("<Double-Button-1>", self._on_double)
        self._cv.bind("<Motion>",          self._on_hover)

    # ── Canvas utils ──────────────────────────────────────────────────────────

    def _cy(self, event):
        return int(self._cv.canvasy(event.y))

    def _hit(self, y):
        """Retorna índice da linha mais próxima de y, ou None."""
        best, dist = None, SNAP + 1
        for i, ly in enumerate(self._lines):
            d = abs(y - ly)
            if d < dist:
                dist, best = d, i
        return best

    def _render(self):
        self._cv.delete("line")
        for i, y in enumerate(self._lines):
            color = C_SEL if i == self._selected else C_LINE
            width = 2 if i == self._selected else 1
            self._cv.create_line(0, y, self._img.width, y,
                                 fill=color, width=width, tags="line")

    # ── Eventos ───────────────────────────────────────────────────────────────

    def _on_press(self, event):
        y = self._cy(event)
        idx = self._hit(y)
        if idx is not None:
            self._selected = idx
            self._dragging = True
            self._drag_orig = self._lines[idx]
            self._push_undo()
        else:
            self._push_undo()
            self._lines.append(y)
            self._lines.sort()
            self._selected = self._lines.index(y)
            self._dragging = False
        self._render()

    def _on_motion(self, event):
        if not self._dragging or self._selected is None:
            return
        y = max(0, min(self._img.height, self._cy(event)))
        self._lines[self._selected] = y
        self._render()

    def _on_release(self, event):
        if self._dragging:
            self._lines.sort()
            self._selected = None
        self._dragging = False
        self._render()

    def _on_double(self, event):
        idx = self._hit(self._cy(event))
        if idx is not None:
            self._push_undo()
            self._lines.pop(idx)
            self._selected = None
            self._render()

    def _on_hover(self, event):
        y = self._cy(event)
        cursor = "sb_v_double_arrow" if self._hit(y) is not None else "crosshair"
        self._cv.config(cursor=cursor)

    # ── Ações ─────────────────────────────────────────────────────────────────

    def _auto_detect(self):
        self._push_undo()
        detected = detect_h_lines(self._img)
        existing = set(self._lines)
        for y in detected:
            if not any(abs(y - e) < SNAP for e in existing):
                self._lines.append(y)
        self._lines.sort()
        self._selected = None
        self._render()
        n = len(detected)
        self._hint.set(f"✔ {n} linha(s) detectada(s) e adicionada(s).")

    def _delete_selected(self):
        if self._selected is not None:
            self._push_undo()
            self._lines.pop(self._selected)
            self._selected = None
            self._render()

    def _clear_lines(self):
        self._push_undo()
        self._lines = []
        self._selected = None
        self._render()
        self._hint.set("Linhas limpas.")

    def _push_undo(self):
        self._undo_stack.append(copy.copy(self._lines))
        self._redo_stack.clear()

    def _undo(self):
        if not self._undo_stack:
            return
        self._redo_stack.append(copy.copy(self._lines))
        self._lines = self._undo_stack.pop()
        self._selected = None
        self._render()
        self._hint.set("Undo.")

    def _redo(self):
        if not self._redo_stack:
            return
        self._undo_stack.append(copy.copy(self._lines))
        self._lines = self._redo_stack.pop()
        self._selected = None
        self._render()
        self._hint.set("Redo.")

    def _do_ocr(self):
        lines = sorted(self._lines)
        self.destroy()
        self._on_ocr(lines)


# ══════════════════════════════════════════════════════════════════════════════
# Janela principal
# ══════════════════════════════════════════════════════════════════════════════

# Extensões de imagem suportadas
_IMG_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".tif", ".webp"}


class App(TkinterDnD.Tk if _DND_AVAILABLE else tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("OCR")
        self.configure(bg="#1e1e2e")
        self.geometry("1150x720")
        self.minsize(750, 480)

        self._img       = None
        self._h_lines   = []
        self._code_mode = tk.BooleanVar(value=False)
        self._build_ui()
        self.bind_all("<Control-v>", self._paste)
        self.bind_all("<Control-V>", self._paste)

        # Registra drop na janela toda
        if _DND_AVAILABLE:
            self._register_dnd(self)

    def _register_dnd(self, widget):
        """Registra drag-and-drop em um widget usando tkinterdnd2."""
        widget.drop_target_register(DND_FILES)
        widget.dnd_bind("<<Drop>>", self._on_drop)

    def _on_drop(self, event):
        """Chamado quando um arquivo é solto na janela."""
        raw = event.data or ""
        # tkinterdnd2 pode retornar múltiplos paths separados por espaço/chaves
        # Pega apenas o primeiro arquivo válido
        paths = self.tk.splitlist(raw)
        for path in paths:
            path = path.strip().strip("{").strip("}")
            ext = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
            if ext in _IMG_EXTS:
                try:
                    img = Image.open(path)
                    img.load()  # força leitura completa
                    self._load_image(img, label=path.split("/")[-1].split("\\")[-1])
                    return
                except Exception as e:
                    messagebox.showerror("Erro ao abrir imagem", str(e))
                    return
        self._status.set("⚠  Arquivo não reconhecido como imagem. Use PNG, JPG, BMP, etc.")

    def _build_ui(self):
        # ── Barra de botões ──
        bar = tk.Frame(self, bg="#1e1e2e")
        bar.pack(fill="x", padx=16, pady=(14, 4))

        def B(text, cmd, fg, **kw):
            return tk.Button(bar, text=text, command=cmd,
                             font=("Consolas", 10, "bold"), fg=fg, bg="#313244",
                             activebackground="#45475a", activeforeground=fg,
                             disabledforeground="#45475a",
                             relief="flat", padx=12, pady=5, cursor="hand2", bd=0, **kw)

        self._btn_cuts = B("✂  Cortes", self._open_cuts, "#f9e2af")
        self._btn_cuts.pack(side="left", padx=(0, 4))
        self._btn_cuts.config(state="disabled")

        self._btn_ocr = B("▶  Processar OCR", self._run_ocr, "#a6e3a1")
        self._btn_ocr.pack(side="left", padx=(0, 12))
        self._btn_ocr.config(state="disabled")

        tk.Frame(bar, bg="#45475a", width=1, height=26).pack(side="left", padx=6)

        B("📋 Copiar", self._copy, "#89dceb").pack(side="left", padx=(6, 4))
        B("🗑  Limpar", self._clear, "#f38ba8").pack(side="left")

        # Idioma + confiança
        tk.Label(bar, text="  Idioma:", fg="#6c7086", bg="#1e1e2e",
                 font=("Consolas", 10)).pack(side="left", padx=(20, 4))
        self._lang = tk.StringVar(value="por+eng")
        ttk.Combobox(bar, textvariable=self._lang,
                     values=["por+eng", "eng", "por"],
                     width=9, state="readonly").pack(side="left")

        tk.Label(bar, text="  Confiança:", fg="#6c7086", bg="#1e1e2e",
                 font=("Consolas", 10)).pack(side="left", padx=(14, 4))
        self._conf = tk.IntVar(value=40)
        self._conf_lbl = tk.Label(bar, text="40", fg="#cba6f7", bg="#1e1e2e",
                                   font=("Consolas", 10, "bold"), width=3)
        self._conf_lbl.pack(side="left")
        tk.Scale(bar, from_=0, to=90, orient="horizontal", variable=self._conf,
                 bg="#1e1e2e", fg="#cdd6f4", troughcolor="#313244",
                 highlightthickness=0, length=110, showvalue=False,
                 command=lambda v: self._conf_lbl.config(text=str(int(float(v))))
                 ).pack(side="left")

        tk.Frame(bar, bg="#45475a", width=1, height=26).pack(side="left", padx=8)
        tk.Checkbutton(bar, text="{ } Modo código",
                       variable=self._code_mode,
                       font=("Consolas", 10, "bold"),
                       fg="#cba6f7", bg="#1e1e2e",
                       selectcolor="#313244",
                       activebackground="#1e1e2e", activeforeground="#cba6f7",
                       relief="flat", cursor="hand2"
                       ).pack(side="left", padx=(0, 4))

        # ── Painel dividido ──
        paned = tk.PanedWindow(self, orient=tk.HORIZONTAL,
                               bg="#313244", sashwidth=5, sashrelief="flat")
        paned.pack(fill="both", expand=True, padx=16, pady=(6, 16))

        # Esquerdo — imagem
        lf = tk.Frame(paned, bg="#181825")
        paned.add(lf, minsize=280)
        tk.Label(lf, text="IMAGEM", font=("Consolas", 8, "bold"),
                 fg="#45475a", bg="#181825").pack(anchor="w", padx=8, pady=(5,0))

        # Drop zone — frame com borda tracejada
        self._drop_frame = tk.Frame(lf, bg="#181825", highlightthickness=2,
                                     highlightbackground="#313244",
                                     highlightcolor="#cba6f7")
        self._drop_frame.pack(fill="both", expand=True, padx=4, pady=4)

        dnd_hint = ("Arraste uma imagem aqui\nou Cole com Ctrl+V"
                    if _DND_AVAILABLE else "Cole uma imagem\nCtrl+V")
        self._img_lbl = tk.Label(self._drop_frame, text=dnd_hint,
                                  font=("Consolas", 12), fg="#45475a",
                                  bg="#181825", justify="center")
        self._img_lbl.pack(fill="both", expand=True, padx=4, pady=4)

        # Registra DnD também no frame e label internos
        if _DND_AVAILABLE:
            self._register_dnd(self._drop_frame)
            self._register_dnd(self._img_lbl)

        # Direito — texto
        rf = tk.Frame(paned, bg="#181825")
        paned.add(rf, minsize=280)
        tk.Label(rf, text="TEXTO EXTRAÍDO", font=("Consolas", 8, "bold"),
                 fg="#45475a", bg="#181825").pack(anchor="w", padx=8, pady=(5,0))

        tf = tk.Frame(rf, bg="#181825")
        tf.pack(fill="both", expand=True, padx=4, pady=4)
        self._txt = tk.Text(tf, font=("Consolas", 12), bg="#11111b", fg="#cdd6f4",
                             insertbackground="#cba6f7", selectbackground="#313244",
                             relief="flat", padx=10, pady=8, wrap="none", undo=True)
        self._txt.pack(fill="both", expand=True, side="left")
        sy = tk.Scrollbar(tf, command=self._txt.yview, bg="#313244")
        sy.pack(side="right", fill="y")
        self._txt.config(yscrollcommand=sy.set)
        sx = tk.Scrollbar(rf, orient="horizontal", command=self._txt.xview, bg="#313244")
        sx.pack(fill="x", padx=4)
        self._txt.config(xscrollcommand=sx.set)

        # Status
        dnd_note = "" if _DND_AVAILABLE else "  [instale tkinterdnd2 para drag-and-drop]"
        self._status = tk.StringVar(value=f"Pronto — arraste uma imagem ou use Ctrl+V{dnd_note}")
        tk.Label(self, textvariable=self._status, font=("Consolas", 8),
                 fg="#45475a", bg="#1e1e2e", anchor="w").pack(fill="x", padx=18, pady=(0,5))

    # ── Carregamento de imagem ────────────────────────────────────────────────

    def _load_image(self, img, label=""):
        """Carrega uma imagem PIL na app."""
        self._img = img
        self._h_lines = []
        self._refresh_preview()
        self._btn_cuts.config(state="normal")
        self._btn_ocr.config(state="normal")
        size_info = f"{img.width}×{img.height}px"
        self._status.set(f"✔  Imagem carregada: {label}  ({size_info})" if label
                         else f"✔  Imagem colada: {size_info}")
        # Realça borda do drop zone brevemente
        self._drop_frame.config(highlightbackground="#a6e3a1")
        self.after(800, lambda: self._drop_frame.config(highlightbackground="#313244"))

    # ── Pasta / preview ───────────────────────────────────────────────────────

    def _paste(self, _=None):
        try:
            img = ImageGrab.grabclipboard()
            if not isinstance(img, Image.Image):
                self._status.set("⚠  Copie uma imagem antes de colar.")
                return
            self._load_image(img)
        except Exception as e:
            messagebox.showerror("Erro", str(e))

    def _refresh_preview(self):
        if self._img is None:
            return
        self._img_lbl.config(image="", text="")
        fw = self._img_lbl.winfo_width()  or 460
        fh = self._img_lbl.winfo_height() or 580
        r = min(fw / self._img.width, fh / self._img.height, 1.0)
        prev = self._img.resize((max(1, int(self._img.width*r)),
                                  max(1, int(self._img.height*r))), Image.LANCZOS)
        self._tk_img = ImageTk.PhotoImage(prev)
        self._img_lbl.config(image=self._tk_img)

    # ── Editor de cortes ──────────────────────────────────────────────────────

    def _open_cuts(self):
        if self._img:
            CutEditor(self, self._img, on_ocr=self._ocr_with_cuts)

    def _ocr_with_cuts(self, h_lines):
        self._h_lines = h_lines
        self._run_ocr()

    # ── OCR ───────────────────────────────────────────────────────────────────

    def _run_ocr(self):
        if self._img is None:
            return
        lang, min_conf = self._lang.get(), self._conf.get()
        try:
            if not self._h_lines:
                self._status.set("⏳ Processando OCR...")
                self.update_idletasks()
                text, skipped = run_ocr_on(self._img, lang, min_conf,
                                            code_mode=self._code_mode.get())
                self._show_result(text, skipped, 1)
            else:
                crops = crop_by_h_lines(self._img, self._h_lines)
                parts, total_skip = [], 0
                for i, crop in enumerate(crops, 1):
                    self._status.set(f"⏳ Bloco {i}/{len(crops)}...")
                    self.update_idletasks()
                    t, s = run_ocr_on(crop, lang, min_conf, code_mode=self._code_mode.get())
                    total_skip += s
                    if t.strip():
                        parts.append(t)
                self._show_result("\n".join(parts), total_skip, len(crops))
        except pytesseract.TesseractNotFoundError:
            messagebox.showerror("Tesseract não encontrado",
                                 r"C:\Program Files\Tesseract-OCR\tesseract.exe não encontrado.")
        except Exception as e:
            messagebox.showerror("Erro no OCR", str(e))

    def _show_result(self, text, skipped, blocks):
        self._txt.delete("1.0", "end")
        self._txt.insert("1.0", text)
        self._status.set(
            f"✔  {blocks} bloco(s)  •  {len(text)} chars  •  {skipped} token(s) ignorados"
        )

    # ── Utilitários ───────────────────────────────────────────────────────────

    def _copy(self):
        t = self._txt.get("1.0", "end-1c")
        if t.strip():
            self.clipboard_clear()
            self.clipboard_append(t)
            self._status.set("✔  Texto copiado.")
        else:
            self._status.set("⚠  Nada para copiar.")

    def _clear(self):
        self._img = None
        self._h_lines = []
        self._tk_img = None
        dnd_hint = ("Arraste uma imagem aqui\nou Cole com Ctrl+V"
                    if _DND_AVAILABLE else "Cole uma imagem\nCtrl+V")
        self._img_lbl.config(image="", text=dnd_hint)
        self._txt.delete("1.0", "end")
        self._btn_cuts.config(state="disabled")
        self._btn_ocr.config(state="disabled")
        self._status.set("Pronto — arraste uma imagem ou use Ctrl+V")


if __name__ == "__main__":
    App().mainloop()