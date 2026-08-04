"""Configuration loading and validation for the preprocessing pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

import yaml

DEFAULT_COMBINED_DUCKDB_MEMORY_LIMIT_MIB = 3072
DEFAULT_COMBINED_DUCKDB_CORE_MEMORY_LIMIT_MIB = 2816


class ConfigError(ValueError):
    """Raised when configuration values are invalid."""


@dataclass(frozen=True)
class DomainConfig:
    """Domain-specific configuration."""

    pattern: str
    patterns: tuple[str, ...] = ()

    @property
    def pattern_list(self) -> tuple[str, ...]:
        """Return all configured glob patterns for the domain."""

        return self.patterns or (self.pattern,)


@dataclass(frozen=True)
class DomainInspection:
    """Observed files for a configured domain pattern."""

    name: str
    pattern: str
    paths: tuple[Path, ...]
    truncated: bool = False
    matched_count_override: int | None = None
    search_dir: Path | None = None
    search_dir_exists: bool | None = None

    @property
    def matched_count(self) -> int:
        """Return the number of matched files."""

        if self.matched_count_override is not None:
            return self.matched_count_override
        return len(self.paths)

    @property
    def first_path(self) -> Path | None:
        """Return the first matched path, if any."""

        if not self.paths:
            return None
        return self.paths[0]


@dataclass(frozen=True)
class ChunkingConfig:
    """Chunking configuration."""

    enabled: bool = False
    lines_per_chunk: int = 10_000_000


@dataclass(frozen=True)
class RfsConfig:
    """RFS configuration."""

    enabled: bool = False
    ruleset: str = "corrected_v1"
    abg_min_pco2_mmhg: float = 45.0
    vbg_min_pco2_mmhg: float = 45.0


@dataclass(frozen=True)
class CohortConfig:
    """Final cohort-selection configuration."""

    event_selection: str = "earliest_per_setting"


@dataclass(frozen=True)
class DataScreenConfig:
    """Final AFTER-screen configuration."""

    mode: str = "diagnosis_or_lab"
    source: str = "derived"


@dataclass(frozen=True)
class GuardrailConfig:
    """Performance guardrail configuration."""

    max_join_multiplier: float = 1.0


@dataclass(frozen=True)
class StorageConfig:
    """Intermediate storage configuration."""

    intermediate_format: str = "csv"
    emit_legacy_csv_intermediates: bool = True
    emit_normalized_domain_tables: bool = False
    parquet_row_group_size: int = 250_000
    analysis_bucket_count: int = 256
    emit_legacy_group_tables: bool = False


@dataclass(frozen=True)
class CombinedPreprocessingConfig:
    """Configuration for the canonical combined preprocessing product."""

    enabled: bool = False
    database_name: str = "trinetx_preprocessed.duckdb"
    schema_version: str = "1.0"
    concept_sets_dir: Path | None = None
    duckdb_memory_limit_mib: int = DEFAULT_COMBINED_DUCKDB_MEMORY_LIMIT_MIB
    duckdb_core_memory_limit_mib: int = DEFAULT_COMBINED_DUCKDB_CORE_MEMORY_LIMIT_MIB


@dataclass(frozen=True)
class Config:
    """Top-level configuration container."""

    data_dir: Path
    work_dir: Path
    output_dir: Path
    domains: dict[str, DomainConfig]
    chunking: ChunkingConfig
    rfs: RfsConfig
    guardrails: GuardrailConfig
    storage: StorageConfig
    cohort: CohortConfig = CohortConfig()
    data_screen: DataScreenConfig = DataScreenConfig()
    combined: CombinedPreprocessingConfig = CombinedPreprocessingConfig()


def load_config(path: Path) -> Config:
    """Load configuration from a YAML file.

    Args:
        path: Path to the YAML configuration file.

    Returns:
        Parsed ``Config`` instance.
    """

    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    raw = yaml.safe_load(config_path.read_text())
    if not isinstance(raw, dict):
        raise ConfigError("Config file must contain a YAML mapping at top level.")

    base_dir = config_path.parent
    data_dir = _load_path(raw, "data_dir", base_dir)
    work_dir = _load_path(raw, "work_dir", base_dir)
    output_dir = _load_path(raw, "output_dir", base_dir)
    domains = _load_domains(raw.get("domains"))
    chunking = _load_chunking(raw.get("chunking"))
    rfs = _load_rfs(raw.get("rfs"))
    cohort = _load_cohort(raw.get("cohort"))
    data_screen = _load_data_screen(raw.get("data_screen"))
    guardrails = _load_guardrails(raw.get("guardrails"))
    storage = _load_storage(raw.get("storage"))
    combined = _load_combined(raw.get("combined"), base_dir)

    return Config(
        data_dir=data_dir,
        work_dir=work_dir,
        output_dir=output_dir,
        domains=domains,
        chunking=chunking,
        rfs=rfs,
        guardrails=guardrails,
        storage=storage,
        cohort=cohort,
        data_screen=data_screen,
        combined=combined,
    )


def validate_config(config: Config) -> None:
    """Validate required paths and glob patterns.

    Args:
        config: ``Config`` instance to validate.

    Raises:
        ConfigError: If any required paths or patterns are invalid.
    """

    _require_dir(config.data_dir, "data_dir")
    _require_dir(config.work_dir, "work_dir")
    _require_dir(config.output_dir, "output_dir")
    validate_combined_path_separation(config)
    collect_domain_paths(config)


def validate_combined_path_separation(config: Config) -> None:
    """Require separate work and output trees for combined preprocessing.

    Args:
        config: ``Config`` instance to validate.

    Raises:
        ConfigError: If the resolved work and output paths overlap.
    """

    if not config.combined.enabled:
        return

    work_dir = config.work_dir.resolve(strict=False)
    output_dir = config.output_dir.resolve(strict=False)
    if paths_overlap(work_dir, output_dir):
        raise ConfigError(
            "Combined preprocessing requires non-overlapping 'work_dir' and "
            f"'output_dir' paths: work_dir={work_dir}; output_dir={output_dir}"
        )


def paths_overlap(first: Path, second: Path) -> bool:
    """Return whether two paths are equal or one contains the other.

    Existing ancestors are compared by filesystem identity so case aliases on
    case-insensitive filesystems cannot bypass lifecycle safety checks. The
    lexical comparison remains necessary for destinations that do not exist
    yet.
    """

    return path_is_within(first, second) or path_is_within(second, first)


def path_is_within(path: Path, directory: Path) -> bool:
    """Return whether ``path`` is equal to or below ``directory`` safely."""

    candidate = Path(path).resolve(strict=False)
    root = Path(directory).resolve(strict=False)
    if candidate == root or root in candidate.parents:
        return True
    if not root.exists():
        return False
    for ancestor in (candidate, *candidate.parents):
        if not ancestor.exists():
            continue
        try:
            if ancestor.samefile(root):
                return True
        except OSError:
            continue
    return False


def collect_domain_paths(config: Config) -> dict[str, list[Path]]:
    """Expand domain patterns into matched file paths.

    Args:
        config: ``Config`` instance to evaluate.

    Returns:
        Mapping of domain name to matched file paths.

    Raises:
        ConfigError: If any domain pattern matches no files.
    """

    matches: dict[str, list[Path]] = {}
    for inspection in inspect_domain_paths(config):
        if not inspection.paths:
            raise ConfigError(
                "No files found for domain "
                f"'{inspection.name}' using pattern '{inspection.pattern}' "
                f"under {config.data_dir}"
            )
        matches[inspection.name] = list(inspection.paths)
    return matches


def inspect_domain_paths(
    config: Config,
    *,
    max_matches: int | None = None,
    domain_names: set[str] | None = None,
) -> list[DomainInspection]:
    """Inspect all configured domain patterns without failing on missing files."""

    if max_matches is not None and max_matches <= 0:
        raise ConfigError("max_matches must be a positive integer when provided.")

    if domain_names:
        unknown = sorted(domain_names - set(config.domains))
        if unknown:
            raise ConfigError(f"Unknown configured domain(s): {', '.join(unknown)}")

    inspections: list[DomainInspection] = []
    for domain_name, domain in config.domains.items():
        if domain_names and domain_name not in domain_names:
            continue
        pattern = domain.pattern
        search_dir = patterns_search_dir(config.data_dir, domain.pattern_list)
        file_paths, truncated = _inspect_patterns(
            config.data_dir,
            domain.pattern_list,
            max_matches=max_matches,
        )
        inspections.append(
            DomainInspection(
                name=domain_name,
                pattern=pattern,
                paths=file_paths,
                truncated=truncated,
                search_dir=search_dir,
                search_dir_exists=search_dir.is_dir() if search_dir else None,
            )
        )
    return inspections


def _inspect_patterns(
    data_dir: Path,
    patterns: tuple[str, ...],
    *,
    max_matches: int | None,
) -> tuple[tuple[Path, ...], bool]:
    file_paths: list[Path] = []
    seen: set[Path] = set()
    truncated = False
    for index, pattern in enumerate(patterns):
        remaining = None if max_matches is None else max_matches - len(file_paths)
        if remaining is not None and remaining <= 0:
            truncated = True
            break
        pattern_paths, pattern_truncated = _inspect_pattern(
            data_dir,
            pattern,
            max_matches=remaining,
        )
        for path in pattern_paths:
            if path in seen:
                continue
            seen.add(path)
            file_paths.append(path)
        if pattern_truncated:
            truncated = True
        if max_matches is not None and len(file_paths) >= max_matches:
            if pattern_truncated or index < len(patterns) - 1:
                truncated = True
            break
    return tuple(sorted(file_paths)), truncated


def _inspect_pattern(
    data_dir: Path,
    pattern: str,
    *,
    max_matches: int | None,
) -> tuple[tuple[Path, ...], bool]:
    if not data_dir.exists():
        return (), False
    if max_matches is None:
        paths = sorted(data_dir.glob(pattern))
        return tuple(path for path in paths if path.is_file()), False
    shallow_result = _inspect_shallow_pattern(
        data_dir,
        pattern,
        max_matches=max_matches,
    )
    if shallow_result is not None:
        return shallow_result

    file_paths: list[Path] = []
    truncated = False
    for path in data_dir.glob(pattern):
        if not path.is_file():
            continue
        if len(file_paths) >= max_matches:
            truncated = True
            break
        file_paths.append(path)
    return tuple(sorted(file_paths)), truncated


def _inspect_shallow_pattern(
    data_dir: Path,
    pattern: str,
    *,
    max_matches: int,
) -> tuple[tuple[Path, ...], bool] | None:
    """Inspect simple ``directory/prefix*.csv`` patterns without glob expansion.

    This path is used only for capped restore-readiness checks. It avoids
    per-entry stat calls because partially restored external volumes can block on
    file metadata. Exact validation and pipeline runs still verify matched paths
    with the normal discovery path.
    """

    pattern_path = Path(pattern)
    if pattern_path.is_absolute():
        return None
    parts = pattern_path.parts
    if not parts or any(part == "**" for part in parts):
        return None
    parent_parts = parts[:-1]
    filename_pattern = parts[-1]
    if any(_has_glob_meta(part) for part in parent_parts):
        return None
    if not _has_glob_meta(filename_pattern):
        return None

    directory = data_dir.joinpath(*parent_parts) if parent_parts else data_dir
    if not directory.exists():
        return (), False
    if not directory.is_dir():
        return (), False

    file_paths: list[Path] = []
    truncated = False
    with os.scandir(directory) as entries:
        for entry in entries:
            if not fnmatchcase(entry.name, filename_pattern):
                continue
            if len(file_paths) >= max_matches:
                truncated = True
                break
            file_paths.append(directory / entry.name)
    return tuple(sorted(file_paths)), truncated


def _has_glob_meta(value: str) -> bool:
    return any(char in value for char in "*?[")


def pattern_search_dir(data_dir: Path, pattern: str) -> Path | None:
    """Return the non-glob parent directory searched by a domain pattern."""

    pattern_path = Path(pattern)
    if pattern_path.is_absolute():
        return None
    parts = pattern_path.parts
    if not parts or any(part == "**" for part in parts):
        return None
    parent_parts = parts[:-1]
    if any(_has_glob_meta(part) for part in parent_parts):
        return None
    return data_dir.joinpath(*parent_parts) if parent_parts else data_dir


def patterns_search_dir(data_dir: Path, patterns: tuple[str, ...]) -> Path | None:
    """Return the shared non-glob parent directory for several patterns."""

    search_dirs = {pattern_search_dir(data_dir, pattern) for pattern in patterns}
    if len(search_dirs) != 1:
        return None
    return next(iter(search_dirs))


def _load_path(raw: dict[str, Any], key: str, base_dir: Path) -> Path:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"Config '{key}' must be a non-empty string path.")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve(strict=False)


def _load_domains(raw: Any) -> dict[str, DomainConfig]:
    if not isinstance(raw, dict) or not raw:
        raise ConfigError("Config 'domains' must be a non-empty mapping.")
    domains: dict[str, DomainConfig] = {}
    for name, value in raw.items():
        if isinstance(value, str):
            patterns = (value,)
        elif isinstance(value, dict):
            patterns = _load_domain_patterns(value, str(name))
        else:
            patterns = ()
        if not patterns:
            raise ConfigError(
                f"Domain '{name}' must define 'pattern' or non-empty 'patterns'."
            )
        pattern_label = patterns[0] if len(patterns) == 1 else " | ".join(patterns)
        domains[str(name)] = DomainConfig(pattern=pattern_label, patterns=patterns)
    return domains


def _load_domain_patterns(value: dict[str, Any], name: str) -> tuple[str, ...]:
    if "patterns" in value:
        raw_patterns = value.get("patterns")
        if not isinstance(raw_patterns, list):
            raise ConfigError(f"Domain '{name}' field 'patterns' must be a list.")
        patterns = tuple(raw_patterns)
    else:
        pattern = value.get("pattern")
        patterns = (pattern,)
    if not patterns or not all(
        isinstance(pattern, str) and pattern.strip() for pattern in patterns
    ):
        raise ConfigError(
            f"Domain '{name}' must define non-empty string pattern values."
        )
    return patterns


def _load_chunking(raw: Any) -> ChunkingConfig:
    if raw is None:
        return ChunkingConfig()
    if not isinstance(raw, dict):
        raise ConfigError("Config 'chunking' must be a mapping if provided.")
    enabled = bool(raw.get("enabled", False))
    lines_per_chunk = raw.get("lines_per_chunk", 10_000_000)
    if not isinstance(lines_per_chunk, int) or lines_per_chunk <= 0:
        raise ConfigError("'chunking.lines_per_chunk' must be a positive integer.")
    return ChunkingConfig(enabled=enabled, lines_per_chunk=lines_per_chunk)


def _load_rfs(raw: Any) -> RfsConfig:
    if raw is None:
        return RfsConfig()
    if not isinstance(raw, dict):
        raise ConfigError("Config 'rfs' must be a mapping if provided.")
    enabled = bool(raw.get("enabled", False))
    ruleset = str(raw.get("ruleset", "corrected_v1"))
    if ruleset != "corrected_v1":
        raise ConfigError("'rfs.ruleset' must be 'corrected_v1'.")
    abg_min = _positive_number(raw, "abg_min_pco2_mmhg", 45.0, section="rfs")
    vbg_min = _positive_number(raw, "vbg_min_pco2_mmhg", 45.0, section="rfs")
    return RfsConfig(
        enabled=enabled,
        ruleset=ruleset,
        abg_min_pco2_mmhg=abg_min,
        vbg_min_pco2_mmhg=vbg_min,
    )


def _load_cohort(raw: Any) -> CohortConfig:
    if raw is None:
        return CohortConfig()
    if not isinstance(raw, dict):
        raise ConfigError("Config 'cohort' must be a mapping if provided.")
    event_selection = str(raw.get("event_selection", "earliest_per_setting"))
    if event_selection != "earliest_per_setting":
        raise ConfigError("'cohort.event_selection' must be 'earliest_per_setting'.")
    return CohortConfig(event_selection=event_selection)


def _load_data_screen(raw: Any) -> DataScreenConfig:
    if raw is None:
        return DataScreenConfig()
    if not isinstance(raw, dict):
        raise ConfigError("Config 'data_screen' must be a mapping if provided.")
    mode = str(raw.get("mode", "diagnosis_or_lab"))
    source = str(raw.get("source", "derived"))
    if mode != "diagnosis_or_lab":
        raise ConfigError("'data_screen.mode' must be 'diagnosis_or_lab'.")
    if source not in {"derived", "legacy_files"}:
        raise ConfigError("'data_screen.source' must be 'derived' or 'legacy_files'.")
    return DataScreenConfig(mode=mode, source=source)


def _load_guardrails(raw: Any) -> GuardrailConfig:
    if raw is None:
        return GuardrailConfig()
    if not isinstance(raw, dict):
        raise ConfigError("Config 'guardrails' must be a mapping if provided.")
    max_join_multiplier = raw.get("max_join_multiplier", 1.0)
    if not isinstance(max_join_multiplier, (int, float)):
        raise ConfigError("'guardrails.max_join_multiplier' must be a number.")
    if max_join_multiplier <= 0:
        raise ConfigError("'guardrails.max_join_multiplier' must be positive.")
    return GuardrailConfig(max_join_multiplier=float(max_join_multiplier))


def _load_storage(raw: Any) -> StorageConfig:
    if raw is None:
        return StorageConfig()
    if not isinstance(raw, dict):
        raise ConfigError("Config 'storage' must be a mapping if provided.")

    intermediate_format = str(raw.get("intermediate_format", "csv")).lower()
    if intermediate_format not in {"csv", "parquet"}:
        raise ConfigError("'storage.intermediate_format' must be 'csv' or 'parquet'.")

    emit_legacy_csv_intermediates = bool(
        raw.get("emit_legacy_csv_intermediates", intermediate_format == "csv")
    )
    emit_normalized_domain_tables = bool(
        raw.get("emit_normalized_domain_tables", False)
    )

    parquet_row_group_size = raw.get("parquet_row_group_size", 250_000)
    if not isinstance(parquet_row_group_size, int) or parquet_row_group_size <= 0:
        raise ConfigError(
            "'storage.parquet_row_group_size' must be a positive integer."
        )

    analysis_bucket_count = raw.get("analysis_bucket_count", 256)
    if (
        not isinstance(analysis_bucket_count, int)
        or analysis_bucket_count <= 0
        or analysis_bucket_count & (analysis_bucket_count - 1)
    ):
        raise ConfigError(
            "'storage.analysis_bucket_count' must be a positive power of two."
        )
    emit_legacy_group_tables = bool(raw.get("emit_legacy_group_tables", False))

    return StorageConfig(
        intermediate_format=intermediate_format,
        emit_legacy_csv_intermediates=emit_legacy_csv_intermediates,
        emit_normalized_domain_tables=emit_normalized_domain_tables,
        parquet_row_group_size=parquet_row_group_size,
        analysis_bucket_count=analysis_bucket_count,
        emit_legacy_group_tables=emit_legacy_group_tables,
    )


def _load_combined(raw: Any, base_dir: Path) -> CombinedPreprocessingConfig:
    if raw is None:
        return CombinedPreprocessingConfig()
    if not isinstance(raw, dict):
        raise ConfigError("Config 'combined' must be a mapping if provided.")

    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ConfigError("'combined.enabled' must be true or false.")
    database_name = str(raw.get("database_name", "trinetx_preprocessed.duckdb")).strip()
    if not database_name or Path(database_name).name != database_name:
        raise ConfigError(
            "'combined.database_name' must be a filename without directories."
        )
    if not database_name.endswith(".duckdb"):
        raise ConfigError("'combined.database_name' must end with '.duckdb'.")

    schema_version = str(raw.get("schema_version", "1.0")).strip()
    if schema_version != "1.0":
        raise ConfigError("'combined.schema_version' must be '1.0'.")

    duckdb_memory_limit_mib = raw.get(
        "duckdb_memory_limit_mib",
        DEFAULT_COMBINED_DUCKDB_MEMORY_LIMIT_MIB,
    )
    if (
        not isinstance(duckdb_memory_limit_mib, int)
        or isinstance(duckdb_memory_limit_mib, bool)
        or duckdb_memory_limit_mib <= 0
    ):
        raise ConfigError(
            "'combined.duckdb_memory_limit_mib' must be a positive integer."
        )
    duckdb_core_memory_limit_mib = raw.get(
        "duckdb_core_memory_limit_mib",
        min(
            DEFAULT_COMBINED_DUCKDB_CORE_MEMORY_LIMIT_MIB,
            duckdb_memory_limit_mib,
        ),
    )
    if (
        not isinstance(duckdb_core_memory_limit_mib, int)
        or isinstance(duckdb_core_memory_limit_mib, bool)
        or duckdb_core_memory_limit_mib <= 0
    ):
        raise ConfigError(
            "'combined.duckdb_core_memory_limit_mib' must be a positive integer."
        )

    concept_sets_value = raw.get("concept_sets_dir")
    concept_sets_dir = None
    if concept_sets_value is not None:
        if not isinstance(concept_sets_value, str) or not concept_sets_value.strip():
            raise ConfigError(
                "'combined.concept_sets_dir' must be a non-empty path string."
            )
        concept_sets_dir = Path(concept_sets_value).expanduser()
        if not concept_sets_dir.is_absolute():
            concept_sets_dir = base_dir / concept_sets_dir
        concept_sets_dir = concept_sets_dir.resolve(strict=False)

    return CombinedPreprocessingConfig(
        enabled=enabled,
        database_name=database_name,
        schema_version=schema_version,
        concept_sets_dir=concept_sets_dir,
        duckdb_memory_limit_mib=duckdb_memory_limit_mib,
        duckdb_core_memory_limit_mib=duckdb_core_memory_limit_mib,
    )


def _positive_number(
    raw: dict[str, Any],
    key: str,
    default: float,
    *,
    section: str,
) -> float:
    value = raw.get(key, default)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise ConfigError(f"'{section}.{key}' must be a positive number.")
    return float(value)


def _require_dir(path: Path, label: str) -> None:
    if not path.exists():
        raise ConfigError(f"Config '{label}' does not exist: {path}")
    if not path.is_dir():
        raise ConfigError(f"Config '{label}' must be a directory: {path}")
