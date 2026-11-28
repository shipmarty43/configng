import errno
import fcntl
import os
from pathlib import Path
import pty
import sys
import termios
import unittest
from array import array
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2]/"share/armbian-config"))
import header_bus_diag as diag


class BusTests(unittest.TestCase):
    def test_real_pty_has_no_direction_control(self):
        m, s = pty.openpty()
        try:
            with self.assertRaises(OSError) as exc:
                diag.rs485(s, "status")
            self.assertEqual(exc.exception.errno, errno.ENOTTY)
        finally:
            os.close(m); os.close(s)

    def test_driver_readback_rollback_and_conflict(self):
        live = array("I", [0]*8)
        def ioctl(fd, op, buf, mutate):
            if op == diag.SET_RS485:
                live[:] = buf
                live[0] &= ~2  # driver sanitizes RTS_ON_SEND
                buf[:] = live  # Linux also writes the sanitized value to the caller
            else:
                buf[:] = live
        with patch.object(fcntl,"ioctl",ioctl), patch.object(termios,"tcgetattr",return_value=[0,0,0]):
            with self.assertRaisesRegex(ValueError,"pinmux"):
                diag.rs485(3,"high")
            with self.assertRaisesRegex(ValueError,"rejected"):
                diag.rs485(3,"high",has_de=True)
            self.assertEqual(live[0],0)
            self.assertIn("0x5", diag.rs485(3,"low",has_de=True))
            self.assertIn("off",diag.rs485(3,"off"))
            with patch.object(termios,"tcgetattr",return_value=[0,0,termios.CRTSCTS]):
                with self.assertRaisesRegex(ValueError,"flow control"):
                    diag.rs485(3,"low",has_de=True)

if __name__ == "__main__": unittest.main()
