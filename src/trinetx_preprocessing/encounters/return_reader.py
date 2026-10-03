"""Bounded read-only access to explicitly trusted return summaries."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from trinetx_preprocessing.encounters.builder import sha256
from trinetx_preprocessing.encounters.compatibility import no_symlinks
from trinetx_preprocessing.encounters.return_acceptance import (
    KEYS,
    frozen_summary_schema,
    summary_names,
    verify_accepted_return_bundle,
    verify_return_output,
)


def _identity(path: Path) -> tuple:
    stat = no_symlinks(path).stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


class ReturnSummary:
    """Verified summary context. Construct through open_return_summary only."""

    def __init__(self, bundle, manifest, variant, evidence):
        self._bundle = bundle
        self._manifest = manifest
        self._variant = variant
        self._evidence = evidence
        self._closed = False

    @property
    def variant(self):
        return self._variant

    @property
    def parent_manifest_sha256(self):
        return self._manifest["parent_manifest_sha256"]

    def __enter__(self):
        self._check_evidence()
        return self

    def __exit__(self, *exc):
        self._closed = True

    def _check_evidence(self):
        if self._closed:
            raise ValueError("Return summary context is closed")
        for path, expected in self._evidence.items():
            no_symlinks(path)
            if sha256(path) != expected:
                raise ValueError("Return acceptance evidence changed during reading")

    def _columns(self, columns):
        names = frozen_summary_schema().names
        if columns is None:
            return names
        if (
            not isinstance(columns, list)
            or any(not isinstance(c, str) for c in columns)
            or len(columns) != len(set(columns))
        ):
            raise ValueError("Columns must be a list of distinct field names")
        if not set(KEYS) <= set(columns):
            raise ValueError(
                "Projected reads must include all three original linkage fields"
            )
        if set(columns) - set(names):
            raise ValueError("Requested return column is not in the frozen schema")
        return columns

    def iter_batches(self, columns=None, batch_size=8192):
        """Yield bounded Arrow batches, preserving original keys and nullable fields.

        File hashes are checked before and after each complete file. Open file and
        path identities are checked around each batch; evidence is rechecked at
        each file boundary. Callers must consume successfully before publishing a
        derived result. A failed or interrupted iteration is not a completed read.
        """
        if type(batch_size) is not int or batch_size < 1:
            raise ValueError("batch_size must be a positive integer")
        columns = self._columns(columns)
        for name in summary_names(self._manifest, self._variant):
            self._check_evidence()
            path = verify_return_output(self._bundle, self._manifest, name)
            identity = _identity(path)
            with path.open("rb") as stream:
                import os

                stat = os.fstat(stream.fileno())
                opened = (
                    stat.st_dev,
                    stat.st_ino,
                    stat.st_size,
                    stat.st_mtime_ns,
                    stat.st_ctime_ns,
                )
                if opened != identity:
                    raise ValueError("Return artifact changed while opening")
                parquet = pq.ParquetFile(stream)
                if not parquet.schema_arrow.equals(
                    frozen_summary_schema(), check_metadata=False
                ):
                    raise ValueError("Return schema changed while reading")
                for batch in parquet.iter_batches(
                    batch_size=batch_size, columns=columns
                ):
                    if _identity(path) != identity:
                        raise ValueError("Return artifact changed during reading")
                    self._check_open()
                    yield batch
                verify_return_output(self._bundle, self._manifest, name)
            self._check_evidence()

    def _check_open(self):
        if self._closed:
            raise ValueError("Return summary context is closed")

    def read_dataframe(self, *, columns):
        """Load an explicit projection, retaining Arrow nullable dtypes."""
        if columns is None:
            raise ValueError("DataFrame reads require explicit columns")
        columns = self._columns(columns)
        batches = list(self.iter_batches(columns=columns))
        schema = frozen_summary_schema()
        selected = pa.schema([schema.field(c) for c in columns])
        return pa.Table.from_batches(batches, schema=selected).to_pandas(
            types_mapper=pd.ArrowDtype
        )


def open_return_summary(
    bundle: Path,
    *,
    variant: str,
    receipt_path: Path,
    expected_receipt_sha256: str,
    validation_report_path: Path,
) -> ReturnSummary:
    """Verify caller-trusted evidence and all artifacts before exposing any rows.

    No latest-product discovery, legacy route, raw-source route or development
    fallback is available. This exposes encounter outcomes without study selection.
    """
    bundle, receipt_path = Path(bundle), Path(receipt_path)
    validation_report_path = Path(validation_report_path)
    manifest = verify_accepted_return_bundle(
        bundle,
        variant=variant,
        receipt_path=receipt_path,
        expected_receipt_sha256=expected_receipt_sha256,
        validation_report_path=validation_report_path,
    )
    receipt = json.loads(receipt_path.read_text())
    evidence = {
        receipt_path: expected_receipt_sha256,
        validation_report_path: receipt["validation_report_sha256"],
        bundle / "manifest.json": receipt["bundle_manifest_sha256"],
    }
    context = ReturnSummary(bundle, manifest, variant, evidence)
    context._check_evidence()
    return context


def join_return_summary(
    parent: pd.DataFrame,
    summary: ReturnSummary,
    *,
    parent_manifest_sha256: str,
    columns: list[str],
) -> pd.DataFrame:
    """Join an explicitly accepted, complete parent variant without row selection.

    Obtain parent and its manifest identity through the existing trusted encounter
    reader. This helper proves exact key coverage and one-to-one cardinality; it
    refuses subsets, alternate populations and outcome/parent column collisions.
    """
    if parent_manifest_sha256 != summary.parent_manifest_sha256:
        raise ValueError("Return bundle names a different parent manifest")
    parent_keys = ["patient_id", "encounter_id", "pat_enc_hash"]
    if not set(parent_keys) <= set(parent.columns):
        raise ValueError("Parent lacks original composite linkage fields")
    if parent[parent_keys].isna().any().any() or parent.duplicated(parent_keys).any():
        raise ValueError("Parent original composite keys are null or duplicated")
    outcomes = summary.read_dataframe(columns=columns)
    outcome_fields = set(columns) - set(KEYS)
    if outcome_fields & set(parent.columns) or "index_event_id" in parent.columns:
        raise ValueError("Parent and return columns overlap")
    coverage = parent[parent_keys].merge(
        outcomes[list(KEYS)],
        how="outer",
        left_on=parent_keys,
        right_on=list(KEYS),
        validate="one_to_one",
        indicator=True,
    )
    if len(coverage) != len(parent) or not coverage["_merge"].eq("both").all():
        raise ValueError("Parent and return original key coverage differs")
    result = parent.merge(
        outcomes,
        how="left",
        left_on=parent_keys,
        right_on=list(KEYS),
        validate="one_to_one",
        sort=False,
    )
    if len(result) != len(parent):
        raise ValueError("Return join changed parent row count")
    return result
