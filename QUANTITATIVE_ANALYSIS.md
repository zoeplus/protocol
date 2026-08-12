# Quantitative Analysis Foundation

This document defines a common recording contract for experiments across the
controlled projects. Its purpose is to make trajectories, outcomes, and usage
comparable without moving result ownership out of the project that produced
them. It covers data capture and normalization; benchmark-specific scoring and
later statistical analysis remain project work.

## Scope and integration boundary

`result_recorder.py` is a reference implementation, not a universal tracing
plugin. A project should copy or adapt it within its own source tree and commit
that integration with the experiment launcher. Do not import it at runtime
from the sibling `server` repository.

The recorder can provide atomic files, retry preservation, transition
numbering, token aggregation, and the common result layout. It cannot infer:

- the exact request actually sent to a model;
- framework-specific context, memory, or tool state;
- which response fields contain usage or model output;
- the action and complete observation produced by a tool;
- the resulting request context after context management;
- benchmark scoring, sample identity, or meaningful experiment configuration.

Each project therefore needs a small adapter at its real model-call and
tool-execution boundaries. When a framework already has reliable tracing,
write an exporter to this contract instead of inserting a second competing
recorder. If exact call-boundary capture is impossible, document the missing
fields in the project README and do not label reconstructed data as exact.

## Artifact contract

Use the project-local layout defined in "Experiment results" below:

```text
results/<benchmark>/<method>--<model>/
├── report.json
└── samples/<sample-id>/
    ├── trajectory_0.json
    ├── trajectory_1.json
    ├── ...
    ├── final_trajectory.json
    ├── result.json
    └── attempts/attempt_<num>/
```

`trajectory_<num>.json` is one complete LLM-call transition, not one isolated
action-observation pair. It contains:

- `initial_context`: the exact serialized model request before the call;
- `response`: the complete serializable model response;
- `usage`: normalized prompt, completion, and total tokens when available;
- `action` and `observation`: the invoked tool and its complete returned value;
- `state_before` and `state_after`: framework state needed to explain context
  changes, such as notes, memory, deleted message IDs, or retrieval state;
- `resulting_context`: the exact request context that would be used by the next
  model call;
- status, error, sample ID, index, and timestamps.

The resulting context of transition `n` must equal the initial context of
transition `n + 1`. This invariant makes prompt deletion, compression, memory,
retrieval, and note updates quantitatively inspectable.

`final_trajectory.json` summarizes the completed or failed session, references
the numbered snapshots, and stores final history and context. It need not
duplicate every transition. `result.json` contains the sample outcome, score,
status, error, and per-sample metrics. `report.json` contains experiment
identity, effective model and inference configuration, dataset coverage,
aggregate scores, and aggregate metrics.

## Recording lifecycle

For each sample:

1. Resolve a stable sample ID and prepare its directory. On explicit resume,
   skip completed samples and archive incomplete primary artifacts as a new
   `attempt_<num>` before retrying.
2. Immediately before the model request, atomically write a pending snapshot
   containing the exact request and state before the call.
3. After receiving the response, persist the full response and normalized
   usage before executing the requested action.
4. After the action, complete the same snapshot with the action, full
   observation, state after the action, and exact resulting context.
5. On failure, complete the active snapshot with the available response,
   resulting state, and error. Never silently discard the failed call.
6. Finalize `final_trajectory.json` and `result.json`. Only the coordinating
   process aggregates `report.json` after workers stop writing sample files.

Parallel workers may process different sample directories. Two workers must
never own the same sample attempt, and workers must not concurrently rewrite
the aggregate report.

## Configuration and metrics

Record conditions that affect model behavior: model and checkpoint identity,
context and output limits, sampling parameters, prompt/tool configuration,
agent or method version, dataset and split, and benchmark-specific options.
Keep service infrastructure such as GPU utilization, device IDs, tensor
parallel size, ports, and daemon PIDs in operational logs unless it defines a
deliberate experimental condition.

At minimum, agent experiments should expose:

- sample completion, failure, answer, and score;
- model/API call count and failed-call count;
- tool-call count by tool name;
- prompt, completion, and total tokens per call and in aggregate;
- maximum prompt tokens observed;
- retry-attempt count.

The transition files also support derived measurements without changing the
collection format: context growth and reduction per call, tokens removed by
context management, tool sequence and frequency, retrieval volume, latency
when timestamps are sufficiently precise, and behavior before and after a
memory operation. Derived metrics should be written by a separate analysis
stage so raw trajectories remain immutable.

