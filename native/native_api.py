#!/usr/bin/env python3
"""EDGE_FANCONTROL_NATIVE: invoked only by the protected PVE API module."""
import argparse
import json
# Installed beside fancontrol.py; tests supply the checkout's src directory.
from fancontrol import Controller, Conflict
from fancontrol_web import panel_status, service_status, tail_logs


def dispatch(controller, action, mode=None, pwm=None, revision=None):
    if action == "status":
        return panel_status(controller)
    if action == "logs":
        return tail_logs(controller)
    if action != "control":
        raise ValueError("Unsupported action")
    services = service_status()
    if any(services[key] != "active" for key in ("timer", "watchdog")):
        raise Conflict("温控定时器或 watchdog 未运行，请先恢复保护服务")
    return controller.apply(mode, pwm, revision)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("status", "logs", "control"))
    parser.add_argument("--mode", choices=("auto", "manual"))
    parser.add_argument("--pwm", type=int)
    parser.add_argument("--revision", type=int)
    args = parser.parse_args()
    if args.action == "control" and (args.mode is None or args.pwm is None or args.revision is None):
        parser.error("control requires mode, pwm and revision")
    try:
        result = dispatch(Controller(), args.action, args.mode, args.pwm, args.revision)
    except (Conflict, ValueError, OSError) as exc:
        result = {"success": False, "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
