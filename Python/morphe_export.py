"""morphe_export.py — exporta janelas Tk/ttk do Morphe para SVG vetorial.

Não é uma captura de tela. O exportador percorre a árvore de widgets da
janela *rodando*, lê a geometria real que o Tk calculou (após
``update_idletasks``) e re-emite cada widget como primitivas SVG. Os
gráficos Matplotlib não são rasterizados: a própria ``Figure`` é
redesenhada pelo backend SVG, então curvas, marcadores e rótulos saem
como vetor puro.

Consequências práticas:

  * resolução infinita — o SVG serve tanto para a coluna do IEEE quanto
    para um pôster A0;
  * texto vetorial e selecionável no PDF final;
  * determinístico — a mesma chamada gera exatamente o mesmo arquivo;
  * zero modificação no Morphe: o módulo só *lê* a árvore de widgets.

Uso típico
----------
    import morphe_export as mex

    win = FFTWindow(root)
    root.update_idletasks()          # deixa o Tk medir tudo
    mex.export_window(win, "figuras/fft.svg")

Conversão para o artigo (LaTeX):
    rsvg-convert -f pdf -o fft.pdf fft.svg     # ou: inkscape --export-type=pdf
    rsvg-convert -f png -z 4 -o fft.png fft.svg   # 4× para preview raster

Limitações conhecidas
---------------------
  * o foco (focus ring) e o hover não são desenhados — a janela é
    exportada em repouso, que é o que se quer numa figura;
  * relevos 3D do tema `clam` (bevels de 1 px) viram uma borda plana;
  * itens de Canvas do tipo `bitmap`/`stipple` não são suportados
    (o Morphe não usa nenhum).
"""
from __future__ import annotations

import base64
import gc
import io
import os
import re
import tempfile
import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont
from typing import Dict, List, Optional, Sequence
from xml.sax.saxutils import escape as xml_escape

__all__ = ["export_window", "SvgExporter", "discover_figures"]


# ══════════════════════════════════════════════════════════════════
# Descoberta das Figures do Matplotlib
# ══════════════════════════════════════════════════════════════════

def discover_figures() -> Dict[str, object]:
    """Mapeia caminho-do-widget-Tk → matplotlib.figure.Figure.

    O widget Tk criado pelo ``FigureCanvasTkAgg`` é um ``tk.Canvas``
    comum: ele *não* guarda referência à Figure. Em vez de exigir uma
    modificação no Morphe, varremos o heap com o gc à procura das
    instâncias vivas de ``FigureCanvasTkAgg`` e montamos o mapa a partir
    delas. Custa alguns milissegundos e mantém o Morphe intocado.
    """
    try:
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    except ImportError:
        return {}

    mapping: Dict[str, object] = {}
    for obj in gc.get_objects():
        if isinstance(obj, FigureCanvasTkAgg):
            try:
                mapping[str(obj.get_tk_widget())] = obj.figure
            except Exception:
                pass
    return mapping


# ══════════════════════════════════════════════════════════════════
# Utilitários de SVG
# ══════════════════════════════════════════════════════════════════

def _f(v: float) -> str:
    """Formata número para o SVG sem lixo de ponto flutuante."""
    return f"{v:.2f}".rstrip("0").rstrip(".") or "0"


def _prefix_svg_ids(svg: str, prefix: str) -> str:
    """Prefixa todos os `id` de um SVG para evitar colisão ao aninhar.

    IDs em SVG são globais ao documento, não ao elemento <svg> aninhado.
    Duas Figures embutidas na mesma janela definiriam glifos e clip-paths
    com os mesmos nomes.
    """
    for ident in set(re.findall(r'id="([^"]+)"', svg)):
        svg = (svg
               .replace(f'id="{ident}"', f'id="{prefix}{ident}"')
               .replace(f'href="#{ident}"', f'href="#{prefix}{ident}"')
               .replace(f"url(#{ident})", f"url(#{prefix}{ident})"))
    return svg


def _strip_svg_preamble(svg: str) -> str:
    """Remove <?xml?>, <!DOCTYPE> e comentários antes do <svg>."""
    i = svg.find("<svg")
    return svg[i:] if i >= 0 else svg


# ══════════════════════════════════════════════════════════════════
# Exportador
# ══════════════════════════════════════════════════════════════════

