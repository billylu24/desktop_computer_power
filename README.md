# Desktop computer power and fan profiles

Reproducible, runtime-only power and cooling controls for the tested desktop:

- AMD Ryzen 9 7900X (Zen 4 / Raphael)
- Gigabyte B650M AORUS ELITE AX with ITE IT8689E Super I/O
- NVIDIA GeForce RTX 5070 (175–250 W power-limit range)
- Ubuntu 26.04 with `amd-pstate-epp` and power-profiles-daemon

CPU power settings remain volatile: rebooting returns the processor to its BIOS
configuration.  No service in this project continuously enforces CPU, GPU, or
Linux power profiles.  The only intended daemon is the fan controller.

## Whole-PC profiles

| Profile | CPU PPT / TDC / EDC | GPU | Linux | Fan curve |
| --- | --- | --- | --- | --- |
| `silent` | 88 W / 75 A / 150 A (65 W Eco) | 175 W | power-saver | SILENT |
| `balanced` | 142 W / 110 A / 170 A (105 W Eco) | 220 W | balanced | BALANCED |
| `stock` | 230 W / 160 A / 225 A (170 W TDP) | 250 W | balanced | STOCK |
| `performance` | 230 W / 160 A / 225 A (170 W TDP) | 250 W | performance | PERFORMANCE |

After fan commissioning is complete:

```bash
sudo pc-power silent
sudo pc-power balanced
sudo pc-power stock
sudo pc-power performance
sudo pc-power status
```

Profile detection compares all four dimensions: CPU limits, GPU limit, Linux
profile, and active fan profile.  Any mismatch is reported as `CUSTOM`.

## Staged installation

Fan commissioning is intentionally staged.  Do not skip CPU/LOWER/UPPER mapping,
dry-run, active tests, and fault-injection tests.

1. Install CPU control, the GPU temperature reader, configuration templates,
   and userspace commands:

   ```bash
   sudo ./install.sh
   sudo modprobe ryzen_smu
   ```

   The installer leaves `/etc/pc-power/fans.conf` disabled and does not install
   or start `pc-fand.service`.  Consequently `pc-power` refuses profile changes
   rather than performing a partial CPU/GPU/Linux switch.

   On upgrades, the installer preserves an existing `fans.conf` and always
   refreshes `/etc/pc-power/fans.conf.example`.  An old configuration must be
   migrated to the `[cpu]`/`[lower]`/`[upper]` schema before service activation.

2. First try the Ubuntu kernel's in-tree `it87` module:

   ```bash
   sudo modprobe it87
   for h in /sys/class/hwmon/hwmon*; do
     [ "$(cat "$h/name" 2>/dev/null)" = it8689 ] && echo "$h"
   done
   ```

   Ubuntu 26.04 kernel `7.0.0-30-generic` on the reference machine provides a
   signed in-tree driver that detects IT8689E correctly.  Do not replace that
   working module with an external DKMS build.  Only if the running kernel does
   not provide a working IT8689E path, install the tested fallback:

   ```bash
   sudo ./install-it87.sh
   sudo modprobe it87
   ```

   This pins `frankcrawford/it87` commit
   `c567739c639533177abd66894a6a8d561337285f`.  No unsafe `force_id`,
   `ignore_resource_conflict`, or polarity option is used.

3. Follow [the fan bring-up procedure](docs/FAN-BRINGUP.md), then populate and
   explicitly enable `/etc/pc-power/fans.conf`.

4. Only after active PWM and failure tests pass, install/start the service:

   ```bash
   sudo ./enable-fan-service.sh
   sudo pc-power status
   ```

The service defaults to the BALANCED fan curve whenever the volatile
`/run/pc-power/fan-profile` file does not exist after boot.  It does not apply a
CPU/GPU/Linux profile at boot.

## Fan controller

`pc-fand.py` reads every second:

- CPU `Tctl` directly from the dynamically located `k10temp` hwmon device;
- GPU core, junction, and VRAM temperatures from the JSON output of the tested
  Blackwell MMIO `gputemps` reader.

The daemon keeps one persistent `gputemps --json --refresh-ms 1000` child
process and consumes its line-delimited output.  It does not fork one reader
per sample.  A missing line for 1.5 seconds, malformed JSON, or an exited child
activates the existing GPU sensor fail-safe for that sample; the reader is
restarted automatically on the next cycle.

Each sensor has its own linear-interpolation curve.  LOWER fan demand is the
maximum of the three normalized GPU cooling demands.  UPPER fan demand is the
maximum of CPU plus all GPU demands, so it exhausts heat from either source.
CPU fan demand is primarily the CPU curve plus the specified 35/45/60% GPU
airflow floors.  Global minimums are CPU 30%, LOWER 35%, and UPPER 35%.  A
five-sample median followed by a short EMA filters spikes; demand rises by up
to 10 percentage points per sample and falls by at most two.

Confirmed reference-machine mapping:

| Zone | PWM | Tach |
| --- | --- | --- |
| CPU cooler | `pwm1` | `fan1_input` |
| Lower case airflow | `pwm3` | `fan3_input` |
| Upper case airflow | `pwm6` | `fan6_input` |

The daemon requires two independent opt-ins before writing PWM:

- command-line `--write-pwm`;
- `[controller] enabled = true` in the mapped three-zone config.

Monitor-only use never writes PWM:

```bash
sudo /usr/local/libexec/pc-fand.py --dry-run --profile silent
```

Emergency raw-temperature triggers bypass filtering and request 100% cooling.
Missing GPU junction/VRAM data imposes 50% LOWER/UPPER floors; total GPU
temperature failure imposes 70%; missing CPU Tctl requests CPU 100% and both
airflow zones at least 70%; total temperature failure requests every
controlled fan at 100%.

## Validated CPU path

The CPU path pins Raphael-capable `amkillam/ryzen_smu` commit
`d2983668300dd2a598e5a7dc40e71ce0678cc270` and installs it through DKMS.  The
7900X-specific control script uses the verified Raphael commands PPT `0x56`,
TDC `0x57`, and EDC `0x58` only.

Runtime transitions `65 → 105 → 65` and `65 → 170 → 65` were previously
read-back verified.  A 60-second, 24-thread `stress-ng` test at the 105 W Eco
profile completed successfully.  The 170 W mode was write/read-back tested,
not burn tested.

## Safety boundaries

This project does not modify CPU voltage, Curve Optimizer, PBO scalar, boost
override, thermal protection, GPU clocks, GPU voltage, GPU fan control, or
VBIOS.  The daemon never writes PWM 0 and does not implement Fan Stop.  RTX board fans
remain under VBIOS control.  On controlled shutdown, the daemon restores each
header's saved firmware/automatic state; if restoration fails it attempts a
100% manual fallback.

Stop commissioning after an MCE, hardware error, SMU timeout, command
rejection, PCI error, implausible temperature, unexpected reset, fan stall, or
incorrect physical mapping.
