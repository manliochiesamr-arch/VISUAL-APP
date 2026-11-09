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
PKGS="ffmpeg python3-venv python3-pip python3-pygame python3-aiohttp python3-numpy openssl python3-opengl dnsmasq-base"
if dpkg -s $PKGS >/dev/null 2>&1; then
  echo "ya instalados (no hace falta internet)"
else
  apt-get update
  apt-get install -y $PKGS
fi

echo "==> Copiando app a $DEST"
mkdir -p "$DEST"
rsync -a --delete --exclude .git --exclude __pycache__ --exclude /venv --exclude /cert "$SRC/" "$DEST/" 2>/dev/null || cp -r "$SRC/." "$DEST/"
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
# regenerar si falta o si cert y clave no son un par valido
if ! openssl x509 -in "$DEST/cert/cert.pem" -noout 2>/dev/null || ! openssl pkey -in "$DEST/cert/key.pem" -noout 2>/dev/null; then
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

echo "==> Pendrives: se montan solos (solo lectura) en /media/visuales y la app importa los MP4"
mkdir -p /media/visuales
cat > /etc/udev/rules.d/90-visuales-usb.rules <<'RULE'
ACTION=="add", SUBSYSTEM=="block", ENV{ID_BUS}=="usb", ENV{ID_FS_USAGE}=="filesystem", RUN{program}+="/usr/bin/systemd-mount --no-block --collect -o ro /dev/%k /media/visuales/%k"
ACTION=="remove", SUBSYSTEM=="block", ENV{ID_BUS}=="usb", RUN{program}+="/usr/bin/systemd-mount --umount /media/visuales/%k"
RULE
udevadm control --reload-rules || true

echo "==> Actualizaciones por pendrive (ZIP de GitHub en la raiz del pendrive)"
cat > /etc/systemd/system/visuales-updater.service <<UNIT
[Unit]
Description=Visuales: actualizar desde pendrive
After=local-fs.target

[Service]
Environment=RUN_USER=$RUN_USER
ExecStart=$DEST/install/usb-updater.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

echo "==> Red: wifi conocido (trabajo/casa) o red propia VISUALES (ver install/red.sh)"
mkdir -p /etc/visuales
[ -f /etc/visuales/red.conf ] || cat > /etc/visuales/red.conf <<'CONF'
# Red propia de la Pi. Despues de cambiar: sudo systemctl start visuales-red
SSID=VISUALES
CLAVE=-          # "-" = abierta (el control queda protegido con el PIN de la app)
OCULTA=no        # si = no aparece en la lista de redes (iPhone: Wi-Fi > Otra...)
PAIS=AR
ESPERA=60        # modo auto: segundos buscando un wifi conocido antes de levantar VISUALES
CONF
. /etc/visuales/red.conf
raspi-config nonint do_wifi_country "$PAIS" 2>/dev/null || true
DATA="$RUN_HOME/visuales-data"
mkdir -p "$DATA"; chown "$RUN_USER" "$DATA"
for ph in boot apply addwifi; do
  case $ph in boot) U=visuales-red-boot ;; apply) U=visuales-red ;; addwifi) U=visuales-red-wifi ;; esac
  cat > /etc/systemd/system/$U.service <<UNIT
[Unit]
Description=Visuales: red ($ph)
After=NetworkManager.service
Wants=NetworkManager.service

[Service]
Type=oneshot
Environment=VISUALES_DATA=$DATA
ExecStart=$DEST/install/red.sh $ph
UNIT
done
cat >> /etc/systemd/system/visuales-red-boot.service <<'UNIT'

[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/systemd/system/visuales-red.path <<UNIT
[Unit]
Description=Visuales: la app cambio el modo de red

[Path]
PathChanged=$DATA/red-modo.txt
Unit=visuales-red.service

[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/systemd/system/visuales-red-wifi.path <<UNIT
[Unit]
Description=Visuales: la app agrego un wifi conocido

[Path]
PathChanged=$DATA/red-wifi-nuevo.txt
Unit=visuales-red-wifi.service

[Install]
WantedBy=multi-user.target
UNIT
# la red propia la decide red.sh: que NetworkManager no la levante solo
nmcli con modify visuales-ap connection.autoconnect no 2>/dev/null || true

systemctl daemon-reload
systemctl enable visuales-red-boot.service visuales-red.path visuales-red-wifi.path
systemctl start visuales-red.path visuales-red-wifi.path || true
systemctl enable visuales.service visuales-updater.service
systemctl restart visuales.service || true
# si esta instalacion la lanzo el propio updater, no reiniciarlo (se cortaria a si mismo)
systemctl is-active -q visuales-updater.service || systemctl start visuales-updater.service || true
echo
echo "Listo. Siguientes pasos:"
echo "  1) Red: se elige desde la app (Biblioteca > Red). Por defecto: wifi conocido y, si no hay, VISUALES"
echo "  2) HDMI fijo:       sudo $DEST/install/hdmi-mode.sh 576p   (opcional, si el conversor lo necesita)"
echo "  3) sudo reboot"
echo "Logs: journalctl -u visuales -f"
