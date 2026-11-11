"""Biblioteca de clips: valida, convierte a SD (una sola vez, al subir) y genera miniaturas."""
import json
import logging
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import uuid

from .util import read_json, write_json

log = logging.getLogger("library")
# baja prioridad para la conversion (en Windows no hay "nice")
NICE = ["nice", "-n", "19"] if shutil.which("nice") else []


TEXT_POS = ("tl", "t", "tr", "l", "c", "r", "bl", "b", "br")


def clean_text(d):
    """Ajustes validados de un recurso de texto."""
    out = {"text": "", "pos": "c", "size": 3, "blink": False, "color": [1.0, 1.0, 1.0],
           "fx": False,   # True = recibe los efectos en vivo (zoom, terremoto, glitch, tinte...)
           "link": None}  # id de un clip: el texto sale solo cuando ese clip esta al aire
    d = d or {}
    out["text"] = str(d.get("text", ""))[:300]
    if d.get("pos") in TEXT_POS:
        out["pos"] = d["pos"]
    try:
        if int(d.get("size", 3)) in (1, 2, 3, 4):
            out["size"] = int(d.get("size", 3))
    except (TypeError, ValueError):
        pass
    out["blink"] = bool(d.get("blink", False))
    out["fx"] = bool(d.get("fx", False))
    out["link"] = str(d["link"])[:40] if d.get("link") else None
    col = d.get("color")
    if isinstance(col, (list, tuple)) and len(col) == 3:
        try:
            out["color"] = [max(0.0, min(1.0, float(v))) for v in col]
        except (TypeError, ValueError):
            pass
    return out


