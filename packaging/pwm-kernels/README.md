# PWM002 kernel image packages

The upgrade replaces the board's standard Armbian `linux-image` package. The Debian version gains the suffix `+pwm002.1`. Keeping the release reported by `uname -r` lets Armbian use the existing device-tree package and boot hooks. The image, System.map, kernel config and loadable modules are rebuilt together. On Zero 3W the module inventory includes the out-of-tree PowerVR driver.

The rollback package contains the stock OCI payload and the installed Debian version from the clean board image. Armbian uses different version strings for the OCI artifact and the distribution package. Match the installed package's `Armbian-Original-Hash` when selecting the OCI artifact and compare its maintainer scripts with those in the clean image. The packaging tool verifies the payload against the clean image's dpkg MD5 manifest before building either package.

## Using a matched kit

Select the directory for the board and distribution kernel version. From that board directory, install the single file in `current/` with `sudo dpkg -i ./current/linux-image-*.deb` and reboot. Check the Debian version with `dpkg-query -W linux-image-current-sunxi64` on Zero 2W or `dpkg-query -W linux-image-vendor-sun60iw2` on Zero 3W. PWM002 checks the parameters parsed by the booted driver when starting a live operation.

To restore the original kernel, install the single file in `rollback/` with `sudo dpkg -i ./rollback/linux-image-*.deb` and reboot. PWM boot selections belong to the configurator. Use its saved-change rollback to restore a previous overlay selection as needed.

## Building

Use the kernel source revision, Armbian framework revision and board config from the target image. Apply the board's PWM patch after its Armbian patch set. Build with `ARCH=arm64`, an AArch64 cross toolchain and the stock release suffix. Build `Image modules` and install to a staging directory with `INSTALL_MOD_PATH` and `INSTALL_MOD_STRIP=1`. Run the distribution family's extra-module build hook when applicable. On Zero 3W this installs `extra/pvrsrvkm.ko`.

With a prepared kernel build and a complete module staging directory, run

```sh
python3 packaging/pwm-kernels/package.py "$OCI_IMAGE_DEB" "$INSTALLED_DEB_VERSION" \
    "$INSTALLED_MD5SUMS" "$KIT/rollback"
python3 packaging/pwm-kernels/package.py "$OCI_IMAGE_DEB" "$INSTALLED_DEB_VERSION" \
    "$INSTALLED_MD5SUMS" "$KIT/current" --build "$KBUILD_OUTPUT" --modroot "$MODULE_STAGE"
```

The builder requires the correct ARM64 Image magic, kernel release, built-in PWM symbol, module inventory and module dependency resolution. It keeps the selected board DTBs and the original Armbian maintainer scripts. Verify a distributed kit with `sha256sum -c SHA256SUMS` from its root.

## Testing installation and rollback

The runner requires a regular raw board image, an ARM64 static BusyBox, qemu-system-aarch64, qemu-img, cpio, e2fsprogs and dpkg-deb. It creates a fresh qcow2 layer and two small virtual disks in the new work directory. The VM has no networking or host directory export.

```sh
bash tests/packaging/pwm-kernels/check-image.sh orangepizero2w "$CLEAN_2W_IMG" \
    "$STOCK_2W_DEB" "$PWM_2W_DEB" "$ARM64_BUSYBOX" "$NEW_2W_WORKDIR"
bash tests/packaging/pwm-kernels/build-virt-ecam.sh "$VENDOR_6_6_98_SOURCE" \
    "$HOST_PREPARED_VENDOR_HEADERS" "$NEW_FIXTURE_DIR"
bash tests/packaging/pwm-kernels/check-image.sh orangepizero3w "$CLEAN_3W_IMG" \
    "$STOCK_3W_DEB" "$PWM_3W_DEB" "$ARM64_BUSYBOX" "$NEW_3W_WORKDIR" "$NEW_FIXTURE_DIR/qa-ecam.ko"
```

The Zero 3W board kernel omits QEMU virt's ECAM host. Its test initramfs loads that transport from the vendor PCI sources so the stock and patched kernels can access their virtual USB disks. It lives only in the runner's initramfs. Guest logs return on a separate ext4 disk, which also works with the vendor kernel's limited console drivers.

The guest runs the real dpkg and boot hooks on the board root filesystem. The runner boots the stock kernel, installs the upgrade, boots the exact Image copied from the upgraded guest, reinstalls the stock version, and boots the Image copied back after rollback. It loads and unloads the packaged pwm-fan module and checks the PWM symbol in the running kernel, package version, control sums for each module, selected boot Image, U-Boot ramdisk header and payload, board DTB and boot environment. QEMU supplies the early initramfs. Target boot ROM, U-Boot execution, physical PWM and fan behaviour require their respective boards.

