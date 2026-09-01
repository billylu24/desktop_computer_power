# Fan commissioning procedure

This procedure is required once per physical fan/header topology.  Do not copy
another machine's `fans.conf`: splitter layout and minimum reliable PWM are
physical properties of the installed fans.

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

The physical CPU/front/rear/top roles cannot be derived safely from those
register numbers.  They must be observed at the case before commissioning can
continue.

## Required order

1. Confirm CPU/GPU are idle and at normal temperature.
2. Change only one known electrical PWM/tach pair at a time.
3. Have a person identify the physical fan(s) that accelerate.
4. Immediately restore that channel to its saved PWM and enable mode.
5. Record splitters: one header may power several physical case fans while only
   one tach signal is reported.
6. For every mapped channel, test 100, 80, 60, 50, 40, 35, 30, 25, and 20%.
   Wait for RPM stabilization at each point.  Never test under load.
7. Record conservative `minimum_start_pwm` and `minimum_stable_pwm` as raw
   1–255 values.  The first version must remain continuously spinning and must
   never write PWM 0.
8. Populate `/etc/pc-power/fans.conf`; keep `enabled=false` during dry-run.
9. Run at least five idle minutes plus short CPU-only and GPU-only loads with
   `pc-fand.py --dry-run`.  Confirm demand responds to the correct heat source.
10. Test the injected sensor-failure modes without damaging or unloading real
    sensors.
11. Perform a supervised active BALANCED PWM test.  Confirm every RPM remains
    nonzero and that exiting restores `pwmN_enable=2`.
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

Expected targets are respectively: case at least 50%; CPU 100% and case at
least 70%; all controlled fans 100%.
