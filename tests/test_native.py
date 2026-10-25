"""Reversible PVE hooks and native adapter tests; no stock-file writes."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


installer = load("native_installer", ROOT / "native/install_native.py")
adapter = load("native_adapter", ROOT / "native/native_api.py")


class NativeTests(unittest.TestCase):
    def test_api_hook_round_trip_and_idempotence(self):
        source = "package PVE::API2::Nodes::Nodeinfo;\n# keep user changes\npackage PVE::API2::Nodes;\n\n1;\n"
        result = installer.patch_api(source)
        self.assertEqual(installer.patch_api(result), result)
        self.assertEqual(installer.strip_block(result, installer.API_BEGIN, installer.API_END), source)
        self.assertEqual(result.count("require PVE::API2::EdgeFanControl"), 1)

    def test_template_round_trip_and_updated_asset_hash(self):
        source = '<head>\n<script src="/pve2/js/pvemanagerlib.js?ver=9.2"></script>\n<script>Ext.onReady(start);</script>\n</head>'
        first = installer.patch_template(source, "abc")
        self.assertEqual(installer.patch_template(first, "abc"), first)
        second = installer.patch_template(first, "def")
        self.assertEqual(second.count("edge-fancontrol.js"), 1)
        self.assertIn("?v=def", second)
        self.assertEqual(installer.strip_block(second, installer.HTML_BEGIN, installer.HTML_END), source)

    def test_unsupported_and_damaged_hooks_refused(self):
        for value in ("not PVE", installer.API_BEGIN + "\nbroken"):
            with self.assertRaises(ValueError):
                installer.patch_api(value)
        with self.assertRaises(ValueError):
            installer.patch_template("<html>missing scripts</html>", "abc")

    def test_adapter_refuses_control_without_watchdog(self):
        with patch.object(adapter, "service_status", return_value={"timer":"active", "watchdog":"inactive"}):
            with self.assertRaises(adapter.Conflict):
                adapter.dispatch(None, "control", "manual", 160, 0)

    def test_perl_routes_require_node_acl_and_protected_execution(self):
        source = (ROOT / "native/EdgeFanControl.pm").read_text()
        self.assertEqual(source.count("protected => 1, proxyto => 'node'"), 3)
        self.assertIn("['Sys.Modify']", source)
        self.assertIn("'/nodes/{node}'", source)
        self.assertNotIn("user => 'all'", source)
        self.assertNotIn("/bin/sh", source)

    @unittest.skipUnless(shutil.which("node"), "Node only needed for developer-side navigation test")
    def test_real_navigation_hook_and_request_contract(self):
        result = subprocess.run(["node", str(ROOT / "tests/native_navigation.cjs")],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
