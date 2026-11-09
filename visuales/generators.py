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


# ---------- glitch / VHS ----------
_COLS = np.arange(W)[None, :]
_ROWS = np.arange(H)[:, None]


def rng_at(t, fps=25, salt=0):
    """Azar que cambia en cada cuadro pero es repetible para un mismo instante."""
    return np.random.default_rng(int(t * fps) * 7919 + salt)


def shift_rows(img, shifts):
    """Corre cada fila horizontalmente (cortes de cinta / tracking)."""
    idx = (_COLS - np.asarray(shifts, np.int64)[:, None]) % W
    return img[_ROWS, idx]


def chroma(img, dx):
    """Separa los canales de color: R a un lado, B al otro."""
    out = img.copy()
    out[..., 0] = np.roll(img[..., 0], dx, axis=1)
    out[..., 2] = np.roll(img[..., 2], -dx, axis=1)
    return out


def estatica(t, beats, hue, detail):
    """Nieve de TV sin senal con bandas de tracking y cortes horizontales (VHS)."""
    r = rng_at(t)
    n = r.random((H, W), dtype=np.float32)
    n = n * n * 1.2                                     # mas negro que gris, como la nieve real
    row = 0.75 + 0.25 * r.random((H, 1), dtype=np.float32)
    band_y = (t * 18) % (H + 30) - 15                   # banda de tracking que baja
    band = np.exp(-((_y[:, :1] - band_y) / 3.0) ** 2)
    img = np.clip(n * row + band * 0.8 * r.random((H, W), dtype=np.float32), 0, 1)
    tears = np.zeros(H)
    if r.random() < 0.3 + 0.6 * detail:                 # cortes de cinta
        y0 = r.integers(0, H - 6)
        tears[y0:y0 + r.integers(2, 12)] = r.integers(-30, 30)
    img = shift_rows(img, tears)
    col = img[..., None] * np.ones(3, np.float32)
    if hue > 0.001:
        col = col * (0.6 + 0.4 * palette(np.full((H, W), 0.0, np.float32), hue))
    return col * (0.75 + 0.25 * pulse(beats, 3))


def fluidos(t, beats, hue, detail):
    """Tinta / aceite: ruido con deformacion de dominio."""
    k = 1.2 + 2.5 * detail
    x, y = X * k, Y * k
    s1 = 0.35 * t
    qx = np.sin(x + 1.7 * np.sin(y * 1.3 + s1) + s1)
    qy = np.cos(y + 1.5 * np.sin(x * 1.1 - s1 * 1.2))
    rx = np.sin(x + 2.2 * qx + 0.3 * t)
    ry = np.cos(y + 2.2 * qy - 0.2 * t)
    v = np.sin(rx * 2.0 + ry * 1.5 + t * 0.2)
    col = palette(v * 0.35 + rx * 0.15 + t * 0.03, hue)
    return col * (0.55 + 0.45 * (0.5 + 0.5 * v))[..., None] * (0.85 + 0.15 * pulse(beats))


