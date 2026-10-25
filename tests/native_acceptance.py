#!/usr/bin/env python3
"""Explicit root-only native HTTPS checks; temporary PVE tickets stay in memory."""
import argparse
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-native", action="store_true")
    args = parser.parse_args()
    if not args.run_native or sys.platform != "linux" or os.geteuid() != 0:
        parser.error("Run on PVE as root with --run-native")
    # No password or ticket is passed in a shell command or printed in reports.
    perl = ('PVE::Cluster::cfs_update(); print encode_json({'
            'ticket=>PVE::AccessControl::assemble_ticket("root@pam"),'
            'csrf=>PVE::AccessControl::assemble_csrf_prevention_token("root@pam")});')
    result = subprocess.run(["perl", "-MPVE::Cluster", "-MPVE::AccessControl", "-MJSON", "-e", perl],
                            capture_output=True, text=True, check=True, timeout=15)
    identity = json.loads(result.stdout)
    context = ssl.create_default_context(cafile="/etc/pve/pve-root-ca.pem")
    context.check_hostname = False  # loopback test; certificate chain still checked against this PVE CA
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
    node = socket.gethostname().split(".")[0]
    endpoint = "/api2/json/nodes/" + urllib.parse.quote(node, safe="") + "/edge-fancontrol"
    checks = []

    def request(path, payload=None, authenticated=True, csrf=True):
        headers = {}
        if authenticated:
            headers["Cookie"] = "PVEAuthCookie=" + identity["ticket"]
        if payload is not None and csrf:
            headers["CSRFPreventionToken"] = identity["csrf"]
        body = urllib.parse.urlencode(payload).encode() if payload is not None else None
        query = urllib.request.Request("https://127.0.0.1:8006" + path, data=body, headers=headers)
        try:
            response = opener.open(query, timeout=20)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            code, text = response.status, response.read().decode()
            try:
                return code, json.loads(text)
            except ValueError:
                return code, text

    code, html = request("/")
    assert code == 200 and "/pve2/js/edge-fancontrol.js" in html
    code, javascript = request("/pve2/js/edge-fancontrol.js")
    assert code == 200 and "PVE.node.EdgeFanControl" in javascript
    checks.append("PVE HTTPS template loads native node-panel JavaScript")
    code, _ = request(endpoint, authenticated=False)
    assert code == 401
    checks.append("Unauthenticated PVE native status rejected (401)")
    code, response = request(endpoint)
    assert code == 200, (code, response)
    status = response["data"]
    assert status["native_access"]["can_modify"] is True
    assert status["control_available"] and not status["error"]
    checks.append("PVE authenticated root status and node modification capability")
    config = status["config"]
    payload = {"mode": config["mode"], "pwm": config["manual_pwm"], "revision": config["revision"]}
    code, _ = request(endpoint, payload, csrf=False)
    assert code in (401, 403)
    checks.append("Cookie without CSRF cannot POST native control")
    code, _ = request(endpoint, dict(payload, pwm=256))
    assert code == 400
    checks.append("PVE schema rejects PWM256 before control execution")
    code, response = request(endpoint, dict(payload, revision=config["revision"] + 1000))
    assert code == 200 and response["data"]["success"] is False
    checks.append("Native configuration revision conflict rejected")
    code, response = request(endpoint, payload)
    assert code == 200 and response["data"]["success"] is True
    assert response["data"]["config"]["mode"] == config["mode"]
    checks.append("Authenticated CSRF-protected control executes and preserves selected mode")
    code, response = request(endpoint + "/logs")
    assert code == 200 and len(response["data"]["lines"]) <= 30
    checks.append("PVE native log endpoint returns at most 30 lines")
    print(json.dumps({"passed": True, "checks": checks}, ensure_ascii=False))


if __name__ == "__main__":
    main()
