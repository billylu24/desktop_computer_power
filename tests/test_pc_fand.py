#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import tempfile
import unittest


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "pc-fand.py"
SPEC = importlib.util.spec_from_file_location("pc_fand", MODULE_PATH)
pc_fand = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(pc_fand)


class FanAlgorithmTests(unittest.TestCase):
    def setUp(self):
        self.profile = {
            sensor: [[40, 20], [60, 40], [80, 100]]
            for sensor in pc_fand.SENSORS
        }
        self.emergency = {
            "cpu_tctl_c": 90,
            "gpu_core_c": 84,
            "gpu_junction_c": 94,
            "gpu_vram_c": 90,
            "release_seconds": 30,
        }

    def calculate(self, values, now=100.0, emergency_until=0.0):
        return pc_fand.demands_for(
            values, values, self.profile, self.emergency,
            emergency_until, now,
        )

    def test_linear_interpolation_and_clamps(self):
        points = [[45, 25], [55, 30], [65, 50]]
        self.assertEqual(pc_fand.interpolate(points, 30), 25)
        self.assertAlmostEqual(pc_fand.interpolate(points, 60), 40)
        self.assertEqual(pc_fand.interpolate(points, 90), 50)

    def test_partial_gpu_failure_uses_50_percent_case_floor(self):
        values = {
            "cpu_tctl": 50,
            "gpu_core": 50,
            "gpu_junction": None,
            "gpu_vram": None,
        }
        cpu, case, _, _, warnings = self.calculate(values)
        self.assertLess(cpu, 50)
        self.assertEqual(case, 50)
        self.assertTrue(any("50%" in warning for warning in warnings))

    def test_all_gpu_failure_uses_70_percent_case_floor(self):
        values = {
            "cpu_tctl": 50,
            "gpu_core": None,
            "gpu_junction": None,
            "gpu_vram": None,
        }
        cpu, case, _, _, _ = self.calculate(values)
        self.assertEqual(case, 70)
        self.assertLess(cpu, 100)

    def test_cpu_failure_uses_cpu_100_and_case_70(self):
        values = {
            "cpu_tctl": None,
            "gpu_core": 50,
            "gpu_junction": 50,
            "gpu_vram": 50,
        }
        cpu, case, _, _, _ = self.calculate(values)
        self.assertEqual(cpu, 100)
        self.assertEqual(case, 70)

    def test_all_failure_uses_all_fans_100(self):
        values = {sensor: None for sensor in pc_fand.SENSORS}
        cpu, case, _, _, _ = self.calculate(values)
        self.assertEqual((cpu, case), (100, 100))

    def test_emergency_bypasses_filter(self):
        raw = {
            "cpu_tctl": 50,
            "gpu_core": 40,
            "gpu_junction": 94,
            "gpu_vram": 40,
        }
        filtered = dict(raw, gpu_junction=50)
        cpu, case, until, _, _ = pc_fand.demands_for(
            raw, filtered, self.profile, self.emergency, 0, 100,
        )
        self.assertEqual((cpu, case), (100, 100))
        self.assertEqual(until, 130)

    def test_emergency_hold_remains_active(self):
        values = {sensor: 40 for sensor in pc_fand.SENSORS}
        cpu, case, until, _, _ = self.calculate(values, now=110, emergency_until=120)
        self.assertEqual((cpu, case), (100, 100))
        self.assertEqual(until, 120)

    def test_slew_rises_fast_and_falls_slow(self):
        self.assertEqual(pc_fand.slew(30, 80, 10, 2), 40)
        self.assertEqual(pc_fand.slew(80, 30, 10, 2), 78)

    def test_disabled_unmapped_config_is_allowed_for_dry_run(self):
        text = """[controller]
enabled=false

[cpu]
pwm=UNMAPPED
fan_input=UNMAPPED
minimum_start_pwm=UNCALIBRATED
minimum_stable_pwm=UNCALIBRATED
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fans.conf"
            path.write_text(text, encoding="utf-8")
            _, channels = pc_fand.parse_fans(path, allow_unmapped=True)
        self.assertEqual(channels, [])

    def test_enabled_incomplete_config_is_rejected_even_for_dry_run(self):
        text = """[controller]
enabled=true

[cpu]
pwm=UNMAPPED
fan_input=UNMAPPED
minimum_start_pwm=UNCALIBRATED
minimum_stable_pwm=UNCALIBRATED
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fans.conf"
            path.write_text(text, encoding="utf-8")
            with self.assertRaises(pc_fand.ConfigurationError):
                pc_fand.parse_fans(path, allow_unmapped=True)


if __name__ == "__main__":
    unittest.main()
