#!/usr/bin/env bash
# Fija la resolucion de la salida HDMI (util con conversores HDMI -> AV para TV de tubo).
# Uso: sudo ./hdmi-mode.sh 576p|480p|720p|auto     -> luego reiniciar
#   576p = 720x576 a 50Hz (PAL, Argentina)   480p = 720x480 a 60Hz (NTSC)
#   720p = 1280x720 a 60Hz                   auto = lo que pida la pantalla/conversor
# Hace copia de seguridad de cmdline.txt la primera vez.
set -euo pipefail
MODE="${1:?Indicar 576p, 480p, 720p o auto}"
BOOT=/boot/firmware; [ -d $BOOT ] || BOOT=/boot
CMD=$BOOT/cmdline.txt
cp -n $CMD $CMD.antes-visuales
sed -i -e 's/ video=HDMI-A-1:[^ ]*//g' $CMD
case "$MODE" in
  576p) V="720x576@50D" ;;
  480p) V="720x480@60D" ;;
  720p) V="1280x720@60D" ;;
  auto) echo "Modo HDMI automatico. Reiniciar con: sudo reboot"; exit 0 ;;
  *) echo "Modo desconocido"; exit 1 ;;
esac
# la D fuerza la salida aunque el conversor no avise que esta conectado
sed -i "1 s/\$/ video=HDMI-A-1:$V/" $CMD
echo "HDMI fijado en $V. Reiniciar con: sudo reboot   (backup: $CMD.antes-visuales)"
