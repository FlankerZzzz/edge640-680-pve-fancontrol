"""Exercise the shipped logrotate rule against aged, isolated archive fixtures."""
import datetime
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest


@unittest.skipUnless(sys.platform == "linux" and shutil.which("logrotate") and os.geteuid() == 0,
                     "requires Linux root and logrotate; fixtures only")
class RetentionTests(unittest.TestCase):
    def test_30_day_cleanup_runs_even_after_log_becomes_empty(self):
        with tempfile.TemporaryDirectory(prefix="edge-logrotate-test-") as directory:
            root = Path(directory)
            active = root / "fan.log"
            active.touch()
            now = time.time()
            for age in range(1, 34):
                date = datetime.datetime.fromtimestamp(now - age * 86400).strftime("%Y%m%d")
                archive = root / ("fan.log-" + date)
                archive.write_text("fixture only\n")
                os.utime(archive, (now - age * 86400, now - age * 86400))
            rule = (Path(__file__).resolve().parents[1] / "config/logrotate").read_text()
            config = root / "logrotate.conf"
            config.write_text(rule.replace("/var/log/fancontroller-pwm.log", str(active)))
            result = subprocess.run(["logrotate", "--force", "--state", str(root / "status"), str(config)],
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            archives = list(root.glob("fan.log-*"))
            self.assertLessEqual(len(archives), 30)
            self.assertGreater(len(archives), 0)
            self.assertTrue(all(now - p.stat().st_mtime <= 30 * 86400 + 60 for p in archives))
            today = datetime.datetime.fromtimestamp(now).strftime("%Y%m%d")
            self.assertTrue((root / ("fan.log-" + today)).exists(), "empty log did not rotate")
            self.assertTrue(active.exists(), "active log was not recreated")
            self.assertTrue(any(p.suffix == ".gz" for p in archives), "older archives were not compressed")


if __name__ == "__main__":
    unittest.main()
