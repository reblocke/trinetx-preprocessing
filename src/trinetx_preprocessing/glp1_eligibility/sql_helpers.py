"""Small SQL fragments shared by GLP-1 phenotype builders."""

from __future__ import annotations


def raw_date_is_date_only_sql(expression: str) -> str:
    """Return SQL identifying supported date-only source representations."""

    value = f"trim(coalesce(cast({expression} AS VARCHAR), ''))"
    return (
        f"(regexp_full_match({value}, '\\d{{8}}') OR "
        f"regexp_full_match({value}, '\\d{{4}}-\\d{{2}}-\\d{{2}}'))"
    )


def timestamp_precision_sql(expression: str) -> str:
    """Return SQL classifying a raw source date as date-only or timestamped."""

    return (
        f"CASE WHEN {raw_date_is_date_only_sql(expression)} "
        "THEN 'date_only' ELSE 'timestamp' END"
    )


def inclusive_lookback_start_sql(
    event_datetime: str,
    precision: str,
    index_datetime: str,
    lookback_days: int,
) -> str:
    """Return a lookback lower bound that preserves source date precision."""

    if lookback_days < 0:
        raise ValueError("lookback_days must be nonnegative")
    return f"""(
        {event_datetime} >= {index_datetime} - INTERVAL {lookback_days} DAY
        OR (
            ({precision}) = 'date_only'
            AND {event_datetime}::DATE >=
                ({index_datetime}::DATE - INTERVAL {lookback_days} DAY)::DATE
        )
    )"""


def inclusive_followup_end_sql(
    event_datetime: str,
    precision: str,
    index_datetime: str,
    followup_days: int,
) -> str:
    """Return a follow-up upper bound that preserves source date precision."""

    if followup_days < 0:
        raise ValueError("followup_days must be nonnegative")
    return f"""(
        {event_datetime} <= {index_datetime} + INTERVAL {followup_days} DAY
        OR (
            ({precision}) = 'date_only'
            AND {event_datetime}::DATE <=
                ({index_datetime}::DATE + INTERVAL {followup_days} DAY)::DATE
        )
    )"""


def inclusive_followup_start_sql(
    event_datetime: str,
    precision: str,
    index_datetime: str,
) -> str:
    """Return a post-index lower bound that preserves source date precision."""

    return f"""(
        {event_datetime} > {index_datetime}
        OR (
            ({precision}) = 'date_only'
            AND {event_datetime}::DATE >= {index_datetime}::DATE
        )
    )"""


def minimum_separation_sql(
    start_datetime: str,
    start_precision: str,
    end_datetime: str,
    end_precision: str,
    minimum_days: int,
) -> str:
    """Return a minimum interval test that preserves source date precision."""

    if minimum_days < 0:
        raise ValueError("minimum_days must be nonnegative")
    return f"""(
        {start_datetime} IS NOT NULL
        AND {end_datetime} IS NOT NULL
        AND CASE
            WHEN ({start_precision}) = 'date_only'
              OR ({end_precision}) = 'date_only'
            THEN datediff(
                'day', {start_datetime}::DATE, {end_datetime}::DATE
            ) >= {minimum_days}
            ELSE {end_datetime} >=
                {start_datetime} + INTERVAL {minimum_days} DAY
        END
    )"""


def inclusive_datetime_end_sql(
    end_datetime: str,
    precision: str,
    fallback: str,
) -> str:
    """Return an inclusive timestamp bound that respects date-only end values."""

    return (
        "CASE "
        f"WHEN {end_datetime} IS NULL THEN {fallback} "
        f"WHEN {precision} = 'date_only' THEN "
        f"{end_datetime} + INTERVAL 1 DAY - INTERVAL 1 MICROSECOND "
        f"ELSE {end_datetime} END"
    )
