#!/usr/bin/env python3
"""Fetch hash-pinned release inputs on the build machine."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import urllib.request

HERE = Path(__file__).resolve().parent
PPA = "https://ppa.launchpadcontent.net/meshtastic/beta/ubuntu/pool/main/m/meshtasticd/"


def cached(path, expected):
    if not path.exists():
        return False
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
            raise ValueError(f"Existing input has unexpected digest: {path}")
    return True


def download(url, path, expected):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as out:
        try:
            digest = hashlib.sha256()
            with urllib.request.urlopen(url, timeout=40) as response:
                while chunk := response.read(128 * 1024):
                    out.write(chunk)
                    digest.update(chunk)
            if digest.hexdigest() != expected:
                raise ValueError(f"Digest mismatch: {path.name}")
            out.flush()
            os.replace(out.name, path)
        finally:
            Path(out.name).unlink(missing_ok=True)


def wheel_url(filename, digest):
    package, version = filename.split("-")[:2]
    with urllib.request.urlopen(f"https://pypi.org/pypi/{package}/{version}/json", timeout=30) as reply:
        entries = json.load(reply)["urls"]
    for entry in entries:
        if entry["filename"] == filename and entry["digests"]["sha256"] == digest:
            return entry["url"]
    raise ValueError(f"Missing pinned wheel: {filename}")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("destination", type=Path)
    target = cli.parse_args().destination
    for line in (HERE / "inputs.sha256").read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        path = target / name
        if not cached(path, digest):
            url = wheel_url(path.name, digest) if path.suffix == ".whl" else PPA + path.name
            download(url, path, digest)
    for line in (HERE / "resolute-deps.sha256").read_text().splitlines():
        digest, relative = line.split(maxsplit=1)
        path = target / "ubuntu" / Path(relative).name
        if not cached(path, digest):
            download("https://ports.ubuntu.com/ubuntu-ports/" + relative, path, digest)


if __name__ == "__main__":
    main()
