#!/bin/bash
# Independent emergency writer: no Python, temperature, config or state dependency.
set -u
reason="${1:-controller_failed}"
if [ "$reason" = watchdog ]; then
  now=$(date +%s)
  updated=$(stat -c %Y /var/lib/fancontroller-pwm/web-state.json 2>/dev/null || echo 0)
  if systemctl is-active --quiet fancontroller-pwm.timer && (( now >= updated && now - updated <= 35 )); then
    exit 0
  fi
  reason=control_stale_or_timer_inactive
fi
result=1
found=0
for device in /sys/class/hwmon/hwmon*; do
  [ -r "$device/name" ] || continue
  [ "$(<"$device/name")" = tc654 ] || continue
  found=1
  if { echo 1 > "$device/pwm1_mode" && echo 255 > "$device/pwm1"; }; then
    actual=$(cat "$device/pwm1" 2>/dev/null || echo unknown)
    if [ "$actual" = 255 ]; then result=0; else result=1; break; fi
  else
    result=1
    break
  fi
done
message="$(date -Is) FALLBACK reason=$reason requested_pwm=255 found=$found result=$result"
echo "$message" >&2
# Reopened for every write, so logrotate can rename without copytruncate races.
echo "$message" >> /var/log/fancontroller-pwm.log || true
exit "$result"