def macrobloques(t, beats, hue, detail):
    """Compresion rota: bloques de 8 px que se quedan pegados, se corren y se posterizan."""
    b = 12
    gh, gw = -(-H // b), W // b
    gx, gy = np.meshgrid(np.arange(gw), np.arange(gh))
    base = np.sin(gx * 0.35 + t) + np.sin(gy * 0.5 - t * 0.7) + np.sin((gx + gy) * 0.2 + t * 0.4)
    blocks = palette(base * 0.2, hue)
    r = rng_at(t, 12)                                   # el glitch cambia 12 veces por segundo
    amount = 0.04 + 0.3 * detail + 0.3 * pulse(beats, 3)
    mask = r.random((gh, gw)) < amount
    src_x = (gx + r.integers(-3, 4, (gh, gw))) % gw
    src_y = (gy + r.integers(-1, 2, (gh, gw))) % gh
    blocks = np.where(mask[..., None], blocks[src_y, src_x][..., ::-1], blocks)
    blocks = np.floor(blocks * 4) / 4                    # pocos colores, como un codec roto
    by = np.minimum(_y.astype(int) // b, gh - 1)
    bx = np.minimum(_x.astype(int) // b, gw - 1)
    img = blocks[by, bx]
    # dentro de algunos bloques, rayas (detalle que "se arrastra")
    smear = (r.random((gh, gw)) < amount * 0.5)[by, bx]
    stripes = (0.55 + 0.45 * np.sin(_x * 0.9 + _y * 0.05))[..., None]
    img = np.where(smear[..., None], img * stripes, img)
    return chroma(img.astype(np.float32), int(2 + 4 * pulse(beats, 4)))


_BARS = np.array([[1, 1, 1], [1, 1, 0], [0, 1, 1], [0, 1, 0], [1, 0, 1], [1, 0, 0], [0, 0, 1]], np.float32)


def barrido_rgb(t, beats, hue, detail):
    """Barras de color con la senal rota: canales corridos, filas cortadas y bloques."""
    r = rng_at(t)
    bars = _BARS[np.minimum((_x / W * 7).astype(int), 6)]
    low = _y > H * 0.72
    bars = np.where(low[..., None], _BARS[(np.minimum((_x / W * 5).astype(int), 4) * 3 + 2) % 7] * 0.6, bars)
    if hue > 0.001:
        bars = bars * palette(np.full((H, W), 0.0, np.float32), hue) * 1.3
    amt = 0.2 + 0.8 * detail
    wave = np.sin(_y[:, 0] * 0.15 + t * 6) * 6 * amt
    jitter = r.normal(0, 1, H) * 3 * amt
    tears = (wave + jitter).astype(int)
    if r.random() < 0.5 * amt + 0.4 * pulse(beats, 3):
        y0 = r.integers(0, H - 10)
        tears[y0:y0 + r.integers(3, 20)] += r.integers(-60, 60)
    img = shift_rows(bars, tears)
    dx = int(3 + 10 * amt * (0.5 + 0.5 * math.sin(t * 2)) + 8 * pulse(beats, 4))
    img = chroma(img, dx)
    img = img * (0.88 + 0.12 * np.sin(_y * 2.2))[..., None]   # lineas de barrido
    return img


def ondas_vhs(t, beats, hue, detail):
    """Fondo claro con curvas oscuras que ondulan, con fantasmas de color (cinta gastada)."""
    r = rng_at(t)
    k = 1 + int(detail * 2.99)
    phase = Y * 2.5 + t * 1.5
    def curves(dx):
        u = (X + dx) * k / 3.6 + 0.5 + 0.18 * np.sin(phase) + 0.015 * np.sin(Y * 40 + t * 25)
        return np.exp(-((u - np.round(u)) / 0.05) ** 2)
    jit = (r.normal(0, 1, H) * (1.5 + 3 * pulse(beats, 3))).astype(int)
    m = curves(0.0)
    ghost_r = shift_rows(curves(-0.05), jit + 4)
    ghost_b = shift_rows(curves(0.05), jit - 4)
    base = np.ones((H, W, 3), np.float32) * 0.92
    if hue > 0.001:
        base = base * (0.7 + 0.3 * palette(np.full((H, W), 0.0, np.float32), hue))
    img = base * (1 - shift_rows(m, jit))[..., None]
    img[..., 0] -= 0.5 * ghost_b                         # bordes verdes / magenta
    img[..., 1] -= 0.6 * ghost_r
    img[..., 2] -= 0.3 * ghost_r
    vign = np.clip(1.25 - 0.35 * (X * X / 3 + Y * Y), 0, 1)
    return np.clip(img, 0, 1) * vign[..., None]


# ---------- audio (espectro del microfono del telefono) ----------
_audio = np.zeros(32, np.float32)     # ultimo espectro recibido (0..1)
_level = np.zeros(W, np.float32)      # desplazamiento suavizado de la linea


def set_audio(bands):
    global _audio
    _audio = np.asarray(bands, np.float32) if len(bands) else np.zeros(32, np.float32)


def linea_audio(t, beats, hue, detail):
    """Linea blanca horizontal que se deforma con las frecuencias del mic:
    graves en el centro, agudos hacia los bordes (espejado)."""
    global _level
    a = _audio if _audio.size else np.zeros(32, np.float32)
    n = a.size
    pos = np.abs(np.linspace(-1, 1, W)) * (n - 1)               # centro = graves
    spec = np.interp(pos, np.arange(n), a)
    wob = np.sin(np.linspace(0, 1, W) * (20 + 40 * detail) + t * 9)   # oscila como una onda
    target = spec * wob * (0.4 + 0.9 * detail) * (H * 0.45)
    _level = np.where(np.abs(target) > np.abs(_level), target, _level * 0.82)  # sube rapido, baja suave
    _level = np.clip(_level, -H * 0.47, H * 0.47)
    yline = H / 2 + _level + np.sin(_x[0] * 0.3 + t * 30) * 0.3
    # cada columna cubre el tramo hasta sus vecinas: la linea queda continua aunque sea empinada
    lo = np.minimum(yline, np.minimum(np.roll(yline, 1), np.roll(yline, -1)) * 0.5 + yline * 0.5)
    hi = np.maximum(yline, np.maximum(np.roll(yline, 1), np.roll(yline, -1)) * 0.5 + yline * 0.5)
    d = np.maximum(0, np.maximum(lo[None, :] - _y, _y - hi[None, :]))
    core = np.clip(1.6 - d, 0, 1)                                # linea de ~2 px
    glow = np.exp(-d / 3.0) * (0.25 + 0.5 * float(a.mean()) if a.size else 0.25)
    v = np.clip(core + glow, 0, 1)
    col = np.ones(3, np.float32) if hue < 0.001 else palette(np.zeros(1, np.float32), hue)[0]
    return v[..., None] * col


GENERATORS = {
    "plasma": ("Plasma", plasma),
    "tunel": ("Túnel", tunel),
    "caleidoscopio": ("Caleidoscopio", caleidoscopio),
    "barras": ("Barras", barras),
    "circulos": ("Círculos", circulos),
    "rejilla": ("Rejilla", rejilla),
    "espiral": ("Espiral", espiral),
    "estatica": ("Estática TV", estatica),
    "fluidos": ("Fluidos", fluidos),
    "macrobloques": ("Macrobloques", macrobloques),
    "barrido_rgb": ("Barrido RGB", barrido_rgb),
    "ondas_vhs": ("Ondas VHS", ondas_vhs),
    "linea_audio": ("Línea de audio", linea_audio),
}


def render(name, t, beats, hue=0.0, detail=0.5):
    """Cuadro RGB (bytes, W*H*3) del generador."""
    f = GENERATORS[name][1]
    img = f(np.float32(t), float(beats), np.float32(hue), float(detail))
    return (np.clip(img, 0, 1) * 255).astype(np.uint8).tobytes()
