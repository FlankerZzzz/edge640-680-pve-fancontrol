#!/bin/bash
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo '请用 root 运行'; exit 1; }
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
