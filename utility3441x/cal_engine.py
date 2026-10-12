"""Shared, UI-independent CAL snapshot, comparison and scalar calculations."""
from __future__ import annotations
from dataclasses import dataclass
import math
from typing import Any
from .cal_display import build_display


@dataclass(frozen=True)
class CalSnapshot:
    """Decoded CAL view shared by inspect, journal slots and saved snapshots.

    Does not certify calibration values. Inspection may show unverified reports;
    comparison eligibility remains explicit at the source adapter boundary.
    """
    report: dict
    body_hex: str | None = None

    @property
    def rows(self):
        return self.report.get('schema45', {}).get('values', [])

    @property
    def meanings(self):
        return self.report.get('schema45', {}).get('meanings', {})

    @property
    def display(self):
        return build_display(self.report)

    def as_record(self):
        return {'report': self.report, 'bodyHex': self.body_hex,
                'comparable': bool(self.report.get('checksumValid') and
                    self.report.get('version') == 45 and self.body_hex is not None)}

    @classmethod
    def from_record(cls, record):
        return cls(record['report'], record.get('bodyHex'))


def scalar_change(reference, selected, mode):
    """Established ohm difference or relative ppm; undefined results return None."""
    a, b = _finite_number(reference), _finite_number(selected)
    if a is None or b is None or mode not in ('ohm_delta', 'ppm'):
        return None
    if mode == 'ppm' and a == 0:
        return None
    result = b - a if mode == 'ohm_delta' else (b - a) / a * 1_000_000
    return result if math.isfinite(result) else None


_SCALE_FAMILIES = {'DcvGain', 'DciGain', 'ResGain', 'Res4Gain', 'AcvGain', 'AciGain', 'FreqGain'}


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return number if math.isfinite(number) else None


def coefficient_choices(history: dict) -> list[dict[str, str]]:
    """Return interpreted scale/gain fields and Divider10M from a valid report."""
    source = next((slot for slot in history.get('slots', [])
                   if slot.get('comparable') and isinstance(slot.get('report'), dict)), None)
    if source is None:
        return []
    rows = CalSnapshot.from_record(source).rows
    cards = CalSnapshot.from_record(source).display
    choices = []
    for row, card in zip(rows, cards):
        name = row.get('name')
        title = card.get('title') or name
        family = row.get('meaning', {}).get('family', '')
        if not isinstance(name, str) or row.get('type') not in ('double', 'int32'):
            continue
        if family != 'Divider10M' and family not in _SCALE_FAMILIES:
            continue
        choices.append({'name': name, 'title': title,
                        'label': f'{title} [{name}]',
                        'mode': 'ohm_delta' if family == 'Divider10M' else 'ppm'})
    return choices


def compare_snapshots(reference: dict, selected: dict) -> list[dict]:
    """Compare schema45 bytes, including signed zero and NaN representations."""
    if not reference.get('comparable') or not selected.get('comparable'):
        raise ValueError("Comparison requires two intact, supported CAL records")
    a_snapshot = CalSnapshot.from_record(reference)
    b_snapshot = CalSnapshot.from_record(selected)
    left = a_snapshot.rows
    right = b_snapshot.rows
    a, b = bytes.fromhex(reference['bodyHex']), bytes.fromhex(selected['bodyHex'])
    if len(a) != 4924 or len(b) != 4924 or len(left) != 1072 or len(right) != 1072:
        raise ValueError("Invalid schema45 comparison span")
    displays_a, displays_b = a_snapshot.display, b_snapshot.display
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


def comparison_rows(reference, selected):
    """Comparison rows with shared human-readable changes for table and export."""
    rows = compare_snapshots(reference, selected)
    choices = {c['name']: c for c in coefficient_choices({'slots': [reference]})}
    a = CalSnapshot.from_record(reference).rows
    b = CalSnapshot.from_record(selected).rows
    for index, row in enumerate(rows):
        change = row['delta'] + ' (stored units)'
        choice = choices.get(row['name'])
        if choice:
            av, bv = a[index]['value'], b[index]['value']
            if _finite_number(av) is not None and _finite_number(bv) is not None:
                mode = choice['mode']
                delta = scalar_change(av, bv, mode)
                if delta is not None:
                    change = f"{delta:+.8g} " + ('ohm' if mode == 'ohm_delta' else 'ppm')
                elif mode == 'ppm' and av == 0:
                    change = 'ppm unavailable (A = 0)'
                else:
                    change = 'Not finite'
        row['interpretedDelta'] = change
    return rows
