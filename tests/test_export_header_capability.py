"""Proposed-source header triage stays bounded and path-free."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trinetx_preprocessing import cli


def _file(path: Path, header: str) -> Path:
    path.write_text(header + "\nrestricted-row-must-not-be-read\n")
    return path


def test_header_screen_reports_fixed_aggregate_fields_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    encounter = _file(
        tmp_path / "private_encounter.csv", "patient_id,start_date,start_datetime"
    )
    lab = _file(tmp_path / "private_lab.csv", "patient_id,date,event_timestamp")
    medication = _file(
        tmp_path / "private_medication.csv",
        "patient_id,start_date,end_date,order_status,status",
    )
    assert (
        cli.main(
            [
                "screen-glp1-export-headers",
                "--encounter-file",
                str(encounter),
                "--lab-file",
                str(lab),
                "--medication-file",
                str(medication),
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["header_only"] is True
    assert payload["source_accepted"] is False
    assert payload["abstract_report_ready"] is False
    capture = {item["domain"]: item for item in payload["domains"]}
    assert capture["encounter"]["files_with_datetime_named_field"] == 1
    assert capture["labs"]["files_with_datetime_named_field"] == 1
    assert capture["medication"]["files_with_end_date"] == 1
    assert capture["medication"]["files_with_order_status"] == 1
    assert tmp_path.as_posix() not in output
    assert "patient_id" not in output
    assert "restricted-row" not in output


def test_header_screen_rejects_unreadable_and_duplicate_headers_without_paths(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    lab = _file(tmp_path / "lab.csv", "date")
    medication = _file(tmp_path / "med.csv", "start_date")
    encounter = _file(tmp_path / "enc.csv", "start_date,start_date")
    args = [
        "screen-glp1-export-headers",
        "--encounter-file",
        str(encounter),
        "--lab-file",
        str(lab),
        "--medication-file",
        str(medication),
    ]
    assert cli.main(args) == 2
    assert "duplicate header" in caplog.text
    assert tmp_path.as_posix() not in caplog.text
    encounter.unlink()
    caplog.clear()
    assert cli.main(args) == 2
    assert "Cannot read encounter CSV header" in caplog.text
    assert tmp_path.as_posix() not in caplog.text
