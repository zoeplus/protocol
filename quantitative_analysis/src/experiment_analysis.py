"""Reusable quantitative analysis for recorder-contract agent experiments."""

from __future__ import annotations

import csv
import html
import json
import math
import os
import re
import statistics
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable


__all__ = [
    "AnalysisProfile",
    "ExperimentAnalysis",
    "analyze_experiment",
    "assign_tool_colors",
    "cache_retention_by_action",
    "distribution",
    "extract_explicit_option",
    "extract_option",
    "common_prefix_length",
    "make_chat_template_tokenizer",
    "markdown_report",
    "render_context_evolution_svg",
    "select_context_samples",
    "wilson",
    "write_analysis",
]


TRAJECTORY_RE = re.compile(r"trajectory_(\d+)\.json$")
OPTION_RE = re.compile(r"^\s*(?:answer\s*[:=-]?\s*)?\(?([A-D])\)?(?:[.\s:]|$)", re.I)
REQUESTED_TOKENS_RE = re.compile(r"requested\s+(\d+)\s+tokens", re.I)
REQUEST_TOKEN_BREAKDOWN_RE = re.compile(
    r"requested\s+(\d+)\s+tokens\s+\((\d+)\s+in the messages,\s*"
    r"(\d+)\s+in the completion\)",
    re.I,
)
TOOL_MARKUP_RE = re.compile(r"</?tool_call>|<function=", re.I)
DEFAULT_COLOR_PALETTE = (
    "#2563eb", "#dc2626", "#ea580c", "#16a34a", "#7c3aed", "#0d9488",
    "#a16207", "#be185d", "#111827", "#6b7280", "#0891b2", "#65a30d",
)


@dataclass
class ExperimentAnalysis:
    """Normalized in-memory result returned by :func:`analyze_experiment`."""

    experiment_dir: Path
    summary: dict[str, Any]
    samples: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    context_calls: list[dict[str, Any]]
    cache_transitions: list[dict[str, Any]]
    context_selection: list[dict[str, Any]]
    tool_colors: dict[str, str]


@dataclass(frozen=True)
class AnalysisProfile:
    """Optional conventions layered on top of the common artifact contract."""

    terminal_tool: str | None = None
    answer_parser: Callable[[Any], str | None] | None = None
    parsed_answer_label: str = "parsed answer"


ContextTokenizer = Callable[[list[dict[str, Any]], Any, bool], list[int]]
ProgressCallback = Callable[[int, int, str], None]


def common_prefix_length(left: list[int], right: list[int]) -> int:
    """Return the token length of the longest common prefix."""
    for index, (left_token, right_token) in enumerate(zip(left, right)):
        if left_token != right_token:
            return index
    return min(len(left), len(right))


def make_chat_template_tokenizer(tokenizer: Any) -> ContextTokenizer:
    """Adapt a tokenizer with ``apply_chat_template`` to the analysis API."""
    def tokenize(
        messages: list[dict[str, Any]], tools: Any, add_generation_prompt: bool,
    ) -> list[int]:
        rendered = tokenizer.apply_chat_template(
            messages,
            tools=tools,
            tokenize=True,
            add_generation_prompt=add_generation_prompt,
        )
        if isinstance(rendered, dict) or hasattr(rendered, "keys"):
            rendered = rendered["input_ids"]
        if rendered and isinstance(rendered[0], list):
            if len(rendered) != 1:
                raise ValueError("chat template returned more than one token sequence")
            rendered = rendered[0]
        return [int(token) for token in rendered]

    return tokenize


def assign_tool_colors(
    tool_names: Iterable[str], overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    """Assign stable colors without requiring knowledge of a tool inventory."""
    names = set(tool_names)
    colors = {
        tool: color for tool, color in (overrides or {}).items() if tool in names
    }
    unassigned = sorted(names - colors.keys())
    for index, tool in enumerate(unassigned):
        colors[tool] = DEFAULT_COLOR_PALETTE[index % len(DEFAULT_COLOR_PALETTE)]
    return colors


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def atomic_write(path: Path, content: str) -> None:
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


def atomic_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def distribution(values: Iterable[float | int | None]) -> dict[str, float | int | None]:
    clean = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    if not clean:
        return {"count": 0, "mean": None, "std": None, "min": None, "p25": None,
                "median": None, "p75": None, "p90": None, "p95": None, "max": None}
    return {
        "count": len(clean),
        "mean": statistics.fmean(clean),
        "std": statistics.stdev(clean) if len(clean) > 1 else 0.0,
        "min": min(clean),
        "p25": percentile(clean, 0.25),
        "median": percentile(clean, 0.50),
        "p75": percentile(clean, 0.75),
        "p90": percentile(clean, 0.90),
        "p95": percentile(clean, 0.95),
        "max": max(clean),
    }


def cache_retention_by_action(
    transitions: Iterable[dict[str, Any]], *, action_field: str = "tool",
) -> list[dict[str, Any]]:
    """Aggregate eligible theoretical KV-prefix transitions by action label."""
    eligible = [
        transition for transition in transitions
        if transition.get("next_call_observed")
        and transition.get("retained_ratio") is not None
    ]
    summaries = []
    for action in sorted({str(row.get(action_field) or "no_action") for row in eligible}):
        rows = [
            row for row in eligible
            if str(row.get(action_field) or "no_action") == action
        ]
        previous_tokens = sum(int(row["previous_token_count"]) for row in rows)
        common_prefix_tokens = sum(
            int(row["common_prefix_token_count"]) for row in rows
        )
        summaries.append({
            "action": action,
            "transition_count": len(rows),
            "previous_token_count": previous_tokens,
            "common_prefix_token_count": common_prefix_tokens,
            "weighted_retention_rate": (
                common_prefix_tokens / previous_tokens if previous_tokens else None
            ),
            "per_transition_retention": distribution(
                row["retained_ratio"] for row in rows
            ),
            "invalidated_previous_token_count": sum(
                int(row["invalidated_previous_token_count"]) for row in rows
            ),
        })
    return summaries


def wilson(successes: int, total: int, z: float = 1.959963984540054) -> list[float] | None:
    if total == 0:
        return None
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    radius = z * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total)) / denominator
    return [max(0.0, center - radius), min(1.0, center + radius)]


def iso_seconds(start: Any, end: Any) -> float | None:
    if not isinstance(start, str) or not isinstance(end, str):
        return None
    try:
        return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
    except ValueError:
        return None


def classify_error(error: Any) -> str:
    if not error:
        return "none"
    text = str(error).lower()
    if "maximum context length" in text or "context length" in text and "tokens" in text:
        return "context_limit"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if "rate limit" in text or "ratelimit" in text:
        return "rate_limit"
    if "connection" in text:
        return "connection"
    return "other"


def extract_option(answer: Any) -> str | None:
    if not isinstance(answer, str):
        return None
    match = OPTION_RE.search(answer)
    return match.group(1).upper() if match else None


