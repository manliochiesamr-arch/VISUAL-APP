#!/usr/bin/env bash
# Crea un wifi propio en la Pi (NetworkManager, Bookworm). La Pi queda en 10.42.0.1.
# Uso: sudo ./setup-ap.sh NOMBRE_RED CLAVE [PAIS] [oculta]
#   CLAVE "-" = red abierta.  "oculta" = la red no se anuncia (en el iPhone: Wi-Fi > Otra...)
set -euo pipefail
SSID="${1:?Falta el nombre de la red}"
PASS="${2:?Falta la clave (minimo 8 caracteres)}"
COUNTRY="${3:-AR}"
HIDDEN=no; [ "${4:-}" = oculta ] && HIDDEN=yes
# correr como servicio aparte: asi no muere cuando se corta el SSH / Remote shell
if [ -z "${INVOCATION_ID:-}" ]; then
  [ "$(id -u)" = 0 ] || { echo "Ejecutar con sudo"; exit 1; }
  systemctl reset-failed visuales-ap-setup 2>/dev/null || true
  systemd-run --unit=visuales-ap-setup --collect -E KEEP="${KEEP:-0}" "$(readlink -f "$0")" "$@" >/dev/null
  echo "Activando la red '$SSID' en segundo plano. La conexion se va a cortar."
  echo "Log: /boot/firmware/ap-log.txt (tambien se puede leer desde la PC con la SD)"
  exit 0
fi
LOG=/boot/firmware/ap-log.txt; [ -d /boot/firmware ] || LOG=/boot/ap-log.txt
exec >"$LOG" 2>&1
date
# CLAVE "-" = red abierta, sin clave (solo para pruebas)
[ "$PASS" = "-" ] || [ ${#PASS} -ge 8 ] || { echo "La clave debe tener 8 caracteres o mas"; exit 1; }
command -v nmcli >/dev/null || { echo "Necesita NetworkManager (Raspberry Pi OS Bookworm)"; exit 1; }
# el modo "shared" de NetworkManager necesita dnsmasq para dar IPs a los telefonos
if ! command -v dnsmasq >/dev/null; then
  echo "Instalando dnsmasq-base (hace falta internet, por ejemplo con cable)..."
  apt-get install -y dnsmasq-base || { echo "ERROR: no se pudo instalar dnsmasq-base. Conecta la Pi a internet y repite."; exit 1; }
fi
rfkill unblock wifi 2>/dev/null || true
raspi-config nonint do_wifi_country "$COUNTRY" 2>/dev/null || true
# wifi al que esta conectada ahora (para volver si la red propia falla)
PREV=$(nmcli -t -f NAME,TYPE con show --active | awk -F: '$2=="802-11-wireless" && $1!="visuales-ap"{print $1; exit}')
nmcli con delete visuales-ap 2>/dev/null || true
nmcli con add type wifi ifname wlan0 con-name visuales-ap autoconnect no ssid "$SSID" \
  802-11-wireless.mode ap 802-11-wireless.band bg 802-11-wireless.channel 6 \
  ipv4.method shared ipv4.addresses 10.42.0.1/24 802-11-wireless.hidden $HIDDEN
if [ "$PASS" != "-" ]; then
  nmcli con modify visuales-ap wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PASS" \
    wifi-sec.proto rsn wifi-sec.pairwise ccmp wifi-sec.group ccmp wifi-sec.pmf disable
fi
# (WPA2-CCMP sin PMF: con PMF el wifi de la Pi 3 (brcmfmac) puede no emitir la red)
nmcli con modify visuales-ap connection.autoconnect-priority 100
if ! nmcli con up visuales-ap; then
  echo "ERROR: no se pudo levantar la red propia. Mandale este mensaje a Claude."
  nmcli dev status
  # no dejar la Pi incomunicada: borrar la red propia y volver al wifi anterior
  nmcli con delete visuales-ap 2>/dev/null || true
  [ -n "$PREV" ] && nmcli con up "$PREV" || true
  exit 1
fi
echo "Wifi '$SSID' activo. Desde el iPhone: conectarse y abrir http://10.42.0.1"
# red de prueba: si en 5 minutos no se conecta ningun equipo, se vuelve al wifi anterior
# (para no dejar la Pi incomunicada si la red no se ve). Saltear con KEEP=1.
if [ "${KEEP:-0}" != 1 ] && [ -n "$PREV" ]; then
  T0=$(date +%s)
  echo "Esperando un equipo conectado (hasta 5 minutos)..."
  for i in $(seq 60); do
    sleep 5
    iw dev wlan0 station dump 2>/dev/null | grep -E "^Station|authorized" || true
    [ $((i % 6)) = 1 ] && { echo "--- $(date +%T)"; iw dev wlan0 info | grep -E "ssid|type|channel"; } || true
    # un equipo cuenta solo si paso la clave y recibio IP (DHCPACK del dnsmasq de NetworkManager)
    if journalctl -u NetworkManager --since "@$T0" --no-pager 2>/dev/null | grep -q "DHCPACK(wlan0)"; then
      nmcli con modify visuales-ap connection.autoconnect yes
      echo "Equipo conectado: la red queda fija (tambien al reiniciar)."; exit 0
    fi
  done
  echo "Nadie se conecto en 5 minutos: vuelvo al wifi '$PREV'."
  nmcli dev status; journalctl -u NetworkManager -n 60 --no-pager; dmesg | grep -i brcm | tail -n 20 || true
  nmcli con delete visuales-ap 2>/dev/null || true
  nmcli con up "$PREV" || true
  exit 1
fi
nmcli con modify visuales-ap connection.autoconnect yes
echo "OJO: si estabas conectado a la Pi por wifi (SSH), se corto. Usar cable o teclado."
