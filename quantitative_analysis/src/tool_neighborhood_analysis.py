"""Reusable within-sample tool-neighborhood analysis from ``tool_calls.csv``."""

from __future__ import annotations

import csv
import html
import json
import math
import os
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


DEFAULT_COLORS = (
    "#2563eb", "#dc2626", "#16a34a", "#ea580c", "#7c3aed",
    "#0d9488", "#a16207", "#be185d", "#4b5563", "#0891b2",
)


@dataclass
class ToolNeighborhoodAnalysis:
    source_csv: Path
    target_tool: str
    events: list[dict[str, Any]]
    summary: dict[str, Any]


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(rows[0]) if rows else ["sample_id", "trajectory_index", "tool"]
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def load_tool_calls(path: str | Path) -> list[dict[str, Any]]:
    """Load only the three fields needed for within-sample sequence analysis."""
    path = Path(path)
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"sample_id", "trajectory_index", "tool"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path} is missing columns: {', '.join(sorted(missing))}")
        rows = []
        seen: set[tuple[str, int]] = set()
        for line_number, row in enumerate(reader, 2):
            try:
                index = int(row["trajectory_index"])
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"{path}:{line_number}: invalid trajectory_index"
                ) from exc
            key = (str(row["sample_id"]), index)
            if key in seen:
                raise ValueError(f"{path}:{line_number}: duplicate sample/index {key}")
            seen.add(key)
            rows.append({"sample_id": key[0], "trajectory_index": index,
                         "tool": str(row["tool"])})
    return rows


def _ranked(counter: Counter[str], total: int) -> list[dict[str, Any]]:
    return [
        {"label": label, "count": count, "rate": count / total if total else None}
        for label, count in counter.most_common()
    ]


def analyze_tool_neighborhoods(
    rows: Iterable[dict[str, Any]], target_tool: str = "deleteContext",
) -> ToolNeighborhoodAnalysis:
    """Analyze exact neighboring trajectory indices within each sample."""
    normalized = list(rows)
    source = Path("tool_calls.csv")
    by_sample: dict[str, dict[int, str]] = defaultdict(dict)
    for row in normalized:
        sample_id = str(row["sample_id"])
        index = int(row["trajectory_index"])
        if index in by_sample[sample_id]:
            raise ValueError(f"duplicate sample/index: {(sample_id, index)}")
        by_sample[sample_id][index] = str(row["tool"])

    events: list[dict[str, Any]] = []
    previous_1: Counter[str] = Counter()
    previous_2: Counter[str] = Counter()
    next_1: Counter[str] = Counter()
    target_run_lengths: list[int] = []
    run_predecessors: Counter[str] = Counter()
    run_successors: Counter[str] = Counter()
    for sample_id in sorted(by_sample):
        indexed = by_sample[sample_id]
        target_indices = sorted(
            index for index, tool in indexed.items() if tool == target_tool
        )
        prior_target_index: int | None = None
        current_run_length = 0
        for ordinal, index in enumerate(target_indices, 1):
            prev1 = indexed.get(index - 1, "missing_t-1")
            prev2 = indexed.get(index - 2, "missing_t-2")
            following = indexed.get(index + 1, "missing_t+1")
            pair = f"{prev2} -> {prev1}"
            previous_1[prev1] += 1
            previous_2[pair] += 1
            next_1[following] += 1
            if prior_target_index is not None and index == prior_target_index + 1:
                current_run_length += 1
            else:
                if current_run_length:
                    target_run_lengths.append(current_run_length)
                current_run_length = 1
            events.append({
                "sample_id": sample_id,
                "trajectory_index": index,
                "tool": target_tool,
                "previous_tool_2": prev2,
                "previous_tool_1": prev1,
                "previous_pair": pair,
                "next_tool_1": following,
                "deletion_ordinal_in_sample": ordinal,
                "intervening_calls_since_previous_deletion": (
                    index - prior_target_index - 1
                    if prior_target_index is not None else None
                ),
            })
            prior_target_index = index
        if current_run_length:
            target_run_lengths.append(current_run_length)
        for run_start in (
            index for index in target_indices
            if indexed.get(index - 1) != target_tool
        ):
            run_end = run_start
            while indexed.get(run_end + 1) == target_tool:
                run_end += 1
            run_predecessors[indexed.get(run_start - 1, "missing_t-1")] += 1
            run_successors[indexed.get(run_end + 1, "missing_t+1")] += 1

    total = len(events)
    samples_with_target = len({event["sample_id"] for event in events})
    per_sample = Counter(event["sample_id"] for event in events)
    summary = {
        "target_tool": target_tool,
        "source_row_count": len(normalized),
        "sample_count": len(by_sample),
        "target_call_count": total,
        "samples_with_target": samples_with_target,
        "samples_with_target_rate": samples_with_target / len(by_sample) if by_sample else None,
        "target_calls_per_using_sample": total / samples_with_target if samples_with_target else None,
        "target_calls_per_sample_distribution": _numeric_summary(per_sample.values()),
        "intervening_calls_since_previous_target_distribution": _numeric_summary(
            event["intervening_calls_since_previous_deletion"] for event in events
        ),
        "target_run_count": len(target_run_lengths),
        "multi_call_target_run_count": sum(length > 1 for length in target_run_lengths),
        "calls_in_multi_call_target_runs": sum(
            length for length in target_run_lengths if length > 1
        ),
        "calls_in_multi_call_target_runs_rate": (
            sum(length for length in target_run_lengths if length > 1) / total
            if total else None
        ),
        "target_run_length_distribution": _numeric_summary(target_run_lengths),
        "target_run_predecessor": _ranked(run_predecessors, len(target_run_lengths)),
        "target_run_successor": _ranked(run_successors, len(target_run_lengths)),
        "previous_tool_1": _ranked(previous_1, total),
        "previous_tool_2_pattern": _ranked(previous_2, total),
        "next_tool_1": _ranked(next_1, total),
        "exact_adjacency_definition": (
            "Neighbors must have the same sample_id and exact trajectory indices "
            "t-1, t-2, or t+1; missing indices are labelled explicitly."
        ),
    }
    return ToolNeighborhoodAnalysis(source, target_tool, events, summary)


