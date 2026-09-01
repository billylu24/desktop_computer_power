#!/usr/bin/env python3
"""Safe multi-sensor three-zone fan controller for the reference desktop.

The program is monitor-only unless both --write-pwm is supplied and
[controller] enabled=true in fans.conf.  This double opt-in is deliberate.
"""

from __future__ import annotations

import argparse
import configparser
from collections import deque
import json
import logging
import math
import os
from pathlib import Path
import re
import signal
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any


DEFAULT_CONFIG = Path("/etc/pc-power/fans.conf")
DEFAULT_PROFILES = Path("/etc/pc-power/fan-profiles.json")
DEFAULT_PROFILE_FILE = Path("/run/pc-power/fan-profile")
DEFAULT_STATUS_FILE = Path("/run/pc-power/fan-status.json")
DEFAULT_GPUTEMPS = Path("/usr/local/libexec/gputemps")
VALID_PROFILES = ("silent", "balanced", "stock", "performance")
SENSORS = ("cpu_tctl", "gpu_core", "gpu_junction", "gpu_vram")


class ConfigurationError(RuntimeError):
    pass


class SensorFilters:
    def __init__(self, window: int, alpha: float) -> None:
        self.window = window
        self.alpha = alpha
        self.samples = {name: deque(maxlen=window) for name in SENSORS}
        self.ema: dict[str, float | None] = {name: None for name in SENSORS}

    def update(self, values: dict[str, float | None]) -> dict[str, float | None]:
        result: dict[str, float | None] = {}
        for name in SENSORS:
            value = values.get(name)
            if value is None:
                result[name] = None
                continue
            self.samples[name].append(value)
            median = float(statistics.median(self.samples[name]))
            previous = self.ema[name]
            filtered = median if previous is None else self.alpha * median + (1 - self.alpha) * previous
            self.ema[name] = filtered
            result[name] = filtered
        return result


def atomic_write(path: Path, text: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def write_text(path: Path, value: int) -> None:
    path.write_text(str(value), encoding="ascii")


def find_hwmon(name: str) -> Path | None:
    for path in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
        try:
            if read_text(path / "name") == name:
                return path
        except OSError:
            continue
    return None


def find_cpu_tctl() -> tuple[float | None, str | None]:
    hwmon = find_hwmon("k10temp")
    if hwmon is None:
        return None, None
    for label_path in hwmon.glob("temp*_label"):
        try:
            if read_text(label_path) != "Tctl":
                continue
            input_path = label_path.with_name(label_path.name.replace("_label", "_input"))
            value = float(read_text(input_path)) / 1000.0
            if not 0 <= value <= 125:
                raise ValueError(f"implausible Tctl {value}")
            return value, str(input_path)
        except (OSError, ValueError):
            continue
    return None, None


def read_gpu_temps(command: Path) -> tuple[dict[str, float | None], str | None]:
    values = {"gpu_core": None, "gpu_junction": None, "gpu_vram": None}
    try:
        completed = subprocess.run(
            [str(command), "--json", "--once"],
            check=True,
            capture_output=True,
            text=True,
            timeout=1.5,
        )
        payload = json.loads(completed.stdout)
        gpu = payload["gpus"][0]
        for output_name, input_name in (
            ("gpu_core", "core"),
            ("gpu_junction", "junction"),
            ("gpu_vram", "vram"),
        ):
            raw = gpu.get(input_name)
            if raw is None:
                continue
            value = float(raw)
            if 0 <= value <= 130:
                values[output_name] = value
        return values, None
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError, json.JSONDecodeError) as exc:
        return values, str(exc)


def interpolate(points: list[list[float]], temperature: float) -> float:
    if temperature <= points[0][0]:
        return float(points[0][1])
    for left, right in zip(points, points[1:]):
        if temperature <= right[0]:
            fraction = (temperature - left[0]) / (right[0] - left[0])
            return float(left[1] + fraction * (right[1] - left[1]))
    return float(points[-1][1])


def validate_profiles(data: dict[str, Any]) -> None:
    if data.get("schema_version") != 1:
        raise ConfigurationError("unsupported fan profile schema")
    for profile_name in VALID_PROFILES:
        profile = data.get("profiles", {}).get(profile_name)
        if not isinstance(profile, dict):
            raise ConfigurationError(f"missing profile {profile_name}")
        for sensor in SENSORS:
            points = profile.get(sensor)
            if not isinstance(points, list) or len(points) < 2:
                raise ConfigurationError(f"{profile_name}.{sensor} needs at least two points")
            previous_temp = -math.inf
            for point in points:
                if not isinstance(point, list) or len(point) != 2:
                    raise ConfigurationError(f"invalid point in {profile_name}.{sensor}")
                temp, demand = point
                if temp <= previous_temp or not 0 <= demand <= 100:
                    raise ConfigurationError(f"invalid curve in {profile_name}.{sensor}")
                previous_temp = temp


