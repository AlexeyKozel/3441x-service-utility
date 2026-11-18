"""Offline, bounded NOR repair. No instrument transport or personality patching."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import struct

from .offline import (NOR_SIZE, NOR_BASE, APP_BASE, APP_END, REC_BASE, REC_END,
                      REC_OFFSET, _image_info, _find_best_zlib, _identify,
                      _decode_ppc_branch, swap_pairs, sha256, parse_cal_payload)
from .cal_history import REGION_OFFSET, REGION_SIZE, SLOT_SIZE, scan_cal_region
from .srecord import parse_xs_bytes


def image_info(cpu: bytes, kind: str) -> dict:
    offset, base, end = (0, APP_BASE, APP_END) if kind == 'app' else (REC_OFFSET, REC_BASE, REC_END)
    try:
        return _image_info(cpu, offset, base, end)
    except (ValueError, struct.error) as exc:
        return dict(headerPlausible=False, checksumValid=False, issue=str(exc))


def normalize(raw: bytes, order: str = 'auto') -> tuple[bytes, str]:
    if len(raw) < NOR_SIZE:
        raise ValueError('A complete 8 MiB NOR dump is required.')
    if order not in ('auto', 'cpu', 'programmer'):
        raise ValueError('Invalid byte order.')
    data = raw[:NOR_SIZE]
    if order != 'auto':
        return (data if order == 'cpu' else swap_pairs(data)), order
    candidates = (data, swap_pairs(data))
    scores = [sum(int(i.get('headerPlausible', False)) + 4*int(i.get('checksumValid', False))
                  for i in (image_info(c, 'app'), image_info(c, 'recovery'))) for c in candidates]
    if scores[0] == scores[1]:
        raise ValueError('NOR byte order is ambiguous. Select CPU or programmer order explicitly.')
    index = int(scores[1] > scores[0])
    return candidates[index], ('cpu', 'programmer')[index]


def content_identity(cpu: bytes, kind: str) -> dict:
    info = image_info(cpu, kind)
    if not info.get('headerPlausible'):
        return {}
    offset = 0 if kind == 'app' else REC_OFFSET
    length = int(info['length'])
    # Identity comes from decompressed image content, never the SA96 writer code.
    return _identify(kind, _find_best_zlib(cpu[offset:offset+length], NOR_BASE+offset)) or {}


def _reset_ok(cpu: bytes, rec_length: int) -> bool:
    decoded = _decode_ppc_branch(int.from_bytes(cpu[-4:], 'big'), 0xFFFFFFFC)
    return bool(decoded.get('isBranch') and not decoded.get('link')
                and REC_BASE <= decoded['target'] < REC_BASE+rec_length)


def _source_image(raw: bytes, kind: str, order: str) -> tuple[bytes, dict, list[tuple[int, int]], bool]:
    """Return independently validated source, coverage, and reset availability."""
    offset = 0 if kind == 'app' else REC_OFFSET
    reset = False
    if raw.startswith(b'%headerlength='):
        cpu, coverage, reset = _package_image(parse_xs_bytes(raw), kind)
    elif len(raw) >= NOR_SIZE:
        cpu, _ = normalize(raw, order)
        info = image_info(cpu, kind)
        coverage = [(offset, offset+int(info.get('length', 0)))]
        reset = kind == 'recovery'
    else:
        if kind != 'recovery' or not 16 <= len(raw) <= NOR_SIZE-REC_OFFSET:
            raise ValueError('Source must be a NOR dump or an XS package; Recovery also accepts a CPU-order logical image.')
        if order == 'programmer':
            raise ValueError('Standalone Recovery images must be CPU order.')
        cpu = bytes(REC_OFFSET) + raw + b'\xff'*(NOR_SIZE-REC_OFFSET-len(raw))
        coverage = [(REC_OFFSET, REC_OFFSET+len(raw))]
        reset = len(raw) == NOR_SIZE-REC_OFFSET
    info = image_info(cpu, kind)
    if not info.get('checksumValid'):
        raise ValueError(f'Source {kind} header/checksum is invalid.')
    length = int(info['length'])
    limit = REGION_OFFSET if kind == 'app' else NOR_SIZE-4
    if offset+length > limit:
        raise ValueError(f'Source {kind} overlaps a protected area.')
    identity = content_identity(cpu, kind)
    if not identity.get('model'):
        raise ValueError(f'Source {kind} content is not recognized; compatibility cannot be established.')
    return cpu, dict(info, identity=identity), coverage, reset


def _package_image(package, kind):
    wanted = 'instrumentimage' if kind == 'app' else 'updateimage'
    if package.image_type != wanted:
        raise ValueError(f'Expected {wanted}.')
    start, stop = (0, REGION_OFFSET) if kind == 'app' else (REC_OFFSET, NOR_SIZE)
    cpu = bytearray(b'\xff'*NOR_SIZE)
    covered = bytearray(NOR_SIZE)
    spans = []
    for r in package.s3_records:
        a = r.address-NOR_BASE; b = a+len(r.data)
        if a < start or b > stop or any(covered[a:b]):
            raise ValueError('Package overlaps protected bytes or repeats addresses.')
        cpu[a:b] = r.data; covered[a:b] = b'\x01'*(b-a); spans.append((a,b))
    info = image_info(cpu, kind)
    end = start+int(info.get('length', 0))
    if end <= start+16 or not all(covered[start:start+8]) or not all(covered[start+16:end]):
        raise ValueError('Package does not independently cover the complete logical image.')
    if any(covered[end:NOR_SIZE-4]):
        raise ValueError('Package writes outside its logical image.')
    if kind == 'recovery' and any(covered[-4:]) and not all(covered[-4:]):
        raise ValueError('Package covers only part of the reset vector.')
    identity = content_identity(cpu, kind)
    if identity.get('model') != package.model:
        raise ValueError('Package model does not match its embedded image content.')
    return bytes(cpu), spans, bool(all(covered[-4:]))


@dataclass(frozen=True)
class RepairPlan:
    output: bytes
    report: dict


def plan_repair(target: Path, *, cal: Path | None = None, app: Path | None = None,
                recovery: Path | None = None, order='auto', donor_order='auto',
                model: str | None = None, restore_reset=False, overwrite_cal_journal=False) -> RepairPlan:
    if not any((cal, app, recovery)):
        raise ValueError('Select at least one repair source.')
    if overwrite_cal_journal and not cal:
        raise ValueError('Overwrite CAL journal requires a CAL source.')
    if restore_reset and not recovery:
        raise ValueError('Reset restoration requires a Recovery source.')
    if model not in (None, '34410A', '34411A', 'L4411A'):
        raise ValueError('Unsupported target model.')
    raw = Path(target).read_bytes(); cpu, detected = normalize(raw, order)
    rec_identity = content_identity(cpu, 'recovery')
    recognized = rec_identity.get('model')
    if recognized and model and recognized != model:
        raise ValueError('Selected model conflicts with target Recovery content.')
    expected = recognized or model
    if not expected:
        raise ValueError('Target Recovery content is unrecognized. Explicit target model is required.')
    work = bytearray(cpu); allowed = bytearray(NOR_SIZE)
    sources = [dict(path=str(Path(target).resolve()), sha256=sha256(raw), role='target')]
    actions = []; warnings = []
    if not recognized:
        warnings.append('Target model is user-specified; damaged/unknown Recovery content cannot independently confirm it.')
    for kind, path in (('recovery', recovery), ('app', app)):
        if not path:
            continue
        source_raw = Path(path).read_bytes()
        src, info, spans, has_reset = _source_image(source_raw, kind, donor_order)
        if info['identity']['model'] != expected:
            raise ValueError(f'Source {kind} content does not match target model {expected}.')
        sources.append(dict(path=str(Path(path).resolve()), sha256=sha256(source_raw), role=kind))
        start = REC_OFFSET if kind == 'recovery' else 0
        end = start+info['length']; copied = 0
        for a,b in spans:
            a, b = max(start,a), min(end,b)
            if b > a:
                work[a:b] = src[a:b]; allowed[a:b] = b'\x01'*(b-a); copied += b-a
        if copied < info['length']:
            warnings.append(f'{kind}: uncovered reserved header bytes are preserved from the target.')
        if kind == 'recovery' and restore_reset:
            if not has_reset or not _reset_ok(src, info['length']):
                raise ValueError('Recovery source has no valid matching reset vector.')
            work[-4:] = src[-4:]; allowed[-4:] = b'\x01'*4
        actions.append(dict(operation=kind, start=start, endExclusive=end,
                            copiedBytes=copied, sourceIdentity=info['identity'], restoreReset=kind == 'recovery' and restore_reset))
    if cal:
        source_raw = Path(cal).read_bytes()
        if len(source_raw) >= NOR_SIZE:
            source_cpu, _ = normalize(source_raw, donor_order)
            region = source_cpu[REGION_OFFSET:REGION_OFFSET+REGION_SIZE]
        elif len(source_raw) == REGION_SIZE:
            region = source_raw
        else:
            region = None
        if region is not None:
            cat = scan_cal_region(region)
            selected = cat['currentSlot'] or cat['fallbackSlot']
            if not selected:
                raise ValueError('CAL source has no unique intact current/fallback record.')
            s = next(s for s in cat['slots'] if s['id'] == selected)
            payload = struct.pack('>HII', s['version'], s['bodyLength'], s['checksumStored'])+bytes.fromhex(s['bodyHex'])
        else:
            payload = source_raw
        parsed = parse_cal_payload(payload)
        if parsed['version'] != 45 or parsed['bodyLength'] != 4924 or not parsed['checksumValid']:
            raise ValueError('CAL transfer requires an intact schema45 payload.')
        ai = content_identity(work, 'app')
        if ai.get('model') != expected or ai.get('revision') != '2.43' or expected not in ('34410A','34411A') or not image_info(work,'app')['checksumValid']:
            raise ValueError('CAL transfer requires a recognized compatible APP 2.43 (34410A/34411A); repair APP first.')
        retired = []
        if overwrite_cal_journal:
            work[REGION_OFFSET:REGION_OFFSET+REGION_SIZE] = b'\xff'*REGION_SIZE
            allowed[REGION_OFFSET:REGION_OFFSET+REGION_SIZE] = b'\x01'*REGION_SIZE
            free = dict(id='A0', norOffset=REGION_OFFSET)
        else:
            cat = scan_cal_region(work[REGION_OFFSET:REGION_OFFSET+REGION_SIZE])
            if any(s['status'] not in ('Empty','Current','Fallback','Historical (retired)') or
                   (s['status'] != 'Empty' and not s['recordValid']) for s in cat['slots']):
                raise ValueError('Target CAL journal is damaged or incomplete; explicitly select Overwrite CAL journal to replace it in a new file.')
            if sum(s['state'] == '0x00A5' for s in cat['slots']) > 1 or sum(s['state'] == '0x00A0' for s in cat['slots']) > 1:
                raise ValueError('Target CAL journal has ambiguous active markers; explicitly select Overwrite CAL journal to replace it in a new file.')
            free = next((s for s in cat['slots'] if s['status'] == 'Empty'), None)
            if not free:
                raise ValueError('Target CAL journal is full; explicitly select Overwrite CAL journal to replace it in a new file.')
            for s in cat['slots']:
                if s['state'] in ('0x00A5','0x00A0'):
                    a=s['norOffset']; work[a:a+2]=b'\0\0'; allowed[a:a+2]=b'\x01'*2
            retired = [s['norOffset'] for s in cat['slots'] if s['state'] in ('0x00A5','0x00A0')]
        record = struct.pack('>HHI',0xA5,45,4932)+payload[2:]
        a=free['norOffset']; work[a:a+SLOT_SIZE]=record+b'\xff'*(SLOT_SIZE-len(record)); allowed[a:a+SLOT_SIZE]=b'\x01'*SLOT_SIZE
        verify = scan_cal_region(work[REGION_OFFSET:REGION_OFFSET+REGION_SIZE])
        selected = next(s for s in verify['slots'] if s['id'] == verify['currentSlot'])
        if selected['id'] != free['id'] or selected['bodyHex'] != payload[10:].hex():
            raise ValueError('CAL read-back verification failed.')
        if overwrite_cal_journal and work[REGION_OFFSET+SLOT_SIZE:REGION_OFFSET+REGION_SIZE] != b'\xff'*(REGION_SIZE-SLOT_SIZE):
            raise ValueError('CAL journal empty-slot verification failed.')
        sources.append(dict(path=str(Path(cal).resolve()),sha256=sha256(source_raw),role='cal'))
        actions.append(dict(operation='cal',slot=free['id'],bodySha256=parsed['bodySha256'],
                            start=a,endExclusive=REGION_OFFSET+REGION_SIZE if overwrite_cal_journal else a+SLOT_SIZE,
                            mode='overwrite' if overwrite_cal_journal else 'append', retiredMarkers=retired))
        warnings.append('NOR contains no serial number. CAL suitability for this specimen must be established by the owner.')
    incomplete = False
    for kind in ('app','recovery'):
        ident = content_identity(work,kind)
        if ident.get('model') and ident['model'] != expected:
            raise ValueError(f'Result {kind} content conflicts with target model.')
        if not image_info(work,kind)['checksumValid']:
            if (kind == 'app' and app) or (kind == 'recovery' and recovery):
                raise ValueError(f'Repaired {kind} failed final checksum verification.')
            warnings.append(f'Result {kind} checksum is invalid; this is a partial repair.')
            incomplete = True
        if not ident.get('model'):
            warnings.append(f'Result {kind} content is unknown; whole-image compatibility is not confirmed.')
            incomplete = True
    rec = image_info(work,'recovery')
    reset_ok = _reset_ok(work,int(rec.get('length',0)))
    if not reset_ok:
        warnings.append('Result reset vector is not a branch into the logical Recovery image.')
        incomplete = True
    changed = sum(a != b for a,b in zip(cpu,work))
    if any(a != b and not permit for a,b,permit in zip(cpu,work,allowed)):
        raise AssertionError('Changes outside the repair plan.')
    output = (bytes(work) if detected == 'cpu' else swap_pairs(work))+raw[NOR_SIZE:]
    report = dict(schema='3441x-nor-repair-v1', status='PARTIAL_REPAIR_OFFLINE_ONLY' if incomplete else 'VERIFIED_OFFLINE_ONLY',
                  targetModel=expected, identityBasis='Recovery decompressed content' if recognized else 'explicit user model',
                  targetRecoveryIdentity=rec_identity, inputOrder=detected, preservedTrailerBytes=len(raw)-NOR_SIZE,
                  sources=sources, actions=actions, changedBytes=changed, outsidePlanChangedBytes=0,
                  outputSha256=sha256(output), outputBytes=len(output),
                  app=image_info(work,'app'),recovery=rec,resetVectorValid=reset_ok,warnings=warnings)
    return RepairPlan(output,report)


def save_plan(plan: RepairPlan, output: Path) -> dict:
    """Exclusive new files only; verify the written dump; never overwrite inputs."""
    output=Path(output); report_path=Path(str(output)+'.json')
    for item in plan.report['sources']:
        if sha256(Path(item['path']).read_bytes()) != item['sha256']:
            raise ValueError('A source changed after planning; rebuild the repair plan.')
    if output.exists() or report_path.exists():
        raise ValueError('Output dump and JSON report must both be new files.')
    if sha256(plan.output) != plan.report['outputSha256']:
        raise ValueError('Repair plan checksum mismatch.')
    made=[]
    try:
        with output.open('xb') as f:
            made.append(output); f.write(plan.output); f.flush(); os.fsync(f.fileno())
        if sha256(output.read_bytes()) != plan.report['outputSha256']:
            raise OSError('Saved NOR read-back failed.')
        report=dict(plan.report,output=str(output.resolve()))
        with report_path.open('x',encoding='utf-8') as f:
            made.append(report_path); json.dump(report,f,indent=2); f.write('\n')
    except BaseException:
        for p in reversed(made):
            p.unlink()
        raise
    return report


def summary(plan: RepairPlan) -> str:
    r=plan.report
    lines=[f"Target model: {r['targetModel']} ({r['identityBasis']})",
           f"Target file: {r['sources'][0]['path']}",
           f"Result status: {r['status']}",
           f"Byte order: {r['inputOrder']}; trailer preserved: {r['preservedTrailerBytes']} bytes",
           'Operations: '+', '.join(a['operation'] for a in r['actions']),
           f"Changed bytes: {r['changedBytes']}; outside plan: 0",
           f"APP checksum: {r['app']['checksumValid']}; Recovery checksum: {r['recovery']['checksumValid']}",
           f"Reset branch into Recovery: {r['resetVectorValid']}",
           'Offline verification only; instrument boot and measurement accuracy are not verified.']
    for a in r['actions']:
        source=next(s for s in r['sources'] if s['role']==a['operation'])
        lines.append(f"{a['operation']}: {source['path']}")
        lines.append(f"  NOR offsets 0x{a['start']:06X}..0x{a['endExclusive']-1:06X}")
        if a['operation']=='cal':
            if a.get('mode') == 'overwrite':
                lines.append('  Overwrite CAL journal: all previous records removed in the output file. A0 is the only active record; 31 slots are empty. Original dump unchanged.')
            else:
                lines.append(f"  New slot {a['slot']}; previous active markers retired, historical bodies preserved.")
        else:
            lines.append(f"  Content: {a['sourceIdentity']['model']} {a['sourceIdentity']['revision']}; reset restored: {a['restoreReset']}")
    lines.extend(r['warnings'])
    return '\n'.join(lines)
