"""Small atomic state files for Zero 2W hardware controls."""
import json
import os
from pathlib import Path
import tempfile


def load(path):
    return json.loads(path.read_text())


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as out:
        try:
            json.dump(data, out)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
            os.replace(out.name, path)
        finally:
            Path(out.name).unlink(missing_ok=True)
    fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
