# Zero 2W header PWM channels

Open `sudo armbian-config-zero2w --cmd PWM001`. Select a channel, choose its
header pin for the next boot, and save the frequency and **active** duty
percentage. The two pins on each row are alternatives for the same waveform.

| Channel | PI route / physical pin | PH route / physical pin | UART mux conflicts |
|---|---|---|---|
| PWM1 | PI11 / 32 | PH3 / 13 | UART3 RTS on PI11 (four-wire), UART5 RX on PH3 |
| PWM2 | PI12 / 33 | PH2 / 11 | UART3 CTS on PI12 (four-wire), UART5 TX on PH2 |
| PWM3 | PI13 / 7 | PH0 / 8 | UART4 TX on PI13, UART0 TX on PH0 |
| PWM4 | PI14 / 16 | PH1 / 10 | UART4 RX on PI14, UART0 RX on PH1 |

The pin numbers are physical header numbers. The Armbian H616 pinctrl driver
and the eight stock `sun50i-h616-pwmN-PIN.dtbo` files supply these mappings.
PWM0/PD28 and PWM5/PA12 are outside the 40-pin header. The stock Zero 2W
board uses PWM5 as the AC300 Ethernet clock. [Board manual](https://www.nikom.biz/pic_info/A704017/OrangePi_Zero2w_H618_User-Manual_v1.1.pdf) · [H616 pinctrl driver](https://github.com/torvalds/linux/blob/v6.18/drivers/pinctrl/sunxi/pinctrl-sun50i-h616.c)

```sh
sudo armbian-config-zero2w --api module_h616_pwm routes
sudo armbian-config-zero2w --api module_h616_pwm pwm2 route PI12
sudo armbian-config-zero2w --api module_h616_pwm pwm2 set 2000 37.5 inversed
sudo armbian-config-zero2w --api module_h616_pwm pwm2 status
# After booting the selected route and preparing the wiring:
sudo armbian-config-zero2w --api module_h616_pwm pwm2 start
sudo armbian-config-zero2w --api module_h616_pwm pwm2 stop
```

`route off` removes that channel's stock route. `default` clears its saved
waveform. `backups` and `boot-rollback change.ID` inspect and restore overlay
changes. The shared overlay manager checks the final composed board tree
for pinctrl and GPIO conflicts, also when the UART or stock overlay menu is
used later. A change of pin preserves the channel's profile. The files are
`/etc/armbian-config/pwm1.json` through `pwm4.json`. Existing PWM1 CLI
commands, file and service keep their original names. PWM2–4 have distinct
service instances, ownership records and kernel exports.

If the next-boot DT cannot be composed, the channel menu still provides live
status, stop and profile editing. Overlay writes continue to require a
validated boot route.

Saving a profile or booting its pin selection leaves output activation
explicit. Use `restart` to replace the waveform of a running channel.
For active-low duty the driver receives the complementary high interval,
as the stock driver selects normal polarity on enable. Frequency requests
span 1 Hz–1 MHz; kernel readback reports requested nanoseconds.

## Shared clock registers

H616 shares the PCCR source and first divider within each pair (0/1,
2/3, 4/5). The Armbian 6.18.57 vendor driver programs that register when
configuring either channel, even for independent PWM duty and period.
At 2 Hz–1 MHz this profile uses OSC24M and DIV_M=0. A 1 Hz request
requires DIV_M=1. The worker checks the enabled exported sibling and DT
PWM consumers while serializing its sysfs setup with the other configurator
workers. For instance PWM2 at 1 Hz cannot run alongside PWM3 at 10 kHz.
On the stock board PWM4 at 1 Hz is rejected to preserve the PWM5 clock;
PWM4 at 20 kHz uses the compatible pair setting. Independently programmed
external clients must also coordinate later changes to a shared pair.
[Allwinner H616 user manual, PWM clock tree](https://linux-sunxi.org/images/1/1d/H616_User_Manual_V1.0.pdf#page=779)

## Sharing pins with UART0

The stock UART0 is enabled. Normal route selection reports a conflict on
pins 8/10. For a deliberately repurposed header, switch the Linux console
using CTTY01 and release any GNSS receiver or getty first. `release-uart0`
adds an explicit user overlay for the next Linux boot. It checks kernel
console selection and current/reserved UART ownership. `restore-uart0`
removes it after the competing PWM routes have been removed. CTTY01 also
checks the pending release. U-Boot's early serial output remains a
bootloader setting. Pin 10 can be driven by the L76K TX on the Waveshare
shield: physically disconnect or isolate that external TX before using
pin 10 as a PWM output.
