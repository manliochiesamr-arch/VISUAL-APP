"""Shows: listas de videos por banda (sobre la biblioteca comun) con sus ajustes en vivo."""
import json
import logging
import os
import threading
import uuid

from .util import read_json, write_json

log = logging.getLogger("shows")

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
                    "shows": [{"id": s["id"], "name": s["name"], "clips": list(s["clips"])} for s in self.shows]}

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
