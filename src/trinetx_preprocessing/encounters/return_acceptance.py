"""Strict, independently trusted acceptance boundary for calendar-day returns.

This verifies existing evidence. It never creates acceptance or discovers trust.
The original historical receipt remains a receipt for its original artifacts.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from .acceptance import _json, _sha256
from .builder import VARIANTS, literal, sha256
from .compatibility import no_symlinks

ACCEPTANCE_CONTRACT_VERSION = "1.0"
VALIDATION_REPORT_VERSION = "1.0"
DATA_CONTRACT_VERSION = "2.0"
KEYS = ("patient_id", "encounter_id", "index_event_id")
TABLES = (
    "episode_source",
    "episodes",
    "diagnosis_evidence",
    "gas_evidence",
    "links",
    "summary",
)
PRODUCTION_IDENTITIES = frozenset(
    {"producer", "source_stage", "contract", "configuration", "catalog", "environment"}
)
IDENTITIES = PRODUCTION_IDENTITIES | {
    "parent_validator",
    "outcome_validator",
    "validator_environment",
}
REQUIRED_GATES = frozenset(
    {
        "source_validation",
        "parent_validation",
        "artifact_validation",
        "retained_reference",
        "unchanged_inputs",
        "original_keys",
    }
)
KEY_ALGORITHM = "return-original-keys-json-utf8-length64be-v1"


def canonical_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def artifact_inventory_digest(inventory: dict) -> str:
    return canonical_digest(inventory)


def frozen_table_schema(table: str) -> pa.Schema:
    contract = _json(Path(__file__).with_name("return_artifact_contract.json"))
    types = {
        "string": pa.string(),
        "bool": pa.bool_(),
        "int64": pa.int64(),
        "uint64": pa.uint64(),
        "double": pa.float64(),
        "date32[day]": pa.date32(),
        "timestamp[us]": pa.timestamp("us"),
    }
    if (
        table not in TABLES
        or contract.get("data_contract_version") != DATA_CONTRACT_VERSION
    ):
        raise ValueError("Unsupported frozen return schema")
    return pa.schema(
        [
            pa.field(f["name"], types[f["type"]], nullable=f["nullable"])
            for f in contract["tables"][table]
        ]
    )


def frozen_summary_schema() -> pa.Schema:
    return frozen_table_schema("summary")


def key_proof(
    paths: list[Path], *, parent: bool = False, work_dir: Path | None = None
) -> dict:
    """Bounded, globally sorted exact original-key digest with uniqueness checks.

    The original index field is mapped only by explicit parent=True. Full
    validation compares both complete key relations as well as these digests.
    """
    if not paths:
        raise ValueError("Original-key proof requires explicit artifacts")
    for path in paths:
        no_symlinks(path)
    index = "pat_enc_hash" if parent else "index_event_id"
    relation = "read_parquet([" + ",".join(literal(p) for p in paths) + "])"
    with duckdb.connect() as db:
        db.execute("SET threads=1")
        db.execute("SET memory_limit='512MiB'")
        if work_dir is not None:
            no_symlinks(work_dir).mkdir(mode=0o700, parents=True, exist_ok=True)
            db.execute("SET temp_directory=?", [str(work_dir)])
        else:
            # Consumers must not spill private linkage fields into an implicit cwd.
            db.execute("SET max_temp_directory_size='0B'")
        cursor = db.execute(
            f"SELECT patient_id, encounter_id, {index} FROM {relation} "
            f"ORDER BY patient_id, encounter_id, {index}"
        )
        digest = hashlib.sha256()
        previous = None
        count = 0
        while batch := cursor.fetchmany(8192):
            for row in batch:
                if any(not isinstance(value, str) for value in row):
                    raise ValueError("Original composite keys must be non-null strings")
                if row == previous:
                    raise ValueError("Duplicate original composite key")
                previous = row
                data = json.dumps(
                    row, ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")
                digest.update(len(data).to_bytes(8, "big"))
                digest.update(data)
                count += 1
    return {"algorithm": KEY_ALGORITHM, "rows": count, "sha256": digest.hexdigest()}


def summary_names(manifest: dict, variant: str) -> list[str]:
    if variant not in VARIANTS:
        raise ValueError("variant must be FULL_DATA or AFTER_EXCLUSION")
    return [
        f"{variant.lower()}_{bucket:04d}_summary.parquet"
        for bucket in range(manifest["partitions"])
    ]


def verify_return_output(bundle: Path, manifest: dict, name: str) -> Path:
    if Path(name).name != name or name not in manifest["outputs"]:
        raise ValueError("Unlisted return artifact")
    root = no_symlinks(bundle)
    path = no_symlinks(root / name)
    info = manifest["outputs"][name]
    if not path.is_file() or not isinstance(info, dict):
        raise ValueError(f"Missing return artifact: {name}")
    if path.stat().st_size != info.get("bytes") or sha256(path) != info.get("sha256"):
        raise ValueError(f"Return artifact identity differs: {name}")
    return path


def _verify_proof(proof: object) -> None:
    if (
        not isinstance(proof, dict)
        or set(proof) != {"algorithm", "rows", "sha256"}
        or proof.get("algorithm") != KEY_ALGORITHM
        or type(proof.get("rows")) is not int
        or proof["rows"] < 0
    ):
        raise ValueError("Invalid trusted original-key proof")
    _sha256(proof["sha256"], "original keys")


def verify_accepted_return_bundle(
    bundle: Path,
    *,
    variant: str,
    receipt_path: Path,
    expected_receipt_sha256: str,
    validation_report_path: Path,
) -> dict:
    """Verify full evidence, inventory, frozen schemas and both original key sets."""
    if variant not in VARIANTS:
        raise ValueError("variant must be FULL_DATA or AFTER_EXCLUSION")
    root = no_symlinks(bundle)
    receipt_path = no_symlinks(receipt_path)
    validation_report_path = no_symlinks(validation_report_path)
    trusted = _sha256(expected_receipt_sha256, "trusted return receipt")
    if sha256(receipt_path) != trusted:
        raise ValueError("Return acceptance receipt differs from trusted SHA-256")
    receipt = _json(receipt_path)
    report_hash = sha256(validation_report_path)
    report = _json(validation_report_path)
    manifest_path = root / "manifest.json"
    manifest_hash = sha256(no_symlinks(manifest_path))
    manifest = _json(manifest_path)
    if (
        receipt.get("kind") != "return_outcomes_acceptance"
        or receipt.get("status") != "accepted"
        or receipt.get("acceptance_contract_version") != ACCEPTANCE_CONTRACT_VERSION
        or report.get("validation_report_version") != VALIDATION_REPORT_VERSION
        or report.get("pass") is not True
        or manifest.get("kind") != "return_outcomes"
        or manifest.get("status") != "complete"
    ):
        raise ValueError("Unsupported or incomplete return acceptance/report contract")
    for document in (receipt, report, manifest):
        if (
            document.get("schema_version") != DATA_CONTRACT_VERSION
            or document.get("return_contract_version") != DATA_CONTRACT_VERSION
        ):
            raise ValueError("Unsupported return data/scientific contract")
    if receipt.get("validation_report_sha256") != report_hash or any(
        d.get("bundle_manifest_sha256") != manifest_hash for d in (receipt, report)
    ):
        raise ValueError("Return manifest or report binding differs")
    for field in (
        "parent_manifest_sha256",
        "source_manifest_sha256",
        "source_database_sha256",
    ):
        expected = _sha256(manifest.get(field), field)
        if any(d.get(field) != expected for d in (receipt, report)):
            raise ValueError(f"Return {field} provenance differs")
    production = manifest.get("identities")
    identities = receipt.get("identities")
    if (
        not isinstance(production, dict)
        or set(production) != PRODUCTION_IDENTITIES
        or not isinstance(identities, dict)
        or set(identities) != IDENTITIES
    ):
        raise ValueError("Incomplete return dependency identities")
    for name, value in identities.items():
        _sha256(value, name)
    if report.get("identities") != identities:
        raise ValueError("Return validator dependency bindings differ")
    if any(identities[name] != value for name, value in production.items()):
        raise ValueError("Return producer dependency bindings differ")
    gates = receipt.get("gates", {})
    if not isinstance(gates, dict) or not REQUIRED_GATES <= gates.keys():
        raise ValueError("Missing required return acceptance gates")
    for name in REQUIRED_GATES:
        gate = gates[name]
        if not isinstance(gate, dict) or gate.get("status") != "pass":
            raise ValueError(f"Return acceptance gate did not pass: {name}")
        _sha256(gate.get("evidence_sha256"), name)
    partitions = manifest.get("partitions")
    if (
        type(partitions) is not int
        or not 1 <= partitions <= 1024
        or manifest.get("variants") != list(VARIANTS)
        or manifest.get("horizons_days") != [30, 90, 365]
    ):
        raise ValueError("Unsupported return inventory configuration")
    expected_names = {"data_dictionary.json", "progress.json"} | {
        f"{v.lower()}_{b:04d}_{t}.parquet"
        for v in VARIANTS
        for b in range(partitions)
        for t in TABLES
    }
    inventory = manifest.get("outputs")
    if not isinstance(inventory, dict) or set(inventory) != expected_names:
        raise ValueError("Incomplete or extra return artifact inventory")
    actual = {p.name for p in root.iterdir() if not p.name.startswith("._")}
    if actual != expected_names | {"manifest.json"}:
        raise ValueError("Return directory inventory differs")
    inventory_hash = artifact_inventory_digest(inventory)
    if any(
        d.get("artifact_inventory_sha256") != inventory_hash for d in (receipt, report)
    ):
        raise ValueError("Return inventory provenance differs")
    for name in sorted(expected_names):
        path = verify_return_output(root, manifest, name)
        if name.endswith(".parquet"):
            table = next(t for t in TABLES if name.endswith(f"_{t}.parquet"))
            if not pq.read_schema(path).equals(
                frozen_table_schema(table), check_metadata=False
            ):
                raise ValueError(
                    f"Actual return schema differs from frozen contract: {name}"
                )
    proofs = receipt.get("original_keys")
    if (
        not isinstance(proofs, dict)
        or set(proofs) != set(VARIANTS)
        or report.get("original_keys") != proofs
    ):
        raise ValueError("Missing or inconsistent original-key evidence")
    for v in VARIANTS:
        _verify_proof(proofs[v])
        if key_proof([root / n for n in summary_names(manifest, v)]) != proofs[v]:
            raise ValueError(f"Return original composite keys differ: {v}")
    if (
        sha256(receipt_path) != trusted
        or sha256(validation_report_path) != report_hash
        or sha256(manifest_path) != manifest_hash
    ):
        raise ValueError("Return acceptance evidence changed during verification")
    return manifest
