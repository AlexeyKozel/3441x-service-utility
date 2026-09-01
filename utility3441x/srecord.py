"""Strict parser/validator for supported 3441x `.xs` packages."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


ALLOWED_MODELS = frozenset({"34410A", "34411A", "L4411A"})
ALLOWED_IMAGE_TYPES = frozenset({"instrumentimage", "updateimage"})
SUPPORTED_UPDATE_METHOD = "caspreRamBased"
LIVE_APP_MODELS = frozenset({"34410A", "34411A"})


@dataclass(frozen=True)
class SRecord:
    line_number: int
    record_type: str
    count: int
    body: bytes
    checksum: int
    raw_line: bytes

    @property
    def address(self) -> int | None:
        if self.record_type == "S3" and len(self.body) >= 4:
            return int.from_bytes(self.body[:4], "big")
        return None

    @property
    def data(self) -> bytes:
        return self.body[4:] if self.record_type == "S3" else b""


@dataclass(frozen=True)
class XsPackage:
    path: Path | None
    raw: bytes
    headers: dict[str, str]
    header_lines: tuple[bytes, ...]
    payload: bytes
    records: tuple[SRecord, ...]

    @property
    def model(self) -> str:
        return self.headers["model"]

    @property
    def image_type(self) -> str:
        return self.headers["imagetype"]

    @property
    def selector(self) -> int:
        return 66 if self.image_type == "instrumentimage" else 177

    @property
    def s3_records(self) -> tuple[SRecord, ...]:
        return tuple(record for record in self.records if record.record_type == "S3")


def assert_app_image_package(package: XsPackage) -> None:
    """Permit only the factory-format APP image class on the live APP path."""

    if package.image_type != "instrumentimage":
        raise PermissionError(
            "Only APP instrumentimage packages are enabled; updateimage upload is blocked"
        )
    if package.model not in LIVE_APP_MODELS:
        raise PermissionError(
            "Live APP upload accepts only 34410A or 34411A packages"
        )


def assert_app_upload_preflight(
    package: XsPackage,
    instrument_identity: dict[str, str],
) -> None:
    assert_app_image_package(package)
    if instrument_identity.get("model") not in LIVE_APP_MODELS:
        raise PermissionError(
            "Live APP upload is limited to 34410A/34411A instruments"
        )


def assert_app_identity_after(
    package: XsPackage,
    before: dict[str, str],
    after: dict[str, str] | None,
) -> None:
    if (
        after is None
        or after.get("serial") != before.get("serial")
        or after.get("model") != package.model
    ):
        raise RuntimeError("Post-APP-update identity does not match the package")


def _split_lines_preserving_endings(raw: bytes) -> list[bytes]:
    lines = raw.splitlines(keepends=True)
    if not lines or b"" in lines:
        raise ValueError("empty `.xs` package")
    return lines


def _parse_record(raw_line: bytes, line_number: int) -> SRecord:
    text = raw_line.rstrip(b"\r\n")
    if len(text) < 6 or text[:1] != b"S":
        raise ValueError(f"line {line_number}: not an S-record")
    try:
        record_type = text[:2].decode("ascii")
        encoded = bytes.fromhex(text[2:].decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"line {line_number}: invalid hex") from exc
    if len(encoded) < 2:
        raise ValueError(f"line {line_number}: S-record is too short")
    count = encoded[0]
    if len(encoded) != count + 1:
        raise ValueError(
            f"line {line_number}: count={count}, actual {len(encoded) - 1}"
        )
    if sum(encoded) & 0xFF != 0xFF:
        raise ValueError(f"line {line_number}: invalid checksum")
    return SRecord(
        line_number=line_number,
        record_type=record_type,
        count=count,
        body=encoded[1:-1],
        checksum=encoded[-1],
        raw_line=raw_line,
    )


def parse_xs_bytes(raw: bytes, *, path: Path | None = None) -> XsPackage:
    lines = _split_lines_preserving_endings(raw)
    first = lines[0].rstrip(b"\r\n")
    if not first.startswith(b"%headerlength="):
        raise ValueError("first line must contain `%headerlength=`")
    try:
        header_count = int(first.split(b"=", 1)[1], 10)
    except ValueError as exc:
        raise ValueError("invalid `%headerlength`") from exc
    if not 1 <= header_count < len(lines):
        raise ValueError("`%headerlength` is outside file bounds")

    headers: dict[str, str] = {}
    for number, line in enumerate(lines[:header_count], start=1):
        stripped = line.rstrip(b"\r\n")
        if not stripped.startswith(b"%") or b"=" not in stripped:
            raise ValueError(f"line {number}: invalid header")
        key, value = stripped[1:].split(b"=", 1)
        key_text = key.decode("ascii").lower()
        if key_text in headers:
            raise ValueError(f"duplicate header `{key_text}`")
        headers[key_text] = value.decode("ascii")

    required = {
        "headerlength",
        "imagerev",
        "imagetype",
        "model",
        "revsnotsupported",
        "supportedio",
        "updatedescription",
        "updatemethod",
        "utilityrev",
    }
    missing = sorted(required - headers.keys())
    if missing:
        raise ValueError(f"missing headers: {', '.join(missing)}")
    if int(headers["headerlength"], 10) != header_count:
        raise ValueError("headerlength does not match the number of header lines")
    if headers["model"] not in ALLOWED_MODELS:
        raise ValueError(f"unsupported model `{headers['model']}`")
    if headers["imagetype"] not in ALLOWED_IMAGE_TYPES:
        raise ValueError(f"unsupported image type `{headers['imagetype']}`")
    if headers["updatemethod"] != SUPPORTED_UPDATE_METHOD:
        raise ValueError(
            f"unsupported update method `{headers['updatemethod']}`; "
            f"only `{SUPPORTED_UPDATE_METHOD}` is accepted"
        )

    payload_lines = lines[header_count:]
    records = tuple(
        _parse_record(line, header_count + index)
        for index, line in enumerate(payload_lines, start=1)
    )
    types = [record.record_type for record in records]
    if not records or types[0] != "S5" or types[-1] != "S9":
        raise ValueError("stream must start with S5 and end with S9")
    if any(kind not in {"S3", "S5", "S9"} for kind in types):
        raise ValueError("stream contains an unsupported S-record type")
    if types.count("S5") != 1 or types.count("S9") != 1:
        raise ValueError("stream must contain exactly one S5 and one S9")

    s3_records = [record for record in records if record.record_type == "S3"]
    if not s3_records:
        raise ValueError("stream does not contain S3 data records")
    s5 = records[0]
    if len(s5.body) != 4 or int.from_bytes(s5.body, "big") != len(s3_records):
        raise ValueError("S5 record count does not match the number of S3 records")
    if len(records[-1].body) != 3:
        raise ValueError("expected a supported S9 with a three-byte start address")

    occupied: list[tuple[int, int]] = []
    for record in s3_records:
        if len(record.body) < 5:
            raise ValueError(f"line {record.line_number}: empty S3 data record")
        start = record.address
        assert start is not None
        end = start + len(record.data)
        if occupied and start < occupied[-1][1]:
            raise ValueError(f"line {record.line_number}: overlapping/out-of-order S3")
        occupied.append((start, end))

    return XsPackage(
        path=path,
        raw=raw,
        headers=headers,
        header_lines=tuple(lines[:header_count]),
        payload=b"".join(payload_lines),
        records=records,
    )


def load_xs(path: Path) -> XsPackage:
    path = Path(path)
    return parse_xs_bytes(path.read_bytes(), path=path)


def encode_srecord(record_type: str, body: bytes, *, newline: bytes = b"\r\n") -> bytes:
    if record_type not in {"S3", "S5", "S9"}:
        raise ValueError("only S3/S5/S9 are supported")
    count = len(body) + 1
    if count > 0xFF:
        raise ValueError("S-record body is too long")
    checksum = (~((count + sum(body)) & 0xFF)) & 0xFF
    return b"S" + record_type[1:].encode("ascii") + bytes([count]).hex().upper().encode() + body.hex().upper().encode() + bytes([checksum]).hex().upper().encode() + newline


def build_xs(
    *,
    model: str,
    image_type: str,
    image_revision: str,
    description: str,
    s3_records: list[tuple[int, bytes]],
) -> bytes:
    if model not in ALLOWED_MODELS:
        raise ValueError("unsupported model")
    if image_type not in ALLOWED_IMAGE_TYPES:
        raise ValueError("unsupported image type")
    headers = [
        b"%headerlength=9\r\n",
        f"%imagerev={image_revision}\r\n".encode(),
        f"%imagetype={image_type}\r\n".encode(),
        f"%model={model}\r\n".encode(),
        b"%revsnotsupported=<0.13\r\n",
        b"%supportedio=lan,gpib,usb\r\n",
        f"%updatedescription={description}\r\n".encode("ascii"),
        b"%updatemethod=caspreRamBased\r\n",
        b"%utilityrev=3441x-service-utility-1.0\r\n",
    ]
    records = [encode_srecord("S5", len(s3_records).to_bytes(4, "big"))]
    records.extend(
        encode_srecord("S3", address.to_bytes(4, "big") + data)
        for address, data in s3_records
    )
    records.append(encode_srecord("S9", b"\0\0\0"))
    package = b"".join(headers + records)
    parse_xs_bytes(package)
    return package
