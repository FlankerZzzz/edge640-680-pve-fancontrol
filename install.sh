#!/bin/bash
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then
  command -v sudo >/dev/null 2>&1 || { echo '请以 root 运行：su - 或直接 ./install.sh'; exit 1; }
  exec sudo bash "$0" "$@"
fi
DIR="$(cd "$(dirname "$0")" && pwd)"
install -D -m 0755 "$DIR/src/i2c-hwmon-devices.sh" /usr/local/sbin/i2c-hwmon-devices.sh
install -D -m 0755 "$DIR/src/fancontroller-pwm.sh" /usr/local/sbin/fancontroller-pwm.sh
install -D -m 0644 "$DIR/systemd/i2c-hwmon-devices.service" /etc/systemd/system/i2c-hwmon-devices.service
install -D -m 0644 "$DIR/systemd/fancontroller-pwm.service" /etc/systemd/system/fancontroller-pwm.service
install -D -m 0644 "$DIR/systemd/fancontroller-pwm.timer" /etc/systemd/system/fancontroller-pwm.timer
install -D -m 0644 "$DIR/systemd/modules-load.conf" /etc/modules-load.d/lm75-tc654.conf
systemctl daemon-reload
systemctl enable --now i2c-hwmon-devices.service
systemctl enable --now fancontroller-pwm.timer
echo '安装完成：systemctl status fancontroller-pwm.timer; sensors'
