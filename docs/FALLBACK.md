# 全速保护与 30 天日志保留

## 保护顺序

每次 tick 先取得共用进程锁，读取配置和硬件，计算输出，再写入并回读 PWM。任何保护覆盖手动选择，但不把手动配置改写成“全速”。

| 条件 | 行为 |
|---|---|
| CPU 温度达到 full_temp（默认 60°C） | 请求 PWM 255；高温期间持续延长保护恢复等待 |
| CPU 温度不存在、不可解析、NaN、超出 0–125°C | 请求 PWM 255，记录 sensor 错误 |
| JSON 配置不存在、损坏、范围无效 | 请求 PWM 255，不静默覆盖坏配置 |
| 风扇启动 30 秒后仍无 RPM 或低于 500 RPM | 请求 PWM 255，记录转速异常 |
| I²C 读取失败、PWM 模式失败、全速回读不为 255 | 再次尝试写 PWM 255，明确记录失败 |
| 状态/日志持久化失败、控制核心未捕获异常 | 核心尝试全速；systemd OnFailure 再调用独立 Shell fallback |
| 控制任务超过 8 秒未完成 | systemd 超时处理，触发独立 fallback |
| 温控 timer 不活跃，或状态超过 35 秒未更新 | 每约 15 秒运行的独立 watchdog 请求全速 |

Watchdog 使用独立 Shell 脚本，既不读取温度，也不解析 Python 配置；因此 Python 崩溃、状态格式错误或 timer 停止不会使它依赖同一条失败路径。检查粒度意味着“状态 35 秒过期”后，最迟再等约 16 秒发出全速请求，不是 35 秒硬实时保证。

若 TC654 设备消失、sysfs 拒绝写入、I²C 硬件损坏或主机本身挂死，软件无法保证风扇进入全速。这种情况下必须明确报告 `FALLBACK_FAILED` 或“全速写入失败”，不能把“发出请求”说成“已生效”。Watchdog 自身被停止或系统整体不能调度也不在保证范围内。

## 恢复

高温每次采样都会刷新 `protect_until`，故障按 120 秒保护恢复等待。故障修复后仍保持全速直至等待期结束。恢复后的较低输出不会再额外重复等待一次 120 秒。

普通降速从首次持续低于当前请求开始计时；低温重复采样不重置起点；升温需要更高输出时立即取消等待并加速。倒计时使用单调时钟，并绑定 Linux boot ID，避免重启沿用失效时间戳。

## 日志

应用日志：`/var/log/fancontroller-pwm.log`。正常控制为 JSON 行，独立 Shell fallback 使用带时间戳的 `FALLBACK` 行。包括采样、请求 PWM、读回 PWM、温度、RPM、保护原因及错误。

轮转配置：`/etc/logrotate.d/edge-fancontrol`。

```text
daily
rotate 30
maxage 30
compress
delaycompress
create 0640 root root
ifempty
```

`rotate 30` 限制最多 30 份归档，`maxage 30` 在 logrotate 运行时删除超过 30 天的归档；活动日志保留当天内容。`ifempty` 保证卸载后活动日志不再增长时，仍会继续每日轮转并执行过期归档清理。这是日级保留，非精确到秒的 720 小时清理。安装启用系统 logrotate.timer。每次控制结束会关闭日志，下次写入重新打开，因此不使用可能丢行的 copytruncate。卸载保留历史日志和轮转规则，旧日志仍按规则清理。

此规则只管理本项目的应用日志，不修改整台 PVE 的 journald 保留期限。诊断配置：

```bash
logrotate --debug /etc/logrotate.d/edge-fancontrol
systemctl status logrotate.timer
ls -lh /var/log/fancontroller-pwm.log*
```

不要通过删除真实传感器或停止系统总线来做故障测试。仓库测试会在隔离目录注入读写、配置、RPM、磁盘错误，不影响实际风扇。
