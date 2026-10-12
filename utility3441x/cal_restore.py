"""Explicit, staged schema45 CAL restore for the studied APP11 2.43 path.

No automatic retry, rollback, unlock, or reboot. Hardware qualification is separate.
"""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
import struct

from .cal_files import check_restore_target, save_cal_backup
from .cal_history import REGION_OFFSET, SLOT_SIZE, SLOT_COUNT
from .offline import parse_cal_payload, NOR_BASE


def validate_restore_payload(payload: bytes) -> dict:
    if len(payload) != 4934:
        raise ValueError('Restore requires a 4934-byte schema45 CAL payload, not a NOR dump or raw body.')
    report = parse_cal_payload(payload)
    if report['version'] != 45 or report['bodyLength'] != 4924 or not report['checksumValid']:
        raise ValueError('Restore requires schema45 with an exact length and valid checksum.')
    values = report['schema45']['values']
    if len(values) != 1072 or any(not math.isfinite(row['value']) for row in values):
        raise ValueError('Restore requires 1072 finite CAL values.')
    return report


def cal_write_frame(payload: bytes) -> bytes:
    validate_restore_payload(payload)
    return b'CAL:DATA:ALL #44934' + payload + b'\n'


def _identity(instrument) -> dict:
    identity = instrument.identity()
    if (identity.get('model') != '34411A' or identity.get('firmware', '').split('-')[0] != '2.43'
            or not identity.get('serial')):
        raise ValueError('CAL restore currently supports only 34411A APP 2.43 with a readable serial number.')
    return identity


def _ready(instrument):
    error = instrument.query_text('SYST:ERR?').strip()
    try:
        code = int(error.split(',', 1)[0])
    except ValueError as exc:
        raise RuntimeError(f'Unexpected error-queue reply: {error!r}') from exc
    if code:
        raise RuntimeError(f'Instrument reports an error: {error}. No automatic clear or retry.')
    security = instrument.query_text('CAL:SEC:STAT?').strip()
    if security not in ('0', '+0'):
        raise RuntimeError('Calibration is secured or its security state is unknown. Unlock it separately before restoring.')


def _complete(instrument):
    if instrument.query_text('*OPC?').strip() not in ('1', '+1'):
        raise RuntimeError('Operation completion was not acknowledged.')
    error = instrument.query_text('SYST:ERR?').strip()
    try:
        code = int(error.split(',', 1)[0])
    except ValueError as exc:
        raise RuntimeError(f'Unexpected error reply: {error!r}') from exc
    if code:
        raise RuntimeError(f'Instrument reports an error: {error}')


def verify_saved_cal(instrument, payload: bytes) -> dict:
    """Read journal headers and the unique current body, without a reboot."""
    current = []
    for i in range(SLOT_COUNT):
        address = NOR_BASE + REGION_OFFSET + SLOT_SIZE * i
        raw = instrument.read_memory(address, 16)
        if len(raw) != 16:
            raise RuntimeError('Short CAL journal header read.')
        state, version, size, length, checksum = struct.unpack('>HHIII', raw)
        if state == 0xA5:
            current.append((i, address, version, size, length, checksum))
    if len(current) != 1:
        raise RuntimeError('NOR has no unique current CAL slot; persistent result is unresolved.')
    i, address, version, size, length, checksum = current[0]
    if version != 45 or length != 4924 or not length+8 <= size <= SLOT_SIZE-8:
        raise RuntimeError('Current NOR CAL record has an unexpected schema or length.')
    body = instrument.read_memory(address+16, length)
    saved = struct.pack('>HII',version,length,checksum)+body
    validate_restore_payload(saved)
    if saved != payload:
        raise RuntimeError('Current NOR CAL does not match the requested payload.')
    return {'slot': f"{'A' if i < 16 else 'B'}{i % 16}", 'sha256': hashlib.sha256(saved).hexdigest()}


