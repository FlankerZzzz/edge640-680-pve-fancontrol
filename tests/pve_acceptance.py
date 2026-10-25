#!/usr/bin/env python3
"""Explicit live PVE acceptance: own stress group; safe full-speed fault injection."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live", action="store_true", help="Authorize actual PWM writes and CPU load")
    parser.add_argument("--stress-seconds", type=int, default=120)
    args = parser.parse_args()
    if not args.run_live or sys.platform != "linux" or os.geteuid() != 0:
        parser.error("Run on PVE as root with --run-live; this changes actual fan settings")
    if not 10 <= args.stress_seconds <= 300:
        parser.error("stress-seconds must be 10–300")
    root = Path(tempfile.mkdtemp(prefix="acceptance-", dir="/var/lib/fancontroller-pwm"))
    os.chmod(root, 0o700)
    token = Path("/etc/edge-fancontrol/web-token").read_text().strip()
    base = "http://127.0.0.1:19090"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    events = []
    checks = []
    original = None
    stress = None
    dropin = Path("/run/systemd/system/fancontroller-pwm.service.d/99-acceptance-fault.conf")
    dropin_created = False
    report = {"started_at": time.time(), "passed": False, "events": events, "checks": checks}

    def command(*parts, check=True):
        return subprocess.run(parts, capture_output=True, text=True, timeout=30, check=check)

    def api(path="/api/status", payload=None, auth=True):
        headers = {"Authorization": "Bearer " + token} if auth else {}
        body = None
        if payload is not None:
            body = json.dumps(payload).encode()
            headers.update({"Content-Type": "application/json", "Origin": base})
        request = urllib.request.Request(base + path, data=body, headers=headers)
        with opener.open(request, timeout=10) as response:
            return json.load(response)

    def snapshot(stage):
        status = api()
        current, live = status["state"], status["live"]
        event = {"stage": stage, "at": time.time(), "temp": live.get("temp"),
                 "rpm": live.get("rpm"), "requested": current.get("last_pwm"),
                 "readback": live.get("pwm"), "reason": current.get("reason"),
                 "wait": status["cooldown_remaining"], "error": status.get("error")}
        events.append(event)
        print(json.dumps(event, ensure_ascii=False), flush=True)
        return status

    def wait_for(predicate, seconds, stage):
        deadline = time.monotonic() + seconds
        while True:
            status = snapshot(stage)
            if predicate(status):
                return status
            if time.monotonic() >= deadline:
                raise AssertionError("Timed out: " + stage)
            time.sleep(10)

    def select(mode, pwm):
        current = api()
        return api("/api/control", {"mode": mode, "pwm": pwm,
                                    "revision": current["config"]["revision"]})

    def stop_stress():
        if stress is not None and stress.poll() is None:
            os.killpg(stress.pid, signal.SIGTERM)
            try:
                stress.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(stress.pid, signal.SIGKILL)
                stress.wait(timeout=5)

    try:
        initial = snapshot("initial")
        original = dict(initial["config"])
        assert all(initial["services"][key] == "active" for key in ("timer", "i2c", "watchdog", "logrotate"))
        for path in ("/", "/app.js", "/style.css"):
            with opener.open(base + path, timeout=5) as response:
                assert response.status == 200
        try:
            api(auth=False)
            raise AssertionError("Unauthenticated API allowed")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
        checks.append("HTTP assets / authentication / all timers active")
        result = command("logrotate", "--debug", "/etc/logrotate.d/edge-fancontrol")
        (root / "logrotate-debug.txt").write_text(result.stdout + result.stderr)
        assert "30 rotations" in result.stderr and "30 days" in result.stderr
        command("logrotate", "--force", "/etc/logrotate.d/edge-fancontrol")
        assert Path("/var/log/fancontroller-pwm.log").exists()
        assert list(Path("/var/log").glob("fancontroller-pwm.log-*") )
        checks.append("Real logrotate dry-run and one forced rotation")
        if initial["config"]["mode"] != "auto":
            select("auto", initial["config"]["manual_pwm"])
        wait_for(lambda s: s["state"]["reason"] == "auto" and s["live"]["pwm"] < 255,
                 160, "initial_idle")
        stress_log = (root / "stress-ng.log").open("w")
        stress = subprocess.Popen(["stress-ng", "--cpu", "16", "--timeout",
                                   str(args.stress_seconds) + "s", "--metrics-brief"],
                                  stdout=stress_log, stderr=subprocess.STDOUT,
                                  start_new_session=True)
        try:
            while stress.poll() is None:
                status = snapshot("stress")
                if status["live"]["temp"] is None or status["live"]["temp"] >= 80:
                    raise AssertionError("Stress stopped: missing temperature or temperature >=80C")
                if status.get("error"):
                    raise AssertionError(status["error"])
                time.sleep(10)
            assert stress.returncode == 0
        finally:
            stop_stress()
            stress_log.close()
        stress_text = (root / "stress-ng.log").read_text()
        assert "failed: 0" in stress_text
        checks.append(f"stress-ng 16 workers / {args.stress_seconds}s / failed=0")
        idle = wait_for(lambda s: s["state"]["reason"] == "auto" and s["live"]["pwm"] < 255,
                        180, "post_stress_cooldown")
        assert idle["live"]["temp"] < idle["config"]["full_temp"]
        checks.append("Real temperature fall / cooldown / reduced PWM")

        sys.path.insert(0, "/usr/local/lib/edge-fancontrol")
        from fancontrol import Controller, Hardware

        class MissingTemperature(Hardware):
            def sample(self):
                sample = super().sample()
                sample["temp"] = None
                return sample

        # Inject only the controller's input; leave real sensor bindings intact.
        failed = Controller(hardware=MissingTemperature()).tick()
        assert failed["reason"] == "failsafe" and failed["readback_pwm"] == 255
        snapshot("injected_missing_temperature")
        checks.append("Injected missing temperature writes and reads back PWM255")
        invalid = root / "invalid-config.json"
        invalid.write_text("{broken json")
        failed = Controller(config=invalid).tick()
        assert failed["reason"] == "failsafe" and failed["readback_pwm"] == 255
        assert Path("/etc/edge-fancontrol/config.json").read_text() != "{broken json"
        checks.append("Isolated corrupt config writes PWM255; real config retained")

        command("systemctl", "stop", "fancontroller-pwm.timer")
        try:
            command("systemctl", "start", "fancontroller-watchdog.service")
            assert Hardware().sample()["pwm"] == 255
            checks.append("Independent watchdog sees inactive timer and reads PWM255")
            if dropin.exists():
                raise RuntimeError("Acceptance drop-in already exists; refusing to overwrite")
            before = command("systemctl", "show", "fancontroller-failsafe.service",
                             "-p", "InvocationID", "--value").stdout.strip()
            command("systemctl", "stop", "fancontroller-pwm.service")
            dropin.parent.mkdir(parents=True, exist_ok=True)
            dropin.write_text("[Service]\nExecStart=\nExecStart=/usr/bin/false\n")
            dropin_created = True
            command("systemctl", "daemon-reload")
            result = command("systemctl", "start", "fancontroller-pwm.service", check=False)
            assert result.returncode != 0
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                after = command("systemctl", "show", "fancontroller-failsafe.service",
                                "-p", "InvocationID", "--value").stdout.strip()
                if after and after != before:
                    break
                time.sleep(0.5)
            else:
                raise AssertionError("OnFailure did not invoke failsafe unit")
            assert Hardware().sample()["pwm"] == 255
            checks.append("Real systemd OnFailure invokes independent full-PWM service")
        finally:
            if dropin_created:
                dropin.unlink(missing_ok=True)
                dropin_created = False
            command("systemctl", "daemon-reload")
            command("systemctl", "reset-failed", "fancontroller-pwm.service", check=False)
            command("systemctl", "start", "fancontroller-pwm.timer")
            command("systemctl", "start", "fancontroller-pwm.service")

        select("manual", 255)
        command("systemctl", "restart", "fancontroller-web.service")
        deadline = time.monotonic() + 15
        while True:
            try:
                current = api()
                assert current["config"]["mode"] == "manual" and current["config"]["manual_pwm"] == 255
                break
            except (OSError, urllib.error.URLError):
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.5)
        checks.append("Manual PWM255 saved and survives Web-service restart")
        select(original["mode"], original["manual_pwm"])
        wait_for(lambda s: s["error"] is None and s["state"]["reason"] == original["mode"]
                 and (s["live"]["pwm"] < 255 if original["mode"] == "auto"
                      else s["state"]["last_pwm"] == original["manual_pwm"]),
                 180, "fallback_recovery")
        checks.append("Fallback recovered after cooldown; original setting restored")
        report["passed"] = True
    except Exception as exc:
        report["failure"] = str(exc)
        print("ACCEPTANCE FAILED: " + str(exc), flush=True)
    finally:
        stop_stress()
        if dropin_created:
            dropin.unlink(missing_ok=True)
            command("systemctl", "daemon-reload", check=False)
        command("systemctl", "reset-failed", "fancontroller-pwm.service", check=False)
        command("systemctl", "start", "fancontroller-pwm.timer", check=False)
        try:
            sys.path.insert(0, "/usr/local/lib/edge-fancontrol")
            from fancontrol import Controller
            controller = Controller()
            controller.tick()
            current = controller.config()
            if original and (current["mode"], current["manual_pwm"]) != (original["mode"], original["manual_pwm"]):
                controller.apply(original["mode"], original["manual_pwm"], current["revision"])
        except Exception as exc:
            report["restore_error"] = str(exc)
            report["passed"] = False
        report["finished_at"] = time.time()
        (root / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
        print(json.dumps({"passed": report["passed"], "checks": checks, "report": str(root / "report.json")}, ensure_ascii=False), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
