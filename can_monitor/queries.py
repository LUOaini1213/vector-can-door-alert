"""Short-lived read-only, parameterized queries for the offline monitor UI."""

from pathlib import Path
import duckdb


class MonitorQueries:
    def __init__(self, db_path):
        if not Path(db_path).is_file():
            raise FileNotFoundError("Run python -m can_monitor demo to create the monitor database")
        self.con = duckdb.connect(str(db_path), read_only=True)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self.con.close()

    def _rows(self, sql, args=None):
        result = self.con.execute(sql, args or [])
        return [dict(zip([d[0] for d in result.description], row)) for row in result.fetchall()]

    def traces(self):
        return self._rows("SELECT * FROM mon.traces ORDER BY trace_id")

    def frames(self, trace_id, start_us=None, end_us=None):
        conditions, args = ["trace_id=?"], [trace_id]
        if start_us is not None:
            conditions.append("timestamp_us>=?"); args.append(start_us)
        if end_us is not None:
            conditions.append("timestamp_us<=?"); args.append(end_us)
        return self._rows("SELECT * FROM mon.frames WHERE " + " AND ".join(conditions)
                          + " ORDER BY frame_no", args)

    def events(self, trace_id, rule=None, start_us=None, end_us=None):
        conditions, args = ["trace_id=?"], [trace_id]
        if rule is not None:
            conditions.append("rule=?"); args.append(rule)
        if start_us is not None:
            conditions.append("end_us>=?"); args.append(start_us)
        if end_us is not None:
            conditions.append("start_us<=?"); args.append(end_us)
        return self._rows("SELECT * FROM mon.events WHERE " + " AND ".join(conditions)
                          + " ORDER BY start_us,rule,can_id,channel,event_id", args)

    def minute_stats(self, trace_id):
        return self._rows("SELECT * FROM mon.minute_stats WHERE trace_id=? ORDER BY minute_index", [trace_id])

    def rejected_lines(self, trace_id):
        return self._rows("SELECT * FROM mon.rejected_lines WHERE trace_id=? ORDER BY line_number", [trace_id])

    def context(self, trace_id, event_id, before_us=200_000, after_us=200_000):
        if (type(before_us) is not int or type(after_us) is not int or before_us < 0 or after_us < 0):
            raise ValueError("context windows must be nonnegative integer microseconds")
        events = self._rows("SELECT * FROM mon.events WHERE trace_id=? AND event_id=?", [trace_id, event_id])
        if not events:
            raise ValueError("event not found in the selected trace")
        event = events[0]
        anchors = {event.get(key) for key in ("frame_no", "previous_frame_no", "recovery_frame_no")}
        anchors.discard(None)
        start, end = max(0, event["start_us"] - before_us), event["start_us"] + after_us
        if anchors:
            placeholders = ",".join("?" for _ in anchors)
            return self._rows("SELECT * FROM mon.frames WHERE trace_id=? AND "
                              f"((timestamp_us BETWEEN ? AND ?) OR frame_no IN ({placeholders})) ORDER BY frame_no",
                              [trace_id, start, end, *sorted(anchors)])
        return self.frames(trace_id, start, end)
