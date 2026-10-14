"""Soma SDK — Adaptive governance for AI coding assistants."""
from soma_sdk.governance import Governance
from soma_sdk.cells import Cell, CellFitness, parse_cell_file
from soma_sdk.errors import CellNotFoundError, CellParseError, SomaError
from soma_core.scoring import wilson_lower_bound
from soma_core.lifecycle import bayesian_fitness

__version__ = '1.5.1'
__all__ = [
    'Governance',
    'Cell',
    'CellFitness',
    'SomaError',
    'CellNotFoundError',
    'CellParseError',
    'parse_cell_file',
    'wilson_lower_bound',
    'bayesian_fitness',
]
