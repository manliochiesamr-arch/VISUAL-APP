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
            path = self.cfg.clips_dir / c["file"]
            if not c.get("width"):
                c["width"], c["height"] = probe_size(path)
            return path, c["width"], c["height"]

    # ---------- alta ----------
    def new_upload_path(self, filename):
        """Devuelve (id, ruta destino) para un archivo entrante. Lanza ValueError si no es mp4."""
        if not filename.lower().endswith(".mp4"):
            raise ValueError("Solo se aceptan archivos .mp4")
        cid = uuid.uuid4().hex[:10]
        return cid, self.cfg.incoming_dir / f"{cid}.mp4"

    def add_uploaded(self, cid, filename, path):
        name = re.sub(r"\.mp4$", "", os.path.basename(filename), flags=re.I)
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
                ["ffprobe", "-v", "error", "-show_entries", "format=format_name,duration:stream=codec_type,codec_name",
                 "-of", "json", str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            info = json.loads(out.stdout or "{}")
        except Exception as e:
            return f"No se pudo leer el archivo ({e})"
        fmt = info.get("format", {})
        if "mp4" not in fmt.get("format_name", ""):
            return "El archivo no es un MP4 valido"
        vids = [s for s in info.get("streams", []) if s.get("codec_type") == "video"]
        if not vids:
            return "El archivo no tiene video"
        codec = vids[0].get("codec_name")
        if codec not in self.cfg.allowed_codecs:
            return f"Codec {codec} no soportado: solo MP4 H.264"
        try:
            clip["duration"] = round(float(fmt.get("duration", 0)), 1)
        except ValueError:
            pass
        return None

    def remove(self, cid):
        with self.lock:
            c = self.clips.pop(cid, None)
        if not c:
            return False
        for p in (self.cfg.clips_dir / c["file"], self.cfg.thumbs_dir / f"{cid}.jpg",
                  self.cfg.incoming_dir / c["source"]):
            p.unlink(missing_ok=True)
        self._save()
        return True

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
        cmd = NICE + ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
               "-i", str(src), "-an", "-vf", vf, "-c:v", "libx264", "-preset", "veryfast",
               "-crf", "23", "-g", str(fps), "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(tmp)]
        t0 = time.time()
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
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
