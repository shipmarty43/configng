# Zero 2W official Android 12 TV v1.0: offline inspection

Inspected 2026-10-26 after the owner downloaded the two archives linked from
the manufacturer's download page. The earlier Google Drive quota blocker is
resolved for this investigation. Neither the firmware nor its binaries were
executed, and no SD card was changed. Hardware CVBS operation is still untested.

Full hashes, item offsets, patch file hashes and extracted DTB hashes are in
[the machine-readable record](zero2w-official-android.json).

| Input | Bytes | SHA-256 |
|---|---:|---|
| `opizero2w_android12_patches.tar.gz` | 55,587 | `29e9450567d44e4b8c649da092aaed1aea833474ff64393ae22c64b7d2d0cfd7` |
| `Orangepi_zero2w_android12_tv_v1.0.tar.gz` | 578,269,602 | `4ad49833c1c7f91fc5cfa8f6a3bace1e1ae82adbe417ab9b5e4ba9edeb663984` |
| Extracted `.img` | 1,247,014,912 | `9bee8e58cb2b8aab5daf301b70de1fb5eda8ed2ea104b5791645bfe690e72e84` |

These are locally computed content identities, not independently published
vendor signatures. The image is an unencrypted Allwinner IMAGEWTY v3 package
with 45 entries; it is not a raw SD disk image.

## Official patch compared with the community source

The official patch's
`longan/device/config/chips/h618/configs/p2/linux-5.4/board.dts` is byte-identical
to the file previously inspected in community Longan commit
`47b861f18054c373241666c1ad3cb6ba0f265441`.
Its SHA-256 is `7452a0f9a5741b5018ea8b448053eb0a15226a465939e7b122f957a45259ec12`.
This closes the provenance gap for that board source file. It does not establish
that the entire community Android distribution matches the vendor image.

The small patch contains seven files: board DTS, kernel defconfig, SPI NOR
driver and four Android device configuration files. It does **not** include
the TVE implementation or a U-Boot DTS. The TVE sources previously compared
remain separately identified references.

The patch defconfig differs from the current official BSP defconfig in several
non-display options. More directly, IKCONFIG extracted from the actual
`boot.fex` kernel confirms Linux **5.4.125**, `CONFIG_ARCH_SUN50IW9=y`,
`CONFIG_DISP2_SUNXI=y`, `CONFIG_TV_DISP2_SUNXI=y`, and `CONFIG_EXTCON=y`.
The AC200 and GM7121 encoder options are disabled. The bundled compressed
`vmlinux.fex` has the same embedded configuration. This confirms the compiled
configuration, not source-to-binary reproducibility or physical output.

## Device trees actually present in the firmware

Seven FDT candidates were extracted and decoded successfully with `dtc`.
They form three byte-identical groups:

| Image offset | Containing item | Tree |
|---|---|---|
| `0x00023000` | `sunxi.fex` | Kernel DT, model `Orange Pi Zero2w` |
| `0x00268000` | `boot_package.fex` | Same kernel DT |
| `0x0555b400` | `vendor_boot.fex` | Same kernel DT |
| `0x0012ccdc` | `u-boot.fex` | U-Boot-embedded tree, model `OrangePi Zero3` |
| `0x002180dc` | `boot_package.fex` | Same U-Boot tree |
| `0x00238800` | `boot_package.fex` | PMIC/CPU-supply overlay |
| `0x4a33ec40` | `dtbo.fex` | Same overlay |

The Android vendor-boot v3 header independently locates the kernel DT at
relative offset `0x1800`, length 69,461 bytes: header 2,112 bytes, page size
2,048, vendor ramdisk 1,437 bytes. This agrees with the carved offset, rather
than relying solely on a magic-byte search. Header layout reference:
[AOSP boot image definitions](https://android.googlesource.com/platform/system/tools/mkbootimg/+/refs/heads/main/include/bootimg/bootimg.h).

The kernel DT's `/soc@3000000/tv0@6520000` has:

- `status = "okay"`, `interface = 1`, `dac_src0 = 0`, `dac_type0 = 0`;
- TOP window `0x06520000 / 0x100`, TVE window `0x06524000 / 0x3fc`;
- three named clocks, two named resets, assigned parent and `tvout` NVMEM cell;
- TV/PAL as screen 1 (`type=2`, `mode=11`); HDMI as screen 0;
- boot candidates for HDMI and TV with detection enabled, fallback device 0.

The embedded U-Boot tree also enables TVE and DAC0 with PAL as the TV default.
Its old `tv0@01c94000` node name still has **actual `reg` windows at
`0x06520000` and `0x06524000`**. Its `OrangePi Zero3` model string is present in
the vendor image and in the community p2 U-Boot source. Do not silently rename
it, infer board compatibility from it, or substitute it for the kernel DT.
Whether other inherited U-Boot properties matter requires hardware validation.

Stored `boot_disp` is zero. It is a placeholder before the bootloader's runtime
selection; this does not contradict the earlier derived TV/PAL handoff value.
No actual boot handoff has been captured.

The DTBO table contains one entry. Its fixups target `twi5` and `cpu0`, modifying
PMIC/regulators and CPU supply; no TV/display override is present. The stored
vendor command line nevertheless contains `androidboot.dtbo_idx=0,1,2`.
Record this discrepancy without assuming how the vendor bootloader resolves it.
The live device tree remains the authority for the booted board.

## Reproduce the inventory

Extract the image from the downloaded tar archive into a workspace directory.
Run the standard-library-only helper on that regular file:

```sh
python3 tests/hardware/inspect_imagewty.py \
  /path/to/Orangepi_zero2w_android12_tv_v1.0.img /path/to/new-output
dtc -I dtb -O dts -o /path/to/kernel.dts \
  /path/to/new-output/offset-0555b400.dtb
python3 -m unittest discover -s tests/hardware -p 'test_inspect_imagewty.py'
```

The helper validates the supported container header, file bounds and overlaps;
reports item names without using them as paths; writes only bounded FDT
candidates and an inventory into a new directory. It never mounts, flashes or
runs image contents. It is a narrow v3 inspection tool, not a universal image
unpacker. `dtc` accepts the extracted legacy trees with warnings; decoding is
not modern DT schema validation. Five synthetic boundary tests pass, and its
seven outputs match the independently carved files byte-for-byte.

## Remaining work

The source board configuration and the packed TVE configuration now agree.
The packaged Android userspace/HAL has not yet been matched to the community
HAL, and there is still no capture from this physical board. Continue with
the [EasyCAP hardware procedure](zero2w-cvbs.md), retaining a separate test SD,
and select the target Armbian kernel before implementing a DRM encoder port.
Do not copy vendor `disp2` nodes straight into a mainline DRM device tree.
