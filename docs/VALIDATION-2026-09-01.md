# Fan-control validation record — 2026-09-01

This is an interim record.  Active PWM control and systemd were deliberately
not enabled because the physical CPU/SYS fan roles have not yet been
supplied/confirmed.  The final design no longer performs per-fan minimum-PWM
calibration; it uses global CPU 30% and SYS 35% floors.

## Driver and electrical channel checks

- IT8689E detected without `force_id`, `ignore_resource_conflict`, or polarity
  overrides.
- Driver source: `frankcrawford/it87` at
  `c567739c639533177abd66894a6a8d561337285f`.
- Electrical pairs confirmed by supervised, 12-second manual 100% tests:
  `pwm1/fan1_input`, `pwm3/fan3_input`, and `pwm6/fan6_input`.
- Every test restored all six `pwmN_enable` attributes to firmware automatic
  mode (`2`).
- A supervised identification test showed that raw PWM 0 still leaves the
  installed fans at their hardware minimum RPM.  Fan Stop is not used.

## Real-sensor dry-run

Five-minute SILENT idle observation, 150 samples at two seconds:

| Measurement | Result |
| --- | --- |
| CPU Tctl | 45.4–45.8°C, average 45.5°C |
| GPU Core | 31–33°C, average 32.2°C |
| GPU Junction | 34–36°C, average 34.7°C |
| GPU VRAM | 40–42°C, average 41.0°C |
| CPU fan target | 25.2–25.4%, average 25.3% |
| Case demand | 25.2–25.4%, average 25.3% |
| Warnings / emergency triggers | 0 / 0 |

Thirty-second, 24-thread CPU-only load under BALANCED dry-run:

- CPU Tctl: 45.4 → 61.6°C;
- GPU temperatures unchanged;
- CPU and case demand: 30.4 → 46.2%;
- final cooldown demand: 33.4%;
- `stress-ng`: 24/24 workers passed, no warnings from `pc-fand`.

Sustained local Ollama/CUDA GPU-only load under BALANCED dry-run:

- GPU Core max: 59°C;
- GPU Junction max: 67°C;
- GPU VRAM max: 66°C;
- CPU Tctl max: 53.1°C;
- CPU fan target max: 37.8%;
- Case demand max: 39.8%;
- the maximum case demand was GPU Core-led, while the CPU fan retained the
  smaller, limited GPU contribution;
- no sensor warnings or emergency triggers.

The first attempted `stress-ng --gpu` run was skipped because NVIDIA GBM could
not create a surface.  It is not counted as a successful load test.

## Injected failures (dry-run)

| Injection | Verified fallback |
| --- | --- |
| Junction + VRAM null | Case demand at least 50% |
| All GPU temperatures null | Case demand at least 70% |
| CPU Tctl null | CPU 100%, case at least 70% |
| CPU + all GPU null | CPU and case 100% |
| Instant Junction 94°C | Immediate CPU and case 100%, emergency hold active |

This table records the earlier pre-two-zone curves.  After the two-zone design
update, algorithm unit tests are tracked by the current test suite rather than
this historical sample count.  An unmapped configuration was also
confirmed to reject `--write-pwm` with a nonzero exit code.

## End state

- CPU: 88 W PPT / 75 A TDC / 150 A EDC;
- GPU power limit: 175 W;
- Linux profile: power-saver, EPP `power`;
- all `pwmN_enable`: 2 (firmware automatic);
- `pc-fand.service`: not installed/enabled;
- active fan takeover: not performed.

Kernel review found no new MCE, hardware error, SMU timeout, or PCI error.  The
two `it87 Unknown symbol` messages in the log predate successful module loading
and came from the initial attempt before loading the `hwmon-vid` dependency.

## Two-zone controller update

The final controller schema has only CPU and SYS groups.  Its current automated
suite passes 15 tests, including identical PWM writes to multiple SYS headers,
whole-group 100% fallback on a zero-RPM tachometer, global 30/35% floors,
35/45/60% GPU airflow floors for the CPU group, sensor failures, emergency
hold, interpolation, filtering slew, and configuration rejection.

A root monitor-only SILENT sample read all four real sensors without warnings:
CPU 47°C, GPU Core 35°C, Junction 38°C, and VRAM 44°C.  It computed CPU 30.4%
and SYS 35.0%.  No PWM was written and the active service remains disabled
until physical CPU/SYS classification is confirmed.