class SvgExporter:
    """Percorre a árvore de widgets de uma janela e emite SVG."""

    # Cor de "field" (fundo de Entry/Combobox) do tema clam.
    CLAM_FIELD = "#ffffff"
    CLAM_BORDER = "#9e9a91"

    def __init__(self, top: tk.Misc, *,
                 figures: Optional[Dict[str, object]] = None,
                 embed_images: bool = True,
                 plot_facecolor: Optional[str] = None,
                 skip: Sequence[tk.Misc] = ()):
        self.top = top
        self.style = ttk.Style(top)
        self.scaling = float(top.tk.call("tk", "scaling"))
        self.figures = discover_figures() if figures is None else figures
        self.embed_images = embed_images
        self.plot_facecolor = plot_facecolor
        self.skip = {str(w) for w in skip}

        self._body: List[str] = []
        self._defs: List[str] = []
        self._uid = 0
        self._rgb_cache: Dict[str, str] = {}
        self._font_cache: Dict[str, tkfont.Font] = {}

        self.x0 = top.winfo_rootx()
        self.y0 = top.winfo_rooty()
        self.W = top.winfo_width()
        self.H = top.winfo_height()

    # ── helpers ────────────────────────────────────────────────

    def _next_id(self, kind: str) -> str:
        self._uid += 1
        return f"{kind}{self._uid}"

    def rect_of(self, w: tk.Misc):
        """Retângulo do widget em coordenadas da janela (px)."""
        return (w.winfo_rootx() - self.x0,
                w.winfo_rooty() - self.y0,
                w.winfo_width(),
                w.winfo_height())

    def rgb(self, color, ref: Optional[tk.Misc] = None) -> Optional[str]:
        """Resolve qualquer especificação de cor do Tk para '#rrggbb'."""
        if color in (None, "", "none"):
            return None
        color = str(color)
        if color in self._rgb_cache:
            return self._rgb_cache[color]
        try:
            r, g, b = (ref or self.top).winfo_rgb(color)  # 16 bits/canal
            out = f"#{r >> 8:02x}{g >> 8:02x}{b >> 8:02x}"
        except tk.TclError:
            out = None
        self._rgb_cache[color] = out
        return out

    def font(self, spec, ref: Optional[tk.Misc] = None) -> tkfont.Font:
        key = str(spec) if spec else "TkDefaultFont"
        if key not in self._font_cache:
            try:
                self._font_cache[key] = tkfont.Font(root=ref or self.top,
                                                    font=key)
            except tk.TclError:
                self._font_cache[key] = tkfont.nametofont("TkDefaultFont")
        return self._font_cache[key]

    def font_css(self, f: tkfont.Font):
        """(família, tamanho-px, peso, estilo) prontos para o SVG."""
        a = f.actual()
        size = a["size"]
        # Tk: tamanho > 0 → pontos; < 0 → pixels.
        px = size * self.scaling if size > 0 else -size
        fam = a["family"]
        return (fam, px,
                "bold" if a["weight"] == "bold" else "normal",
                "italic" if a["slant"] == "italic" else "normal")

    @staticmethod
    def _cls(w: tk.Misc) -> str:
        return w.winfo_class()

    def style_name(self, w: tk.Misc) -> str:
        try:
            s = w.cget("style")
        except tk.TclError:
            s = ""
        return s or self._cls(w)

    def clam_border(self, style_name: str) -> int:
        """Largura da borda que o clam *de fato* desenha.

        Medido, não deduzido: o `lookup` devolve borderwidth=1 para os
        estilos `relief=solid` do Morphe, mas o clam pinta 2 px. Com
        relief=flat ou borderwidth=0 ele não pinta nada.
        """
        relief = str(self.style.lookup(style_name, "relief") or "flat")
        try:
            bw = int(self.style.lookup(style_name, "borderwidth") or 0)
        except (TypeError, ValueError):
            bw = 0
        if relief == "flat" or bw <= 0:
            return 0
        return max(2, bw)

    def lookup(self, w: tk.Misc, opt: str, default=None):
        v = self.style.lookup(self.style_name(w), opt)
        return v if v not in ("", None) else default

    def cget(self, w: tk.Misc, opt: str, default=None):
        try:
            v = w.cget(opt)
        except tk.TclError:
            return default
        return v if v not in ("", None) else default

    def text_of(self, w: tk.Misc) -> str:
        """Texto do widget, seguindo `textvariable` quando presente."""
        txt = self.cget(w, "text", "")
        if txt:
            return str(txt)
        var = self.cget(w, "textvariable", "")
        if var:
            try:
                return str(w.tk.globalgetvar(var))
            except tk.TclError:
                return ""
        return ""

    # ── primitivas ─────────────────────────────────────────────

    def add_rect(self, x, y, w, h, fill=None, stroke=None, sw=1.0):
        if w <= 0 or h <= 0:
            return
        if not fill and not stroke:
            return
        parts = [f'<rect x="{_f(x)}" y="{_f(y)}" '
                 f'width="{_f(w)}" height="{_f(h)}"']
        parts.append(f'fill="{fill}"' if fill else 'fill="none"')
        if stroke:
            # stroke centrado na borda: encolhe meio pixel para alinhar
            parts[0] = (f'<rect x="{_f(x + sw / 2)}" y="{_f(y + sw / 2)}" '
                        f'width="{_f(max(0, w - sw))}" '
                        f'height="{_f(max(0, h - sw))}"')
            parts.append(f'stroke="{stroke}" stroke-width="{_f(sw)}"')
        self._body.append(" ".join(parts) + "/>")

    def wrap(self, text: str, f: tkfont.Font, wraplength: int) -> List[str]:
        """Reproduz a quebra de linha do Tk: respeita \\n e quebra em
        espaços; só parte palavra quando ela sozinha estoura a largura."""
        lines: List[str] = []
        for para in str(text).split("\n"):
            if wraplength <= 0 or f.measure(para) <= wraplength:
                lines.append(para)
                continue
            cur = ""
            for word in para.split(" "):
                cand = f"{cur} {word}".strip()
                if cur and f.measure(cand) > wraplength:
                    lines.append(cur)
                    cur = word
                else:
                    cur = cand
                # palavra isolada maior que a largura → quebra bruta
                while f.measure(cur) > wraplength and len(cur) > 1:
                    cut = len(cur)
                    while cut > 1 and f.measure(cur[:cut]) > wraplength:
                        cut -= 1
                    lines.append(cur[:cut])
                    cur = cur[cut:]
            lines.append(cur)
        return lines

    @staticmethod
    def parse_anchor(anchor) -> tuple:
        """Decompõe uma âncora do Tk em (vertical, horizontal).

        Cuidado com a armadilha: as âncoras válidas são n/ne/e/se/s/sw/w/nw
        e **center** — e "center" contém as letras 'n' e 'e'. Testar com
        `"n" in anchor` manda todo texto centralizado para o canto superior
        direito. Por isso o caso central é tratado antes de qualquer coisa.
        """
        a = str(anchor).lower().strip()
        if a in ("", "center", "centre", "c"):
            return "", ""
        v = "n" if a.startswith("n") else ("s" if a.startswith("s") else "")
        h = "w" if a.endswith("w") else ("e" if a.endswith("e") else "")
        return v, h

    def add_text(self, text, box, f: tkfont.Font, fill, *,
                 anchor="center", justify="left", wraplength=0,
                 padx=0, pady=0):
        """Desenha texto seguindo a semântica de anchor/justify do Tk."""
        if not text:
            return
        x, y, w, h = box
        cx, cy = x + padx, y + pady
        cw, ch = max(0, w - 2 * padx), max(0, h - 2 * pady)

        lines = self.wrap(text, f, wraplength)
        ls = f.metrics("linespace")
        asc = f.metrics("ascent")
        block_h = ls * len(lines)
        block_w = max((f.measure(ln) for ln in lines), default=0)

        va, ha = self.parse_anchor(anchor)

        # posição vertical do bloco
        if va == "n":
            top = cy
        elif va == "s":
            top = cy + ch - block_h
        else:
            top = cy + (ch - block_h) / 2
        # posição horizontal do bloco
        if ha == "w":
            left = cx
        elif ha == "e":
            left = cx + cw - block_w
        else:
            left = cx + (cw - block_w) / 2

        fam, px, weight, slant = self.font_css(f)
        deco = ' text-decoration="underline"' if f.actual()["underline"] else ""

        for i, line in enumerate(lines):
            if not line:
                continue
            if justify == "center":
                tx, ta = left + block_w / 2, "middle"
            elif justify == "right":
                tx, ta = left + block_w, "end"
            else:
                tx, ta = left, "start"
            by = top + i * ls + asc
            self._body.append(
                f'<text x="{_f(tx)}" y="{_f(by)}" text-anchor="{ta}" '
                f'font-family="{xml_escape(fam)}, sans-serif" '
                f'font-size="{_f(px)}px" font-weight="{weight}" '
                f'font-style="{slant}" fill="{fill}"{deco} '
                f'xml:space="preserve">{xml_escape(line)}</text>')

    def add_image(self, img_name: str, box, ref: tk.Misc):
        """Embute uma PhotoImage do Tk como PNG base64 (ícones da toolbar)."""
        if not self.embed_images or not img_name:
            return
        x, y, w, h = box
        try:
            with tempfile.NamedTemporaryFile(suffix=".png",
                                             delete=False) as tmp:
                path = tmp.name
            ref.tk.call(img_name, "write", path, "-format", "png")
            with open(path, "rb") as fh:
                b64 = base64.b64encode(fh.read()).decode("ascii")
            os.unlink(path)
        except Exception:
            return
        iw = int(ref.tk.call("image", "width", img_name))
        ih = int(ref.tk.call("image", "height", img_name))
        ix = x + (w - iw) / 2
        iy = y + (h - ih) / 2
        self._body.append(
            f'<image x="{_f(ix)}" y="{_f(iy)}" width="{iw}" height="{ih}" '
            f'xlink:href="data:image/png;base64,{b64}"/>')

    # ── Matplotlib ─────────────────────────────────────────────

    def add_figure(self, fig, box) -> bool:
        """Re-renderiza a Figure pelo backend SVG e aninha o resultado."""
        x, y, w, h = box
        buf = io.StringIO()
        fc = self.plot_facecolor or fig.get_facecolor()
        try:
            fig.savefig(buf, format="svg", facecolor=fc, edgecolor="none",
                        transparent=False)
        except Exception:
            return False

        svg = _strip_svg_preamble(buf.getvalue())
        svg = _prefix_svg_ids(svg, self._next_id("mpl") + "-")

        m = re.search(r'viewBox="([^"]+)"', svg)
        view = f' viewBox="{m.group(1)}"' if m else ""
        inner = svg[svg.index(">", svg.index("<svg")) + 1:]
        inner = inner[:inner.rindex("</svg>")]

        self._body.append(
            f'<svg x="{_f(x)}" y="{_f(y)}" width="{_f(w)}" height="{_f(h)}"'
            f'{view} preserveAspectRatio="none" overflow="hidden">'
            f"{inner}</svg>")
        return True

    # ── despacho por classe de widget ──────────────────────────

    def emit(self, w: tk.Misc, clip: Optional[str] = None):
        if str(w) in self.skip:
            return
        try:
            if not w.winfo_ismapped() and w is not self.top:
                return
        except tk.TclError:
            return

        box = self.rect_of(w)
        cls = self._cls(w)
        handler = getattr(self, f"_do_{cls.lower()}", None)

        opened_group = False
        if clip:
            self._body.append(f'<g clip-path="url(#{clip})">')
            opened_group = True

        if handler is not None:
            handler(w, box)
        else:
            self._do_generic(w, box)

        # Canvas: recorta os filhos ao retângulo do canvas (scroll!)
        child_clip = None
        if cls == "Canvas" and str(w) not in self.figures:
            cid = self._next_id("clip")
            x, y, cw, ch = box
            self._defs.append(
                f'<clipPath id="{cid}"><rect x="{_f(x)}" y="{_f(y)}" '
                f'width="{_f(cw)}" height="{_f(ch)}"/></clipPath>')
            child_clip = cid

        for child in w.winfo_children():
            self.emit(child, clip=child_clip)

        if opened_group:
            self._body.append("</g>")

    # -- containers ---------------------------------------------

    def _bg_of(self, w) -> Optional[str]:
        if isinstance(w, ttk.Widget):
            return self.rgb(self.lookup(w, "background"), w)
        return self.rgb(self.cget(w, "background"), w)

    def _do_generic(self, w, box):
        self.add_rect(*box, fill=self._bg_of(w))

    def _do_toplevel(self, w, box):
        self.add_rect(0, 0, self.W, self.H,
                      fill=self.rgb(self.cget(w, "background"), w))

    _do_tk = _do_toplevel

    def _do_tframe(self, w, box):
        self.add_rect(*box, fill=self.rgb(self.lookup(w, "background"), w))

    def _do_frame(self, w, box):
        """tk.Frame — respeita highlightthickness (usado nos banners)."""
        x, y, bw, bh = box
        bg = self.rgb(self.cget(w, "background"), w)
        ht = int(self.cget(w, "highlightthickness", 0) or 0)
        self.add_rect(x, y, bw, bh, fill=bg)
        if ht > 0:
            hc = self.rgb(self.cget(w, "highlightbackground"), w)
            if hc:
                self.add_rect(x, y, bw, bh, stroke=hc, sw=ht)

    def _do_tlabelframe(self, w, box):
        """Card: borda + rótulo. No clam o rótulo fica ACIMA da borda
        (labeloutside=true), por isso medimos a altura da fonte do
        sub-estilo `.Label` e recuamos o topo do retângulo."""
        x, y, bw, bh = box
        st = self.style_name(w)
        bg = self.rgb(self.style.lookup(st, "background"), w)
        bc = self.rgb(self.style.lookup(st, "bordercolor"), w)
        border_w = self.clam_border(st)

        text = self.text_of(w)
        lstyle = f"{st}.Label"
        lf = self.font(self.style.lookup(lstyle, "font")
                       or "TkDefaultFont", w)
        lh = lf.metrics("linespace") if text else 0

        # margem inferior do rótulo (clam: '0 0 0 4')
        margins = str(self.style.lookup(st, "labelmargins") or "0 0 0 4").split()
        try:
            mb = int(margins[3]) if len(margins) >= 4 else 4
        except ValueError:
            mb = 4

        top = y + lh + mb if text else y
        self.add_rect(x, top, bw, bh - (top - y), fill=bg,
                      stroke=bc, sw=border_w)

        if text:
            lfg = self.rgb(self.style.lookup(lstyle, "foreground")
                           or "black", w)
            lbg = self.rgb(self.style.lookup(lstyle, "background"), w)
            pad = str(self.style.lookup(lstyle, "padding") or "0 0").split()
            try:
                px_ = int(pad[0])
            except (ValueError, IndexError):
                px_ = 0
            tw = lf.measure(text)
            if lbg:
                self.add_rect(x, y, tw + 2 * px_, lh, fill=lbg)
            self.add_text(text, (x + px_, y, tw, lh), lf, lfg, anchor="w")

    # -- textos --------------------------------------------------

    def _label_common(self, w, box, *, ttk_widget: bool):
        if ttk_widget:
            bg = self.rgb(self.lookup(w, "background"), w)
            fg = self.rgb(self.lookup(w, "foreground", "black"), w)
            fnt = self.font(self.lookup(w, "font", "TkDefaultFont"), w)
            default_anchor = "w"
        else:
            bg = self.rgb(self.cget(w, "background"), w)
            fg = self.rgb(self.cget(w, "foreground", "black"), w)
            fnt = self.font(self.cget(w, "font", "TkDefaultFont"), w)
            default_anchor = "center"

        self.add_rect(*box, fill=bg)

        anchor = self.cget(w, "anchor") or self.lookup(w, "anchor") \
            or default_anchor
        justify = self.cget(w, "justify", "left")
        wl = int(self.cget(w, "wraplength", 0) or 0)
        padx = int(self.cget(w, "padx", 0) or 0)
        pady = int(self.cget(w, "pady", 0) or 0)
        bd = int(self.cget(w, "borderwidth", 0) or 0) + \
            int(self.cget(w, "highlightthickness", 0) or 0)

        x, y, bw, bh = box
        self.add_text(self.text_of(w),
                      (x + bd, y + bd, bw - 2 * bd, bh - 2 * bd),
                      fnt, fg, anchor=str(anchor), justify=str(justify),
                      wraplength=wl, padx=padx, pady=pady)

    def _do_tlabel(self, w, box):
        self._label_common(w, box, ttk_widget=True)

    def _do_label(self, w, box):
        self._label_common(w, box, ttk_widget=False)

    # -- botões --------------------------------------------------

    def _do_tbutton(self, w, box):
        st = self.style_name(w)
        disabled = w.instate(["disabled"])
        state = ["disabled"] if disabled else ["!disabled"]

        bg = self.rgb(self.style.lookup(st, "background", state) or
                      self.style.lookup(st, "background"), w)
        fg = self.rgb(self.style.lookup(st, "foreground", state) or
                      self.style.lookup(st, "foreground") or "black", w)
        bc = self.rgb(self.style.lookup(st, "bordercolor", state) or
                      self.style.lookup(st, "bordercolor"), w)
        bw_ = self.clam_border(st)
        fnt = self.font(self.style.lookup(st, "font") or "TkDefaultFont", w)

        self.add_rect(*box, fill=bg,
                      stroke=bc if bw_ > 0 else None, sw=bw_ or 1)
        self.add_text(self.text_of(w), box, fnt, fg, anchor="center",
                      justify="center")

    def _do_button(self, w, box):
        """tk.Button — usado pela toolbar do Matplotlib e pelos botões
        coloridos do construtor de sinais do FIR."""
        bg = self.rgb(self.cget(w, "background"), w)
        fg = self.rgb(self.cget(w, "foreground", "black"), w)
        bd = int(self.cget(w, "borderwidth", 1) or 0)
        relief = str(self.cget(w, "relief", "raised"))
        stroke = self.rgb(self.cget(w, "highlightbackground"), w) \
            if relief in ("solid", "ridge", "groove") else None
        self.add_rect(*box, fill=bg, stroke=stroke, sw=max(1, bd))
        img = self.cget(w, "image", "")
        if img:
            self.add_image(str(img), box, w)
        else:
            fnt = self.font(self.cget(w, "font", "TkDefaultFont"), w)
            self.add_text(self.text_of(w), box, fnt, fg, anchor="center",
                          justify="center")

    def _do_checkbutton(self, w, box):
        """tk.Checkbutton — os botões Pan/Zoom da toolbar do Matplotlib
        são deste tipo: carregam ícone e não têm indicador."""
        self.add_rect(*box, fill=self.rgb(self.cget(w, "background"), w))
        img = self.cget(w, "image", "")
        if img:
            self.add_image(str(img), box, w)
            return
        fg = self.rgb(self.cget(w, "foreground", "black"), w)
        fnt = self.font(self.cget(w, "font", "TkDefaultFont"), w)
        x, y, bw, bh = box
        ix, iy, isz, _ = self._indicator_box(box)
        self.add_rect(ix, iy, isz, isz, fill=self.CLAM_FIELD,
                      stroke=self.CLAM_BORDER, sw=1)
        tx = ix + isz + 6
        self.add_text(self.text_of(w), (tx, y, bw - (tx - x), bh),
                      fnt, fg, anchor="w")

    # -- campos --------------------------------------------------

    def _field(self, w, box, *, arrow=False):
        """Entry/Combobox do clam: campo + moldura de 2 px (1 px de
        `bordercolor` por fora, 1 px de `lightcolor` por dentro)."""
        st = self.style_name(w)
        fieldbg = self.rgb(self.style.lookup(st, "fieldbackground")
                           or self.CLAM_FIELD, w)
        bc = self.rgb(self.style.lookup(st, "bordercolor")
                      or self.CLAM_BORDER, w)
        lc = self.rgb(self.style.lookup(st, "lightcolor") or "#eeebe7", w)
        fg = self.rgb(self.style.lookup(st, "foreground") or "black", w)
        fnt = self.font(self.style.lookup(st, "font") or "TkDefaultFont", w)

        # readonly/disabled: o clam usa o `background` no lugar do campo
        if w.instate(["readonly"]) or w.instate(["disabled"]):
            fieldbg = self.rgb(self.style.lookup(st, "background")
                               or "#dcdad5", w)

        x, y, bw, bh = box
        self.add_rect(x, y, bw, bh, fill=fieldbg)
        self.add_rect(x, y, bw, bh, stroke=bc, sw=1)
        self.add_rect(x + 1, y + 1, bw - 2, bh - 2, stroke=lc, sw=1)

        try:
            txt = w.get()
        except tk.TclError:
            txt = ""

        aw = 17 if arrow else 0
        self.add_text(str(txt), (x + 5, y, bw - 10 - aw, bh), fnt, fg,
                      anchor="w")

        if arrow:
            sx = x + bw - aw           # separador vertical do botão da seta
            self.add_rect(sx, y + 2, 1, bh - 4, fill=bc)
            ax = sx + aw / 2
            ay = y + bh / 2
            self._body.append(
                f'<path d="M {_f(ax - 3.5)} {_f(ay - 1.5)} '
                f'L {_f(ax + 3.5)} {_f(ay - 1.5)} L {_f(ax)} {_f(ay + 2.5)} Z" '
                f'fill="#000000"/>')

    def _do_tentry(self, w, box):
        self._field(w, box)

    def _do_tcombobox(self, w, box):
        self._field(w, box, arrow=True)

    # -- check / radio -------------------------------------------

    def _indicator_box(self, box, size=12):
        x, y, bw, bh = box
        return x + 2, y + (bh - size) / 2, size, size

    def _do_tcheckbutton(self, w, box):
        st = self.style_name(w)
        bg = self.rgb(self.style.lookup(st, "background"), w)
        fg = self.rgb(self.style.lookup(st, "foreground") or "black", w)
        fnt = self.font(self.style.lookup(st, "font") or "TkDefaultFont", w)
        self.add_rect(*box, fill=bg)

        ix, iy, isz, _ = self._indicator_box(box)
        # `alternate` = variável Tk não inicializada; o clam pinta o
        # indicador de azul (tristate) em vez de deixá-lo vazio.
        inner = "#5895bc" if w.instate(["alternate"]) else self.CLAM_FIELD
        self.add_rect(ix, iy, isz, isz, fill=inner,
                      stroke=self.CLAM_BORDER, sw=1)
        if w.instate(["selected"]):
            self._body.append(
                f'<path d="M {_f(ix + 2.5)} {_f(iy + 6)} '
                f'L {_f(ix + 5)} {_f(iy + 9)} '
                f'L {_f(ix + 9.5)} {_f(iy + 3)}" fill="none" '
                f'stroke="{fg}" stroke-width="1.8" stroke-linecap="round" '
                f'stroke-linejoin="round"/>')

        x, y, bw, bh = box
        tx = ix + isz + 6
        self.add_text(self.text_of(w), (tx, y, bw - (tx - x), bh),
                      fnt, fg, anchor="w")

    def _do_tradiobutton(self, w, box):
        st = self.style_name(w)
        bg = self.rgb(self.style.lookup(st, "background"), w)
        fg = self.rgb(self.style.lookup(st, "foreground") or "black", w)
        fnt = self.font(self.style.lookup(st, "font") or "TkDefaultFont", w)
        self.add_rect(*box, fill=bg)

        ix, iy, isz, _ = self._indicator_box(box)
        cx, cy, r = ix + isz / 2, iy + isz / 2, isz / 2
        self._body.append(
            f'<circle cx="{_f(cx)}" cy="{_f(cy)}" r="{_f(r)}" '
            f'fill="{self.CLAM_FIELD}" stroke="{self.CLAM_BORDER}" '
            f'stroke-width="1"/>')
        if w.instate(["selected"]):
            self._body.append(
                f'<circle cx="{_f(cx)}" cy="{_f(cy)}" r="{_f(r - 3.5)}" '
                f'fill="{fg}"/>')

        x, y, bw, bh = box
        tx = ix + isz + 6
        self.add_text(self.text_of(w), (tx, y, bw - (tx - x), bh),
                      fnt, fg, anchor="w")

    # -- barras --------------------------------------------------

    def _do_tprogressbar(self, w, box):
        st = self.style_name(w)
        trough = self.rgb(self.style.lookup(st, "troughcolor") or "#bab5ab", w)
        barc = self.rgb(self.style.lookup(st, "background") or "#dcdad5", w)
        bc = self.rgb(self.style.lookup(st, "bordercolor") or self.CLAM_BORDER, w)
        x, y, bw, bh = box
        self.add_rect(x, y, bw, bh, fill=trough, stroke=bc, sw=1)
        try:
            val = float(w.cget("value") or 0)
            mx = float(w.cget("maximum") or 100)
        except (tk.TclError, ValueError):
            val, mx = 0.0, 100.0
        if mx > 0 and val > 0:
            frac = max(0.0, min(1.0, val / mx))
            self.add_rect(x + 1, y + 1, (bw - 2) * frac, bh - 2, fill=barc)

    def _do_tscrollbar(self, w, box):
        st = self.style_name(w)
        trough = self.rgb(self.style.lookup(st, "troughcolor") or "#bab5ab", w)
        thumb = self.rgb(self.style.lookup(st, "background") or "#dcdad5", w)
        bc = self.rgb(self.style.lookup(st, "bordercolor") or self.CLAM_BORDER, w)
        x, y, bw, bh = box
        self.add_rect(x, y, bw, bh, fill=trough, stroke=bc, sw=1)
        try:
            first, last = (float(v) for v in w.get())
        except (tk.TclError, ValueError, TypeError):
            first, last = 0.0, 1.0
        vertical = str(self.cget(w, "orient", "vertical")) == "vertical"
        if vertical:
            self.add_rect(x + 1, y + bh * first, bw - 2,
                          bh * (last - first), fill=thumb, stroke=bc, sw=1)
        else:
            self.add_rect(x + bw * first, y + 1, bw * (last - first),
                          bh - 2, fill=thumb, stroke=bc, sw=1)

    # -- treeview ------------------------------------------------

    def _do_treeview(self, w, box):
        st = self.style_name(w)
        bg = self.rgb(self.style.lookup(st, "fieldbackground")
                      or self.style.lookup(st, "background") or "#ffffff", w)
        fg = self.rgb(self.style.lookup(st, "foreground") or "black", w)
        fnt = self.font(self.style.lookup(st, "font") or "TkDefaultFont", w)
        hbg = self.rgb(self.style.lookup(f"{st}.Heading", "background")
                       or "#dcdad5", w)
        hfg = self.rgb(self.style.lookup(f"{st}.Heading", "foreground")
                       or "black", w)
        hfnt = self.font(self.style.lookup(f"{st}.Heading", "font")
                         or "TkHeadingFont", w)

        x, y, bw, bh = box
        self.add_rect(x, y, bw, bh, fill=bg, stroke=self.CLAM_BORDER, sw=1)

        cols = list(w.cget("columns") or ())
        items = w.get_children()

        # A altura do cabeçalho sai do bbox da primeira linha; sem linhas,
        # estima-se pela fonte.
        head_h = hfnt.metrics("linespace") + 8
        if items:
            bb = w.bbox(items[0])
            if bb:
                head_h = bb[1] - 0  # y da primeira linha (relativo ao widget)

        self.add_rect(x, y, bw, head_h, fill=hbg, stroke=self.CLAM_BORDER, sw=1)

        cx = x
        for col in cols:
            try:
                cw = int(w.column(col, "width"))
                title = str(w.heading(col, "text"))
            except tk.TclError:
                continue
            self.add_rect(cx, y, cw, head_h, stroke=self.CLAM_BORDER, sw=1)
            self.add_text(title, (cx + 6, y, cw - 12, head_h), hfnt, hfg,
                          anchor="w")
            cx += cw

        row_h = fnt.metrics("linespace") + 4
        for i, item in enumerate(items):
            bb = w.bbox(item)
            ry = (y + bb[1]) if bb else (y + head_h + i * row_h)
            rh = bb[3] if bb else row_h
            vals = w.item(item, "values") or ()
            cx = x
            for j, col in enumerate(cols):
                try:
                    cw = int(w.column(col, "width"))
                    anch = str(w.column(col, "anchor") or "w")
                except tk.TclError:
                    continue
                if j < len(vals):
                    self.add_text(str(vals[j]), (cx + 6, ry, cw - 12, rh),
                                  fnt, fg, anchor=anch)
                cx += cw

    # -- canvas --------------------------------------------------

    def _do_canvas(self, w, box):
        key = str(w)
        if key in self.figures:
            if self.add_figure(self.figures[key], box):
                return
        # Canvas comum
        self.add_rect(*box, fill=self.rgb(self.cget(w, "background"), w))
        self._canvas_items(w, box)

    def _canvas_items(self, w: tk.Canvas, box):
        x0, y0, _, _ = box
        try:
            items = w.find_all()
        except tk.TclError:
            return
        def opt(item, name, default=None):
            """itemcget tolerante: cada tipo de item aceita opções distintas
            (um item `window`, por exemplo, não tem -fill)."""
            try:
                v = w.itemcget(item, name)
            except tk.TclError:
                return default
            return v if v not in ("", None) else default

        for it in items:
            typ = w.type(it)
            # itens `window` embutem um widget de verdade, que já é filho do
            # canvas e será desenhado pelo caminhamento normal da árvore.
            if typ == "window":
                continue
            try:
                coords = [float(c) for c in w.coords(it)]
            except (tk.TclError, ValueError):
                continue
            # o canvas pode estar rolado: converte coords do canvas p/ tela
            pts = [(x0 + coords[i] - w.canvasx(0),
                    y0 + coords[i + 1] - w.canvasy(0))
                   for i in range(0, len(coords) - 1, 2)]

            fill = self.rgb(opt(it, "fill"), w)
            outline = self.rgb(opt(it, "outline"), w)
            try:
                width = float(opt(it, "width", 1) or 1)
            except (TypeError, ValueError):
                width = 1.0

            if typ in ("rectangle", "oval") and len(pts) >= 2:
                (ax, ay), (bx, by) = pts[0], pts[1]
                if typ == "rectangle":
                    self.add_rect(ax, ay, bx - ax, by - ay,
                                  fill=fill, stroke=outline, sw=width)
                else:
                    self._body.append(
                        f'<ellipse cx="{_f((ax + bx) / 2)}" '
                        f'cy="{_f((ay + by) / 2)}" rx="{_f(abs(bx - ax) / 2)}" '
                        f'ry="{_f(abs(by - ay) / 2)}" '
                        f'fill="{fill or "none"}" '
                        f'stroke="{outline or "none"}" '
                        f'stroke-width="{_f(width)}"/>')
            elif typ == "line" and len(pts) >= 2:
                d = " ".join(f"{_f(px)},{_f(py)}" for px, py in pts)
                self._body.append(
                    f'<polyline points="{d}" fill="none" '
                    f'stroke="{fill or "black"}" stroke-width="{_f(width)}"/>')
            elif typ == "polygon" and len(pts) >= 3:
                d = " ".join(f"{_f(px)},{_f(py)}" for px, py in pts)
                self._body.append(
                    f'<polygon points="{d}" fill="{fill or "none"}" '
                    f'stroke="{outline or "none"}" '
                    f'stroke-width="{_f(width)}"/>')
            elif typ == "text" and pts:
                txt = opt(it, "text", "")
                fnt = self.font(opt(it, "font", "TkDefaultFont"), w)
                va, ha = self.parse_anchor(opt(it, "anchor", "center"))
                tw = fnt.measure(txt)
                th = fnt.metrics("linespace")
                px_, py_ = pts[0]
                # a âncora diz onde o PONTO fica em relação ao texto
                bx = px_ if ha == "w" else (px_ - tw if ha == "e"
                                            else px_ - tw / 2)
                by = py_ if va == "n" else (py_ - th if va == "s"
                                            else py_ - th / 2)
                self.add_text(txt, (bx, by, tw, th), fnt,
                              fill or "#000000", anchor="w")
            elif typ == "image" and pts:
                img = opt(it, "image")
                if img:
                    iw = int(w.tk.call("image", "width", img))
                    ih = int(w.tk.call("image", "height", img))
                    self.add_image(img, (pts[0][0], pts[0][1], iw, ih), w)

    # ── saída ──────────────────────────────────────────────────

    def to_svg(self, scale: float = 1.0) -> str:
        self.emit(self.top)
        W, H = self.W * scale, self.H * scale
        defs = ("<defs>" + "".join(self._defs) + "</defs>") if self._defs else ""
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="{_f(W)}" height="{_f(H)}" '
            f'viewBox="0 0 {_f(self.W)} {_f(self.H)}">\n'
            f'{defs}\n' + "\n".join(self._body) + "\n</svg>\n")


