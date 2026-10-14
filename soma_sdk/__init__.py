"""Soma SDK — Adaptive governance for AI coding assistants."""
from soma_sdk.governance import Governance
from soma_sdk.cells import Cell, CellFitness, parse_cell_file, Rule, RuleFitness, parse_rule_file
from soma_sdk.errors import CellNotFoundError, CellParseError, SomaError, RuleNotFoundError, RuleParseError, AegisError
from soma_core.scoring import wilson_lower_bound
from soma_core.lifecycle import bayesian_fitness

__version__ = '1.5.1'
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
