"""Strict, traceable reader for this project's standard classic CAN ASC subset."""

from decimal import Decimal, DecimalException
import hashlib
from pathlib import Path
import re

from .limits import check_trace_span

TRACE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
ALLOWED_PROVENANCE = {"synthetic", "user-provided-unverified"}


def _microseconds(timestamp):
    """Convert exactly without Decimal context rounding or giant exponent work."""
    try:
        time = Decimal(timestamp)
        if not time.is_finite() or time < 0:
            raise ValueError("INVALID_TIMESTAMP")
        _, digits, exponent = time.as_tuple()
        if not any(digits):
            return 0
        shift = exponent + 6
        if shift < 0:
            remove = -shift
            if remove > len(digits) or any(digits[-remove:]):
                raise ValueError("INVALID_TIMESTAMP: sub-microsecond precision")
            digits = digits[:-remove]
            shift = 0
        if len(digits) + shift > 19:
            raise ValueError("INVALID_TIMESTAMP: timestamp out of range")
        micros = int("".join(map(str, digits))) * 10 ** shift
        if micros > 9_000_000_000_000_000_000:
            raise ValueError("INVALID_TIMESTAMP: timestamp out of range")
        return micros
    except DecimalException as exc:
        raise ValueError("INVALID_TIMESTAMP") from exc


def read_asc(path, trace_id=None, provenance="user-provided-unverified"):
    path = Path(path)
    trace_id = path.stem if trace_id is None else trace_id
    if not isinstance(trace_id, str) or not TRACE_ID.fullmatch(trace_id):
        raise ValueError("trace_id must be 1..64 safe ASCII filename characters")
    if provenance not in ALLOWED_PROVENANCE:
        raise ValueError("provenance must be synthetic or user-provided-unverified")
    snapshot = path.read_bytes()
    text = snapshot.decode("utf-8-sig")
    frames, rejected = [], []
    header_seen = False
    previous = -1
    for line_number, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        lower = line.lower()
        if not line or line.startswith("//"):
            continue
        if re.match(r"base(?:\s|$)", lower):
            if lower.split() != ["base", "hex", "timestamps", "absolute"]:
                raise ValueError("only base hex timestamps absolute ASC headers are supported")
            if frames:
                raise ValueError("ASC base header must precede all frames")
            header_seen = True
            continue
        if (re.match(r"date\s+", lower) or
                re.fullmatch(r"(?:no\s+)?internal\s+events\s+logged", lower) or
                re.fullmatch(r"(?:begin|end)\s+triggerblock(?:\s+.+)?", lower) or
                re.fullmatch(r"\d+(?:\.\d+)?\s+start\s+of\s+measurement", lower)):
            continue
        if not header_seen:
            raise ValueError("missing supported ASC base header before data")
        try:
            parts = line.split()
            if len(parts) < 6:
                raise ValueError("UNSUPPORTED_RECORD: expected classic CAN data record")
            timestamp, channel, can_id, direction, kind, dlc, *payload = parts
            timestamp_us = _microseconds(timestamp)
            if not re.fullmatch(r"[0-9]+", channel) or not 0 < int(channel) <= 2_147_483_647:
                raise ValueError("INVALID_CHANNEL")
            if not re.fullmatch(r"[0-9A-Fa-f]{1,3}", can_id) or int(can_id, 16) > 0x7FF:
                raise ValueError("UNSUPPORTED_ID: standard 11-bit IDs only")
            if direction not in {"Rx", "Tx"} or kind != "d":
                raise ValueError("UNSUPPORTED_FRAME: Rx/Tx classic data frames only")
            if not re.fullmatch(r"[0-8]", dlc) or len(payload) != int(dlc):
                raise ValueError("DLC_MISMATCH")
            if any(not re.fullmatch(r"[0-9A-Fa-f]{2}", byte) for byte in payload):
                raise ValueError("INVALID_HEX_PAYLOAD")
            data_hex = " ".join(byte.upper() for byte in payload)
        except ValueError as exc:
            rejected.append({"line_number": line_number, "raw_line": raw_line, "reason": str(exc)})
            continue
        if timestamp_us < previous:
            raise ValueError(f"accepted frame timestamps move backwards at physical line {line_number}")
        previous = timestamp_us
        frames.append({"frame_no": len(frames) + 1, "line_number": line_number,
                       "timestamp_us": timestamp_us, "can_id": int(can_id, 16),
                       "channel": int(channel), "direction": direction, "dlc": int(dlc),
                       "data_hex": data_hex, "raw_line": raw_line})
    if not header_seen or not frames:
        raise ValueError("ASC input must have the supported header and at least one accepted frame")
    check_trace_span(frames[0]["timestamp_us"], frames[-1]["timestamp_us"])
    return {"trace_id": trace_id, "source_name": path.name,
            "source_sha256": hashlib.sha256(snapshot).hexdigest(), "provenance": provenance,
            "start_us": frames[0]["timestamp_us"], "end_us": frames[-1]["timestamp_us"],
            "frames": frames, "rejected_lines": rejected}
