"""One-scan, patient-partitioned source cache for final analytic features."""

from __future__ import annotations

import json
import multiprocessing
import os
import resource
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from ..config import Config
from ..filesystem import remove_tree_strict, write_text_atomic
from ..process_locks import duplicate_lock_file_descriptors_for_spawn
from ..storage import (
    PartitionedParquetStore,
    find_work_tables,
    iter_work_tables,
    resolve_work_table,
)
from ..transform.diagnosis import DIAGNOSIS_CODE_GROUPS, DIAGNOSIS_COLUMNS
from ..transform.labs import LAB_COLUMNS
from ..transform.medications import MEDICATION_CODE_GROUPS, MEDICATION_COLUMNS
from ..transform.procedure import PROCEDURE_CODE_GROUPS, PROCEDURE_COLUMNS
from ..transform.vitals import VITAL_SIGN_RULES, VITALS_COLUMNS

LAB_SOURCE_NAME = "__normalized_labs__"
FINAL_FEATURE_INDEX_MAX_CHUNK_ROWS = 100_000
FINAL_FEATURE_BUFFER_ROWS_PER_BUCKET = 10_000
SOURCE_COLUMNS = [
    "source_name",
    "patient_id",
    "encounter_id",
    "code",
    "date",
    "numeric_value",
    "principal_diagnosis_indicator",
    "admitting_diagnosis",
    "reason_for_visit",
    "_source_row_order",
]


@dataclass(frozen=True)
class _SourceDefinition:
    domain: str
    name: str
    paths: tuple[Path, ...]
    columns: tuple[str, ...]
    date_column: str
    numeric_column: str | None = None


