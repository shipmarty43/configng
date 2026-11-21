# Zero 2W and Zero 3W chip-select and flow-control acceptance

2026-11-21. Tests composed the distribution DTBs and overlays in temporary boot directories. The scripts exercised the configurator APIs, the stock overlay writer and real Linux termios calls on pseudo-terminals. No device on a physical board was accessed.

| Armbian board and kernel | Base DTB SHA-256 |
|---|---|
| Zero 2W, 6.18.57-current-sunxi64 | `4b90c01af0137b2297fb7243f200c5b32c33ce7e9b0e3d15fbde8c9733363758` |
| Zero 3W, 6.6.98-vendor-sun60iw2 | `1eb1160f92dd1d566af920002583c67fbbb6eb35d190a62fb8f0bc1236bb74e1` |

- **SPI2 on A733.** With CS0+CS3, the native select count was 4 and the pin group contained PB0/1/2/3/6. With all four selects, the active and sleep groups both contained PB0–6. Three synthetic peripheral bindings at CS1–3 kept distinct limits and modes. The test rejected an over-limit request, removal of a bound CS, and conflicts with stock PWM0 on PB4, stock PWM8 on PB6 and a test PWM1 route on its documented PB5 alternate. SPI2 conflicts with I²C0 on PB2/PB3. The vendor pin-test IRQ on PB6 requires an explicit release before using CS3.
- **UART on A733.** UART2 RTS/CTS and I²C0 cannot both own PB2/PB3. UART6 RTS/CTS conflicts with I²C3 and with a PWM0 alternate on PE3. UART6 also needs PE0, reserved by the stock camera configuration. Tests switched each UART back to two wires, checked coexistence on freed pads and restored a saved four-wire selection.
- **UART on H618.** Exercised UART2 PI and PH, UART3 PI and UART4 PI. DFR0528 on I²C1 blocked the UART2 PI handshake. The alternate PH route rejected stock I²C4. PWM1/PWM2 PI conflicted with the UART3 handshake, PWM3 PI with UART4 TX. An RS-485-at-boot override on the four-wire port was refused.
- **Linux restore.** For all six four-wire routes, the test mirrored the actual composed controller and pin-group properties into temporary sysfs fixtures. The restore worker set `CRTSCTS` on a PTY and checked readback, both with and without saved framing. Runtime rollback restored the original framing and flag. Removing the flow pins from the live fixture prevented activation.
- **Persistence.** Conflicting writes preserved armbianEnv.txt byte-for-byte. SPI endpoint and UART route changes could be undone using the generated backup ID. The existing two-wire and SPI2 CS0-only overlay binaries were compared with the preceding release.

From the checkout, with dtc, fdtget and fdtoverlay available:

```sh
bash tests/hardware/check-uart-overlays.sh "$H618_DTB" "$H618_STOCK_OVERLAY_DIR"
bash tests/hardware/check-a733-io.sh "$A733_ALLWINNER_DIR"
```

Physical acceptance still requires observing each CS during transfers and measuring TX pause/resume against CTS with a four-wire peer. [H616/A733 audit and hardware references](pin-manual-audit.md) · [A733 BSP pinmux](https://github.com/orangepi-xunlong/linux-orangepi/blob/2ac08e8c7cdc28abbdc5c9a9dd812f887ae9c79f/bsp/drivers/pinctrl/pinctrl-sun60iw2.c)
