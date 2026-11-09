#!/usr/bin/env bash
# Corre como root (servicio visuales-updater). Si un pendrive montado en /media/visuales
# tiene en su raiz un ZIP del repo (VISUAL-APP*.zip, el "Download ZIP" de GitHub),
# instala esa version una sola vez. Estado para la app: /var/lib/visuales/update-status
set -uo pipefail
STATE=${STATE:-/var/lib/visuales}; MEDIA=${MEDIA:-/media/visuales}; mkdir -p $STATE; chmod 755 $STATE
status() { echo "$1" > $STATE/update-status; chmod 644 $STATE/update-status; echo "$1"; }
while true; do
  for z in $MEDIA/*/VISUAL-APP*.zip $MEDIA/*/visual-app*.zip; do
    [ -f "$z" ] || continue
    sum=$(sha256sum "$z" | cut -c1-16)
    grep -qx "$sum" $STATE/applied 2>/dev/null && continue
    status "Actualizando la app desde el pendrive ($(basename "$z"))…"
    W=$(mktemp -d)
    if python3 -m zipfile -e "$z" "$W" && INST=$(ls -d "$W"/*/install/install.sh 2>/dev/null | head -n1) && [ -n "$INST" ]; then
      chmod +x "$INST" "$(dirname "$INST")"/*.sh
      if SUDO_USER="$RUN_USER" bash "$INST" > $STATE/update-log.txt 2>&1; then
        echo "$sum" >> $STATE/applied
        status "App actualizada desde el pendrive ($(date "+%d/%m %H:%M"))"
      else
        echo "$sum" >> $STATE/applied   # no reintentar en bucle; ver update-log.txt
        status "Fallo la actualizacion: $(tail -n 1 $STATE/update-log.txt)"
      fi
    else
      echo "$sum" >> $STATE/applied
      status "El ZIP del pendrive no es de Visuales o esta danado"
    fi
    rm -rf "$W"
  done
  sleep 5
done
