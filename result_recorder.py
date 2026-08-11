"""Reference recorder for project-local quantitative experiment artifacts.

Copy and adapt this module inside the project that owns an experiment. It does
not discover prompts, framework state, tool events, scores, or token usage by
itself; the project adapter must supply those values at the actual call and
tool-execution boundaries. See QUANTITATIVE_ANALYSIS.md.
"""

import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


SCHEMA_VERSION = 1
PRIMARY_ARTIFACT_RE = re.compile(r"^(?:trajectory_\d+|final_trajectory|result)\.json$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sanitize(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    elif hasattr(value, "dict"):
        value = value.dict()
    if isinstance(value, dict):
        return {str(key): sanitize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [sanitize(item) for item in value]
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def atomic_write_json(path: Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(sanitize(value), stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def read_json(path: Path) -> Dict[str, Any]:
    with Path(path).open(encoding="utf-8") as stream:
        return json.load(stream)


def safe_sample_id(value: Any) -> str:
    result = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value))
    if not result or result in {".", ".."}:
        raise ValueError(f"Invalid sample id: {value!r}")
    return result


def archive_primary_attempt(sample_dir: Path) -> Optional[Path]:
    sample_dir = Path(sample_dir)
    primary = [
        path for path in sample_dir.iterdir()
        if path.is_file() and PRIMARY_ARTIFACT_RE.match(path.name)
    ] if sample_dir.exists() else []
    if not primary:
        return None
    attempts_dir = sample_dir / "attempts"
    attempts_dir.mkdir(parents=True, exist_ok=True)
    attempt_index = 0
    while (attempts_dir / f"attempt_{attempt_index}").exists():
        attempt_index += 1
    destination = attempts_dir / f"attempt_{attempt_index}"
    destination.mkdir()
    for path in primary:
        os.replace(path, destination / path.name)
    return destination


def prepare_sample(sample_dir: Path, resume: bool) -> bool:
    sample_dir = Path(sample_dir)
    result_path = sample_dir / "result.json"
    if result_path.exists() and read_json(result_path).get("status") == "completed":
        if resume:
            return False
        raise RuntimeError(f"Completed sample already exists: {sample_dir}")
    if sample_dir.exists() and any(sample_dir.iterdir()):
        if not resume:
            raise RuntimeError(f"Sample artifacts already exist: {sample_dir}")
        archive_primary_attempt(sample_dir)
    sample_dir.mkdir(parents=True, exist_ok=True)
    return True


class SampleRecorder:
    def __init__(self, sample_dir: Path, sample_id: Any):
        self.sample_dir = Path(sample_dir)
        self.sample_id = str(sample_id)
        self.sample_dir.mkdir(parents=True, exist_ok=True)
        self._active_index: Optional[int] = None
        self._next_index = 0
        self._last_resulting_context: Optional[Dict[str, Any]] = None

    def _path(self, index: int) -> Path:
        return self.sample_dir / f"trajectory_{index}.json"

    def begin_call(self, request: Dict[str, Any], state_before: Dict[str, Any]) -> int:
        if self._active_index is not None:
            raise RuntimeError("Cannot begin an LLM call while another call is active")
        normalized_request = sanitize(request)
        if self._last_resulting_context is not None and normalized_request != self._last_resulting_context:
            raise RuntimeError(
                "The initial context does not match the previous transition's resulting context"
            )
        index = self._next_index
        self._next_index += 1
        self._active_index = index
        atomic_write_json(self._path(index), {
            "schema_version": SCHEMA_VERSION,
            "sample_id": self.sample_id,
            "trajectory_index": index,
            "status": "pending",
            "started_at": utc_now(),
            "initial_context": normalized_request,
            "state_before": state_before,
            "response": None,
            "usage": None,
            "action": None,
            "observation": None,
            "state_after": None,
            "resulting_context": None,
            "error": None,
        })
        return index

    def record_response(
        self,
        index: int,
        response: Any,
        usage: Optional[Dict[str, Any]] = None,
    ) -> None:
        snapshot = read_json(self._path(index))
        snapshot["status"] = "response_received"
        snapshot["response"] = sanitize(response)
        snapshot["usage"] = sanitize(usage) if usage is not None else None
        atomic_write_json(self._path(index), snapshot)

    @property
    def has_active_call(self) -> bool:
        return self._active_index is not None

    def fail_active_call(
        self,
        error: str,
        state_after: Dict[str, Any],
        resulting_context: Dict[str, Any],
    ) -> None:
        if self._active_index is None:
            return
        self.complete_call(
            self._active_index,
            action=None,
            observation=None,
            state_after=state_after,
            resulting_context=resulting_context,
            error=error,
        )

    def complete_call(
        self,
        index: int,
        *,
        action: Optional[Dict[str, Any]],
        observation: Any,
        state_after: Dict[str, Any],
        resulting_context: Dict[str, Any],
        error: Optional[str] = None,
    ) -> None:
        if self._active_index != index:
            raise RuntimeError(f"Call {index} is not the active call")
        snapshot = read_json(self._path(index))
        snapshot.update({
            "status": "failed" if error else "completed",
            "completed_at": utc_now(),
            "action": action,
            "observation": observation,
            "state_after": state_after,
            "resulting_context": resulting_context,
            "error": error,
        })
        atomic_write_json(self._path(index), snapshot)
        self._last_resulting_context = sanitize(resulting_context)
        self._active_index = None

    def metrics(self) -> Dict[str, Any]:
        calls = []
        tool_calls = Counter()
        failed = 0
        for path in sorted(self.sample_dir.glob("trajectory_*.json"), key=_trajectory_number):
            snapshot = read_json(path)
            response = snapshot.get("response") or {}
            response_usage = response.get("usage") if isinstance(response, dict) else None
            usage = snapshot.get("usage") or response_usage or {}
            prompt = int(usage.get("prompt_tokens") or 0)
            completion = int(usage.get("completion_tokens") or 0)
            total = int(usage.get("total_tokens") or prompt + completion)
            calls.append({
                "trajectory_index": snapshot["trajectory_index"],
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": total,
                "usage_available": bool(usage),
            })
            action = snapshot.get("action")
            if action and action.get("name"):
                tool_calls[action["name"]] += 1
            failed += snapshot.get("status") != "completed"
        return {
            "api_call_count": len(calls),
            "successful_api_call_count": len(calls) - failed,
            "failed_api_call_count": failed,
            "round_count": len(calls),
            "tool_call_count": sum(tool_calls.values()),
            "tool_calls": dict(sorted(tool_calls.items())),
            "token_usage": {
                "calls_with_usage": sum(item["usage_available"] for item in calls),
                "prompt_tokens": sum(item["prompt_tokens"] for item in calls),
                "completion_tokens": sum(item["completion_tokens"] for item in calls),
                "total_tokens": sum(item["total_tokens"] for item in calls),
                "max_prompt_tokens": max((item["prompt_tokens"] for item in calls), default=0),
                "per_call": calls,
            },
        }

    def finalize(
        self,
        *,
        full_history: Any,
        final_context: Any,
        result: Dict[str, Any],
        status: str,
        error: Optional[str],
    ) -> None:
        metrics = self.metrics()
        atomic_write_json(self.sample_dir / "final_trajectory.json", {
            "schema_version": SCHEMA_VERSION,
            "sample_id": self.sample_id,
            "status": status,
            "error": error,
            "completed_at": utc_now(),
            "trajectory_count": metrics["api_call_count"],
            "trajectory_files": [
                f"trajectory_{index}.json" for index in range(metrics["api_call_count"])
            ],
            "full_history": full_history,
            "final_context": final_context,
            "metrics": metrics,
        })
        normalized_result = dict(result)
        normalized_result.update({
            "schema_version": SCHEMA_VERSION,
            "sample_id": self.sample_id,
            "status": status,
            "error": error,
            "metrics": metrics,
            "completed_at": utc_now(),
        })
        atomic_write_json(self.sample_dir / "result.json", normalized_result)


def _trajectory_number(path: Path) -> int:
    return int(path.stem.rsplit("_", 1)[1])


def initialize_experiment(
    experiment_dir: Path,
    identity: Dict[str, Any],
    configuration: Dict[str, Any],
    resume: bool,
) -> None:
    experiment_dir = Path(experiment_dir)
    report_path = experiment_dir / "report.json"
    if report_path.exists():
        existing = read_json(report_path)
        if existing.get("identity") != sanitize(identity) or existing.get("configuration") != sanitize(configuration):
            raise RuntimeError(f"Existing experiment configuration does not match: {experiment_dir}")
        if not resume:
            raise RuntimeError(f"Experiment already exists; use resume explicitly: {experiment_dir}")
        return
    if experiment_dir.exists() and any(experiment_dir.iterdir()):
        raise RuntimeError(f"Experiment directory exists without a compatible report: {experiment_dir}")
    experiment_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(report_path, {
        "schema_version": SCHEMA_VERSION,
        "identity": identity,
        "configuration": configuration,
        "status": "running",
        "created_at": utc_now(),
        "dataset_coverage": {},
        "scores": {},
        "metrics": {},
    })


def aggregate_report(experiment_dir: Path, expected_sample_ids: Iterable[Any]) -> Dict[str, Any]:
    experiment_dir = Path(experiment_dir)
    report = read_json(experiment_dir / "report.json")
    results = []
    for path in (experiment_dir / "samples").glob("*/result.json"):
        results.append(read_json(path))
    results.sort(key=lambda item: str(item.get("sample_id")))
    expected_ids = [str(item) for item in expected_sample_ids]
    completed = [item for item in results if item.get("status") == "completed"]
    failed = [item for item in results if item.get("status") != "completed"]
    scored = [item for item in completed if item.get("score") is not None]
    token_keys = ("prompt_tokens", "completion_tokens", "total_tokens")
    report.update({
        "status": "completed" if len(completed) == len(expected_ids) else "partial",
        "updated_at": utc_now(),
        "dataset_coverage": {
            "expected_count": len(expected_ids),
            "recorded_count": len(results),
            "completed_count": len(completed),
            "failed_count": len(failed),
            "missing_sample_ids": sorted(set(expected_ids) - {str(item["sample_id"]) for item in results}),
        },
        "scores": {
            "scored_count": len(scored),
            "correct_count": sum(float(item["score"]) == 1.0 for item in scored),
            "mean": (
                sum(float(item["score"]) for item in scored) / len(scored)
                if scored else None
            ),
        },
        "metrics": {
            "api_call_count": sum(item.get("metrics", {}).get("api_call_count", 0) for item in results),
            "tool_call_count": sum(item.get("metrics", {}).get("tool_call_count", 0) for item in results),
            "retry_attempt_count": sum(
                len(list((path.parent / "attempts").glob("attempt_*")))
                for path in (experiment_dir / "samples").glob("*/result.json")
            ),
            "token_usage": {
                key: sum(item.get("metrics", {}).get("token_usage", {}).get(key, 0) for item in results)
                for key in token_keys
            },
        },
    })
    report["metrics"]["token_usage"]["max_prompt_tokens"] = max(
        (item.get("metrics", {}).get("token_usage", {}).get("max_prompt_tokens", 0) for item in results),
        default=0,
    )
    atomic_write_json(experiment_dir / "report.json", report)
    return report
