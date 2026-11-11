"""Texto en pantalla estilo videocasetera (OSD): letra pixelada 5x7 en mayusculas, blanca con sombra.

El texto se dibuja en un lienzo chico (RGBA) que el render pone encima de la mezcla,
escalado sin suavizar para que se vean los pixeles como en un VHS.
"""
import time
import unicodedata

import numpy as np

# 5x7: cada letra son 7 filas de 5 columnas ('#' = pixel encendido)
_FONT_SRC = {
    'A': [' ### ', '#   #', '#   #', '#####', '#   #', '#   #', '#   #'],
    'B': ['#### ', '#   #', '#   #', '#### ', '#   #', '#   #', '#### '],
    'C': [' ### ', '#   #', '#    ', '#    ', '#    ', '#   #', ' ### '],
    'D': ['#### ', '#   #', '#   #', '#   #', '#   #', '#   #', '#### '],
    'E': ['#####', '#    ', '#    ', '#### ', '#    ', '#    ', '#####'],
    'F': ['#####', '#    ', '#    ', '#### ', '#    ', '#    ', '#    '],
    'G': [' ### ', '#   #', '#    ', '# ###', '#   #', '#   #', ' ####'],
    'H': ['#   #', '#   #', '#   #', '#####', '#   #', '#   #', '#   #'],
    'I': [' ### ', '  #  ', '  #  ', '  #  ', '  #  ', '  #  ', ' ### '],
    'J': ['  ###', '   # ', '   # ', '   # ', '   # ', '#  # ', ' ##  '],
    'K': ['#   #', '#  # ', '# #  ', '##   ', '# #  ', '#  # ', '#   #'],
    'L': ['#    ', '#    ', '#    ', '#    ', '#    ', '#    ', '#####'],
    'M': ['#   #', '## ##', '# # #', '#   #', '#   #', '#   #', '#   #'],
    'N': ['#   #', '##  #', '# # #', '#  ##', '#   #', '#   #', '#   #'],
    'Ñ': [' ### ', '     ', '##  #', '# # #', '#  ##', '#   #', '#   #'],
    'O': [' ### ', '#   #', '#   #', '#   #', '#   #', '#   #', ' ### '],
    'P': ['#### ', '#   #', '#   #', '#### ', '#    ', '#    ', '#    '],
    'Q': [' ### ', '#   #', '#   #', '#   #', '# # #', '#  # ', ' ## #'],
    'R': ['#### ', '#   #', '#   #', '#### ', '# #  ', '#  # ', '#   #'],
    'S': [' ####', '#    ', '#    ', ' ### ', '    #', '    #', '#### '],
    'T': ['#####', '  #  ', '  #  ', '  #  ', '  #  ', '  #  ', '  #  '],
    'U': ['#   #', '#   #', '#   #', '#   #', '#   #', '#   #', ' ### '],
    'V': ['#   #', '#   #', '#   #', '#   #', '#   #', ' # # ', '  #  '],
    'W': ['#   #', '#   #', '#   #', '# # #', '# # #', '# # #', ' # # '],
    'X': ['#   #', '#   #', ' # # ', '  #  ', ' # # ', '#   #', '#   #'],
    'Y': ['#   #', '#   #', ' # # ', '  #  ', '  #  ', '  #  ', '  #  '],
    'Z': ['#####', '    #', '   # ', '  #  ', ' #   ', '#    ', '#####'],
    '0': [' ### ', '#   #', '#  ##', '# # #', '##  #', '#   #', ' ### '],
    '1': ['  #  ', ' ##  ', '  #  ', '  #  ', '  #  ', '  #  ', ' ### '],
    '2': [' ### ', '#   #', '    #', '   # ', '  #  ', ' #   ', '#####'],
    '3': ['#####', '   # ', '  #  ', '   # ', '    #', '#   #', ' ### '],
    '4': ['   # ', '  ## ', ' # # ', '#  # ', '#####', '   # ', '   # '],
    '5': ['#####', '#    ', '#### ', '    #', '    #', '#   #', ' ### '],
    '6': ['  ## ', ' #   ', '#    ', '#### ', '#   #', '#   #', ' ### '],
    '7': ['#####', '    #', '   # ', '  #  ', ' #   ', ' #   ', ' #   '],
    '8': [' ### ', '#   #', '#   #', ' ### ', '#   #', '#   #', ' ### '],
    '9': [' ### ', '#   #', '#   #', ' ####', '    #', '   # ', ' ##  '],
    ' ': ['     ', '     ', '     ', '     ', '     ', '     ', '     '],
    '.': ['     ', '     ', '     ', '     ', '     ', ' ##  ', ' ##  '],
    ',': ['     ', '     ', '     ', '     ', ' ##  ', '  #  ', ' #   '],
    ':': ['     ', ' ##  ', ' ##  ', '     ', ' ##  ', ' ##  ', '     '],
    '-': ['     ', '     ', '     ', '#####', '     ', '     ', '     '],
    '!': ['  #  ', '  #  ', '  #  ', '  #  ', '  #  ', '     ', '  #  '],
    '?': [' ### ', '#   #', '    #', '   # ', '  #  ', '     ', '  #  '],
    '/': ['    #', '    #', '   # ', '  #  ', ' #   ', '#    ', '#    '],
    "'": ['  #  ', '  #  ', ' #   ', '     ', '     ', '     ', '     '],
    '+': ['     ', '  #  ', '  #  ', '#####', '  #  ', '  #  ', '     '],
    '=': ['     ', '     ', '#####', '     ', '#####', '     ', '     '],
    '(': ['   # ', '  #  ', ' #   ', ' #   ', ' #   ', '  #  ', '   # '],
    ')': [' #   ', '  #  ', '   # ', '   # ', '   # ', '  #  ', ' #   '],
    '#': [' # # ', ' # # ', '#####', ' # # ', '#####', ' # # ', ' # # '],
    '%': ['##   ', '##  #', '   # ', '  #  ', ' #   ', '#  ##', '   ##'],
    '*': ['     ', '# # #', ' ### ', '#####', ' ### ', '# # #', '     '],
    '_': ['     ', '     ', '     ', '     ', '     ', '     ', '#####'],
    '▶': ['#    ', '##   ', '###  ', '#### ', '###  ', '##   ', '#    '],
    '◀': ['    #', '   ##', '  ###', ' ####', '  ###', '   ##', '    #'],
    '●': ['     ', ' ### ', '#####', '#####', '#####', ' ### ', '     '],
    '■': ['     ', '#####', '#####', '#####', '#####', '#####', '     '],
    '❚': ['## ##', '## ##', '## ##', '## ##', '## ##', '## ##', '## ##'],
    '[': [' ### ', ' #   ', ' #   ', ' #   ', ' #   ', ' #   ', ' ### '],
    ']': [' ### ', '   # ', '   # ', '   # ', '   # ', '   # ', ' ### '],
    ';': ['     ', ' ##  ', ' ##  ', '     ', ' ##  ', '  #  ', ' #   '],
    '>': [' #   ', '  #  ', '   # ', '    #', '   # ', '  #  ', ' #   '],
    '<': ['   # ', '  #  ', ' #   ', '#    ', ' #   ', '  #  ', '   # '],
    '&': [' ##  ', '#  # ', '# #  ', ' #   ', '# # #', '#  # ', ' ## #'],
    '|': ['  #  ', '  #  ', '  #  ', '  #  ', '  #  ', '  #  ', '  #  '],
    '"': [' # # ', ' # # ', '     ', '     ', '     ', '     ', '     '],
}
FONT = {ch: np.array([[c != " " for c in r] for r in rows], bool) for ch, rows in _FONT_SRC.items()}

