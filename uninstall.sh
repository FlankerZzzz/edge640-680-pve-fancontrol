#!/bin/bash
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then
  command -v sudo >/dev/null 2>&1 || { echo '请以 root 运行：su - 或直接 ./uninstall.sh'; exit 1; }
  exec sudo bash "$0" "$@"
fi
systemctl disable --now fancontroller-pwm.timer fancontroller-pwm.service i2c-hwmon-devices.service || true
rm -f /etc/systemd/system/{i2c-hwmon-devices.service,fancontroller-pwm.service,fancontroller-pwm.timer} /etc/modules-load.d/lm75-tc654.conf /usr/local/sbin/{i2c-hwmon-devices.sh,fancontroller-pwm.sh}
systemctl daemon-reload
echo '服务和脚本已移除；内核模块未强制卸载。'
