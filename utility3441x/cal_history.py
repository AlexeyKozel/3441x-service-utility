"""Read-only CAL journal catalog and byte-exact coefficient comparison."""
from __future__ import annotations

import math
import struct

from .offline import detect_nor_order, parse_cal_payload, sha256
from .cal_display import build_display

REGION_OFFSET = 0x5C0000
SLOT_SIZE = 0x2000
SLOT_COUNT = 32
_STATES = {0xA5: "Current", 0xA0: "Fallback", 0xF5: "Incomplete", 0: "Historical (retired)"}


def scan_cal_history(raw: bytes, *, source: str = "<memory>") -> dict:
    """Accept a complete NOR dump; never infer journal order from CAL payloads."""
    cpu, order = detect_nor_order(raw)
    result = scan_cal_region(cpu[REGION_OFFSET:REGION_OFFSET + SLOT_SIZE * SLOT_COUNT])
    result.update(source=source, inputOrder=order, sha256Input=sha256(raw),
                  sha256CPUOrder=sha256(cpu))
    return result


def scan_cal_region(region: bytes) -> dict:
    """Parse an explicitly CPU-order 256 KiB journal, mainly for bounded tests."""
    if len(region) != SLOT_SIZE * SLOT_COUNT:
        raise ValueError("CAL journal must contain exactly 32 slots of 8192 bytes")
    slots = []
    seen = {}
    for index in range(SLOT_COUNT):
        data = region[index * SLOT_SIZE:(index + 1) * SLOT_SIZE]
        state, version, size, length, check = struct.unpack_from(">HHIII", data)
        slot = dict(id=f"{'A' if index < 16 else 'B'}{index % 16}", index=index,
                    norOffset=REGION_OFFSET + index * SLOT_SIZE, state=f"0x{state:04X}",
                    status=_STATES.get(state, "Unknown"), version=version,
                    bodyLength=length, imageSize=size, checksumValid=None,
                    bodySha256=None, duplicateOf=None, comparable=False,
                    report=None, bodyHex=None, recordValid=False)
        if data == b'\xff' * SLOT_SIZE:
            slot.update(status="Empty", version=None, bodyLength=None, imageSize=None)
        elif state == 0xFFFF:
            slot.update(status="Incomplete", issue="Erased state with non-erased bytes")
        elif not 8 <= size <= SLOT_SIZE - 8 or length > size - 8:
            slot.update(status="Invalid", issue="Invalid record length or slot boundary")
        else:
            body = data[16:16 + length]
            calculated = (~sum(body)) & 0xFFFFFFFF
            valid = check == calculated
            slot.update(checksumValid=valid, checksumStored=check,
                        checksumCalculated=calculated, bodySha256=sha256(body),
                        bodyHex=body.hex(), recordValid=valid)
            if not valid:
                slot.update(status="Invalid", issue="Checksum mismatch")
            elif state in (0, 0xA0, 0xA5):
                key = (version, length, slot['bodySha256'])
                slot['duplicateOf'] = seen.get(key)
                seen.setdefault(key, slot['id'])
                if version == 45 and length == 4924:
                    payload = struct.pack('>HII', version, length, check) + body
                    slot.update(report=parse_cal_payload(payload, explain=True), comparable=True)
                else:
                    slot['issue'] = "Unsupported CAL schema; coefficient interpretation unavailable"
        slots.append(slot)
    # A marker alone is not proof of firmware boot selection or live RAM CAL.
    marked = [s for s in slots if s['state'] == '0x00A5']
    current = marked[0]['id'] if len(marked) == 1 and marked[0]['recordValid'] else None
    old = [s for s in slots if s['state'] == '0x00A0']
    fallback = old[0]['id'] if not marked and len(old) == 1 and old[0]['recordValid'] else None
    note = (f"Current marker in this dump: {current}; not a live CAL read."
            if current else "No unique intact current marker; current selection is unresolved.")
    if fallback:
        note += f" Intact fallback marker: {fallback}."
    return dict(source="<region>", inputOrder="cpu", slots=slots, currentSlot=current, fallbackSlot=fallback,
                selectionNote=note + " Slot order is physical, not a dated calibration history.")


def compare_slots(reference: dict, selected: dict) -> list[dict]:
    """Compare schema45 bytes, including signed zero and NaN representations."""
    if not reference.get('comparable') or not selected.get('comparable'):
        raise ValueError("Comparison requires two intact, supported CAL records")
    left = reference['report']['schema45']['values']
    right = selected['report']['schema45']['values']
    a, b = bytes.fromhex(reference['bodyHex']), bytes.fromhex(selected['bodyHex'])
    if len(a) != 4924 or len(b) != 4924 or len(left) != 1072 or len(right) != 1072:
        raise ValueError("Invalid schema45 comparison span")
    displays_a, displays_b = build_display(reference['report']), build_display(selected['report'])
    rows = []
    for x, y, da, db in zip(left, right, displays_a, displays_b):
        if any(x[k] != y[k] for k in ('name', 'offset', 'type')):
            raise ValueError("CAL field identity mismatch")
        offset = x['offset']
        width = 8 if x['type'] == 'double' else 4
        changed = a[offset:offset + width] != b[offset:offset + width]
        delta = '0'
        if changed:
            vx, vy = x['value'], y['value']
            if math.isfinite(vx) and math.isfinite(vy):
                difference = vy - vx
                delta = format(difference, '.8g') if math.isfinite(difference) else 'Not finite'
                if difference == 0:
                    delta = 'Bytes differ (e.g. signed zero)'
            else:
                delta = 'Non-finite; bytes differ'
        rows.append(dict(name=x['name'], title=da['title'], offset=offset, type=x['type'],
                         reference=da['value'], selected=db['value'], delta=delta,
                         changed=changed, referenceRaw=repr(x['value']), selectedRaw=repr(y['value']),
                         referenceHex=a[offset:offset+width].hex(), selectedHex=b[offset:offset+width].hex()))
    return rows
