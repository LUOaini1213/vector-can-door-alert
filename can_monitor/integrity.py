"""Independent SQL reconciliation of published monitor tables.

These checks compare the database layers. They do not authenticate an ASC file
or prove that a stored signal was decoded from its original source bytes.
"""

import math

from .limits import check_trace_span


MINUTE_US = 60_000_000
CHECK_NAMES = (
    "frame_count_balanced", "event_count_balanced", "rejected_count_balanced",
    "timeout_duration_balanced", "event_frame_references_valid",
    "event_intervals_in_log", "frame_intervals_in_log", "minute_metrics_balanced",
)


def _same_number(actual, expected):
    if actual is None or expected is None:
        return actual is None and expected is None
    return (math.isfinite(actual) and math.isfinite(expected)
            and math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-9))


def validate_trace(con, trace_id):
    """Return named consistency checks, using SQL independent of the engine.

    Minute expansion is bounded by the validated trace span (24 hours), rather
    than by event endpoints or persisted minute indexes, which may be damaged.
    """
    failed = {"trace_id": trace_id, **dict.fromkeys(CHECK_NAMES, False)}
    trace = con.execute(
        "SELECT start_us,end_us,frame_count,event_count,rejected_line_count "
        "FROM mon.traces WHERE trace_id=?", [trace_id]).fetchone()
    if trace is None:
        return failed
    start, end, expected_frames, expected_events, expected_rejected = trace
    try:
        check_trace_span(start, end)
    except ValueError:
        return failed

    frame_count, frames_in_log = con.execute(
        "SELECT count(*), coalesce(bool_and(timestamp_us BETWEEN ? AND ?),false) "
        "FROM mon.frames WHERE trace_id=?", [start, end, trace_id]).fetchone()
    event_count, timeout_duration, intervals_ok = con.execute(
        "SELECT count(*),coalesce(sum(duration_us) FILTER (WHERE rule='MESSAGE_TIMEOUT'),0),"
        "coalesce(bool_and(start_us>=? AND start_us<=end_us AND end_us<=? "
        "AND duration_us=end_us-start_us),true) FROM mon.events WHERE trace_id=?",
        [start, end, trace_id]).fetchone()
    rejected_count = con.execute(
        "SELECT count(*) FROM mon.rejected_lines WHERE trace_id=?", [trace_id]).fetchone()[0]
    minute_frames, minute_events, minute_timeout = con.execute(
        "SELECT coalesce(sum(frame_count),0),coalesce(sum(event_start_count),0),"
        "coalesce(sum(timeout_duration_us),0) FROM mon.minute_stats WHERE trace_id=?",
        [trace_id]).fetchone()
    references_ok = con.execute(
        "SELECT NOT EXISTS (SELECT 1 FROM mon.events e, "
        "unnest([e.frame_no,e.previous_frame_no,e.recovery_frame_no]) r(frame_no) "
        "WHERE e.trace_id=? AND r.frame_no IS NOT NULL AND NOT EXISTS "
        "(SELECT 1 FROM mon.frames f WHERE f.trace_id=e.trace_id AND f.frame_no=r.frame_no))",
        [trace_id]).fetchone()[0]

    # range has at most 1,441 entries: the independent bound was checked above.
    # Empty minutes are published only when frames, event starts, or positive
    # timeout overlap require them, matching the documented sparse table grain.
    expected_minutes = con.execute("""
        WITH buckets AS (
            SELECT unnest(range(?,?)) AS minute_index
        ), frames AS (
            SELECT timestamp_us // 60000000 AS minute_index,
                   count(*) AS frame_count,
                   count(*) FILTER (WHERE decode_status='invalid') AS invalid_frame_count,
                   count(*) FILTER (WHERE decode_status='unknown') AS unknown_frame_count,
                   avg(speed_kmh) AS speed_mean_kmh,max(speed_kmh) AS speed_max_kmh
            FROM mon.frames WHERE trace_id=? GROUP BY 1
        ), starts AS (
            SELECT start_us // 60000000 AS minute_index,count(*) AS event_start_count
            FROM mon.events WHERE trace_id=? GROUP BY 1
        ), timeouts AS (
            SELECT b.minute_index,
                   sum(least(e.end_us,(b.minute_index+1)*60000000)
                       - greatest(e.start_us,b.minute_index*60000000)) AS timeout_duration_us
            FROM buckets b JOIN mon.events e
              ON e.trace_id=? AND e.rule='MESSAGE_TIMEOUT'
             AND e.start_us<e.end_us
             AND e.start_us<(b.minute_index+1)*60000000
             AND e.end_us>b.minute_index*60000000
            GROUP BY 1
        ), indexes AS (
            SELECT minute_index FROM frames UNION SELECT minute_index FROM starts
            UNION SELECT minute_index FROM timeouts
        )
        SELECT i.minute_index,coalesce(f.frame_count,0),coalesce(f.invalid_frame_count,0),
               coalesce(f.unknown_frame_count,0),coalesce(s.event_start_count,0),
               coalesce(t.timeout_duration_us,0),f.speed_mean_kmh,f.speed_max_kmh
        FROM indexes i LEFT JOIN frames f USING (minute_index)
        LEFT JOIN starts s USING (minute_index) LEFT JOIN timeouts t USING (minute_index)
        ORDER BY i.minute_index
        """, [start // MINUTE_US, end // MINUTE_US + 1, trace_id, trace_id, trace_id]).fetchall()
    actual_minutes = con.execute(
        "SELECT minute_index,frame_count,invalid_frame_count,unknown_frame_count,"
        "event_start_count,timeout_duration_us,speed_mean_kmh,speed_max_kmh "
        "FROM mon.minute_stats WHERE trace_id=? ORDER BY minute_index", [trace_id]).fetchall()
    minutes_ok = len(actual_minutes) == len(expected_minutes) and all(
        actual[:6] == expected[:6] and _same_number(actual[6], expected[6])
        and _same_number(actual[7], expected[7])
        for actual, expected in zip(actual_minutes, expected_minutes))
    return {
        "trace_id": trace_id,
        "frame_count_balanced": expected_frames == frame_count == minute_frames,
        "event_count_balanced": expected_events == event_count == minute_events,
        "rejected_count_balanced": expected_rejected == rejected_count,
        "timeout_duration_balanced": timeout_duration == minute_timeout,
        "event_frame_references_valid": references_ok,
        "event_intervals_in_log": intervals_ok,
        "frame_intervals_in_log": frames_in_log,
        "minute_metrics_balanced": minutes_ok,
    }


def checks_pass(checks):
    """Require every fixed check; trace_id is metadata, never a truth value."""
    return all(checks.get(name) is True for name in CHECK_NAMES)
