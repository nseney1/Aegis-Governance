"""Cell data structures and utilities."""
from __future__ import annotations
from datetime import datetime, timezone, date
import math
import os
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Callable, Optional, Tuple, Union


from soma_sdk.errors import CellParseError, CellNotFoundError, CellPathTraversalError
from soma_sdk.scoring import bayesian_posterior, laplace_score

yaml = None  # Backward-compatible sentinel: zero-dependency runtime


def _stdlib_parse_frontmatter(yaml_text: str) -> dict:
    from soma_core.somayaml import parse_yaml_subset, FrontmatterError
    try:
        res = parse_yaml_subset(yaml_text)
        if not isinstance(res, dict):
            raise CellParseError("Frontmatter is not a mapping")
        return res
    except FrontmatterError as e:
        raise CellParseError(f"Invalid YAML frontmatter: {e}") from e


__all__ = [
    "Cell",
    "CellFitness",
    "Rule",
    "RuleFitness",
    "parse_cell_file",
    "parse_rule_file",
    "write_cell_frontmatter",
    "write_rule_frontmatter",
    "save_cell_file",
    "save_rule_file",
    "load_cell",
    "load_rule",
    "dump_cell",
    "dump_rule",
]



@dataclass
class CellFitness:
    """Fitness metrics for a governance cell."""
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
            if '/' in val:
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
        from soma_core.scoring import calculate_snr
        return calculate_snr(self.true_positives, self.false_positives)
    
    def bayesian(self, confidence: float = 0.90) -> dict[str, float | str]:
        """Wilson-bounded posterior with Jeffrey's prior.

        Delegates to soma_sdk.scoring.bayesian_posterior.
        """
        return bayesian_posterior(
            tp=self.true_positives,
            fp=self.false_positives,
            confidence=confidence,
        )


@dataclass
class Cell:
    """A Soma immune cell."""
    name: str
    type: str  # wall | vacuole | membrane | chloroplast | plasmodesmata
    hypothesis: str = ''
    prediction: str = ''
    falsification: str = ''
    target_paths: list = field(default_factory=list)
    minimum_mode: str = 'breeze'
    tags: list = field(default_factory=list)
    fitness: CellFitness = field(default_factory=CellFitness)
    created_date: Optional[Union[datetime, date, str]] = None
    
    @property
    def is_wall(self) -> bool:
        return self.type == 'wall'
    
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
            c_date = getattr(self, 'created_date', None)
            if not c_date:
                return False
            if isinstance(c_date, str):
                try:
                    c_date = datetime.strptime(c_date, "%Y-%m-%d" if 'T' not in c_date else "%Y-%m-%dT%H:%M:%SZ")
                except Exception:
                    return False
            elif isinstance(c_date, date) and not isinstance(c_date, datetime):
                c_date = datetime.combine(c_date, datetime.min.time())
            if not isinstance(c_date, datetime):
                return False
            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            created_utc = c_date.replace(tzinfo=None) if hasattr(c_date, 'tzinfo') and c_date.tzinfo else c_date
            if (now_utc - created_utc).days < min_age_days:
                return False
        return True


# ---------------------------------------------------------------------------
# Canonical Cell Parser (Phase 2.1)
# ---------------------------------------------------------------------------

def parse_cell_file(filepath: str) -> Tuple[dict, str]:
    """Parse a cell markdown file into (frontmatter_dict, body_text).

    The single source of truth for YAML frontmatter parsing.

    Args:
        filepath: Absolute or relative path to a cell .md file.

    Returns:
        Tuple of (frontmatter_dict, body_text).

    Raises:
        CellNotFoundError: If the file does not exist.
        CellParseError: If the file has no valid YAML frontmatter.
    """
    if not os.path.isfile(filepath):
        raise CellNotFoundError(f"Cell file not found: {filepath}")

    from soma_core.somayaml import parse_cell_frontmatter
    try:
        return parse_cell_frontmatter(filepath)
    except ValueError as exc:
        raise CellParseError(f"Error parsing cell {filepath}: {exc}") from exc


def write_cell_frontmatter(
    filepath: str,
    frontmatter: dict,
    body: str,
) -> None:
    """Write a cell file with YAML frontmatter and body text.

    Args:
        filepath: Path to write the cell file.
        frontmatter: Dict to serialize as YAML frontmatter.
        body: Markdown body text.
    """
    from soma_core.somayaml import dump_frontmatter
    yaml_text = dump_frontmatter(frontmatter)

    content = f"---\n{yaml_text.strip()}\n---\n"
    if body:
        content += body

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)


def _sanitize_cell_id(cell_id: str) -> str:
    """Validate cell_id against path traversal attacks.

    Raises:
        CellPathTraversalError: If cell_id contains '..' or starts with '/'.
    """
    if '..' in cell_id or cell_id.startswith('/'):
        raise CellPathTraversalError(f"Invalid cell_id: {cell_id}")
    return cell_id


