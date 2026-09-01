# Fan commissioning procedure

This procedure is required once per physical fan/header topology.  The final
controller has three outputs: CPU cooler, lower airflow, and upper airflow.

## Reference-system discovery record

Read-only discovery on the reference Gigabyte B650M AORUS ELITE AX found:

- Super I/O: ITE IT8689E, device ID `0x8689`;
- driver: `frankcrawford/it87` commit
  `c567739c639533177abd66894a6a8d561337285f`;
- binding log: `Found IT8689E chip at 0xa40 [MMIO at 0xfe000000], revision 2`;
- hwmon name: `it8689` (the numeric `hwmonN` path is intentionally not fixed);
- connected tach channels: fan1, fan3, and fan6;
- unused/no-tach channels at discovery: fan2, fan4, and fan5;
- all six headers were initially in firmware automatic mode (`pwmN_enable=2`).

Short, reversible 100% tests established the electrical pairs and restored
automatic mode after every test:

| PWM | Tach | Idle RPM | 12-second 100% RPM |
| --- | --- | ---: | ---: |
| pwm1 | fan1_input | 649 | 1569 |
| pwm3 | fan3_input | 832 | 1548 |
| pwm6 | fan6_input | 969 | 1516 |

Supervised visual tests subsequently confirmed:

| Zone | PWM | Tach |
| --- | --- | --- |
| CPU cooler | pwm1 | fan1_input |
| Lower case fans | pwm3 | fan3_input |
| Upper case fans | pwm6 | fan6_input |

## Required order

1. Confirm CPU/GPU are idle and at normal temperature.
2. Change only one known electrical PWM/tach pair at a time.
3. Have a person identify the physical fan(s) that accelerate.
4. Immediately restore that channel to its saved PWM and enable mode.
5. Record splitters: one header may power several physical case fans while only
   one tach signal is reported.
6. Classify each connected channel as `CPU_FAN`, `LOWER_FAN`, or `UPPER_FAN`.
7. Populate the comma-separated `pwm_paths`, `fan_inputs`, and optional `names`
   lists in `/etc/pc-power/fans.conf`; keep `enabled=false` during dry-run.
   The global floors are CPU 30%, LOWER 35%, and UPPER 35%.  Do not configure
   Fan Stop.
8. Run at least five idle minutes plus short CPU-only and GPU-only loads with
   `pc-fand.py --dry-run`.  Confirm demand responds to the correct heat source.
9. Test the injected sensor-failure modes without damaging or unloading real
    sensors.
10. Perform a supervised active BALANCED PWM test.  Confirm every RPM remains
    nonzero and that exiting restores `pwmN_enable=2`.
11. If a case zone cannot sustain 35%, raise that zone's global minimum for all
    fans attached to its header.
12. Only then set `enabled=true` and use `enable-fan-service.sh`.

## Failure injection examples (dry-run only)

```bash
sudo /usr/local/libexec/pc-fand.py --dry-run --once --profile balanced \
  --inject gpu_junction=null,gpu_vram=null

sudo /usr/local/libexec/pc-fand.py --dry-run --once --profile balanced \
  --inject cpu_tctl=null

sudo /usr/local/libexec/pc-fand.py --dry-run --once --profile balanced \
  --inject cpu_tctl=null,gpu_core=null,gpu_junction=null,gpu_vram=null
```

Expected targets are respectively: LOWER/UPPER at least 50%; CPU 100% and both
airflow zones at least 70%; all controlled fans 100%.
