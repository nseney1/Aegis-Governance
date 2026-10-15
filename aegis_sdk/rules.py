"""Rule data structures and utilities (Aegis Rule Model)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from fractions import Fraction
import math
import os
from typing import Optional, Tuple, Union

from aegis_core.taxonomy import ReviewMode, normalize_review_mode
from aegis_sdk.errors import (
    RuleNotFoundError,
    RuleParseError,
    RulePathTraversalError,
)
from aegis_sdk.scoring import bayesian_posterior, laplace_score

yaml = None  # Zero-dependency runtime sentinel


def _stdlib_parse_frontmatter(yaml_text: str) -> dict:
    from aegis_core.yaml_engine.parser import FrontmatterError, parse_yaml_subset
    try:
        res = parse_yaml_subset(yaml_text)
        if not isinstance(res, dict):
            raise RuleParseError("Frontmatter is not a mapping")
        return res
    except FrontmatterError as e:
        raise RuleParseError(f"Invalid YAML frontmatter: {e}") from e


__all__ = [
    "Rule",
    "RuleFitness",
    "parse_rule_file",
    "write_rule_frontmatter",
    "save_rule_file",
    "load_rule",
    "dump_rule",
]


@dataclass
class RuleFitness:
    """Fitness metrics for a governance rule."""
    triggers: int = 0
    true_positives: Union[int, float] = 0
    false_positives: Union[int, float] = 0
    score: Optional[float] = None
    stress_survived: int = 0

    def __post_init__(self):
        self.triggers = int(self._coerce_num(self.triggers, default=0))
        self.true_positives = self._coerce_num(self.true_positives, default=0)
        self.false_positives = self._coerce_num(self.false_positives, default=0)
        if self.score is not None:
            self.score = self._coerce_num(self.score, default=None)

    @staticmethod
    def _coerce_num(val, default=0):
        if val is None or isinstance(val, bool):
            return default
        if isinstance(val, (int, float)):
            if not math.isfinite(val):
                return default
            val = max(0, val)
            return int(val) if isinstance(val, float) and val.is_integer() else val
        if isinstance(val, str):
            val = val.strip()
            if not val:
                return default
            if "/" in val:
                try:
                    f = Fraction(val)
                    flt = float(f)
                    if not math.isfinite(flt):
                        return default
                    flt = max(0.0, flt)
                    return int(flt) if flt.is_integer() else round(flt, 4)
                except Exception:
                    return default
            try:
                flt = float(val)
                if not math.isfinite(flt):
                    return default
                flt = max(0.0, flt)
                return int(flt) if flt.is_integer() else round(flt, 4)
            except Exception:
                return default
        return default

    @property
    def raw_score(self) -> float | None:
        if self.triggers == 0:
            return None
        return self.true_positives / self.triggers

    @property
    def snr_db(self) -> float | None:
        """Signal-to-noise ratio in decibels."""
        from aegis_core.scoring import calculate_snr
        return calculate_snr(self.true_positives, self.false_positives)

    def bayesian(self, confidence: float = 0.90) -> dict[str, float | str]:
        """Wilson-bounded posterior with Jeffrey's prior."""
        return bayesian_posterior(
            tp=self.true_positives,
            fp=self.false_positives,
            confidence=confidence,
        )


@dataclass
class Rule:
    """An Aegis governance rule."""
    name: str
    type: str = "trap"
    hypothesis: str = ""
    prediction: str = ""
    falsification: str = ""
    target_paths: list = field(default_factory=list)
    minimum_mode: str = str(ReviewMode.PATROL)
    tags: list = field(default_factory=list)
    fitness: RuleFitness = field(default_factory=RuleFitness)
    created_date: Optional[Union[datetime, date, str]] = None

    def __post_init__(self) -> None:
        self.minimum_mode = normalize_review_mode(
            self.minimum_mode, default=str(ReviewMode.PATROL)
        )

    @property
    def is_invariant(self) -> bool:
        return self.type in ("invariant", "wall")

    @property
    def is_wall(self) -> bool:
        return self.is_invariant

    @property
    def is_extinct(self) -> bool:
        if self.fitness.triggers == 0:
            return False
        score = laplace_score(self.fitness.true_positives, self.fitness.triggers)
        return score <= 0.15

    @property
    def is_promotable(self) -> bool:
        if self.fitness.triggers == 0:
            return False
        score = laplace_score(self.fitness.true_positives, self.fitness.triggers)
        return score > 0.85 and self.fitness.triggers >= 20

    def is_promotable_with_age(self, min_age_days: int = 0) -> bool:
        if not self.is_promotable:
            return False
        if min_age_days > 0:
            c_date = getattr(self, "created_date", None)
            if not c_date:
                return False
            if isinstance(c_date, str):
                try:
                    c_date = datetime.strptime(
                        c_date, "%Y-%m-%d" if "T" not in c_date else "%Y-%m-%dT%H:%M:%SZ"
                    )
                except Exception:
                    return False
            elif isinstance(c_date, date) and not isinstance(c_date, datetime):
                c_date = datetime.combine(c_date, datetime.min.time())
            if not isinstance(c_date, datetime):
                return False
            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            created_utc = (
                c_date.replace(tzinfo=None)
                if hasattr(c_date, "tzinfo") and c_date.tzinfo
                else c_date
            )
            if (now_utc - created_utc).days < min_age_days:
                return False
        return True


