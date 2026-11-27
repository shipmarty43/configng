"""Run the patched C driver functions against memory-backed registers, using matching source inputs."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

DIR = Path(__file__).resolve().parent
REPO = DIR.parents[2]


def function(source, name):
    start = source.index(name + "(")
    start = source.rindex("\n", 0, start) + 1
    end = source.index("\n}", start) + 2
    return source[start:end]


def check(board, directory, work):
    name, target, patch, functions = {
        "h618": ("pwm-sunxi-enhance", "drivers/pwm", "h616-io/patches/pwm-pair-stop.patch",
                 ["get_pccr_reg_offset", "get_pdzcr_reg_offset", "sunxi_pwm_config_dual",
                  "sunxi_pwm_set_polarity_dual", "sunxi_pwm_enable_dual", "sunxi_pwm_disable_dual"]),
        "a733": ("pwm-sunxi", "bsp/drivers/pwm", "a733-io/patches/pwm-capture-burst.patch",
                 ["sunxi_pwm_set_polarity", "get_pdzcr_reg_offset", "sunxi_pwm_config_clk",
                  "sunxi_pwm_config_single", "sunxi_pwm_config_dual", "sunxi_pwm_config_channel",
                  "sunxi_pwm_enable_single", "sunxi_pwm_enable_dual", "sunxi_pwm_enable",
                  "sunxi_pwm_disable_single", "sunxi_pwm_disable_dual", "sunxi_pwm_disable",
                  "sunxi_pwm_apply", "sunxi_pwm_handler",
                  "sunxi_pwm_capture_a733"]),
    }[board]
    dest = work / target
    dest.mkdir(parents=True, exist_ok=True)
    for suffix in (".h", ".c"):
        shutil.copyfile(directory / (name + suffix), dest / (name + suffix))
    subprocess.run(["git", "apply", str(REPO / "hardware" / patch)], cwd=work, check=True)
    source = (dest / (name + ".c")).read_text()
    code = '#include "' + name + '.h"\n#include "registers.h"\n'
    code += "\n".join(function(source, f) for f in functions)
    file = work / (board + ".c")
    file.write_text(code + '\n#include "checks.h"\n')
    subprocess.run(["cc", "-std=gnu11", "-Werror=implicit-function-declaration", "-D" + board.upper(),
                    "-I", dest, "-I", DIR, file, "-o", work / board], check=True)
    subprocess.run([work / board], check=True)


if __name__ == "__main__":
    h, a = map(Path, sys.argv[1:])
    with tempfile.TemporaryDirectory() as tmp:
        for board, directory in (("h618", h), ("a733", a)):
            check(board, directory, Path(tmp))
