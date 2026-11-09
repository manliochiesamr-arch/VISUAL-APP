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


def render(text, pos="tl", size=2, screen_aspect=4 / 3, color=(1.0, 1.0, 1.0)):
    """Lienzo RGBA float32 (alto, ancho, 4) con el texto. None si no hay texto."""
    text = normalize(expand(text or "")).strip("\n")
    if not text.strip():
        return None
    W, H = canvas_size(screen_aspect)
    img = np.zeros((H, W, 4), np.float32)
    lines = text.split("\n")
    s = max(1, min(4, int(size)))
    cw, ch, gap = 6 * s, 9 * s, s            # ancho de letra con espacio, alto de linea
    tw = max(len(l) for l in lines) * cw - s
    th = len(lines) * ch - 2 * s
    m = 12
    x0 = {"tl": m, "bl": m, "c": (W - tw) // 2, "tr": W - m - tw, "br": W - m - tw}.get(pos, m)
    y0 = {"tl": m, "tr": m, "c": (H - th) // 2, "bl": H - m - th, "br": H - m - th}.get(pos, m)
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
