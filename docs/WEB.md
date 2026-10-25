# PVE 控制页面（1.1.0-dev）

## 与 ESXi 页面一致的交互

保留自动/固定模式、已保存设置与实际输出分开显示、明确执行结果、配置版本冲突检测及页面失联时禁用操作的行为。PVE 直接使用 Linux hwmon，无需 ESXi 的 SSH 代理、内核扩展或 VIB。

本版是 PVE 本机独立管理页，不修改 `/usr/share/pve-manager`，也不向 PVE 左侧菜单注入代码。1.0 基准仍位于 `v1.0.0`。

## 安装与升级

```bash
git clone --branch feature/pve-control-page https://github.com/FlankerZzzz/edge640-680-pve-fancontrol.git
cd edge640-680-pve-fancontrol
bash ./install.sh
```

已有克隆：

```bash
cd /data/codex/edge640-680-pve-fancontrol
git fetch origin
git switch feature/pve-control-page
git pull --ff-only
bash ./install.sh
```

新核心会替换旧的 Shell 温控实现；旧的 `/var/lib/fancontroller-pwm/state` 文本状态不再读取，新状态为 `web-state.json`。旧安装的曲线 service drop-in 应迁移到 `/etc/edge-fancontrol/config.json`，保证页面与 timer 使用同一份曲线。

升级会保留已有新格式配置和令牌。首次启动先请求全速，待降速条件持续满足 120 秒后回到自动曲线。

## 访问

后端默认仅监听 PVE 的 `127.0.0.1:19090`。在你的电脑建立 SSH 隧道：

```bash
ssh -N -L 19090:127.0.0.1:19090 root@192.168.2.70
```

主机上运行 `cat /etc/edge-fancontrol/web-token` 获取令牌，然后在电脑浏览器打开 `http://127.0.0.1:19090/`。不需要输入 PVE 登录密码，令牌只保留在页面内存中。

如果本地 19090 被 ESXi 测试占用，先停止旧隧道/代理，或调整 SSH 隧道和 Web 服务端口，使本地与服务端端口一致（后端会校验 Host/Origin）。不要直接用 `http://PVE-IP:19090`，默认未监听局域网。

## 页面信息

- CPU：所有 `coretemp` 的 Package 温度取最大值，不用 Core 温度替代。
- LM75：主板温度，仅作为辅助监测。
- 风扇：两个 RPM 反馈，不把写入 PWM 当成已达到目标 RPM。
- 当前 PWM：sysfs 读回值，不使用 `sensors` 百分比缩放。
- 已保存模式：重启后恢复的自动/手动选择。
- 实际状态：自动、手动、降速等待、高温保护、故障保护分别显示。
- 日志：尾部 30 行，失败消息不被前端吞掉。
- 失联/过期：采样超过 35 秒时隐藏失效读数、禁用写入。

低 PWM 的实际 RPM 与芯片量化有关，手动 PWM 是输出请求，不是闭环 RPM 控制。高温或故障时请求全速，保持原来的已保存选择，恢复后按等待逻辑返回。

## 本地模拟预览

```bash
python3 src/fancontrol_web.py --demo --port 19092
```

浏览器打开 `http://127.0.0.1:19092/`。页面会明确标注模拟设备，使用隔离的 `.preview/` 目录，不读取真实 sysfs、不写主机配置。demo 自动连接，令牌 `demo-only` 仅用于隔离演示。

## 自检

```bash
python3 -m unittest discover -s tests -v
for f in install.sh uninstall.sh src/*.sh; do bash -n "$f" || exit; done
node --check src/web/app.js   # 仅开发检查，PVE 运行不依赖 Node
systemd-analyze verify systemd/*.service systemd/*.timer
logrotate --debug /etc/logrotate.d/edge-fancontrol
systemctl status fancontroller-pwm.timer fancontroller-watchdog.timer fancontroller-web.service
journalctl -u fancontroller-pwm.service -u fancontroller-failsafe.service -n 50
```

软件测试采用模拟 hwmon 和 HTTP 请求，不等同于 PVE 实机验证。压测、30 天轮转的实际定时运行、重启恢复和真实风扇故障注入须在目标 Linux 上验收。

## 回到 1.0

先在页面版目录执行 `bash ./uninstall.sh`（先请求全速），再在干净工作区切换 `git switch --detach v1.0.0` 并运行旧版安装脚本。新版配置/令牌保留但不会被旧版读取。1.0 不具备本版新增的 watchdog 和完整 fallback。
