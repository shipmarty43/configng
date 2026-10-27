#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise the actual CLI and private files; never enable or access hardware."""
import pathlib
import subprocess
import sys
import tempfile

binary = sys.argv[1]
example = pathlib.Path(__file__).with_name('lorawan.conf.example').read_text()
# Deliberately synthetic test credentials, never used on air.
keys = ('join_eui=0000000000000000\ndev_eui=0102030405060708\n'
        'app_key=0102030405060708090a0b0c0d0e0f10\n')
with tempfile.TemporaryDirectory(prefix='opi-lw-cli-') as tmp:
    root = pathlib.Path(tmp)
    config, credentials, state = root/'config', root/'keys', root/'state-dir'
    config.write_text(example)
    credentials.write_text(keys)
    config.chmod(0o600)
    credentials.chmod(0o600)
    state.mkdir(mode=0o700)

    def call(action, ok):
        r = subprocess.run([binary, action, str(config), str(credentials), str(state)],
                           text=True, capture_output=True, timeout=5)
        assert (r.returncode == 0) == ok, (action, r.stdout, r.stderr)
        assert '0102030405060708090a0b0c0d0e0f10' not in r.stdout+r.stderr
        return r

    call('check', True)
    call('preflight', False)
    call('status', False)
    assert not (state/'state').exists()
    call('provision', True)
    original = (state/'state').read_bytes()
    call('provision', False)
    call('status', True)
    call('run', False)
    assert (state/'state').read_bytes() == original
    credentials.chmod(0o644)
    call('check', False)
    credentials.chmod(0o600)
    credentials.rename(root/'real-keys')
    credentials.symlink_to(root/'real-keys')
    call('check', False)
    credentials.unlink()
    (root/'real-keys').rename(credentials)
    credentials.write_text(keys.replace('dev_eui=01', 'dev_eui=02'))
    call('status', False)
    credentials.write_text(keys)
    (state/'state').write_text('interrupted or corrupt state')
    call('status', False)
    call('provision', False)
    assert (state/'state').read_text() == 'interrupted or corrupt state'
print('CLI validation, provisioning, disabled run, permissions, symlinks and corrupt state: passed')
