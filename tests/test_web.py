"""HTTP integration against an isolated controller, including invalid requests."""
import concurrent.futures
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fancontrol import Controller
from fancontrol_web import DemoHardware, make_server


class WebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.controller = Controller(DemoHardware(), root / "config", root / "state",
                                     root / "lock", root / "log", boot_id="http-test")
        self.controller.initialize()
        self.controller.tick()
        self.server = make_server(self.controller, "test-only-token", port=0, demo=True)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(self, path, payload=None, headers=None):
        default = {"Authorization": "Bearer test-only-token"}
        if payload is not None:
            default.update({"Origin": self.base, "Content-Type": "application/json"})
        if headers:
            default.update(headers)
        body = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(self.base + path, data=body, headers=default)
        try:
            response = self.opener.open(request, timeout=5)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            return response.status, response.read(), response.headers

    def test_static_page_contains_no_token_and_no_cache(self):
        code, body, headers = self.request("/")
        self.assertEqual(code, 200)
        self.assertNotIn(b"test-only-token", body)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        for path in ("/app.js", "/style.css"):
            self.assertEqual(self.request(path)[0], 200)

    def test_status_and_apply_and_revision(self):
        code, body, _ = self.request("/api/status")
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(body)["demo"])
        payload = {"mode": "manual", "pwm": 160, "revision": 0}
        code, body, _ = self.request("/api/control", payload)
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(body)["saved"])
        self.assertEqual(self.request("/api/control", payload)[0], 409)
        self.assertEqual(self.controller.config()["revision"], 1)

    def test_host_auth_origin_and_payload_validation(self):
        payload = {"mode": "manual", "pwm": 160, "revision": 0}
        self.assertEqual(self.request("/api/status", headers={"Authorization": ""})[0], 401)
        self.assertEqual(self.request("/api/status", headers={"Host": "evil.test"})[0], 403)
        self.assertEqual(self.request("/api/control", payload, {"Origin": "http://evil.test"})[0], 403)
        for change in ({"pwm": True}, {"pwm": 256}, {"revision": True},
                       {"mode": "shell"}, {"command": "whoami"}):
            self.assertEqual(self.request("/api/control", dict(payload, **change))[0], 400)
        self.assertEqual(self.controller.config()["revision"], 0)

    def test_two_clients_cannot_overwrite_same_revision(self):
        payload = {"mode": "manual", "pwm": 160, "revision": 0}
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(self.request, "/api/control", payload) for _ in range(2)]
            codes = sorted(f.result()[0] for f in futures)
        self.assertEqual(codes, [200, 409])

    def test_ssh_forwarded_local_port_and_invalid_hosts(self):
        self.assertEqual(self.request("/api/status", headers={"Host": "127.0.0.1:19091"})[0], 200)
        payload = {"mode": "manual", "pwm": 160, "revision": 0}
        headers = {"Host": "localhost:19091", "Origin": "http://localhost:19091"}
        self.assertEqual(self.request("/api/control", payload, headers)[0], 200)
        for host in ("evil.test:19091", "user@localhost:19091", "localhost:65536", "localhost:0"):
            self.assertEqual(self.request("/api/status", headers={"Host": host})[0], 403)

    def test_log_api_uses_last_30_lines(self):
        with self.controller.log_path.open("w") as stream:
            stream.write("\n".join(str(i) for i in range(100)) + "\n")
        code, body, _ = self.request("/api/logs")
        self.assertEqual(code, 200)
        lines = json.loads(body)["lines"]
        self.assertEqual(len(lines), 30)
        self.assertEqual(lines[0], "70")
        self.assertEqual(lines[-1], "99")


if __name__ == "__main__":
    unittest.main()
