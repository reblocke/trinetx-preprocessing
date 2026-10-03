"""Aggregate every retained return alternative through the trusted reader."""

from __future__ import annotations

import argparse
import csv
import json
import platform
import sys
import uuid
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc

from trinetx_preprocessing.combined_preprocessing.builder import (
    require_safe_output_location,
)
from trinetx_preprocessing.encounters.builder import VARIANTS, sha256
from trinetx_preprocessing.encounters.compatibility import no_symlinks
from trinetx_preprocessing.encounters.return_acceptance import (
    KEYS,
    frozen_summary_schema,
)
from trinetx_preprocessing.filesystem import fsync_directory_strict, write_text_atomic

from .return_reader import open_return_summary

CATEGORIES = frozenset(
    {
        "anchor_state",
        "index_end_precision",
        "inpatient_event_term",
        *(f"outcome_followup_observation_{d}d" for d in (30, 90, 365)),
    }
)
EXCLUDED = frozenset({*KEYS, "index_episode_id"})
STATE_DEFINITION = (
    "Positive and negative are the retained true and false flags. For null flags, "
    "not_applicable is a retained not_applicable anchor; unavailable is another "
    "non-available anchor or a positive retained phenotype_unavailable_count; "
    "unknown is every remaining null flag. These five counts partition the "
    "original-index denominator. Unknown is not negative. Count-field sums use "
    "only non-null retained values and report their denominator separately."
)


def _count(mask):
    return int(pc.sum(pc.cast(pc.fill_null(mask, False), pa.int64())).as_py() or 0)


def _accumulate(fields, batch):
    anchor = batch.column(batch.schema.get_field_index("anchor_state"))
    not_applicable = pc.equal(anchor, "not_applicable")
    unavailable_anchor = pc.invert(pc.fill_null(pc.equal(anchor, "available"), False))
    for name, col in zip(batch.schema.names, batch.columns, strict=True):
        if name in EXCLUDED:
            continue
        item = fields.setdefault(name, {"denominator": 0, "non_null": 0, "null": 0})
        item["denominator"] += len(col)
        item["null"] += col.null_count
        item["non_null"] += len(col) - col.null_count
        if name.endswith("_flag"):
            null = pc.is_null(col)
            unavailable = unavailable_anchor
            evidence_name = name[:-5] + "_phenotype_unavailable_count"
            if evidence_name in batch.schema.names:
                unavailable = pc.or_kleene(
                    unavailable, pc.greater(batch.column(evidence_name), 0)
                )
            na_count = _count(pc.and_kleene(null, not_applicable))
            unavailable_count = _count(
                pc.and_kleene(
                    null,
                    pc.and_kleene(
                        pc.invert(pc.fill_null(not_applicable, False)), unavailable
                    ),
                )
            )
            values = {
                "positive": _count(col),
                "negative": _count(pc.invert(col)),
                "not_applicable": na_count,
                "unavailable": unavailable_count,
                "unknown": col.null_count - na_count - unavailable_count,
            }
            for state, n in values.items():
                item[state] = item.get(state, 0) + n
        elif name.endswith("_count"):
            item["sum"] = item.get("sum", 0) + int(pc.sum(col).as_py() or 0)
        if name in CATEGORIES:
            counts = item.setdefault("categories", {})
            for value in pc.value_counts(col).to_pylist():
                label = "<null>" if value["values"] is None else value["values"]
                counts[label] = counts.get(label, 0) + value["counts"]
        if name.endswith("_first_timestamp") and len(col) != col.null_count:
            raise ValueError(
                "Unexpected intraday first-return timestamp under contract 2.0"
            )


