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
        self.gen = None        # nombre del generador si el clip es generativo
        self.late = 0          # veces que el video no llego a tiempo (decodificador atrasado)
        self.blend = 1.0       # camara lenta: cuanto del cuadro actual se ve (el resto es el anterior)
        self.loop = None       # (inicio, duracion) en segundos: loopea solo esa parte del clip
        self.t_loop = 0.0
        self.procs = []

    @property
    def aspect(self):
        return self.w / self.h if self.h else 4 / 3

    def load(self, src, loop=None):
        """src = (ruta, ancho, alto) o None. loop = (inicio, duracion) en segundos o None (todo el clip)."""
        if src == self.src and loop == self.loop:
            return
        if src == self.src:
            # solo cambio el in/out (se esta moviendo el fader): no reiniciar ffmpeg en cada paso
            import time
            if time.monotonic() - self.t_loop < 0.3:
                return
            self.t_loop = time.monotonic()
        self.stop()
        self.src, self.loop = src, loop
        self.blend = 1.0
        self.frame = None
        self.frame_serial += 1
        if src is None:
            return
        path, self.w, self.h = src
        self.t = 0.0
        self.idx = 0
        if str(path).startswith("gen:"):
            self.gen = str(path)[4:]
            log.info("deck %s <- generador %s", self.name, self.gen)
            return
        self.gen = None
        fb = self.w * self.h * 3
        out = ["-an", "-vf", f"scale={self.w}:{self.h}", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"]
        base = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-threads", "2"]
        self.q = queue.Queue(maxsize=4)
        if not loop:
            self.proc = subprocess.Popen(base + ["-stream_loop", "-1", "-i", str(path)] + out,
                                         stdout=subprocess.PIPE, bufsize=fb * 2)
            self.procs = [self.proc]
            threading.Thread(target=self._reader, args=(self.proc, self.q, fb), daemon=True).start()
            log.info("deck %s <- %s (%dx%d)", self.name, path, self.w, self.h)
            return
        # in/out: cada vuelta es un ffmpeg desde el in; la siguiente arranca mientras se lee la
        # actual, asi al llegar al out ya esta decodificada y el loop no salta
        ss, dur = loop
        cmd = base + ["-ss", f"{ss:.3f}", "-t", f"{dur:.3f}", "-i", str(path)] + out
        procs = self.procs = []

        def spawn():
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=fb * 2)
            procs.append(p)
            return p
        self.proc = spawn()
        threading.Thread(target=self._loop_reader, args=(self.proc, spawn, self.q, fb, procs), daemon=True).start()
        log.info("deck %s <- %s (%dx%d) loop %.2fs + %.2fs", self.name, path, self.w, self.h, ss, dur)

    @staticmethod
    def _loop_reader(first, spawn, q, fb, procs):
        cur = nxt = first
        try:
            while True:
                nxt = spawn()  # la vuelta siguiente ya va decodificando
                n = 0
                while True:
                    buf = cur.stdout.read(fb)
                    if not buf or len(buf) < fb:
                        break
                    q.put(buf)
                    n += 1
                cur.wait()
                if cur in procs:
                    procs.remove(cur)
                if n == 0 or cur.returncode not in (0, None):
                    break  # parado (stop) o el archivo no se puede leer
                cur = nxt
        except Exception:
            pass
        finally:
            for p in (cur, nxt):  # que no quede ningun ffmpeg colgado
                try:
                    p.kill()
                    p.wait(timeout=2)
                except Exception:
                    pass
            q.put(None)

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
            for p in list(self.procs) or [self.proc]:
                try:
                    p.kill()
                    p.stdout.close()
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
        self.loop = None
        self.procs = []

    def update(self, dt, speed, beats=0.0, fx=None):
        """Avanza el reloj del clip y saca de la cola los frames necesarios."""
        if self.gen == "solid" and self.src:
            import colorsys
            fx = fx or {}
            rgb = colorsys.hsv_to_rgb(fx.get("hue", 0.0), fx.get("sat", 1.0), fx.get("bright", 1.0))
            px = bytes(int(round(v * 255)) for v in rgb)
            if self.frame is None or self.frame[:3] != px:
                self.frame = px * (self.w * self.h)
                self.frame_serial += 1
            return
        if self.gen and self.src:
            self.t += dt * speed
            self.acc = getattr(self, "acc", 0.0) + dt
            # se dibuja a los fps del video (25), no a los del render: ahorra CPU en la Pi
            if (speed > 0 and self.acc >= 1.0 / self.fps) or self.frame is None:
                self.acc = 0.0
                from .generators import render
                fx = fx or {}
                # beats tambien escalados por la velocidad del clip (0 = congelado)
                self.frame = render(self.gen, self.t, beats * (1.0 if speed > 0 else 0.0),
                                    fx.get("hue", 0.0), fx.get("detail", 0.5))
                self.frame_serial += 1
            return
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
                self.late += 1
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
        # camara lenta: entre cuadro y cuadro se funde el anterior con el actual (va un cuadro atrasado)
        pos = self.t * self.fps
        if 0.0 < speed < 0.95 and self.idx >= 2 and self.idx >= int(pos):
            self.blend = max(0.0, min(1.0, pos - self.idx))
        else:
            self.blend = 1.0
