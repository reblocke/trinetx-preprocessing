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
