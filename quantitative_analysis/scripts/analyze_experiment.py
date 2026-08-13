#!/usr/bin/env python3
"""Generate standard derived artifacts for one recorded agent experiment."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.experiment_analysis import (
    AnalysisProfile,
    analyze_experiment,
    extract_option,
    make_chat_template_tokenizer,
    write_analysis,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "experiment_dir", type=Path, help="Folder containing report.json and samples/"
    )
    parser.add_argument(
        "--output-dir", type=Path, help="Default: <experiment_dir>/analysis"
    )
    parser.add_argument(
        "--context-samples",
        type=int,
        default=6,
        help="Number of representative context trajectories to plot (default: 6)",
    )
    parser.add_argument(
        "--tokenizer-path",
        type=Path,
        help=(
            "Tokenizer used by the experiment. Enables theoretical token-prefix "
            "retention analysis; Transformers is imported only when supplied."
        ),
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=0,
        metavar="SAMPLES",
        help="Print elapsed time and ETA every N samples (default: disabled)",
    )
    parser.add_argument(
        "--terminal-tool",
        help="Optional tool name that marks a valid terminal answer transition",
    )
    parser.add_argument(
        "--parse-leading-option",
        action="store_true",
        help="Enable the generic explicit leading A-D answer diagnostic",
    )
    args = parser.parse_args()
    if args.context_samples < 0:
        parser.error("--context-samples must be non-negative")
    if args.progress_every < 0:
        parser.error("--progress-every must be non-negative")

    context_tokenizer = None
    tokenizer_name = None
    if args.tokenizer_path is not None:
        try:
            from transformers import AutoTokenizer
        except ImportError:
            parser.error(
                "--tokenizer-path requires transformers; run in the experiment environment"
            )
        tokenizer_path = args.tokenizer_path.expanduser().resolve()
        tokenizer = AutoTokenizer.from_pretrained(
            tokenizer_path, local_files_only=True, trust_remote_code=True
        )
        context_tokenizer = make_chat_template_tokenizer(tokenizer)
        tokenizer_name = str(tokenizer_path)

    started_at = time.monotonic()

    def report_progress(completed: int, total: int, sample_id: str) -> None:
        if not args.progress_every or (
            completed != total and completed % args.progress_every != 0
        ):
            return
        elapsed = time.monotonic() - started_at
        remaining = elapsed / completed * (total - completed) if completed else 0.0
        percent = 100 * completed / total if total else 100.0
        print(
            f"Progress: {completed}/{total} ({percent:.1f}%), "
            f"sample={sample_id}, elapsed={elapsed:.0f}s, ETA={remaining:.0f}s",
            flush=True,
        )

    profile = AnalysisProfile(
        terminal_tool=args.terminal_tool,
        answer_parser=extract_option if args.parse_leading_option else None,
        parsed_answer_label="explicit leading A-D answer",
    )
    analysis = analyze_experiment(
        args.experiment_dir,
        context_sample_limit=args.context_samples,
        profile=profile,
        context_tokenizer=context_tokenizer,
        context_tokenizer_name=tokenizer_name,
        progress_callback=report_progress,
    )
    output_dir = write_analysis(analysis, args.output_dir)
    print(
        f"Analyzed {len(analysis.samples)} samples and "
        f"{len(analysis.tool_calls)} tool calls"
    )
    print(f"Wrote {output_dir}")


if __name__ == "__main__":
    main()