# atajos que se pueden escribir en el texto
TOKENS = {"{play}": "PLAY ▶", "{rec}": "● REC", "{pause}": "PAUSE ❚", "{stop}": "STOP ■",
          "{ff}": "FF ▶▶", "{rew}": "◀◀ REW"}


def normalize(text):
    for k, v in TOKENS.items():
        text = text.replace(k, v)
    out = []
    for ch in text.upper():
        if ch in FONT or ch == "\n":
            out.append(ch)
            continue
        base = unicodedata.normalize("NFD", ch)[0]  # Á -> A
        out.append(base if base in FONT else "?")
    return "".join(out)


def expand(text, now=None):
    """Reemplaza {hora} y {fecha} por los valores actuales (formato VHS)."""
    now = now or time.localtime()
    h = now.tm_hour
    return (text.replace("{hora}", f"{'AM' if h < 12 else 'PM'} {(h % 12) or 12:2d}:{now.tm_min:02d}")
                .replace("{fecha}", time.strftime("%b. %d %Y", now).upper()))


def canvas_size(screen_aspect):
    return (320, 240) if screen_aspect < 1.5 else (384, 216)


def render_layers(layers, screen_aspect=4 / 3):
    """Varias capas [(texto, lugar, tamano[, color])] en un solo lienzo. None si no hay nada que mostrar."""
    img = None
    for text, pos, size, *more in layers:
        color = more[0] if more and more[0] else (1.0, 1.0, 1.0)
        echo = more[1] if len(more) > 1 and more[1] else None
        img = render(text, pos, size, screen_aspect, color=color, img=img, echo=echo) if text else img
    return img


