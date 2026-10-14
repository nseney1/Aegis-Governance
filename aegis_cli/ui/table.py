"""Width-aware ANSI Table, Grid, Box, and Error Panel classes for Aegis CLI."""
from __future__ import annotations

from dataclasses import dataclass
import shutil
from typing import Any, Iterable, Optional, Sequence, Union

from aegis_cli.ui.theme import OutputContext, strip_ansi

_SECTION_SENTINEL = object()


def visible_len(text: str) -> int:
    """Return the visible character length of text excluding ANSI escape codes."""
    return len(strip_ansi(str(text)))


def _align_visible(text: str, width: int, justify: str = "left") -> str:
    text_str = str(text)
    pad = max(width - visible_len(text_str), 0)
    if justify == "right":
        return (" " * pad) + text_str
    if justify == "center":
        left = pad // 2
        right = pad - left
        return (" " * left) + text_str + (" " * right)
    return text_str + (" " * pad)


def _truncate_visible(text: str, max_len: int) -> str:
    text_str = str(text)
    if max_len <= 0 or visible_len(text_str) <= max_len:
        return text_str
    plain = strip_ansi(text_str)
    if max_len <= 3:
        return plain[:max_len]
    return plain[: max_len - 1] + "…"


@dataclass(frozen=True)
class Column:
    """Declarative column specification for Table and Grid layouts."""

    header: str = ""
    justify: str = "left"
    style: Optional[str] = None
    no_wrap: bool = False
    min_width: int = 8


class Table:
    """ANSI-aware, terminal-width-adaptive tabular layout with alignment and section dividers."""

    def __init__(
        self,
        title: Optional[str] = None,
        ctx: Optional[OutputContext] = None,
        max_width: Optional[int] = None,
        show_header: bool = True,
    ) -> None:
        self.title = title
        self.ctx = ctx or OutputContext()
        self.max_width = max_width
        self.show_header = show_header
        self.columns: list[Column] = []
        self._rows: list[Union[list[str], object]] = []

    def add_column(
        self,
        header: str = "",
        justify: str = "left",
        style: Optional[str] = None,
        no_wrap: bool = False,
        min_width: int = 8,
    ) -> "Table":
        self.columns.append(
            Column(
                header=header,
                justify=justify,
                style=style,
                no_wrap=no_wrap,
                min_width=min_width,
            )
        )
        return self

    def add_row(self, *cells: Any) -> "Table":
        str_cells = [str(c) for c in cells]
        while len(self.columns) < len(str_cells):
            self.add_column()
        self._rows.append(str_cells)
        return self

    def add_section(self) -> "Table":
        """Insert a horizontal section divider between row groups."""
        self._rows.append(_SECTION_SENTINEL)
        return self

    def render(self, ctx: Optional[OutputContext] = None) -> str:
        ui = ctx or self.ctx
        col_count = len(self.columns)
        if col_count == 0:
            return ""

        term_width = self.max_width or shutil.get_terminal_size((100, 24)).columns
        widths = [visible_len(col.header) if self.show_header else 0 for col in self.columns]
        data_rows = [r for r in self._rows if isinstance(r, list)]

        for r in data_rows:
            for i in range(min(col_count, len(r))):
                widths[i] = max(widths[i], visible_len(r[i]))

        separator = "  " if (ui.plain or not ui.emoji_enabled) else " │ "
        sep_overhead = len(separator) * (col_count - 1)
        total_width = sum(widths) + sep_overhead

        if total_width > term_width:
            shrinkable = [i for i, col in enumerate(self.columns) if not col.no_wrap]
            if shrinkable:
                widest_idx = max(shrinkable, key=lambda idx: widths[idx])
                excess = total_width - term_width
                min_w = self.columns[widest_idx].min_width
                widths[widest_idx] = max(min_w, widths[widest_idx] - excess)


        lines: list[str] = []
        if self.title:
            lines.append(ui.style(self.title, "bold", "cyan"))

        rule_sep = (
            separator.join("-" * w for w in widths)
            if (ui.plain or not ui.emoji_enabled)
            else "─┼─".join("─" * w for w in widths)
        )

        if self.show_header:
            styled_headers = [
                _align_visible(
                    ui.style(_truncate_visible(col.header, widths[i]), "bold"),
                    widths[i],
                    justify=col.justify,
                )
                for i, col in enumerate(self.columns)
            ]
            lines.append(separator.join(styled_headers))
            lines.append(rule_sep)

        for entry in self._rows:
            if entry is _SECTION_SENTINEL:
                lines.append(rule_sep)
                continue
            assert isinstance(entry, list)
            rendered_cells: list[str] = []
            for i, col in enumerate(self.columns):
                raw_val = entry[i] if i < len(entry) else ""
                truncated = _truncate_visible(raw_val, widths[i])
                if col.style and "\x1b[" not in truncated:
                    truncated = ui.style(truncated, col.style)
                aligned = _align_visible(truncated, widths[i], justify=col.justify)
                rendered_cells.append(aligned)
            lines.append(separator.join(rendered_cells))

        return "\n".join(lines)