class Library:
    def __init__(self, cfg, on_change=None):
        self.cfg = cfg
        self.on_change = on_change or (lambda: None)
        for d in (cfg.clips_dir, cfg.thumbs_dir, cfg.incoming_dir):
            d.mkdir(parents=True, exist_ok=True)
        self.index_file = cfg.data_dir / "library.json"
        self.lock = threading.RLock()
        self.clips = {}
        self._load()
        self._add_generators()
        self.jobs = queue.Queue()
        threading.Thread(target=self._worker, daemon=True).start()
        # reencolar trabajos que quedaron a medias (corte de luz, etc.)
        for c in list(self.clips.values()):
            if c["status"] in ("queued", "processing"):
                src = cfg.incoming_dir / c["source"]
                if src.exists():
                    c["status"] = "queued"
                    self.jobs.put(c["id"])
                else:
                    c["status"], c["error"] = "error", "archivo original perdido"
        self._save()

    # ---------- generadores (clips sin archivo) ----------
    def _add_generators(self):
        from . import generators as g
        for i, (key, (name, _)) in enumerate(g.GENERATORS.items()):
            cid = "gen-" + key
            if cid not in self.clips:
                self.clips[cid] = {"id": cid, "name": name, "kind": "gen", "gen": key, "status": "ready",
                                   "error": None, "duration": None, "added": 1000 - i,
                                   "width": g.W, "height": g.H, "file": "", "source": ""}

        # miniaturas: se rehacen en cada arranque (por si cambio el dibujo), de a una
        keys = list(g.GENERATORS)
        threading.Thread(target=lambda: [self._gen_thumb(k, self.cfg.thumbs_dir / f"gen-{k}.jpg") for k in keys],
                         daemon=True).start()

    @staticmethod
    def _gen_thumb(key, thumb):
        from . import generators as g
        try:
            raw = g.render(key, 2.0, 0.3, 0.0, 0.5)
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo",
                            "-pix_fmt", "rgb24", "-s", f"{g.W}x{g.H}", "-i", "-", "-frames:v", "1",
                            "-vf", "scale=240:-2", str(thumb)], input=raw, capture_output=True, timeout=30)
        except Exception:
            log.exception("miniatura de generador %s", key)

    # ---------- persistencia ----------
    def _load(self):
        if self.index_file.exists():
            try:
                self.clips = {c["id"]: c for c in read_json(self.index_file)}
            except Exception:
                log.exception("library.json corrupto, empiezo vacio")

    def _save(self):
        with self.lock:
            write_json(self.index_file, list(self.clips.values()))
        self.on_change()

    def list(self):
        with self.lock:
            return sorted(self.clips.values(), key=lambda c: c["added"], reverse=True)

    def path_of(self, clip_id):
        """(ruta, ancho, alto) de un clip listo, o None."""
        with self.lock:
            c = self.clips.get(clip_id)
            if not c or c["status"] != "ready":
                return None
            if c.get("kind") == "gen":
                return "gen:" + c["gen"], c["width"], c["height"]
            if c.get("kind") == "solid":
                return "gen:solid", 16, 9
            if c.get("kind") == "text":
                return None  # los textos no van a un deck: se prenden encima del aire
            path = self.cfg.clips_dir / c["file"]
            if not c.get("width"):
                c["width"], c["height"] = probe_size(path)
            return path, c["width"], c["height"]

    # ---------- alta ----------
    def new_upload_path(self, filename):
        """Devuelve (id, ruta destino) para un archivo entrante. Lanza ValueError si no es un video aceptado."""
        ext = os.path.splitext(filename)[1].lower()
        if ext not in self.cfg.video_exts:
            raise ValueError("Solo se aceptan videos " + " / ".join(self.cfg.video_exts))
        cid = uuid.uuid4().hex[:10]
        return cid, self.cfg.incoming_dir / f"{cid}{ext}"

    def add_uploaded(self, cid, filename, path):
        name = os.path.splitext(os.path.basename(filename))[0]
        clip = {
            "id": cid, "name": name, "source": path.name, "file": f"{cid}.mp4",
            "status": "queued", "error": None, "duration": None, "added": time.time(),
        }
        # validacion rapida antes de encolar
        err = self._probe_error(path, clip)
        if err:
            path.unlink(missing_ok=True)
            raise ValueError(err)
        with self.lock:
            self.clips[cid] = clip
        self._save()
        self.jobs.put(cid)
        return clip

    def _probe_error(self, path, clip):
        try:
            out = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries",
                 "format=format_name,duration:stream=codec_type,codec_name,width,height,pix_fmt,r_frame_rate",
                 "-of", "json", str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            info = json.loads(out.stdout or "{}")
        except Exception as e:
            return f"No se pudo leer el archivo ({e})"
        fmt = info.get("format", {})
        if "mp4" not in fmt.get("format_name", ""):  # mp4 y mov comparten formato ("mov,mp4,...")
            return "El archivo no es un MP4/MOV valido"
        vids = [s for s in info.get("streams", []) if s.get("codec_type") == "video"]
        if not vids:
            return "El archivo no tiene video"
        codec = vids[0].get("codec_name")
        if codec not in self.cfg.allowed_codecs:
            return f"Codec {codec} no soportado"
        v = vids[0]
        try:
            num, den = (v.get("r_frame_rate") or "0/1").split("/")
            fps = float(num) / float(den or 1)
        except (ValueError, ZeroDivisionError):
            fps = 0
        clip["probe"] = {"codec": codec, "w": v.get("width"), "h": v.get("height"),
                         "pix": v.get("pix_fmt"), "fps": round(fps, 2)}
        try:
            clip["duration"] = round(float(fmt.get("duration", 0)), 1)
        except ValueError:
            pass
        return None

    def remove(self, cid):
        with self.lock:
            if self.clips.get(cid, {}).get("kind") == "gen":
                return False  # los generadores no se borran (se sacan del show)
            c = self.clips.pop(cid, None)
            for t in self.clips.values():  # textos vinculados a este clip quedan sueltos
                if t.get("kind") == "text" and t["text"].get("link") == cid:
                    t["text"]["link"] = None
        if not c:
            return False
        if c.get("file"):
            (self.cfg.clips_dir / c["file"]).unlink(missing_ok=True)
        if c.get("source"):
            (self.cfg.incoming_dir / c["source"]).unlink(missing_ok=True)
        (self.cfg.thumbs_dir / f"{cid}.jpg").unlink(missing_ok=True)
        self._save()
        return True

    # ---------- recursos: solidos de color y textos ----------
    def create(self, kind, name=None, text=None, fx=None):
        """Crea un solido de color o un texto. Devuelve el clip."""
        cid = kind + "-" + uuid.uuid4().hex[:8]
        with self.lock:
            n = sum(1 for c in self.clips.values() if c.get("kind") == kind) + 1
            clip = {"id": cid, "kind": kind, "status": "ready", "error": None, "duration": None,
                    "added": time.time(), "width": None, "height": None, "file": "", "source": ""}
            if kind == "solid":
                clip["name"] = (name or f"Sólido {n}")[:80]
                clip["fx"] = {"fit": "stretch", "hue": 0.0, "sat": 1.0, "bright": 1.0}
                if isinstance(fx, dict):
                    for k in ("hue", "sat", "bright"):
                        try:
                            clip["fx"][k] = max(0.0, min(1.0, float(fx.get(k, clip["fx"][k]))))
                        except (TypeError, ValueError):
                            pass
            elif kind == "text":
                clip["text"] = clean_text({"text": text or name or ""})
                clip["name"] = (name or (text or "").strip().split("\n")[0] or f"Texto {n}")[:80]
            else:
                raise ValueError("tipo desconocido")
            self.clips[cid] = clip
        self._save()
        return clip

    def kind(self, cid):
        with self.lock:
            return (self.clips.get(cid) or {}).get("kind")

    def set_text(self, cid, data):
        with self.lock:
            c = self.clips.get(cid)
            if not c or c.get("kind") != "text":
                return False
            c["text"] = clean_text({**c.get("text", {}), **data})
            if "name" in data and str(data["name"]).strip():
                c["name"] = str(data["name"]).strip()[:80]
        self._save_later()
        return True

    def linked_texts(self, clip_id):
        """Textos vinculados a un clip (salen solos cuando ese clip esta al aire)."""
        if not clip_id:
            return []
        with self.lock:
            return [c["id"] for c in self.clips.values()
                    if c.get("kind") == "text" and c["text"].get("link") == clip_id]

    def text_layers(self, ids, beats):
        """Capas para el render de los textos prendidos (mismo formato que el texto en vivo)."""
        out = []
        with self.lock:
            for cid in ids:
                c = self.clips.get(cid)
                if not c or c.get("kind") != "text":
                    continue
                t = c["text"]
                on = bool(t["text"].strip()) and (not t["blink"] or (beats % 1.0) < 0.6)
                out.append({"text": t["text"], "pos": t["pos"], "size": t["size"], "on": on,
                            "color": tuple(t["color"]), "fx": t.get("fx", False)})
        return out

    def _save_later(self):
        """Guarda y avisa a los telefonos con demora (para no escribir la SD con cada letra)."""
        with self.lock:
            if getattr(self, "_later", None):
                self._later.cancel()
            self._later = threading.Timer(0.8, self._save)
            self._later.daemon = True
            self._later.start()

    def get_fx(self, cid):
        with self.lock:
            c = self.clips.get(cid)
            return dict(c.get("fx") or {}) if c else {}

    def set_fx(self, cid, fx):
        """Guarda los ajustes del clip. Escribe a disco con demora (no gastar la SD con cada fader)."""
        with self.lock:
            if cid not in self.clips:
                return
            self.clips[cid]["fx"] = dict(fx)
            if self.clips[cid].get("kind") == "solid":
                self._save_later()  # el color se ve en la grilla: avisar a los telefonos
                return
            if getattr(self, "_fx_timer", None):
                self._fx_timer.cancel()
            self._fx_timer = threading.Timer(1.5, self._save_quiet)
            self._fx_timer.daemon = True
            self._fx_timer.start()

    def _save_quiet(self):
        with self.lock:
            write_json(self.index_file, list(self.clips.values()))

    def rename(self, cid, name):
        with self.lock:
            if cid in self.clips:
                self.clips[cid]["name"] = name[:80]
        self._save()

    # ---------- conversion ----------
    def _set(self, cid, **kw):
        with self.lock:
            if cid in self.clips:
                self.clips[cid].update(kw)
        self._save()

    def _worker(self):
        while True:
            cid = self.jobs.get()
            try:
                self._convert(cid)
            except Exception as e:
                log.exception("conversion %s", cid)
                self._set(cid, status="error", error=f"Error interno: {e}")

    def _convert(self, cid):
        with self.lock:
            c = dict(self.clips.get(cid) or {})
        if not c:
            return
        src = self.cfg.incoming_dir / c["source"]
        dst = self.cfg.clips_dir / c["file"]
        tmp = dst.with_suffix(".part.mp4")
        self._set(cid, status="processing")
        fps = self.cfg.fps
        # se conserva la proporcion original: alto 576 (o ancho max 1024 si es muy panoramico)
        mw, mh = self.cfg.clip_max_w, self.cfg.clip_max_h
        wide = f"gt(iw/ih,{mw}/{mh})"
        vf = (f"scale=iw*sar:ih,setsar=1,"
              f"scale='if({wide},{mw},-2)':'if({wide},-2,{mh})',setsar=1,fps={fps}")
        base = NICE + ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(src), "-an"]
        tail = ["-movflags", "+faststart", str(tmp)]
        pr = c.get("probe") or {}
        t0 = time.time()
        attempts = []
        if (pr.get("codec") == "h264" and pr.get("pix") == "yuv420p" and pr.get("h") and pr["h"] <= mh
                and pr.get("w") and pr["w"] <= mw and abs((pr.get("fps") or 0) - fps) < 0.5):
            # ya esta en el formato final: se copia tal cual, sin recodificar (instantaneo)
            attempts.append(("copia", base + ["-c:v", "copy"] + tail))
        if hw_encoder():
            # encoder por hardware de la Pi: varias veces mas rapido que libx264
            attempts.append(("hw", base + ["-vf", vf + ",format=yuv420p", "-c:v", "h264_v4l2m2m",
                                           "-b:v", "2500k", "-g", str(fps)] + tail))
        attempts.append(("x264", base + ["-vf", vf, "-c:v", "libx264", "-preset", "superfast", "-crf", "23",
                                         "-g", str(fps), "-pix_fmt", "yuv420p"] + tail))
        for how, cmd in attempts:
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if r.returncode == 0 and tmp.exists() and tmp.stat().st_size > 1000 and probe_size(tmp)[0]:
                log.info("clip %s convertido (%s)", cid, how)
                break
            log.warning("conversion %s fallo para %s: %s", how, cid, (r.stderr or "")[-300:])
            tmp.unlink(missing_ok=True)
        if r.returncode != 0 or not tmp.exists():
            log.error("conversion fallo %s: %s", cid, r.stderr[-500:])
            tmp.unlink(missing_ok=True)
            last = (r.stderr or "").strip().splitlines()[-1:] or ["sin detalle"]
            self._set(cid, status="error", error="Fallo la conversion: " + last[0][:160])
            return
        os.replace(tmp, dst)
        thumb = self.cfg.thumbs_dir / f"{cid}.jpg"
        for ss in ("1", "0"):  # clips de menos de 1s: usar el primer frame
            subprocess.run(NICE + ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                            "-ss", ss, "-i", str(dst), "-frames:v", "1", "-vf", "scale=240:-2",
                            str(thumb)], capture_output=True)
            if thumb.exists():
                break
        src.unlink(missing_ok=True)
        vw, vh = probe_size(dst)
        self._set(cid, width=vw, height=vh)
        log.info("clip %s listo en %.1fs", cid, time.time() - t0)
        self._set(cid, status="ready")


