# Edge640/Edge680 PVE LM75 + TC654 PWM 风扇控制器

> **版本 1.0 基准声明：**适用于 Edge640、Edge680，以及采用相同 LM75 + TC654 硬件设计的 OEM 设备（例如 Dell VEP1445）。本项目由 Codex 辅助生成和整理；投入生产前必须在目标硬件上完成 I²C 地址、PWM 曲线、风扇转速、温度保护、开机恢复和回滚测试。

这是面向 Proxmox VE 9.2 / Debian 13 的轻量风扇控制服务。它自动加载 LM75、TC654 驱动，实例化 I²C 设备，从 CPU `coretemp` 读取 Package 温度，并通过 TC654 的 PWM 输出调节风扇。

当前基准版本详情见 [VERSION.md](VERSION.md)，许可证为 [MIT](LICENSE)。

## 已验证环境

- Proxmox VE 9.2 / Debian 13
- Linux 7.0 系列 PVE 内核
- Intel `coretemp`，读取 `Package id 0`
- LM75：`i2c-0`，地址 `0x4a`
- TC654：`i2c-0`，地址 `0x1b`
- TC654 `pwm1_mode=1`（PWM 模式）

其他 OEM 型号可能使用不同的 I²C 总线、地址或温度传感器名称，安装前必须核对。

## 控制策略

服务由 systemd timer 每约 10 秒执行一次：

| CPU Package 温度 | PWM 行为 |
|---|---:|
| ≤45°C | 0 |
| 45–60°C | 0–255 线性映射 |
| ≥60°C | 255（全速） |

- 升温时立即提高 PWM。
- 降温时保留当前 PWM 120 秒，再按当前温度降速。
- 使用 `flock` 防止多个控制进程重叠。
- 找不到 CPU 温度或 TC654 hwmon 节点时退出，不盲目写入其他设备。

已验证设备的参考值：PWM 约 77≈2100 RPM、102≈2500、160≈5000、196≈6050、243≈8450、255≈8500–9500 RPM。实际值会因风扇和芯片量化而变化。

## 安装前检查

以 root 身份执行：

```bash
i2cdetect -l
i2cdetect -y 0
modinfo lm75
modinfo tc654
sensors
```

确认 `0x4a` 和 `0x1b` 与目标硬件一致。PWM=0 可能让风扇完全停转，首次测试时请保持本地控制台可用。

## 一键安装

```bash
git clone https://github.com/FlankerZzzz/edge640-680-pve-fancontrol.git
cd edge640-680-pve-fancontrol
./install.sh
```

root 用户不需要 `sudo`；普通用户若已安装 `sudo`，脚本会自动提权。

安装内容：

- `/usr/local/sbin/i2c-hwmon-devices.sh`
- `/usr/local/sbin/fancontroller-pwm.sh`
- `/etc/systemd/system/i2c-hwmon-devices.service`
- `/etc/systemd/system/fancontroller-pwm.service`
- `/etc/systemd/system/fancontroller-pwm.timer`
- `/etc/modules-load.d/lm75-tc654.conf`

## 检查运行状态

```bash
systemctl status i2c-hwmon-devices.service
systemctl status fancontroller-pwm.timer
systemctl list-timers --all | grep fancontroller
sensors
tail -f /var/log/fancontroller-pwm.log
```

控制服务是 `Type=oneshot`，单次成功后显示 `inactive (dead)` 属于正常现象；应确认 timer 为 `active`，且服务退出状态为成功。

## 更新部署

```bash
cd /data/codex/edge640-680-pve-fancontrol
git pull
install -m 0644 systemd/fancontroller-pwm.timer /etc/systemd/system/fancontroller-pwm.timer
systemctl daemon-reload
systemctl restart fancontroller-pwm.timer
```

若脚本也有修改，建议直接重新运行：

```bash
./install.sh
```

## 参数调整

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `I2C_BUS` | `0` | I²C 总线编号 |
| `LM75_ADDR` | `0x4a` | LM75 地址 |
| `TC654_ADDR` | `0x1b` | TC654 地址 |
| `TEMP_SENSOR` | `coretemp-isa-0000` | `sensors` 芯片名称 |
| `FAN_STOP_TEMP` | `45` | 停转温度 |
| `FAN_FULL_TEMP` | `60` | 全速温度 |
| `COOLDOWN_SECONDS` | `120` | 降速延迟 |

systemd 默认不继承交互式 Shell 环境。长期覆盖参数时执行：

```bash
systemctl edit fancontroller-pwm.service
```

示例：

```ini
[Service]
Environment=FAN_STOP_TEMP=45
Environment=FAN_FULL_TEMP=65
Environment=COOLDOWN_SECONDS=120
```

然后执行：

```bash
systemctl daemon-reload
systemctl restart fancontroller-pwm.timer
```

## 压力测试

```bash
stress-ng --cpu 16 --timeout 120s --metrics-brief
watch -n 2 sensors
```

应确认温度升高后约 10 秒内提高 PWM，达到全速温度后写入 255，压力解除后按 120 秒策略降速，且 CPU 温度不接近临界值。

## 卸载

```bash
./uninstall.sh
```

卸载脚本停止并删除服务与部署脚本，但不会强制卸载当前正在使用的内核模块。

## 在其他机器继续开发

```bash
git clone https://github.com/FlankerZzzz/edge640-680-pve-fancontrol.git
cd edge640-680-pve-fancontrol
git switch -c feature/你的功能名称
```

修改后至少执行：

```bash
bash -n install.sh uninstall.sh src/*.sh
systemd-analyze verify systemd/*.service systemd/*.timer
git diff --check
```

建议在功能分支提交，通过实机测试后再合并到 `main`。不要在未验证硬件地址和温控曲线时直接用于生产。

## 已知说明

- `sensors` 对 TC654 PWM 百分比的显示可能超过 100%，应结合 sysfs 原始 `pwm1` 和实际 RPM 判断。
- TC654 的实际 PWM 档位可能被驱动或芯片量化，请求值不一定等于读回值。
- `hwmonN` 编号会变化，控制脚本按设备名称查找 TC654，不固定依赖 `hwmon4`。