def _numeric_summary(values: Iterable[int | None]) -> dict[str, float | int | None]:
    clean = sorted(value for value in values if value is not None)
    if not clean:
        return {"count": 0, "mean": None, "median": None, "max": None}
    middle = len(clean) // 2
    median = (
        clean[middle] if len(clean) % 2
        else (clean[middle - 1] + clean[middle]) / 2
    )
    return {"count": len(clean), "mean": sum(clean) / len(clean),
            "median": median, "max": max(clean)}


def _pie_slices(rows: list[dict[str, Any]], max_slices: int) -> list[tuple[str, int]]:
    ranked = [(str(row["label"]), int(row["count"])) for row in rows]
    if len(ranked) <= max_slices:
        return ranked
    kept = ranked[:max_slices - 1]
    kept.append(("other", sum(count for _, count in ranked[max_slices - 1:])))
    return kept


def render_pie_svg(
    title: str, rows: list[dict[str, Any]], *, max_slices: int = 9,
) -> str:
    """Render a dependency-free SVG pie with a complete count legend."""
    slices = _pie_slices(rows, max_slices)
    total = sum(count for _, count in slices)
    width, height = 920, max(430, 150 + 34 * len(slices))
    cx, cy, radius = 220, height / 2 + 15, 150
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="32" y="45" font-family="sans-serif" font-size="22" fill="#111827">{html.escape(title)}</text>',
    ]
    if not slices:
        parts.append(
            '<text x="32" y="100" font-family="sans-serif" font-size="17" '
            'fill="#4b5563">No matching tool calls.</text>'
        )
    angle = -math.pi / 2
    for index, (label, count) in enumerate(slices):
        fraction = count / total if total else 0
        next_angle = angle + 2 * math.pi * fraction
        x1, y1 = cx + radius * math.cos(angle), cy + radius * math.sin(angle)
        x2, y2 = cx + radius * math.cos(next_angle), cy + radius * math.sin(next_angle)
        large = 1 if fraction > 0.5 else 0
        color = DEFAULT_COLORS[index % len(DEFAULT_COLORS)]
        if fraction >= 0.999999:
            parts.append(f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="{color}"/>')
        else:
            path = f"M {cx} {cy} L {x1:.2f} {y1:.2f} A {radius} {radius} 0 {large} 1 {x2:.2f} {y2:.2f} Z"
            parts.append(f'<path d="{path}" fill="{color}" stroke="#ffffff" stroke-width="2"><title>{html.escape(label)}: {count} ({100*fraction:.1f}%)</title></path>')
        legend_y = 90 + index * 34
        parts.extend([
            f'<rect x="440" y="{legend_y - 15}" width="18" height="18" fill="{color}"/>',
            f'<text x="470" y="{legend_y}" font-family="sans-serif" font-size="15" fill="#111827">{html.escape(label)}: {count} ({100*fraction:.1f}%)</text>',
        ])
        angle = next_angle
    parts.append('</svg>')
    return "\n".join(parts)


def write_tool_neighborhood_analysis(
    analysis: ToolNeighborhoodAnalysis, output_dir: str | Path,
) -> Path:
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = dict(analysis.summary)
    summary["source_csv"] = str(analysis.source_csv)
    _atomic_write(output_dir / "summary.json", json.dumps(summary, indent=2, sort_keys=True) + "\n")
    _atomic_csv(output_dir / "events.csv", analysis.events)
    _atomic_write(
        output_dir / "previous_tool_1.svg",
        render_pie_svg(f"Tool immediately before {analysis.target_tool}", summary["previous_tool_1"]),
    )
    _atomic_write(
        output_dir / "previous_tool_2_pattern.svg",
        render_pie_svg(f"Two-tool pattern before {analysis.target_tool}", summary["previous_tool_2_pattern"]),
    )
    _atomic_write(output_dir / "report.md", markdown_report(summary))
    return output_dir


def markdown_report(summary: dict[str, Any]) -> str:
    def pct(value: Any) -> str:
        return "NA" if value is None else f"{100 * value:.1f}%"

    def number(value: Any) -> str:
        return "NA" if value is None else f"{value:.2f}"

    lines = [
        f"# Tool Neighborhood Analysis: {summary['target_tool']}", "",
        f"Source: `{summary['source_csv']}`.", "",
        summary["exact_adjacency_definition"], "",
        "| Measure | Value |", "|---|---:|",
        f"| Samples | {summary['sample_count']} |",
        f"| Target calls | {summary['target_call_count']} |",
        f"| Samples invoking target | {summary['samples_with_target']} |",
        f"| Sample coverage | {pct(summary['samples_with_target_rate'])} |",
        f"| Calls per using sample | {summary['target_calls_per_using_sample'] or 0:.2f} |", "",
        "## Immediate predecessor", "",
        "![Immediate predecessor](previous_tool_1.svg)", "",
        "| Tool | Calls | Rate |", "|---|---:|---:|",
    ]
    for row in summary["previous_tool_1"]:
        lines.append(f"| {row['label']} | {row['count']} | {pct(row['rate'])} |")
    lines.extend([
        "", "## Two-tool predecessor pattern", "",
        "Each row is an overlapping `(t-2, t-1)` window ending immediately "
        "before one target call.", "",
        "![Two-tool predecessor pattern](previous_tool_2_pattern.svg)", "",
        "| Pattern | Calls | Rate |", "|---|---:|---:|",
    ])
    for row in summary["previous_tool_2_pattern"][:20]:
        lines.append(f"| {row['label']} | {row['count']} | {pct(row['rate'])} |")
    lines.extend(["", "## Following tool", "", "| Tool | Calls | Rate |", "|---|---:|---:|"])
    for row in summary["next_tool_1"]:
        lines.append(f"| {row['label']} | {row['count']} | {pct(row['rate'])} |")
    spacing = summary["intervening_calls_since_previous_target_distribution"]
    runs = summary["target_run_length_distribution"]
    lines.extend([
        "", "## Repetition", "",
        f"Consecutive `{summary['target_tool']}` runs: {summary['target_run_count']} "
        f"total, {summary['multi_call_target_run_count']} containing multiple calls. "
        f"{pct(summary['calls_in_multi_call_target_runs_rate'])} of target calls belong "
        f"to multi-call runs. Run length: mean {number(runs['mean'])}, "
        f"median {runs['median'] if runs['median'] is not None else 'NA'}, "
        f"maximum {runs['max'] if runs['max'] is not None else 'NA'}.", "",
        f"Intervening calls between `{summary['target_tool']}` invocations within a sample: "
        f"mean {number(spacing['mean'])}, "
        f"median {spacing['median'] if spacing['median'] is not None else 'NA'}, "
        f"maximum {spacing['max'] if spacing['max'] is not None else 'NA'}.", "",
        "### Run boundaries", "",
        "| Tool before run | Runs | Rate |", "|---|---:|---:|",
    ])
    for row in summary["target_run_predecessor"]:
        lines.append(f"| {row['label']} | {row['count']} | {pct(row['rate'])} |")
    lines.extend(["", "| Tool after run | Runs | Rate |", "|---|---:|---:|"])
    for row in summary["target_run_successor"]:
        lines.append(f"| {row['label']} | {row['count']} | {pct(row['rate'])} |")
    lines.extend(["", "`events.csv` contains one row per target invocation for custom analysis."])
    return "\n".join(lines)