def build_quality_report(
    bundle: Path,
    *,
    receipt_path: Path,
    expected_receipt_sha256: str,
    validation_report_path: Path,
    output_dir: Path,
) -> dict:
    """Write external aggregate-only JSON, CSV, Markdown and hashed evidence.

    No patient identifiers, row-level values or exact date distributions are
    emitted. Both original variants and every retained alternative are included.
    """
    bundle, output_dir = no_symlinks(bundle), no_symlinks(output_dir)
    require_safe_output_location(output_dir, artifact_label="return quality report")
    if output_dir.exists():
        raise FileExistsError("Quality report destination already exists")
    for path in (bundle, Path(receipt_path), Path(validation_report_path)):
        if output_dir.is_relative_to(path) or path.is_relative_to(output_dir):
            raise ValueError("Quality report destination overlaps an input")
    output_dir.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    staging = output_dir.with_name(f".{output_dir.name}.staging-{uuid.uuid4().hex}")
    staging.mkdir(mode=0o700)
    expected_receipt = expected_receipt_sha256
    result = {
        "report_contract_version": "1.0",
        "return_contract_version": "2.0",
        "state_definitions": STATE_DEFINITION,
        "variants": {},
        "limitations": [
            "All alternatives retained; no primary endpoint selected.",
            "Observed follow-up does not establish continuous or complete capture.",
            "No population restriction or new censoring rule.",
            "Contract 2.0 intentionally has no intraday first-return timestamps.",
            "Coarse death information availability is not an exact death date.",
        ],
    }
    names = [f.name for f in frozen_summary_schema() if f.name not in EXCLUDED]
    for variant in VARIANTS:
        with open_return_summary(
            bundle,
            variant=variant,
            receipt_path=receipt_path,
            expected_receipt_sha256=expected_receipt,
            validation_report_path=validation_report_path,
        ) as summary:
            fields = {}
            schema = frozen_summary_schema()
            selected = [*KEYS, *names]
            empty = pa.RecordBatch.from_arrays(
                [pa.array([], type=schema.field(name).type) for name in selected],
                names=selected,
            )
            _accumulate(fields, empty)
            total = 0
            for batch in summary.iter_batches(columns=[*KEYS, *names]):
                total += batch.num_rows
                _accumulate(fields, batch)
            result["variants"][variant] = {
                "original_index_count": total,
                "original_key_reconciliation": (
                    "exact trusted parent-key proof verified"
                ),
                "join_cardinality": "one return row per original composite parent key",
                "parent_manifest_sha256": summary.parent_manifest_sha256,
                "fields": fields,
            }
    # Recheck the externally supplied trust after both complete reads.
    if sha256(Path(receipt_path)) != expected_receipt:
        raise ValueError("Return receipt changed during aggregate reporting")
    write_text_atomic(
        staging / "quality.json", json.dumps(result, sort_keys=True, indent=2) + "\n"
    )
    columns = [
        "variant",
        "field",
        "denominator",
        "non_null",
        "null",
        "positive",
        "negative",
        "unknown",
        "unavailable",
        "not_applicable",
        "sum",
        "categories",
    ]
    with (staging / "quality.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for variant, values in result["variants"].items():
            for name, counts in values["fields"].items():
                row = {"variant": variant, "field": name, **counts}
                if "categories" in row:
                    row["categories"] = json.dumps(row["categories"], sort_keys=True)
                writer.writerow(row)
        handle.flush()
        import os

        os.fsync(handle.fileno())
    lines = [
        "# Return outcome quality",
        "",
        STATE_DEFINITION,
        "",
        *["- " + x for x in result["limitations"]],
        "",
        "The CSV and JSON contain every retained field, "
        "including event counts, testing",
        "availability, uncertainty dispositions, first-date availability, "
        "observed follow-up",
        "categories and coarse death-information availability. Exact original keys and",
        "one-to-one correspondence are verified through the trusted parent-key proof.",
        "",
    ]
    for variant, values in result["variants"].items():
        lines += [
            f"## {variant}",
            "",
            f"Original index denominator: {values['original_index_count']}",
            "",
            "| Retained flag | Denominator | Positive | Negative | Unknown | "
            "Unavailable | Not applicable |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for name, counts in values["fields"].items():
            if name.endswith("_flag"):
                lines.append(
                    "| "
                    + name
                    + " | "
                    + " | ".join(
                        str(counts[k])
                        for k in (
                            "denominator",
                            "positive",
                            "negative",
                            "unknown",
                            "unavailable",
                            "not_applicable",
                        )
                    )
                    + " |"
                )
        lines.append("")
    write_text_atomic(staging / "quality.md", "\n".join(lines) + "\n")
    evidence = {
        "status": "complete",
        "evidence_contract_version": "1.0",
        "acceptance_sha256": expected_receipt,
        "validation_report_sha256": sha256(Path(validation_report_path)),
        "bundle_manifest_sha256": sha256(bundle / "manifest.json"),
        "command": sys.argv,
        "python": sys.version,
        "platform": platform.platform(),
        "artifacts": {
            p.name: {"bytes": p.stat().st_size, "sha256": sha256(p)}
            for p in staging.iterdir()
        },
    }
    write_text_atomic(
        staging / "evidence.json", json.dumps(evidence, sort_keys=True, indent=2) + "\n"
    )
    fsync_directory_strict(staging)
    staging.replace(output_dir)
    fsync_directory_strict(output_dir.parent)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--trusted-acceptance-sha256", required=True)
    parser.add_argument("--validation-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build_quality_report(
        args.bundle,
        receipt_path=args.receipt,
        expected_receipt_sha256=args.trusted_acceptance_sha256,
        validation_report_path=args.validation_report,
        output_dir=args.output,
    )
    print("Return quality report and evidence written successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
