# Shared implementation contract

This file fixes interfaces while the Python runner, independent tests, CAPL adapter,
and learning documents are authored in parallel. Canonical behavior is specified below.

## Scope and evidence

An educational simulation of an in-motion open-door warning. Thresholds are invented
teaching requirements, not OEM calibration or a certified safety specification.
Python is runnable without CANoe. CAPL files are integration sources until compiled
and executed in a suitable CANoe installation. Never label Python runs as CANoe runs.

## CAN frames

Classic standard-ID CAN, all three messages have DLC 8, Intel/little-endian.
VehicleStatus 0x100: speed raw uint16 in bytes 0/1, factor 0.01 km/h,
physical range 0..250; byte 2 ignition, only 0 or 1 valid. Other bytes unused.
DoorStatus 0x101: byte 0 mask bits 0..3 correspond to FL/FR/RL/RR open,
mask 0..15 valid; high bits set are invalid. Other bytes unused.
AlertStatus 0x200: byte 0 warning (0/1), byte 1 data_fault (0/1),
byte 2 reason code, bytes 3..7 zero.
Malformed DLC or invalid payload immediately invalidates that input stream until
a valid frame for that same ID arrives. Unknown IDs are ignored.

## Timing and state

Parameters: on threshold 5.00 km/h inclusive, off threshold 3.00 km/h inclusive,
continuous on-debounce 200 ms, freshness timeout 300 ms, controller tick 10 ms.
Evaluation is at each 10-ms tick including t=0. All input frames at that exact
time are received before tick evaluation. Scenario event times must be nonnegative
integer multiples of 10, duration_ms also a multiple of 10.
Input is fresh when last_valid_time exists, stream is valid, and age <=300 ms;
at age 310 ms it is stale. Last frame of one ID at the same timestamp wins.
At initialization there is no valid input, warning=0 data_fault=1 reason=1.
All timestamps are integer milliseconds; they must not move backwards.

Evaluation priority:
1. Either input missing/invalid/stale: warning=0, data_fault=1,
   pending cleared, reason=1 DATA_UNAVAILABLE.
2. Both fresh and ignition=0: warning=0, data_fault=0, pending cleared,
   reason=2 IGNITION_OFF.
3. Both fresh and all doors closed: warning=0, data_fault=0, pending cleared,
   reason=3 DOORS_CLOSED.
4. warning already active: speed<=3 clears warning and pending, reason=4
   BELOW_THRESHOLD; otherwise warning remains 1 with reason=6 WARNING_ACTIVE.
5. warning inactive: speed>=5 starts or continues pending. At elapsed>=200,
   warning=1, pending cleared, reason=6. Before that reason=5 DEBOUNCING.
   Speed<5 resets pending, warning=0 reason=4 (including the 3..5 deadband).
Hysteresis holds an active warning in 3<speed<5. Door closing and ignition off
clear immediately on the next evaluated tick. Data-fault clears when both inputs
are valid and fresh; warning then needs a new 200-ms debounce.

## Python API

door_alert.protocol.Frame(timestamp_ms:int, arbitration_id:int, data:bytes)
encode_vehicle(timestamp_ms, speed_kmh, ignition)->Frame
encode_doors(timestamp_ms, door_mask)->Frame
encode_alert(timestamp_ms, warning, data_fault, reason)->Frame
decode_vehicle(frame)->dict {speed_raw:int, ignition:bool}; invalid raises ValueError.
decode_doors(frame)->int; invalid raises ValueError.
decode_alert(frame)->dict {warning:bool,data_fault:bool,reason:int}.

door_alert.controller.Controller(): receive(frame)->None; tick(timestamp_ms)->Snapshot
Snapshot fields: timestamp_ms, warning(bool), data_fault(bool), reason(int),
speed_kmh(float|None), door_mask(int|None), pending_since_ms(int|None).
Every tick returns a Snapshot. receive/tick reject backward timestamps with ValueError.
Use integer raw-speed comparisons (500/300), avoiding float threshold drift.

door_alert.scenarios.load_scenarios(path)->list[dict]
run_scenario(scenario, controller_factory=Controller)->dict
Scenario keys: id,title,requirements(list[str]),duration_ms,events,assertions.
Events use at_ms and either:
- kind='vehicle', speed_kmh number, ignition boolean;
- kind='doors', door_mask integer 0..15;
- kind='raw', arbitration_id integer, data_hex string, for injected bad frames.
Events can have period_ms and until_ms (inclusive) for repeated transmission.
An assertion uses at_ms, warning boolean, data_fault boolean, reason optional integer.
Result keys id,title,requirements,passed,assertions(list with expected/actual/passed),
trace(list of Snapshot dicts), input_frames(list of Frame dicts with data_hex).

CLI: python -m door_alert demo --output reports/demo
python -m door_alert run --scenarios data/scenarios.json --output reports/latest
python -m unittest discover -s tests -v
CLI returns nonzero when assertions fail; reports JSON, HTML, CSV and ASC.

## Repository layout

`door_alert/` contains the executable reference model; `tests/` and
`data/scenarios.json` contain explicit expected results. `canoe/` contains the
integration sources and `docs/` contains requirements and learning material.
