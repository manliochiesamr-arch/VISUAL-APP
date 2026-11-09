#!/usr/bin/env bash
# Red de la Pi: decide entre un wifi conocido (trabajo, casa) y la red propia VISUALES.
#
# Modo (lo cambia la app, o un archivo en la SD para rescate):
#   auto      al arrancar busca un wifi conocido; si en ESPERA segundos no hay ninguno, levanta VISUALES
#   visuales  siempre VISUALES (dia del show)
#   wifi      nunca VISUALES (solo wifi conocido)
#
# Rescate sin app: crear en la SD (particion "bootfs") un archivo visuales-red.txt con una sola
# palabra: auto, visuales o wifi. Se aplica al arrancar y se renombra a visuales-red.usado.txt
#
# Lo corre systemd como root: al arrancar (visuales-red.service), cada vez que la app cambia
# el modo (visuales-red.path) y cuando agrega un wifi conocido (visuales-red-wifi.path).
set -u
DATA="${VISUALES_DATA:?falta VISUALES_DATA}"
MODE_FILE="$DATA/red-modo.txt"
WIFI_FILE="$DATA/red-wifi-nuevo.txt"   # linea 1: nombre de la red, linea 2: clave
CONF=/etc/visuales/red.conf
BOOT=/boot/firmware; [ -d $BOOT ] || BOOT=/boot
LOG=$BOOT/red-log.txt
PHASE="${1:-apply}"   # boot | apply | addwifi

# log corto, legible desde la PC con la SD
[ -f "$LOG" ] && [ "$(wc -l < "$LOG")" -gt 400 ] && tail -n 200 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
exec >>"$LOG" 2>&1
log() { echo "$(date '+%F %T') [$PHASE] $*"; }
# una sola instancia a la vez (arranque y app pueden coincidir); al re-ejecutarse ya tiene el lock
if [ -z "${RED_LOCK:-}" ]; then
  exec 9>/run/visuales-red.lock; flock 9; export RED_LOCK=1
fi

SSID=VISUALES; CLAVE=-; OCULTA=no; PAIS=AR; ESPERA=60
[ -f $CONF ] && . $CONF

status() { echo "$*" > /run/visuales-red 2>/dev/null || true; }

wifi_actual() {  # nombre de la conexion activa en wlan0 (vacio si ninguna)
  nmcli -t -f GENERAL.STATE,GENERAL.CONNECTION dev show wlan0 2>/dev/null |
    awk -F: '/GENERAL.STATE/{ok=($2 ~ /^100/)} /GENERAL.CONNECTION/{c=$2} END{if(ok) print c}'
}