class _DomainPartitionReader:
    """Read-only access to one worker-built feature-domain partition set."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._paths = {
            int(item.stem.rsplit("-", 1)[1]): item
            for item in path.glob("bucket-*.parquet")
        }

    def read_frame(
        self,
        bucket: int,
        *,
        columns: Sequence[str] | None = None,
    ) -> pd.DataFrame | None:
        path = self._paths.get(bucket)
        if path is None:
            return None
        return pd.read_parquet(
            path,
            columns=list(columns) if columns is not None else None,
        )

    def populated_buckets(self) -> set[int]:
        return set(self._paths)

    def disk_size_bytes(self) -> int:
        return sum(path.stat().st_size for path in self._paths.values())


class FinalFeatureBucket:
    """Feature source rows for one patient hash partition."""

    def __init__(
        self,
        frame: pd.DataFrame | None = None,
        *,
        bucket: int | None = None,
        stores: dict[str, _DomainPartitionReader] | None = None,
        source_domains: dict[str, str] | None = None,
    ) -> None:
        self._bucket = bucket
        self._stores = stores or {}
        self._source_domains = source_domains or {}
        self._active_domain: str | None = None
        self._frame = pd.DataFrame(columns=SOURCE_COLUMNS)
        self._source_positions: dict[str, np.ndarray] = {}
        self._set_frame(frame)

    def _set_frame(self, frame: pd.DataFrame | None) -> None:
        if frame is None or frame.empty:
            self._frame = pd.DataFrame(columns=SOURCE_COLUMNS)
            self._source_positions = {}
            return
        self._frame = frame
        source_row_order = frame["_source_row_order"].to_numpy(copy=False)
        self._source_positions = {}
        for name, positions in frame.groupby("source_name", sort=False).indices.items():
            source_positions = np.asarray(positions, dtype=np.int64)
            stable_order = np.argsort(
                source_row_order[source_positions],
                kind="stable",
            )
            self._source_positions[str(name)] = source_positions[stable_order]

    def _activate_source_domain(self, source_name: str) -> None:
        domain = self._source_domains.get(source_name)
        if domain is None or domain == self._active_domain:
            return
        if self._bucket is None:
            return
        frame = self._stores[domain].read_frame(
            self._bucket,
            columns=SOURCE_COLUMNS,
        )
        self._set_frame(frame)
        self._active_domain = domain

    def frame(self, source_name: str, columns: Sequence[str]) -> pd.DataFrame:
        """Return one source in its historical logical column shape."""

        self._activate_source_domain(source_name)
        positions = self._source_positions.get(source_name)
        if positions is None:
            return pd.DataFrame(columns=columns)
        result: dict[str, pd.Series] = {}
        for column in columns:
            if column == "start_date":
                source_column = "date"
            elif column in {"value", "lab_result_num_val"}:
                source_column = "numeric_value"
            else:
                source_column = column
            result[column] = (
                self._frame[source_column].take(positions).reset_index(drop=True)
            )
        return pd.DataFrame(result, columns=columns)

    def has_source(self, source_name: str) -> bool:
        """Return whether this patient bucket contains the logical source."""

        self._activate_source_domain(source_name)
        return source_name in self._source_positions


class FinalFeatureSourceStore:
    """Build and expose all final-feature sources with one source scan."""

    def __init__(
        self,
        config: Config,
        *,
        chunksize: int | None,
        lock_file_descriptors: tuple[int, ...] = (),
    ) -> None:
        self.config = config
        self.lock_file_descriptors = lock_file_descriptors
        requested_chunksize = chunksize or FINAL_FEATURE_INDEX_MAX_CHUNK_ROWS
        self.chunksize = min(
            requested_chunksize,
            FINAL_FEATURE_INDEX_MAX_CHUNK_ROWS,
        )
        self._scratch_root: Path | None = None
        self._stores: dict[str, _DomainPartitionReader] = {}
        self._source_domains: dict[str, str] = {}
        self.rows_indexed = 0
        self.files_scanned = 0
        self.source_files_scanned: list[str] = []
        self.peak_worker_rss_mb = 0.0
        self.worker_metrics: dict[str, dict[str, object]] = {}

    def __enter__(self) -> "FinalFeatureSourceStore":
        self.config.work_dir.mkdir(parents=True, exist_ok=True)
        self._scratch_root = Path(
            tempfile.mkdtemp(
                prefix=".trinetx-final-feature-sources-",
                dir=self.config.work_dir,
            )
        )
        try:
            self._build()
        except BaseException:
            self._cleanup()
            raise
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._cleanup()

    def bucket(self, bucket: int) -> FinalFeatureBucket:
        """Load one source partition for reuse across all final outputs."""

        return FinalFeatureBucket(
            bucket=bucket,
            stores=self._stores,
            source_domains=self._source_domains,
        )

    def populated_buckets(self) -> set[int]:
        """Return populated partition numbers without retaining row frames."""

        populated: set[int] = set()
        for store in self._stores.values():
            populated.update(store.populated_buckets())
        return populated

    def disk_size_bytes(self) -> int:
        """Return the compressed source-index footprint."""

        return sum(store.disk_size_bytes() for store in self._stores.values())

    def _build(self) -> None:
        next_row_order = 0
        definitions_by_domain: dict[str, list[_SourceDefinition]] = {}
        for definition in _source_definitions(self.config):
            definitions_by_domain.setdefault(definition.domain, []).append(definition)

        for domain, definitions in definitions_by_domain.items():
            root = self._require_scratch_root()
            metadata_path = root / f"{domain}.json"
            process = multiprocessing.get_context("spawn").Process(
                target=_build_feature_domain_worker,
                args=(
                    self.config,
                    self.chunksize,
                    domain,
                    tuple(definitions),
                    next_row_order,
                    root,
                    metadata_path,
                    duplicate_lock_file_descriptors_for_spawn(
                        self.lock_file_descriptors
                    ),
                ),
                name=f"trinetx-final-feature-{domain}",
            )
            process.start()
            try:
                process.join()
            except BaseException:
                if process.is_alive():
                    process.terminate()
                process.join()
                raise
            if not metadata_path.exists():
                raise RuntimeError(
                    f"Final {domain} feature index worker exited "
                    f"with status {process.exitcode} without metadata."
                )
            metadata = json.loads(metadata_path.read_text())
            if process.exitcode != 0 or metadata.get("status") != "complete":
                message = metadata.get("error", "feature-domain worker failed")
                raise RuntimeError(f"Final {domain} feature index failed: {message}")
            rows_indexed = int(metadata["rows_indexed"])
            next_row_order += rows_indexed
            self.rows_indexed += rows_indexed
            self.files_scanned += int(metadata["files_scanned"])
            self.source_files_scanned.extend(metadata["source_files_scanned"])
            self.peak_worker_rss_mb = max(
                self.peak_worker_rss_mb,
                float(metadata["peak_rss_mb"]),
            )
            self.worker_metrics[domain] = {
                "rows_indexed": rows_indexed,
                "files_scanned": int(metadata["files_scanned"]),
                "peak_rss_mb": float(metadata["peak_rss_mb"]),
            }
            for source_name in metadata["source_names"]:
                self._source_domains[str(source_name)] = domain
            self._stores[domain] = _DomainPartitionReader(
                root / str(metadata["partition_path"])
            )

    def _require_scratch_root(self) -> Path:
        if self._scratch_root is None:
            raise RuntimeError("Final feature source store is not open.")
        return self._scratch_root

    def _cleanup(self) -> None:
        if self._scratch_root is None:
            return
        remove_tree_strict(
            self._scratch_root,
            context="Final feature source index scratch",
        )
        self._scratch_root = None


def _build_feature_domain_worker(
    config: Config,
    chunksize: int,
    domain: str,
    definitions: tuple[_SourceDefinition, ...],
    row_order_start: int,
    root: Path,
    metadata_path: Path,
    lock_file_descriptors: tuple[int, ...],
) -> None:
    """Build one domain in a fresh process so allocator state cannot accumulate."""

    try:
        _build_feature_domain_worker_body(
            config,
            chunksize,
            domain,
            definitions,
            row_order_start,
            root,
            metadata_path,
        )
    finally:
        for descriptor in reversed(lock_file_descriptors):
            os.close(descriptor)


def _build_feature_domain_worker_body(
    config: Config,
    chunksize: int,
    domain: str,
    definitions: tuple[_SourceDefinition, ...],
    row_order_start: int,
    root: Path,
    metadata_path: Path,
) -> None:
    store = PartitionedParquetStore(
        root,
        prefix=f".{domain}-",
        key_columns=["patient_id"],
        bucket_count=config.storage.analysis_bucket_count,
        row_group_size=config.storage.parquet_row_group_size,
        buffer_rows_per_bucket=FINAL_FEATURE_BUFFER_ROWS_PER_BUCKET,
        cleanup_context=f"Final {domain} feature index scratch",
    )
    store.__enter__()
    rows_indexed = 0
    files_scanned = 0
    source_files_scanned: list[str] = []
    source_names: set[str] = set()
    try:
        for definition in definitions:
            for path in definition.paths:
                files_scanned += 1
                source_files_scanned.append(path.name)
                for chunk in iter_work_tables(
                    [path],
                    chunksize=chunksize,
                    usecols=definition.columns,
                    dtype={
                        "patient_id": "string",
                        "encounter_id": "string",
                        "code": "string",
                    },
                ):
                    indexed = _to_index_frame(
                        chunk,
                        definition,
                        row_order_start=row_order_start + rows_indexed,
                    )
                    rows_indexed += len(indexed)
                    source_names.update(
                        str(value) for value in indexed["source_name"].dropna().unique()
                    )
                    store.add_frame(indexed)
        store.seal()
        payload = {
            "status": "complete",
            "rows_indexed": rows_indexed,
            "files_scanned": files_scanned,
            "source_files_scanned": source_files_scanned,
            "source_names": sorted(source_names),
            "partition_path": str(store.path.relative_to(root)),
            "peak_rss_mb": _peak_rss_mb(),
        }
    except BaseException as exc:
        payload = {
            "status": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "peak_rss_mb": _peak_rss_mb(),
        }
        write_text_atomic(metadata_path, json.dumps(payload, sort_keys=True))
        raise
    write_text_atomic(metadata_path, json.dumps(payload, sort_keys=True))


def _peak_rss_mb() -> float:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    return round(value / divisor, 3)


def _source_definitions(config: Config) -> Iterable[_SourceDefinition]:
    vital_analysis = resolve_work_table(config, "analysis_vital_features.csv")
    if vital_analysis.exists():
        yield _SourceDefinition(
            "vitals",
            "__indexed_vitals__",
            (vital_analysis,),
            ("source_name", *VITALS_COLUMNS),
            "date",
            "value",
        )
    else:
        for rule in VITAL_SIGN_RULES:
            yield from _logical_source(
                config,
                "vitals",
                f"{rule.name}.csv",
                VITALS_COLUMNS,
                "date",
                "value",
            )

    lab_analysis = resolve_work_table(config, "analysis_lab_features.csv")
    if lab_analysis.exists():
        yield _SourceDefinition(
            "labs",
            "__indexed_labs__",
            (lab_analysis,),
            ("source_name", *LAB_COLUMNS),
            "date",
            "lab_result_num_val",
        )
    else:
        lab_paths = tuple(find_work_tables(config, "lab_results_NEW_*.csv"))
        if not lab_paths:
            lab_paths = ()
    if not lab_analysis.exists() and lab_paths:
        yield _SourceDefinition(
            "labs",
            LAB_SOURCE_NAME,
            lab_paths,
            tuple(LAB_COLUMNS),
            "date",
            "lab_result_num_val",
        )

    diagnosis_analysis = resolve_work_table(config, "analysis_diagnosis_features.csv")
    if diagnosis_analysis.exists():
        yield _SourceDefinition(
            "diagnosis",
            "__indexed_diagnosis__",
            (diagnosis_analysis,),
            ("source_name", *DIAGNOSIS_COLUMNS),
            "date",
        )
    else:
        for group in DIAGNOSIS_CODE_GROUPS:
            yield from _logical_source(
                config,
                "diagnosis",
                f"{group.name}.csv",
                DIAGNOSIS_COLUMNS,
                "date",
            )

    procedure_analysis = resolve_work_table(config, "analysis_procedure_features.csv")
    if procedure_analysis.exists():
        yield _SourceDefinition(
            "procedure",
            "__indexed_procedure__",
            (procedure_analysis,),
            ("source_name", *PROCEDURE_COLUMNS),
            "date",
        )
    else:
        for group in PROCEDURE_CODE_GROUPS:
            yield from _logical_source(
                config,
                "procedure",
                f"{group.name}.csv",
                PROCEDURE_COLUMNS,
                "date",
            )

    medication_analysis = resolve_work_table(config, "analysis_medication_features.csv")
    if medication_analysis.exists():
        yield _SourceDefinition(
            "medications",
            "__indexed_medications__",
            (medication_analysis,),
            ("source_name", *MEDICATION_COLUMNS),
            "start_date",
        )
    else:
        for group in MEDICATION_CODE_GROUPS:
            yield from _logical_source(
                config,
                "medications",
                f"{group.name}.csv",
                MEDICATION_COLUMNS,
                "start_date",
            )


def _logical_source(
    config: Config,
    domain: str,
    logical_name: str,
    columns: Sequence[str],
    date_column: str,
    numeric_column: str | None = None,
) -> Iterable[_SourceDefinition]:
    path = resolve_work_table(config, logical_name)
    if path.exists():
        yield _SourceDefinition(
            domain,
            logical_name,
            (path,),
            tuple(columns),
            date_column,
            numeric_column,
        )


def _to_index_frame(
    frame: pd.DataFrame,
    definition: _SourceDefinition,
    *,
    row_order_start: int,
) -> pd.DataFrame:
    size = len(frame)
    indexed = pd.DataFrame(index=frame.index)
    if "source_name" in frame:
        indexed["source_name"] = frame["source_name"].astype("string")
    else:
        indexed["source_name"] = pd.Series(
            [definition.name] * size,
            index=frame.index,
            dtype="string",
        )
    for column in ("patient_id", "encounter_id", "code"):
        indexed[column] = frame[column].astype("string")
    indexed["date"] = pd.to_datetime(frame[definition.date_column], errors="coerce")
    if definition.numeric_column is None:
        indexed["numeric_value"] = np.nan
    else:
        indexed["numeric_value"] = pd.to_numeric(
            frame[definition.numeric_column], errors="coerce"
        ).astype("float64")
    for column in (
        "principal_diagnosis_indicator",
        "admitting_diagnosis",
        "reason_for_visit",
    ):
        if column in frame:
            indexed[column] = frame[column].astype("string")
        else:
            indexed[column] = pd.Series(pd.NA, index=frame.index, dtype="string")
    indexed["_source_row_order"] = np.arange(
        row_order_start,
        row_order_start + size,
        dtype=np.int64,
    )
    return indexed.loc[:, SOURCE_COLUMNS].reset_index(drop=True)
