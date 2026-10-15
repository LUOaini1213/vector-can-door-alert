"""Deterministic signal-level controller; time is supplied by the test runner."""

from dataclasses import asdict, dataclass
from enum import IntEnum
from .protocol import DOOR_ID, VEHICLE_ID, decode_doors, decode_vehicle, require_time

TICK_MS = 10
FRESHNESS_MS = 300
DEBOUNCE_MS = 200
ON_SPEED_RAW = 500
OFF_SPEED_RAW = 300


class Reason(IntEnum):
    DATA_UNAVAILABLE = 1
    IGNITION_OFF = 2
    DOORS_CLOSED = 3
    BELOW_THRESHOLD = 4
    DEBOUNCING = 5
    WARNING_ACTIVE = 6


@dataclass(frozen=True)
class Snapshot:
    timestamp_ms: int
    warning: bool
    data_fault: bool
    reason: int
    speed_kmh: float | None
    door_mask: int | None
    pending_since_ms: int | None

    def to_dict(self):
        return asdict(self)


class Controller:
    def __init__(self):
        self._time = -1
        self._vehicle = None
        self._doors = None
        self._vehicle_at = None
        self._doors_at = None
        self._vehicle_valid = False
        self._doors_valid = False
        self.warning = False
        self.pending_since_ms = None

    def _advance(self, timestamp_ms):
        require_time(timestamp_ms)
        if timestamp_ms < self._time:
            raise ValueError("timestamps must not move backwards")
        self._time = timestamp_ms

    def receive(self, frame):
        self._advance(frame.timestamp_ms)
        if frame.arbitration_id == VEHICLE_ID:
            try:
                self._vehicle = decode_vehicle(frame)
            except ValueError:
                self._vehicle_valid = False
            else:
                self._vehicle_valid = True
                self._vehicle_at = frame.timestamp_ms
        elif frame.arbitration_id == DOOR_ID:
            try:
                self._doors = decode_doors(frame)
            except ValueError:
                self._doors_valid = False
            else:
                self._doors_valid = True
                self._doors_at = frame.timestamp_ms

    def tick(self, timestamp_ms):
        require_time(timestamp_ms)
        if timestamp_ms % TICK_MS:
            raise ValueError("controller ticks must be multiples of 10 ms")
        self._advance(timestamp_ms)
        vehicle_fresh = (self._vehicle_valid and self._vehicle_at is not None
                         and timestamp_ms - self._vehicle_at <= FRESHNESS_MS)
        doors_fresh = (self._doors_valid and self._doors_at is not None
                       and timestamp_ms - self._doors_at <= FRESHNESS_MS)
        fault = not (vehicle_fresh and doors_fresh)
        if fault:
            self.warning = False
            self.pending_since_ms = None
            reason = Reason.DATA_UNAVAILABLE
        elif not self._vehicle["ignition"]:
            self.warning = False
            self.pending_since_ms = None
            reason = Reason.IGNITION_OFF
        elif self._doors == 0:
            self.warning = False
            self.pending_since_ms = None
            reason = Reason.DOORS_CLOSED
        elif self.warning:
            if self._vehicle["speed_raw"] <= OFF_SPEED_RAW:
                self.warning = False
                self.pending_since_ms = None
                reason = Reason.BELOW_THRESHOLD
            else:
                reason = Reason.WARNING_ACTIVE
        elif self._vehicle["speed_raw"] >= ON_SPEED_RAW:
            if self.pending_since_ms is None:
                self.pending_since_ms = timestamp_ms
            if timestamp_ms - self.pending_since_ms >= DEBOUNCE_MS:
                self.warning = True
                self.pending_since_ms = None
                reason = Reason.WARNING_ACTIVE
            else:
                reason = Reason.DEBOUNCING
        else:
            self.pending_since_ms = None
            reason = Reason.BELOW_THRESHOLD
        return Snapshot(timestamp_ms, self.warning, fault, int(reason),
                        self._vehicle["speed_raw"] / 100 if vehicle_fresh else None,
                        self._doors if doors_fresh else None, self.pending_since_ms)
