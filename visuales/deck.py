"""Un deck: decodifica un clip en loop con ffmpeg y entrega frames RGB al ritmo pedido."""
import logging
import queue
import subprocess
import threading

log = logging.getLogger("deck")


class Deck:
    def __init__(self, name, fps):
        self.name = name
        self.fps = fps
        self.w = self.h = 0
        self.src = None        # (ruta, ancho, alto) cargado
        self.proc = None
        self.q = None
        self.frame = None      # bytes RGB del frame actual (None = negro)
        self.t = 0.0           # reloj del clip en segundos
        self.idx = 0           # frames consumidos
        self.frame_serial = 0

    @property
    def aspect(self):
        return self.w / self.h if self.h else 4 / 3

    def load(self, src):
        """src = (ruta, ancho, alto) o None."""
        if src == self.src:
            return
        self.stop()
        self.src = src
        self.frame = None
        self.frame_serial += 1
        if src is None:
            return
        path, self.w, self.h = src
        fb = self.w * self.h * 3
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
            "-threads", "2", "-stream_loop", "-1", "-i", str(path), "-an",
            "-vf", f"scale={self.w}:{self.h}",
            "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
        ]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=fb * 2)
        self.q = queue.Queue(maxsize=4)
        threading.Thread(target=self._reader, args=(self.proc, self.q, fb), daemon=True).start()
        self.t = 0.0
        self.idx = 0
        log.info("deck %s <- %s (%dx%d)", self.name, path, self.w, self.h)

    @staticmethod
    def _reader(proc, q, fb):
        try:
            while True:
                buf = proc.stdout.read(fb)
                if not buf or len(buf) < fb:
                    break
                q.put(buf)  # bloquea si el render no consume: ffmpeg queda en pausa
        except Exception:
            pass
        finally:
            q.put(None)

    def stop(self):
        if self.proc:
            try:
                self.proc.kill()
                self.proc.stdout.close()
            except Exception:
                pass
            try:  # destrabar al lector si estaba bloqueado en put()
                while True:
                    self.q.get_nowait()
            except Exception:
                pass
            try:
                self.proc.wait(timeout=2)
            except Exception:
                pass
        self.proc = None
        self.src = None

    def update(self, dt, speed):
        """Avanza el reloj del clip y saca de la cola los frames necesarios."""
        if not self.proc:
            return
        self.t += dt * speed
        target = int(self.t * self.fps)
        if self.frame is None:
            target = max(target, 1)  # mostrar el primer frame en cuanto este listo
        changed = False
        while self.idx < target:
            try:
                buf = self.q.get_nowait()
            except queue.Empty:
                # decodificador atrasado: no acumular deuda (evita saltos despues)
                self.t = self.idx / self.fps
                break
            if buf is None:
                log.warning("deck %s: decoder termino", self.name)
                self.proc = None
                self.src = None  # se reintenta en el proximo load
                break
            self.frame = buf
            self.idx += 1
            changed = True
        if changed:
            self.frame_serial += 1
