#!/usr/bin/env python3
"""Analyze neighboring tools from one generated tool_calls.csv."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.tool_neighborhood_analysis import (
    analyze_tool_neighborhoods,
    load_tool_calls,
    write_tool_neighborhood_analysis,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tool_calls_csv", type=Path)
    parser.add_argument("--target-tool", default="deleteContext")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    source = args.tool_calls_csv.resolve()
    rows = load_tool_calls(source)
    analysis = analyze_tool_neighborhoods(rows, args.target_tool)
    analysis.source_csv = source
    output_dir = args.output_dir or source.parent / "tool_neighborhoods" / args.target_tool
    written = write_tool_neighborhood_analysis(analysis, output_dir)
    print(
        f"Analyzed {analysis.summary['target_call_count']} {args.target_tool} calls; "
        f"wrote {written}"
    )


if __name__ == "__main__":
    main()