## Required adaptation

Before using the reference recorder in a new project, define and test:

- where the final serialized request exists immediately before transport;
- how response and usage objects are converted to JSON-safe values;
- where tool dispatch begins and the complete observation becomes available;
- which internal state explains prompt changes;
- how the next exact request is reconstructed after the action;
- how final answers, scores, failures, and expected sample IDs are determined;
- whether multiprocessing assigns exclusive sample ownership.

The adapter must preserve native information rather than forcing unlike
framework concepts into misleading fields. Additional namespaced fields are
allowed. Changing the meaning of a common field requires a schema-version
change.

## Validation gate

Run a one-sample smoke test before a full collection. Verify that:

- trajectory indices are zero-based and contiguous;
- every completed transition has request, response, state, and resulting
  context fields appropriate to the framework;
- adjacent context equality holds exactly;
- a real context-management or tool transition shows the expected before and
  after change;
- per-call token sums equal sample and report aggregates;
- `result.json` and `report.json` agree on status and coverage;
- resume skips completed samples and archives an interrupted attempt;
- the full experiment configuration rejects an incompatible resume.

Only after this gate passes should the project launcher start a full run. Keep
the smoke artifact in the canonical experiment only when the full run uses the
same configuration and can resume it without rewriting the sample.

## Experiment results

[`result_recorder.py`](result_recorder.py) is a reference implementation to
copy and adapt inside the project that owns an experiment; it is not a
drop-in recorder for every agent or evaluation framework.

Keep every generated experiment artifact inside the project that produced it,
under its project-local `results/` directory. Never create an ad hoc result
root elsewhere in `$HOME`, such as `~/statelm-evaluation`.

Use this structure:

```text
results/
└── <benchmark>/
    └── <method>--<model>/
        ├── report.json
        └── samples/
            └── <sample-id>/
                ├── final_trajectory.json
                ├── trajectory_0.json
                ├── trajectory_1.json
                ├── ...
                └── result.json
```

The first level is the benchmark. The second level is the experiment ID: the
method and model joined as `<method>--<model>`, for example
`statelm--qwen3-8b`. Add a short configuration suffix only when it distinguishes
a real experimental condition, such as `statelm--qwen3-8b--context128k`; do not
add generic `evaluation`, `experiment`, `run`, or timestamp prefixes or suffixes.
Use stable filesystem-safe lowercase names.

`report.json` is the machine-readable aggregate for the complete experiment.
It records the effective configuration, dataset coverage, completion and
failure counts, aggregate scores, and aggregate behavioral metrics. Each sample
gets one directory under `samples/`. Keep the completed interaction trace in
`final_trajectory.json`. Each `trajectory_<num>.json` is one complete LLM-call
transition, using zero-based, monotonically increasing numbers. It must record
the exact request context before the call, the model response, the tool action
and full observation when present, context-management state before and after
the action, and the exact resulting context. The resulting context of one
completed transition must match the initial context of the next call. This is
especially important for context-management actions: the record must make
deletion, note, retrieval, and other prompt changes directly inspectable rather
than reducing the trajectory to an isolated action-observation pair.

Write the initial request before invoking the model, then complete the same
snapshot atomically after the response and action. This preserves the input of
a failed or interrupted call. Keep the sample's final answer, status, score,
and per-sample metrics in `result.json`. When retrying a failed or interrupted
sample, move its prior primary artifacts under
`samples/<sample-id>/attempts/attempt_<num>/` and start a clean primary
trajectory; never concatenate separate agent sessions or discard the failed
attempt. Supporting artifacts that belong only to that sample may be stored in
the same sample directory. Do not mix per-sample files, aggregate reports, and
unrelated runs in one directory.

Operational stdout/stderr logs remain under `$HOME/logs`; models, datasets, and
download caches may remain in their dedicated external locations. These are
not experiment results. Generated results normally remain untracked by Git,
but their project-relative layout must be stable so `fetch-blue.sh` can mirror
them to the same location in the controlled vault.

Record experiment metrics in `report.json` and each sample's `result.json`, not
only in terminal or service logs. Agent experiments must include API-call and
round counts, tool-call counts, failure state, effective configuration, and
token usage where the backend provides it. Token metrics should include
per-call and aggregate prompt, completion, and total tokens, plus the maximum
prompt size observed during the trajectory.
