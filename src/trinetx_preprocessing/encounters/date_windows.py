"""Calendar-day windows for the legacy daily encounter anchor.

Source timestamps and their precision are retained in evidence. These wrappers
make daily upper/lower bounds explicit without inventing an encounter time.
As in the original date-only medication rule, anchor-day starts can be both
pre-index and follow-up evidence; downstream analyses must choose their estimand.
"""

from ..clinical_sources.sql_helpers import (
    inclusive_datetime_end_sql,
    minimum_separation_sql,
    timestamp_precision_sql,
)
from ..clinical_sources.sql_helpers import (
    inclusive_followup_end_sql as _followup_end,
)
from ..clinical_sources.sql_helpers import (
    inclusive_followup_start_sql as _followup_start,
)
from ..clinical_sources.sql_helpers import (
    inclusive_lookback_start_sql as _lookback_start,
)

__all__ = [
    "inclusive_datetime_end_sql",
    "minimum_separation_sql",
    "timestamp_precision_sql",
    "inclusive_followup_end_sql",
    "inclusive_followup_start_sql",
    "inclusive_lookback_start_sql",
]


def inclusive_lookback_start_sql(event, precision, anchor, days):
    return _lookback_start(f"({event})::DATE", "'date_only'", anchor, days)


def inclusive_followup_end_sql(event, precision, anchor, days):
    return _followup_end(f"({event})::DATE", "'date_only'", anchor, days)


def inclusive_followup_start_sql(event, precision, anchor):
    return _followup_start(f"({event})::DATE", "'date_only'", anchor)
