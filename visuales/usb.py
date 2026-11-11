"""Importa automaticamente los MP4 de un pendrive enchufado a la Pi.

install.sh agrega una regla udev que monta cada pendrive (solo lectura) en /media/visuales/<disp>.
Aca se revisa esa carpeta cada pocos segundos y se importan los .mp4 que todavia no se trajeron.
Un archivo ya importado (mismo nombre y tamano) no se vuelve a importar aunque se borre de la biblioteca.
"""
import logging
import os
import shutil
import threading
import time
from pathlib import Path

from .util import read_json, write_json

log = logging.getLogger("usb")


class UsbImporter:
    def __init__(self, cfg, library, shows, on_status):
        self.cfg, self.library, self.shows, self.on_status = cfg, library, shows, on_status
        self.root = Path(cfg.usb_dir)
        self.db = cfg.data_dir / "usb-imported.json"
        try:
            self.seen = set(read_json(self.db).get("files", []))
        except (OSError, ValueError):
            self.seen = set()
        self.status = ""

    def start(self):
        threading.Thread(target=self._run, daemon=True, name="usb").start()

    def _set_status(self, text):
        self.status = text
        self.on_status(text)

    def _scan(self):
        found = []
        if not self.root.is_dir():
            return found
        for mount in sorted(self.root.iterdir()):
            for dirpath, dirs, files in os.walk(mount):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d != "System Volume Information"]
                for f in sorted(files):
                    if f.lower().endswith(self.cfg.video_exts + self.cfg.image_exts) and not f.startswith("._"):
                        p = Path(dirpath) / f
                        try:
                            key = f"{f}|{p.stat().st_size}"
                        except OSError:
                            continue
                        if key not in self.seen:
                            found.append((p, key))
        return found

    def _update_status(self):
        """Muestra en el telefono lo que informa el actualizador por pendrive (servicio root)."""
        f = Path("/var/lib/visuales/update-status")
        try:
            m = f.stat().st_mtime
        except OSError:
            return
        if m != getattr(self, "_upd_mtime", None):
            first = getattr(self, "_upd_mtime", None) is None
            self._upd_mtime = m
            if not first or time.time() - m < 600:
                self._set_status(f.read_text(encoding="utf-8", errors="replace").strip())

    def _run(self):
        while True:
            self._update_status()
            try:
                todo = self._scan()
                if todo:
                    self._import(todo)
            except Exception:
                log.exception("importando del pendrive")
                self._set_status("Pendrive: error leyendo, revisa el log")
            time.sleep(4)

    def _import(self, todo):
        ok = bad = 0
        for i, (p, key) in enumerate(todo, 1):
            self._set_status(f"Pendrive: copiando {i}/{len(todo)} · {p.name}")
            try:
                cid, dest = self.library.new_upload_path(p.name)
                shutil.copyfile(p, dest)
                clip = self.library.add_uploaded(cid, p.name, dest)
                self.shows.add_to_active(clip["id"])
                ok += 1
            except (ValueError, OSError) as e:
                log.warning("pendrive: %s rechazado: %s", p.name, e)
                bad += 1
            self.seen.add(key)
            write_json(self.db, {"files": sorted(self.seen)})
        msg = f"Pendrive: {ok} video(s) importados, convirtiendo…"
        if bad:
            msg += f" {bad} rechazado(s) (formato no soportado)"
        self._set_status(msg + " Ya podes sacar el pendrive.")
