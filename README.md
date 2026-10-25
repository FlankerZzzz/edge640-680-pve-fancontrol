# Edge640/Edge680 及相同设计 OEM（如 Dell VEP1445）的 PVE 风扇控制器

> **当前分支：1.1.0-dev 控制页面测试版。**1.0 基准保存在 `v1.0.0` 标签。本项目由 Codex 辅助生成和整理；投入生产前必须在目标硬件上完成传感器、风扇、fallback 和开机恢复测试。OEM 型号只在硬件设计相同时作为适配目标。

这是面向 Proxmox VE 9.2 / Debian 13 的轻量风扇控制服务。它自动加载 LM75、TC654 驱动，实例化 I²C 设备，从 CPU `coretemp` 读取 Package 温度，并通过 TC654 的 PWM 输出调节风扇。

版本详情见 [VERSION.md](VERSION.md)。[PVE 原生节点页面安装](docs/PVE-NATIVE.md) 可让任意浏览器登录 PVE 后看到“风扇控制”；[独立页面与升级操作](docs/WEB.md) 保留本机端口访问方式。[保护与日志策略](docs/FALLBACK.md)。许可证为 [MIT](LICENSE)。

## 已验证环境

- Proxmox VE 9.2 / Debian 13
- Linux 7.0 系列 PVE 内核
- Intel `coretemp`；1.1 直接读取 sysfs，在多个 CPU Package 中取最高温度
- LM75：`i2c-0`，地址 `0x4a`
- TC654：`i2c-0`，地址 `0x1b`
- TC654 `pwm1_mode=1`（SMBus 软件控制 PWM；`0` 为 Vin 输入控制，输出本身仍是 PWM）

