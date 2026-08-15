# PVE LM75 + TC654 PWM Fan Controller

适用于 Proxmox VE 9.2 / Debian 13 的 LM75 温度传感器和 TC654 PWM 风扇一键部署工具。

## 工作流程

1. 加载 `lm75`、`tc654` 内核模块。
2. 在 I²C 总线上实例化 LM75（默认 `i2c-0/0x4a`）和 TC654（默认 `i2c-0/0x1b`）。
3. 每 10 秒读取 `coretemp` 的 CPU Package 温度。
4. 通过 TC654 的 `pwm1` 输出控制风扇，并固定为 PWM 模式。
5. 温度上升立即加速，温度下降延迟 120 秒降速。

## 安装

```bash
git clone https://github.com/REPLACE_ME/fancontrol-pve.git
cd fancontrol-pve
./install.sh
```

默认曲线：低于 45°C 停转；45–59°C 线性升速；60°C 及以上全速。首次部署前请确认风扇在 PWM=0 时允许停转，并准备本地控制台以便回滚。

## 检查与卸载

```bash
systemctl status i2c-hwmon-devices.service fancontroller-pwm.timer
sensors
tail -f /var/log/fancontroller-pwm.log
./uninstall.sh
```

可通过环境变量调整：`I2C_BUS`、`LM75_ADDR`、`TC654_ADDR`、`TEMP_SENSOR`、`POLL_SECONDS`、`MIN_TEMP`、`MAX_TEMP`、`FAN_STOP_TEMP`、`FAN_FULL_TEMP`、`COOLDOWN_SECONDS`。

## 安全说明

这是硬件控制脚本，默认只写入检测到的 hwmon PWM 节点，不修改网络、GRUB 或存储配置。不同主板的 I²C 总线和地址可能不同，安装前请用 `i2cdetect -l` / `i2cdetect -y 0` 核对。
