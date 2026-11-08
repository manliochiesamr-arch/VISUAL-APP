#!/usr/bin/env bash
# Crea un wifi propio en la Pi (NetworkManager, Bookworm). La Pi queda en 10.42.0.1.
# Uso: sudo ./setup-ap.sh NOMBRE_RED CLAVE [PAIS]
set -euo pipefail
SSID="${1:?Falta el nombre de la red}"
PASS="${2:?Falta la clave (minimo 8 caracteres)}"
COUNTRY="${3:-AR}"
[ ${#PASS} -ge 8 ] || { echo "La clave debe tener 8 caracteres o mas"; exit 1; }
command -v nmcli >/dev/null || { echo "Necesita NetworkManager (Raspberry Pi OS Bookworm)"; exit 1; }
# el modo "shared" de NetworkManager necesita dnsmasq para dar IPs a los telefonos
if ! command -v dnsmasq >/dev/null; then
  echo "Instalando dnsmasq-base (hace falta internet, por ejemplo con cable)..."
  apt-get install -y dnsmasq-base || { echo "ERROR: no se pudo instalar dnsmasq-base. Conecta la Pi a internet y repite."; exit 1; }
fi
rfkill unblock wifi 2>/dev/null || true
raspi-config nonint do_wifi_country "$COUNTRY" 2>/dev/null || true
nmcli con delete visuales-ap 2>/dev/null || true
nmcli con add type wifi ifname wlan0 con-name visuales-ap autoconnect yes ssid "$SSID" \
  802-11-wireless.mode ap 802-11-wireless.band bg 802-11-wireless.channel 6 \
  ipv4.method shared ipv4.addresses 10.42.0.1/24 \
  wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PASS"
nmcli con modify visuales-ap connection.autoconnect-priority 100
if ! nmcli con up visuales-ap; then
  echo "ERROR: no se pudo levantar la red propia. Mandale este mensaje a Claude."
  nmcli dev status
  exit 1
fi
echo "Wifi '$SSID' activo. Desde el iPhone: conectarse y abrir http://10.42.0.1"
echo "OJO: si estabas conectado a la Pi por wifi (SSH), se corto. Usar cable o teclado."
