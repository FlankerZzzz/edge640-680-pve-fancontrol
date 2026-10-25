# 1.1.0-dev 验证记录

日期：2026-10-25。环境：Windows 开发机、Python 3.12、Git Bash、Node.js。测试不连接真实 PVE，不写实际风扇。

## 已执行

`python -m unittest discover -s tests -v`：24 项全部通过。

控制核心覆盖：自动曲线；持续低温 120 秒降速；升温取消降速等待；手动模式高温覆盖及单次恢复等待；无温度/NaN/越界温度；I²C 读取失败；PWM 写失败；坏配置/配置缺失；风扇启动宽限和低 RPM 故障；配置保存、状态写入、日志写入失败后的全速尝试；配置版本冲突；配置持久化；过期采样；重启 boot ID；旧版状态格式；PWM 0 停转后重新启动。

模拟 sysfs 覆盖：忽略单核温度、多个 Package 取最高值；按名称寻找 TC654；SMBus 模式和 255 写入；不尝试不存在的 `pwm1_enable`。

HTTP 集成覆盖：静态页面不含管理令牌；no-store/CSP；状态及设置接口；未授权、错误 Host、错误 Origin、越界或多余参数；两个客户端竞争同一配置版本仅一个成功；日志尾部仅 30 行。

Shell 脚本逐个 `bash -n`，前端 `node --check src/web/app.js`，`git diff --check`：通过。

本地模拟 HTTP 服务成功启动并提供接口。浏览器 UI 自动验证因当前浏览器 URL 无法可靠识别而被工具终止，因此本报告不声称已完成视觉、移动端和浏览器点击验收。

## 尚需 PVE 实机验收

- `systemd-analyze verify` 与实际单元启动、OnFailure、8 秒超时触发。
- `logrotate --debug /etc/logrotate.d/edge-fancontrol`，跨日轮转、压缩与历史文件删除。
- 驱动档位量化后的请求/读回 PWM 与真实 RPM。
- 16 worker / 120 秒压力测试，完整观察升速和低温持续 120 秒后的降速。
- 重启后自动实例化传感器、恢复已保存模式、watchdog 和页面服务。
- 使用独立测试夹具验证 watchdog 采样过期和全速请求；不通过破坏真实 I²C 总线来模拟故障。

1.0 的历史压测数据仍在 VERSION.md，它不构成 1.1 实机通过证明。

## 2026-10-25：Edge680 / PVE 实机验收补充

平台：VMwareEdge680，Linux `7.0.14-25-pve`。先备份旧服务后安装功能分支。以下记录为实际硬件测试，取代上面对应项目的“待验证”状态。

- Linux 上最新 26 项自动测试全部通过，包括 Host/Origin/令牌、SSH 端口映射、并发配置冲突和故障回归。
- `systemd-analyze verify` 通过；温控 timer、watchdog timer、Web 服务、logrotate timer 均 active 且 enabled。
- `stress-ng --cpu 16 --timeout 120s --metrics-brief`：16 worker，failed=0。
- CPU 起始约 51°C，采样最高 68°C；约 10 秒内升至请求 PWM255 / 读回255。
- 双风扇采样最高约 9500 / 9200 RPM。
- 压力解除后完整观察保护等待：120 秒结束并到达下次 tick 后，从255降至请求119 / 读回124，RPM约3750 / 3650。
- 临时注入“无 CPU 温度”：真实 TC654 立即写入并读回255；未解除真实传感器绑定。
- 用隔离的损坏配置输入测试：真实输出255；正式配置文件保留。
- 停止温控 timer，调用 watchdog：独立保护读回255。
- 使用 `/run` 临时 drop-in 让控制服务失败：确认 `OnFailure` 启动独立 fallback 单元并写255，之后移除 drop-in、恢复 timer，两个服务 Result=success。
- 手动255保存后重启 Web 服务，设置仍保留；随后恢复原自动设置。
- fallback 恢复期结束，实际回到 PWM102、约2950 / 2850 RPM，error=null。
- logrotate debug 与一次真实轮转通过；隔离的33天归档夹具证实最多30份、过期清理、空日志轮转及旧归档压缩。
- 通过本机SSH映射端口验证页面 HTTP200、未授权状态接口 HTTP401。

实机自动验收共10项检查，耗时约465秒，报告 `passed=true`。复测命令（会实际压测与写PWM，需在Linux root执行）：

```bash
python3 tests/pve_acceptance.py --run-live --stress-seconds 120
```

报告保存到主机 `/var/lib/fancontroller-pwm/acceptance-*/report.json`。旧服务备份位于主机 `/root/edge-fancontrol-backup-2ebUShyn/installed.tgz`。

仍未验证：整机重启、8秒超时路径、watchdog自身失效、真实I²C硬件故障、浏览器视觉/移动端布局。实机没有修改网络、GRUB或SR-IOV。
