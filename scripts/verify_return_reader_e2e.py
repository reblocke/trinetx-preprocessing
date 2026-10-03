#!/usr/bin/env python3
"""Retained installed-package return reader boundary E2E (synthetic evidence).

Independent expectations precede implementation. This small boundary fixture is
not the source-to-parent-to-return workflow and cannot certify private acceptance.
Run outside either checkout, with the noneditable upstream wheel installed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def run(root):
    from trinetx_preprocessing.encounters.return_acceptance import (
        KEYS,
        PRODUCTION_IDENTITIES,
        REQUIRED_GATES,
        artifact_inventory_digest,
        frozen_summary_schema,
        key_proof,
    )
    from trinetx_preprocessing.encounters.return_reader import open_return_summary

    root.mkdir(parents=True, exist_ok=False)
    bundle = root / "bundle"
    bundle.mkdir()
    schema = frozen_summary_schema()
    # Same patient, two distinct encounters, one independently excluded encounter.
    # Nullable outcome is retained as unknown, never converted to false.
    rows = [
        dict(zip(KEYS, key, strict=True))
        for key in (
            ("p", "e1", "p_e1"),
            ("p", "e2", "p_e2"),
            ("q", "e3", "q_e3"),
            ("r", "e4", "r_e4"),
            ("p", "e5", "p_e5"),
        )
    ]
    for row, flag, anchor in zip(
        rows,
        (True, None, None, None, False),
        (
            "available",
            "available",
            "missing_episode_end",
            "not_applicable",
            "available",
        ),
        strict=True,
    ):
        row["outcome_inpatient_all_cause_30d_flag"] = flag
        row["anchor_state"] = anchor
    variants = ("FULL_DATA", "AFTER_EXCLUSION")
    summaries = {}
    for variant in variants:
        path = bundle / f"{variant.lower()}_0000_summary.parquet"
        pq.write_table(
            pa.Table.from_pylist(
                rows if variant == variants[0] else rows[:1], schema=schema
            ),
            path,
        )
        summaries[variant] = [path]
    # The complete six-table inventory is populated with typed empty evidence.
    from trinetx_preprocessing.encounters.return_acceptance import (
        TABLES,
        frozen_table_schema,
    )

    for variant in variants:
        for table in TABLES:
            if table != "summary":
                pq.write_table(
                    pa.Table.from_batches([], schema=frozen_table_schema(table)),
                    bundle / f"{variant.lower()}_0000_{table}.parquet",
                )
    write(bundle / "data_dictionary.json", {"fixture": "reader boundary only"})
    write(bundle / "progress.json", {"fixture": "reader boundary only"})
    inventory = {
        p.name: {"bytes": p.stat().st_size, "sha256": sha(p)} for p in bundle.iterdir()
    }
    identities = {
        name: hashlib.sha256(name.encode()).hexdigest()
        for name in (
            "producer",
            "parent_validator",
            "outcome_validator",
            "source_stage",
            "contract",
            "configuration",
            "catalog",
            "environment",
            "validator_environment",
        )
    }
    proofs = {v: key_proof(paths) for v, paths in summaries.items()}
    manifest = dict(
        kind="return_outcomes",
        status="complete",
        schema_version="2.0",
        return_contract_version="2.0",
        variants=list(variants),
        partitions=1,
        horizons_days=[30, 90, 365],
        outputs=inventory,
        identities={k: v for k, v in identities.items() if k in PRODUCTION_IDENTITIES},
        parent_manifest_sha256="a" * 64,
        source_manifest_sha256="b" * 64,
        source_database_sha256="d" * 64,
    )
    manifest_path = bundle / "manifest.json"
    write(manifest_path, manifest)
    common = dict(
        bundle_manifest_sha256=sha(manifest_path),
        identities=identities,
        parent_manifest_sha256="a" * 64,
        source_manifest_sha256="b" * 64,
        source_database_sha256="d" * 64,
        original_keys=proofs,
        artifact_inventory_sha256=artifact_inventory_digest(inventory),
        schema_version="2.0",
        return_contract_version="2.0",
    )
    report = dict(common, validation_report_version="1.0", **{"pass": True})
    report_path = root / "validation.json"
    write(report_path, report)
    receipt = dict(
        common,
        kind="return_outcomes_acceptance",
        status="accepted",
        acceptance_contract_version="1.0",
        validation_report_sha256=sha(report_path),
        gates={
            gate: {"status": "pass", "evidence_sha256": "c" * 64}
            for gate in REQUIRED_GATES
        },
        evidence_scope="synthetic reader boundary fixture",
    )
    receipt_path = root / "acceptance.json"
    write(receipt_path, receipt)

    def opened(variant="FULL_DATA", digest=None):
        return open_return_summary(
            bundle,
            variant=variant,
            receipt_path=receipt_path,
            expected_receipt_sha256=digest or sha(receipt_path),
            validation_report_path=report_path,
        )

    with opened() as summary:
        batches = list(summary.iter_batches(columns=list(KEYS), batch_size=1))
        assert [b.num_rows for b in batches] == [1] * 5
        assert pa.Table.from_batches(batches).to_pylist() == [
            {k: r[k] for k in KEYS} for r in rows
        ]
        frame = summary.read_dataframe(columns=list(KEYS))
        assert frame.shape == (5, 3)
        flags = summary.read_dataframe(
            columns=[*KEYS, "outcome_inpatient_all_cause_30d_flag"]
        )
        assert bool(flags.iloc[0, 3]) is True
        assert flags.iloc[:, 3].isna().tolist() == [False, True, True, True, False]
        try:
            summary.read_dataframe()
        except TypeError:
            pass
        else:
            raise AssertionError("Unrestricted dataframe was allowed")
    with opened("AFTER_EXCLUSION") as summary:
        assert sum(b.num_rows for b in summary.iter_batches(columns=list(KEYS))) == 1

    rejected = []

    def rejection(label, action):
        try:
            action()
        except (ValueError, FileNotFoundError):
            rejected.append(label)
        else:
            raise AssertionError(f"Did not reject {label}")

    import pandas as pd

    from trinetx_preprocessing.encounters.return_quality import build_quality_report
    from trinetx_preprocessing.encounters.return_reader import join_return_summary

    parent = pd.DataFrame(
        [{**{k: r[k] for k in KEYS}, "original_order": i} for i, r in enumerate(rows)]
    )
    parent = parent.rename(columns={"index_event_id": "pat_enc_hash"})
    with opened() as summary:
        joined = join_return_summary(
            parent,
            summary,
            parent_manifest_sha256="a" * 64,
            columns=[*KEYS, "outcome_inpatient_all_cause_30d_flag"],
        )
        assert joined["original_order"].tolist() == list(range(5))
        assert joined["outcome_inpatient_all_cause_30d_flag"].isna().tolist() == [
            False,
            True,
            True,
            True,
            False,
        ]
        rejection(
            "wrong parent manifest",
            lambda: join_return_summary(
                parent, summary, parent_manifest_sha256="f" * 64, columns=list(KEYS)
            ),
        )
        rejection(
            "missing parent row",
            lambda: join_return_summary(
                parent.iloc[:1],
                summary,
                parent_manifest_sha256="a" * 64,
                columns=list(KEYS),
            ),
        )
        rejection(
            "duplicate parent row",
            lambda: join_return_summary(
                pd.concat([parent, parent.iloc[:1]]),
                summary,
                parent_manifest_sha256="a" * 64,
                columns=list(KEYS),
            ),
        )
    quality = build_quality_report(
        bundle,
        receipt_path=receipt_path,
        expected_receipt_sha256=sha(receipt_path),
        validation_report_path=report_path,
        output_dir=root / "quality",
    )
    metric = quality["variants"]["FULL_DATA"]["fields"][
        "outcome_inpatient_all_cause_30d_flag"
    ]
    assert {
        k: metric[k]
        for k in ("positive", "negative", "unknown", "unavailable", "not_applicable")
    } == dict(positive=1, negative=1, unknown=1, unavailable=1, not_applicable=1)
    assert metric["denominator"] == 5
    assert quality["variants"]["AFTER_EXCLUSION"]["original_index_count"] == 1
    assert (
        len(
            [
                k
                for k in quality["variants"]["FULL_DATA"]["fields"]
                if k.endswith("_flag")
            ]
        )
        == 3 * 4 * 19
    )
    assert all(
        (root / "quality" / name).is_file()
        for name in ("quality.json", "quality.csv", "quality.md", "evidence.json")
    )

    rejection("wrong trusted digest", lambda: opened(digest="0" * 64))
    original_report = report_path.read_bytes()
    write(report_path, dict(report, parent_manifest_sha256="d" * 64))
    rejection("changed validation report", opened)
    report_path.write_bytes(original_report)
    original_receipt = receipt_path.read_bytes()
    for field in (
        "schema_version",
        "return_contract_version",
        "acceptance_contract_version",
    ):
        write(receipt_path, dict(receipt, **{field: "unsupported"}))
        rejection(f"unsupported {field}", opened)
    receipt_path.write_bytes(original_receipt)
    p = summaries["FULL_DATA"][0]
    original = p.read_bytes()
    context = opened()
    p.write_bytes(original + b"altered")
    rejection("changed artifact before open", opened)
    rejection(
        "changed artifact during read",
        lambda: list(context.iter_batches(columns=list(KEYS))),
    )
    p.write_bytes(original)
    for label, bad_rows in (
        ("missing key", rows[:1]),
        (
            "extra key",
            rows + [dict(zip(KEYS, ("extra", "e9", "extra_e9"), strict=True))],
        ),
        ("duplicate key", rows + [rows[0]]),
        ("null key", [dict(rows[0], patient_id=None), rows[1]]),
        (
            "incorrect original key mapping",
            [dict(rows[0], index_event_id="wrong"), rows[1]],
        ),
    ):
        pq.write_table(pa.Table.from_pylist(bad_rows, schema=schema), p)
        # Rebind byte evidence to reach the semantic key proof, retaining the
        # independently expected original key set in both trusted documents.
        inventory[p.name] = {"bytes": p.stat().st_size, "sha256": sha(p)}
        write(manifest_path, manifest)
        changed = dict(
            common,
            bundle_manifest_sha256=sha(manifest_path),
            artifact_inventory_sha256=artifact_inventory_digest(inventory),
        )
        write(report_path, dict(report, **changed))
        write(
            receipt_path,
            dict(receipt, **changed, validation_report_sha256=sha(report_path)),
        )
        rejection(label, opened)
    p.write_bytes(original)
    inventory[p.name] = {"bytes": p.stat().st_size, "sha256": sha(p)}
    write(manifest_path, manifest)
    report_path.write_bytes(original_report)
    receipt_path.write_bytes(original_receipt)
    return {
        "status": "passed",
        "rejections": rejected,
        "expected_variant_rows": {"FULL_DATA": 5, "AFTER_EXCLUSION": 1},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_dir", type=Path)
    parser.add_argument("--require-installed", action="store_true")
    args = parser.parse_args()
    if args.artifact_dir.exists():
        parser.error("Artifact directory exists; choose a new destination")
    import importlib.metadata
    import os

    import trinetx_preprocessing

    installed = all(
        Path(m.__file__).is_relative_to(Path(sys.prefix))
        for m in (trinetx_preprocessing,)
    )
    if args.require_installed and (not installed or "PYTHONPATH" in os.environ):
        parser.error("Require noneditable upstream package and removed PYTHONPATH")
    result = {
        "command": sys.argv,
        "python": sys.version,
        "platform": platform.platform(),
        "script_sha256": sha(Path(__file__)),
    }
    try:
        result.update(run(args.artifact_dir))
        result["exit_status"] = 0
    except Exception as exc:
        result.update(
            status="failed", error=f"{type(exc).__name__}: {exc}", exit_status=1
        )
    args.artifact_dir.mkdir(parents=True, exist_ok=True)
    (args.artifact_dir / "runner.py").write_bytes(Path(__file__).read_bytes())
    result["schema"] = "trinetx-return-e2e-v1"
    result["installed_noneditable"] = installed
    result["packages"] = {
        n: importlib.metadata.version(n)
        for n in (
            "duckdb",
            "pyarrow",
            "pandas",
            "numpy",
            "trinetx-preprocessing",
        )
    }
    result["inventory"] = {
        str(p.relative_to(args.artifact_dir)): {
            "bytes": p.stat().st_size,
            "sha256": sha(p),
        }
        for p in sorted(args.artifact_dir.rglob("*"))
        if p.is_file()
    }
    write(args.artifact_dir / "e2e.json", result)
    print(json.dumps(result, indent=2))
    return result["exit_status"]


if __name__ == "__main__":
    raise SystemExit(main())
