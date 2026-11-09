"""Estado compartido del mezclador. Lo modifica el servidor web y lo lee el render."""
import math
import random
import threading
import time

STROBE_DIVS = (0.25, 0.5, 1, 2, 4)  # destellos por beat
ZOOM_CYCLES = (0.5, 1, 2, 4, 8, 16, 32)  # beats por ciclo de zoom
ZOOM_MODES = ("fixed", "pulse", "in", "out")
FITS = ("fit", "fill", "stretch")
DEFAULT_FX = {"fit": "fit", "zoom": 1.0, "panx": 0.0, "pany": 0.0, "speed": 1.0,
              "hue": 0.0, "detail": 0.5}  # hue/detail: solo para los generadores


def clean_fx(fx):
    """Ajustes por clip validados (lo que queda guardado con cada video)."""
    out = dict(DEFAULT_FX)
    fx = fx or {}
    if fx.get("fit") in FITS:
        out["fit"] = fx["fit"]
    for k, lo, hi in (("zoom", 0.25, 4.0), ("panx", -1.0, 1.0), ("pany", -1.0, 1.0), ("speed", 0.0, 4.0),
                      ("hue", 0.0, 1.0), ("detail", 0.0, 1.0)):
        if k in fx:
            try:
                out[k] = max(lo, min(hi, float(fx[k])))
            except (TypeError, ValueError):
                pass
    return out


class BeatClock:
    def __init__(self, bpm=120.0):
        self.bpm = bpm
        self.anchor = time.monotonic()  # instante de un beat "1"
        self.taps = []

    def tap(self, now=None):
        now = now or time.monotonic()
        if self.taps and now - self.taps[-1] > 2.0:
            self.taps = []
        self.taps.append(now)
        self.taps = self.taps[-8:]
        if len(self.taps) >= 2:
            intervals = [b - a for a, b in zip(self.taps, self.taps[1:])]
            avg = sum(intervals) / len(intervals)
            if avg > 0:
                self.bpm = max(40.0, min(240.0, 60.0 / avg))
        self.anchor = now

    def set_bpm(self, bpm):
        self.bpm = max(40.0, min(240.0, float(bpm)))

    def resync(self, now=None):
        self.anchor = now or time.monotonic()

    def beats(self, now=None):
        """Beats transcurridos (float) desde el ancla."""
        now = now or time.monotonic()
        return (now - self.anchor) * self.bpm / 60.0


