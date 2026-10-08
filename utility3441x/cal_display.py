"""Conservative, read-only human display of explained schema45 CAL values.

The returned values describe saved coefficients, not calibration correctness or
an active instrument configuration. No result path or hardware state is changed.
"""
from __future__ import annotations

import math
import re
from typing import Any


_GAIN_UNITS = {
    "DcvGain": "V", "DciGain": "A", "ResGain": "ohm", "Res4Gain": "ohm",
    "AcvGain": "V", "AciGain": "A",
}
_OFFSET_UNITS = {"DcvOff": "V", "DciOff": "A", "ResOff": "ohm", "Res4Off": "ohm"}
_OFFSET_GAIN = {"DcvOff": "DcvGain", "DciOff": "DciGain",
                "ResOff": "ResGain", "Res4Off": "Res4Gain"}
# Exact APP11 2.43 constructor binary64 values, not presumed ideal gains.
# Evidence: research/cal_dci_reference_20261008/firmware_reference.json.
_DCI_REFERENCE_GAINS = {
    "DciGain100u": 1.6360649992225384e-11,
    "DciGain1_0m": 1.6360649992225388e-10,
    "DciGain10m": 1.6524256492147642e-9,
    "DciGain100m": 1.652425649214764e-8,
    "DciGain1_0": 3.2387542724609374e-8,
    "DciGain3_0": 3.2387542724609377e-7,
}
# Same five initial values verified independently in APP10 and APP11 2.43.
# Evidence: research/cal_dcv_reference_20261008/firmware_reference.json.
_DCV_REFERENCE_GAINS = {
    "DcvGain0_1": 3.2387542724609376e-9,
    "DcvGain1_0": 3.2387542724609374e-8,
    "DcvGain10": 3.2387542724609377e-7,
    "DcvGain100": 3.2387542724609375e-6,
    "DcvGain1000": 3.2387542724609374e-5,
}
# All 22 named states verified in APP10/APP11 2.43; 2W/4W bases match.
# High ranges intentionally share a base. OC uses a different base.
# Evidence: research/cal_res_reference_20261008/firmware_reference.json.
_RES_REFERENCE_GAINS = {
    family + suffix: gain
    for family in ("ResGain", "Res4Gain")
    for suffix, gain in {
        "100": 3.2387542724609375e-6,
        "1K": 3.2387542724609374e-5,
        "10K": 3.238754272460938e-4,
        "100K": 0.003238754272460938,
        "1M": 0.06477508544921876,
        "10M": 0.6477508544921875,
        "100M": 0.6477508544921875,
        "1G": 0.6477508544921875,
        "100OC": 3.5986158582899304e-6,
        "1KOC": 3.5986158582899305e-5,
        "10KOC": 3.5986158582899307e-4,
    }.items()
}
# Explicit APP10/APP11 2.43 reference expressions; runtime initializer order
# is not asserted. ACI 3 A has a zero reference and cannot form a ratio.
# Evidence: research/cal_ac_reference_20261008/firmware_reference.json.
_AC_REFERENCE_GAINS = {
    "AcvGain1000V": 1.8616 * 100,
    "AcvGain100V": 1.8616 * 10,
    "AcvGain100mV": 1.8616 / 100,
    "AcvGain10V": 1.8616,
    "AcvGain1V": 1.8616 / 10,
    "AciGain1A": 0.42451,
    "AciGain100mA": 0.42451 * 0.05,
    "AciGain10mA": (0.42451 * 0.05) * 0.1,
    "AciGain1mA": (0.42451 * 0.05) * 0.01,
    "AciGain100uA": (0.42451 * 0.05) * 0.001,
    "AciGain3A": 0.0,
}
_PREFIXES = ((-12, "p"), (-9, "n"), (-6, "u"), (-3, "m"),
             (0, ""), (3, "k"), (6, "M"), (9, "G"), (12, "T"))