class Grid:
    """Borderless multi-column alignment grid for help screens, key-value summaries, and check lists."""

    def __init__(
        self,
        ctx: Optional[OutputContext] = None,
        padding: int = 2,
    ) -> None:
        self.ctx = ctx or OutputContext()
        self.padding = max(padding, 1)
        self.columns: list[Column] = []
        self._rows: list[list[str]] = []

    def add_column(
        self,
        justify: str = "left",
        style: Optional[str] = None,
    ) -> "Grid":
        self.columns.append(Column(justify=justify, style=style, no_wrap=True))
        return self

    def add_row(self, *cells: Any) -> "Grid":
        str_cells = [str(c) for c in cells]
        while len(self.columns) < len(str_cells):
            self.add_column()
        self._rows.append(str_cells)
        return self

    def render(self, ctx: Optional[OutputContext] = None) -> str:
        ui = ctx or self.ctx
        col_count = len(self.columns)
        if col_count == 0 or not self._rows:
            return ""

        widths = [0] * col_count
        for r in self._rows:
            for i in range(min(col_count, len(r))):
                widths[i] = max(widths[i], visible_len(r[i]))

        sep = " " * self.padding
        lines: list[str] = []
        for r in self._rows:
            parts: list[str] = []
            for i, col in enumerate(self.columns):
                val = r[i] if i < len(r) else ""
                if col.style and "\x1b[" not in val:
                    val = ui.style(val, col.style)
                if i == col_count - 1 and col.justify == "left":
                    parts.append(val)
                else:
                    parts.append(_align_visible(val, widths[i], justify=col.justify))
            lines.append(sep.join(parts).rstrip())
        return "\n".join(lines)


def render_table(
    headers: Sequence[str],
    rows: Iterable[Sequence[str]],
    ctx: Optional[OutputContext] = None,
    max_width: Optional[int] = None,
) -> str:
    """Convenience wrapper around Table for simple header + rows rendering."""
    tbl = Table(ctx=ctx, max_width=max_width)
    for h in headers:
        tbl.add_column(h)
    for r in rows:
        tbl.add_row(*r)
    return tbl.render()


def render_box(
    title: str,
    body_lines: Sequence[str],
    ctx: Optional[OutputContext] = None,
) -> str:
    """Render a summary header box in Unicode (TTY) or ASCII (--plain)."""
    ui = ctx or OutputContext()
    all_lines = [title, *body_lines]
    inner_width = max((visible_len(line) for line in all_lines), default=20) + 2

    if ui.plain or not ui.emoji_enabled:
        border = "+" + ("-" * (inner_width + 2)) + "+"
        out = [border, f"| {_align_visible(ui.style(title, 'bold'), inner_width)} |"]
        if body_lines:
            out.append("+" + ("-" * (inner_width + 2)) + "+")
            for b in body_lines:
                out.append(f"| {_align_visible(b, inner_width)} |")
        out.append(border)
        return "\n".join(out)

    top = "╭─" + ("─" * inner_width) + "─╮"
    mid = "├─" + ("─" * inner_width) + "─┤"
    bot = "╰─" + ("─" * inner_width) + "─╯"
    out = [top, f"│ {_align_visible(ui.style(title, 'bold', 'cyan'), inner_width)} │"]
    if body_lines:
        out.append(mid)
        for b in body_lines:
            out.append(f"│ {_align_visible(b, inner_width)} │")
    out.append(bot)
    return "\n".join(out)


def render_error_panel(
    message: str,
    fix: Optional[str] = None,
    ctx: Optional[OutputContext] = None,
) -> str:
    """Format an error banner with an optional actionable 'Fix:' remediation line."""
    ui = ctx or OutputContext()
    lines = [f"{ui.badge_fail()} {message}"]
    if fix:
        fix_label = ui.style("Fix:", "bold", "yellow")
        lines.append(f"  {fix_label} {fix}")
    return "\n".join(lines)
