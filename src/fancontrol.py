#!/usr/bin/env python3
"""Shared PVE controller. All hardware/config writers use the same process lock."""
import argparse
import contextlib
import json
import math
import os
from pathlib import Path
import socket
import sys
import tempfile
import time

VERSION = "1.1.0-dev"


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextlib.contextmanager
def process_lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if os.name == "nt":  # permits a local Windows preview, never real sysfs
            import msvcrt
            if path.stat().st_size == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def integer(path):
    return int(Path(path).read_text(encoding="ascii").strip())


class Hardware:
    def __init__(self, root="/sys/class/hwmon", bus="0", address="0x1b"):
        self.root = Path(root)
        self.device_id = f"{int(bus)}-{int(address, 16):04x}"

    def find(self, name):
        found = []
        for item in self.root.glob("hwmon*"):
            try:
                if (item / "name").read_text().strip() == name:
                    found.append(item)
            except OSError:
                continue
        return found

    def tc654(self):
        found = self.find("tc654")
        if len(found) == 1:
            return found[0]
        matching = [p for p in found if self.device_id in (p / "device").resolve().parts
                    or self.device_id in p.resolve().parts]
        if len(matching) != 1:
            raise RuntimeError("无法唯一定位 TC654，请核对总线和设备地址")
        return matching[0]

    def sample(self):
        temperatures = []
        for item in self.find("coretemp"):
            for label in item.glob("temp*_label"):
                if label.read_text().strip().startswith("Package id"):
                    temperatures.append(integer(label.with_name(label.name.replace("_label", "_input"))) / 1000)
        temp = max(temperatures) if temperatures else None
        if temp is not None and (not math.isfinite(temp) or not 0 <= temp <= 125):
            temp = None
        lm75 = []
        for item in self.find("lm75"):
            try:
                lm75.append(integer(item / "temp1_input") / 1000)
            except (OSError, ValueError):
                pass
        device = self.tc654()
        rpm = []
        for index in (1, 2):
            try:
                rpm.append(integer(device / f"fan{index}_input"))
            except (OSError, ValueError):
                rpm.append(None)
        return {"temp": temp, "lm75": max(lm75) if lm75 else None,
                "rpm": rpm, "pwm": integer(device / "pwm1"),
                "pwm_mode": integer(device / "pwm1_mode"), "device": str(device)}

    def write(self, pwm):
        if type(pwm) is not int or not 0 <= pwm <= 255:
            raise ValueError("PWM 必须为 0–255 的整数")
        device = self.tc654()
        # TC654 has no pwm1_enable. mode=1 means SMBus PWM, mode=0 means Vin.
        (device / "pwm1_mode").write_text("1\n", encoding="ascii")
        (device / "pwm1").write_text(f"{pwm}\n", encoding="ascii")
        readback = integer(device / "pwm1")
        if integer(device / "pwm1_mode") != 1 or not 0 <= readback <= 255:
            raise RuntimeError("PWM 模式或回读无效")
        if (pwm == 255 and readback != 255) or (pwm > 0 and readback == 0):
            raise RuntimeError(f"PWM 写入未生效：请求 {pwm}，回读 {readback}")
        return readback


def default_config():
    return {"schema": 1, "revision": 0, "mode": "auto", "manual_pwm": 160,
            "stop_temp": int(os.environ.get("FAN_STOP_TEMP", 45)),
            "full_temp": int(os.environ.get("FAN_FULL_TEMP", 60)),
            "cooldown_seconds": int(os.environ.get("COOLDOWN_SECONDS", 120))}


def validate_config(config):
    if not isinstance(config, dict) or config.get("schema") != 1:
        raise ValueError("配置格式错误")
    for field in ("revision", "manual_pwm", "stop_temp", "full_temp", "cooldown_seconds"):
        if type(config.get(field)) is not int:
            raise ValueError(f"配置 {field} 必须为整数")
    if config["mode"] not in ("auto", "manual") or not 0 <= config["manual_pwm"] <= 255:
        raise ValueError("模式或 PWM 无效")
    if not (0 <= config["stop_temp"] < config["full_temp"] <= 90):
        raise ValueError("温度阈值无效")
    if not 0 <= config["cooldown_seconds"] <= 3600 or config["revision"] < 0:
        raise ValueError("降速等待或版本无效")
    return config


