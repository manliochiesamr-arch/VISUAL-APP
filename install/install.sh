#!/usr/bin/env bash
# Instala Visuales en una Raspberry Pi (Raspberry Pi OS Bookworm, 64-bit recomendado).
# Uso:  sudo ./install/install.sh            (desde la carpeta del proyecto)
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Ejecutar con sudo"; exit 1; }
RUN_USER="${SUDO_USER:-}"
if [ -z "$RUN_USER" ] || [ "$RUN_USER" = root ]; then
  echo "Ejecutalo con sudo desde tu usuario normal (ej: sudo ./install/install.sh), no como root."
  exit 1
fi
RUN_HOME=$(getent passwd "$RUN_USER" | cut -d: -f6)
SRC="$(cd "$(dirname "$0")/.." && pwd)"
DEST=/opt/visuales

echo "==> Paquetes del sistema"
apt-get update
apt-get install -y ffmpeg python3-venv python3-pip python3-pygame python3-aiohttp python3-numpy openssl python3-opengl

echo "==> Copiando app a $DEST"
mkdir -p "$DEST"
rsync -a --delete --exclude .git --exclude __pycache__ "$SRC/" "$DEST/" 2>/dev/null || cp -r "$SRC/." "$DEST/"
python3 -m venv --system-site-packages "$DEST/venv"
MODEL=$(tr -d '\0' < /proc/device-tree/model 2>/dev/null || echo "?")
echo "Placa: $MODEL"
EXTRA_ENV=""
if echo "$MODEL" | grep -q "Raspberry Pi 3"; then
  # Pi 3: GPU VideoCore IV (OpenGL 2.1) y CPU justa -> render gl2 y clips de 360p
  EXTRA_ENV="Environment=VISUALES_CLIP_H=360"
else
  "$DEST/venv/bin/pip" install --upgrade "moderngl>=5.8" || echo "AVISO: moderngl no se instalo; se usara otro render (funciona igual)"
fi

echo "==> Certificado HTTPS local (para el microfono del iPhone)"
mkdir -p "$DEST/cert"
if [ ! -f "$DEST/cert/cert.pem" ]; then
  openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
    -keyout "$DEST/cert/key.pem" -out "$DEST/cert/cert.pem" \
    -subj "/CN=visuales" -addext "subjectAltName=IP:10.42.0.1,DNS:visuales.local"
fi
chown -R "$RUN_USER" "$DEST/cert"

echo "==> Servicio systemd (usuario $RUN_USER)"
cat > /etc/systemd/system/visuales.service <<UNIT
[Unit]
Description=Visuales en vivo
After=network.target

[Service]
User=$RUN_USER
SupplementaryGroups=video render input
WorkingDirectory=$DEST
Environment=VISUALES_DATA=$RUN_HOME/visuales-data
Environment=VISUALES_HTTP_PORT=80
Environment=VISUALES_HTTPS_PORT=443
Environment=VISUALES_CERT=$DEST/cert/cert.pem
Environment=VISUALES_KEY=$DEST/cert/key.pem
Environment=SDL_VIDEODRIVER=kmsdrm
$EXTRA_ENV
Environment=PYTHONUNBUFFERED=1
AmbientCapabilities=CAP_NET_BIND_SERVICE
ExecStart=$DEST/venv/bin/python -m visuales
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable visuales.service
echo
echo "Listo. Siguientes pasos:"
echo "  1) Red propia:      sudo $DEST/install/setup-ap.sh VISUALES clave-de-8-o-mas"
echo "  2) HDMI fijo:       sudo $DEST/install/hdmi-mode.sh 576p   (opcional, si el conversor lo necesita)"
echo "  3) sudo reboot"
echo "Logs: journalctl -u visuales -f"
