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
