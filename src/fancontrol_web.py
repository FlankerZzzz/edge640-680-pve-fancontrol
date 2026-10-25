#!/usr/bin/env python3
"""Loopback PVE control panel. Python stdlib only; no PVE password or cookies."""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import threading
import time

from fancontrol import Controller, Conflict, VERSION


class DemoHardware:
    """Explicit isolated preview. Never opens sysfs or production files."""
    def __init__(self):
        self.pwm = 119
        self.started = time.monotonic()

    def sample(self):
        return {"temp": 52.0, "lm75": 39.5, "rpm": [int(self.pwm * 35), int(self.pwm * 34)],
                "pwm": self.pwm, "pwm_mode": 1, "device": "SIMULATION / TC654"}

    def write(self, pwm):
        self.pwm = pwm
        return pwm


def service_status(demo=False):
    if demo:
        return {key: "simulation" for key in ("timer", "i2c", "watchdog", "logrotate")}
    try:
        result = subprocess.run(["systemctl", "is-active", "fancontroller-pwm.timer",
                                 "i2c-hwmon-devices.service", "fancontroller-watchdog.timer",
                                 "logrotate.timer"], capture_output=True,
                                text=True, timeout=3, check=False)
        lines = result.stdout.splitlines()
        return {key: lines[i] if len(lines) > i else "unknown"
                for i, key in enumerate(("timer", "i2c", "watchdog", "logrotate"))}
    except (OSError, subprocess.TimeoutExpired):
        return {key: "unknown" for key in ("timer", "i2c", "watchdog", "logrotate")}


def make_server(controller, token, port=19090, demo=False, assets=None):
    assets = Path(assets) if assets else Path(__file__).resolve().parent / "web"

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def respond(self, body, status=200, kind="application/json; charset=utf-8"):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(body)

        def valid_host(self):
            # SSH may forward localhost:19091 to PVE localhost:19090.
            # Keep hostnames loopback-only; POST must still match Origin + bearer.
            match = re.fullmatch(r"(?:127\.0\.0\.1|localhost):([0-9]{1,5})",
                                 self.headers.get("Host", ""))
            return bool(match and 1 <= int(match.group(1)) <= 65535)

        def authorized(self):
            return hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token)

        def do_GET(self):
            if not self.valid_host():
                self.respond({"error": "Host 不受支持，请使用本机地址或 SSH 隧道"}, 403)
                return
            files = {"/": ("index.html", "text/html; charset=utf-8"),
                     "/app.js": ("app.js", "application/javascript; charset=utf-8"),
                     "/style.css": ("style.css", "text/css; charset=utf-8")}
            if self.path in files:
                filename, kind = files[self.path]
                body = (assets / filename).read_bytes()
                if demo and self.path == "/":
                    body = body.replace(b"<body>", b'<body data-demo="true">')
                self.respond(body, kind=kind)
                return
            if not self.authorized():
                self.respond({"error": "请输入管理令牌"}, 401)
                return
            if self.path == "/api/status":
                try:
                    status = controller.status()
                    status.update(services=service_status(demo), demo=demo)
                    if not demo and status["services"]["timer"] != "active":
                        status["control_available"] = False
                        status["error"] = "温控定时器未运行；watchdog 将请求全速"
                    if not demo and status["services"]["watchdog"] != "active":
                        status["control_available"] = False
                        status["error"] = "独立 watchdog 未运行，请先恢复保护服务"
                    if not demo and status["services"]["logrotate"] != "active":
                        status["warning"] = "日志轮转定时器未运行，请检查 logrotate.timer"
                    self.respond(status)
                except Exception:
                    self.respond({"error": "读取状态失败，请检查 journald"}, 503)
            elif self.path == "/api/logs":
                try:
                    # Bounded tail; do not load a long log into server memory.
                    with controller.log_path.open("rb") as stream:
                        stream.seek(0, 2)
                        size = stream.tell()
                        stream.seek(max(0, size - 32768))
                        lines = stream.read().decode("utf-8", "replace").splitlines()[-30:]
                    self.respond({"lines": lines})
                except FileNotFoundError:
                    self.respond({"lines": []})
            else:
                self.respond({"error": "Not found"}, 404)

        def do_POST(self):
            if not self.valid_host() or not self.authorized():
                self.respond({"error": "未授权"}, 403)
                return
            if self.headers.get("Origin") != "http://" + self.headers.get("Host", ""):
                self.respond({"error": "Origin 不受支持"}, 403)
                return
            if self.path != "/api/control":
                self.respond({"error": "Not found"}, 404)
                return
            try:
                if self.headers.get("Content-Type") != "application/json":
                    raise ValueError("仅支持 JSON")
                length = int(self.headers.get("Content-Length", "0"))
                if not 1 <= length <= 1024:
                    raise ValueError("请求长度无效")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict) or set(data) != {"mode", "pwm", "revision"}:
                    raise ValueError("请求字段无效")
                services = service_status(demo)
                if not demo and any(services[key] != "active" for key in ("timer", "watchdog")):
                    raise Conflict("温控定时器或 watchdog 未运行，请先恢复服务")
                result = controller.apply(data["mode"], data["pwm"], data["revision"])
                self.respond(result, 200 if result["success"] else 503)
            except Conflict as exc:
                self.respond({"error": str(exc)}, 409)
            except (ValueError, KeyError) as exc:
                self.respond({"error": str(exc)}, 400)
            except Exception:
                self.respond({"error": "执行结果未确认，已请求全速，请刷新核对设置和实际输出"}, 503)

        def log_message(self, *_):
            # Avoid logging Authorization or request bodies.
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=19090)
    parser.add_argument("--token-file", default="/etc/edge-fancontrol/web-token")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--demo-dir", default=".preview")
    args = parser.parse_args()
    if args.demo:
        directory = Path(args.demo_dir)
        controller = Controller(hardware=DemoHardware(), config=directory / "config.json",
                                state=directory / "state.json", lock=directory / "lock",
                                log=directory / "fan.log", boot_id="preview")
        controller.initialize()
        token = "demo-only"
        def poll():
            while True:
                controller.tick()
                time.sleep(2)
        threading.Thread(target=poll, daemon=True).start()
    else:
        controller = Controller()
        path = Path(args.token_file)
        token = path.read_text(encoding="ascii").strip()
        if len(token) < 32 or (os.name != "nt" and path.stat().st_mode & 0o077):
            raise RuntimeError("管理令牌无效或权限过宽，请使用 0600")
    server = make_server(controller, token, args.port, args.demo)
    print(f"Edge PVE fan control {VERSION}: http://127.0.0.1:{server.server_address[1]}/", flush=True)
    if args.demo:
        print("SIMULATION ONLY — login token: demo-only", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
