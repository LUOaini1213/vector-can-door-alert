"""Transactional content-addressed DuckDB publication for offline CAN traces."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid

import duckdb

from .engine import RuleConfig, analyze_trace


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "sql" / "monitor_schema.sql"
MODEL_FILES = (
    "can_monitor/parser.py", "can_monitor/engine.py", "can_monitor/store.py",
    "door_alert/protocol.py", "data/body_control.dbc", "sql/monitor_schema.sql",
)


def _utcnow():
    # UTC timestamps are persisted as explicitly UTC-derived naive TIMESTAMPs.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def model_fingerprint():
    """Hash exact original model bytes, with path boundaries included."""
    digest = hashlib.sha256()
    for relative in MODEL_FILES:
        content = (ROOT / relative).read_bytes()
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _fingerprint(trace, config):
    # Metadata is included too: changing a label/provenance must not silently
    # skip and leave an old label next to otherwise identical source bytes.
    identity = {
        "source_sha256": trace["source_sha256"],
        "source_name": trace["source_name"], "provenance": trace["provenance"],
        "config": config.as_dict(), "model_sha256": model_fingerprint(),
    }
    return hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _insert_many(con, table, columns, rows):
    if not rows:
        return
    # table/column identifiers come only from the fixed code below. User data is
    # always passed separately, including trace IDs and raw ASC lines.
    placeholders = ",".join("?" for _ in columns)
    con.executemany(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})",
                    [[row.get(column) for column in columns] for row in rows])


class MonitorStore:
    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(str(self.db_path))
        try:
            self.con.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
        except Exception:
            self.con.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self):
        self.con.close()

    def ingest(self, trace, config=None, failpoint=None):
        if config is None:
            config = RuleConfig()
        if not isinstance(config, RuleConfig):
            raise ValueError("config must be a RuleConfig")
        if failpoint not in (None, "after_delete"):
            raise ValueError("unknown failpoint")
        trace_id = trace["trace_id"]
        fingerprint = _fingerprint(trace, config)
        run_id = str(uuid.uuid4())
        self.con.execute("INSERT INTO mon.runs VALUES (?, ?, 'RUNNING', ?, ?, ?, NULL, '')",
                         [run_id, trace_id, trace["source_sha256"], fingerprint, _utcnow()])
        transaction_open = False
        try:
            prior = self.con.execute(
                "SELECT fingerprint,frame_count,event_count,rejected_line_count FROM mon.traces WHERE trace_id=?",
                [trace_id]).fetchone()
            if prior is not None and prior[0] == fingerprint:
                self.con.execute("UPDATE mon.runs SET status='SKIPPED',finished_at=?,message=? WHERE run_id=?",
                                 [_utcnow(), "identical source, configuration and model fingerprint", run_id])
                return {"status": "skipped", "trace_id": trace_id, "fingerprint": fingerprint,
                        "frame_count": prior[1], "event_count": prior[2], "rejected_line_count": prior[3]}

            analysis = analyze_trace(trace, config)
            frames, events = analysis["frames"], analysis["events"]
            rejected = trace["rejected_lines"]
            self.con.execute("BEGIN TRANSACTION")
            transaction_open = True
            for table in ("mon.frames", "mon.rejected_lines", "mon.events", "mon.minute_stats", "mon.traces"):
                self.con.execute(f"DELETE FROM {table} WHERE trace_id=?", [trace_id])
            if failpoint == "after_delete":
                raise RuntimeError("injected failure after_delete")

            metadata = {key: trace[key] for key in (
                "trace_id", "source_name", "source_sha256", "provenance", "start_us", "end_us")}
            metadata.update(frame_count=len(frames), event_count=len(events),
                            rejected_line_count=len(rejected), fingerprint=fingerprint,
                            config_json=json.dumps(config.as_dict(), sort_keys=True, separators=(",", ":")))
            _insert_many(self.con, "mon.traces", (
                "trace_id", "source_name", "source_sha256", "provenance", "start_us", "end_us",
                "frame_count", "event_count", "rejected_line_count", "fingerprint", "config_json"), [metadata])
            stored_frames = [{**frame, "trace_id": trace_id, "physical_line": frame["line_number"]}
                             for frame in frames]
            _insert_many(self.con, "mon.frames", (
                "trace_id", "frame_no", "physical_line", "timestamp_us", "can_id", "channel", "direction",
                "dlc", "data_hex", "raw_line", "decode_status", "decode_error", "speed_kmh", "ignition",
                "door_mask", "warning", "data_fault", "reason_code"), stored_frames)
            _insert_many(self.con, "mon.rejected_lines", ("trace_id", "line_number", "raw_line", "reason"),
                         [{**row, "trace_id": trace_id} for row in rejected])
            _insert_many(self.con, "mon.events", (
                "event_id", "trace_id", "rule", "severity", "can_id", "channel", "start_us", "end_us",
                "duration_us", "open_at_end", "frame_no", "previous_frame_no", "recovery_frame_no", "detail"), events)
            _insert_many(self.con, "mon.minute_stats", (
                "trace_id", "minute_index", "frame_count", "invalid_frame_count", "unknown_frame_count",
                "event_start_count", "timeout_duration_us", "speed_mean_kmh", "speed_max_kmh"),
                         analysis["minute_stats"])
            # A COMPLETED run and all published rows share one commit. The
            # RUNNING audit was committed before BEGIN and can survive rollback.
            self.con.execute("UPDATE mon.runs SET status='COMPLETED',finished_at=?,message=? WHERE run_id=?",
                             [_utcnow(), "trace published atomically", run_id])
            self.con.execute("COMMIT")
            transaction_open = False
            return {"status": "loaded", "trace_id": trace_id, "fingerprint": fingerprint,
                    "frame_count": len(frames), "event_count": len(events), "rejected_line_count": len(rejected)}
        except Exception as exc:
            if transaction_open:
                self.con.execute("ROLLBACK")
            self.con.execute("UPDATE mon.runs SET status='FAILED',finished_at=?,message=? WHERE run_id=?",
                             [_utcnow(), f"{type(exc).__name__}: {exc}", run_id])
            raise
