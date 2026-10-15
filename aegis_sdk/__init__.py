"""Aegis SDK — Adaptive governance for AI coding assistants."""
from aegis_sdk.governance import Governance
from aegis_sdk.rules import Rule, RuleFitness, parse_rule_file
from aegis_sdk.errors import RuleNotFoundError, RuleParseError, AegisError
from aegis_core.scoring import wilson_lower_bound
from aegis_core.lifecycle import bayesian_fitness

__version__ = '3.3.0'
__all__ = [
    'Governance',
    'Rule',
    'RuleFitness',
    'AegisError',
    'RuleNotFoundError',
    'RuleParseError',
    'parse_rule_file',
    'wilson_lower_bound',
    'bayesian_fitness',
]
