"""Offline NOR, Recovery and schema45 CAL analysis without hardware access."""

from __future__ import annotations

import hashlib
import json
import struct
import zlib
from pathlib import Path


NOR_BASE = 0xFF800000
NOR_SIZE = 0x00800000
NOR_END = 0xFFFFFFFF
APP_BASE, APP_END = 0xFF800000, 0xFFDFFFFF
REC_BASE, REC_END = 0xFFE00000, 0xFFFFFFFF
REC_OFFSET = REC_BASE - NOR_BASE
SCHEMA45_BODY_BYTES = 4924

KNOWN_APP_DECOMP = {
    "9d05d676bf87d5109f75150935d6a95d8422ce4ceec2e768f5538caba9d02c6b": ("34410A", "2.43"),
    "435633c24c33b546bf7e708392a751719fc41ed58d9ab8cf9643d559748f8654": ("34411A", "2.43"),
    "24dc210f0eae3039b6390105beefa140062c40f94b5cf1d2b8f4fc78fa42f46a": ("L4411A", "2.39"),
    "5e251b1cdf20ae4b010a673c69a2f9fae92234724b5aa88720fce49f2309ee36": ("L4411A", "2.35"),
}
KNOWN_REC_DECOMP = {
    "81d4f49637ac5abf6b7057b387c15b30c259627030190583016f8e6cfd7537fd": ("34410A", "2.35"),
    "e7a5e9c33532519cc7d6cb0a1c43d256596474b724330cfc67f0342eb7620ca9": ("34411A", "2.35"),
    "ad45aee6f39316030d8232378915ef15b924a1a4234641a4c8f4d65f825186dc": ("34410A", "2.40"),
    "983d9c9eab812f3ef53589bd5ec51162fc2778f005c9f3d4cd948d04f7c26311": ("L4411A", "2.35"),
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def swap_pairs(data: bytes) -> bytes:
    if len(data) & 1:
        raise ValueError("pair-swap requires an even size")
    output = bytearray(len(data))
    output[0::2] = data[1::2]
    output[1::2] = data[0::2]
    return bytes(output)


def _be32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


def _sum32(data: bytes, start: int, end_inclusive: int) -> int:
    length = end_inclusive - start + 1
    if length <= 0 or length & 3:
        raise ValueError("SUM32 span must be divisible by four")
    return sum(_be32(data, offset) for offset in range(start, end_inclusive + 1, 4)) & 0xFFFFFFFF


def _image_info(cpu: bytes, offset: int, base: int, window_end: int) -> dict[str, object]:
    stored = _be32(cpu, offset)
    end_address = _be32(cpu, offset + 4)
    if not base + 0x10 <= end_address <= window_end:
        return {
            "headerPlausible": False,
            "storedChecksum": stored,
            "endAddress": end_address,
            "checksumValid": False,
        }
    end_offset = offset + end_address - base
    if end_offset >= len(cpu):
        return {
            "headerPlausible": False,
            "storedChecksum": stored,
            "endAddress": end_address,
            "checksumValid": False,
        }
    calculated = _sum32(cpu, offset + 0x10, end_offset)
    return {
        "headerPlausible": True,
        "storedChecksum": stored,
        "calculatedChecksum": calculated,
        "checksumValid": stored == calculated,
        "endAddress": end_address,
        "length": end_offset - offset + 1,
        "sha256Logical": sha256(cpu[offset : end_offset + 1]),
    }


def detect_nor_order(data: bytes) -> tuple[bytes, str]:
    if len(data) < NOR_SIZE:
        raise ValueError("a complete 8 MiB NOR dump is required")
    data = data[:NOR_SIZE]

    def score(candidate: bytes) -> int:
        objects = (
            _image_info(candidate, 0, APP_BASE, APP_END),
            _image_info(candidate, REC_OFFSET, REC_BASE, REC_END),
        )
        return sum(
            (1 if item["headerPlausible"] else 0)
            + (4 if item["checksumValid"] else 0)
            for item in objects
        )

    swapped = swap_pairs(data)
    original_score, swapped_score = score(data), score(swapped)
    if original_score > swapped_score:
        return data, "cpu"
    if swapped_score > original_score:
        return swapped, "programmer"
    raise ValueError(
        f"byte order is ambiguous: cpu={original_score}, programmer={swapped_score}"
    )


def _decode_ppc_branch(instruction: int, pc: int) -> dict[str, object]:
    if instruction >> 26 != 18:
        return {"isBranch": False}
    displacement = instruction & 0x03FFFFFC
    if displacement & 0x02000000:
        displacement -= 0x04000000
    absolute = bool(instruction & 2)
    target = (displacement if absolute else pc + displacement) & 0xFFFFFFFF
    return {
        "isBranch": True,
        "absolute": absolute,
        "link": bool(instruction & 1),
        "displacement": displacement,
        "target": target,
    }


def _find_personality(cpu: bytes, recovery: dict[str, object]) -> list[dict[str, object]]:
    if not recovery.get("headerPlausible"):
        return []
    length = int(recovery["length"])
    logical = cpu[REC_OFFSET : REC_OFFSET + length]
    suffix = bytes.fromhex("3C8090003884000AB0640000")
    models = {0x235A: "34410A", 0xB643: "34411A"}
    hits = []
    for offset in range(0, len(logical) - 15, 4):
        if logical[offset : offset + 2] == b"\x38\x60" and logical[offset + 4 : offset + 16] == suffix:
            value = int.from_bytes(logical[offset + 2 : offset + 4], "big")
            hits.append(
                {
                    "address": REC_BASE + offset + 2,
                    "value": value,
                    "model": models.get(value),
                }
            )
    return hits


def _zlib_header_ok(first: int, second: int) -> bool:
    return (first & 0x0F) == 8 and ((first << 8) | second) % 31 == 0


def _find_best_zlib(region: bytes, base: int) -> dict[str, object] | None:
    best = None
    for offset in range(len(region) - 2):
        if region[offset] != 0x78 or not _zlib_header_ok(region[offset], region[offset + 1]):
            continue
        try:
            decoder = zlib.decompressobj()
            output = decoder.decompress(region[offset:], 32 * 1024 * 1024)
            compressed = len(region[offset:]) - len(decoder.unused_data)
            if not decoder.eof or len(output) < 100_000 or compressed < 10_000:
                continue
            candidate = {
                "address": base + offset,
                "compressedLength": compressed,
                "decompressedSize": len(output),
                "sha256Decompressed": sha256(output),
            }
            if best is None or candidate["decompressedSize"] > best["decompressedSize"]:
                best = candidate
        except zlib.error:
            continue
    return best


def _identify(kind: str, stream: dict[str, object] | None) -> dict[str, object] | None:
    if stream is None:
        return None
    database = KNOWN_APP_DECOMP if kind == "app" else KNOWN_REC_DECOMP
    identity = database.get(str(stream["sha256Decompressed"]))
    result = dict(stream)
    result.update(
        {
            "known": identity is not None,
            "model": identity[0] if identity else None,
            "revision": identity[1] if identity else None,
        }
    )
    return result


def inspect_nor_bytes(raw: bytes, *, source: str = "<memory>") -> dict[str, object]:
    cpu, order = detect_nor_order(raw)
    app = _image_info(cpu, 0, APP_BASE, APP_END)
    recovery = _image_info(cpu, REC_OFFSET, REC_BASE, REC_END)
    reset_vector = _be32(cpu, NOR_SIZE - 4)
    reset_decode = _decode_ppc_branch(reset_vector, 0xFFFFFFFC)
    app_region = cpu[: int(app.get("length", 0))] if app["headerPlausible"] else b""
    recovery_region = (
        cpu[REC_OFFSET : REC_OFFSET + int(recovery.get("length", 0))]
        if recovery["headerPlausible"]
        else b""
    )
    return {
        "file": source,
        "inputOrder": order,
        "sha256Input": sha256(raw),
        "sha256CPUOrder": sha256(cpu),
        "app": app,
        "recovery": recovery,
        "embeddedApp": _identify("app", _find_best_zlib(app_region, APP_BASE)),
        "embeddedRecovery": _identify(
            "recovery", _find_best_zlib(recovery_region, REC_BASE)
        ),
        "resetVector": reset_vector,
        "resetVectorDecode": reset_decode,
        "personalityHits": _find_personality(cpu, recovery),
    }


def inspect_nor_file(path: Path) -> dict[str, object]:
    path = Path(path)
    return inspect_nor_bytes(path.read_bytes(), source=str(path))


def inspect_recovery_bytes(recovery: bytes) -> dict[str, object]:
    info = _image_info(recovery, 0, REC_BASE, REC_END)
    if not info["headerPlausible"]:
        raise ValueError("Recovery BootImageHeader failed boundary validation")
    logical = recovery[: int(info["length"])]
    stream = _identify("recovery", _find_best_zlib(logical, REC_BASE))
    fake_nor = bytearray(NOR_SIZE)
    fake_nor[REC_OFFSET : REC_OFFSET + len(logical)] = logical
    return {
        "recovery": info,
        "embeddedRecovery": stream,
        "personalityHits": _find_personality(bytes(fake_nor), info),
        "sha256": sha256(logical),
    }


def parse_cal_payload(payload: bytes) -> dict[str, object]:
    if len(payload) < 10:
        raise ValueError("CAL:DATA:ALL payload is too short")
    version = int.from_bytes(payload[0:2], "big")
    body_length = int.from_bytes(payload[2:6], "big")
    stored = int.from_bytes(payload[6:10], "big")
    if len(payload) != 10 + body_length:
        raise ValueError(
            f"payload size {len(payload)} does not equal 10+bodyLength {10 + body_length}"
        )
    body = payload[10:]
    calculated = (~sum(body)) & 0xFFFFFFFF
    result: dict[str, object] = {
        "size": len(payload),
        "sha256": sha256(payload),
        "version": version,
        "bodyLength": body_length,
        "checksumStored": stored,
        "checksumCalculated": calculated,
        "checksumValid": stored == calculated,
        "bodySha256": sha256(body),
    }
    if body_length == SCHEMA45_BODY_BYTES:
        result["schema45"] = decode_schema45_body(body)
    return result


def _registry_path() -> Path:
    return Path(__file__).with_name("data") / "schema45_registry_snapshot.json"


def load_schema45_registry() -> dict[str, object]:
    registry = json.loads(_registry_path().read_text(encoding="utf-8"))
    rows = registry["registry"]["rows"]
    counts = registry["registry"]["counts"]
    if (len(rows), counts["double"], counts["int32"], counts["body_bytes"]) != (
        1072,
        159,
        913,
        SCHEMA45_BODY_BYTES,
    ):
        raise ValueError("schema45 registry snapshot is damaged")
    return registry


def decode_schema45_body(body: bytes) -> dict[str, object]:
    if len(body) != SCHEMA45_BODY_BYTES:
        raise ValueError(f"schema45 body must contain {SCHEMA45_BODY_BYTES} bytes")
    rows = load_schema45_registry()["registry"]["rows"]
    values = []
    for row in rows:
        offset = row["offset"]
        value = struct.unpack_from(">d" if row["type"] == "double" else ">i", body, offset)[0]
        values.append(
            {
                "offset": offset,
                "name": row["name"],
                "type": row["type"],
                "value": value,
                "provenance": row["provenance"],
            }
        )
    return {
        "elementCount": len(values),
        "doubleCount": 159,
        "int32Count": 913,
        "values": values,
    }
