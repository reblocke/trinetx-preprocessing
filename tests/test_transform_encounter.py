from __future__ import annotations

import pandas as pd
import pytest

from trinetx_preprocessing.transform.datetimes import (
    coerce_trinetx_datetime,
    parse_trinetx_datetime,
)


def test_trinetx_datetime_coercion_is_opt_in() -> None:
    values = pd.Series(["20220101", "not-a-date", pd.NA], dtype="string")

    with pytest.raises(ValueError, match="Could not parse 1"):
        parse_trinetx_datetime(values)

    coerced = coerce_trinetx_datetime(values)
    assert coerced.iloc[0] == pd.Timestamp("2022-01-01")
    assert pd.isna(coerced.iloc[1])
    assert pd.isna(coerced.iloc[2])
