"""Shows: listas de videos por banda (sobre la biblioteca comun) con sus ajustes en vivo.

Carpetas: dentro de la lista del show van marcas "dir:<id>"; los videos que siguen a una marca
(hasta la proxima) son de esa carpeta. Los de antes de la primera marca quedan sueltos arriba.
Asi el orden del show sigue siendo una sola lista y mover un video entre carpetas es moverlo."""
import json
import logging
import os
import threading
import uuid

from .util import read_json, write_json

log = logging.getLogger("shows")
DIR = "dir:"


def _block(lst, i):
    """Fin (exclusivo) del bloque que empieza en la marca de carpeta lst[i]."""
    j = i + 1
    while j < len(lst) and not lst[j].startswith(DIR):
        j += 1
    return j


class Shows:
    def __init__(self, cfg):
        self.file = cfg.data_dir / "shows.json"
        self.lock = threading.RLock()
        self.shows = []
        self.active = None
        self._timer = None
        if self.file.exists():
            try:
                d = read_json(self.file)
                self.shows, self.active = d.get("shows", []), d.get("active")
            except Exception:
                log.exception("shows.json corrupto, empiezo vacio")
        if self.active and not self._get(self.active):
            self.active = None

    # ---------- persistencia ----------
    def _save(self):
        with self.lock:
            write_json(self.file, {"shows": self.shows, "active": self.active})

    def _save_later(self):
        with self.lock:
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(2.0, self._save)
            self._timer.daemon = True
            self._timer.start()

    def _get(self, sid):
        return next((s for s in self.shows if s["id"] == sid), None)

    def payload(self):
        with self.lock:
            return {"type": "shows", "active": self.active,
                    "shows": [{"id": s["id"], "name": s["name"], "clips": list(s["clips"]),
                               "dirs": dict(s.get("dirs") or {}), "closed": list(s.get("closed") or [])}
                              for s in self.shows]}

    def active_live(self):
        with self.lock:
            s = self._get(self.active)
            return dict(s.get("live") or {}) if s else None

    # ---------- comandos ----------
    def apply(self, cmd, data):
        """Devuelve (cambio_algo, ajustes_en_vivo_a_cargar_o_None)."""
        with self.lock:
            sid = data.get("id")
            s = self._get(sid) if sid else None
            load = None
            if cmd == "show_create":
                name = str(data.get("name") or "Show nuevo").strip()[:60]
                s = {"id": uuid.uuid4().hex[:8], "name": name, "clips": [], "live": dict(data.get("live") or {})}
                self.shows.append(s)
                self.active = s["id"]
            elif cmd == "show_rename" and s:
                s["name"] = str(data.get("name") or s["name"]).strip()[:60]
            elif cmd == "show_delete" and s:
                self.shows.remove(s)
                if self.active == sid:
                    self.active = None
            elif cmd == "show_select":
                if sid is None or s:
                    self.active = sid
                    load = dict(s.get("live") or {}) if s else None
            elif cmd == "show_toggle_clip" and s and data.get("clip"):
                c = data["clip"]
                if c in s["clips"]:
                    s["clips"].remove(c)
                else:
                    s["clips"].append(c)
            elif cmd == "show_dir_add" and s:
                d = uuid.uuid4().hex[:6]
                s.setdefault("dirs", {})[d] = str(data.get("name") or "Carpeta").strip()[:40]
                s["clips"].append(DIR + d)
            elif cmd == "show_dir_rename" and s and data.get("dir") in (s.get("dirs") or {}):
                s["dirs"][data["dir"]] = str(data.get("name") or "").strip()[:40] or s["dirs"][data["dir"]]
            elif cmd == "show_dir_delete" and s and DIR + str(data.get("dir")) in s["clips"]:
                # se borra la carpeta, no los videos: pasan a la carpeta de arriba (o quedan sueltos)
                s["clips"].remove(DIR + data["dir"])
                s.get("dirs", {}).pop(data["dir"], None)
                if data["dir"] in s.get("closed", []):
                    s["closed"].remove(data["dir"])
            elif cmd == "show_dir_toggle" and s and data.get("dir") in (s.get("dirs") or {}):
                closed = s.setdefault("closed", [])
                if data["dir"] in closed:
                    closed.remove(data["dir"])
                else:
                    closed.append(data["dir"])
            elif cmd == "show_dir_move" and s and DIR + str(data.get("dir")) in s["clips"]:
                # mueve la carpeta entera (con sus videos) arriba o abajo de la carpeta vecina
                lst = s["clips"]
                i = lst.index(DIR + data["dir"])
                j = _block(lst, i)
                blk, rest = lst[i:j], lst[:i] + lst[j:]
                marks = [k for k, x in enumerate(rest) if x.startswith(DIR)]
                before = [k for k in marks if k < i]
                if int(data.get("dir_step", 0)) < 0:
                    at = before[-1] if before else i   # antes de la carpeta de arriba
                else:
                    after = [k for k in marks if k >= i]
                    at = _block(rest, after[0]) if after else i  # despues de la carpeta de abajo
                s["clips"] = rest[:at] + blk + rest[at:]
            elif cmd == "show_move_to" and s and data.get("clip") in s["clips"]:
                # pasa un video al final de una carpeta (dir vacio = sueltos, arriba de todo)
                lst, c = s["clips"], data["clip"]
                lst.remove(c)
                d = data.get("dir")
                if d and DIR + d in lst:
                    lst.insert(_block(lst, lst.index(DIR + d)), c)
                else:
                    first = next((k for k, x in enumerate(lst) if x.startswith(DIR)), len(lst))
                    lst.insert(first, c)
            elif cmd == "show_move" and s and data.get("clip") in s["clips"]:
                lst, c = s["clips"], data["clip"]
                i = lst.index(c)
                j = max(0, min(len(lst) - 1, i + int(data.get("dir", 0))))
                lst.insert(j, lst.pop(i))
            else:
                return False, None
            self._save()
            return True, load

    def add_to_active(self, clip_id):
        with self.lock:
            s = self._get(self.active)
            if s and clip_id not in s["clips"]:
                s["clips"].append(clip_id)
                self._save()
                return True
        return False

    def remove_clip(self, clip_id):
        with self.lock:
            changed = False
            for s in self.shows:
                if clip_id in s["clips"]:
                    s["clips"].remove(clip_id)
                    changed = True
            if changed:
                self._save()
            return changed

    def store_live(self, live):
        """Guarda los ajustes en vivo actuales en el show activo (con demora)."""
        with self.lock:
            s = self._get(self.active)
            if s and s.get("live") != live:
                s["live"] = live
                self._save_later()
