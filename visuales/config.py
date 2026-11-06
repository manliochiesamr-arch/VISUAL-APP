"""Configuracion global. Se puede sobreescribir con variables de entorno VISUALES_*."""
import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name, default, cast=str):
    v = os.environ.get("VISUALES_" + name)
    if v is None:
        return default
    if cast is bool:
        return v.lower() in ("1", "true", "yes", "si")
    return cast(v)


@dataclass
class Config:
    # Tamano de ventana en modo --window (en pantalla completa se usa la resolucion del HDMI)
    width: int = field(default_factory=lambda: _env("WIDTH", 720, int))
    height: int = field(default_factory=lambda: _env("HEIGHT", 576, int))
    # Tamano maximo de los clips convertidos (se conserva la proporcion: 16:9 -> 1024x576, 4:3 -> 768x576)
    # En la Pi 3 se usa 360 de alto (VISUALES_CLIP_H=360) para poder decodificar dos clips a la vez
    clip_max_h: int = field(default_factory=lambda: _env("CLIP_H", 576, int))

    @property
    def clip_max_w(self):
        return int(self.clip_max_h * 16 / 9) // 2 * 2
    fps: int = field(default_factory=lambda: _env("FPS", 25, int))
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA", str(Path.home() / "visuales-data"))))
    http_port: int = field(default_factory=lambda: _env("HTTP_PORT", 8080, int))
    https_port: int = field(default_factory=lambda: _env("HTTPS_PORT", 8443, int))
    cert_file: str = field(default_factory=lambda: _env("CERT", ""))
    key_file: str = field(default_factory=lambda: _env("KEY", ""))
    renderer: str = field(default_factory=lambda: _env("RENDERER", "auto"))  # auto | gl | sdl
    fullscreen: bool = field(default_factory=lambda: _env("FULLSCREEN", True, bool))
    # Solo se aceptan MP4 con video H.264 (evita HEVC/archivos pesados en la Pi)
    allowed_codecs: tuple = ("h264",)
    max_upload_mb: int = field(default_factory=lambda: _env("MAX_UPLOAD_MB", 2048, int))

    @property
    def clips_dir(self):
        return self.data_dir / "clips"

    @property
    def thumbs_dir(self):
        return self.data_dir / "thumbs"

    @property
    def incoming_dir(self):
        return self.data_dir / "incoming"