class Mixer:
    """Todo lo que controla el telefono. Acceso protegido con self.lock."""

    def __init__(self):
        self.lock = threading.RLock()
        self.version = 0
        # decks: clip cargado y velocidad
        self.decks = {k: {"clip": None, "fx": dict(DEFAULT_FX)} for k in "AB"}
        self.xfade = 0.0           # 0 = A al aire, 1 = B al aire
        self.xfade_anim = None     # (desde, hasta, t0, duracion)
        self.fade_time = 2.0       # segundos del crossfade automatico (GO)
        self.master = 1.0          # fader master (brillo general)
        self.blackout = False
        self.blackout_level = 0.0  # 0 = normal, 1 = negro total (animado)
        self.blackout_time = 1.0
        self.tint = [1.0, 0.2, 0.6]
        self.tint_amount = 0.0
        self.strobe = False
        self.strobe_div = 1        # destellos por beat
        self.strobe_color = "white"
        # imagen
        self.screen_aspect = "4:3"  # proporcion fisica de la pantalla
        self.zoom = 1.0
        self.zoom_mode = "fixed"
        self.zoom_cycle = 4         # beats por ciclo
        self.quake = False
        self.quake_amount = 0.5
        # texto en pantalla estilo VHS
        self.osd = {"text": "", "on": False, "pos": "tl", "size": 2, "blink": False}
        self.beat = BeatClock()
        self._last = time.monotonic()

    # ---------- helpers ----------
    def touch(self):
        self.version += 1

    def live_deck(self):
        return "A" if self.xfade < 0.5 else "B"

    def next_deck(self):
        return "B" if self.xfade < 0.5 else "A"

    # ---------- audio del telefono ----------
    def set_audio(self, bands):
        """bands: lista de 0..255 (graves a agudos) que manda el telefono."""
        try:
            vals = [max(0.0, min(1.0, float(v) / 255.0)) for v in list(bands)[:64]]
        except (TypeError, ValueError):
            return
        with self.lock:
            self.audio, self.audio_t = vals, time.monotonic()

    # ---------- comandos ----------
    def apply(self, cmd, data):
        """Aplica un comando del telefono. Devuelve True si cambio algo."""
        with self.lock:
            if cmd == "cue":  # cargar clip en el deck oculto (o en el indicado)
                deck = data.get("deck") or self.next_deck()
                self.decks[deck]["clip"] = data.get("clip")
                self.decks[deck]["fx"] = clean_fx(data.get("fx"))
                if data.get("go"):
                    self._go(deck)
            elif cmd == "go":
                self._go(data.get("deck") or self.next_deck())
            elif cmd == "cut":
                self.xfade_anim = None
                self.xfade = 1.0 if self.next_deck() == "B" else 0.0
            elif cmd == "xfade":
                self.xfade_anim = None
                self.xfade = _clamp(data.get("value", 0))
            elif cmd == "fade_time":
                self.fade_time = max(0.0, min(30.0, float(data.get("value", 2))))
            elif cmd == "clipfx":  # ajustes del clip cargado en un deck
                d = self.decks[data["deck"]]
                if data.get("reset"):
                    d["fx"] = dict(DEFAULT_FX)
                else:
                    d["fx"] = clean_fx({**d["fx"], **{k: v for k, v in data.items() if k in DEFAULT_FX}})
            elif cmd == "eject":
                self.decks[data["deck"]]["clip"] = None
            elif cmd == "master":
                self.master = _clamp(data.get("value", 1))
            elif cmd == "blackout":
                self.blackout = bool(data.get("value", not self.blackout))
            elif cmd == "blackout_time":
                self.blackout_time = max(0.0, min(10.0, float(data.get("value", 1))))
            elif cmd == "tint":
                if "color" in data:
                    self.tint = [_clamp(c) for c in data["color"]][:3]
                if "amount" in data:
                    self.tint_amount = _clamp(data["amount"])
            elif cmd == "strobe":
                if "on" in data:
                    self.strobe = bool(data["on"])
                if "div" in data and float(data["div"]) in STROBE_DIVS:
                    self.strobe_div = float(data["div"])
                if data.get("color") in ("white", "black", "tint"):
                    self.strobe_color = data["color"]
            elif cmd == "view":
                if data.get("screen") in ("4:3", "16:9"):
                    self.screen_aspect = data["screen"]
            elif cmd == "zoom":
                if "value" in data:
                    self.zoom = max(1.0, min(4.0, float(data["value"])))
                if data.get("mode") in ZOOM_MODES:
                    self.zoom_mode = data["mode"]
                if "cycle" in data and float(data["cycle"]) in ZOOM_CYCLES:
                    self.zoom_cycle = float(data["cycle"])
            elif cmd == "quake":
                if "on" in data:
                    self.quake = bool(data["on"])
                if "amount" in data:
                    self.quake_amount = _clamp(data["amount"])
            elif cmd == "osd":
                o = self.osd
                if "text" in data:
                    o["text"] = str(data["text"])[:200]
                if "on" in data:
                    o["on"] = bool(data["on"])
                if data.get("pos") in ("tl", "tr", "c", "bl", "br"):
                    o["pos"] = data["pos"]
                if "size" in data and int(data["size"]) in (1, 2, 3, 4):
                    o["size"] = int(data["size"])
                if "blink" in data:
                    o["blink"] = bool(data["blink"])
            elif cmd == "tap":
                self.beat.tap()
            elif cmd == "bpm":
                self.beat.set_bpm(data.get("value", 120))
                if data.get("resync"):
                    self.beat.resync()
            elif cmd == "resync":
                self.beat.resync()
            elif cmd == "clip_removed":
                for d in self.decks.values():
                    if d["clip"] == data.get("clip"):
                        d["clip"] = None
            else:
                return False
            self.touch()
            return True

    def _go(self, deck):
        target = 1.0 if deck == "B" else 0.0
        if self.fade_time <= 0:
            self.xfade, self.xfade_anim = target, None
        else:
            self.xfade_anim = (self.xfade, target, time.monotonic(), self.fade_time)

    # ---------- tick del render ----------
    def tick(self):
        """Avanza animaciones y devuelve una copia de lo que necesita el render."""
        now = time.monotonic()
        with self.lock:
            dt = now - self._last
            self._last = now
            if self.xfade_anim:
                a, b, t0, dur = self.xfade_anim
                k = min(1.0, (now - t0) / dur)
                k = k * k * (3 - 2 * k)  # ease in/out
                self.xfade = a + (b - a) * k
                if k >= 1.0:
                    self.xfade_anim = None
            target = 1.0 if self.blackout else 0.0
            if self.blackout_time <= 0:
                self.blackout_level = target
            else:
                step = dt / self.blackout_time
                if self.blackout_level < target:
                    self.blackout_level = min(target, self.blackout_level + step)
                elif self.blackout_level > target:
                    self.blackout_level = max(target, self.blackout_level - step)
            strobe = 0.0
            if self.strobe:
                phase = (self.beat.beats(now) * self.strobe_div) % 1.0
                strobe = 1.0 if phase < 0.35 else 0.0
            if self.strobe_color == "white":
                scol = (1.0, 1.0, 1.0)
            elif self.strobe_color == "black":
                scol = (0.0, 0.0, 0.0)
            else:
                scol = tuple(self.tint)
            beats = self.beat.beats(now)
            zoom, droste = self.zoom, False
            if self.zoom_mode != "fixed":
                ph = (beats / self.zoom_cycle) % 1.0
                if self.zoom_mode == "pulse":
                    zoom *= 1.0 + 0.35 * (0.5 - 0.5 * math.cos(2 * math.pi * ph))
                elif self.zoom_mode == "in":
                    zoom *= 2.0 ** ph
                    droste = True
                else:
                    zoom *= 2.0 ** (1.0 - ph)
                    droste = True
            offset = (0.0, 0.0)
            if self.quake:
                rnd = random.Random(int(now * 30))  # 30 sacudidas por segundo
                q = 0.2 + 0.8 * self.quake_amount
                offset = (rnd.uniform(-1, 1) * 0.04 * q, rnd.uniform(-1, 1) * 0.04 * q)
                zoom *= 1.0 + 0.1 * q * rnd.random()
            return {
                "screen_aspect": 4 / 3 if self.screen_aspect == "4:3" else 16 / 9,
                "beats": beats,
                "audio": getattr(self, "audio", []) if now - getattr(self, "audio_t", 0) < 0.6 else [],
                "zoom": zoom,
                "offset": offset,
                "droste": droste,
                "decks": {k: {"clip": v["clip"], "fx": dict(v["fx"])} for k, v in self.decks.items()},
                "xfade": self.xfade,
                "master": self.master * (1.0 - self.blackout_level),
                "tint": tuple(self.tint),
                "tint_amount": self.tint_amount,
                "strobe": strobe,
                "strobe_color": scol,
                "osd": dict(self.osd, on=self.osd["on"] and bool(self.osd["text"].strip()) and
                            (not self.osd["blink"] or (beats % 1.0) < 0.6)),
            }

    def live_settings(self):
        """Ajustes en vivo que se guardan con cada show."""
        with self.lock:
            return {"bpm": round(self.beat.bpm, 2), "screen": self.screen_aspect, "tint": list(self.tint),
                    "tint_amount": self.tint_amount, "strobe_div": self.strobe_div,
                    "strobe_color": self.strobe_color, "fade_time": self.fade_time,
                    "blackout_time": self.blackout_time, "zoom_cycle": self.zoom_cycle,
                    "quake_amount": self.quake_amount, "master": self.master,
                    "osd": {k: self.osd[k] for k in ("text", "pos", "size", "blink")}}

    def load_live(self, d):
        """Carga los ajustes en vivo de un show (los efectos activos se apagan)."""
        if not d:
            return
        with self.lock:
            try:
                if "bpm" in d:
                    self.beat.set_bpm(d["bpm"])
                if d.get("screen") in ("4:3", "16:9"):
                    self.screen_aspect = d["screen"]
                if isinstance(d.get("tint"), list) and len(d["tint"]) == 3:
                    self.tint = [_clamp(c) for c in d["tint"]]
                if d.get("strobe_div") in STROBE_DIVS:
                    self.strobe_div = d["strobe_div"]
                if d.get("strobe_color") in ("white", "black", "tint"):
                    self.strobe_color = d["strobe_color"]
                if d.get("zoom_cycle") in ZOOM_CYCLES:
                    self.zoom_cycle = d["zoom_cycle"]
                for k in ("tint_amount", "quake_amount", "master"):
                    if k in d:
                        setattr(self, k, _clamp(d[k]))
                if "fade_time" in d:
                    self.fade_time = max(0.0, min(30.0, float(d["fade_time"])))
                if "blackout_time" in d:
                    self.blackout_time = max(0.0, min(10.0, float(d["blackout_time"])))
                if isinstance(d.get("osd"), dict):
                    o = d["osd"]
                    self.osd.update(text=str(o.get("text", ""))[:200], on=False,
                                    pos=o.get("pos", "tl") if o.get("pos") in ("tl", "tr", "c", "bl", "br") else "tl",
                                    size=int(o.get("size", 2)) if int(o.get("size", 2)) in (1, 2, 3, 4) else 2,
                                    blink=bool(o.get("blink", False)))
            except (TypeError, ValueError):
                pass
            self.strobe = False
            self.quake = False
            self.touch()

    def snapshot(self):
        """Estado para enviar al telefono."""
        with self.lock:
            return {
                "decks": self.decks,
                "live": self.live_deck(),
                "next": self.next_deck(),
                "xfade": round(self.xfade, 3),
                "fading": self.xfade_anim is not None,
                "fade_time": self.fade_time,
                "master": self.master,
                "blackout": self.blackout,
                "blackout_time": self.blackout_time,
                "tint": self.tint,
                "tint_amount": self.tint_amount,
                "strobe": self.strobe,
                "strobe_div": self.strobe_div,
                "strobe_color": self.strobe_color,
                "screen": self.screen_aspect,
                "zoom": self.zoom,
                "zoom_mode": self.zoom_mode,
                "zoom_cycle": self.zoom_cycle,
                "quake": self.quake,
                "quake_amount": self.quake_amount,
                "osd": dict(self.osd),
                "bpm": round(self.beat.bpm, 1),
                "beat": int(self.beat.beats()),
            }


def _clamp(v):
    return max(0.0, min(1.0, float(v)))
