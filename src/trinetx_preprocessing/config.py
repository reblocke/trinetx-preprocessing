"""Configuration loading and validation for the preprocessing pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """Raised when configuration values are invalid."""


@dataclass(frozen=True)
class DomainConfig:
    """Domain-specific configuration."""

    pattern: str


@dataclass(frozen=True)
class ChunkingConfig:
    """Chunking configuration."""

    enabled: bool = False
    lines_per_chunk: int = 10_000_000


@dataclass(frozen=True)
class RfsConfig:
    """RFS configuration."""

    enabled: bool = False


@dataclass(frozen=True)
class GuardrailConfig:
    """Performance guardrail configuration."""

    max_join_multiplier: float = 1.0


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
    guardrails = _load_guardrails(raw.get("guardrails"))

    return Config(
        data_dir=data_dir,
        work_dir=work_dir,
        output_dir=output_dir,
        domains=domains,
        chunking=chunking,
        rfs=rfs,
        guardrails=guardrails,
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
    collect_domain_paths(config)


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
    for domain_name, domain in config.domains.items():
        pattern = domain.pattern
        paths = sorted(config.data_dir.glob(pattern))
        file_paths = [path for path in paths if path.is_file()]
        if not file_paths:
            raise ConfigError(
                "No files found for domain "
                f"'{domain_name}' using pattern '{pattern}' under {config.data_dir}"
            )
        matches[domain_name] = file_paths
    return matches


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
            pattern = value
        elif isinstance(value, dict):
            pattern = value.get("pattern")
        else:
            pattern = None
        if not isinstance(pattern, str) or not pattern.strip():
            raise ConfigError(
                f"Domain '{name}' must define a non-empty 'pattern' string."
            )
        domains[str(name)] = DomainConfig(pattern=pattern)
    return domains


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
    return RfsConfig(enabled=enabled)


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


def _require_dir(path: Path, label: str) -> None:
    if not path.exists():
        raise ConfigError(f"Config '{label}' does not exist: {path}")
    if not path.is_dir():
        raise ConfigError(f"Config '{label}' must be a directory: {path}")
