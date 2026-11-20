"""Open the local simulator's phone API and wait for the SDK's full handshake."""
from queue import Empty, Queue
import time

from meshtastic.tcp_interface import TCPInterface
from pubsub import pub


def connect_simulator(port=4403, timeout=12):
    ready = Queue()

    def established(interface):
        ready.put(interface)

    pub.subscribe(established, "meshtastic.connection.established")
    try:
        client = TCPInterface(hostname="127.0.0.1", portNumber=port, timeout=timeout)
        # TCPInterface returns before its reader has finished the first heartbeat.
        # There may be multiple clients in the two-firmware acceptance process.
        deadline = time.monotonic() + timeout
        try:
            while ready.get(timeout=max(0, deadline-time.monotonic())) is not client:
                pass
        except Empty:
            client.close()
            raise TimeoutError("Simulator phone API handshake timed out") from None
        return client
    finally:
        pub.unsubscribe(established, "meshtastic.connection.established")
