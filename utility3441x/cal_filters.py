"""Offline, DC-normalized linear projections of saved schema45 FIR coefficients.

These curves describe coefficient mathematics. They do not model integer
FPGA arithmetic, active RAM contents, the ADC, analog path, or full instrument
response. The optional cascade axes are conditional image1 nominal models.
"""
from __future__ import annotations

import cmath
import math
from typing import Any


# Source-derived conditional image1 projection conditions documented in
# research/cal_app11_{cascade,aci_cascade}_projection_20261006.
CONDITIONAL_G3_HZ = 106_250_000
CONDITIONAL_ACV_EVENT_PERIOD_G3 = 72
CONDITIONAL_ACI_EVENT_PERIOD_G3 = 108
CASCADE_AXIS_SCOPE = (
    "Conditional nominal image1 event-frequency axis; not a measured clock, "
    "sample rate, or full instrument response. ACV: stage lags 2k/j, ordinary "
    "profile 68/138/68/68, timing L71/K59/H63/Fine2. ACI: lags 7k/j, "
    "profile 68/488/68/68, timing L107/K102/H92/Fine2. Both assume held "
    "lock/release, washout with no new RX writes, and historical fixture taps."
)


def _signed_low16(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("FIR CAL tap must be an integer int32 value")
    if not -(1 << 31) <= value < (1 << 31):
        raise ValueError("FIR CAL tap is outside int32 range")
    low = value & 0xFFFF
    return low - 0x10000 if low & 0x8000 else low


def filter_vectors(report: dict[str, Any]) -> dict[str, list[int]]:
    """Extract complete flatness/lp vectors from an explained schema45 report."""
    if not isinstance(report, dict) or report.get("version") != 45 or report.get("bodyLength") != 4924:
        raise ValueError("FIR vectors require a schema45 CAL report with a 4924-byte body")
    if report.get("interpretation", {}).get("status") != "available":
        raise ValueError("FIR vectors require available exact CAL field meanings")
    schema = report.get("schema45")
    if not isinstance(schema, dict) or schema.get("elementCount") != 1072:
        raise ValueError("Invalid schema45 field report")
    values = schema.get("values")
    if not isinstance(values, list) or len(values) != 1072:
        raise ValueError("Invalid schema45 value list")

    grouped: dict[str, dict[int, int]] = {}
    families: dict[str, str] = {}
    for entry in values:
        if not isinstance(entry, dict):
            raise ValueError("Invalid schema45 value entry")
        meaning = entry.get("meaning")
        if not isinstance(meaning, dict):
            raise ValueError("FIR extraction requires exact CAL field meanings")
        family = meaning.get("family")
        if family not in ("flatness", "lp"):
            continue
        name = meaning.get("nameBase")
        index = meaning.get("elementIndex")
        if not isinstance(name, str) or not name or isinstance(index, bool) or not isinstance(index, int):
            raise ValueError("Invalid FIR field identity")
        if entry.get("type") != "int32":
            raise ValueError("FIR CAL fields must be int32")
        if name in families and families[name] != family:
            raise ValueError("FIR vector has inconsistent family identity")
        families[name] = family
        members = grouped.setdefault(name, {})
        if index in members:
            raise ValueError("Duplicate FIR element index")
        members[index] = _signed_low16(entry.get("value"))

    if not grouped:
        raise ValueError("No flatness/lp vectors found")
    result: dict[str, list[int]] = {}
    for name, members in grouped.items():
        if set(members) != set(range(70)):
            raise ValueError(f"Incomplete or invalid 70-tap FIR vector: {name}")
        taps = [members[index] for index in range(70)]
        if sum(taps) == 0:
            raise ValueError(f"FIR vector has zero DC sum: {name}")
        result[name] = taps
    return result


def _validate_taps(taps: Any) -> list[float]:
    try:
        coeffs = [float(value) for value in taps]
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("taps must be a finite nonempty coefficient sequence") from exc
    if not coeffs or any(not math.isfinite(value) for value in coeffs):
        raise ValueError("taps must be a finite nonempty coefficient sequence")
    if sum(coeffs) == 0:
        raise ValueError("Zero DC sum: normalization is undefined")
    return coeffs


def _response(coeffs: list[float], frequency: float, lag: int = 1) -> complex:
    total = sum(coeffs)
    return sum(c * cmath.exp(-2j * math.pi * frequency * lag * k)
               for k, c in enumerate(coeffs)) / total


def response(taps: Any, points: int = 513, lag: int = 1) -> list[tuple[float, float]]:
    """Return (cycles per tap-index, dB relative to DC) through Nyquist."""
    coeffs = _validate_taps(taps)
    if isinstance(points, bool) or not isinstance(points, int) or points < 2:
        raise ValueError("points must be an integer >= 2")
    if isinstance(lag, bool) or not isinstance(lag, int) or lag < 1:
        raise ValueError("lag must be a positive integer")
    result = []
    for i in range(points):
        frequency = 0.5 * i / (points - 1)
        magnitude = abs(_response(coeffs, frequency, lag))
        db = 20 * math.log10(magnitude) if magnitude else float("-inf")
        result.append((frequency, db))
    return result


def cascade_response(flatness: Any, lp: Any, kind: str,
                     points: int = 513) -> list[tuple[float, float]]:
    """Return conditional nominal-Hz ACV or ACI two-FIR linear projection."""
    flat = _validate_taps(flatness)
    lowpass = _validate_taps(lp)
    if isinstance(points, bool) or not isinstance(points, int) or points < 2:
        raise ValueError("points must be an integer >= 2")
    if kind == "acv":
        period, stride = CONDITIONAL_ACV_EVENT_PERIOD_G3, 2
    elif kind == "aci":
        period, stride = CONDITIONAL_ACI_EVENT_PERIOD_G3, 7
    else:
        raise ValueError("kind must be 'acv' or 'aci'")
    sample_rate = CONDITIONAL_G3_HZ / period
    nyquist = sample_rate / 2
    result = []
    for i in range(points):
        frequency = nyquist * i / (points - 1)
        event_frequency = frequency / sample_rate
        h = _response(flat, event_frequency, stride) * _response(lowpass, event_frequency, 1)
        magnitude = abs(h)
        db = 20 * math.log10(magnitude) if magnitude else float("-inf")
        result.append((frequency, db))
    return result