def restore_calibration(instrument, payload: bytes, source_path: Path, backup_folder: Path,
                        confirm, status=lambda text: None) -> dict:
    """Confirm callbacks run through the GUI's main-thread dialog queue."""
    target = validate_restore_payload(payload)
    identity = _identity(instrument)
    gate = check_restore_target(source_path, identity['serial'])
    if gate['requiresConfirmation'] and not confirm('CAL serial number', gate['message']):
        return {'status':'cancelled', 'written':False}
    _ready(instrument)
    status('Reading and saving current CAL before restore')
    before, _ = instrument.read_calibration()
    before_report = validate_restore_payload(before)
    backup = save_cal_backup(Path(backup_folder), before, identity)
    journal_path = Path(backup['file'] + '.restore.json')
    journal = {'status':'backup_saved', 'identity':identity, 'source':str(source_path),
               'targetSha256':target['sha256'], 'beforeSha256':before_report['sha256'],
               'backupFile':backup['file'], 'serialCheck':gate, 'importAttempted':False,
               'storeAttempted':False}

    def record(state):
        journal['status'] = state
        with journal_path.open('w',encoding='utf-8') as stream:
            json.dump(journal,stream,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())

    record('backup_saved')
    needs_import = before != payload
    if not needs_import:
        try:
            journal['savedRecord'] = verify_saved_cal(instrument,payload)
        except RuntimeError:
            # Same RAM data may still need a commit (for example, after declining
            # the previous NOR confirmation). Do not silently suppress that step.
            pass
        else:
            record('already_saved')
            return {**journal, 'journal':str(journal_path),
                    'note':'Working CAL and current NOR already match. No import or CAL:STORE was performed.'}
    changed = sum(a != b for a,b in zip(before[10:],payload[10:]))
    message = (f"Instrument: {identity['model']} / {identity['serial']} / APP 2.43\n"
               f"File: {Path(source_path).name}\nChanged body bytes: {changed}\n"
               f"Backup: {backup['file']}\n\n"
               'Load this CAL into working memory? A separate confirmation follows before saving to NOR.\n'
               'This workflow is offline-tested; live hardware qualification is pending.')
    if needs_import and not confirm('Restore working CAL',message):
        record('cancelled');return {**journal,'journal':str(journal_path)}
    try:
        if _identity(instrument) != identity:
            raise RuntimeError('Instrument identity changed during confirmation.')
        _ready(instrument)
        fresh, _ = instrument.read_calibration()
        if fresh != before:
            raise RuntimeError('Working CAL changed during confirmation. Start again with a fresh backup.')
        if needs_import:
            status('Loading working CAL — no automatic retry')
            journal['importAttempted'] = True; record('import_attempted')
            instrument.write_calibration(payload)
            _complete(instrument)
        readback, _ = instrument.read_calibration()
        if readback != payload:
            raise RuntimeError('Working CAL readback differs. NOR commit was not attempted.')
        record('working_verified')
        if not confirm('Save CAL to NOR',
                       'Working CAL matches the file byte for byte.\n\n'
                       'Save it permanently with CAL:STORE? This increments the calibration count.\n'
                       'Choose No to leave the imported working CAL without a NOR commit. No automatic rollback is performed.'):
            record('working_only')
            return {**journal,'journal':str(journal_path),
                    'warning':'Imported CAL remains in working state; CAL:STORE was not sent. Power-cycle persistence is not claimed.'}
        if _identity(instrument) != identity:
            raise RuntimeError('Instrument identity changed before saving.')
        _ready(instrument)
        fresh, _ = instrument.read_calibration()
        if fresh != payload:
            raise RuntimeError('Working CAL changed before saving. CAL:STORE was not sent.')
        journal['storeAttempted'] = True; record('store_attempted')
        status('Saving CAL to NOR — do not interrupt power')
        instrument.write_text('CAL:STORE')
        _complete(instrument)
        record('store_acknowledged')
        status('Verifying saved CAL in NOR')
        journal['savedRecord'] = verify_saved_cal(instrument,payload)
        readback, _ = instrument.read_calibration()
        if readback != payload:
            raise RuntimeError('Working CAL differs after NOR save.')
        record('saved_and_verified')
        return {**journal,'journal':str(journal_path),
                'note':'Working CAL and the unique current NOR record match. No reboot was performed; activation in every measurement object was not verified.'}
    except Exception as exc:
        journal['error'] = str(exc)
        phase = journal['status']
        try: record('stopped_with_error')
        except OSError: pass
        raise RuntimeError(f'CAL restore stopped at {phase}: {exc}\n'
                           f'Backup: {backup["file"]}\nJournal: {journal_path}\n'
                           'No retry or automatic rollback was performed. '
                           'If an import/store was attempted, its effects may be partial or uncertain.') from exc
