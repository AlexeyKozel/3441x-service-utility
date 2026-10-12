"""Read and preserve the complete CAL journal; no instrument writes."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from .cal_files import backup_filename, read_operating_hours
from .cal_history import REGION_OFFSET, REGION_SIZE, SLOT_SIZE, SLOT_COUNT
from .offline import NOR_BASE, sha256


def backup_cal_journal(instrument, folder: Path, *, progress=None, saved_at=None) -> dict:
    identity = instrument.identity()
    saved_at = saved_at or datetime.now(timezone.utc)
    name = backup_filename(identity.get('serial'), saved_at).replace('_CAL_', '_CAL_HISTORY_', 1)
    path = Path(folder) / name
    sidecar = path.with_suffix('.bin.json')
    if path.exists() or sidecar.exists():
        raise FileExistsError(f'CAL journal backup already exists: {path}')
    raw = instrument.read_memory(NOR_BASE + REGION_OFFSET, REGION_SIZE, progress=progress)
    if len(raw) != REGION_SIZE:
        raise RuntimeError('Short CAL journal read; backup was not saved.')
    if instrument.identity() != identity:
        raise RuntimeError('Instrument identity changed during CAL journal read; backup was not saved.')
    operating_time = read_operating_hours(instrument)
    metadata = dict(format='3441x-cal-journal-v1', identity=identity,
                    savedAtUtc=saved_at.astimezone(timezone.utc).isoformat(),
                    file=path.name, size=len(raw), sha256=sha256(raw), byteOrder='cpu',
                    norOffset=REGION_OFFSET, slotSize=SLOT_SIZE, slotCount=SLOT_COUNT,
                    operatingTime=operating_time,
                    note='Sequential NOR read; atomic snapshot is not guaranteed. Do not operate the instrument while the CAL journal backup is in progress.')
    # Retain every byte, including empty, incomplete and invalid slots.
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush(); os.fsync(stream.fileno())
    with sidecar.open('x', encoding='utf-8') as stream:
        json.dump(metadata, stream, indent=2)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    return dict(file=str(path), metadataFile=str(sidecar), report=metadata)
