#!/bin/bash
# Visuales - modo test en Mac (tambien sirve en Linux: bash INICIAR-MAC.command)
# Doble click en Finder. La primera vez descarga uv (Python 3.12 portable) y ffmpeg; no toca el Python del sistema.
cd "$(dirname "$0")" || exit 1
echo
echo " ===== VISUALES - modo test en Mac ====="
echo
mkdir -p tools

fallo() {
  echo
  echo "ERROR: $1"
  echo "Mandame una captura de esta ventana."
  read -r -p "Enter para cerrar..." _
  exit 1
}

# ---------- 1. uv: trae su propio Python 3.12 portable ----------
UV="$PWD/tools/uv/uv"
if [ ! -x "$UV" ]; then
  case "$(uname -s)-$(uname -m)" in
    Darwin-arm64)  T=aarch64-apple-darwin ;;
    Darwin-x86_64) T=x86_64-apple-darwin ;;
    Linux-x86_64)  T=x86_64-unknown-linux-gnu ;;
    Linux-aarch64) T=aarch64-unknown-linux-gnu ;;
    *) fallo "sistema no soportado: $(uname -s) $(uname -m)" ;;
  esac
  echo "Descargando uv, solo la primera vez..."
  mkdir -p tools/uv
  curl -fsSL "https://github.com/astral-sh/uv/releases/latest/download/uv-$T.tar.gz" \
    | tar -xz -C tools/uv --strip-components 1 || fallo "no se pudo descargar uv. Revisa la conexion a internet."
fi
export UV_PYTHON_INSTALL_DIR="$PWD/tools/python"
export UV_CACHE_DIR="$PWD/tools/cache"
echo "[ok] uv"

# ---------- 2. Entorno Python 3.12 + librerias ----------
if [ ! -f .venv/visuales-ok2.txt ]; then
  echo "Preparando Python 3.12 y librerias, la primera vez tarda un poco..."
  [ -x .venv/bin/python ] || "$UV" venv .venv --python 3.12 || fallo "no se pudo crear el entorno de Python"
  "$UV" pip install --python .venv/bin/python -r requirements.txt || fallo "no se pudieron instalar las librerias"
  echo ok > .venv/visuales-ok2.txt
fi
echo "[ok] Python y librerias"

# ---------- 3. ffmpeg (el del sistema si hay, si no uno portable) ----------
if command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null; then
  :
else
  if [ ! -x tools/ffmpeg/ffmpeg ]; then
    echo "Descargando ffmpeg, solo la primera vez..."
    "$UV" pip install --python .venv/bin/python -q static-ffmpeg || fallo "no se pudo descargar ffmpeg"
    FF=$(.venv/bin/python -c "from static_ffmpeg import run; print('\n'.join(run.get_or_fetch_platform_executables_else_raise()))") \
      || fallo "no se pudo descargar ffmpeg. Alternativa: instalar Homebrew y correr: brew install ffmpeg"
    mkdir -p tools/ffmpeg
    ln -sf "$(echo "$FF" | sed -n 1p)" tools/ffmpeg/ffmpeg
    ln -sf "$(echo "$FF" | sed -n 2p)" tools/ffmpeg/ffprobe
  fi
  export PATH="$PWD/tools/ffmpeg:$PATH"
fi
echo "[ok] ffmpeg"

# ---------- 4. Arrancar ----------
# los videos y shows viven fuera de la carpeta del programa: sobreviven a actualizaciones
export VISUALES_DATA="$HOME/visuales-datos"
echo
echo " MODO TEST: la red y el pendrive de la Pi estan simulados."
echo " Se abre una ventana con la salida de video y el control en el navegador."
echo " Videos y shows guardados en: $VISUALES_DATA"
echo " Pendrive simulado: copia videos a $VISUALES_DATA/pendrive/mi-pendrive"
echo " Si el Mac pregunta si Python puede aceptar conexiones entrantes: Permitir (para usarlo desde el iPhone)."
echo " Para salir: Esc en la ventana de video, o cerrar esta ventana."
echo
( sleep 5; if command -v open >/dev/null; then open http://localhost:8080; else xdg-open http://localhost:8080 >/dev/null 2>&1; fi ) &
.venv/bin/python -m visuales --test "$@"
echo
echo "Visuales se cerro."
read -r -p "Enter para cerrar..." _
