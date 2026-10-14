"""Zero-dependency UI rendering package for Aegis CLI."""
from __future__ import annotations

from aegis_cli.ui.table import (
    Column,
    Grid,
    Table,
    render_box,
    render_error_panel,
    render_table,
    visible_len,
)
from aegis_cli.ui.theme import (
    ANSI_ESCAPE_RE,
    OutputContext,
    strip_ansi,
)

__all__ = [
    "ANSI_ESCAPE_RE",
    "Column",
    "Grid",
    "OutputContext",
    "Table",
    "render_box",
    "render_error_panel",
    "render_table",
    "strip_ansi",
    "visible_len",
]
