# PVE 服务器端原生面板

在 PVE 节点功能菜单中增加“风扇控制”，使用 PVE ExtJS 组件、当前主题、登录会话和 CSRF。任意浏览器登录已安装此接入层的 PVE 后可使用；不需要安装浏览器扩展，也不需要 SSH 转发或额外管理令牌。

本接入层为项目提供的服务器本地扩展，不是 Proxmox 官方插件。

## 安装

已有 1.1 控制核心：

```bash
cd /data/codex/edge640-680-pve-fancontrol
git fetch origin
git switch feature/pve-control-page
git pull --ff-only
bash native/install.sh
```

全新安装控制核心与原生页面：

```bash
bash ./install.sh --native
```

以 root 在 PVE 上执行。安装校验 PVE 的节点菜单结构及 Perl/API 注册，并先调用本机 `pvesh` 读取真实状态；通过后平滑重载 `pvedaemon`、`pveproxy` 工作进程。不重启主机。校验或重载失败会尝试回滚刚才修改的文件。

打开 `https://你的PVE地址:8006/`，按 `Ctrl+F5`，登录后选择具体节点，在节点功能菜单中点击“风扇控制”。入口属于节点，不属于数据中心或虚拟机。

## 面板与权限

- 温度：CPU Package 最高值、LM75 辅助温度。
- 实时反馈：双风扇 RPM、请求 PWM、实际读回 PWM。
- 设置：自动温控 / 手动 PWM、保存并执行、恢复当前已保存设置。
- 固定转速使用 16 档下拉框，显示参考 RPM（沿用 ESXi 参考标注），发送 Linux TC654 的实际 sysfs PWM 值，普通列表不含停转档。
- 状态：保护原因、降速等待、控制及 watchdog 服务状态、日志。
- 样式：使用 PVE 本身组件和主题，不额外嵌入 HTTP iframe。

权限检查在服务端执行：

| 接口 | 节点权限 |
|---|---|
| GET `/api2/json/nodes/{node}/edge-fancontrol` | `Sys.Audit` |
| GET `/api2/json/nodes/{node}/edge-fancontrol/logs` | `Sys.Audit` |
| POST `/api2/json/nodes/{node}/edge-fancontrol` | `Sys.Modify`，并由 PVE 校验会话及 CSRF |

有读取权限但没有修改权限的用户只能查看。后端以 PVE protected API 执行，并使用 `proxyto=node`；多个节点时，各目标节点也须安装控制核心和接入层。不要通过修改前端按钮来授予权限；应使用 PVE 的 ACL 管理。

调速继续使用原有 Python 控制核心及同一把锁，保持所有 fallback、配置版本冲突检测和 30 天日志规则；原生页面不引入第二个 PWM 写入程序。高温/故障可以覆盖手动设置，读回值与请求值可能因 TC654 量化而不同。

16 档 PWM 映射为 `77,88,102,112,124,136,148,160,172,184,196,207,219,231,243,255`，对应 TC654 的硬件档位；不是向 sysfs 发送 0–15。参考 RPM 不是速度反馈目标，不保证与其他机器一致。映射来自 [Linux TC654 驱动](https://github.com/torvalds/linux/blob/master/drivers/hwmon/tc654.c)。已有非标准 PWM 配置会显示为“已有自定义 PWM”，不会因为刷新页面被偷偷换档。

## 文件与可恢复性

新增文件：

- `/usr/share/perl5/PVE/API2/EdgeFanControl.pm`：受权限保护的 API。
- `/usr/share/pve-manager/js/edge-fancontrol.js`：原生节点面板及菜单接入。
- `/usr/local/lib/edge-fancontrol/native_api.py`：本机受控调用适配器。

两处带 `EDGE_FANCONTROL_NATIVE` 标记的加载钩子：

- `/usr/share/perl5/PVE/API2/Nodes.pm`：注册节点 API 子路由。
- `/usr/share/pve-manager/index.html.tpl`：在 PVE 自身 JS 后加载独立面板文件。

不替换 `pvemanagerlib.js`。原文件周围的代码保留；重复安装不会增加重复钩子，JS URL 使用内容摘要刷新缓存。原文件备份位于 `/var/lib/fancontroller-pwm/native-backups/install-*/`。

PVE 包更新可能覆盖这两处钩子。更新后检查节点入口和 API；需要时重新执行 `bash native/install.sh`。脚本会校验当前结构，拒绝未知结构；不要直接把旧版完整 `Nodes.pm` 或 HTML 模板覆盖回新版本。

## 卸载原生接入层

```bash
bash native/uninstall.sh
```

只移除自己的标记段与新增模块，平滑重载管理工作进程，风扇核心继续运行。`bash ./uninstall.sh` 则先卸载原生接入层，再卸载整个控制服务。

## 已完成验证

2026-10-25，在 Edge680 / PVE / Linux `7.0.14-25-pve`：

- 32 项自动测试通过，含可逆/幂等钩子、节点菜单插入、只读按钮、配置冲突、Linux 日志保留及原有 fallback。
- `pvesh` 本机节点 API 状态读取通过。
- Perl/API 注册、管理服务平滑重载通过。
- `python3 tests/native_acceptance.py --run-native` 的 8 项 HTTPS 验收通过：页面资源、匿名拒绝、登录状态、CSRF 缺失拒绝、PWM 范围、配置版本冲突、合法 POST 与日志读取。

验收临时会话仅保存在测试进程内存，不打印或存入仓库。尚未以非 root 的真实只读账户验收 HTTP 权限，尚未完成浏览器视觉与点击验收、整机重启及 PVE 包更新后的重装验证。
