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
