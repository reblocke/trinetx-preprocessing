"""Conservative change classification and reproducible source fingerprints."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
POLICY = ROOT / "config/verification_policy.json"
RANK = {"static": 0, "workflow": 1, "materialization": 2, "scientific": 3}
# These modules only observe artifacts. Any other code change invalidates reuse.
NON_PRODUCERS = (
    "src/trinetx_preprocessing/__main__.py",
    "src/trinetx_preprocessing/verification/",
    "src/trinetx_preprocessing/glp1_eligibility/parity.py",
    "src/trinetx_preprocessing/combined_preprocessing/validation.py",
    "src/trinetx_preprocessing/combined_preprocessing/evidence.py",
)


def git(*args: str, root: Path = ROOT) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *args])


def sha(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def code_fingerprint(
    ref: str,
    *,
    root: Path = ROOT,
    materialization: bool = False,
    raw_reference: bool = False,
) -> str:
    """Reproduce the producer's historical content hash, including path/mode."""
    paths = (
        git(
            "ls-tree",
            "-r",
            "--name-only",
            "-z",
            ref,
            "--",
            "src",
            "pyproject.toml",
            "uv.lock",
            root=root,
        )
        .decode()
        .split("\0")
    )
    digest = hashlib.sha256()
    for path in sorted(p for p in paths if p):
        if materialization and path.startswith(NON_PRODUCERS):
            continue
        if raw_reference and path.startswith(
            NON_PRODUCERS
            + ("src/trinetx_preprocessing/combined_preprocessing/glp1_adapter.py",)
        ):
            continue
        entry = git("ls-tree", ref, "--", path, root=root).decode()
        content = git("show", f"{ref}:{path}", root=root)
        digest.update(b"path\0" + path.encode() + b"\0")
        digest.update(b"symlink\0" if entry.startswith("120000") else b"file\0")
        digest.update(content + b"\0")
    return digest.hexdigest()


def classify(paths: list[str], policy: dict) -> dict:
    routes = []
    for path in sorted(set(paths)):
        rule = next(
            (
                r
                for r in policy["rules"]
                if any(fnmatch.fnmatchcase(path, p) for p in r["patterns"])
            ),
            None,
        )
        routes.append(
            {
                "path": path,
                "gate": rule["gate"] if rule else "materialization",
                "products": rule["products"] if rule else policy["products"],
                "unknown": rule is None,
            }
        )
    gate = max((r["gate"] for r in routes), key=RANK.get, default="static")
    return {
        "gate": gate,
        "routes": routes,
        "products": sorted({p for r in routes for p in r["products"]}),
        "unknown_paths": [r["path"] for r in routes if r["unknown"]],
    }


def make_plan(base: str, head: str = "HEAD", *, root: Path = ROOT) -> dict:
    base_sha = (
        git("rev-parse", "--verify", f"{base}^{{commit}}", root=root).decode().strip()
    )
    head_sha = (
        git("rev-parse", "--verify", f"{head}^{{commit}}", root=root).decode().strip()
    )
    policy = json.loads((root / "config/verification_policy.json").read_text())
    paths = (
        git("diff", "--name-only", "--no-renames", "-z", base_sha, head_sha, root=root)
        .decode()
        .split("\0")
    )
    # Include both sides of renames, staged/unstaged changes and untracked files.
    dirty = (
        git("diff", "--name-only", "--no-renames", "-z", head_sha, root=root)
        .decode()
        .split("\0")
    )
    untracked = (
        git("ls-files", "--others", "--exclude-standard", "-z", root=root)
        .decode()
        .split("\0")
    )
    result = classify([p for p in paths + dirty + untracked if p], policy)
    result.update(
        schema_version=1,
        base=base_sha,
        head=head_sha,
        policy_sha256=sha(policy),
        clean=not any(dirty + untracked),
        code_sha256=code_fingerprint(head_sha, root=root),
    )
    result["plan_sha256"] = sha(result)
    result["required"] = ["public_tests", "lint"]
    if result["gate"] != "static":
        result["required"] += ["source_contract", "glp1_full_data_parity"]
    if "canonical" in result["products"]:
        result["required"] += ["canonical_build", "compatibility36"]
    if result["gate"] == "scientific":
        result["required"] += ["approved_scientific_decision", "drift_report"]
    return result
