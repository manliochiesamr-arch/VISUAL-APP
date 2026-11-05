"""Utilidades compartidas."""
import json
import os
import time


def write_json(path, obj):
    """Escritura atomica con reintentos: en Windows el antivirus/OneDrive/indexador
    puede tener el archivo abierto un instante y os.replace falla con PermissionError."""
    tmp = path.with_suffix(".tmp")
    data = json.dumps(obj, indent=1)
    for i in range(20):
        try:
            tmp.write_text(data, encoding="utf-8")
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05 * (i + 1))
    # ultimo intento sin atomicidad antes de rendirse
    path.write_text(data, encoding="utf-8")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))
