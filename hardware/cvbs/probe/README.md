# Zero 2W CVBS diagnostic boot

This ARM64 kernel boots a small userspace in RAM. It provides a serial shell,
the sun4i DRM driver and colour bars for the composite jack. The test profile
dedicates TCON-TV0 to CVBS. Serial access is required for the physical test.
The one-time U-Boot commands below leave the normal boot configuration on the card.

## Build on a disk-backed filesystem

Use an Armbian-patched Linux 6.18.57 source tree with the combined CVBS patch
applied as described in the [driver build instructions](../README.md#reproduce-the-offline-checks).
The tested source uses the 546 enabled entries of the Armbian sunxi-6.18 series
at `e4de830005f0d616fed576a9c046f3a8aeb24ef8`. We applied their kernel code,
omitting the DTS, documentation and MAINTAINERS hunks. The board DTB comes from
the archived Armbian image. Keep the source, object directory and temporary
directory on disk. The example limits make to two jobs and each process to
768 MiB of virtual memory. It requires an AArch64 GNU cross toolchain, bison,
flex, make, prlimit, and the device-tree tools listed in the driver instructions.

Run in the configng checkout. Set `KERNEL`, `STOCK_DTB` and `WORK` to absolute
paths. Use a new `WORK` directory and allow several GiB there.

```sh
probe=$PWD/hardware/cvbs/probe
mkdir -p "$WORK/obj" "$WORK/tmp" "$WORK/probe"
export TMPDIR="$WORK/tmp" ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- LOCALVERSION=
KCONFIG_ALLCONFIG="$probe/zero2w.config" prlimit --as=805306368 -- \
    make -j2 -C "$KERNEL" O="$WORK/obj" allnoconfig
prlimit --as=805306368 -- make -j2 -C "$KERNEL" O="$WORK/obj" Image
cp "$WORK/obj/arch/arm64/boot/Image" "$WORK/probe/Image"
cp "$WORK/obj/.config" "$WORK/probe/kernel.config"
python3 hardware/cvbs/tests/check-dtb.py "$STOCK_DTB" "$KERNEL" --output "$WORK/dt"
cp "$WORK/dt/zero2w-cvbs.dtb" "$WORK/probe/"
```

Set `BUSYBOX` to the static ARM64 BusyBox binary, `MODETEST` to ARM64 modetest,
and `LIBDIR` to the directory with the matching ARM64 libc, loader and libdrm.
Ubuntu arm64 BusyBox 1.37.0, libdrm 2.4.131 and glibc 2.43 were used here.
The kernel host tool emits the console device node without root privileges.

```sh
"$probe/build-initramfs.sh" "$WORK/obj/usr/gen_init_cpio" "$BUSYBOX" "$MODETEST" \
    "$LIBDIR" "$WORK/probe/initramfs.cpio.gz" "$WORK/tmp"
"$probe/smoke-qemu.sh" "$WORK/probe/Image" "$WORK/probe/initramfs.cpio.gz"
```

QEMU boots its own `virt` DT with one cortex-a53 CPU and 256 MiB. The guest
discovers the virtual connector and primary plane, shows a 640×480 XR24
framebuffer, reads the active scanout state via DRM debugfs, then releases the
display and checks that the CRTC is inactive. The host script requires the
guest's pass marker. The stock-board DT and H618 register paths have separate
[offline tests](../README.md#de33-colour-and-boot-test-2026-11-20).

## One-time boot on the Orange Pi Zero 2W

The diagnostic kit contains `Image`, `initramfs.cpio.gz`, `zero2w-cvbs.dtb`,
the resolved `kernel.config` and `SHA256SUMS`. Verify the files with
`sha256sum -c SHA256SUMS` in the extracted directory. Place the three boot
files together in a separate directory on media readable by U-Boot. The DTB
already includes the overlay.

Interrupt U-Boot on the board's serial console. Identify the readable
partition and directory with `mmc list`, `part list mmc 0` and `ls mmc 0:1 /`,
adjusting the device number for your card. The following example assumes the
files are under `/boot/cvbs-probe` on MMC 0, partition 1. Verify the three
load addresses with `printenv kernel_addr_r fdt_addr_r ramdisk_addr_r`.
Each load must succeed. The last load supplies the raw initramfs length to
`booti`. The environment changes below last for this boot.
[U-Boot load](https://docs.u-boot.org/en/stable/usage/cmd/load.html) ·
[U-Boot booti](https://docs.u-boot.org/en/stable/usage/cmd/booti.html)

```text
setenv cvbs_part 0:1
setenv cvbs_dir /boot/cvbs-probe
setenv bootargs 'console=ttyS0,115200n8 rdinit=/init'
load mmc ${cvbs_part} ${kernel_addr_r} ${cvbs_dir}/Image && load mmc ${cvbs_part} ${fdt_addr_r} ${cvbs_dir}/zero2w-cvbs.dtb && load mmc ${cvbs_part} ${ramdisk_addr_r} ${cvbs_dir}/initramfs.cpio.gz && booti ${kernel_addr_r} ${ramdisk_addr_r}:${filesize} ${fdt_addr_r}
```

The UART shell reports the physical DRM connectors and encoders. Run
`cvbs-bars PAL`, select PAL on EasyCAP, and press Enter to release the
framebuffer after recording it. Repeat with `cvbs-bars NTSC` and the matching
capture standard. Each command submits the TV standard, connector mode and
full-frame primary plane together. If probing fails, capture the serial log,
`dmesg` and `cat /sys/kernel/debug/devices_deferred`. Use `reboot -f` to leave
the diagnostic. Physical board boot, analogue capture and HDMI recovery are
pending. [Hardware acceptance record](../../../tests/hardware/zero2w-cvbs.md)
