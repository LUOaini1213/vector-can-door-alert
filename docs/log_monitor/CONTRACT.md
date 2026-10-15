# Offline CAN log monitor contract

New AI-assisted educational extension, 2026-10-15. Use existing synthetic ASC
traces. Do not claim physical bus, OEM, CANoe/CAPL or production validation.
Existing standard-library door_alert runtime/tests remain dependency-free.
New code is can_monitor/, optional requirements-monitor.txt, monitor_app.py,
tests_monitor/, reports/log_monitor/. Use DuckDB 1.5.6, python-can 4.6.1 only for
independent parsing checks, Streamlit for local UI; no network service required.

## Parser interface

`from can_monitor.parser import read_asc`
`read_asc(path, trace_id=None, provenance='user-provided-unverified') -> dict`
Provenance is restricted to synthetic or user-provided-unverified.
Reads a byte snapshot, hashes original bytes, parses the supported classic CAN
standard-ID ASC subset: `base hex timestamps absolute`, direction Rx/Tx, data d,
DLC 0..8, hex ID 0..7ff and exact payload length. No CAN FD, remote, extended-ID,
relative-timestamp or generic vendor format claims. UTF-8/BOM accepted; malformed
candidate/unsupported records retained in rejected_lines; invalid header, backwards
accepted timestamps or no accepted frames raise ValueError. File order and identical
frames retained. Timestamps must be nonnegative exact integer microseconds.

Returned dict keys:
- trace_id: safe [A-Za-z0-9][A-Za-z0-9_.-]{0,63}; source_name (basename),
  source_sha256, provenance, start_us, end_us.
- frames: ordered list, each has frame_no (1-based accepted ordinal), line_number
  (1-based physical file line), timestamp_us, can_id, channel (positive int),
  direction, dlc, data_hex (uppercase space separated), raw_line.
- rejected_lines: each line_number, raw_line, reason.

## Engine

`RuleConfig(timeout_ms=300, max_acceleration_kmh_s=100.0, expected_channels=(1,))`
is a frozen dataclass; validate finite positive timeout/rate and positive distinct
integer channels. `analyze_trace(trace, config=None)->dict` returns `frames` (all
input keys + decode_status/decode_error/speed_kmh/ignition/door_mask/warning/
data_fault/reason_code), `events`, `minute_stats`. Use door_alert.protocol
decoders matching the fixed data/body_control.dbc. Unknown IDs preserved with
decode_status='unknown'; valid='valid'; known malformed payload='invalid'.

Rules are teaching policies, not vehicle safety or fault diagnoses:
- SIGNAL_INVALID: one zero-duration point event for each invalid known frame.
- SPEED_JUMP: known valid 0x100 samples on same channel, compare consecutive
  valid speeds only when 0 < dt <= timeout_ms; abs(delta)/dt_seconds > configured
  rate. Equality does not trigger. At dt=0, changed speed triggers with explanatory
  detail and undefined rate; unchanged duplicate does not. Longer gaps restart
  speed baseline. Invalid samples do not update last-valid state.
- MESSAGE_TIMEOUT: independently for 0x100/0x101 on expected_channels only. Fresh
  age <= timeout_ms. At integer-microsecond precision first timeout starts at
  last_valid_us + timeout_ms*1000 + 1. Before first valid frame use trace.start_us
  as grace-period origin. Recover only on a valid frame of matching ID+channel.
  Cap open interval at trace.end_us; open_at_end=True means no recovery observed,
  not a claim about future duration. Do not manufacture time after log end.

Every event: event_id deterministic string, trace_id, rule, severity,
can_id, channel, start_us, end_us, duration_us=end-start, open_at_end,
frame_no (triggering invalid/speed frame, or last-valid timeout anchor; nullable
if no valid anchor), previous_frame_no (speed comparison/timeout anchor, nullable),
recovery_frame_no (timeout valid recovery, nullable), detail (human readable).
Events sorted by start_us/rule/can_id/channel/frame_no. Preserve source references.

Minute rows: trace_id,minute_index=floor(timestamp_us/60000000),frame_count,
invalid_frame_count,unknown_frame_count,event_start_count,timeout_duration_us,
speed_mean_kmh,speed_max_kmh. For timeout duration, sum overlap of each timeout
interval with each minute; separate ID/channel durations add (signal-time, not
unique wall-clock outage). Count point event starts exactly once. Frame totals
sum to accepted raw frames. Do not interpolate signals across gaps.

## Persistence and queries

`MonitorStore(db_path)` context manager exposes `.con`.
`.ingest(trace, config=None, failpoint=None)->dict` with status loaded/skipped,
trace_id, fingerprint, frame_count,event_count,rejected_line_count.
`.ingest` uses source SHA + config + parser/engine/store/protocol/DBC/schema code
fingerprint. Same trace_id and fingerprint skips; changed input/config/model
atomically replaces only that trace; another trace untouched. failpoint='after_delete'
raises RuntimeError and rolls back published data; FAILED audit survives.

Tables mon.traces,mon.frames,mon.rejected_lines,mon.events,mon.minute_stats,
mon.runs. Column names match parser+engine dicts, except:
mon.frames uses physical_line instead of line_number;
mon.rejected_lines uses line_number;
mon.traces includes frame_count,event_count,rejected_line_count,fingerprint,
config_json plus parser metadata above (no frames/rejected_lines arrays).
mon.runs: run_id,trace_id,status,source_sha256,fingerprint,started_at,finished_at,message.
No SQL interpolation of user path/trace_id. UI is read-only and opens a short-lived
read_only DuckDB connection per rerun. Import is CLI only; do not cache connections.

## Query interface

`MonitorQueries(db_path)` context manager, read-only `.con`.
`.traces()->list[dict]` all mon.traces metadata sorted trace_id.
`.frames(trace_id,start_us=None,end_us=None)->list[dict]` inclusive time range.
`.events(trace_id,rule=None,start_us=None,end_us=None)->list[dict]` interval overlap
inclusive at boundaries for exploration (duration uses half-open interval math).
`.minute_stats(trace_id)->list[dict]` ordered minute_index.
`.context(trace_id,event_id,before_us=200000,after_us=200000)->list[dict]` union
time context around event onset and all explicit anchor/trigger/recovery frames;
must include far-away recovery even if outside onset window.
`.rejected_lines(trace_id)->list[dict]` ordered line_number.

## UI

Chinese local Streamlit UI. Main scenario selectbox, rule filter, time slider,
metrics, speed chart with real sparse timestamps, event list and event selector,
context table showing raw lines/physical line numbers and cause/recovery flags,
minute stats chart/table, rejected-lines table, raw-frame CSV download.
Database from env CAN_MONITOR_DB or ROOT/artifacts/log_monitor.duckdb. Friendly
missing DB instructions. No arbitrary SQL editor, upload or implicit import.
Timestamp axis uses relative log seconds, not wall-clock dates. All visible text
distinguishes monitor rule events, controller warning output and synthetic traces.
