#!/bin/bash
set -Eeuo pipefail
if [ "$(id -u)" -ne 0 ]; then
  command -v sudo >/dev/null 2>&1 || { echo '请以 root 运行：su - 或直接 ./install.sh'; exit 1; }
  exec sudo bash "$0" "$@"
fi
DIR="$(cd "$(dirname "$0")" && pwd)"
trap 'status=$?; bash "$DIR/src/fancontroller-failsafe.sh" install_error || true; exit "$status"' ERR
for dependency in python3 logrotate; do
  if ! command -v "$dependency" >/dev/null 2>&1; then
    apt-get update
    apt-get install -y "$dependency"
  fi
done
modprobe lm75
modprobe tc654
modprobe coretemp
# Verify scripts before interrupting the existing controller.
python3 -c 'import ast,sys; [ast.parse(open(p, encoding="utf-8").read()) for p in sys.argv[1:]]' "$DIR/src/fancontrol.py" "$DIR/src/fancontrol_web.py"
systemctl stop fancontroller-pwm.timer fancontroller-web.service 2>/dev/null || true
systemctl stop fancontroller-pwm.service 2>/dev/null || true
install -d -m 0700 /etc/edge-fancontrol
install -d -m 0755 /usr/local/lib/edge-fancontrol/web
install -d -m 0700 /var/lib/fancontroller-pwm
install -m 0644 "$DIR/src/fancontrol.py" "$DIR/src/fancontrol_web.py" /usr/local/lib/edge-fancontrol/
install -m 0644 "$DIR/src/web/index.html" "$DIR/src/web/style.css" "$DIR/src/web/app.js" /usr/local/lib/edge-fancontrol/web/
install -D -m 0755 "$DIR/src/i2c-hwmon-devices.sh" /usr/local/sbin/i2c-hwmon-devices.sh
install -D -m 0755 "$DIR/src/fancontroller-pwm.sh" /usr/local/sbin/fancontroller-pwm.sh
install -D -m 0755 "$DIR/src/fancontroller-failsafe.sh" /usr/local/sbin/fancontroller-failsafe.sh
install -D -m 0644 "$DIR/systemd/i2c-hwmon-devices.service" /etc/systemd/system/i2c-hwmon-devices.service
install -D -m 0644 "$DIR/systemd/fancontroller-pwm.service" /etc/systemd/system/fancontroller-pwm.service
install -D -m 0644 "$DIR/systemd/fancontroller-pwm.timer" /etc/systemd/system/fancontroller-pwm.timer
install -D -m 0644 "$DIR/systemd/modules-load.conf" /etc/modules-load.d/lm75-tc654.conf
for unit in fancontroller-failsafe.service fancontroller-watchdog.service fancontroller-watchdog.timer fancontroller-web.service; do
  install -m 0644 "$DIR/systemd/$unit" "/etc/systemd/system/$unit"
done
install -m 0644 "$DIR/config/logrotate" /etc/logrotate.d/edge-fancontrol
umask 077
if [ ! -s /etc/edge-fancontrol/web-token ]; then
  python3 -c 'import secrets; print(secrets.token_urlsafe(32))' > /etc/edge-fancontrol/web-token
fi
chmod 0600 /etc/edge-fancontrol/web-token
python3 /usr/local/lib/edge-fancontrol/fancontrol.py init
systemctl daemon-reload
systemctl enable --now i2c-hwmon-devices.service
systemctl restart i2c-hwmon-devices.service
/usr/local/sbin/fancontroller-failsafe.sh install_initial_full_speed
systemctl start fancontroller-pwm.service
systemctl enable --now fancontroller-pwm.timer
systemctl restart fancontroller-pwm.timer
systemctl enable --now fancontroller-watchdog.timer fancontroller-web.service logrotate.timer
systemctl restart fancontroller-web.service
echo '安装完成。页面 http://127.0.0.1:19090/；远程访问使用 SSH 隧道。'
echo '管理令牌：在主机运行 cat /etc/edge-fancontrol/web-token 查看。'
echo '日志每日轮转，保留 30 天；详情见 docs/WEB.md。'
