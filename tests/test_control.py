"""Deterministic hardware-fault and recovery tests; no real fan writes."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fancontrol import Controller, Hardware, Conflict, atomic_json


class FakeHardware:
    def __init__(self):
        self.temp, self.pwm, self.rpm = 52, 119, [3600, 3500]
        self.fail_read = False
        self.fail_write = False
        self.writes = []

    def sample(self):
        if self.fail_read:
            raise OSError("I2C read failed")
        return {"temp": self.temp, "lm75": 39, "pwm": self.pwm,
                "pwm_mode": 1, "rpm": self.rpm, "device": "fake"}

    def write(self, pwm):
        self.writes.append(pwm)
        if self.fail_write:
            raise OSError("I2C write failed")
        self.pwm = pwm
        return pwm


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.hw = FakeHardware()
        self.now = 1000
        self.controller = Controller(self.hw, config=root / "config", state=root / "state",
                                     lock=root / "lock", log=root / "log",
                                     clock=lambda: self.now, wall=lambda: self.now,
                                     boot_id="test-boot")
        self.controller.initialize()

    def advance(self, seconds):
        self.now += seconds
        return self.controller.tick()

    def settle(self):
        self.controller.tick()
        return self.advance(120)

    def test_auto_curve(self):
        self.assertEqual(self.settle()["last_pwm"], 119)
        self.hw.temp = 55
        self.assertEqual(self.advance(10)["last_pwm"], 170)
        self.hw.temp = 60
        self.assertEqual(self.advance(10)["last_pwm"], 255)

    def test_cooldown_not_reset_by_ticks(self):
        self.settle()
        self.hw.temp = 49
        first = self.advance(10)
        start = first["pending_since"]
        for _ in range(11):
            current = self.advance(10)
            self.assertEqual(current["last_pwm"], 119)
            self.assertEqual(current["pending_since"], start)
        self.assertEqual(self.advance(10)["last_pwm"], 68)

    def test_temperature_rise_cancels_pending(self):
        self.settle()
        self.hw.temp = 49
        self.advance(10)
        self.hw.temp = 55
        state = self.advance(10)
        self.assertEqual(state["last_pwm"], 170)
        self.assertIsNone(state["pending_since"])

    def test_hot_manual_mode_and_exact_recovery_wait(self):
        self.settle()
        self.controller.apply("manual", 77, 0)
        self.hw.temp = 65
        self.advance(10)
        self.hw.temp = 52
        self.assertEqual(self.advance(119)["last_pwm"], 255)
        state = self.advance(1)
        self.assertEqual(state["last_pwm"], 77)
        self.assertEqual(self.controller.config()["manual_pwm"], 77)

    def test_missing_invalid_temperature_full_speed(self):
        for value in (None, float("nan"), float("inf"), -10, 130, "bad"):
            with self.subTest(value=value):
                self.hw.temp = value
                state = self.controller.tick()
                self.assertEqual(state["last_pwm"], 255)
                self.assertEqual(state["reason"], "failsafe")

    def test_i2c_read_failure_full_speed(self):
        self.hw.fail_read = True
        self.assertEqual(self.controller.tick()["reason"], "failsafe")
        self.assertEqual(self.hw.writes[-1], 255)

    def test_write_failure_reported_not_claimed_success(self):
        self.hw.fail_write = True
        state = self.controller.tick()
        self.assertIsNone(state["readback_pwm"])
        self.assertIn("全速写入失败", state["error"])

    def test_corrupt_config_full_speed(self):
        self.controller.config_path.write_text("broken", encoding="utf-8")
        self.assertEqual(self.controller.tick()["last_pwm"], 255)
        self.assertEqual(self.controller.config_path.read_text(), "broken")

    def test_missing_config_does_not_silently_restore_default(self):
        self.controller.config_path.unlink()
        state = self.controller.tick()
        self.assertEqual(state["last_pwm"], 255)
        self.assertEqual(state["reason"], "failsafe")
        self.assertFalse(self.controller.config_path.exists())

    def test_repaired_sensor_recovers_after_single_cooldown(self):
        self.hw.temp = None
        state = self.controller.tick()
        self.assertEqual(state["last_pwm"], 255)
        self.hw.temp = 52
        self.assertEqual(self.advance(119)["last_pwm"], 255)
        state = self.advance(1)
        self.assertEqual(state["last_pwm"], 119)
        self.assertIsNone(state["error"])

    def test_shutdown_to_zero_and_startup_grace_resets(self):
        config = self.controller.config()
        config["cooldown_seconds"] = 0
        atomic_json(self.controller.config_path, config)
        self.hw.temp = 40
        self.assertEqual(self.controller.tick()["last_pwm"], 0)
        self.hw.rpm = [0, 0]
        self.assertIsNone(self.advance(60)["error"])
        self.hw.temp = 55
        self.assertEqual(self.advance(1)["last_pwm"], 170)
        self.assertIsNone(self.advance(29)["error"])
        self.assertIsNotNone(self.advance(1)["error"])

    def test_failed_save_forces_full_without_new_revision(self):
        self.settle()
        with patch("fancontrol.atomic_json", side_effect=OSError("read-only config")):
            with self.assertRaises(OSError):
                self.controller.apply("manual", 100, 0)
        self.assertEqual(self.hw.writes[-1], 255)
        self.assertEqual(self.controller.config()["revision"], 0)

    def test_legacy_text_state_is_ignored(self):
        self.controller.state_path.write_text("255 1786818324")
        state = self.controller.tick()
        self.assertEqual(state["last_pwm"], 255)
        self.assertIsNone(state["error"])

    def test_fan_startup_grace_and_stall_fallback(self):
        self.hw.rpm = [0, 0]
        self.controller.tick()
        self.assertIsNone(self.advance(29)["error"])
        self.assertIn("转速异常", self.advance(1)["error"])
        self.assertEqual(self.hw.writes[-1], 255)

    def test_log_or_state_write_error_still_requests_full(self):
        self.settle()
        with patch("fancontrol.atomic_json", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.controller.tick()
        self.assertEqual(self.hw.writes[-1], 255)
        self.controller.log_path.unlink()
        self.controller.log_path.mkdir()
        with self.assertRaises(OSError):
            self.controller.tick()
        self.assertEqual(self.hw.writes[-1], 255)

    def test_bad_revision_and_out_of_range_do_not_save(self):
        self.settle()
        for pwm in (-1, 256, True, "160"):
            with self.assertRaises(ValueError):
                self.controller.apply("manual", pwm, 0)
        with self.assertRaises(Conflict):
            self.controller.apply("manual", 160, 9)
        self.assertEqual(self.controller.config()["revision"], 0)

    def test_settings_persist_and_stale_control_refused(self):
        self.settle()
        self.controller.apply("manual", 160, 0)
        self.assertEqual(json.loads(self.controller.config_path.read_text())["manual_pwm"], 160)
        self.assertEqual(self.controller.status()["config"]["revision"], 1)
        self.now += 36
        self.assertTrue(self.controller.status()["stale"])
        with self.assertRaises(Conflict):
            self.controller.apply("auto", 160, 1)

    def test_boot_id_and_corrupt_state_discarded(self):
        self.settle()
        saved = self.controller.load_state()
        saved["boot_id"] = "old-boot"
        atomic_json(self.controller.state_path, saved)
        self.assertEqual(self.controller.load_state(), {})
        self.controller.state_path.write_text("garbage")
        self.assertEqual(self.controller.load_state(), {})


class SysfsTests(unittest.TestCase):
    def test_package_temperature_and_tc654_pwm_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cpu = root / "hwmon1"
            fan = root / "hwmon4"
            cpu.mkdir(); fan.mkdir()
            for filename, value in {"name": "coretemp", "temp1_label": "Package id 0",
                                    "temp1_input": "52000", "temp2_label": "Core 0",
                                    "temp2_input": "99000", "temp3_label": "Package id 1",
                                    "temp3_input": "56000"}.items():
                (cpu / filename).write_text(value)
            for filename, value in {"name": "tc654", "pwm1": "119", "pwm1_mode": "0",
                                    "fan1_input": "3600", "fan2_input": "3500"}.items():
                (fan / filename).write_text(value)
            hw = Hardware(root)
            self.assertEqual(hw.sample()["temp"], 56)
            self.assertEqual(hw.write(255), 255)
            self.assertEqual((fan / "pwm1_mode").read_text().strip(), "1")
            self.assertFalse((fan / "pwm1_enable").exists())


if __name__ == "__main__":
    unittest.main()