_LABELS = {
    "DcvGain": "DC voltage scale", "DcvOff": "DC voltage offset",
    "DciGain": "DC current scale", "DciOff": "DC current offset",
    "ResGain": "2-wire resistance scale", "ResOff": "2-wire resistance offset",
    "Res4Gain": "4-wire resistance scale", "Res4Off": "4-wire resistance offset",
    "AcvGain": "AC voltage RMS scale", "AcvSqNoise": "AC voltage squared-noise term",
    "AciGain": "AC current RMS scale", "AciSqNoise": "AC current squared-noise term",
    "FreqGain": "Frequency scale", "Divider10M": "High-range resistance divider",
    "AdcQuad": "DC voltage quadratic coefficient", "PrechargePwm": "Precharge PWM setting",
    "AcvSlowNoiseGainSquared": "SLOW noise-term multiplier adjustment",
    "Adc_FineMergeGain": "ADC fine merge scale",
    "Adc_DcOffset": "ADC internal offset",
    "Adc_PiOffset": "ADC alternating offset",
    "Adc_LutGain": "ADC coarse correction scale",
    "Adc_Jitter": "ADC digital modulation setting",
    "Adc_N_Decisions": "ADC decision-cycle length",
    "Adc_Nf_Slope": "ADC decision window",
    "Adc_FineSamplOffset": "ADC fine-sample position",
    "AcvMedIirDenomCoef": "MED AC filter feedback factor",
    "AcvSlowIirDenomCoef": "SLOW AC filter feedback factor",
    "AcvMedIirNumeratorCoef": "MED AC compensation scale",
    "AcvSlowIirNumeratorCoef": "SLOW AC compensation scale",
    "AcvSlowDcGainSquared": "SLOW DC compensation setting",
    "CapOffset": "Capacitance offset",
    "HeaterRes": "Heater resistance setting",
    "HeaterGain": "Heater drive scale",
    "CurrentSrcDelay": "Current-source settling setting",
    "McDelay": "Signal-measurement delay (MC / AZ)",
    "MzDelay": "Zero-measurement delay (MZ / AZ)",
    "flatness": "AC flatness filter tap", "lp": "AC low-pass filter tap",
}
_OPEN_FAMILIES = {"AcvSlowDcGainSquared", "McDelay", "MzDelay"}
_ACTIONS = {
    "DcvGain": "Scales a DC voltage reading.", "DcvOff": "Shifts the DC voltage linear stage.",
    "DciGain": "Scales a DC current reading.", "DciOff": "Shifts the DC current linear stage.",
    "ResGain": "Scales a two-wire resistance reading.",
    "ResOff": "Shifts the two-wire resistance linear stage.",
    "Res4Gain": "Scales a four-wire resistance reading.",
    "Res4Off": "Shifts the four-wire resistance linear stage.",
    "AcvGain": "Scales the internal AC voltage RMS result.",
    "AciGain": "Scales the internal AC current RMS result.",
    "AcvSqNoise": "Adjusts the AC voltage power term before RMS conversion.",
    "AciSqNoise": "Adjusts the AC current power term before RMS conversion.",
    "AcvMedIirDenomCoef": "Shapes MED low-frequency AC filtering.",
    "AcvMedIirNumeratorCoef": "Shapes MED low-frequency AC filtering.",
    "AcvSlowIirDenomCoef": (
        "Controls how much of the previous state is retained by the SLOW AC "
        "compensation IIR filter. A positive coefficient closer to 1 makes "
        "the state decay more slowly in filter-update steps.\n\n"
        "For stored coefficient a, firmware forms q = trunc(a * 2^20 + 0.5).\n"
        "Effective feedback a_eff = q / 2^20. Ignoring integer truncation and "
        "overflow, the recurrence is y[n] = x[n] / 8 + a_eff * y[n-1].\n"
        "The actual implementation adds (x << 17) and q * previous_state "
        "in 64-bit arithmetic, then shifts right arithmetically by 20. "
        "This is one compensation stage. Its update period is not established "
        "here, so a time constant in seconds or a corner frequency in Hz "
        "cannot yet be assigned."),
    "AcvSlowIirNumeratorCoef": (
        "Sets the scale of the SLOW AC compensation contribution before the "
        "RMS result is formed. It scales the linear and squared compensation "
        "terms consistently; it is not a multiplier of the complete reading.\n\n"
        "For stored numerator b:\n"
        "A = (16 / 147^3) * b\n"
        "C_linear = A * 2^-28; C_squared = A^2 * 256.\n"
        "For internal compensation inputs Uc and Qc, the contribution to "
        "the power calculation is Qc * C_squared - (Uc * C_linear)^2. "
        "At fixed inputs this contribution scales as b^2. The internal input "
        "scales and later RMS processing must be retained; b alone does not "
        "describe the instrument frequency response."),
    "AcvSlowDcGainSquared": (
        "Saved parameter named for SLOW DC compensation. Its CAL state and "
        "getter have been identified, but a path from this saved value to "
        "the working result calculation has not been established.\n\n"
        "A separate internal DC-gain setter stores its argument plus 1, "
        "but there is no confirmed connection from this CAL field to that "
        "setter. The checked ordinary SLOW result calculation does not read "
        "that internal DC-gain field. Consequently neither 1 + CAL nor "
        "sqrt(CAL) is presented as an effective correction. This does not "
        "prove that the saved parameter is unused everywhere."),
    "AcvSlowNoiseGainSquared": (
        "Adjusts the noise term subtracted during AC power calculation, "
        "before the square root and final range gain. The same saved state "
        "is selected in the checked SLOW and MED software paths.\n\n"
        "For stored adjustment c, the runtime multiplier is k_noise = 1 + c.\n"
        "P = P_signal_and_compensation - k_noise * SqNoise.\n"
        "SqNoise is the separate range-selected squared-noise term. For a "
        "positive SqNoise, increasing c subtracts more power. Before later "
        "limits and small-reading processing, y = G * sqrt(max(P, 0)), "
        "where G is the range gain. The displayed multiplier applies only "
        "to SqNoise, not to the entire reading or a measured noise level."),
    "AdcQuad": (
        "Applies a quadratic correction after the DC voltage linear stage "
        "in the checked 10 V range path.\n\n"
        "For linear-stage voltage V and saved coefficient q:\n"
        "correction = q * V^2; corrected voltage = V + q * V^2.\n"
        "q is in 1/V. Equivalently, the voltage-dependent multiplier is "
        "1 + q * V. At fixed q, the correction scales with the square of V; "
        "its sign follows q for either polarity of V."),
    "Adc_DcOffset": (
        "Sets the common level of the ADC feedback-offset table. Together with the "
        "alternating offset, it forms two table levels.\n\n"
        "D = trunc(DcOffset), P = trunc(PiOffset).\n"
        "offset[2k] = D+P; offset[2k+1] = D-P, for k = 0 through 31.\n"
        "trunc removes the fractional part toward zero. Increasing D by one "
        "raises both table levels by one before encoding. The table is read "
        "by the feedback address sequencer and combined with the generated "
        "digital modulation and coarse feedback-table contribution. "
        "Firmware builds 16-bit words; the FPGA retains their low 7 bits "
        "and uses them as signed feedback codes."),
    "Adc_PiOffset": (
        "Sets the alternating part of the ADC feedback-offset table. It is added "
        "to and subtracted from the common level in alternating entries.\n\n"
        "D = trunc(DcOffset), P = trunc(PiOffset).\n"
        "offset[2k] = D+P; offset[2k+1] = D-P, for k = 0 through 31.\n"
        "Increasing P by one raises the even entries by one and lowers the "
        "odd entries by one before encoding. For example, D=11 and P=-2 "
        "produce alternating levels 9 and 13. The FPGA uses signed low-7-bit codes.\n\n"
        "During ADC adjustment, feedbackPiCancel estimates an initial P as "
        "-round(sample / 2), refines it from subsequent residual measurements, "
        "then compares P, P+1 and P-1 by absolute residual. The selected integer "
        "is saved in this scalar state. Rounding of the initial estimate is "
        "to nearest with halfway cases away from zero."),
    "Adc_FineMergeGain": (
        "Combines the coarse feedback contribution with the change measured "
        "by the fine ADC. The fine contribution accounts for the change in "
        "the integrator residual between the paired samples. This coefficient "
        "aligns their internal scales.\n\n"
        "For saved coefficient g, firmware rounds g * 65536 to an integer; "
        "the FPGA uses its low 10 bits as G (0 through 1023). For the ordinary "
        "nonnegative input domain: G = floor(g * 65536 + 0.5) & 1023.\n"
        "Effective ratio k = G / 65536; one step in G changes k by 1 / 65536.\n\n"
        "In normal merge mode, without arithmetic overflow:\n"
        "delta_fine = previous_fine - current_fine\n"
        "M = 65536 * C_history + G * delta_fine\n"
        "M / 65536 = C_history + k * delta_fine.\n"
        "C_history is the saved feedback code paired with these fine samples, "
        "not the current raw coarse-ADC code. The FPGA uses registered history; "
        "operands must belong to the corresponding capture events.\n\n"
        "In a matched ideal charge model, k = q_fine / q_feedback, the ratio "
        "of charge represented by one fine-code step to one feedback-code step. "
        "Changing k changes the fine contribution at fixed operands.\n"
        "The ADC adjustment routine fineMergeGainTune2 selects this scalar "
        "using a minimum-spread criterion on processed calibration samples."),
    "Adc_FineSamplOffset": (
        "Moves the fine-ADC sampling request within the repeating decision cycle. "
        "Firmware combines this offset with the cycle length to calculate a "
        "wrapped trigger position. The ADC clock burst and data capture follow "
        "that request, so the stored value is not itself an analog sampling delay.\n\n"
        "Let N = trunc(N_Decisions), f = trunc(FineSamplOffset).\n"
        "Fine request position F = rem(f + N - 2, N).\n"
        "At nominal GCLK3 = 106.25 MHz, position F corresponds to F / 106.25 us "
        "from counter position 0. This is a request position, not the physical ADC aperture.\n"
        "trunc removes the fractional part toward zero; rem(a,N) = a - trunc(a/N)*N. "
        "For ordinary nonnegative numerators this is modulo N. Firmware transmits "
        "the low 7 bits of the result; unusual inputs need separate interpretation."),
    "Adc_Jitter": (
        "Selects a deterministic digital modulation pattern in the ADC feedback; "
        "the FPGA captures only the low three parameter bits. The generated "
        "addition depends on internal state and is already included in the "
        "feedback code.\n\n"
        "For an ordinary integer setting j, the effective parameter is p = j & 7. "
        "p=0 gives J=0; p=2 allows J values -2, -1, 0 and +1 depending on "
        "generator state. The sequence advances on the internal decision event. "
        "Its contribution is combined with the offset-table and coarse-table "
        "values before the feedback code is limited and saved for merge. "
        "Startup and retained generator state affect the sequence."),
    "Adc_LutGain": (
        "Sets the slope used to build the 256-entry coarse-ADC feedback table. "
        "Table entries are rounded and limited before use, so changing this "
        "value changes discrete feedback steps.\n\n"
        "For saved slope g and table index i = 0 through 255:\n"
        "gain[i] = clamp(round((i - 127.5) * g), -64, 63).\n"
        "round uses nearest-integer rounding with halfway cases away from zero; "
        "clamp limits the result to the stated endpoints. The read index is "
        "255 - coarse_code for the captured 8-bit coarse code. The selected "
        "entry contributes to the internal feedback calculation.\n\n"
        "During ADC adjustment, feedbackLutGainTune tries scalar candidates, "
        "applies the settings and measures the response, then writes the "
        "selected slope back to this CAL state. The 256 entries are generated "
        "from that slope."),
    "Adc_N_Decisions": (
        "Sets the number of FPGA timing-clock ticks in one repeating ADC "
        "decision cycle. At the nominal GCLK3 frequency of 106.25 MHz, each "
        "tick is about 9.411765 ns and the cycle duration is N / 106.25 us. "
        "Firmware forms the cycle-counter limit N-1 and uses "
        "N to position other events. N is not a count of complete decision "
        "cycles, output packets or displayed readings, and is not the NPLC aperture.\n\n"
        "N = trunc(N_Decisions); counter limit L = N - 1.\n"
        "Counter positions: 0 through L. Nominal cycle time T = N / 106.25 us.\n"
        "Nf_Slope positions the decision-window boundaries and coarse request; "
        "FineSamplOffset positions the fine request within this same cycle. "
        "trunc removes the fractional part toward zero. The timing field is 7 bits; "
        "the simple N-tick interpretation requires 1 <= N <= 128."),
    "Adc_Nf_Slope": (
        "Positions the start and end of the internal decision window and also "
        "affects the coarse-ADC sampling request. Firmware uses the integer "
        "half of this value together with the cycle length.\n\n"
        "For ordinary small settings, let N = trunc(N_Decisions), "
        "S = trunc(Nf_Slope), H = trunc(S / 2).\n"
        "Decision start = rem(N - H - 1, N).\n"
        "Decision end = rem(N + H - 1, N).\n"
        "Coarse request K = rem(N + min(H - 17, 0) - 4, N).\n"
        "At nominal GCLK3 = 106.25 MHz, a counter position p corresponds to "
        "p / 106.25 us from position 0. The window may cross the end of the cycle.\n"
        "trunc removes the fractional part toward zero; rem(a,N) = a - trunc(a/N)*N. "
        "These positions are not a coarse-to-fine sampling delay: that also depends "
        "on FineSamplOffset and the clock bursts following each request. "
        "Large or negative settings require the full signed firmware arithmetic "
        "and low-7-bit field handling."),
    "CapOffset": "Subtracts a terminal-selected capacitance offset.",
    "CurrentSrcDelay": "Sets a packet wait count in a compensated current-source path.",
    "Divider10M": "Corrects high-range resistance under a runtime guard.",
    "FreqGain": "Scales frequency counting and the related period calculation.",
    "HeaterGain": "Divides a heater-drive calculation.",
    "HeaterRes": "Contributes to a heater-drive calculation.",
    "McDelay": "MC is the input-signal measurement phase in the autozero (AZ) cycle. The phase name does not establish the time represented by this saved CAL value.",
    "MzDelay": "MZ is the internal-zero measurement phase in the autozero (AZ) cycle. The phase name does not establish the time represented by this saved CAL value.",
    "PrechargePwm": "Sets the precharge digital PWM control.",
    "flatness": "Shapes AC filter response as part of a complete tap vector.",
    "lp": "Shapes AC low-pass response as part of a complete tap vector.",
}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        result = float(value)
    except (OverflowError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _fmt(value: float) -> str:
    return f"{value:.8g}"


def _si(value: float, unit: str) -> str:
    if value == 0:
        return f"0 {unit}"
    exponent = 3 * math.floor(math.log10(abs(value)) / 3)
    if -12 <= exponent <= 12:
        prefix = dict(_PREFIXES)[exponent]
        return f"{_fmt(value / 10 ** exponent)} {prefix}{unit}"
    return f"{_fmt(value)} {unit}"


def _title(family: str, meaning: dict[str, Any]) -> str:
    name = str(meaning.get("nameBase") or family)
    if family in ("flatness", "lp"):
        index = meaning.get("elementIndex")
        part = f"tap {index}" if isinstance(index, int) and not isinstance(index, bool) else ""
        return f"{_LABELS[family]} — {name}" + (f", {part}" if part else "")
    tail = name[len(family):] if name.startswith(family) else ""
    rear = tail.endswith("Rear")
    if rear:
        tail = tail[:-4]
    if family in ('ResGain', 'ResOff', 'Res4Gain', 'Res4Off') and tail:
        compensated = tail.endswith('OC')
        range_name = tail[:-2] if compensated else tail
        ranges = {'100': '100 Ohm', '1K': '1 kOhm', '10K': '10 kOhm',
                  '100K': '100 kOhm', '1M': '1 MOhm', '10M': '10 MOhm',
                  '100M': '100 MOhm', '1G': '1 GOhm'}
        tail = ranges.get(range_name, range_name) + (' OC' if compensated else '')
    elif family in ("DcvGain", "DcvOff", "DciGain", "DciOff") and tail:
        if family.startswith("Dcv"):
            tail = {"0_1": "100 mV", "1_0": "1 V"}.get(tail, tail + " V")
        else:
            tail = {"1_0": "1 A", "3_0": "3 A", "1_0m": "1 mA"}.get(tail, tail.replace("u", " uA")
                                                         .replace("m", " mA"))
    else:
        tail = tail.replace("_", ".")
    suffix = meaning.get("displaySuffix")
    context = []
    if tail:
        context.append(tail)
    if suffix and family not in ("flatness", "lp"):
        context.append(str(suffix).lower())
    elif rear:
        context.append("rear")
    elif family in _OFFSET_UNITS:
        context.append("front")
    index = meaning.get("elementIndex")
    if isinstance(index, int) and not isinstance(index, bool):
        context.append(f"tap {index}")
    base = _LABELS.get(family, family.replace("Adc_", "ADC ").replace("_", " "))
    return base + (" — " + ", ".join(context) if context else "")


def _paired_gain_name(name: str, family: str) -> str | None:
    """Use only the verified exact name stem, including OC bank identity."""
    match = re.fullmatch(r"([A-Za-z0-9_]+?)(?:Rear|\[(?:FRONT|REAR)\])?", name)
    if not match or not match.group(1).startswith(family):
        return None
    return _OFFSET_GAIN[family] + match.group(1)[len(family):]


def build_display(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Return display cards in the original 1072-field order.

    A report without validated, exact field meanings retains raw-only cards.
    A checksum mismatch suppresses every derived numerical value.
    """
    if not isinstance(report, dict):
        return []
    schema = report.get("schema45", {})
    if not isinstance(schema, dict):
        return []
    rows = schema.get("values")
    meanings = schema.get("meanings")
    if not isinstance(rows, list):
        return []
    available = (report.get("version") == 45 and report.get("bodyLength") == 4924
                 and report.get("interpretation", {}).get("status") == "available"
                 and len(rows) == 1072 and isinstance(meanings, dict)
                 and all(isinstance(row, dict) and isinstance(row.get("meaning"), dict)
                         and row["meaning"].get("family") in meanings for row in rows))
    if not available:
        return [{"name": row.get("name", ""), "offset": row.get("offset"),
                 "title": str(row.get("name", "CAL value")),
                 "value": f"{row.get('value')!r} (stored)",
                 "description": "CAL field action unavailable for this schema or binding.",
                 "qualification": "Physical equivalent not established.", "derived": []}
                for row in rows if isinstance(row, dict)]
    intact = report.get("checksumValid") is True
    by_name = {row["name"]: row for row in rows}
    result: list[dict[str, Any]] = []
    for row in rows:
        meaning = row["meaning"]
        family = meaning["family"]
        raw = row.get("value")
        number = _number(raw)
        card: dict[str, Any] = {
            "name": row["name"], "offset": row["offset"],
            "title": _title(family, meaning),
            "value": f"{raw!r} (stored)",
            "description": _ACTIONS.get(family, "Adjusts an internal calibration path."),
            "qualification": ("Runtime CAL use is unresolved; physical equivalent not established."
                              if family in _OPEN_FAMILIES else
                              "Internal parameter; direct physical equivalent not established."),
            "derived": [],
        }
        if not intact:
            card["qualification"] = "Checksum mismatch; physical equivalent not established."
            result.append(card)
            continue
        if number is None:
            card["qualification"] = "Non-finite or invalid value; physical equivalent not established."
            result.append(card)
            continue
        if family.startswith("Adc_"):
            card["qualification"] = "ADC profile: " + row["name"].split("[")[-1].rstrip("]") + "."
        if family in _GAIN_UNITS:
            unit = _GAIN_UNITS[family]
            if family.startswith("Ac"):
                card["value"] = _si(number, unit) + " per internal RMS unit"
                card["qualification"] = "Internal RMS scale; final reading depends on its processing path."
                reference = _AC_REFERENCE_GAINS.get(row['name'])
                ratio = number / reference if reference is not None and reference > 0 else float('nan')
                if math.isfinite(ratio):
                    card['value'] = '×' + _fmt(ratio) + ' of APP 2.43 reference'
                    card['description'] = 'Compares the saved RMS gain with the firmware-defined reference for this range.'
                    card['qualification'] = 'Gain ratio only; not an accuracy estimate or a complete AC correction.'
                    card['derived'] = [
                        'Reference gain: ' + _si(reference, unit) + ' per internal RMS unit.',
                        'CAL gain: ' + _si(number, unit) + ' per internal RMS unit.',
                        'At fixed RMS input and noise terms, this scales the ordinary MED/FAST RMS stage before later corrections.',
                        'The reference is a fixed comparison baseline, not a calibration accuracy target.',
                    ]
                elif reference == 0:
                    card['qualification'] = 'Firmware reference is zero; a relative multiplier is undefined.'
            else:
                quantity = {"V": "Voltage", "A": "Current", "ohm": "Resistance"}[unit]
                card["value"] = _si(number, unit) + " per internal unit"
                card["description"] = f"Multiplies the internal result to obtain {quantity.lower()} in {unit}."
                card["derived"] = [
                    f"{quantity} [{unit}] = internal result × {_fmt(number)}",
                    "Internal result: offset-corrected accumulated ADC value divided by the measurement weight.",
                ]
                card["qualification"] = "Linear stage, before later corrections."
                reference = _DCI_REFERENCE_GAINS.get(row["name"]) if family == "DciGain" else None
                if family == "DcvGain":
                    reference = _DCV_REFERENCE_GAINS.get(row["name"])
                elif family in ("ResGain", "Res4Gain"):
                    reference = _RES_REFERENCE_GAINS.get(row["name"])
                ratio = number / reference if reference is not None else float("nan")
                if math.isfinite(ratio):
                    card["value"] = "×" + _fmt(ratio) + " of firmware default"
                    card["description"] = f"Multiply the {quantity.lower()} calculated with the reference gain by this factor, keeping the same offset."
                    card["qualification"] = "Reference: APP11 2.43 initial gain; not an accuracy estimate."
                    if family == "DcvGain":
                        card["description"] = "Multiply the linear-stage voltage calculated with the reference gain by this factor, keeping the same offset."
                        if row["name"] == "DcvGain10":
                            card["qualification"] += " Applied before the 10 V quadratic correction."
                    card["derived"] = [
                        f"{quantity} = reference-scale {quantity.lower()} × " + _fmt(ratio),
                        "Reference gain: " + _si(reference, unit) + " per internal unit.",
                        "CAL gain: " + _si(number, unit) + " per internal unit.",
                        *card["derived"],
                    ]
                    if family == "DcvGain":
                        card["derived"][0] = "Linear-stage voltage = reference-scale voltage × " + _fmt(ratio)
                    elif family in ("ResGain", "Res4Gain"):
                        card["description"] = "Multiply the signed linear-stage resistance calculated with the matching reference gain by this factor, keeping the same offset."
                        card["qualification"] += " Applied before absolute value."
                        if row["name"][len(family):] in ("100M", "1G"):
                            card["qualification"] += " Also before nonlinear divider correction."
                        card["derived"][0] = "Signed linear-stage resistance = reference-scale resistance × " + _fmt(ratio)
                        card["derived"].append("Reference matches this range, 2-wire/4-wire mode and OC setting.")
        elif family in ("AcvSqNoise", "AciSqNoise"):
            gain_family = "AcvGain" if family == "AcvSqNoise" else "AciGain"
            gain_name = gain_family + row["name"][len(family):]
            gain_row = by_name.get(gain_name)
            gain = _number(gain_row.get("value")) if gain_row else None
            unit = "V" if family == "AcvSqNoise" else "A"
            card["value"] = _fmt(number) + " internal squared-RMS units"
            if gain is not None:
                power = gain * gain * number
                if math.isfinite(power):
                    card["value"] = _fmt(power) + f" {unit}² equivalent"
                    card["derived"] = ["Equivalent squared output term: " + _fmt(power) + f" {unit}²"]
                    if number >= 0:
                        rms = abs(gain) * math.sqrt(number)
                        if math.isfinite(rms):
                            card["value"] = _si(rms, unit) + ' RMS equivalent'
                            card["derived"].append("Equivalent RMS term: " + _si(rms, unit))
                    card["qualification"] = ("Ordinary MED/FAST pre-rolldown path; "
                                             "derived term is not measured noise or a fixed reading subtraction.")
        elif family in _OFFSET_UNITS:
            gain_name = _paired_gain_name(row["name"], family)
            gain = by_name.get(gain_name or "")
            gain_number = _number(gain.get("value")) if gain else None
            equivalent = -number * gain_number if gain_number is not None else float("nan")
            if math.isfinite(equivalent):
                card["value"] = "about " + _si(equivalent, _OFFSET_UNITS[family])
                card["derived"] = ["Approximate linear-stage equivalent: -offset × paired gain."]
                card["qualification"] = ("Before packet-weight rounding, absolute value or other "
                                         "nonlinear corrections; not the final reading offset.")
        elif family == "FreqGain":
            card["value"] = "×" + f"{number:.12g}"
            card["derived"] = [f"{_fmt((number - 1) * 1e6)} ppm relative to 1"]
            if number > 0:
                card["derived"].append("Period multiplier: ×" + f"{1 / number:.12g}")
            card["qualification"] = "At fixed valid counter values; period uses the reciprocal."
        elif family == "Divider10M":
            card["value"] = _si(number, "ohm")
            card["qualification"] = "Resistance dimension derived from the guarded high-range formula."
        elif family == 'HeaterGain' and number > 0:
            ratio = 1.33 / number
            if math.isfinite(ratio):
                card['value'] = '×' + _fmt(ratio) + ' of default heater drive'
                card['description'] = 'Scales the heater command inversely: increasing HeaterGain reduces the calculated drive.'
                card['qualification'] = 'APP11 2.43 reference; fixed HeaterRes and positive target power, before rounding and limits.'
                card['derived'] = [
                    'Relative drive = 1.33 / stored HeaterGain; stored value: ' + _fmt(number),
                    'Drive calculation: 77.272727… × sqrt(HeaterRes × target power) / HeaterGain.',
                    'DCV heat compensation reduces target power when |voltage| >= 300 V; this is not a voltage-reading gain.',
                ]
        elif family == "CapOffset":
            card["value"] = _si(number, "F")
            card["description"] = "Subtracts this capacitance offset from the computed capacitance for the selected terminals."
            card["derived"] = ["Reading contribution: " + _si(-number, "F")]
            card["qualification"] = "Stored in farads; this is a calibration offset, not a measured external capacitance."
        elif family == "CurrentSrcDelay" and 0 <= number <= 2147483647 and number.is_integer():
            # APP11 RES computeSampTimeMin uses this initialized binary64
            # seconds/count scale, including the current-source wait count.
            # Evidence: research/cal_mc_mz_time_scale_20261008/evidence.json.
            nominal_ms = number * float.fromhex('0x1.4ec13ad4f4c62p-16') * 1000
            card["value"] = f"{int(number)} DC packets (~{nominal_ms:.3g} ms nominal)"
            card["description"] = "Sets a minimum settling wait after switching the current source in the compensated resistance path. Packets are short internal records before NPLC accumulation."
            card["qualification"] = "Nominal APP11 software timing; other timing settings can extend the wait."
            card["derived"] = [
                "Time estimate for this CAL count: packets x 19.952941176 us, using the APP11 sample-time calculation scale.",
                "This is one wait's nominal span, not the complete autozero cycle or a measured hardware duration.",
            ]
        elif family in ("McDelay", "MzDelay") and 0 <= number <= 2147483647 and number.is_integer():
            # Hypothesis only: this scale belongs to working counters;
            # the numeric link from these saved CAL fields is unresolved.
            estimated_ms = number * float.fromhex('0x1.4ec13ad4f4c62p-16') * 1000
            card["qualification"] = "Runtime CAL use is unresolved; the time estimate below is hypothetical, not confirmed."
            card["derived"] = [
                f"Hypothetical duration: {estimated_ms:.6f} ms, if this stored value counts steps of 19.952941176 us.",
                "This step duration is established for APP11 2.43 working delay counters; its application to this CAL field has not been confirmed.",
                "The estimate does not establish the actual measurement delay or the complete autozero cycle time.",
            ]
        elif family == "AdcQuad":
            card["value"] = _fmt(number) + " 1/V"
            card["qualification"] = "Checked DCV 10 V quadratic path: correction q × linear reading²."
        elif family == "AcvSlowNoiseGainSquared":
            multiplier = 1 + number
            if math.isfinite(multiplier):
                card["value"] = "×" + _fmt(multiplier) + " noise term"
                card["qualification"] = "SLOW noise term only; not a whole-reading multiplier."
        elif family == "PrechargePwm" and 0 <= number <= 255:
            digital = math.floor(number + 0.5)
            card["value"] = _fmt((digital + 1) * 100 / 256) + "% low duty"
            card["qualification"] = "Conditional stable enabled E127/A1 ordinary PWM profile."
        elif family == "Adc_N_Decisions" and number.is_integer() and 1 <= number <= 128:
            # N-1 fits the seven-bit cycle field without wrapping. This is
            # timing arithmetic, not validation of the entire ADC profile.
            card["value"] = _fmt(number / 106.25) + " us nominal cycle"
            card["qualification"] = "At nominal FPGA GCLK3 = 106.25 MHz; not the NPLC aperture."
            card["derived"] = [
                f"{int(number)} FPGA clock ticks per decision cycle; "
                f"{int(number)} / 106.25 = {_fmt(number / 106.25)} us.",
                "Calculated for this saved setting; does not confirm an active or valid ADC profile.",
            ]
        elif family in ("Adc_Nf_Slope", "Adc_FineSamplOffset"):
            card["qualification"] = "Digital timing setting; nominal FPGA GCLK3 = 106.25 MHz."
            peer = by_name.get(row["name"].replace(family, "Adc_N_Decisions", 1), {})
            n = _number(peer.get("value"))
            # Only project exact small integers with nonnegative numerators.
            # Outside this domain do not substitute Python modulo for PPC rem.
            if n is not None and n.is_integer() and 1 <= n <= 128 and number.is_integer() and 0 <= number <= 127:
                n, setting = int(n), int(number)
                if family == "Adc_FineSamplOffset":
                    positions = [("Fine request F", setting + n - 2)]
                    inputs = f"N = {n}, f = {setting}."
                else:
                    half = setting // 2
                    positions = [("Decision start", n - half - 1),
                                 ("Decision end", n + half - 1),
                                 ("Coarse request K", n + min(half - 17, 0) - 4)]
                    inputs = f"N = {n}, S = {setting}, H = {half}."
                if all(numerator >= 0 for _, numerator in positions):
                    card["derived"] = ["Calculated from this CAL profile: " + inputs]
                    for label, numerator in positions:
                        position = numerator % n
                        card["derived"].append(
                            f"{label} = rem({numerator}, {n}) = {position}; "
                            f"nominal position {_fmt(position / 106.25)} us from counter 0.")
                    card["derived"].append("Counter positions only; not measured analog delays or confirmation of an active ADC profile.")
        elif family == "Adc_FineMergeGain" and 0 <= number < 1 / 64:
            rounded = math.floor(number * 65536 + 0.5)
            gain = rounded & 1023
            effective = gain / 65536
            card["value"] = "×" + _fmt(effective) + " fine/feedback code ratio"
            card["derived"] = [
                f"For this CAL value: rounded g * 65536 = {rounded}; G = {gain}.",
                f"Effective k = {gain} / 65536 = {effective:.15g}.",
                f"At fixed C_history, delta_fine = +1 adds {effective:.15g} "
                "feedback-code units to M / 65536; delta_fine = -1 subtracts the same amount.",
            ]
            card["qualification"] = "Effective internal ratio after quantization; formulas describe normal merge mode."
        elif family in ('AcvMedIirDenomCoef', 'AcvSlowIirDenomCoef'):
            card['value'] = _fmt(number) + ' filter feedback factor'
            card['qualification'] = 'Dimensionless filter coefficient; not a whole-reading multiplier.'
            if 0 <= number < 1:
                effective = math.trunc(number * 2**20 + .5) / 2**20
                card['derived'] = ['Effective factor after firmware quantization: ' + _fmt(effective)]
        elif family in ('flatness', 'lp'):
            card['qualification'] = 'No standalone physical unit; see Filter curves for the complete vector.'
        result.append(card)
    return result
