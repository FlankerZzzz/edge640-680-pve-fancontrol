#!/bin/bash
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then
  command -v sudo >/dev/null 2>&1 || { echo '请以 root 运行：su - 或直接 ./uninstall.sh'; exit 1; }
  exec sudo bash "$0" "$@"
fi
systemctl disable --now fancontroller-web.service fancontroller-watchdog.timer fancontroller-pwm.timer || true
systemctl stop fancontroller-pwm.service fancontroller-watchdog.service fancontroller-failsafe.service || true
if [ -x /usr/local/sbin/fancontroller-failsafe.sh ]; then
  /usr/local/sbin/fancontroller-failsafe.sh uninstall_full_speed || true
fi
systemctl disable --now i2c-hwmon-devices.service || true
rm -f /etc/systemd/system/{i2c-hwmon-devices.service,fancontroller-pwm.service,fancontroller-pwm.timer} /etc/modules-load.d/lm75-tc654.conf /usr/local/sbin/{i2c-hwmon-devices.sh,fancontroller-pwm.sh}
rm -f /etc/systemd/system/{fancontroller-web.service,fancontroller-failsafe.service,fancontroller-watchdog.service,fancontroller-watchdog.timer} /usr/local/sbin/fancontroller-failsafe.sh
rm -f /usr/local/lib/edge-fancontrol/fancontrol.py /usr/local/lib/edge-fancontrol/fancontrol_web.py /usr/local/lib/edge-fancontrol/web/{index.html,style.css,app.js}
# Keep logrotate to enforce retention on preserved logs after uninstall.
rm -f /var/lib/fancontroller-pwm/web-state.json /var/lib/fancontroller-pwm/state
systemctl daemon-reload
echo '服务和脚本已移除；已请求全速。保留配置、令牌、历史日志和 30 天轮转规则。'