ap_ensure() {
  local hidden=no; [ "$OCULTA" = si ] || [ "$OCULTA" = yes ] && hidden=yes
  if ! nmcli -t -f NAME con show | grep -qx visuales-ap; then
    log "creo la red propia '$SSID' (oculta=$hidden)"
    nmcli con add type wifi ifname wlan0 con-name visuales-ap autoconnect no ssid "$SSID" \
      802-11-wireless.mode ap 802-11-wireless.band bg 802-11-wireless.channel 6 \
      ipv4.method shared ipv4.addresses 10.42.0.1/24 >/dev/null
  fi
  # la decide este script, nunca NetworkManager solo (si no, le gana al wifi de casa)
  nmcli con modify visuales-ap connection.autoconnect no 802-11-wireless.ssid "$SSID" \
    802-11-wireless.hidden $hidden
  if [ "$CLAVE" != "-" ] && [ ${#CLAVE} -ge 8 ]; then
    nmcli con modify visuales-ap wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$CLAVE" \
      wifi-sec.proto rsn wifi-sec.pairwise ccmp wifi-sec.group ccmp wifi-sec.pmf disable
  else
    nmcli con modify visuales-ap remove 802-11-wireless-security 2>/dev/null || true
  fi
}

ap_up() {
  ap_ensure
  if nmcli con up visuales-ap >/dev/null; then
    log "VISUALES activa (http://10.42.0.1)"; status "visuales"
    return 0
  fi
  log "ERROR: no levanto VISUALES"; nmcli dev status
  status "error"
  return 1
}

wifi_up() {
  nmcli con down visuales-ap >/dev/null 2>&1 || true
  nmcli dev wifi rescan >/dev/null 2>&1 || true
  nmcli dev connect wlan0 >/dev/null 2>&1 || true
}

esperar_wifi() {  # espera hasta $1 segundos un wifi conocido
  local i
  for i in $(seq "$1"); do
    local c; c=$(wifi_actual)
    if [ -n "$c" ] && [ "$c" != visuales-ap ]; then
      log "conectado al wifi '$c'"; status "wifi:$c"
      return 0
    fi
    sleep 1
  done
  return 1
}

rfkill unblock wifi 2>/dev/null || true

# ---- rescate desde la SD
if [ -f $BOOT/visuales-red.txt ]; then
  m=$(tr -dc 'a-z' < $BOOT/visuales-red.txt)
  case "$m" in auto|visuales|wifi) echo "$m" > "$MODE_FILE"; log "modo '$m' desde la SD" ;; esac
  mv -f $BOOT/visuales-red.txt $BOOT/visuales-red.usado.txt
fi

# ---- wifi nuevo cargado desde la app
if [ -f "$WIFI_FILE" ]; then
  NSSID=$(sed -n 1p "$WIFI_FILE" | tr -d '\r'); NPASS=$(sed -n 2p "$WIFI_FILE" | tr -d '\r')
  rm -f "$WIFI_FILE"
  if [ -n "$NSSID" ]; then
    nmcli con delete "wifi-$NSSID" >/dev/null 2>&1 || true
    if [ -n "$NPASS" ]; then
      nmcli con add type wifi ifname wlan0 con-name "wifi-$NSSID" ssid "$NSSID" autoconnect yes \
        wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$NPASS" >/dev/null
    else
      nmcli con add type wifi ifname wlan0 con-name "wifi-$NSSID" ssid "$NSSID" autoconnect yes >/dev/null
    fi
    log "wifi conocido agregado: '$NSSID'"
  fi
fi
[ "$PHASE" = addwifi ] && exit 0   # solo se agrego un wifi: no tocar la red actual

leer_modo() { local m; m=$(tr -dc 'a-z' 2>/dev/null < "$MODE_FILE"); echo "${m:-auto}"; }
MODE=$(leer_modo)
modo_cambio() { [ "$(leer_modo)" != "$MODE" ]; }
log "modo $MODE"
ACTUAL=$(wifi_actual)

case "$MODE" in
  visuales)
    [ "$ACTUAL" = visuales-ap ] && { status "visuales"; exit 0; }
    ap_up || { wifi_up; esperar_wifi 30; exit 1; }
    # cambiado desde la app: si en 5 minutos no se conecta ningun telefono (la red no se ve),
    # volver a auto para no dejar la Pi incomunicada. Al arrancar no se vigila (dia del show).
    if [ "$PHASE" = apply ]; then
      T0=$(date +%s)
      for i in $(seq 60); do
        sleep 5
        journalctl -u NetworkManager --since "@$T0" --no-pager 2>/dev/null | grep -q "DHCPACK(wlan0)" &&
          { log "telefono conectado a VISUALES"; exit 0; }
        modo_cambio && exec "$0" apply
      done
      log "nadie se conecto a VISUALES en 5 minutos: vuelvo a modo auto"
      echo auto > "$MODE_FILE"
      exec "$0" apply
    fi
    ;;
  wifi)
    wifi_up
    esperar_wifi 40 || { log "ningun wifi conocido a la vista"; status "ninguna"; }
    ;;
  *)
    if [ -n "$ACTUAL" ] && [ "$ACTUAL" != visuales-ap ]; then
      log "ya en el wifi '$ACTUAL'"; status "wifi:$ACTUAL"; exit 0
    fi
    [ "$ACTUAL" = visuales-ap ] && wifi_up
    esperar_wifi "$ESPERA" || { log "sin wifi conocido en ${ESPERA}s: levanto VISUALES"; ap_up; }
    ;;
esac
# si la app cambio el modo mientras esperabamos, aplicarlo ahora
modo_cambio && exec "$0" apply
exit 0