_HW = None


def hw_encoder():
    """True si ffmpeg puede codificar H.264 por hardware (Pi 3/4: h264_v4l2m2m en /dev/video11)."""
    global _HW
    if _HW is None:
        _HW = False
        if os.path.exists("/dev/video11"):
            try:
                out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=20)
                _HW = "h264_v4l2m2m" in out.stdout
            except Exception:
                pass
        log.info("encoder por hardware: %s", "si" if _HW else "no")
    return _HW


def disk_free_gb(path):
    return round(shutil.disk_usage(path).free / 1e9, 1)


def probe_size(path):
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                              "stream=width,height", "-of", "csv=p=0", str(path)],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15).stdout.strip()
        w, h = out.split(",")[:2]
        return int(w), int(h)
    except Exception:
        return 720, 576


DEMOS = [
    ("demo barras 16x9", "testsrc2=size=1280x720:rate=25"),
    ("demo fractal 16x9", "mandelbrot=size=960x540:rate=25"),
    ("demo vida 4x3", "life=size=320x240:mold=10:rate=25:ratio=0.1:death_color=#C83232:life_color=#00FF00,scale=640:480:flags=neighbor"),
    ("demo plasma 16x9", "gradients=size=1280x720:rate=25:speed=0.02:n=4"),
]


def add_demo_clips(library):
    """Genera clips de prueba con ffmpeg si la biblioteca esta vacia."""
    if library.list():
        return
    for name, src in DEMOS:
        try:
            cid, dest = library.new_upload_path(name + ".mp4")
            r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                                "-f", "lavfi", "-i", src, "-t", "10", "-c:v", "libx264", "-preset", "veryfast",
                                "-pix_fmt", "yuv420p", str(dest)], capture_output=True, text=True, encoding="utf-8", errors="replace")
            if r.returncode == 0:
                library.add_uploaded(cid, name + ".mp4", dest)
            else:
                log.warning("no pude generar %s: %s", name, r.stderr[-200:])
        except Exception:
            log.exception("demo %s", name)