def extract_explicit_option(answer: Any) -> str | None:
    """Extract a leading or explicitly labelled A-D answer, preferring the last."""
    if not isinstance(answer, str):
        return None
    patterns = (
        re.compile(
            r"(?:the\s+)?(?:final|correct|best)\s+answer\s+(?:is\s*)?"
            r"[:\-]?\s*(?:\*\*)?(?:\\boxed\{)?\(?([A-D])\b",
            re.I,
        ),
        re.compile(
            r"\banswer\s+is\s*[:\-]?\s*(?:\*\*)?(?:\\boxed\{)?"
            r"\(?([A-D])\b",
            re.I,
        ),
        re.compile(
            r"^\s*(?:final\s+answer\s*[:\-]?\s*)?(?:\*\*)?"
            r"(?:\\boxed\{)?\(?([A-D])\)?(?:[.\s:*}]|$)",
            re.I | re.M,
        ),
    )
    matches = [
        (match.start(), match.group(1).upper())
        for pattern in patterns
        for match in pattern.finditer(answer)
    ]
    return max(matches)[1] if matches else None


def request_token_breakdown(error: Any) -> dict[str, int] | None:
    """Parse common OpenAI-compatible context-limit error token counts."""
    if not error:
        return None
    match = REQUEST_TOKEN_BREAKDOWN_RE.search(str(error))
    if not match:
        return None
    return {
        "requested_tokens": int(match.group(1)),
        "message_tokens": int(match.group(2)),
        "completion_tokens": int(match.group(3)),
    }


def observation_succeeded(observation: Any, trajectory_error: Any = None) -> bool:
    if trajectory_error:
        return False
    if not isinstance(observation, dict):
        return True
    status = str(observation.get("status", "")).lower()
    return "error" not in observation and status not in {"error", "failed", "failure"}


def json_scalar(value: Any) -> Any:
    return value if value is None or isinstance(value, (str, int, float, bool)) else json.dumps(value, ensure_ascii=True, sort_keys=True)


