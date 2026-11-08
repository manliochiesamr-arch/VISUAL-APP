#!/usr/bin/env bash
# PIN para controlar Visuales desde el telefono.
# Uso: sudo ./set-pin.sh 1234     (sin PIN: sudo ./set-pin.sh -)
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Ejecutar con sudo"; exit 1; }
PIN="${1:?Indicar el PIN, o - para quitarlo}"
D=/etc/systemd/system/visuales.service.d
mkdir -p $D
if [ "$PIN" = "-" ]; then rm -f $D/pin.conf; echo "PIN quitado"; else
  printf '[Service]\nEnvironment=VISUALES_PIN=%s\n' "$PIN" > $D/pin.conf; chmod 600 $D/pin.conf; echo "PIN fijado"; fi
systemctl daemon-reload
systemctl restart visuales
