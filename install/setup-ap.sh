#!/usr/bin/env bash
# Configura la red propia de la Pi (nombre, clave, oculta). La Pi queda en 10.42.0.1.
# Uso: sudo ./setup-ap.sh NOMBRE_RED CLAVE|- [PAIS] [oculta]
#   CLAVE "-" = red abierta.  "oculta" = no aparece en la lista (iPhone: Wi-Fi > Otra...)
# Cuando se usa la red propia lo decide red.sh (modo auto / visuales / wifi, se elige desde la app).
# Esto solo cambia sus datos y, si ahora mismo esta activa, la vuelve a levantar.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Ejecutar con sudo"; exit 1; }
SSID="${1:?Falta el nombre de la red}"
PASS="${2:?Falta la clave (8 caracteres o mas, o - para red abierta)}"
COUNTRY="${3:-AR}"
HIDDEN=no; [ "${4:-}" = oculta ] && HIDDEN=si
[ "$PASS" = "-" ] || [ ${#PASS} -ge 8 ] || { echo "La clave debe tener 8 caracteres o mas"; exit 1; }
CONF=/etc/visuales/red.conf
mkdir -p /etc/visuales
ESPERA=60; [ -f $CONF ] && ESPERA=$(. $CONF; echo "${ESPERA:-60}")
cat > $CONF <<CONF
# Red propia de la Pi. Despues de cambiar: sudo systemctl start visuales-red
SSID='$SSID'
CLAVE='$PASS'    # "-" = abierta (el control queda protegido con el PIN de la app)
OCULTA=$HIDDEN   # si = no aparece en la lista de redes
PAIS=$COUNTRY
ESPERA=$ESPERA   # modo auto: segundos buscando un wifi conocido antes de levantar VISUALES
CONF
raspi-config nonint do_wifi_country "$COUNTRY" 2>/dev/null || true
echo "Red propia: '$SSID' $( [ "$PASS" = - ] && echo abierta || echo con clave ) oculta=$HIDDEN"
if nmcli -t -f NAME con show --active | grep -qx visuales-ap; then
  echo "Esta activa: la vuelvo a levantar con los datos nuevos (se corta la conexion unos segundos)."
  nmcli con delete visuales-ap >/dev/null 2>&1 || true
  systemctl start --no-block visuales-red.service
else
  nmcli con delete visuales-ap >/dev/null 2>&1 || true
  echo "Se usa la proxima vez que la Pi levante VISUALES (modo auto sin wifi conocido, o 'Forzar VISUALES' en la app)."
fi