def analyze_sample(
    sample_dir: Path,
    profile: AnalysisProfile | None = None,
    context_tokenizer: ContextTokenizer | None = None,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[str],
]:
    profile = profile or AnalysisProfile()
    warnings: list[str] = []
    result_path = sample_dir / "result.json"
    result: dict[str, Any] = {}
    if result_path.exists():
        try:
            result = load_json(result_path)
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(f"{sample_dir.name}/result.json: {exc}")

    trajectory_paths: list[tuple[int, Path]] = []
    for path in sample_dir.glob("trajectory_*.json"):
        match = TRAJECTORY_RE.match(path.name)
        if match:
            trajectory_paths.append((int(match.group(1)), path))
    trajectory_paths.sort()

    expected = list(range(len(trajectory_paths)))
    observed = [index for index, _ in trajectory_paths]
    contiguous = observed == expected
    actions: Counter[str] = Counter()
    action_success: Counter[str] = Counter()
    action_failure: Counter[str] = Counter()
    prompt_tokens: list[int] = []
    completion_tokens: list[int] = []
    total_tokens: list[int] = []
    call_latency: list[float] = []
    action_records: list[dict[str, Any]] = []
    context_records: list[dict[str, Any]] = []
    cache_records: list[dict[str, Any]] = []
    deleted_ids: set[Any] = set()
    note_keys: set[str] = set()
    trajectory_errors = 0
    statuses: Counter[str] = Counter()
    previous_resulting_context: Any = None
    adjacent_checks = 0
    adjacent_mismatches = 0
    seen_action_signatures: dict[str, set[str]] = defaultdict(set)
    last_action_name: str | None = None

    loaded_trajectories: dict[int, dict[str, Any]] = {}
    for index, path in trajectory_paths:
        try:
            loaded_trajectories[index] = load_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(f"{sample_dir.name}/{path.name}: {exc}")

    for position, (index, path) in enumerate(trajectory_paths):
        trajectory = loaded_trajectories.get(index)
        if trajectory is None:
            continue
        statuses[str(trajectory.get("status", "missing"))] += 1
        if trajectory.get("error"):
            trajectory_errors += 1
        if previous_resulting_context is not None and "initial_context" in trajectory:
            adjacent_checks += 1
            if previous_resulting_context != trajectory.get("initial_context"):
                adjacent_mismatches += 1
        previous_resulting_context = trajectory.get("resulting_context")

        usage = (trajectory.get("response") or {}).get("usage") or {}
        prompt = usage.get("prompt_tokens")
        completion = usage.get("completion_tokens")
        total = usage.get("total_tokens")
        if isinstance(prompt, (int, float)):
            prompt_tokens.append(int(prompt))
        if isinstance(completion, (int, float)):
            completion_tokens.append(int(completion))
        if isinstance(total, (int, float)):
            total_tokens.append(int(total))
        latency = iso_seconds(trajectory.get("started_at"), trajectory.get("completed_at"))
        if latency is not None and latency >= 0:
            call_latency.append(latency)

        action = trajectory.get("action") or {}
        name = action.get("name")
        rejected = request_token_breakdown(trajectory.get("error"))
        chart_prompt_tokens = (
            int(prompt) if isinstance(prompt, (int, float))
            else rejected["message_tokens"] if rejected else None
        )
        context_records.append({
            "sample_id": str(result.get("sample_id", sample_dir.name)),
            "trajectory_index": index,
            "prompt_tokens": chart_prompt_tokens,
            "completion_tokens": int(completion) if isinstance(completion, (int, float)) else None,
            "tool": str(name) if name else "no_tool",
            "preceding_tool": last_action_name,
            "is_rejected_request": rejected is not None,
            "trajectory_status": trajectory.get("status"),
            "has_error": bool(trajectory.get("error")),
        })

        if context_tokenizer is not None:
            initial = trajectory.get("initial_context")
            resulting = trajectory.get("resulting_context")
            next_index = (
                trajectory_paths[position + 1][0]
                if position + 1 < len(trajectory_paths) else None
            )
            next_trajectory = (
                loaded_trajectories.get(next_index)
                if next_index == index + 1 else None
            )
            next_call_observed = next_trajectory is not None
            transition_scope = (
                "observed_adjacent_call" if next_call_observed
                else "terminal_snapshot" if next_index is None
                else "missing_adjacent_trajectory"
            )
            next_context = (
                next_trajectory.get("initial_context")
                if next_call_observed else resulting
            )
            cache_record = {
                "sample_id": str(result.get("sample_id", sample_dir.name)),
                "trajectory_index": index,
                "next_trajectory_index": (
                    next_index if next_call_observed else None
                ),
                "next_call_observed": next_call_observed,
                "transition_scope": transition_scope,
                "recorded_contexts_match": (
                    resulting == next_trajectory.get("initial_context")
                    if next_call_observed else None
                ),
                "tool": str(name) if name else "no_tool",
                "previous_token_count": None,
                "next_prompt_token_count": None,
                "common_prefix_token_count": None,
                "retained_ratio": None,
                "invalidated_previous_token_count": None,
                "reported_previous_total_tokens": total,
                "previous_vs_reported_total_delta": None,
                "reported_next_prompt_tokens": None,
                "next_prompt_vs_reported_delta": None,
                "error": None,
            }
            try:
                if not isinstance(initial, dict) or not isinstance(next_context, dict):
                    raise ValueError("missing initial or resulting context")
                initial_messages = initial.get("messages")
                if not isinstance(initial_messages, list):
                    raise ValueError("initial context has no message list")
                assistant_message = None
                resulting_messages = resulting.get("messages") if isinstance(resulting, dict) else None
                if (
                    isinstance(resulting_messages, list)
                    and len(resulting_messages) > len(initial_messages)
                    and isinstance(resulting_messages[len(initial_messages)], dict)
                    and resulting_messages[len(initial_messages)].get("role") == "assistant"
                ):
                    assistant_message = resulting_messages[len(initial_messages)]
                if assistant_message is None:
                    choices = ((trajectory.get("response") or {}).get("choices") or [])
                    if choices and isinstance(choices[0], dict):
                        assistant_message = choices[0].get("message")
                if not isinstance(assistant_message, dict):
                    raise ValueError("missing assistant response message")
                previous_tokens = context_tokenizer(
                    [*initial_messages, assistant_message], initial.get("tools"), False
                )
                next_messages = next_context.get("messages")
                if not isinstance(next_messages, list):
                    raise ValueError("next context has no message list")
                next_tokens = context_tokenizer(
                    next_messages, next_context.get("tools"), True
                )
                prefix = common_prefix_length(previous_tokens, next_tokens)
                next_usage = (
                    ((next_trajectory.get("response") or {}).get("usage") or {})
                    if next_trajectory else {}
                )
                reported_next_prompt = next_usage.get("prompt_tokens")
                cache_record.update({
                    "previous_token_count": len(previous_tokens),
                    "next_prompt_token_count": len(next_tokens),
                    "common_prefix_token_count": prefix,
                    "retained_ratio": prefix / len(previous_tokens) if previous_tokens else None,
                    "invalidated_previous_token_count": len(previous_tokens) - prefix,
                    "previous_vs_reported_total_delta": (
                        len(previous_tokens) - total if isinstance(total, (int, float)) else None
                    ),
                    "reported_next_prompt_tokens": reported_next_prompt,
                    "next_prompt_vs_reported_delta": (
                        len(next_tokens) - reported_next_prompt
                        if isinstance(reported_next_prompt, (int, float)) else None
                    ),
                })
            except Exception as exc:
                cache_record["error"] = f"{type(exc).__name__}: {exc}"
            cache_records.append(cache_record)
        if not name:
            continue
        name = str(name)
        last_action_name = name
        actions[name] += 1
        observation = trajectory.get("observation")
        observation_status = observation.get("status") if isinstance(observation, dict) else None
        succeeded = observation_succeeded(observation, trajectory.get("error"))
        (action_success if succeeded else action_failure)[name] += 1
        arguments = action.get("arguments")
        argument_signature = json.dumps(arguments, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        repeated_in_sample = argument_signature in seen_action_signatures[name]
        seen_action_signatures[name].add(argument_signature)
        try:
            observation_chars = len(json.dumps(observation, ensure_ascii=False, sort_keys=True))
        except (TypeError, ValueError):
            observation_chars = len(str(observation))
        after = trajectory.get("state_after") or {}
        deleted_ids.update(after.get("deleted_message_ids") or [])
        notes = after.get("notes") or {}
        if isinstance(notes, dict):
            note_keys.update(map(str, notes.keys()))
        current_prompt = prompt if isinstance(prompt, (int, float)) else None
        next_prompt = None
        if position + 1 < len(trajectory_paths):
            try:
                next_trajectory = loaded_trajectories.get(trajectory_paths[position + 1][0]) or {}
                next_prompt = ((next_trajectory.get("response") or {}).get("usage") or {}).get("prompt_tokens")
            except (AttributeError, TypeError):
                pass
        action_records.append({
            "sample_id": str(result.get("sample_id", sample_dir.name)),
            "trajectory_index": index,
            "tool": name,
            "argument_signature": argument_signature,
            "repeated_in_sample": repeated_in_sample,
            "succeeded": succeeded,
            "observation_status": observation_status,
            "observation_chars": observation_chars,
            "prompt_tokens": current_prompt,
            "next_prompt_tokens": next_prompt,
            "next_prompt_delta": next_prompt - current_prompt
            if isinstance(current_prompt, (int, float)) and isinstance(next_prompt, (int, float)) else None,
        })

    metrics = result.get("metrics") or {}
    recorded_usage = metrics.get("token_usage") or {}
    score = result.get("score")
    score_number = float(score) if isinstance(score, (int, float)) else None
    error = result.get("error")
    requested = REQUESTED_TOKENS_RE.search(str(error)) if error else None
    rejected_request = request_token_breakdown(error)
    final_answer = result.get("final_answer")
    status = result.get("status", "missing")
    parsed_answer = profile.answer_parser(final_answer) if profile.answer_parser else None
    parsed_gold = profile.answer_parser(result.get("correct_answer")) if profile.answer_parser else None
    has_terminal_tool = (
        actions.get(profile.terminal_tool, 0) > 0 if profile.terminal_tool else status == "completed"
    )
    parsed_answer_correct = (
        parsed_answer == parsed_gold if parsed_answer is not None and parsed_gold is not None else None
    )
    if status == "completed" and profile.terminal_tool and has_terminal_tool:
        terminal_mode = profile.terminal_tool
    elif status == "completed":
        terminal_mode = "plain_response"
    else:
        terminal_mode = str(status)
    if status == "completed" and has_terminal_tool:
        valid_completed_score = (
            float(parsed_answer_correct)
            if profile.answer_parser and parsed_answer_correct is not None
            else score_number if profile.answer_parser is None else None
        )
    else:
        valid_completed_score = None
    row = {
        "sample_id": str(result.get("sample_id", sample_dir.name)),
        "artifact_state": "result" if result else ("trajectories_only" if trajectory_paths else "empty"),
        "status": status,
        "score": score_number,
        "correct": score_number is not None and score_number > 0,
        "gold_answer": json_scalar(result.get("correct_answer")),
        "parsed_answer": parsed_answer,
        "parsed_answer_correct": parsed_answer_correct,
        "valid_completed_score": valid_completed_score,
        "terminal_mode": terminal_mode,
        "has_terminal_tool": has_terminal_tool,
        "terminal_tool": profile.terminal_tool,
        "final_answer_has_tool_markup": bool(
            isinstance(final_answer, str) and TOOL_MARKUP_RE.search(final_answer)
        ),
        "failed_with_positive_score": status != "completed" and bool(score_number and score_number > 0),
        "error_class": classify_error(error),
        "error": error,
        "requested_tokens_on_failure": int(requested.group(1)) if requested else None,
        "rejected_message_tokens": rejected_request["message_tokens"] if rejected_request else None,
        "rejected_completion_tokens": rejected_request["completion_tokens"] if rejected_request else None,
        "failure_preceding_tool": last_action_name if status != "completed" else None,
        "trajectory_count": len(trajectory_paths),
        "trajectory_indices_contiguous": contiguous,
        "trajectory_error_count": trajectory_errors,
        "trajectory_statuses": dict(statuses),
        "adjacent_context_checks": adjacent_checks,
        "adjacent_context_mismatches": adjacent_mismatches,
        "api_call_count": metrics.get("api_call_count", len(trajectory_paths)),
        "round_count": metrics.get("round_count"),
        "tool_call_count": metrics.get("tool_call_count", sum(actions.values())),
        "tool_counts": dict(actions),
        "tool_failure_count": sum(action_failure.values()),
        "tool_failure_counts": dict(action_failure),
        "repeated_tool_call_count": sum(record["repeated_in_sample"] for record in action_records),
        "repeated_tool_counts": dict(Counter(
            record["tool"] for record in action_records if record["repeated_in_sample"]
        )),
        "tool_sequence": ">".join(record["tool"] for record in action_records),
        "unique_tool_count": len(actions),
        "deleted_message_count": len(deleted_ids),
        "note_key_count": len(note_keys),
        "calls_with_usage": len(prompt_tokens),
        "prompt_tokens": sum(prompt_tokens) if prompt_tokens else recorded_usage.get("prompt_tokens"),
        "completion_tokens": sum(completion_tokens) if completion_tokens else recorded_usage.get("completion_tokens"),
        "total_tokens": sum(total_tokens) if total_tokens else recorded_usage.get("total_tokens"),
        "first_prompt_tokens": prompt_tokens[0] if prompt_tokens else None,
        "last_prompt_tokens": prompt_tokens[-1] if prompt_tokens else None,
        "max_prompt_tokens": max(prompt_tokens) if prompt_tokens else recorded_usage.get("max_prompt_tokens"),
        "mean_prompt_tokens_per_call": statistics.fmean(prompt_tokens) if prompt_tokens else None,
        "mean_completion_tokens_per_call": statistics.fmean(completion_tokens) if completion_tokens else None,
        "mean_call_latency_seconds": statistics.fmean(call_latency) if call_latency else None,
        "total_call_latency_seconds": sum(call_latency) if call_latency else None,
        "cache_observed_transition_count": sum(
            record["next_call_observed"] and record["retained_ratio"] is not None
            for record in cache_records
        ),
        "cache_common_prefix_tokens": sum(
            record["common_prefix_token_count"] or 0
            for record in cache_records if record["next_call_observed"]
        ),
        "cache_previous_tokens": sum(
            record["previous_token_count"] or 0
            for record in cache_records if record["next_call_observed"]
        ),
    }
    row["theoretical_cache_retention_rate"] = (
        row["cache_common_prefix_tokens"] / row["cache_previous_tokens"]
        if row["cache_previous_tokens"] else None
    )
    for record in action_records:
        record["sample_status"] = row["status"]
        record["sample_score"] = score_number
    return row, action_records, context_records, cache_records, warnings


def select_context_samples(rows: list[dict[str, Any]], limit: int = 6) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()

    def add(row: dict[str, Any], reason: str) -> None:
        sample_id = str(row["sample_id"])
        if sample_id not in selected_ids and len(selected) < limit:
            selected_ids.add(sample_id)
            selected.append({"sample_id": sample_id, "reason": reason})

    failed = sorted(
        (row for row in rows if row["status"] != "completed"),
        key=lambda row: (
            row.get("rejected_message_tokens") or -1,
            row["max_prompt_tokens"] or -1,
            row["api_call_count"] or -1,
        ),
        reverse=True,
    )
    for row in failed[:2]:
        add(row, f"{row['status']} with largest rejected request")

    completed = [row for row in rows if row["status"] == "completed"]
    for correct, label in ((True, "correct"), (False, "incorrect")):
        group = [row for row in completed if bool(row["correct"]) is correct]
        if group:
            add(max(group, key=lambda row: row["api_call_count"] or -1), f"longest completed {label}")

    for correct, label in ((True, "correct"), (False, "incorrect")):
        group = [row for row in completed if bool(row["correct"]) is correct]
        if group:
            median_calls = statistics.median(row["api_call_count"] or 0 for row in group)
            add(
                min(group, key=lambda row: (abs((row["api_call_count"] or 0) - median_calls), str(row["sample_id"]))),
                f"typical completed {label}",
            )

    for row in sorted(rows, key=lambda row: row["max_prompt_tokens"] or -1, reverse=True):
        add(row, "high context pressure")
    return selected


def render_context_evolution_svg(
    selected: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    context_records: list[dict[str, Any]],
    tool_colors: dict[str, str] | None = None,
) -> str:
    tool_colors = assign_tool_colors(
        (record["tool"] for record in context_records), tool_colors
    )
    row_by_id = {str(row["sample_id"]): row for row in rows}
    traces: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in context_records:
        if record["prompt_tokens"] is not None:
            traces[str(record["sample_id"])].append(record)
    for trace in traces.values():
        trace.sort(key=lambda record: record["trajectory_index"])

    panels = [item for item in selected if traces.get(item["sample_id"])]
    columns = 2
    panel_width = 570
    panel_height = 250
    gap = 20
    margin_x = 30
    header_height = 105
    rows_count = max(1, math.ceil(len(panels) / columns))
    width = margin_x * 2 + columns * panel_width + gap
    height = header_height + rows_count * panel_height + max(0, rows_count - 1) * gap + 35
    used_tools = sorted({record["tool"] for item in panels for record in traces[item["sample_id"]]})

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        '<title id="title">Context size evolution by tool</title>',
        '<desc id="desc">Prompt token count across calls for selected samples. Segment colors identify the tool invoked at the segment start.</desc>',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<style>text{font-family:Arial,sans-serif;letter-spacing:0}.title{font-size:20px;font-weight:700;fill:#111827}.subtitle{font-size:12px;fill:#4b5563}.panel-title{font-size:13px;font-weight:700;fill:#111827}.axis{font-size:10px;fill:#6b7280}.legend{font-size:10px;fill:#374151}.grid{stroke:#e5e7eb;stroke-width:1}.axis-line{stroke:#9ca3af;stroke-width:1}</style>',
        '<text class="title" x="30" y="30">Context evolution in selected trajectories</text>',
        '<text class="subtitle" x="30" y="50">Each segment is colored by the tool invoked before the next model call.</text>',
    ]
    legend_x = 30
    legend_y = 76
    for tool in used_tools:
        color = tool_colors[tool]
        label_width = 18 + 7 * len(tool)
        if legend_x + label_width > width - 30:
            legend_x = 30
            legend_y += 18
        svg.extend([
            f'<line x1="{legend_x}" y1="{legend_y}" x2="{legend_x + 14}" y2="{legend_y}" stroke="{color}" stroke-width="4"/>',
            f'<text class="legend" x="{legend_x + 19}" y="{legend_y + 4}">{html.escape(tool)}</text>',
        ])
        legend_x += label_width

    plot_top = max(header_height, legend_y + 22)
    for panel_index, item in enumerate(panels):
        column = panel_index % columns
        row_index = panel_index // columns
        x0 = margin_x + column * (panel_width + gap)
        y0 = plot_top + row_index * (panel_height + gap)
        left = x0 + 55
        right = x0 + panel_width - 18
        top = y0 + 42
        bottom = y0 + panel_height - 36
        trace = traces[item["sample_id"]]
        sample = row_by_id[item["sample_id"]]
        maximum = max(record["prompt_tokens"] for record in trace)
        y_max = max(1000, math.ceil(maximum / 5000) * 5000)
        indices = [record["trajectory_index"] for record in trace]
        x_min, x_max = min(indices), max(indices)

        def px(index: int) -> float:
            return left + (right - left) * (index - x_min) / max(1, x_max - x_min)

        def py(tokens: int) -> float:
            return bottom - (bottom - top) * tokens / y_max

        title = f"Sample {item['sample_id']} - {item['reason']}"
        details = f"status={sample['status']}, score={fmt(sample['score'])}, calls={fmt(sample['api_call_count'], 0)}, peak={maximum:,}"
        svg.extend([
            f'<rect x="{x0}" y="{y0}" width="{panel_width}" height="{panel_height}" rx="4" fill="#ffffff" stroke="#d1d5db"/>',
            f'<text class="panel-title" x="{x0 + 12}" y="{y0 + 18}">{html.escape(title)}</text>',
            f'<text class="axis" x="{x0 + 12}" y="{y0 + 34}">{html.escape(details)}</text>',
        ])
        for fraction in (0.0, 0.5, 1.0):
            grid_y = bottom - (bottom - top) * fraction
            token_label = int(y_max * fraction)
            svg.append(f'<line class="grid" x1="{left}" y1="{grid_y:.1f}" x2="{right}" y2="{grid_y:.1f}"/>')
            svg.append(f'<text class="axis" x="{left - 7}" y="{grid_y + 3:.1f}" text-anchor="end">{token_label // 1000}k</text>')
        svg.extend([
            f'<line class="axis-line" x1="{left}" y1="{top}" x2="{left}" y2="{bottom}"/>',
            f'<line class="axis-line" x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}"/>',
            f'<text class="axis" x="{(left + right) / 2:.1f}" y="{bottom + 27}" text-anchor="middle">Model call index</text>',
            f'<text class="axis" x="{left}" y="{bottom + 13}" text-anchor="middle">{x_min}</text>',
            f'<text class="axis" x="{right}" y="{bottom + 13}" text-anchor="middle">{x_max}</text>',
        ])
        for current, following in zip(trace, trace[1:]):
            color = tool_colors[current["tool"]]
            delta = following["prompt_tokens"] - current["prompt_tokens"]
            svg.append(
                f'<line x1="{px(current["trajectory_index"]):.1f}" y1="{py(current["prompt_tokens"]):.1f}" '
                f'x2="{px(following["trajectory_index"]):.1f}" y2="{py(following["prompt_tokens"]):.1f}" '
                f'stroke="{color}" stroke-width="2.5" stroke-linecap="round">'
                f'<title>call {current["trajectory_index"]}: {html.escape(current["tool"])}; '
                f'{current["prompt_tokens"]:,} to {following["prompt_tokens"]:,} tokens '
                f'(delta {delta:+,})</title></line>'
            )
        for record in trace:
            svg.append(
                f'<circle cx="{px(record["trajectory_index"]):.1f}" cy="{py(record["prompt_tokens"]):.1f}" r="2" fill="#ffffff" stroke="#374151" stroke-width="0.7"/>'
            )
    svg.append("</svg>")
    return "\n".join(svg) + "\n"


def rate_summary(rows: list[dict[str, Any]], denominator: int) -> dict[str, Any]:
    scored = [row for row in rows if row["score"] is not None]
    completed = [row for row in rows if row["status"] == "completed"]
    completed_scored = [row for row in completed if row["score"] is not None]
    successes = sum(bool(row["correct"]) for row in completed_scored)
    valid = [row for row in rows if row["valid_completed_score"] is not None]
    valid_successes = sum(bool(row["valid_completed_score"]) for row in valid)
    parsed_completed = [
        row for row in completed if row["parsed_answer_correct"] is not None
    ]
    parsed_successes = sum(bool(row["parsed_answer_correct"]) for row in parsed_completed)
    return {
        "raw_score_count": len(scored),
        "completed_count": len(completed),
        "completion_rate": len(completed) / denominator if denominator else None,
        "completion_rate_wilson_95": wilson(len(completed), denominator),
        "completed_scored_count": len(completed_scored),
        "completed_correct_count": successes,
        "mean_score_completed": statistics.fmean(row["score"] for row in completed_scored) if completed_scored else None,
        "binary_accuracy_completed": successes / len(completed_scored) if completed_scored else None,
        "binary_accuracy_completed_wilson_95": wilson(successes, len(completed_scored)),
        "parsed_completed_count": len(parsed_completed),
        "parsed_completed_coverage": (
            len(parsed_completed) / len(completed) if completed else None
        ),
        "parsed_completed_correct_count": parsed_successes,
        "parsed_completed_accuracy": (
            parsed_successes / len(parsed_completed) if parsed_completed else None
        ),
        "parsed_completed_accuracy_wilson_95": wilson(
            parsed_successes, len(parsed_completed)
        ),
        "parsed_end_to_end_correct_rate": (
            parsed_successes / denominator if denominator else None
        ),
        "valid_terminal_count": len(valid),
        "valid_terminal_coverage": len(valid) / denominator if denominator else None,
        "valid_terminal_correct_count": valid_successes,
        "valid_terminal_accuracy": valid_successes / len(valid) if valid else None,
        "valid_terminal_accuracy_wilson_95": wilson(valid_successes, len(valid)),
        "strict_end_to_end_correct_rate": valid_successes / denominator if denominator else None,
        "strict_end_to_end_correct_rate_wilson_95": wilson(valid_successes, denominator),
        "end_to_end_correct_rate": successes / denominator if denominator else None,
        "end_to_end_correct_rate_wilson_95": wilson(successes, denominator),
    }


def fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "NA"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def pct(value: Any) -> str:
    return "NA" if value is None else f"{100 * value:.1f}%"


def markdown_report(summary: dict[str, Any]) -> str:
    inventory = summary["inventory"]
    outcomes = summary["outcomes"]
    performance = summary["performance"]
    behavior = summary["behavior"]
    usage = summary["usage"]
    integrity = summary["integrity"]
    profile = summary["analysis"]["profile"]
    terminal_requirement = (
        f"`{profile['terminal_tool']}` tool + {profile['parsed_answer_label']}"
        if profile["terminal_tool"] and profile["answer_parser_enabled"]
        else f"`{profile['terminal_tool']}` tool"
        if profile["terminal_tool"]
        else profile["parsed_answer_label"]
        if profile["answer_parser_enabled"]
        else "completed result"
    )
    lines = [
        f"# Experiment Analysis: {summary['experiment']['name']}", "",
        f"Generated from `{summary['experiment']['path']}` at {summary['analysis']['generated_at']}.", "",
        "This is a single-run descriptive analysis. Associations between tools and scores are not causal, and comparisons with other runs require compatible dataset, sampling, model, prompt, tool, and context configurations.", "",
        "## Coverage and outcomes", "",
        "| Measure | Value |", "|---|---:|",
        f"| Sample directories | {inventory['sample_directory_count']} |",
        f"| Samples with result.json | {inventory['result_count']} |",
        f"| Completed | {outcomes['status_counts'].get('completed', 0)} |",
        f"| Failed | {outcomes['status_counts'].get('failed', 0)} |",
        f"| Other/missing | {inventory['sample_directory_count'] - outcomes['status_counts'].get('completed', 0) - outcomes['status_counts'].get('failed', 0)} |",
        f"| Results carrying a numeric score | {performance['raw_score_count']} |",
        f"| Completion rate | {pct(performance['completion_rate'])} |",
        f"| Completed and scored | {performance['completed_scored_count']} |",
        f"| Correct among completed | {performance['completed_correct_count']} |",
        f"| Accuracy among completed | {pct(performance['binary_accuracy_completed'])} |",
        f"| Completed with {profile['parsed_answer_label']} | {performance['parsed_completed_count']} |",
        f"| Parsed-answer coverage among completed | {pct(performance['parsed_completed_coverage'])} |",
        f"| Accuracy among parsed completed answers | {pct(performance['parsed_completed_accuracy'])} |",
        f"| Parsed-answer end-to-end correct rate | {pct(performance['parsed_end_to_end_correct_rate'])} |",
        f"| Valid terminal results ({terminal_requirement}) | {performance['valid_terminal_count']} |",
        f"| Valid terminal coverage | {pct(performance['valid_terminal_coverage'])} |",
        f"| Accuracy among valid terminal results | {pct(performance['valid_terminal_accuracy'])} |",
        f"| Strict end-to-end correct rate | {pct(performance['strict_end_to_end_correct_rate'])} |",
        f"| End-to-end correct rate (all sample dirs) | {pct(performance['end_to_end_correct_rate'])} |",
        "",
        f"The completed accuracy reproduces the recorded score over completed samples. Parsed-answer metrics apply the configured {profile['parsed_answer_label']} parser regardless of terminal mechanism and are secondary diagnostics, not a replacement benchmark score. The valid-terminal rate additionally requires {terminal_requirement}; read it with terminal coverage because filtering malformed outputs can inflate conditional accuracy. The strict end-to-end rate counts only correct valid terminals over all sample directories. The raw end-to-end rate uses recorded scores for completed samples.", "",
        "## Failures", "",
        "| Error class | Samples |", "|---|---:|",
    ]
    for key, count in sorted(outcomes["error_class_counts"].items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| {key} | {count} |")
    if outcomes["failure_preceding_tool_counts"]:
        lines.extend([
            "", "### Failure attribution", "",
            "| Tool before failed request | Samples |", "|---|---:|",
        ])
        for tool, count in sorted(
            outcomes["failure_preceding_tool_counts"].items(),
            key=lambda item: (-item[1], item[0]),
        ):
            lines.append(f"| {tool} | {count} |")
        rejected = outcomes["rejected_message_tokens"]
        lines.extend([
            "",
            f"Rejected request message tokens: median {fmt(rejected['median'], 0)}, "
            f"P95 {fmt(rejected['p95'], 0)}, maximum {fmt(rejected['max'], 0)}.",
        ])
    context_evolution = behavior["context_evolution"]
    lines.extend([
        "", "## Context evolution", "",
        "Prompt tokens are plotted at each model call. A segment's color identifies the tool invoked at its starting call, so the following endpoint shows the context growth or reduction observed by the next request.", "",
        "![Context evolution by tool](context_evolution.svg)", "",
        "| Sample | Selection reason | Status | Score | Calls | Peak plotted context |",
        "|---|---|---:|---:|---:|---:|",
    ])
    for selected in context_evolution["selected_samples"]:
        lines.append(
            f"| {selected['sample_id']} | {selected['reason']} | {selected['status']} | "
            f"{fmt(selected['score'])} | {fmt(selected['api_call_count'], 0)} | "
            f"{fmt(selected['peak_plotted_context_tokens'], 0)} |"
        )
    cache = behavior["theoretical_cache_retention"]
    lines.extend([
        "", "## Theoretical KV prefix retention", "",
        "This measures the longest common token prefix between the context after "
        "an assistant action and the next recorded model prompt. Terminal snapshots "
        "are retained in the CSV but excluded because no subsequent cache lookup occurred.", "",
        "| Measure | Value |", "|---|---:|",
        f"| Available | {'yes' if cache['available'] else 'no'} |",
        f"| Tokenizer | {cache['tokenizer'] or 'not supplied'} |",
        f"| Adjacent call transitions | {cache['observed_transition_count']} |",
        f"| Token-weighted retained prefix | {pct(cache['weighted_retention_rate'])} |",
        f"| Mean per-transition retention | {pct(cache['per_transition_retention']['mean'])} |",
        f"| Median per-transition retention | {pct(cache['per_transition_retention']['median'])} |",
        f"| Previous tokens considered | {fmt(cache['previous_token_count'], 0)} |",
        f"| Common-prefix tokens | {fmt(cache['common_prefix_token_count'], 0)} |",
        f"| Reconstruction errors | {cache['reconstruction_error_count']} |", "",
        cache["caveat"], "",
        "Reconstruction validation compares locally rendered lengths with the "
        "server-reported token usage. Non-zero deltas indicate tokenizer, chat-template, "
        "or serving serialization differences and should be investigated before treating "
        "the rate as exact.", "",
        "| Validation delta | Median | P95 | Max |", "|---|---:|---:|---:|",
        f"| Rendered `(s_t, a_t)` minus reported total | "
        f"{fmt(cache['previous_vs_reported_total_delta']['median'])} | "
        f"{fmt(cache['previous_vs_reported_total_delta']['p95'])} | "
        f"{fmt(cache['previous_vs_reported_total_delta']['max'])} |",
        f"| Rendered next prompt minus reported prompt | "
        f"{fmt(cache['next_prompt_vs_reported_delta']['median'])} | "
        f"{fmt(cache['next_prompt_vs_reported_delta']['p95'])} | "
        f"{fmt(cache['next_prompt_vs_reported_delta']['max'])} |",
    ])
    if cache["by_action"]:
        lines.extend([
            "", "### Retention by preceding action", "",
            "| Action | Transitions | Token-weighted retention | Mean transition retention | Invalidated previous tokens |",
            "|---|---:|---:|---:|---:|",
        ])
        for action in cache["by_action"]:
            lines.append(
                f"| {action['action']} | {action['transition_count']} | "
                f"{pct(action['weighted_retention_rate'])} | "
                f"{pct(action['per_transition_retention']['mean'])} | "
                f"{action['invalidated_previous_token_count']} |"
            )
    lines.extend(["", "## Resource use", "", "| Per-sample metric | Mean | Median | P90 | P95 | Max |", "|---|---:|---:|---:|---:|---:|"])
    for key, label in (("api_call_count", "API calls"), ("tool_call_count", "Tool calls"),
                       ("prompt_tokens", "Prompt tokens"), ("completion_tokens", "Completion tokens"),
                       ("max_prompt_tokens", "Peak prompt tokens"), ("total_call_latency_seconds", "Recorded call latency (s)")):
        stats = usage[key]
        lines.append(f"| {label} | {fmt(stats['mean'])} | {fmt(stats['median'])} | {fmt(stats['p90'])} | {fmt(stats['p95'])} | {fmt(stats['max'])} |")
    lines.extend(["", "## Tool behavior", "", "| Tool | Calls | Samples using | Calls/sample | Success rate | Repeated arguments | Mean next-prompt delta |", "|---|---:|---:|---:|---:|---:|---:|"])
    for tool in behavior["tools"]:
        lines.append(
            f"| {tool['tool']} | {tool['call_count']} | {tool['sample_count']} | "
            f"{fmt(tool['calls_per_sample'])} | {pct(tool['success_rate'])} | "
            f"{tool['repeated_argument_call_count']} | {fmt(tool['next_prompt_delta']['mean'])} |"
        )
    conditioned = behavior["score_conditioned"]
    lines.extend(["", "## Correct versus incorrect completed samples", "", "| Metric | Correct mean | Incorrect mean |", "|---|---:|---:|"])
    for key, label in (("api_call_count", "API calls"), ("tool_call_count", "Tool calls"),
                       ("prompt_tokens", "Prompt tokens"), ("completion_tokens", "Completion tokens"),
                       ("max_prompt_tokens", "Peak prompt tokens"), ("deleted_message_count", "Deleted messages"),
                       ("note_key_count", "Final distinct note keys")):
        lines.append(f"| {label} | {fmt(conditioned['correct'][key]['mean'])} | {fmt(conditioned['incorrect'][key]['mean'])} |")
    lines.extend(["", "These groups are post-outcome descriptions: harder samples can cause both more tool use and lower accuracy.", "",
                  "## Terminal-state audit", "", "| Finding | Samples |", "|---|---:|",
                  f"| Completed without required terminal tool | {integrity['completed_without_terminal_tool_count']} |",
                  f"| Final answer contains tool markup | {integrity['final_answer_tool_markup_count']} |",
                  f"| Failed/incomplete with positive raw score | {integrity['failed_with_positive_score_count']} |", "",
                  "## Data quality", "", "| Check | Value |", "|---|---:|",
                  f"| Malformed/unreadable artifacts | {len(integrity['warnings'])} |",
                  f"| Samples with non-contiguous trajectory indices | {integrity['noncontiguous_sample_count']} |",
                  f"| Adjacent context pairs checked | {integrity['adjacent_context_checks']} |",
                  f"| Adjacent context mismatches | {integrity['adjacent_context_mismatches']} |",
                  f"| Report/sample prompt-token difference | {fmt(integrity['report_minus_sample_prompt_tokens'], 0)} |", "",
                  "## Outputs", "", "- `summary.json`: complete aggregate statistics and source configuration.",
                  "- `samples.csv`: one normalized row per sample directory.",
                  "- `tools.csv`: one row per tool, including score-conditioned usage.",
                  "- `tool_calls.csv`: one row per recorded tool action for sequence or transition analysis.",
                  "- `context_evolution.csv`: prompt tokens and invoked tool for every recorded model call.",
                  "- `context_evolution.svg`: tool-colored context trajectories embedded above.",
                  "- `cache_transitions.csv`: token-prefix retention for every reconstructable snapshot transition.", ""])
    return "\n".join(lines)


def analyze_experiment(
    experiment_dir: str | Path,
    *,
    context_sample_limit: int = 6,
    tool_colors: dict[str, str] | None = None,
    profile: AnalysisProfile | None = None,
    context_tokenizer: ContextTokenizer | None = None,
    context_tokenizer_name: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> ExperimentAnalysis:
    """Read one experiment and return normalized data without writing files."""
    profile = profile or AnalysisProfile()
    experiment_dir = Path(experiment_dir).resolve()
    samples_dir = experiment_dir / "samples"
    if not samples_dir.is_dir():
        raise FileNotFoundError(f"missing samples directory: {samples_dir}")

    report: dict[str, Any] = {}
    report_path = experiment_dir / "report.json"
    report_warning = None
    if report_path.exists():
        try:
            report = load_json(report_path)
        except (OSError, json.JSONDecodeError) as exc:
            report_warning = f"report.json: {exc}"

    sample_dirs = sorted((path for path in samples_dir.iterdir() if path.is_dir()), key=lambda path: path.name)
    rows: list[dict[str, Any]] = []
    action_rows: list[dict[str, Any]] = []
    context_rows: list[dict[str, Any]] = []
    cache_rows: list[dict[str, Any]] = []
    warnings: list[str] = [report_warning] if report_warning else []
    for completed_count, sample_dir in enumerate(sample_dirs, start=1):
        row, actions, contexts, cache, sample_warnings = analyze_sample(
            sample_dir, profile, context_tokenizer
        )
        rows.append(row)
        action_rows.extend(actions)
        context_rows.extend(contexts)
        cache_rows.extend(cache)
        warnings.extend(sample_warnings)
        if progress_callback is not None:
            progress_callback(completed_count, len(sample_dirs), sample_dir.name)

    status_counts = Counter(str(row["status"]) for row in rows)
    error_counts = Counter(row["error_class"] for row in rows)
    artifact_counts = Counter(row["artifact_state"] for row in rows)
    performance = rate_summary(rows, len(rows))
    completed_scored = [row for row in rows if row["status"] == "completed" and row["score"] is not None]
    correct_rows = [row for row in completed_scored if row["correct"]]
    incorrect_rows = [row for row in completed_scored if not row["correct"]]
    numeric_fields = ["api_call_count", "round_count", "tool_call_count", "prompt_tokens", "completion_tokens",
                      "total_tokens", "first_prompt_tokens", "last_prompt_tokens", "max_prompt_tokens",
                      "mean_prompt_tokens_per_call", "mean_completion_tokens_per_call", "mean_call_latency_seconds",
                      "total_call_latency_seconds", "deleted_message_count", "note_key_count"]

    tool_names = sorted({name for row in rows for name in row["tool_counts"]})
    tools: list[dict[str, Any]] = []
    for name in tool_names:
        records = [record for record in action_rows if record["tool"] == name]
        samples_using = {record["sample_id"] for record in records}
        success_count = sum(bool(record["succeeded"]) for record in records)
        completed_records = [record for record in records if record["sample_status"] == "completed"]
        correct_records = [record for record in completed_records if record["sample_score"] is not None and record["sample_score"] > 0]
        incorrect_records = [record for record in completed_records if record["sample_score"] == 0]
        tools.append({
            "tool": name,
            "call_count": len(records),
            "sample_count": len(samples_using),
            "sample_rate": len(samples_using) / len(rows) if rows else None,
            "calls_per_sample": len(records) / len(rows) if rows else None,
            "success_count": success_count,
            "failure_count": len(records) - success_count,
            "success_rate": success_count / len(records) if records else None,
            "repeated_argument_call_count": sum(record["repeated_in_sample"] for record in records),
            "samples_with_repeated_arguments": len({
                record["sample_id"] for record in records if record["repeated_in_sample"]
            }),
            "observation_chars": distribution(record["observation_chars"] for record in records),
            "next_prompt_delta": distribution(record["next_prompt_delta"] for record in records),
            "correct_completed_call_count": len(correct_records),
            "incorrect_completed_call_count": len(incorrect_records),
            "correct_completed_calls_per_sample": len(correct_records) / len(correct_rows) if correct_rows else None,
            "incorrect_completed_calls_per_sample": len(incorrect_records) / len(incorrect_rows) if incorrect_rows else None,
        })

    report_prompt = (((report.get("metrics") or {}).get("token_usage") or {}).get("prompt_tokens"))
    sample_prompt = sum(row["prompt_tokens"] or 0 for row in rows)
    context_selection = select_context_samples(rows, limit=context_sample_limit)
    assigned_tool_colors = assign_tool_colors(
        (record["tool"] for record in context_rows), tool_colors
    )
    rows_by_id = {str(row["sample_id"]): row for row in rows}
    selected_context_samples = []
    for item in context_selection:
        row = rows_by_id[item["sample_id"]]
        selected_context_samples.append({
            **item,
            "status": row["status"],
            "score": row["score"],
            "api_call_count": row["api_call_count"],
            "max_prompt_tokens": row["max_prompt_tokens"],
            "peak_plotted_context_tokens": max(
                row["max_prompt_tokens"] or 0,
                row["rejected_message_tokens"] or 0,
            ),
        })
    observed_cache_rows = [
        record for record in cache_rows
        if record["next_call_observed"] and record["retained_ratio"] is not None
    ]
    cache_previous_tokens = sum(
        record["previous_token_count"] for record in observed_cache_rows
    )
    cache_common_prefix_tokens = sum(
        record["common_prefix_token_count"] for record in observed_cache_rows
    )
    cache_summary = {
        "available": context_tokenizer is not None,
        "tokenizer": context_tokenizer_name,
        "definition": (
            "LCP(chat_template(s_t + a_t), chat_template(s_{t+1})) / "
            "len(chat_template(s_t + a_t))"
        ),
        "scope": "adjacent recorded LLM calls; terminal snapshots are excluded",
        "transition_record_count": len(cache_rows),
        "observed_transition_count": len(observed_cache_rows),
        "terminal_snapshot_count": sum(
            record["transition_scope"] == "terminal_snapshot" for record in cache_rows
        ),
        "missing_adjacent_trajectory_count": sum(
            record["transition_scope"] == "missing_adjacent_trajectory"
            for record in cache_rows
        ),
        "reconstruction_error_count": sum(record["error"] is not None for record in cache_rows),
        "reconstruction_error_counts": dict(Counter(
            record["error"] for record in cache_rows if record["error"] is not None
        )),
        "recorded_context_mismatch_count": sum(
            record["recorded_contexts_match"] is False for record in cache_rows
        ),
        "previous_token_count": cache_previous_tokens,
        "common_prefix_token_count": cache_common_prefix_tokens,
        "weighted_retention_rate": (
            cache_common_prefix_tokens / cache_previous_tokens
            if cache_previous_tokens else None
        ),
        "per_transition_retention": distribution(
            record["retained_ratio"] for record in observed_cache_rows
        ),
        "by_action": cache_retention_by_action(cache_rows),
        "invalidated_previous_tokens": distribution(
            record["invalidated_previous_token_count"] for record in observed_cache_rows
        ),
        "previous_vs_reported_total_delta": distribution(
            record["previous_vs_reported_total_delta"] for record in observed_cache_rows
        ),
        "next_prompt_vs_reported_delta": distribution(
            record["next_prompt_vs_reported_delta"] for record in observed_cache_rows
        ),
        "caveat": (
            "Token-level theoretical retention reconstructed from saved messages. "
            "It is not an observed serving-engine cache hit rate and does not model "
            "block alignment, eviction, routing, or cache policy."
        ),
    }
    summary = {
        "analysis": {
            "schema_version": 2,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "profile": {
                "terminal_tool": profile.terminal_tool,
                "answer_parser_enabled": profile.answer_parser is not None,
                "parsed_answer_label": profile.parsed_answer_label,
            },
        },
        "experiment": {"name": experiment_dir.name, "path": str(experiment_dir), "report": report},
        "inventory": {
            "sample_directory_count": len(rows),
            "result_count": sum(row["artifact_state"] == "result" for row in rows),
            "trajectory_file_count": sum(row["trajectory_count"] for row in rows),
            "artifact_state_counts": dict(artifact_counts),
        },
        "outcomes": {
            "status_counts": dict(status_counts),
            "error_class_counts": dict(error_counts),
            "requested_tokens_on_context_failure": distribution(
                row["requested_tokens_on_failure"] for row in rows if row["error_class"] == "context_limit"
            ),
            "rejected_message_tokens": distribution(
                row["rejected_message_tokens"] for row in rows
            ),
            "failure_preceding_tool_counts": dict(Counter(
                row["failure_preceding_tool"] or "unknown"
                for row in rows if row["status"] != "completed"
            )),
            "parsed_answer_counts": dict(Counter(
                row["parsed_answer"] or "unparsed"
                for row in rows if row["artifact_state"] == "result"
            )),
        },
        "performance": performance,
        "usage": {field: distribution(row[field] for row in rows) for field in numeric_fields},
        "behavior": {
            "tools": tools,
            "theoretical_cache_retention": cache_summary,
            "context_evolution": {
                "selected_samples": selected_context_samples,
                "tool_colors": assigned_tool_colors,
                "call_count": len(context_rows),
            },
            "top_tool_sequences": Counter(row["tool_sequence"] for row in rows).most_common(20),
            "score_conditioned": {
                "correct": {field: distribution(row[field] for row in correct_rows) for field in numeric_fields},
                "incorrect": {field: distribution(row[field] for row in incorrect_rows) for field in numeric_fields},
            },
        },
        "integrity": {
            "warnings": warnings,
            "terminal_mode_counts": dict(Counter(row["terminal_mode"] for row in rows)),
            "completed_without_terminal_tool_count": sum(
                row["status"] == "completed" and not row["has_terminal_tool"] for row in rows
            ),
            "final_answer_tool_markup_count": sum(row["final_answer_has_tool_markup"] for row in rows),
            "failed_with_positive_score_count": sum(row["failed_with_positive_score"] for row in rows),
            "noncontiguous_sample_count": sum(not row["trajectory_indices_contiguous"] for row in rows),
            "adjacent_context_checks": sum(row["adjacent_context_checks"] for row in rows),
            "adjacent_context_mismatches": sum(row["adjacent_context_mismatches"] for row in rows),
            "sample_prompt_tokens": sample_prompt,
            "report_prompt_tokens": report_prompt,
            "report_minus_sample_prompt_tokens": report_prompt - sample_prompt if isinstance(report_prompt, (int, float)) else None,
        },
    }

    return ExperimentAnalysis(
        experiment_dir=experiment_dir,
        summary=summary,
        samples=rows,
        tools=tools,
        tool_calls=action_rows,
        context_calls=context_rows,
        cache_transitions=cache_rows,
        context_selection=context_selection,
        tool_colors=assigned_tool_colors,
    )


def write_analysis(
    analysis: ExperimentAnalysis,
    output_dir: str | Path | None = None,
) -> Path:
    """Atomically write the standard derived artifacts for an analysis."""
    output_dir = Path(output_dir or analysis.experiment_dir / "analysis").resolve()
    flat_rows = []
    for row in analysis.samples:
        flat = dict(row)
        for field in ("tool_counts", "tool_failure_counts", "repeated_tool_counts", "trajectory_statuses"):
            flat[field] = json.dumps(flat[field], ensure_ascii=True, sort_keys=True)
        flat_rows.append(flat)
    sample_fields = list(flat_rows[0]) if flat_rows else ["sample_id"]
    tool_fields = list(analysis.tools[0]) if analysis.tools else ["tool"]
    flat_tools = []
    for tool in analysis.tools:
        flat = dict(tool)
        flat["observation_chars"] = json.dumps(flat["observation_chars"], sort_keys=True)
        flat["next_prompt_delta"] = json.dumps(flat["next_prompt_delta"], sort_keys=True)
        flat_tools.append(flat)
    action_fields = list(analysis.tool_calls[0]) if analysis.tool_calls else ["sample_id", "trajectory_index", "tool"]
    context_fields = list(analysis.context_calls[0]) if analysis.context_calls else ["sample_id", "trajectory_index", "prompt_tokens", "tool"]
    cache_fields = list(analysis.cache_transitions[0]) if analysis.cache_transitions else ["sample_id", "trajectory_index", "next_call_observed"]

    atomic_write(output_dir / "summary.json", json.dumps(analysis.summary, indent=2, ensure_ascii=True, sort_keys=True) + "\n")
    atomic_csv(output_dir / "samples.csv", flat_rows, sample_fields)
    atomic_csv(output_dir / "tools.csv", flat_tools, tool_fields)
    atomic_csv(output_dir / "tool_calls.csv", analysis.tool_calls, action_fields)
    atomic_csv(output_dir / "context_evolution.csv", analysis.context_calls, context_fields)
    atomic_csv(output_dir / "cache_transitions.csv", analysis.cache_transitions, cache_fields)
    atomic_write(
        output_dir / "context_evolution.svg",
        render_context_evolution_svg(
            analysis.context_selection,
            analysis.samples,
            analysis.context_calls,
            analysis.tool_colors,
        ),
    )
    atomic_write(output_dir / "report.md", markdown_report(analysis.summary))
    return output_dir
