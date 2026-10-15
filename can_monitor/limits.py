"""Explicit offline-analysis limits shared by parsing and direct API callers."""


MAX_TRACE_SPAN_US = 24 * 60 * 60 * 1_000_000


def check_trace_span(start_us, end_us):
    """Reject invalid bounds or spans that could expand into unbounded minute rows."""
    if (type(start_us) is not int or type(end_us) is not int or
            start_us < 0 or end_us < start_us or
            end_us - start_us > MAX_TRACE_SPAN_US):
        raise ValueError(
            "trace bounds must be ordered nonnegative integer microseconds "
            "with a maximum span of 24 hours"
        )
