"""Boot environment selection and immutable single-node DT clock overlays."""
import os
from pathlib import Path
import re
import subprocess
import tempfile


def prop(blob, path, name, kind="s", default=None):
    options = ["-d", default] if default is not None else []
    return subprocess.check_output(["fdtget", "-t", kind, *options, blob, path, name],
                                   text=True).strip()


def tokens(text):
    lines = [line.split("=", 1)[1] for line in text.splitlines() if line.startswith("user_overlays=")]
    if len(lines) > 1:
        raise ValueError("Duplicate user_overlays entry")
    return lines[0].split() if lines else []


def env_names(text, key):
    values = [line.partition("=")[2].split() for line in text.splitlines()
              if line.startswith(key + "=")]
    if len(values) > 1:
        raise ValueError(f"Duplicate {key}")
    return values[0] if values else []


def replace_env_names(text, key, names):
    if env_names(text, key) == names:
        return text
    text = re.sub(rf"^{re.escape(key)}=.*(?:\n|$)", "", text, flags=re.M)
    if not names:
        return text
    return text + ("" if text.endswith("\n") else "\n") + key + "=" + " ".join(names) + "\n"


def write_selection(before, after, names):
    value = "user_overlays=" + " ".join(names)
    if tokens(before) == names:
        after.write_text(before)
    elif re.search(r"^user_overlays=", before, re.M):
        after.write_text(re.sub(r"^user_overlays=.*$", lambda _: value, before, flags=re.M))
    else:
        after.write_text(before + ("" if before.endswith("\n") else "\n") + value + "\n")


def install_overlay(folder, name, target, properties):
    cells = "\n".join(f"            {key} = <{value}>;" for key, value in properties.items())
    source = f'''/dts-v1/;
/plugin/;
/ {{
    fragment@0 {{
        target-path = "{target}";
        __overlay__ {{
{cells}
        }};
    }};
}};
'''
    data = subprocess.check_output(["dtc", "-I", "dts", "-O", "dtb"], input=source.encode())
    install_blob(folder, name, data)


def install_blob(folder, name, data):
    if folder.is_symlink():
        raise ValueError("Unexpected symlink at overlay-user")
    folder.mkdir(exist_ok=True)
    path = folder / (name + ".dtbo")
    if path.is_symlink():
        raise ValueError(f"Unexpected symlink at {path.name}")
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"Existing clock overlay differs: {path.name}")
        return
    with tempfile.NamedTemporaryFile(dir=folder, delete=False) as f:
        try:
            f.write(data)
            f.flush()
            os.fchmod(f.fileno(), 0o644)
            os.fsync(f.fileno())
            os.link(f.name, path)
        finally:
            Path(f.name).unlink(missing_ok=True)
    fd = os.open(folder, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def check_overlay(file, target, properties):
    fragment = "/fragment@0"
    edit = fragment + "/__overlay__"

    def entries(flag, path):
        return set(subprocess.check_output(["fdtget", flag, file, path], text=True).split())

    if (file.is_symlink() or entries("-l", "/") != {"fragment@0"} or
            entries("-p", fragment) != {"target-path"} or prop(file, fragment, "target-path") != target or
            entries("-l", fragment) != {"__overlay__"} or entries("-l", edit) or
            entries("-p", edit) != set(properties) or
            any(prop(file, edit, k, "u") != str(v) for k, v in properties.items())):
        raise ValueError(f"Unexpected contents in managed overlay {file.name}")
