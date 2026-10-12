"""CAL backup names and filename-based target checks; no instrument writes."""
from __future__ import annotations
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re

from .offline import parse_cal_payload


def read_operating_hours(instrument) -> dict:
    """Optional last query in a backup session; failure never invalidates CAL bytes."""
    command = 'DIAG:PEEK:FIRMWARE? 24,0,0'
    result = {'status': 'unavailable', 'operatingHours': None, 'command': command,
              'readAtUtc': datetime.now(timezone.utc).isoformat(), 'rawResponse': None,
              'semantics': 'Accumulated instrument operating time, reported by firmware in hours.'}
    try:
        reply = instrument.query_text(command)
        if not isinstance(reply, str):
            raise ValueError('Runtime reply is not text.')
        result['rawResponse'] = reply
        match = re.fullmatch(r'\s*Elapsed Time Hours:\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*', reply)
        if not match:
            raise ValueError('Unexpected elapsed-runtime response.')
        hours = float(match[1])
        if not math.isfinite(hours) or hours < 0:
            raise ValueError('Elapsed runtime must be finite and non-negative.')
        result.update(status='available', operatingHours=hours)
    except Exception as exc:
        result['error'] = str(exc)
    return result

_NAME = re.compile(r'(?P<serial>[A-Za-z0-9-]+)_CAL_(?P<stamp>\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}-\d{6}Z)\.bin', re.I)


def backup_filename(serial: str, saved_at: datetime) -> str:
    if not isinstance(serial, str) or not re.fullmatch(r'[A-Za-z0-9-]+', serial):
        raise ValueError('Instrument serial is missing or cannot be used in a CAL filename.')
    if saved_at.tzinfo is None or saved_at.utcoffset() is None:
        raise ValueError('Save time must include a timezone.')
    stamp = saved_at.astimezone(timezone.utc).strftime('%Y-%m-%d_%H-%M-%S-%fZ')
    return f'{serial}_CAL_{stamp}.bin'


def filename_serial(path: str | Path) -> str | None:
    match = _NAME.fullmatch(Path(path).name)
    if not match:
        return None
    try:
        datetime.strptime(match['stamp'], '%Y-%m-%d_%H-%M-%S-%fZ')
    except ValueError:
        return None
    return match['serial']


def check_restore_target(path: str | Path, instrument_serial: str) -> dict:
    """Prepare the serial confirmation gate for the future restore workflow.

    Filename matching is not authenticity validation or permission to write.
    The caller must obtain fresh identity and explicit confirmation when required.
    """
    if not isinstance(instrument_serial, str) or not instrument_serial.strip():
        raise ValueError('Read the instrument serial before checking the CAL file.')
    target = instrument_serial.strip()
    source = filename_serial(path)
    if source is not None and source == target:
        return {'status': 'match', 'requiresConfirmation': False, 'message': '',
                'fileSerial': source, 'instrumentSerial': target}
    if source is None:
        message = (f'The CAL filename does not contain a recognized serial number.\n'
                   f'Connected instrument: {target}\n\n'
                   'The file may belong to a different instrument. Are you sure you want to continue?')
        status = 'unknown'
    else:
        message = (f'The CAL file belongs to serial {source}.\n'
                   f'Connected instrument: {target}\n\n'
                   'The serial numbers do not match. Are you sure you want to continue?')
        status = 'mismatch'
    return {'status': status, 'requiresConfirmation': True, 'message': message,
            'fileSerial': source, 'instrumentSerial': target}


def save_cal_backup(folder: Path, payload: bytes, identity: dict, *,
                    saved_at: datetime | None = None, explicit_path: Path | None = None,
                    operating_time: dict | None = None) -> dict:
    """Write unchanged logical payload and identity-bearing JSON without overwrite."""
    report = parse_cal_payload(payload)
    if not report['checksumValid']:
        raise ValueError('CAL checksum mismatch; backup was not saved.')
    saved_at = saved_at or datetime.now(timezone.utc)
    name = backup_filename(identity.get('serial'), saved_at)
    path = Path(explicit_path) if explicit_path is not None else Path(folder) / name
    sidecar = path.with_suffix(path.suffix + '.json')
    if path.exists() or sidecar.exists():
        raise FileExistsError(f'CAL backup already exists: {path}')
    report['backup'] = {'identity': dict(identity), 'savedAtUtc': saved_at.astimezone(timezone.utc).isoformat(),
                        'file': path.name, 'naming': 'serial_CAL_UTC-date-time.bin',
                        'filenameSerial': filename_serial(path)}
    if operating_time is not None:
        report['backup']['operatingTime'] = operating_time
    # Keep the binary payload identical to CAL:DATA:ALL? for existing readers.
    with path.open('xb') as stream:
        stream.write(payload)
        stream.flush(); os.fsync(stream.fileno())
    with sidecar.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        stream.flush(); os.fsync(stream.fileno())
    return {'file': str(path), 'metadataFile': str(sidecar), 'report': report}