def _csv_values(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_fans(path: Path, allow_unmapped: bool) -> tuple[configparser.ConfigParser, list[dict[str, Any]]]:
    parser = configparser.ConfigParser()
    if not parser.read(path):
        raise ConfigurationError(f"cannot read {path}")
    enabled = parser.getboolean("controller", "enabled", fallback=False)
    floors = {
        "cpu": parser.getint("controller", "cpu_fan_min_percent", fallback=30),
        "lower": parser.getint("controller", "lower_fan_min_percent", fallback=35),
        "upper": parser.getint("controller", "upper_fan_min_percent", fallback=35),
    }
    for role, floor in floors.items():
        if not 1 <= floor <= 100:
            raise ConfigurationError(f"invalid {role} fan minimum percentage: {floor}")

    channels: list[dict[str, Any]] = []
    incomplete_sections: list[str] = []
    for section, role in (("cpu", "cpu"), ("lower", "lower"), ("upper", "upper")):
        if not parser.has_section(section):
            incomplete_sections.append(section)
            continue
        pwms = _csv_values(parser.get(section, "pwm_paths", fallback=""))
        fan_inputs = _csv_values(parser.get(section, "fan_inputs", fallback=""))
        names = _csv_values(parser.get(section, "names", fallback=""))
        mapped = (
            bool(pwms)
            and len(pwms) == len(fan_inputs)
            and all(re.fullmatch(r"pwm\d+", pwm) for pwm in pwms)
            and all(re.fullmatch(r"fan\d+_input", fan) for fan in fan_inputs)
        )
        if not mapped:
            incomplete_sections.append(section)
            continue
        if names and len(names) != len(pwms):
            raise ConfigurationError(f"{section}.names must match the number of PWM paths")
        if not names:
            label = f"{role.upper()}_FAN"
            names = [label if len(pwms) == 1 else f"{label}_{index}" for index in range(1, len(pwms) + 1)]
        for name, pwm, fan_input in zip(names, pwms, fan_inputs):
            channels.append(
                {
                    "section": section,
                    "role": role,
                    "name": name,
                    "pwm": pwm,
                    "fan_input": fan_input,
                    "minimum_percent": floors[role],
                }
            )
    if enabled and incomplete_sections:
        raise ConfigurationError(f"enabled controller has unmapped groups: {', '.join(incomplete_sections)}")
    if enabled and not any(channel["role"] == "cpu" for channel in channels):
        raise ConfigurationError("enabled controller has no mapped CPU fan")
    if enabled and not any(channel["role"] == "lower" for channel in channels):
        raise ConfigurationError("enabled controller has no mapped LOWER fan")
    if enabled and not any(channel["role"] == "upper" for channel in channels):
        raise ConfigurationError("enabled controller has no mapped UPPER fan")
    pwms = [channel["pwm"] for channel in channels]
    fan_inputs = [channel["fan_input"] for channel in channels]
    if len(pwms) != len(set(pwms)) or len(fan_inputs) != len(set(fan_inputs)):
        raise ConfigurationError("duplicate PWM or tach mapping")
    return parser, channels


def parse_injections(spec: str | None) -> dict[str, float | None]:
    injected: dict[str, float | None] = {}
    if not spec:
        return injected
    for item in spec.split(","):
        name, separator, raw = item.partition("=")
        if not separator or name not in SENSORS:
            raise ConfigurationError(f"invalid injected sensor: {item}")
        injected[name] = None if raw.lower() == "null" else float(raw)
    return injected


def read_requested_profile(explicit: str | None, profile_file: Path) -> str:
    if explicit:
        return explicit
    try:
        profile = read_text(profile_file).lower()
    except OSError:
        profile = "balanced"
    if profile not in VALID_PROFILES:
        logging.error("invalid runtime fan profile %r; using balanced", profile)
        profile = "balanced"
    return profile


def demands_for(
    raw: dict[str, float | None],
    filtered: dict[str, float | None],
    profile: dict[str, list[list[float]]],
    emergency: dict[str, float],
    emergency_until: float,
    now: float,
) -> tuple[float, float, float, float, dict[str, float | None], list[str]]:
    warnings: list[str] = []
    sensor_demands: dict[str, float | None] = {}
    for sensor in SENSORS:
        value = filtered.get(sensor)
        sensor_demands[sensor] = None if value is None else interpolate(profile[sensor], value)

    emergency_now = any(
        raw.get(sensor) is not None and float(raw[sensor]) >= float(emergency[threshold])
        for sensor, threshold in (
            ("cpu_tctl", "cpu_tctl_c"),
            ("gpu_core", "gpu_core_c"),
            ("gpu_junction", "gpu_junction_c"),
            ("gpu_vram", "gpu_vram_c"),
        )
    )
    if emergency_now or now < emergency_until:
        return 100.0, 100.0, 100.0, now + float(emergency["release_seconds"]) if emergency_now else emergency_until, sensor_demands, warnings

    cpu = sensor_demands["cpu_tctl"]
    gpu_core = sensor_demands["gpu_core"]
    gpu_junction = sensor_demands["gpu_junction"]
    gpu_vram = sensor_demands["gpu_vram"]

    gpu_airflow_floor = 0.0
    if (gpu_junction is not None and filtered["gpu_junction"] >= 90) or (gpu_vram is not None and filtered["gpu_vram"] >= 86):
        gpu_airflow_floor = 60.0
    elif (gpu_junction is not None and filtered["gpu_junction"] >= 85) or (gpu_vram is not None and filtered["gpu_vram"] >= 80):
        gpu_airflow_floor = 45.0
    elif (gpu_junction is not None and filtered["gpu_junction"] >= 75) or (gpu_vram is not None and filtered["gpu_vram"] >= 72):
        gpu_airflow_floor = 35.0
    cpu_demand = max(cpu or 0, gpu_airflow_floor)
    gpu_available = [value for value in (gpu_core, gpu_junction, gpu_vram) if value is not None]
    lower_demand = max(gpu_available, default=0)
    upper_demand = max([value for value in (cpu, *gpu_available) if value is not None], default=0)

    if gpu_junction is None or gpu_vram is None:
        lower_demand = max(lower_demand, 50)
        upper_demand = max(upper_demand, 50)
        warnings.append("GPU junction/VRAM unavailable: LOWER/UPPER fan floor 50%")
    if gpu_core is None and gpu_junction is None and gpu_vram is None:
        lower_demand = max(lower_demand, 70)
        upper_demand = max(upper_demand, 70)
        warnings.append("all GPU temperatures unavailable: LOWER/UPPER fan floor 70%")
    if cpu is None:
        cpu_demand = 100
        lower_demand = max(lower_demand, 70)
        upper_demand = max(upper_demand, 70)
        warnings.append("CPU Tctl unavailable: CPU fan 100%, LOWER/UPPER fan floor 70%")
    if cpu is None and gpu_core is None and gpu_junction is None and gpu_vram is None:
        cpu_demand = lower_demand = upper_demand = 100
        warnings.append("all temperatures unavailable: all fans 100%")
    return cpu_demand, lower_demand, upper_demand, emergency_until, sensor_demands, warnings


def apply_group_floors(
    cpu_demand: float,
    lower_demand: float,
    upper_demand: float,
    cpu_floor: float,
    lower_floor: float,
    upper_floor: float,
) -> tuple[float, float, float]:
    return (
        max(cpu_demand, cpu_floor),
        max(lower_demand, lower_floor),
        max(upper_demand, upper_floor),
    )


def slew(previous: float | None, target: float, rise: float, fall: float) -> float:
    if previous is None:
        return target
    if target > previous:
        return min(target, previous + rise)
    return max(target, previous - fall)


class PwmController:
    def __init__(self, hwmon: Path, channels: list[dict[str, Any]]) -> None:
        self.hwmon = hwmon
        self.channels = channels
        self.original: dict[str, tuple[int, int]] = {}
        self.active = False

    def take_control(self) -> None:
        for channel in self.channels:
            pwm = channel["pwm"]
            pwm_path = self.hwmon / pwm
            enable_path = self.hwmon / f"{pwm}_enable"
            fan_path = self.hwmon / channel["fan_input"]
            for required in (pwm_path, enable_path, fan_path):
                if not required.exists():
                    raise ConfigurationError(f"missing fan interface: {required}")
            self.original[pwm] = (int(read_text(pwm_path)), int(read_text(enable_path)))
        self.active = True
        try:
            for channel in self.channels:
                write_text(self.hwmon / f"{channel['pwm']}_enable", 1)
        except Exception:
            self.restore()
            raise

    def write_targets(self, cpu_percent: float, lower_percent: float, upper_percent: float) -> tuple[list[dict[str, Any]], list[str]]:
        output: list[dict[str, Any]] = []
        warnings: list[str] = []
        group_percent = {"cpu": cpu_percent, "lower": lower_percent, "upper": upper_percent}
        rpms: dict[str, int] = {}
        for channel in self.channels:
            rpms[channel["pwm"]] = int(read_text(self.hwmon / channel["fan_input"]))
        for role in ("cpu", "lower", "upper"):
            if any(channel["role"] == role and rpms[channel["pwm"]] <= 0 for channel in self.channels):
                group_percent[role] = 100.0
                warnings.append(f"{role.upper()} fan tachometer reported 0 RPM: entire group forced to 100%")
        for channel in self.channels:
            demand = max(group_percent[channel["role"]], float(channel["minimum_percent"]))
            # Round upward so the quantized 0-255 value never falls below a
            # configured percentage floor (30% -> 77, 35% -> 90).
            target = min(255, math.ceil(demand * 255 / 100))
            write_text(self.hwmon / channel["pwm"], target)
            actual = int(read_text(self.hwmon / channel["pwm"]))
            if actual != target:
                raise RuntimeError(f"{channel['name']} PWM readback wanted {target}, got {actual}")
            output.append({"name": channel["name"], "role": channel["role"], "pwm_raw": actual, "pwm_percent": round(actual * 100 / 255, 1), "rpm": rpms[channel["pwm"]]})
        return output, warnings

    def status_only(self) -> list[dict[str, Any]]:
        output = []
        for channel in self.channels:
            actual = int(read_text(self.hwmon / channel["pwm"]))
            rpm = int(read_text(self.hwmon / channel["fan_input"]))
            output.append({"name": channel["name"], "role": channel["role"], "pwm_raw": actual, "pwm_percent": round(actual * 100 / 255, 1), "rpm": rpm})
        return output

    def restore(self) -> None:
        if not self.active:
            return
        failures = []
        for channel in self.channels:
            pwm = channel["pwm"]
            old_pwm, old_enable = self.original[pwm]
            try:
                write_text(self.hwmon / pwm, old_pwm)
                write_text(self.hwmon / f"{pwm}_enable", old_enable)
            except OSError as exc:
                failures.append(f"{channel['name']}: {exc}")
                try:
                    write_text(self.hwmon / f"{pwm}_enable", 1)
                    write_text(self.hwmon / pwm, 255)
                except OSError:
                    pass
        self.active = False
        if failures:
            logging.critical("automatic-mode restore failed; attempted 100%% fallback: %s", "; ".join(failures))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=VALID_PROFILES)
    parser.add_argument("--dry-run", action="store_true", help="monitor and compute only; never write PWM")
    parser.add_argument("--write-pwm", action="store_true", help="allow PWM writes when fans.conf also enables them")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--samples", type=int, help="exit after this many samples")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--profile-file", type=Path, default=DEFAULT_PROFILE_FILE)
    parser.add_argument("--status-file", type=Path, default=DEFAULT_STATUS_FILE)
    parser.add_argument("--gputemps", type=Path, default=DEFAULT_GPUTEMPS)
    parser.add_argument("--inject", help="test only, e.g. cpu_tctl=null,gpu_core=70")
    parser.add_argument("--no-status-file", action="store_true")
    args = parser.parse_args()
    if args.dry_run and args.write_pwm:
        parser.error("--dry-run and --write-pwm are mutually exclusive")
    if not args.dry_run and not args.write_pwm:
        parser.error("choose --dry-run or --write-pwm explicitly")
    if args.samples is not None and args.samples < 1:
        parser.error("--samples must be positive")

    logging.basicConfig(level=logging.INFO, format="pc-fand: %(levelname)s: %(message)s")
    profiles_data = json.loads(args.profiles.read_text(encoding="utf-8"))
    validate_profiles(profiles_data)
    fan_config, channels = parse_fans(args.config, allow_unmapped=args.dry_run)
    hardware_enabled = fan_config.getboolean("controller", "enabled", fallback=False)
    cpu_floor = fan_config.getint("controller", "cpu_fan_min_percent", fallback=30)
    lower_floor = fan_config.getint("controller", "lower_fan_min_percent", fallback=35)
    upper_floor = fan_config.getint("controller", "upper_fan_min_percent", fallback=35)
    if args.write_pwm and not hardware_enabled:
        raise ConfigurationError("PWM writes refused: [controller] enabled is not true")
    injections = parse_injections(args.inject)
    filters = SensorFilters(
        int(profiles_data["filter"]["median_samples"]),
        float(profiles_data["filter"]["ema_alpha"]),
    )
    hwmon_name = fan_config.get("controller", "hwmon_name", fallback="it8689")
    fan_hwmon = find_hwmon(hwmon_name)
    if args.write_pwm and fan_hwmon is None:
        raise ConfigurationError(f"hwmon controller {hwmon_name!r} not found")
    controller = PwmController(fan_hwmon, channels) if fan_hwmon else None
    if args.write_pwm:
        assert controller is not None
        controller.take_control()

    stop = False
    def request_stop(_signum: int, _frame: Any) -> None:
        nonlocal stop
        stop = True
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    previous_cpu: float | None = None
    previous_lower: float | None = None
    previous_upper: float | None = None
    emergency_until = 0.0
    count = 0
    try:
        while not stop:
            started = time.monotonic()
            cpu, cpu_path = find_cpu_tctl()
            gpu, gpu_error = read_gpu_temps(args.gputemps)
            raw = {"cpu_tctl": cpu, **gpu}
            raw.update(injections)
            filtered = filters.update(raw)
            profile_name = read_requested_profile(args.profile, args.profile_file)
            cpu_target, lower_target, upper_target, emergency_until, sensor_demands, warnings = demands_for(
                raw,
                filtered,
                profiles_data["profiles"][profile_name],
                profiles_data["emergency"],
                emergency_until,
                started,
            )
            cpu_target, lower_target, upper_target = apply_group_floors(
                cpu_target,
                lower_target,
                upper_target,
                cpu_floor,
                lower_floor,
                upper_floor,
            )
            cpu_applied = slew(previous_cpu, cpu_target, float(profiles_data["filter"]["rise_percent_per_sample"]), float(profiles_data["filter"]["fall_percent_per_sample"]))
            lower_applied = slew(previous_lower, lower_target, float(profiles_data["filter"]["rise_percent_per_sample"]), float(profiles_data["filter"]["fall_percent_per_sample"]))
            upper_applied = slew(previous_upper, upper_target, float(profiles_data["filter"]["rise_percent_per_sample"]), float(profiles_data["filter"]["fall_percent_per_sample"]))
            previous_cpu, previous_lower, previous_upper = cpu_applied, lower_applied, upper_applied

            fan_rows: list[dict[str, Any]] = []
            if args.write_pwm:
                assert controller is not None
                fan_rows, fan_warnings = controller.write_targets(cpu_applied, lower_applied, upper_applied)
                warnings.extend(fan_warnings)
            elif controller and channels:
                fan_rows = controller.status_only()

            status = {
                "timestamp": int(time.time()),
                "mode": "write-pwm" if args.write_pwm else "dry-run",
                "profile": profile_name,
                "sensors_c": raw,
                "filtered_sensors_c": {key: None if value is None else round(value, 2) for key, value in filtered.items()},
                "sensor_demands_percent": {key: None if value is None else round(value, 1) for key, value in sensor_demands.items()},
                "cpu_fan_target_percent": round(cpu_applied, 1),
                "lower_fan_target_percent": round(lower_applied, 1),
                "upper_fan_target_percent": round(upper_applied, 1),
                "emergency_hold": started < emergency_until,
                "warnings": warnings + ([f"gputemps: {gpu_error}"] if gpu_error else []),
                "cpu_tctl_path": cpu_path,
                "fan_hwmon": str(fan_hwmon) if fan_hwmon else None,
                "fans": fan_rows,
            }
            if not args.no_status_file:
                atomic_write(args.status_file, json.dumps(status, indent=2, sort_keys=True) + "\n")
            print(json.dumps(status, sort_keys=True), flush=True)
            for warning in status["warnings"]:
                logging.warning(warning)
            count += 1
            if args.once or (args.samples is not None and count >= args.samples):
                break
            remaining = float(profiles_data["sample_interval_seconds"]) - (time.monotonic() - started)
            if remaining > 0:
                time.sleep(remaining)
    finally:
        if controller:
            controller.restore()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ConfigurationError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"pc-fand: fatal: {exc}", file=sys.stderr)
        raise SystemExit(1)
