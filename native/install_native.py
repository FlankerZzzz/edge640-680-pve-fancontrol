#!/usr/bin/env python3
"""Transactional PVE-native hook installer. Preserves stock code around markers."""
import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile

API_BEGIN = "# BEGIN EDGE_FANCONTROL_NATIVE"
API_END = "# END EDGE_FANCONTROL_NATIVE"
HTML_BEGIN = "<!-- BEGIN EDGE_FANCONTROL_NATIVE -->"
HTML_END = "<!-- END EDGE_FANCONTROL_NATIVE -->"
HERE = Path(__file__).resolve().parent
NODES = Path("/usr/share/perl5/PVE/API2/Nodes.pm")
TEMPLATE = Path("/usr/share/pve-manager/index.html.tpl")
MODULE = Path("/usr/share/perl5/PVE/API2/EdgeFanControl.pm")
JAVASCRIPT = Path("/usr/share/pve-manager/js/edge-fancontrol.js")
ADAPTER = Path("/usr/local/lib/edge-fancontrol/native_api.py")
WEB = Path("/usr/local/lib/edge-fancontrol/fancontrol_web.py")


def strip_block(text, begin, end):
    if text.count(begin) != text.count(end) or text.count(begin) > 1:
        raise ValueError("Integration markers are damaged; refusing to modify file")
    return re.sub(r"\n?" + re.escape(begin) + r"[\s\S]*?" + re.escape(end), "", text)


def patch_api(text):
    text = strip_block(text, API_BEGIN, API_END)
    if "package PVE::API2::Nodes::Nodeinfo;" not in text or "package PVE::API2::Nodes;" not in text:
        raise ValueError("Unsupported PVE Nodes module layout")
    ending = re.search(r"\n1;\s*\Z", text)
    if not ending:
        raise ValueError("PVE Nodes module terminator not found")
    hook = (API_BEGIN + "\nrequire PVE::API2::EdgeFanControl;\n"
            "PVE::API2::Nodes::Nodeinfo->register_method({\n"
            "    subclass => 'PVE::API2::EdgeFanControl', path => 'edge-fancontrol',\n"
            "});\n" + API_END)
    return text[:ending.start()] + "\n" + hook + text[ending.start():]


def patch_template(text, revision):
    text = strip_block(text, HTML_BEGIN, HTML_END)
    anchor = re.search(r'^[ \t]*<script[^\n]*src=[\'\"]/pve2/js/pvemanagerlib\.js[^\n]*</script>', text, re.M)
    if not anchor:
        raise ValueError("PVE manager script anchor not found")
    hook = ("\n" + HTML_BEGIN + '\n    <script src="/pve2/js/edge-fancontrol.js?v=' +
            revision + '"></script>\n' + HTML_END)
    return text[:anchor.end()] + hook + text[anchor.end():]


def replace(path, data, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".edge-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def run(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError("Command failed: " + " ".join(args) + "\n" + result.stderr[-4000:])
    return result


def reload_pve():
    # Gracefully restart API/Web workers; do not reboot or change VM services.
    run("systemctl", "reload", "pvedaemon.service")
    run("systemctl", "reload", "pveproxy.service")


def install():
    if not Path("/usr/local/lib/edge-fancontrol/fancontrol.py").exists():
        raise RuntimeError("Install the base fan controller first: bash ./install.sh")
    for path in (NODES, TEMPLATE, Path("/usr/share/pve-manager/js/pvemanagerlib.js")):
        if not path.is_file():
            raise RuntimeError("Not a supported PVE installation: " + str(path))
    manager = Path("/usr/share/pve-manager/js/pvemanagerlib.js").read_text()
    if not all(marker in manager for marker in ("Ext.define('PVE.node.Config'", "Ext.define('PVE.panel.Config'", "me.insertNodes(me.items)")):
        raise RuntimeError("Unsupported PVE UI layout; refusing to inject a hook")
    for path in (MODULE, JAVASCRIPT, ADAPTER):
        if path.exists() and "EDGE_FANCONTROL_NATIVE" not in path.read_text():
            raise RuntimeError("An unrelated file occupies " + str(path))
    script = (HERE / "edge-fancontrol.js").read_bytes()
    revision = hashlib.sha256(script).hexdigest()[:12]
    payloads = {
        MODULE: (HERE / "EdgeFanControl.pm").read_bytes(),
        JAVASCRIPT: script,
        ADAPTER: (HERE / "native_api.py").read_bytes(),
        WEB: (HERE.parent / "src/fancontrol_web.py").read_bytes(),
        NODES: patch_api(NODES.read_text()).encode(),
        TEMPLATE: patch_template(TEMPLATE.read_text(), revision).encode(),
    }
    originals = {p: p.read_bytes() if p.exists() else None for p in payloads}
    modes = {p: p.stat().st_mode & 0o777 if p.exists() else 0o644 for p in payloads}
    backup_root = Path("/var/lib/fancontroller-pwm/native-backups")
    backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = Path(tempfile.mkdtemp(prefix="install-", dir=backup_root))
    for path, data in originals.items():
        if data is not None:
            target = backup / path.relative_to("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    try:
        for path, data in payloads.items():
            replace(path, data, modes[path])
        run("perl", "-e", "use PVE::API2::Nodes; print qq(API registration OK\\n);")
        node = socket.gethostname().split(".")[0]
        run("pvesh", "get", "/nodes/" + node + "/edge-fancontrol", "--output-format", "json")
        reload_pve()
        run("systemctl", "try-restart", "fancontroller-web.service")
    except Exception:
        for path, data in originals.items():
            if data is None:
                path.unlink(missing_ok=True)
            else:
                replace(path, data, modes[path])
        try:
            reload_pve()
        except Exception as error:
            print("Rollback worker reload requires inspection: " + str(error))
        raise
    print("PVE-native panel installed. Backup: " + str(backup))
    print("Refresh the PVE page, select this node, then click 风扇控制.")


def remove():
    # Remove only our marked hooks. Never restore an old full PVE package file.
    for path, begin, end in ((NODES, API_BEGIN, API_END), (TEMPLATE, HTML_BEGIN, HTML_END)):
        if path.exists():
            before = path.read_text()
            after = strip_block(before, begin, end)
            if before != after:
                replace(path, after.encode(), path.stat().st_mode & 0o777)
    for path in (MODULE, JAVASCRIPT, ADAPTER):
        if path.exists() and "EDGE_FANCONTROL_NATIVE" in path.read_text():
            path.unlink()
    reload_pve()
    print("PVE-native panel removed; base fan controller continues running.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("install", "remove"))
    args = parser.parse_args()
    if os.name != "posix" or os.geteuid() != 0:
        parser.error("Run as root on PVE")
    (install if args.action == "install" else remove)()


if __name__ == "__main__":
    main()
