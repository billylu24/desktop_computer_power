# Desktop computer power profiles

Runtime CPU and GPU power-profile switching for a tested Ubuntu system:

- AMD Ryzen 9 7900X (Zen 4 / Raphael)
- Gigabyte B650M AORUS ELITE AX
- NVIDIA GeForce RTX 5070 (175–250 W supported range)
- Ubuntu 26.04

The CPU control path uses the Raphael-capable [`amkillam/ryzen_smu`](https://github.com/amkillam/ryzen_smu) kernel module and the 7900X-specific [`julbouln` control script](https://gist.github.com/julbouln/a39bed663e37882c5a20521451e53814). CPU limits are volatile: a reboot returns control to the BIOS configuration. This repository intentionally does **not** install a service that applies a power profile at boot.

## Profiles

| Profile | CPU PPT / TDC / EDC | GPU limit |
| --- | --- | --- |
| `silent` | 88 W / 75 A / 150 A (65 W Eco) | 175 W |
| `balanced` | 142 W / 110 A / 170 A (105 W Eco) | 220 W |
| `stock` | 230 W / 160 A / 225 A (170 W TDP) | 250 W |

## Install

Review and run the installer on a supported Ubuntu machine:

```bash
git clone https://github.com/billylu24/desktop_computer_power.git
cd desktop_computer_power
sudo ./install.sh
sudo modprobe ryzen_smu
sudo pc-power status
```

The installer uses `amkillam/ryzen_smu` commit `d2983668300dd2a598e5a7dc40e71ce0678cc270`, checks that the source contains the Raphael (`0x61`) detection path, installs the module with DKMS, and installs the three scripts under `/usr/local`.

## Use

```bash
sudo pc-power silent
sudo pc-power balanced
sudo pc-power stock
sudo pc-power status
```

The lower-level CPU command is also available:

```bash
sudo cpu-power 65
sudo cpu-power 105
sudo cpu-power 170
sudo cpu-power status
```

After a reboot, load the module manually before using either command:

```bash
sudo modprobe ryzen_smu
```

## Validation performed

On the reference system, the module identified `family 0x19 / model 0x61` as `Raphael`; the PM table was readable. Runtime transitions `65 → 105 → 65` and `65 → 170 → 65` both read back their expected PPT/TDC/EDC values. A 60-second 24-thread `stress-ng` test at 105 W completed successfully, with sampled CPU power around 123 W and Tctl around 84°C. The 170 W mode was write/readback tested only; it was not stress tested.

## Safety

Only the validated Raphael PPT (`0x56`), TDC (`0x57`), and EDC (`0x58`) paths are invoked by the profile scripts. They do not change voltage, Curve Optimizer, PBO scalar, boost override, thermal limits, GPU voltage, or GPU clocks.

Stop testing if Raphael is not detected, PM-table data is implausible, or the kernel reports an MCE, hardware error, SMU timeout, command rejection, or PCI error.