## Acceptance on 28 November 2026

| Board | Clean image | Upgrade under dpkg | Restored version | Loadable modules |
|---|---|---|---|---:|
| Zero 2W | Armbian community Resolute XFCE, 6.18.57-current-sunxi64 | `26.11.0-trunk.108+pwm002.1` | `26.11.0-trunk.108` | 2680 |
| Zero 3W | Armbian Trixie Minimal, 6.6.98-vendor-sun60iw2 | `26.11.3+pwm002.1` | `26.11.3` | 465 |

Both boards completed three cold boots of their own kernels under QEMU. With systemd running on each board's original root filesystem, dpkg installed the upgrade and later downgraded to the original version. The second boot detected the patched driver's symbol, and the third boot restored the stock Image byte for byte. All module files matched their package manifest, `pwm-fan` loaded and unloaded on each boot, and the two source images kept their original SHA-256. The board DTB, boot script and environment passed the same checksum checks before and after each package change. The regenerated U-Boot ramdisk matched the initramfs and passed its header and data CRC checks. The local kit contains the guest logs for each phase. [Package, board and boot Image hashes](../../tests/hardware/evidence/pwm-kernels-2026-11-28.json)

The build used the configs from the images, GCC 14.3, binutils 2.46 and pahole 1.31 with BTF enabled. Temporary DWARF sections were compressed on disk. The Zero 2W build used the 6.18.57 stable kernel, the board distribution's kernel-code patches and its enabled extra drivers, including UWE5622. The Zero 3W build applied the distribution patch set to the pinned Orange Pi kernel and rebuilt the separate PowerVR module. Both packages retained the board DTBs supplied by their original Armbian artifacts. [Zero 2W framework revision](https://github.com/armbian/build/tree/fac57a02f1c6ff2221a3f3099a1094dcdf41be26) · [Zero 3W framework revision](https://github.com/armbian/build/tree/0bf4c8e96) · [A733 vendor kernel](https://github.com/orangepi-xunlong/linux-orangepi/tree/2ac08e8c7cdc28abbdc5c9a9dd812f887ae9c79f)

Both distribution DTBs also passed the PWM002 profile and rollback checks. The register double passed on the selected driver inputs. It checked complementary output shutdown, fan-channel preservation and A733 capture, error cleanup and counted bursts. QEMU executed the package-selected Image with a test initramfs. These runs cover packaging, boot selection and the Linux userspace lifecycle. Electrical timing and the board's U-Boot execution remain physical acceptance items.

## Matched header configurator kits

The full kit has a configurator and WiringPi C/Python package in `support/`,
the ABI-matched GPIO preset and I²C recovery modules, and the PWM kernel and
rollback in `current/` and `rollback/`. Zero 2W also includes its DFR0528 driver.
Build the configurator with `packaging/zero2w/build.py REVISION --core-only --output OUT --work WORK`.
Build the WiringPi package in the corresponding WiringPi fork. The Zero 3W Trixie
image requires a library built against an appropriate Debian sysroot.

```sh
python3 packaging/pwm-kernels/assemble-kit.py "$KERNEL_KIT" "$CORE_DEB" "$GPIO_DEB"     "$NEW_KIT" "$I2C_RECOVERY_KO" --wiringpi "$WIRINGPI_DEB"
```

For Zero 2W include the DFR0528 .ko as another positional module. The assembler
checks module names and vermagic, pairs the kernel with its original version,
and emits the checksum manifest. The complete kit installs with
`sudo ./apply.sh install`. Use PWM002 to undo the saved profile and
`sudo ./apply.sh rollback-kernel` to restore the original kernel. Support
packages stay installed. The installer checks board identity, the installed
kernel package version and the kit checksums.

Set `PWM_CONFIG_KIT` when running the image lifecycle test to exercise the
real packaged PWM002 menu under a PTY. `PWM_QA_I2C` adds the memory-backed
test adapter from `tests/packaging/header-kit/qa_i2c.c`. On Zero 3W,
`PWM_QA_GPIO` additionally supplies `qa_gpio.c` built as a module. They
belong on the test input disk only. The reboot check compares every boot
assignment and comment and the contents of the PWM overlays. Armbian may
reappend the usbstoragequirks assignment during boot. The test preserves that
distinction while checking the selected profile, the fan levels and rollback.
