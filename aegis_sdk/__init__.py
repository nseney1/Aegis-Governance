"""Soma SDK — Adaptive governance for AI coding assistants."""
from aegis_sdk.governance import Governance
from aegis_sdk.cells import Cell, CellFitness, parse_cell_file, Rule, RuleFitness, parse_rule_file
from aegis_sdk.errors import CellNotFoundError, CellParseError, SomaError, RuleNotFoundError, RuleParseError, AegisError
from aegis_core.scoring import wilson_lower_bound
from aegis_core.lifecycle import bayesian_fitness

__version__ = '2.1.0'
__all__ = [
    'Governance',
    'Cell',
    'CellFitness',
    'Rule',
    'RuleFitness',
    'SomaError',
    'AegisError',
    'CellNotFoundError',
    'RuleNotFoundError',
    'CellParseError',
    'RuleParseError',
    'parse_cell_file',
    'parse_rule_file',
    'wilson_lower_bound',
    'bayesian_fitness',
]