class Conflict(Exception):
    pass


class Controller:
    def __init__(self, hardware=None, config="/etc/edge-fancontrol/config.json",
                 state="/var/lib/fancontroller-pwm/web-state.json",
                 lock="/run/fancontroller-pwm.lock", log="/var/log/fancontroller-pwm.log",
                 clock=time.monotonic, wall=time.time, boot_id=None):
        self.hardware = hardware or Hardware(bus=os.environ.get("I2C_BUS", "0"),
                                             address=os.environ.get("TC654_ADDR", "0x1b"))
        self.config_path, self.state_path = Path(config), Path(state)
        self.lock_path, self.log_path = Path(lock), Path(log)
        self.clock, self.wall = clock, wall
        try:
            self.boot_id = boot_id or Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        except OSError:
            self.boot_id = boot_id or "local-preview"

    def config(self):
        try:
            value = json.loads(self.config_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise ValueError("配置文件缺失，请重新运行安装脚本；已请求全速") from None
        return validate_config(value)

    def load_state(self):
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(state, dict) or state.get("schema") != 2 or state.get("boot_id") != self.boot_id:
                return {}
            for key in ("pending_since", "protect_until", "running_since"):
                value = state.get(key)
                if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
                    return {}
            if type(state.get("last_pwm")) is not int or not 0 <= state["last_pwm"] <= 255:
                return {}
            return state
        except (OSError, ValueError):
            return {}

    def initialize(self):
        with process_lock(self.lock_path):
            if not self.config_path.exists():
                atomic_json(self.config_path, validate_config(default_config()))
            self.config()

    def tick(self):
        try:
            with process_lock(self.lock_path):
                return self._tick()
        except Exception:
            # Includes state/log persistence failure, not only sensor failures.
            self.emergency()
            raise

    def emergency(self):
        try:
            self.hardware.write(255)
        except Exception as exc:
            print("FALLBACK_FAILED: " + str(exc), file=sys.stderr)

    def _tick(self):
        now = self.clock()
        state = self.load_state()
        previous = state.get("last_pwm", 255)
        pending = state.get("pending_since")
        protection = state.get("protect_until", 0) or 0
        error = None
        try:
            config = self.config()
            sample = self.hardware.sample()
            temp = sample["temp"]
            if temp is None:
                raise RuntimeError("CPU Package 温度不可用，已请求全速")
            if type(temp) not in (int, float) or not math.isfinite(temp) or not 0 <= temp <= 125:
                raise RuntimeError("CPU Package 温度无效，已请求全速")
            running_since = state.get("running_since")
            if previous > 0 and running_since is not None and now - running_since >= 30:
                if any(rpm is None or rpm < 500 for rpm in sample["rpm"]):
                    raise RuntimeError("风扇转速异常，已请求全速；请检查风扇")
            cooldown = config["cooldown_seconds"]
            if temp >= config["full_temp"]:
                protection = now + cooldown
                pwm, reason, pending = 255, "high_temperature", None
            elif protection > now:
                pwm, reason, pending = 255, "protection_cooldown", None
            else:
                # A completed protection cooldown already paid the 120-second wait.
                # Do not start a second cooldown when returning to the saved mode.
                if protection > 0:
                    pending, protection = now - cooldown, 0
                target = config["manual_pwm"] if config["mode"] == "manual" else max(
                    0, min(255, int((temp - config["stop_temp"]) * 255 /
                                   (config["full_temp"] - config["stop_temp"]))))
                if config["mode"] == "manual":
                    # Explicit fixed settings take effect immediately in either direction.
                    # High-temperature and fault recovery protection above still wins.
                    pwm, reason, pending = target, "manual", None
                elif target < previous:
                    pending = now if pending is None else pending
                    if now - pending < cooldown:
                        pwm, reason = previous, "cooldown"
                    else:
                        pwm, reason, pending = target, config["mode"], None
                else:
                    pwm, reason, pending = target, config["mode"], None
            readback = self.hardware.write(pwm)
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            error, reason, pwm, pending = str(exc), "failsafe", 255, None
            protection = now + 120
            try:
                readback = self.hardware.write(255)
            except (OSError, ValueError, RuntimeError) as write_error:
                readback = None
                error += "; 全速写入失败: " + str(write_error)
            try:
                sample = self.hardware.sample()
            except (OSError, ValueError, RuntimeError):
                sample = {"temp": None, "lm75": None, "rpm": [None, None]}
            try:
                config = self.config()
            except (OSError, ValueError, KeyError):
                config = None
        result = {"schema": 2, "boot_id": self.boot_id, "updated_at": self.wall(),
                  "last_pwm": pwm, "readback_pwm": readback,
                  "pending_since": pending, "protect_until": protection,
                  "running_since": (state.get("running_since") if previous > 0 else now)
                  if pwm > 0 else None, "reason": reason, "error": error,
                  "config_revision": config["revision"] if config else None,
                  "temp": sample["temp"], "rpm": sample["rpm"], "lm75": sample["lm75"],
                  "sample": state.get("sample", 0) + 1}
        if pwm > 0 and result["running_since"] is None:
            result["running_since"] = now
        atomic_json(self.state_path, result)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as log:
            log.write(json.dumps(result, ensure_ascii=False) + "\n")
        return result

    def status(self):
        with process_lock(self.lock_path):
            config_error = None
            try:
                config = self.config()
            except (OSError, ValueError, KeyError) as exc:
                config, config_error = None, str(exc)
            state = self.load_state()
            try:
                live, error = self.hardware.sample(), None
            except (OSError, ValueError, RuntimeError) as exc:
                live, error = {"temp": None, "rpm": [None, None], "lm75": None}, str(exc)
            age = self.wall() - state.get("updated_at", 0)
            stale = not state or not 0 <= age <= 35
            pending = state.get("pending_since")
            wait = 0
            if config and pending is not None:
                wait = max(0, config["cooldown_seconds"] - (self.clock() - pending))
            wait = max(wait, (state.get("protect_until") or 0) - self.clock())
            return {"version": VERSION, "host": socket.gethostname(), "config": config,
                    "state": state, "live": live, "stale": stale,
                    "control_available": bool(config and not error and not stale and not state.get("error")),
                    "cooldown_remaining": int(max(0, wait)),
                    "error": config_error or error or state.get("error"),
                    "collected_at": self.wall()}

    def apply(self, mode, pwm, revision):
        if mode not in ("auto", "manual") or type(pwm) is not int or not 0 <= pwm <= 255:
            raise ValueError("模式或 PWM 无效")
        if type(revision) is not int or revision < 0:
            raise ValueError("配置版本无效")
        with process_lock(self.lock_path):
            state = self.load_state()
            if not state or not 0 <= self.wall() - state.get("updated_at", 0) <= 35:
                raise Conflict("温控采样已过期，请先检查温控定时器")
            config = self.config()
            if revision != config["revision"]:
                raise Conflict("设置已由其他页面修改，请刷新后重试")
            config.update(mode=mode, manual_pwm=pwm, revision=revision + 1)
            try:
                atomic_json(self.config_path, config)
                result = self._tick()
            except Exception:
                self.emergency()
                raise
            return {"saved": True, "success": result["error"] is None,
                    "config": config, "state": result,
                    "message": "设置已保存并执行；请以 PWM 回读和 RPM 确认实际输出"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["init", "tick", "status"])
    args = parser.parse_args()
    controller = Controller()
    if args.command == "init":
        controller.initialize()
    elif args.command == "tick":
        result = controller.tick()
        print(json.dumps(result, ensure_ascii=False))
        return 1 if result["error"] else 0
    else:
        print(json.dumps(controller.status(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
