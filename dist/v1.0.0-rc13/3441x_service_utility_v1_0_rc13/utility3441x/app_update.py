"""Post-END completion checks for APP firmware updates."""

from __future__ import annotations

import time
from typing import Callable, Protocol

from .srecord import XsPackage, assert_app_identity_after


class AppCompletionInstrument(Protocol):
    def identity(self) -> dict[str, str]: ...

    def reconnect(self) -> None: ...


def wait_for_final_app_identity(
    instrument: AppCompletionInstrument,
    package: XsPackage,
    identity_before: dict[str, str],
    *,
    timeout_seconds: float = 600.0,
    poll_seconds: float = 2.0,
    status: Callable[[str], None] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, str]:
    """Wait through internal programming/reboots without repeating the upload."""

    if timeout_seconds <= 0 or poll_seconds <= 0:
        raise ValueError("APP completion timeouts must be positive")
    deadline = monotonic() + timeout_seconds
    last_identity: dict[str, str] | None = None
    last_error: Exception | None = None

    while True:
        try:
            candidate = instrument.identity()
            last_identity = candidate
            last_error = None
            if (
                candidate.get("serial") == identity_before.get("serial")
                and candidate.get("model") == package.model
            ):
                assert_app_identity_after(package, identity_before, candidate)
                return candidate
        except Exception as exc:
            last_error = exc

        remaining = deadline - monotonic()
        if remaining <= 0:
            detail = (
                f"last identity={last_identity}"
                if last_identity is not None
                else f"last error={type(last_error).__name__}: {last_error}"
            )
            raise TimeoutError(
                "APP blocks were accepted and END returned zero, but final APP "
                f"identity was not observed; do not retry automatically; {detail}"
            )

        if status is not None:
            model = last_identity.get("model") if last_identity else "unavailable"
            status(
                f"Waiting for manual power cycle and final APP boot "
                f"(current identity: {model})"
            )
        sleep(min(poll_seconds, remaining))
        try:
            instrument.reconnect()
        except Exception as exc:
            last_error = exc
