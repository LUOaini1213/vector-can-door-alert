"""Explicit Classic CAN wire encoding; DBC mapping lives in data/body_control.dbc."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

VEHICLE_ID = 0x100
DOOR_ID = 0x101
ALERT_ID = 0x200


def require_time(value):
    if type(value) is not int or value < 0:
        raise ValueError("timestamp_ms must be a nonnegative integer")
    return value


@dataclass(frozen=True)
class Frame:
    timestamp_ms: int
    arbitration_id: int
    data: bytes

    def __post_init__(self):
        require_time(self.timestamp_ms)
        if type(self.arbitration_id) is not int or not 0 <= self.arbitration_id <= 0x7FF:
            raise ValueError("arbitration_id must be a standard 11-bit CAN identifier")
        if not isinstance(self.data, bytes):
            raise ValueError("frame data must be bytes")
        # Raw injection deliberately permits malformed DLC, so receivers can test it.

    def to_dict(self):
        return {"timestamp_ms": self.timestamp_ms,
                "arbitration_id": self.arbitration_id,
                "data_hex": self.data.hex(" ").upper()}


def _check(frame, expected_id):
    if not isinstance(frame, Frame) or frame.arbitration_id != expected_id:
        raise ValueError("unexpected CAN message identifier")
    if len(frame.data) != 8:
        raise ValueError("message must contain exactly 8 bytes")


def _boolean(value, label):
    if type(value) is not bool:
        raise ValueError(f"{label} must be boolean")
    return int(value)


def encode_vehicle(timestamp_ms, speed_kmh, ignition):
    if isinstance(speed_kmh, bool) or not isinstance(speed_kmh, (int, float, Decimal)):
        raise ValueError("speed_kmh must be a number")
    try:
        value = Decimal(str(speed_kmh))
        raw = value * 100
        valid = value.is_finite() and 0 <= value <= 250 and raw == raw.to_integral_value()
    except (InvalidOperation, ValueError):
        valid = False
    if not valid:
        raise ValueError("speed_kmh must be 0..250 with at most two decimal places")
    payload = int(raw).to_bytes(2, "little") + bytes([_boolean(ignition, "ignition")]) + bytes(5)
    return Frame(timestamp_ms, VEHICLE_ID, payload)


def decode_vehicle(frame):
    _check(frame, VEHICLE_ID)
    raw = int.from_bytes(frame.data[:2], "little")
    if raw > 25000 or frame.data[2] not in (0, 1):
        raise ValueError("vehicle payload contains invalid speed or ignition")
    return {"speed_raw": raw, "ignition": bool(frame.data[2])}


def encode_doors(timestamp_ms, door_mask):
    if type(door_mask) is not int or not 0 <= door_mask <= 15:
        raise ValueError("door_mask must be an integer in 0..15")
    return Frame(timestamp_ms, DOOR_ID, bytes([door_mask]) + bytes(7))


def decode_doors(frame):
    _check(frame, DOOR_ID)
    if frame.data[0] > 15:
        raise ValueError("door mask contains reserved bits")
    return frame.data[0]


def encode_alert(timestamp_ms, warning, data_fault, reason):
    if type(reason) is not int or reason not in range(1, 7):
        raise ValueError("reason must be a code from 1 through 6")
    return Frame(timestamp_ms, ALERT_ID,
                 bytes([_boolean(warning, "warning"), _boolean(data_fault, "data_fault"), reason]) + bytes(5))


def decode_alert(frame):
    _check(frame, ALERT_ID)
    if frame.data[0] not in (0, 1) or frame.data[1] not in (0, 1) or frame.data[2] not in range(1, 7):
        raise ValueError("invalid alert status payload")
    return {"warning": bool(frame.data[0]), "data_fault": bool(frame.data[1]),
            "reason": frame.data[2]}
