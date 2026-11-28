# Header bus diagnostics

Open **Hardware → Bus diagnostics** (`BUS001`) in the packaged configurator. The I²C page resolves the Linux bus number from its live OF controller and lists the clients already registered on that adapter. The system-bus PMIC and mux children are outside the selectable header-controller list. Listing clients performs no I²C address scan.

The `opi_i2c_recovery` bridge exposes two operations. Status reads the adapter's registered recovery capability. Recover rechecks its identity, takes the kernel root-adapter lock and invokes `i2c_recover_bus()`. A successful response is the adapter driver's result. A busy bus, an adapter timeout and an unsupported callback are reported independently. The kernel owns the line transitions. Manual GPIO manipulation is unnecessary. [Linux I²C driver API](https://docs.kernel.org/driver-api/i2c.html)

The matched board kit installs the helper for its kernel ABI. To rebuild a module for a prepared target kernel, run `make -C "$KDIR" ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- M="$PWD" modules` from this directory.

## UART direction control

BUS001 queries `TIOCGRS485` on an idle header tty. On Zero 2W, UART01 can reserve the four-pin mux for RS-485 direction without enabling CRTSCTS. The native RTS/DE contacts are UART2 PI pin 5 or PH pin 19, UART3 pin 32 and UART4 pin 31. After reboot, choose high-on-send or low-on-send in BUS001. Baud and framing remain under UART01. Enabling RS-485 checks the mux, exclusive tty ownership and CRTSCTS. The setting is live until another driver request or reboot. The tool compares readback to the original request and restores and verifies the preceding state if the driver filters the polarity. [Linux serial RS-485 API](https://docs.kernel.org/driver-api/serial/serial-rs485.html)

On the audited A733 BSP the header UARTs identify as `allwinner,uart-v100`. The driver's capability table disables hardware direction control for v100. Its separate GPIO-OE configuration uses vendor DT properties and its callback rejects a request with RS-485 disabled. BUS001 reports the live ioctl result; enabling a native RTS/DE profile is consequently confined to the qualified Zero 2W routes. The A733 RTS/CTS menus continue to manage serial flow control. [Pinned A733 UART source](https://github.com/orangepi-xunlong/linux-orangepi/blob/2ac08e8c7cdc28abbdc5c9a9dd812f887ae9c79f/bsp/drivers/uart/sunxi-uart-ng-core.c)