# ══════════════════════════════════════════════════════════════════
# API pública
# ══════════════════════════════════════════════════════════════════

def export_window(win: tk.Misc, path: str, *,
                  scale: float = 1.0,
                  figures: Optional[Dict[str, object]] = None,
                  embed_images: bool = True,
                  plot_facecolor: Optional[str] = None,
                  skip: Sequence[tk.Misc] = ()) -> str:
    """Exporta uma janela Tk viva para SVG vetorial.

    Parameters
    ----------
    win : tk.Tk | tk.Toplevel
        Janela já construída e mapeada. Chame ``win.update_idletasks()``
        (ou ``update()``) antes, para que o Tk tenha calculado a geometria.
    path : str
        Caminho do .svg de saída.
    scale : float
        Apenas os atributos width/height do SVG. O viewBox continua em
        pixels lógicos, então o desenho é idêntico — útil só para quem
        rasteriza sem passar um zoom.
    figures : dict, optional
        Mapa {str(widget_tk): Figure}. Por padrão é descoberto sozinho.
    embed_images : bool
        Embute PhotoImages (ícones da toolbar do Matplotlib) como PNG.
    plot_facecolor : str, optional
        Sobrescreve o fundo das Figures — passe ``"white"`` para figuras
        de artigo impresso.
    skip : sequência de widgets
        Widgets (e suas subárvores) a omitir — ex.: a toolbar do
        Matplotlib, que raramente interessa numa figura de artigo.

    Returns
    -------
    str : o caminho escrito.
    """
    win.update_idletasks()
    exp = SvgExporter(win, figures=figures, embed_images=embed_images,
                      plot_facecolor=plot_facecolor, skip=skip)
    svg = exp.to_svg(scale=scale)
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(svg)
    return path
