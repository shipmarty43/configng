# Zero 2W Python GPIO verification, 2026-11-20

The **Hardware → GPIO header → WiringPi header report** action in `GPIO01` inspects each of the 28 GPIO
contacts. It shows the physical position, SoC number and name, kernel
direction and consumer. It does not claim lines. An unclaimed GPIO can still
have a peripheral mux or an external driver connected to it.

The matching [WiringPi library, Python package and installation instructions](https://github.com/shipmarty43/WiringPi/tree/3994de57b25201da906372abb51d063afc9dc9ea/python)
provide the common pin map and the checked v1 ABI. Install the shared library
on the loader path and the wheel into a root-owned `/opt/wiringpi-zero2w`
virtual environment or system Python. Both the menu and
`module_zero2w_gpio status` report errors if the package, library, board or
gpiochip is unavailable. The optional [armbian-gui System Tools page](https://github.com/shipmarty43/armbian-gui/commit/b1730248e280249395d54f96248f19e6a0989d12)
uses the same pin map and reads fresh details when the user selects a pin.

## Offline acceptance record

| Environment | Result |
|---|---|
| x86-64 host | Checked all 40 header positions, rejected invalid arguments and received `ENODEV` outside a compatible board. Passed existing C regressions with ASan/UBSan and the checked initial-value/FD-zero tests. |
| ARM64 QEMU virt, Linux 6.18.57 with gpio-sim, 1 vCPU / 256 MiB | Nine kernel-line tests passed. Covered two processes competing for a line, cleanup after kill, inherited handles, both initial levels, input pulls, direction, event selection, debounce request, timestamps, queue overrun, timeout and cancellation, and missing PWM route. |
| Simulated loopback and acceptance harness | Ran the same 37→29 digital test with output-to-input coupling supplied by the fixture. Scripted edge timestamps covered the PWM measurement and failure thresholds. Hardware tests require one explicit wiring selection. |
| Host PWM device-tree/sysfs fixture | Called the checked C backend from Python. Verified period/duty, busy channel, pin-32 mux exclusion, fork isolation and a retried failed unexport. |
| Configurator | Both Bats cases passed. The assembled system module used the installed wheel via isolated Python in the ARM64 guest and the read-dialog backend returned 28 lines including physical 29, PI0, sunxi 256. |
| Application | Two System Tools tests exercised menu selection, refreshed ownership, a missing package and a failed kernel lookup. |

The QEMU guest used CPython 3.14, bash and the principal runtime libraries from
`Armbian_community_26.11.0-trunk.108_Orangepizero2w_resolute_current_6.18.57_xfce_desktop.img`.
It used a test kernel and QEMU virt device tree. Of 16 Python cases, 15
passed in the guest; the host-only wrong-board case passed separately on x86.
The [fixture and runner](https://github.com/shipmarty43/WiringPi/tree/3994de57b25201da906372abb51d063afc9dc9ea/python/tests)
use Linux GPIO v2 ioctls, shuffled gpio-sim offsets and real kernel event
queues. The PWM waveform still requires a physical controller.

## Board checklist

1. Open the ownership page with the regular user and the relevant gpiochip permissions.
   Compare its names with `gpio readall` on this board and identify the owners of attached peripherals.
2. With **physical 32→29 through 1 kΩ**, both contacts isolated from other
   devices and `pwm1-pi11` active, run the PWM scenario. Capture 10, 100 and
   1000 Hz at 25/50/75% duty, then confirm steady 0/100%. An external analyzer
   can independently measure period and pulse width.
3. Power down and change the resistor to **physical 37→29** for the digital
   scenario. Verify LOW and HIGH on acquisition and both edge directions,
   then re-open the page to confirm release. Use an analyzer to qualify
   sub-sample glitches if the attached device requires glitch-free reset.
4. For applications relying on internal pulls or debounce, qualify pull-up
   and pull-down on an isolated input and apply timed pulses of known duration.
   Record the actual kernel/overlay, pin, electrical setup, timestamps and result.

The [hardware test commands and tolerances](https://github.com/shipmarty43/WiringPi/blob/3994de57b25201da906372abb51d063afc9dc9ea/python/README.md#board-acceptance)
use physical header numbering. Existing C hardware measurements remain in
the [controls follow-up](zero2w-controls-2026-10-27.md). Legacy radio
drivers that import OPi.GPIO have their own pinmux, routing and integration
work tracked in the [ecosystem plan](zero2w-radio-ecosystem.md).
