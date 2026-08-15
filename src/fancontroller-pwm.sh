#!/bin/bash
set -euo pipefail
exec 9>/run/fancontroller-pwm.lock; flock -n 9 || exit 0
log=/var/log/fancontroller-pwm.log; state=/var/lib/fancontroller-pwm/state
mkdir -p "$(dirname "$state")"; touch "$log"
sensor="${TEMP_SENSOR:-coretemp-isa-0000}"; min="${MIN_TEMP:-45}"; max="${MAX_TEMP:-59}"; stop="${FAN_STOP_TEMP:-45}"; full="${FAN_FULL_TEMP:-60}"; cool="${COOLDOWN_SECONDS:-120}"
temp=$(sensors "$sensor" 2>/dev/null | awk '/Package id 0:/ {gsub(/\+/,"",$4); sub(/°C/,"",$4); print int($4); exit}')
[ -n "${temp:-}" ] || exit 1
hw=$(for d in /sys/class/hwmon/hwmon*; do [ "$(cat "$d/name" 2>/dev/null)" = tc654 ] && echo "$d"; done | head -1)
[ -n "${hw:-}" ] || exit 1
echo 1 > "$hw/pwm1_enable" 2>/dev/null || true; echo 1 > "$hw/pwm1_mode" 2>/dev/null || true
old=$(awk '{print $1}' "$state" 2>/dev/null || echo 0); last=$(awk '{print $2}' "$state" 2>/dev/null || echo 0); now=$(date +%s); pwm=$old
if (( temp >= full )); then pwm=255; elif (( temp <= stop )); then pwm=0; else pwm=$(( (temp-stop)*255/(full-stop) )); fi
if (( pwm < old && now-last < cool )); then pwm=$old; fi
echo "$pwm" > "$hw/pwm1"; printf '%s temp=%sC pwm=%s\n' "$(date -Is)" "$temp" "$pwm" >> "$log"; echo "$pwm $now" > "$state"
