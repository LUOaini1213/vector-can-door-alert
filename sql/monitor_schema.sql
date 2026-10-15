CREATE SCHEMA IF NOT EXISTS mon;

CREATE TABLE IF NOT EXISTS mon.traces (
    trace_id VARCHAR PRIMARY KEY,
    source_name VARCHAR NOT NULL,
    source_sha256 VARCHAR NOT NULL,
    provenance VARCHAR NOT NULL,
    start_us BIGINT NOT NULL,
    end_us BIGINT NOT NULL,
    frame_count BIGINT NOT NULL,
    event_count BIGINT NOT NULL,
    rejected_line_count BIGINT NOT NULL,
    fingerprint VARCHAR NOT NULL,
    config_json VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS mon.frames (
    trace_id VARCHAR NOT NULL,
    frame_no BIGINT NOT NULL,
    physical_line BIGINT NOT NULL,
    timestamp_us BIGINT NOT NULL,
    can_id INTEGER NOT NULL,
    channel INTEGER NOT NULL,
    direction VARCHAR NOT NULL,
    dlc INTEGER NOT NULL,
    data_hex VARCHAR NOT NULL,
    raw_line VARCHAR NOT NULL,
    decode_status VARCHAR NOT NULL,
    decode_error VARCHAR,
    speed_kmh DOUBLE,
    ignition BOOLEAN,
    door_mask INTEGER,
    warning BOOLEAN,
    data_fault BOOLEAN,
    reason_code INTEGER,
    PRIMARY KEY (trace_id, frame_no)
);

CREATE TABLE IF NOT EXISTS mon.rejected_lines (
    trace_id VARCHAR NOT NULL,
    line_number BIGINT NOT NULL,
    raw_line VARCHAR NOT NULL,
    reason VARCHAR NOT NULL,
    PRIMARY KEY (trace_id, line_number)
);

CREATE TABLE IF NOT EXISTS mon.events (
    event_id VARCHAR PRIMARY KEY,
    trace_id VARCHAR NOT NULL,
    rule VARCHAR NOT NULL,
    severity VARCHAR NOT NULL,
    can_id INTEGER NOT NULL,
    channel INTEGER NOT NULL,
    start_us BIGINT NOT NULL,
    end_us BIGINT NOT NULL,
    duration_us BIGINT NOT NULL,
    open_at_end BOOLEAN NOT NULL,
    frame_no BIGINT,
    previous_frame_no BIGINT,
    recovery_frame_no BIGINT,
    detail VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS mon.minute_stats (
    trace_id VARCHAR NOT NULL,
    minute_index BIGINT NOT NULL,
    frame_count BIGINT NOT NULL,
    invalid_frame_count BIGINT NOT NULL,
    unknown_frame_count BIGINT NOT NULL,
    event_start_count BIGINT NOT NULL,
    timeout_duration_us BIGINT NOT NULL,
    speed_mean_kmh DOUBLE,
    speed_max_kmh DOUBLE,
    PRIMARY KEY (trace_id, minute_index)
);

CREATE TABLE IF NOT EXISTS mon.runs (
    run_id VARCHAR PRIMARY KEY,
    trace_id VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    source_sha256 VARCHAR NOT NULL,
    fingerprint VARCHAR NOT NULL,
    started_at TIMESTAMP NOT NULL,
    finished_at TIMESTAMP,
    message VARCHAR NOT NULL
);
