"""Analysis utilities for governance metrics."""
import math
from typing import Dict


def shannon_diversity(type_counts: Dict[str, int]) -> dict:
    """Calculate Shannon entropy and evenness for cell type distribution."""
    total = sum(type_counts.values())
    if total == 0 or len(type_counts) <= 1:
        return {'entropy': 0.0, 'evenness': 0.0, 'assessment': 'monoculture'}
    
    entropy = -sum((n/total) * math.log(n/total) for n in type_counts.values() if n > 0)
    max_entropy = math.log(len(type_counts))
    evenness = entropy / max_entropy if max_entropy > 0 else 0
    
    if evenness > 0.8:
        assessment = 'healthy'
    elif evenness > 0.6:
        assessment = 'acceptable'
    elif evenness > 0.4:
        assessment = 'imbalanced'
    else:
        assessment = 'monoculture'
    
    return {'entropy': round(entropy, 4), 'evenness': round(evenness, 4), 'assessment': assessment}


def letter_grade(pct: float) -> str:
    """Convert percentage to letter grade."""
    if pct >= 97: return 'A+'
    if pct >= 93: return 'A'
    if pct >= 90: return 'A-'
    if pct >= 87: return 'B+'
    if pct >= 83: return 'B'
    if pct >= 80: return 'B-'
    if pct >= 77: return 'C+'
    if pct >= 73: return 'C'
    if pct >= 70: return 'C-'
    if pct >= 67: return 'D+'
    if pct >= 60: return 'D'
    return 'F'


def specificity_penalty(trigger_rate: float) -> float:
    """Anti-Goodhart penalty for overly broad cells."""
    if trigger_rate > 0.8:
        return 1.0 - min(trigger_rate, 1.0)
    return 1.0


def antifragile_bonus(stress_survived: int, cap: int = 10) -> float:
    """Cells gain +5% per survived high-intensity review."""
    return 1.0 + (0.05 * min(stress_survived, cap))
