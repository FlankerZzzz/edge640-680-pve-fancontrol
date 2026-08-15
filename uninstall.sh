#!/bin/bash
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo '请用 root 运行'; exit 1; }
systemctl disable --now fancontroller-pwm.timer fancontroller-pwm.service i2c-hwmon-devices.service || true
rm -f /etc/systemd/system/{i2c-hwmon-devices.service,fancontroller-pwm.service,fancontroller-pwm.timer} /etc/modules-load.d/lm75-tc654.conf /usr/local/sbin/{i2c-hwmon-devices.sh,fancontroller-pwm.sh}
systemctl daemon-reload
echo '服务和脚本已移除；内核模块未强制卸载。'