def _shift(a, dx, dy):
    """Corre un lienzo dx, dy pixeles (lo que sale se pierde, lo que entra es transparente)."""
    out = np.zeros_like(a)
    H, W = a.shape[:2]
    if abs(dx) >= W or abs(dy) >= H:
        return out
    ys, yd = (slice(0, H - dy), slice(dy, H)) if dy >= 0 else (slice(-dy, H), slice(0, H + dy))
    xs, xd = (slice(0, W - dx), slice(dx, W)) if dx >= 0 else (slice(-dx, W), slice(0, W + dx))
    out[yd, xd] = a[ys, xs]
    return out


def _over(dst, src, k=1.0):
    """src encima de dst (RGBA), con opacidad extra k."""
    a = src[..., 3:4] * k
    dst[..., :3] = src[..., :3] * a + dst[..., :3] * (1 - a)
    dst[..., 3:4] = a + dst[..., 3:4] * (1 - a)


def render(text, pos="tl", size=2, screen_aspect=4 / 3, color=(1.0, 1.0, 1.0), img=None, echo=None):
    """Lienzo RGBA float32 (alto, ancho, 4) con el texto. None si no hay texto.
    Con img se dibuja encima de un lienzo existente (capas).
    echo = (copias, x, y): copias corridas detras del texto que se van apagando."""
    if echo and int(echo[0]) > 1:
        layer = render(text, pos, size, screen_aspect, color)
        if layer is None:
            return img
        if img is None:
            img = np.zeros_like(layer)
        n, ex, ey = int(echo[0]), float(echo[1]), float(echo[2])
        s = max(1, min(4, int(size)))
        for i in range(n - 1, 0, -1):  # de la mas lejana a la mas cercana
            dx, dy = int(round(ex * 4 * s * i)), int(round(-ey * 4 * s * i))
            _over(img, _shift(layer, dx, dy), 0.85 * (1 - i / n))
        _over(img, layer)
        return img
    text = normalize(expand(text or "")).strip("\n")
    if not text.strip():
        return img
    W, H = canvas_size(screen_aspect)
    if img is None:
        img = np.zeros((H, W, 4), np.float32)
    lines = text.split("\n")
    s = max(1, min(4, int(size)))
    cw, ch, gap = 6 * s, 9 * s, s            # ancho de letra con espacio, alto de linea
    tw = max(len(l) for l in lines) * cw - s
    th = len(lines) * ch - 2 * s
    m = 12
    col = {"l": m, "c": (W - tw) // 2, "r": W - m - tw}
    row = {"t": m, "c": (H - th) // 2, "b": H - m - th}
    # pos: tl t tr / l c r / bl b br
    p = {"t": "tc", "b": "bc", "l": "cl", "r": "cr", "c": "cc"}.get(pos, pos)
    y0 = row.get(p[0], m)
    x0 = col.get(p[1], m)
    rgb = np.array(color, np.float32)
    for li, line in enumerate(lines):
        for ci, chr_ in enumerate(line):
            g = np.kron(FONT.get(chr_, FONT["?"]), np.ones((s, s), bool))
            x, y = x0 + ci * cw, y0 + li * ch
            for dx, dy, val in ((s, s, None), (0, 0, rgb)):   # primero la sombra, despues la letra
                xa, ya = x + dx, y + dy
                if xa < 0 or ya < 0 or xa + g.shape[1] > W or ya + g.shape[0] > H:
                    continue
                reg = img[ya:ya + g.shape[0], xa:xa + g.shape[1]]
                if val is None:
                    reg[g] = (0.0, 0.0, 0.0, 0.85)
                else:
                    reg[g, :3] = val
                    reg[g, 3] = 1.0
    return img
