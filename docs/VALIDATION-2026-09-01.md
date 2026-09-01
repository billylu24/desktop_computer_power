# Fan-control validation record — 2026-09-01

This is an interim record.  Active PWM control and systemd were deliberately
not enabled because physical CPU/case fan roles and minimum reliable PWM have
not yet been supplied/confirmed.

## Driver and electrical channel checks

- IT8689E detected without `force_id`, `ignore_resource_conflict`, or polarity
  overrides.
- Driver source: `frankcrawford/it87` at
  `c567739c639533177abd66894a6a8d561337285f`.
- Electrical pairs confirmed by supervised, 12-second manual 100% tests:
  `pwm1/fan1_input`, `pwm3/fan3_input`, and `pwm6/fan6_input`.
- Every test restored all six `pwmN_enable` attributes to firmware automatic
  mode (`2`).
- No active-PWM calibration or Fan Stop test was performed.

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

Algorithm unit tests: 8/8 passed.  An uncalibrated configuration was also
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
