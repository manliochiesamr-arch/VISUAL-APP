"""Visuales generativos: imagenes calculadas en vivo, sin archivo de video.

Cada generador dibuja un cuadro chico (W x H) con numpy; el render lo escala a pantalla
como cualquier clip (el suavizado queda muy bien en una TV de tubo). Todos reciben:
  t      tiempo del clip en segundos (afectado por la velocidad del clip)
  beats  beats transcurridos (para latir con el BPM)
  hue    corrimiento de color 0..1      detail  complejidad 0..1
"""
import math

import numpy as np

W, H = 192, 108
_y, _x = np.mgrid[0:H, 0:W].astype(np.float32)
X = (_x - W / 2) / (H / 2)          # -1.8..1.8 (16:9), y -1..1
Y = (_y - H / 2) / (H / 2)
R = np.sqrt(X * X + Y * Y) + 1e-4
A = np.arctan2(Y, X)
TAU = np.float32(2 * math.pi)
_PH = np.array([0.0, 0.33, 0.67], np.float32)


def palette(v, hue):
    """v (HxW, cualquier rango) -> RGB 0..1 con paleta coseno ciclica."""
    return 0.5 + 0.5 * np.cos(TAU * (v[..., None] + hue + _PH))


def pulse(beats, sharp=6.0):
    """1 justo en el beat y cae rapido hasta el siguiente."""
    return math.exp(-sharp * (beats % 1.0))


def plasma(t, beats, hue, detail):
    k = 2 + 6 * detail
    v = (np.sin(X * k + t) + np.sin(Y * k * 0.8 - t * 1.3) +
         np.sin((X + Y) * k * 0.6 + t * 0.7) + np.sin(R * k * 1.4 - t * 2.0)) / 8
    return palette(v + t * 0.05, hue) * (0.75 + 0.25 * pulse(beats))


def tunel(t, beats, hue, detail):
    z = 1.0 / R + t * 1.5 + beats * 0.25
    seg = 4 + int(detail * 12)
    v = np.sin(z * 4) * np.sin(A * seg + t)
    rings = 0.5 + 0.5 * np.sign(v)
    col = palette(z * 0.1, hue) * rings[..., None]
    return col * np.clip(R * 1.4, 0, 1)[..., None] * (0.7 + 0.3 * pulse(beats))


def caleidoscopio(t, beats, hue, detail):
    n = 3 + int(detail * 9)
    a = np.abs(((A + t * 0.2) % (TAU / n)) - math.pi / n)
    px, py = R * np.cos(a), R * np.sin(a)
    v = np.sin(px * 6 - t * 2) * np.cos(py * 9 + t) + np.sin(R * 8 - beats * TAU * 0.5) * 0.5
    return palette(v * 0.4 + R * 0.2, hue) * (0.6 + 0.4 * pulse(beats))


def barras(t, beats, hue, detail):
    n = 4 + int(detail * 20)
    v = ((_x / W) * n + t * 2) % 1.0
    on = (v < 0.5).astype(np.float32)
    idx = np.floor((_x / W) * n + t * 2)
    col = palette(idx * 0.13 + beats * 0.25, hue) * on[..., None]
    return col * (0.4 + 0.6 * pulse(beats, 4))


def circulos(t, beats, hue, detail):
    k = 4 + detail * 16
    v = (R * k - beats * 2) % 2.0
    on = np.clip(1.0 - np.abs(v - 1.0) * 3, 0, 1)
    return palette(np.floor(R * k - beats * 2) * 0.1, hue) * on[..., None]


def rejilla(t, beats, hue, detail):
    n = 3 + int(detail * 13)
    b = int(beats) % 2
    cx = np.floor((X + t * 0.1) * n) + np.floor(Y * n)
    on = ((cx + b) % 2 == 0).astype(np.float32)
    return palette(np.full_like(X, beats * 0.125), hue) * on[..., None] * (0.5 + 0.5 * pulse(beats))


def espiral(t, beats, hue, detail):
    arms = 1 + int(detail * 7)
    v = np.sin(A * arms + np.log(R) * 6 - t * 3)
    on = np.clip(v * 3, 0, 1)
    return palette(np.log(R) * 0.3 - t * 0.1, hue) * on[..., None] * (0.7 + 0.3 * pulse(beats))


_rng = np.random.default_rng()


def estatica(t, beats, hue, detail):
    n = _rng.random((H, W), dtype=np.float32)
    lines = 0.85 + 0.15 * np.sin(_y * 0.8 + t * 40)
    v = n * lines * (0.6 + 0.4 * pulse(beats, 3))
    tint = palette(np.full((H, W), 0.0, np.float32), hue)
    return v[..., None] * (1 - detail + detail * tint)


GENERATORS = {
    "plasma": ("Plasma", plasma),
    "tunel": ("Túnel", tunel),
    "caleidoscopio": ("Caleidoscopio", caleidoscopio),
    "barras": ("Barras", barras),
    "circulos": ("Círculos", circulos),
    "rejilla": ("Rejilla", rejilla),
    "espiral": ("Espiral", espiral),
    "estatica": ("Estática TV", estatica),
}


def render(name, t, beats, hue=0.0, detail=0.5):
    """Cuadro RGB (bytes, W*H*3) del generador."""
    f = GENERATORS[name][1]
    img = f(np.float32(t), float(beats), np.float32(hue), float(detail))
    return (np.clip(img, 0, 1) * 255).astype(np.uint8).tobytes()
