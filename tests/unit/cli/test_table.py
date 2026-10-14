"""Behavioral tests for aegis_cli.ui.table (Table, Grid, Column, box, and error panel rendering)."""
from __future__ import annotations

import argparse

from aegis_cli.ui.table import (
    Column,
    Grid,
    Table,
    render_box,
    render_error_panel,
    render_table,
    visible_len,
)
from aegis_cli.ui.theme import OutputContext, strip_ansi


def _ctx(plain: bool = False, isatty: bool = True) -> OutputContext:
    ns = argparse.Namespace(
        plain=plain,
        no_emoji=plain,
        format="text",
        json=False,
        quiet=False,
        verbose=False,
    )
    return OutputContext.from_env_and_args(ns, environ={}, isatty=isatty)


def test_visible_len_ignores_ansi_escape_sequences():
    ctx = _ctx(plain=False, isatty=True)
    colored = ctx.style("invariant-rule", "bold", "magenta")
    assert "\x1b[" in colored
    assert visible_len(colored) == len("invariant-rule")


def test_table_class_supports_column_alignment_styles_sections_and_no_wrap():
    ctx = _ctx(plain=False, isatty=True)
    long_id = "invariant-very-long-rule-identifier-exceeding-36-chars"

    table = Table(title="Active Governance Rules", ctx=ctx, max_width=95)
    table.add_column("Rule ID", style="bold", no_wrap=True)
    table.add_column("Type", justify="center")
    table.add_column("Fitness", justify="right")
    table.add_column("Description")

    table.add_row(
        long_id,
        ctx.color_rule_type("invariant"),
        ctx.color_fitness(0.95),
        "A very long description that should be truncated before a no_wrap Rule ID column is touched",
    )
    table.add_section()
    table.add_row(
        "trap-short",
        ctx.color_rule_type("trap"),
        ctx.color_fitness(0.42),
        "Short trap rule",
    )

    out = table.render()
    plain_lines = [strip_ansi(line) for line in out.splitlines() if line.strip()]

    # Title is rendered
    assert "Active Governance Rules" in plain_lines[0]
    # no_wrap column (long_id) is preserved intact while Description truncates to fit max_width=95
    assert any(long_id in line for line in plain_lines)
    # Right-aligned Fitness column pads leading spaces before "0.95"
    data_line = next(line for line in plain_lines if "trap-short" in line)
    assert "   0.42" in data_line


def test_grid_class_renders_borderless_aligned_columns_for_help_and_summaries():
    ctx = _ctx(plain=False, isatty=True)
    grid = Grid(ctx=ctx, padding=3)
    grid.add_column(style="bold")
    grid.add_column()
    grid.add_row("status", "Show active rules and governance health")
    grid.add_row("doctor", "Run workspace & environment diagnostics")

    out = grid.render()
    plain_lines = [strip_ansi(line) for line in out.splitlines()]
    assert len(plain_lines) == 2
    assert plain_lines[0] == "status   Show active rules and governance health"
    assert plain_lines[1] == "doctor   Run workspace & environment diagnostics"
    assert "│" not in out


def test_render_table_plain_mode_emits_zero_ansi_and_ascii_separators():
    ctx = _ctx(plain=True, isatty=False)
    headers = ["Check", "Status", "Detail"]
    rows = [
        ["workspace", ctx.badge_pass(), ".aegis/rules active"],
        ["drivers", ctx.badge_warn(), "1 optional driver missing"],
    ]
    out = render_table(headers, rows, ctx=ctx)
    assert "\x1b[" not in out
    assert "[PASS]" in out
    assert "[WARN]" in out
    assert "╭" not in out


def test_render_box_and_error_panel_include_remediation_fix():
    tty_ctx = _ctx(plain=False, isatty=True)
    box = render_box("Aegis Workspace Status", ["Grade: A", "Rules: 18 active"], ctx=tty_ctx)
    assert "Aegis Workspace Status" in strip_ansi(box)
    assert "╭" in box

    plain_ctx = _ctx(plain=True, isatty=False)
    err = render_error_panel(
        "Workspace not initialized",
        fix="Run 'aegis init' to initialize .aegis/rules/",
        ctx=plain_ctx,
    )
    assert "\x1b[" not in err
    assert "[FAIL] Workspace not initialized" in err
    assert "Fix: Run 'aegis init' to initialize .aegis/rules/" in err