1.1 已于 2026-10-25 在 Edge680 / `7.0.14-25-pve` 完成安装、26 项自动测试、16 worker / 120 秒压测、完整降速、全速 fallback、页面服务重启及日志轮转验证；尚未进行整机重启与浏览器视觉验收。详情见 [测试记录](docs/TESTING-1.1.md)。TC654 模式语义见 [Linux 内核文档](https://docs.kernel.org/hwmon/tc654.html)。

## 控制策略

服务由 systemd timer 每约 10 秒执行一次：

| CPU Package 温度 | PWM 行为 |
|---|---:|
| ≤45°C | 0 |
| 45–60°C | 0–255 线性映射 |
| ≥60°C | 255（全速） |

- 升温时立即提高 PWM。
- 持续需要降速满 120 秒后，按当前温度降速；升温会取消降速等待。
- 上述普通降速等待仅用于自动模式；固定模式选档后立即应用 PWM，升速与降速均不等待。
- 高温或故障保护解除后也等待 120 秒，再恢复已保存模式。
- 页面和定时任务使用同一把进程锁。
- 温度缺失/无效、配置损坏/缺失、风扇反馈异常、I²C 失败均尝试 PWM 255；全速写入失败会明确报告。
- 独立 watchdog 每约 15 秒检查控制采样；采样超过 35 秒未更新或 timer 停止时尝试全速。
- 应用日志每天轮转，压缩归档并保留 30 天。

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

测试当前功能分支时，首次 clone 后执行 `git switch feature/pve-control-page` 再安装。安装脚本会检查 Python 3 和 logrotate，缺少时通过 APT 安装。此版不包含内核驱动编译器；内核必须已有可用的 `lm75`、`tc654` 模块。

root 用户不需要 `sudo`；普通用户若已安装 `sudo`，脚本会自动提权。

安装内容：

- `/usr/local/sbin/i2c-hwmon-devices.sh`
- `/usr/local/sbin/fancontroller-pwm.sh`
- `/etc/systemd/system/i2c-hwmon-devices.service`
- `/etc/systemd/system/fancontroller-pwm.service`
- `/etc/systemd/system/fancontroller-pwm.timer`
- `/etc/modules-load.d/lm75-tc654.conf`
- `/usr/local/lib/edge-fancontrol/`（Python 控制核心、Web 后端、页面静态文件）
- `/etc/edge-fancontrol/config.json`（持久化模式、PWM、曲线）
- `/etc/edge-fancontrol/web-token`（0600 管理令牌）
- `fancontroller-web.service`、`fancontroller-failsafe.service`、`fancontroller-watchdog.timer`
- `/etc/logrotate.d/edge-fancontrol`（每日轮转 / 30 天）

## 打开控制页面

推荐服务器端原生接入（已有控制核心时执行）：

```bash
bash native/install.sh
```

刷新 PVE 网页，选择节点 → 风扇控制。沿用 PVE 登录、`Sys.Audit` / `Sys.Modify` 权限及 CSRF，无需下面的 SSH 隧道或独立令牌。新机器可直接 `bash ./install.sh --native` 安装全部组件。

如果选择独立页面模式：

在管理员电脑保持 SSH 隧道运行：

```bash
ssh -N -L 19090:127.0.0.1:19090 root@你的PVE地址
```

在 PVE 本机查看管理令牌：

```bash
cat /etc/edge-fancontrol/web-token
```

浏览器打开 `http://127.0.0.1:19090/` 输入令牌。页面支持 CPU/LM75 温度、双风扇 RPM、PWM 请求与回读、自动/手动模式、保护状态、倒计时、日志和会话内趋势。设置保存到主机，关页不停止温控。

## 检查运行状态

```bash
systemctl status i2c-hwmon-devices.service
systemctl status fancontroller-pwm.timer
systemctl status fancontroller-web.service fancontroller-watchdog.timer
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

上面的旧命令只用于单独更新 timer。从 1.0 升级到页面版必须安装新控制核心和保护单元：

```bash
./install.sh
```

## 参数调整

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `I2C_BUS` | `0` | I²C 总线编号 |
| `LM75_ADDR` | `0x4a` | LM75 地址 |
| `TC654_ADDR` | `0x1b` | TC654 地址 |
| `FAN_STOP_TEMP` | `45` | 停转温度 |
| `FAN_FULL_TEMP` | `60` | 全速温度 |
| `COOLDOWN_SECONDS` | `120` | 降速延迟 |

`I2C_BUS` / 地址通过初始化服务环境提供。温控曲线环境变量只在第一次生成配置时读取；升级保留已有配置。页面与 timer 共用 `/etc/edge-fancontrol/config.json`。修改曲线时使用：

```bash
nano /etc/edge-fancontrol/config.json
```

示例（保留其他字段，并增加 `revision`）：

```json
{"schema":1,"revision":1,"mode":"auto","manual_pwm":160,"stop_temp":45,"full_temp":60,"cooldown_seconds":120}
```

然后执行：

```bash
systemctl start fancontroller-pwm.service
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

卸载先请求全速，再停止并删除本项目服务与脚本。保留内核模块、配置、令牌、历史日志和轮转规则，便于重装及执行 30 天保留策略。

## 在其他机器继续开发

```bash
git clone https://github.com/FlankerZzzz/edge640-680-pve-fancontrol.git
cd edge640-680-pve-fancontrol
git switch -c feature/你的功能名称
```

修改后至少执行：

```bash
for f in install.sh uninstall.sh src/*.sh; do bash -n "$f" || exit; done
python3 -m unittest discover -s tests -v
systemd-analyze verify systemd/*.service systemd/*.timer
git diff --check
```

建议在功能分支提交，通过实机测试后再合并到 `main`。不要在未验证硬件地址和温控曲线时直接用于生产。

## 已知说明

- `sensors` 对 TC654 PWM 百分比的显示可能超过 100%，应结合 sysfs 原始 `pwm1` 和实际 RPM 判断。
- TC654 的实际 PWM 档位可能被驱动或芯片量化，请求值不一定等于读回值。
- `hwmonN` 编号会变化，控制脚本按设备名称查找 TC654，不固定依赖 `hwmon4`。
- 全速 fallback 依赖操作系统和 TC654 可写；主机挂死、断电或 I²C 硬件失效时，软件无法保证成功写入，详见保护说明。
