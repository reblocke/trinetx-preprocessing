"""Cohort-source candidate rules derived from the historical pipeline.

The historical preprocessing rules deliberately mix code matching with later
numeric, temporal, and cohort-selection steps.  This module exposes only the
code-matching part as source candidates.  A downstream cohort implementation
must apply its own value thresholds, unit handling, index selection, and
inclusion logic.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable

from ..glp1_eligibility.concept_sets import Concept
from ..transform import rfs
from ..transform.diagnosis import DIAGNOSIS_CODE_GROUPS
from ..transform.lab_features import LAB_VALUE_RULES
from ..transform.medications import MEDICATION_CODE_GROUPS
from ..transform.procedure import PROCEDURE_CODE_GROUPS
from ..transform.vitals import VITAL_SIGN_RULES

TRADITIONAL_CONCEPT_PREFIX = "traditional"
"""Namespace reserved for candidates from the historical pipeline."""

ANY_CODE_SYSTEM = "*"
"""Catalog code-system marker for legacy rules that did not restrict systems."""

TRADITIONAL_SOURCE_AUTHORITY = "historical-preprocessing-rules"
TRADITIONAL_SOURCE_VERSION = "1.0"
SOURCE_CANDIDACY_NOTE = (
    "Source candidacy only; numeric thresholds, units, temporal/index selection, "
    "and cohort inclusion remain downstream."
)


def traditional_concept_id(domain: str, rule_name: str) -> str:
    """Return the stable catalog identifier for one historical source rule."""

    normalized_domain = _normalize_identifier(domain)
    normalized_rule = _normalize_identifier(rule_name)
    if not normalized_domain or not normalized_rule:
        raise ValueError("Traditional source domain and rule name must be non-empty.")
    return f"{TRADITIONAL_CONCEPT_PREFIX}.{normalized_domain}.{normalized_rule}"


def traditional_concepts() -> tuple[Concept, ...]:
    """Return every historical code-rule candidate as versioned source concepts.

    The returned concepts intentionally reproduce code and code-system matching
    only.  Values, date windows, encounter selection, and final cohort logic
    are not encoded here because those decisions belong to downstream cohorts.
    """

    builder = _TraditionalConceptBuilder()
    builder.add_rules(
        domain="diagnosis",
        rules=DIAGNOSIS_CODE_GROUPS,
        source_file="transform/diagnosis.py",
        description_prefix="Historical diagnosis feature candidate",
    )
    builder.add_rules(
        domain="procedure",
        rules=PROCEDURE_CODE_GROUPS,
        source_file="transform/procedure.py",
        description_prefix="Historical procedure feature candidate",
    )
    builder.add_rules(
        domain="medication",
        rules=MEDICATION_CODE_GROUPS,
        source_file="transform/medications.py",
        description_prefix="Historical medication feature candidate",
    )
    builder.add_rules(
        domain="lab",
        rules=LAB_VALUE_RULES,
        source_file="transform/lab_features.py",
        description_prefix="Historical lab feature candidate",
    )
    builder.add_rules(
        domain="vital",
        rules=VITAL_SIGN_RULES,
        source_file="transform/vitals.py",
        description_prefix="Historical vital-sign feature candidate",
    )
    _add_rfs_candidates(builder)
    return builder.concepts


def _add_rfs_candidates(builder: "_TraditionalConceptBuilder") -> None:
    """Add RFS code candidates without importing RFS value or cohort gates."""

    builder.add_rules(
        domain="lab",
        rules=(
            rfs._pco2_rule(
                "rfs_abg",
                ("2019-8", "32771-8"),
                rfs.DEFAULT_ABG_VALUE_MIN,
            ),
            rfs._pco2_rule(
                "rfs_vbg",
                ("2021-4",),
                rfs.DEFAULT_VBG_VALUE_MIN,
            ),
        ),
        source_file="transform/rfs.py",
        description_prefix="Historical RFS source candidate",
    )
    builder.add_rules(
        domain="diagnosis",
        rules=(rfs.RESPFAIL_RULE,),
        source_file="transform/rfs.py",
        description_prefix="Historical RFS source candidate",
        element_names=("rfs_respfail",),
    )
    builder.add_rules(
        domain="diagnosis",
        rules=(rfs.OBESITY_DIAGNOSIS_RULE,),
        source_file="transform/rfs.py",
        description_prefix="Historical RFS source candidate",
        element_names=("rfs_obesity_diagnosis",),
    )
    builder.add_rules(
        domain="vital",
        rules=(rfs.OBESITY_BMI_RULE,),
        source_file="transform/rfs.py",
        description_prefix="Historical RFS source candidate",
        element_names=("rfs_obesity_bmi",),
    )
    builder.add_rules(
        domain="procedure",
        rules=(rfs.VENTSUPPORT_RULE,),
        source_file="transform/rfs.py",
        description_prefix="Historical RFS source candidate",
        element_names=("rfs_ventsupport",),
    )
    builder.add_rules(
        domain="diagnosis",
        rules=(rfs.PREDISPOSITION_RULE,),
        source_file="transform/rfs.py",
        description_prefix="Historical RFS source candidate",
        element_names=("rfs_predisposition",),
    )


class _TraditionalConceptBuilder:
    """Build deterministic, provenance-preserving Concept rows."""

    def __init__(self) -> None:
        self._concepts: list[Concept] = []
        self._element_ids: set[str] = set()
        self._source_rows: defaultdict[str, int] = defaultdict(int)

    @property
    def concepts(self) -> tuple[Concept, ...]:
        """Return the generated catalog rows in stable source order."""

        return tuple(self._concepts)

    def add_rules(
        self,
        *,
        domain: str,
        rules: Iterable[object],
        source_file: str,
        description_prefix: str,
        element_names: tuple[str, ...] | None = None,
    ) -> None:
        """Add typed code rules with their legacy matching semantics only."""

        selected_rules = tuple(rules)
        if element_names is not None and len(element_names) != len(selected_rules):
            raise ValueError("Each traditional rule override must name one rule.")
        for index, rule in enumerate(selected_rules):
            rule_name = element_names[index] if element_names is not None else rule.name
            concept_set_id = traditional_concept_id(domain, rule_name)
            if concept_set_id in self._element_ids:
                raise ValueError(f"Duplicate traditional source rule: {concept_set_id}")
            self._element_ids.add(concept_set_id)
            self._add_rule_rows(
                concept_set_id=concept_set_id,
                domain=domain,
                rule=rule,
                source_file=source_file,
                description=f"{description_prefix}: {rule.name}",
            )

    def _add_rule_rows(
        self,
        *,
        concept_set_id: str,
        domain: str,
        rule: object,
        source_file: str,
        description: str,
    ) -> None:
        exact_codes = tuple(getattr(rule, "exact_codes", ()))
        prefixes = tuple(getattr(rule, "prefixes", ()))
        allowed_code_systems = tuple(getattr(rule, "allowed_code_systems", ()))
        if not exact_codes and not prefixes:
            raise ValueError(f"Traditional rule {concept_set_id!r} has no codes.")
        code_systems = allowed_code_systems or (ANY_CODE_SYSTEM,)
        for match_type, codes in (("exact", exact_codes), ("prefix", prefixes)):
            for code in codes:
                for code_system in code_systems:
                    self._source_rows[source_file] += 1
                    self._concepts.append(
                        Concept(
                            concept_set_id=concept_set_id,
                            domain=domain,
                            code_system=str(code_system),
                            code=str(code).strip().upper(),
                            match_type=match_type,
                            include=True,
                            description=description,
                            source_authority=TRADITIONAL_SOURCE_AUTHORITY,
                            source_version=TRADITIONAL_SOURCE_VERSION,
                            effective_start=None,
                            effective_end=None,
                            notes=SOURCE_CANDIDACY_NOTE,
                            source_file=source_file,
                            source_row=self._source_rows[source_file],
                        )
                    )


def _normalize_identifier(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