def parse_rule_file(filepath: str) -> Tuple[dict, str]:
    """Parse a rule markdown file into (frontmatter_dict, body_text)."""
    if not os.path.isfile(filepath):
        raise RuleNotFoundError(f"Rule file not found: {filepath}")

    from aegis_core.yaml_engine.frontmatter import parse_rule_frontmatter
    try:
        return parse_rule_frontmatter(filepath)
    except ValueError as exc:
        raise RuleParseError(f"Error parsing rule {filepath}: {exc}") from exc


def write_rule_frontmatter(
    filepath: str,
    frontmatter: dict,
    body: str,
) -> None:
    """Write a rule file with YAML frontmatter and body text."""
    from aegis_core.yaml_engine.serializer import dump_frontmatter
    yaml_text = dump_frontmatter(frontmatter)

    content = f"---\n{yaml_text.strip()}\n---\n"
    if body:
        content += body

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)


def _sanitize_rule_id(rule_id: str) -> str:
    """Validate rule_id against path traversal attacks."""
    if ".." in rule_id or rule_id.startswith("/"):
        raise RulePathTraversalError(f"Invalid rule_id: {rule_id}")
    return rule_id


_sanitize_cell_id = _sanitize_rule_id


def load_rule(
    rule_id: str,
    cells_dir: Optional[str] = None,
    rules_dir: Optional[str] = None,
) -> Rule:
    """Load a Rule by its ID from the rules directory."""
    rule_id = _sanitize_rule_id(rule_id)
    target_dir = rules_dir or cells_dir

    if target_dir is None:
        cwd = os.getcwd()
        cand_aegis = os.path.join(cwd, ".aegis", "rules")
        if os.path.isdir(cand_aegis):
            target_dir = cand_aegis
        else:
            raise RuleNotFoundError(f"Cannot find .aegis/rules/ from {cwd}")

    target_fname = f"{rule_id}.md"
    found_path = None
    standard_subdirs = (
        "invariants",
        "traps",
        "boundaries",
        "personas",
        "contracts",
        "gates",
        "walls",
        "membranes",
        "ribosomes",
        "nuclei",
        "",
    )
    for subdir in standard_subdirs:
        candidate_file = (
            os.path.join(target_dir, subdir, target_fname)
            if subdir
            else os.path.join(target_dir, target_fname)
        )
        if os.path.isfile(candidate_file):
            found_path = candidate_file
            break

    if not found_path:
        for root, _dirs, files in os.walk(target_dir):
            if target_fname in files:
                found_path = os.path.join(root, target_fname)
                break

    if found_path:
        filepath = found_path
        real_path = os.path.realpath(filepath)
        real_rules = os.path.realpath(target_dir)
        if not real_path.startswith(real_rules):
            raise RulePathTraversalError(f"Resolved path escapes rules dir: {filepath}")
        frontmatter, _body = parse_rule_file(filepath)
        fitness_data = frontmatter.get("fitness", {})
        if isinstance(fitness_data, (int, float)):
            fitness_data = {"score": float(fitness_data)}
        elif not isinstance(fitness_data, dict):
            fitness_data = {}
        rule_inst = Rule(
            name=frontmatter.get("name", rule_id),
            type=frontmatter.get("type", "trap"),
            hypothesis=frontmatter.get("hypothesis", ""),
            prediction=frontmatter.get("prediction", ""),
            falsification=frontmatter.get("falsification", ""),
            target_paths=frontmatter.get("target_paths", []),
            minimum_mode=normalize_review_mode(
                frontmatter.get("minimum_mode"), default=str(ReviewMode.PATROL)
            ),
            tags=frontmatter.get("tags", []),
            fitness=RuleFitness(
                triggers=fitness_data.get("triggers", 0),
                true_positives=fitness_data.get("true_positives", 0),
                false_positives=fitness_data.get("false_positives", 0),
                score=fitness_data.get("score"),
                stress_survived=fitness_data.get("stress_survived", 0),
            ),
            created_date=frontmatter.get("created_date") or frontmatter.get("created"),
        )
        if not rule_inst.created_date and os.path.exists(filepath):
            try:
                rule_inst.created_date = datetime.fromtimestamp(
                    os.path.getctime(filepath), tz=timezone.utc
                )
            except Exception:
                pass
        return rule_inst

    raise RuleNotFoundError(f"Rule not found: {rule_id}")


def dump_rule(frontmatter: dict, body: str = "") -> str:
    """Dump rule dictionary and body to markdown with frontmatter."""
    from aegis_core.yaml_engine.serializer import dump_frontmatter
    yaml_text = dump_frontmatter(frontmatter)
    content = f"---\n{yaml_text.strip()}\n---\n"
    if body:
        content += body
    return content


save_rule_file = write_rule_frontmatter