def load_cell(
    cell_id: str,
    cells_dir: Optional[str] = None,
) -> Cell:
    """Load a Cell by its ID from the cells directory.

    Args:
        cell_id: Cell identifier (filename without extension).
        cells_dir: Path to .soma/cells/ directory. Defaults to auto-detect.

    Returns:
        A Cell dataclass instance.

    Raises:
        CellPathTraversalError: If cell_id contains path traversal.
        CellNotFoundError: If no matching cell file is found.
        CellParseError: If the cell file is malformed.
    """
    cell_id = _sanitize_cell_id(cell_id)

    if cells_dir is None:
        # Walk up from CWD to find .aegis/rules/ or .soma/cells/
        cwd = os.getcwd()
        cand_aegis = os.path.join(cwd, '.aegis', 'rules')
        cand_soma_rules = os.path.join(cwd, '.soma', 'rules')
        cand_soma = os.path.join(cwd, '.soma', 'cells')
        if os.path.isdir(cand_aegis):
            cells_dir = cand_aegis
        elif os.path.isdir(cand_soma_rules):
            cells_dir = cand_soma_rules
        elif os.path.isdir(cand_soma):
            cells_dir = cand_soma
        else:
            raise CellNotFoundError(
                f"Cannot find .aegis/rules/ or .soma/cells/ from {cwd}"
            )

    # Fast-path: check standard cell and rule subdirectories directly before recursive walk
    target_fname = f"{cell_id}.md"
    found_path = None
    standard_subdirs = (
        "walls", "vacuoles", "membranes", "chloroplasts", "plasmodesmata",
        "invariants", "traps", "boundaries", "personas", "contracts",
        "ribosomes", "nuclei", ""
    )
    for subdir in standard_subdirs:
        candidate_file = os.path.join(cells_dir, subdir, target_fname) if subdir else os.path.join(cells_dir, target_fname)
        if os.path.isfile(candidate_file):
            found_path = candidate_file
            break

    # Fallback: Search for cell_id.md recursively in cells_dir
    if not found_path:
        for root, _dirs, files in os.walk(cells_dir):
            if target_fname in files:
                found_path = os.path.join(root, target_fname)
                break

    if found_path:
        filepath = found_path
        # Verify resolved path is within cells_dir
        real_path = os.path.realpath(filepath)
        real_cells = os.path.realpath(cells_dir)
        if not real_path.startswith(real_cells):
            raise CellPathTraversalError(
                f"Resolved path escapes cells dir: {filepath}"
            )
        frontmatter, _body = parse_cell_file(filepath)
        fitness_data = frontmatter.get('fitness', {})
        if isinstance(fitness_data, (int, float)):
            fitness_data = {'score': float(fitness_data)}
        elif not isinstance(fitness_data, dict):
            fitness_data = {}
        cell_inst = Cell(
            name=frontmatter.get('name', cell_id),
            type=frontmatter.get('type', 'vacuole'),
            hypothesis=frontmatter.get('hypothesis', ''),
            prediction=frontmatter.get('prediction', ''),
            falsification=frontmatter.get('falsification', ''),
            target_paths=frontmatter.get('target_paths', []),
            minimum_mode=frontmatter.get('minimum_mode', 'breeze'),
            tags=frontmatter.get('tags', []),
            fitness=CellFitness(
                triggers=fitness_data.get('triggers', 0),
                true_positives=fitness_data.get('true_positives', 0),
                false_positives=fitness_data.get('false_positives', 0),
                score=fitness_data.get('score'),
                stress_survived=fitness_data.get('stress_survived', 0),
            ),
            created_date=frontmatter.get('created_date') or frontmatter.get('created'),
        )
        if not cell_inst.created_date and os.path.exists(filepath):
            try:
                cell_inst.created_date = datetime.fromtimestamp(os.path.getctime(filepath), tz=timezone.utc)
            except Exception:
                pass
        return cell_inst

    raise CellNotFoundError(f"Cell not found: {cell_id}")


# Backward-compatible and canonical engineering aliases
Rule = Cell
RuleFitness = CellFitness
load_rule = load_cell
write_rule_frontmatter = write_cell_frontmatter
save_cell_file = write_cell_frontmatter
save_rule_file = write_cell_frontmatter
parse_rule_file = parse_cell_file


def dump_cell(frontmatter: dict, body: str = "") -> str:
    """Dump cell/rule dictionary and body to markdown with frontmatter."""
    from soma_core.somayaml import dump_frontmatter
    yaml_text = dump_frontmatter(frontmatter)
    content = f"---\n{yaml_text.strip()}\n---\n"
    if body:
        content += body
    return content


dump_rule = dump_cell

