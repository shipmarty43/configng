"""Relink the existing minimal ARM64 6.18.57 gpio-sim build with lab providers."""
from pathlib import Path
import argparse
import shlex
import subprocess

here = Path(__file__).resolve().parent
cli = argparse.ArgumentParser(description=__doc__)
cli.add_argument("objects", type=Path)
cli.add_argument("work", type=Path)
args = cli.parse_args()
obj, work = args.objects.resolve(), args.work.resolve()
source = (obj / "source").resolve()
config = (obj / ".config").read_text()
if not all(x in config.splitlines() for x in (
        "CONFIG_I2C_MV64XXX=y", "CONFIG_POWER_SUPPLY=y", "CONFIG_LTO_NONE=y",
        "# CONFIG_KALLSYMS is not set", "# CONFIG_PWM is not set")):
    raise SystemExit("Expected the project's minimal ARM64 gpio-sim build")
record = (obj/"drivers/i2c/busses/.i2c-mv64xxx.o.cmd").read_text().splitlines()[0]
compiler = shlex.split(record.split(" := ", 1)[1])
objects = []
# The existing thin archive is read in place. Place all additional objects in
# the new directory. Only the real PWM framework and test provider need CONFIG_PWM.
for path in (here/"dfr0528_adapter.c", here.parents[2]/"hardware/dfrobot-ups/dfr0528_battery.c",
             here/"pwm_chip.c", source/"drivers/pwm/core.c"):
    output = work / (path.stem + ".o")
    cmd = [arg for arg in compiler if not arg.startswith("-Wp,-MMD,")]
    for i, arg in enumerate(cmd):
        if arg.startswith(("-DKBUILD", "-D__KBUILD")):
            cmd[i] = arg.replace("drivers/i2c/busses/i2c-mv64xxx", path.stem).replace("i2c_mv64xxx", path.stem)
    cmd[cmd.index("-o")+1] = str(output)
    cmd[-1] = str(path)
    if path.stem in ("pwm_chip", "core"):
        cmd.insert(1, "-DCONFIG_PWM=1")
    subprocess.run(cmd, cwd=obj, check=True)
    objects.append(output)
subprocess.run(["aarch64-linux-gnu-ld", "--no-keep-memory", "-EL", "-maarch64elf", "-z", "noexecstack",
                "--no-undefined", "-X", "--pic-veneer", "--build-id=sha1", "-T", "arch/arm64/kernel/vmlinux.lds",
                "-o", work/"vmlinux", "--whole-archive", "vmlinux.a", "--no-whole-archive", *objects,
                "init/version-timestamp.o", ".vmlinux.export.o"], cwd=obj, check=True)
subprocess.run(["aarch64-linux-gnu-objcopy", "-O", "binary", "-R", ".note", "-R", ".note.gnu.build-id",
                "-R", ".comment", "-S", work/"vmlinux", work/"Image"], check=True)
