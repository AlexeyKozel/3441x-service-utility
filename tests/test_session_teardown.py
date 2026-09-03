from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utility3441x.instrument import VisaInstrument  # noqa: E402


VISA_INV_OBJECT = (
    "VI_ERROR_INV_OBJECT (-1073807346): "
    "The given session or object reference is invalid."
)


def detached_instrument(resource: object, manager: object = None) -> VisaInstrument:
    """A VisaInstrument bound to fakes, without opening VISA."""

    instrument = VisaInstrument.__new__(VisaInstrument)
    instrument._inst = resource
    instrument._rm = manager
    return instrument


class DeadSession:
    """A session whose event context died with an instrument reboot.

    pyvisa's Resource.close() calls before_close() -> __switch_events_off() ->
    disable_event() before it closes the session, and that is what the backend
    rejects. The handle answers queries right up until it is closed.
    """

    read_termination = "\n"
    timeout = 10_000

    @staticmethod
    def close() -> None:
        raise OSError(VISA_INV_OBJECT)


class LiveSession:
    read_termination = "\n"
    timeout = 10_000

    def __init__(self):
        self.closed = False

    def close(self) -> None:
        self.closed = True


class ManagerHoldingALeakedResource:
    """A ResourceManager that walks a resource reconnect() failed to close.

    reconnect() closes the dead handle inside `except Exception: pass`, so a
    close that fails leaves the resource registered. _rm.close() then walks it
    and raises, which is how the error reached the operator even when _inst
    itself was a healthy post-reconnect session.
    """

    @staticmethod
    def close() -> None:
        raise OSError(VISA_INV_OBJECT)


class HealthyManager:
    def __init__(self):
        self.closed = False

    def close(self) -> None:
        self.closed = True


class SessionTeardownTests(unittest.TestCase):
    """Releasing a session must not fail the operation that just finished.

    Observed on an Agilent 34410A: an APP image was uploaded, the instrument
    rebooted itself while the GUI's power-cycle dialog was open, and
    wait_for_final_app_identity confirmed the final identity. Leaving the
    `with VisaInstrument(...)` block then raised VI_ERROR_INV_OBJECT out of a
    completed operation, and the GUI reported "Operation failed" and discarded
    the verified result. Reproduced deterministically by pausing 60 s between
    the upload and the wait, standing in for the dialog.
    """

    def test_a_dead_session_does_not_fail_the_close(self):
        manager = HealthyManager()
        instrument = detached_instrument(DeadSession(), manager)
        instrument.close()
        self.assertIsNone(instrument._inst)
        self.assertTrue(manager.closed, "the manager must still be closed")

    def test_a_leaked_resource_in_the_manager_does_not_fail_the_close(self):
        # _inst is healthy here: this is the post-reconnect case, where the
        # failure comes from the manager walking a resource reconnect() leaked.
        session = LiveSession()
        instrument = detached_instrument(session, ManagerHoldingALeakedResource())
        instrument.close()
        self.assertTrue(session.closed)
        self.assertIsNone(instrument._inst)

    def test_both_failing_at_once_does_not_fail_the_close(self):
        instrument = detached_instrument(DeadSession(), ManagerHoldingALeakedResource())
        instrument.close()
        self.assertIsNone(instrument._inst)

    def test_context_manager_exit_does_not_discard_a_completed_result(self):
        instrument = detached_instrument(DeadSession(), ManagerHoldingALeakedResource())
        with instrument:
            result = "the verified result the caller wants to return"
        self.assertEqual(result, "the verified result the caller wants to return")


if __name__ == "__main__":
    unittest.main()
