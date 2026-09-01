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

    def test_partial_gpu_failure_uses_50_percent_sys_floor(self):
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

    def test_all_gpu_failure_uses_70_percent_sys_floor(self):
        values = {
            "cpu_tctl": 50,
            "gpu_core": None,
            "gpu_junction": None,
            "gpu_vram": None,
        }
        cpu, case, _, _, _ = self.calculate(values)
        self.assertEqual(case, 70)
        self.assertLess(cpu, 100)

    def test_cpu_failure_uses_cpu_100_and_sys_70(self):
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

    def test_gpu_airflow_floor_for_cpu_fan(self):
        base = {
            "cpu_tctl": 40,
            "gpu_core": 40,
            "gpu_junction": 74,
            "gpu_vram": 71,
        }
        cpu, _, _, _, _ = self.calculate(base)
        self.assertEqual(cpu, 20)
        cpu, _, _, _, _ = self.calculate(dict(base, gpu_junction=75))
        self.assertEqual(cpu, 35)
        cpu, _, _, _, _ = self.calculate(dict(base, gpu_junction=85))
        self.assertEqual(cpu, 45)
        cpu, _, _, _, _ = self.calculate(dict(base, gpu_vram=86))
        self.assertEqual(cpu, 60)

    def test_global_group_floors(self):
        self.assertEqual(pc_fand.apply_group_floors(20, 25, 30, 35), (30, 35))
        self.assertEqual(pc_fand.apply_group_floors(50, 60, 30, 35), (50, 60))

    def test_disabled_unmapped_config_is_allowed_for_dry_run(self):
        text = """[controller]
enabled=false
cpu_fan_min_percent=30
sys_fan_min_percent=35

[cpu]
pwm_paths=UNMAPPED
fan_inputs=UNMAPPED

[sys]
pwm_paths=UNMAPPED
fan_inputs=UNMAPPED
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fans.conf"
            path.write_text(text, encoding="utf-8")
            _, channels = pc_fand.parse_fans(path, allow_unmapped=True)
        self.assertEqual(channels, [])

    def test_enabled_incomplete_config_is_rejected_even_for_dry_run(self):
        text = """[controller]
enabled=true
cpu_fan_min_percent=30
sys_fan_min_percent=35

[cpu]
pwm_paths=UNMAPPED
fan_inputs=UNMAPPED

[sys]
pwm_paths=UNMAPPED
fan_inputs=UNMAPPED
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fans.conf"
            path.write_text(text, encoding="utf-8")
            with self.assertRaises(pc_fand.ConfigurationError):
                pc_fand.parse_fans(path, allow_unmapped=True)

    def test_two_zone_mapping_supports_multiple_headers(self):
        text = """[controller]
enabled=true
cpu_fan_min_percent=30
sys_fan_min_percent=35

[cpu]
pwm_paths=pwm1
fan_inputs=fan1_input
names=CPU_FAN

[sys]
pwm_paths=pwm3,pwm6
fan_inputs=fan3_input,fan6_input
names=SYS_A,SYS_B
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fans.conf"
            path.write_text(text, encoding="utf-8")
            _, channels = pc_fand.parse_fans(path, allow_unmapped=False)
        self.assertEqual([channel["role"] for channel in channels], ["cpu", "sys", "sys"])
        self.assertEqual([channel["minimum_percent"] for channel in channels], [30, 35, 35])

    def test_all_sys_headers_receive_identical_pwm(self):
        channels = [
            {"name": "CPU_FAN", "role": "cpu", "pwm": "pwm1", "fan_input": "fan1_input", "minimum_percent": 30},
            {"name": "SYS_A", "role": "sys", "pwm": "pwm3", "fan_input": "fan3_input", "minimum_percent": 35},
            {"name": "SYS_B", "role": "sys", "pwm": "pwm6", "fan_input": "fan6_input", "minimum_percent": 35},
        ]
        with tempfile.TemporaryDirectory() as directory:
            hwmon = Path(directory)
            for number, rpm in ((1, 700), (3, 800), (6, 900)):
                (hwmon / f"pwm{number}").write_text("63", encoding="ascii")
                (hwmon / f"pwm{number}_enable").write_text("2", encoding="ascii")
                (hwmon / f"fan{number}_input").write_text(str(rpm), encoding="ascii")
            controller = pc_fand.PwmController(hwmon, channels)
            controller.take_control()
            rows, warnings = controller.write_targets(30, 55)
            self.assertFalse(warnings)
            expected = pc_fand.math.ceil(55 * 255 / 100)
            self.assertEqual(int((hwmon / "pwm3").read_text()), expected)
            self.assertEqual(int((hwmon / "pwm6").read_text()), expected)
            self.assertEqual({row["pwm_raw"] for row in rows if row["role"] == "sys"}, {expected})
            controller.restore()

    def test_one_stalled_sys_tach_forces_entire_sys_group_to_full(self):
        channels = [
            {"name": "CPU_FAN", "role": "cpu", "pwm": "pwm1", "fan_input": "fan1_input", "minimum_percent": 30},
            {"name": "SYS_A", "role": "sys", "pwm": "pwm3", "fan_input": "fan3_input", "minimum_percent": 35},
            {"name": "SYS_B", "role": "sys", "pwm": "pwm6", "fan_input": "fan6_input", "minimum_percent": 35},
        ]
        with tempfile.TemporaryDirectory() as directory:
            hwmon = Path(directory)
            for number, rpm in ((1, 700), (3, 0), (6, 900)):
                (hwmon / f"pwm{number}").write_text("63", encoding="ascii")
                (hwmon / f"pwm{number}_enable").write_text("2", encoding="ascii")
                (hwmon / f"fan{number}_input").write_text(str(rpm), encoding="ascii")
            controller = pc_fand.PwmController(hwmon, channels)
            controller.take_control()
            rows, warnings = controller.write_targets(30, 35)
            self.assertTrue(any("SYS" in warning for warning in warnings))
            self.assertEqual({row["pwm_raw"] for row in rows if row["role"] == "sys"}, {255})
            controller.restore()


if __name__ == "__main__":
    unittest.main()
