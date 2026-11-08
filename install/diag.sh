#!/usr/bin/env bash
# Diagnostico de pantalla para Visuales. Uso: sudo /opt/visuales/install/diag.sh
echo "== placa";      tr -d '\0' < /proc/device-tree/model; echo
echo "== sistema";    . /etc/os-release; echo "$PRETTY_NAME"; uname -m
echo "== arranque";   systemctl get-default
echo "== escritorio"; systemctl is-active display-manager 2>/dev/null || echo "sin escritorio"
echo "== dri";        ls -l /dev/dri 2>&1
echo "== hdmi";       for c in /sys/class/drm/card*-*; do [ -e "$c/status" ] && echo "$(basename $c): $(cat $c/status)"; done
echo "== config.txt"; grep -nE "^[^#]*(dtoverlay=vc4|hdmi_|max_framebuffers)" /boot/firmware/config.txt 2>/dev/null
echo "== cmdline";    grep -o "video=[^ ]*" /boot/firmware/cmdline.txt 2>/dev/null || echo "sin video="
echo "== sdl";        dpkg -l 'libsdl2-2*' 2>/dev/null | awk '/^ii/{print $2, $3}'
echo "== app";        journalctl -u visuales -n 400 --no-pager | grep -E "render|sin pantalla|fps|Error|error" | tail -n 8
