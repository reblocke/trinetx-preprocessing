from __future__ import annotations

import pandas as pd
import pytest

from trinetx_preprocessing.validation import require_columns


def test_require_columns_raises_with_context() -> None:
    df = pd.DataFrame({"col_a": [1], "col_b": [2]})

    with pytest.raises(ValueError) as excinfo:
        require_columns(df, ["col_a", "col_c"], context="sample.csv")

    message = str(excinfo.value)
    assert "sample.csv" in message
    assert "col_c" in message
    assert "missing required columns" in message
