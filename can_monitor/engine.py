"""Deterministic offline teaching rules for the fixed body-control CAN protocol.

Intervals use exact integer microseconds. These are monitoring-policy events,
not diagnoses of a physical vehicle or the controller's warning output.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math

from door_alert.protocol import (
    ALERT_ID, DOOR_ID, VEHICLE_ID, Frame,
    decode_alert, decode_doors, decode_vehicle,
)


MINUTE_US = 60_000_000


def _positive_decimal(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(f"{label} must be a finite positive number")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{label} must be a finite positive number") from exc
    if not number.is_finite() or number <= 0:
        raise ValueError(f"{label} must be a finite positive number")
    return number


@dataclass(frozen=True)
class RuleConfig:
    timeout_ms: float = 300
    max_acceleration_kmh_s: float = 100.0
    expected_channels: tuple = (1,)

    def __post_init__(self):
        timeout = _positive_decimal(self.timeout_ms, "timeout_ms")
        ticks = timeout * 1000
        if ticks != ticks.to_integral_value():
            raise ValueError("timeout_ms must represent an exact integer number of microseconds")
        _positive_decimal(self.max_acceleration_kmh_s, "max_acceleration_kmh_s")
        try:
            channels = tuple(self.expected_channels)
        except TypeError as exc:
            raise ValueError("expected_channels must be nonempty positive distinct integers") from exc
        if not channels or any(type(channel) is not int or channel <= 0 for channel in channels):
            raise ValueError("expected_channels must be nonempty positive distinct integers")
        if len(set(channels)) != len(channels):
            raise ValueError("expected_channels must contain distinct channels")
        object.__setattr__(self, "expected_channels", channels)

    @property
    def timeout_us(self):
        return int(Decimal(str(self.timeout_ms)) * 1000)

    def as_dict(self):
        """Canonical configuration used in the persisted content fingerprint."""
        return {
            "timeout_us": self.timeout_us,
            "max_acceleration_kmh_s": str(Decimal(str(self.max_acceleration_kmh_s)).normalize()),
            "expected_channels": sorted(self.expected_channels),
        }


def _event(trace_id, rule, frame, start_us, end_us, *, can_id=None, channel=None,
           previous_frame_no=None, recovery_frame_no=None, open_at_end=False, detail=""):
    result = {
        "trace_id": trace_id,
        "rule": rule,
        "severity": "warning",
        "can_id": frame["can_id"] if frame is not None else can_id,
        "channel": frame["channel"] if frame is not None else channel,
        "start_us": start_us,
        "end_us": end_us,
        "duration_us": end_us - start_us,
        "open_at_end": open_at_end,
        "frame_no": frame["frame_no"] if frame is not None else None,
        "previous_frame_no": previous_frame_no,
        "recovery_frame_no": recovery_frame_no,
        "detail": detail,
    }
    identity = json.dumps(result, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    result["event_id"] = f"{trace_id}:{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]}"
    return result


def _decode(frame):
    result = dict(frame)
    result.update({"decode_status": "unknown", "decode_error": None,
                   "speed_kmh": None, "ignition": None, "door_mask": None,
                   "warning": None, "data_fault": None, "reason_code": None})
    identifier = frame["can_id"]
    if identifier not in (VEHICLE_ID, DOOR_ID, ALERT_ID):
        return result
    try:
        payload = bytes.fromhex(frame["data_hex"])
        if len(payload) != frame["dlc"]:
            raise ValueError("DLC differs from the payload byte count")
        # Existing decoders do not use timestamp_ms. The ASC timestamp remains
        # untouched in timestamp_us; setting 0 avoids any sub-ms rounding.
        wire = Frame(0, identifier, payload)
        if identifier == VEHICLE_ID:
            decoded = decode_vehicle(wire)
            result["speed_kmh"] = decoded["speed_raw"] / 100
            result["ignition"] = decoded["ignition"]
        elif identifier == DOOR_ID:
            result["door_mask"] = decode_doors(wire)
        else:
            decoded = decode_alert(wire)
            result.update(warning=decoded["warning"], data_fault=decoded["data_fault"],
                          reason_code=decoded["reason"])
        result["decode_status"] = "valid"
    except (ValueError, TypeError) as exc:
        result["decode_status"] = "invalid"
        result["decode_error"] = str(exc)
    return result


def _minute_stats(trace_id, frames, events):
    rows = {}

    def minute(index):
        if index not in rows:
            rows[index] = {
                "trace_id": trace_id, "minute_index": index,
                "frame_count": 0, "invalid_frame_count": 0,
                "unknown_frame_count": 0, "event_start_count": 0,
                "timeout_duration_us": 0, "speed_mean_kmh": None,
                "speed_max_kmh": None, "_speeds": [],
            }
        return rows[index]

    for frame in frames:
        row = minute(frame["timestamp_us"] // MINUTE_US)
        row["frame_count"] += 1
        row["invalid_frame_count"] += int(frame["decode_status"] == "invalid")
        row["unknown_frame_count"] += int(frame["decode_status"] == "unknown")
        if frame["speed_kmh"] is not None:
            row["_speeds"].append(frame["speed_kmh"])
    for event in events:
        minute(event["start_us"] // MINUTE_US)["event_start_count"] += 1
        if event["rule"] != "MESSAGE_TIMEOUT" or event["duration_us"] == 0:
            continue
        first = event["start_us"] // MINUTE_US
        last = (event["end_us"] - 1) // MINUTE_US
        for index in range(first, last + 1):
            overlap = min(event["end_us"], (index + 1) * MINUTE_US) - max(
                event["start_us"], index * MINUTE_US)
            minute(index)["timeout_duration_us"] += overlap
    output = []
    for index in sorted(rows):
        row = rows[index]
        speeds = row.pop("_speeds")
        if speeds:
            row["speed_mean_kmh"] = math.fsum(speeds) / len(speeds)
            row["speed_max_kmh"] = max(speeds)
        output.append(row)
    return output


def analyze_trace(trace, config=None):
    """Decode all accepted frames and evaluate three deterministic policy rules."""
    if config is None:
        config = RuleConfig()
    if not isinstance(config, RuleConfig):
        raise ValueError("config must be a RuleConfig")
    trace_id = trace["trace_id"]
    start_us, end_us = trace["start_us"], trace["end_us"]
    if (type(start_us) is not int or type(end_us) is not int or
            start_us < 0 or end_us < start_us):
        raise ValueError("trace bounds must be ordered nonnegative integer microseconds")
    frames = []
    previous_us = start_us
    for source in trace["frames"]:
        timestamp = source["timestamp_us"]
        if type(timestamp) is not int or not previous_us <= timestamp <= end_us:
            raise ValueError("frame timestamps must be ordered integer microseconds within trace bounds")
        previous_us = timestamp
        frames.append(_decode(source))
    if not frames:
        raise ValueError("trace must contain at least one accepted frame")

    events = []
    last_speed = {}
    rate_limit = Decimal(str(config.max_acceleration_kmh_s))
    for frame in frames:
        timestamp = frame["timestamp_us"]
        if frame["decode_status"] == "invalid":
            events.append(_event(trace_id, "SIGNAL_INVALID", frame, timestamp, timestamp,
                                 detail=frame["decode_error"]))
        if frame["can_id"] != VEHICLE_ID or frame["decode_status"] != "valid":
            continue
        channel = frame["channel"]
        previous = last_speed.get(channel)
        if previous is not None:
            elapsed = timestamp - previous["timestamp_us"]
            delta = abs(Decimal(str(frame["speed_kmh"])) - Decimal(str(previous["speed_kmh"])))
            detail = None
            if elapsed == 0 and delta != 0:
                detail = (f"Speed changed from {previous['speed_kmh']:g} to {frame['speed_kmh']:g} km/h "
                          "at the same timestamp; acceleration rate is undefined (dt=0 us).")
            elif 0 < elapsed <= config.timeout_us and delta * 1_000_000 > rate_limit * elapsed:
                rate = delta * 1_000_000 / elapsed
                detail = (f"Speed changed from {previous['speed_kmh']:g} to {frame['speed_kmh']:g} km/h "
                          f"over {elapsed} us; absolute rate {rate} km/h/s exceeds {rate_limit}.")
            if detail is not None:
                events.append(_event(trace_id, "SPEED_JUMP", frame, timestamp, timestamp,
                                     previous_frame_no=previous["frame_no"], detail=detail))
        last_speed[channel] = frame

    # Each expected signal has independent liveness, including a channel where
    # that ID never appeared. Invalid samples cannot refresh a signal.
    for channel in sorted(config.expected_channels):
        for identifier in (VEHICLE_ID, DOOR_ID):
            origin, anchor = start_us, None
            matching = (frame for frame in frames if frame["channel"] == channel and
                        frame["can_id"] == identifier and frame["decode_status"] == "valid")
            for recovery in matching:
                timeout_start = origin + config.timeout_us + 1
                if recovery["timestamp_us"] >= timeout_start:
                    events.append(_event(
                        trace_id, "MESSAGE_TIMEOUT", anchor, timeout_start, recovery["timestamp_us"],
                        can_id=identifier, channel=channel,
                        previous_frame_no=anchor["frame_no"] if anchor is not None else None,
                        recovery_frame_no=recovery["frame_no"],
                        detail=(f"0x{identifier:03X} channel {channel} exceeded {config.timeout_us} us "
                                f"freshness from {'trace start (no valid anchor)' if anchor is None else 'last valid frame'}; "
                                "a matching valid frame recovered the signal.")))
                origin, anchor = recovery["timestamp_us"], recovery
            timeout_start = origin + config.timeout_us + 1
            if timeout_start <= end_us:
                events.append(_event(
                    trace_id, "MESSAGE_TIMEOUT", anchor, timeout_start, end_us,
                    can_id=identifier, channel=channel,
                    previous_frame_no=anchor["frame_no"] if anchor is not None else None,
                    open_at_end=True,
                    detail=(f"0x{identifier:03X} channel {channel} exceeded {config.timeout_us} us "
                            f"freshness from {'trace start (no valid anchor)' if anchor is None else 'last valid frame'}; "
                            "no recovery was observed before the log ended.")))
    events.sort(key=lambda item: (item["start_us"], item["rule"], item["can_id"],
                                  item["channel"], item["frame_no"] or 0))
    return {"frames": frames, "events": events,
            "minute_stats": _minute_stats(trace_id, frames, events)}
