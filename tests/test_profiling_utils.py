from __future__ import annotations

import pytest

from trinetx_preprocessing.profiling import StageTimer


def test_stage_timer_records_elapsed() -> None:
    times = iter([1.0, 2.25])

    def time_fn() -> float:
        return next(times)

    timings: dict[str, float] = {}
    with StageTimer("demo", timings=timings, time_fn=time_fn):
        pass

    assert timings["demo"] == pytest.approx(1.25)
