"""aegis_sdk: the stable external facade over aegis_core (ADR 0005 D9).

External callers (citadel fleet telemetry, mapleterm) use Governance and
parse_rule_file; nothing inside Aegis imports this package.
"""
from aegis_core._version import __version__ as __version__
from aegis_core.yaml_engine.frontmatter import parse_rule_file
from aegis_sdk.governance import Governance

__all__ = ["Governance", "parse_rule_file"]
