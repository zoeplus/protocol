# Launcher Protocol

## Long-running jobs

Start jobs with a single process-group owner (`setsid --wait`) and redirect
stdout/stderr to `~/logs`. Record the PID and process group. To stop one job,
send `TERM` to the process group, then verify with `ps` and `nvidia-smi`:

```bash
kill -TERM -- -<process-group-id>
ps -eo pid,ppid,pgid,sid,stat,cmd | rg '<job marker>'
nvidia-smi
```

Avoid nested `nohup`, backgrounding SSH layers, or killing only the shell PID;
those patterns can leave multiprocessing CUDA children alive after the parent
appears stopped. If `nvidia-smi` reports `[Not Found]` PIDs, host-level
inspection or container restart by the administrator may be required.


## Long-running launcher script standard

Represent every service, evaluation, conversion, or other long-running task
with a committed project-local launcher instead of an ad hoc command. The
launcher is part of the reproducible experiment configuration and must expose
machine- or run-specific values through environment variables.

### Launcher filename protocol

Classify a script before naming it. Public entrypoints and internal delegation
layers use different prefixes so an operator can identify runnable experiment
conditions from a directory listing.

| Script role | Filename form | Example |
|---|---|---|
| Model service entrypoint | `serve_<model>.sh` | `serve_qwen3_8b.sh` |
| Public experiment entrypoint | `run_<benchmark>__<method>__<model>.sh` | `run_infinitebench__basic_tools__qwen3_8b.sh` |
| Internal shared implementation or benchmark adapter | `im_<purpose>.sh` | `im_infinitebench_evaluation.sh` |

Double underscores separate the benchmark, method, and model fields in public
experiment launchers. Single underscores remain part of one field, such as
`longmemeval_s`, `basic_tools`, or `qwen3_8b`. Keep every field explicit even
when values repeat: use `run_infinitebench__statelm__statelm_8b.sh`, not an
abbreviated name that hides whether `statelm` identifies the method or model.
Put a stable benchmark variant in the benchmark field when needed, for example
`run_niah_128k__statelm__statelm_8b.sh`.

An `im_` script is not an operator-facing experiment command. Public `run_`
wrappers set the condition-specific defaults and delegate to the relevant
`im_` implementation. Internal layers must not retain a `run_` name merely
because they can technically be invoked directly. Setup, download, inspection,
and synchronization utilities may retain their established functional verbs;
do not force them into this experiment-launcher routine.

Before committing a launcher change, list the scripts and verify that every
public condition has exactly one unambiguous `run_` entrypoint, every delegated
target exists, and no internal layer is presented as a public condition.

### Variable protocol

Use one meaning per variable name across launchers. Declare variables near the
top of the script in this order: derived script paths, executable environment,
input/model configuration, experiment configuration, runtime resources, and
job lifecycle. Do not use several aliases for the same value in one script.

| Variable            | Meaning                                                                           | Rule                                                                                                                                       |
| ------------------- | --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `SCRIPT_DIR`        | Absolute directory containing the invoked script                                  | Derive from `BASH_SOURCE[0]`; never accept it from the environment or export it.                                                           |
| `SCRIPT_PATH`       | Absolute path of the invoked script when it reinvokes a worker mode               | Derive from `SCRIPT_DIR`; omit it when the script does not reinvoke itself.                                                                |
| `PROJECT_ROOT`      | Root of the project that owns the launcher                                        | Derive from `SCRIPT_DIR`; use this name instead of mixing `REPO_ROOT`, `PROJECT_DIR`, and similar aliases.                                 |
| `CONDA_BIN`         | Conda executable path                                                             | Operator-configurable; default to the verified installation path.                                                                          |
| `CONDA_ENV_NAME`    | Conda environment used to execute the job                                         | Operator-configurable. New scripts must not use the ambiguous `ENV_NAME`.                                                                  |
| `MODEL_PATH`        | Local checkpoint or model directory passed to the serving/runtime command         | This is a filesystem path, never a model label.                                                                                            |
| `SERVED_MODEL_NAME` | Model name exposed by an inference endpoint and used in API requests              | Keep it aligned with the endpoint configuration. Do not call it `MODEL_NAME`.                                                              |
| `BENCHMARK_ID`      | Stable filesystem-safe benchmark identity                                         | Used as the first project-local result level.                                                                                              |
| `METHOD_ID`         | Stable filesystem-safe agent or evaluation-method identity                        | Describes the method independently of the checkpoint.                                                                                      |
| `MODEL_ID`          | Stable filesystem-safe checkpoint/model identity                                  | Describes the model independently of its API alias.                                                                                        |
| `EXPERIMENT_ID`     | Stable project-local result identity, normally `<method>--<model>[--<condition>]` | Determines the result directory; it must not contain a timestamp or change merely to preserve logs.                                        |
| `JOB_NAME`          | Operational log/PID identity                                                      | Evaluation launchers set it to `EXPERIMENT_ID`; standalone services and setup jobs use an independent descriptive name.                    |
| `LOG_DIR`           | Directory for operational logs                                                    | Default to `${LOG_DIR:-$HOME/logs}` on the server. `LOG_DIR` is the optional host-level override; launcher logic uses `LOG_DIR` afterward. |
| `LOG_FILE`          | Log path for this invocation                                                      | Always derive as `$LOG_DIR/$JOB_NAME.log`; do not accept an independent override.                                                          |
| `PID_FILE`          | PID/PGID path for this invocation                                                 | Always derive as `$LOG_FILE.pid`; do not accept an independent override.                                                                   |

`EXPERIMENT_ID` and `CONDA_ENV_NAME` identify different things and must never be
substituted for one another. Evaluation launchers deliberately reuse
`EXPERIMENT_ID` as `JOB_NAME` so the result directory, log, and PID are easy to
match. Do not introduce a generic
`ENVIRONMENT_ID`: dependency/runtime environments use `CONDA_ENV_NAME`, while
an agent-environment catalog entry is documentation metadata rather than a
launcher variable. Prefer descriptive names such as `DATASET_PATH`,
`TOKENIZER_PATH`, `TOOL_CONFIG_PATH`, `RESULTS_ROOT`, `GPU_IDS`, and `PORT` over
generic `PATH`, `CONFIG`, `OUTPUT`, `DEVICE`, or `NAME`.

Suffixes carry consistent semantics: `_PATH` is one filesystem entry, `_DIR`
is a directory, `_FILE` is a specific file, `_ID` is a stable machine-facing
identity, and `_NAME` is a runtime/display name accepted by another system.
Use `_ROOT` only for the root of a structured tree. Do not store a path in an
`_ID` or `_NAME` variable, and do not use a display name as a result-directory
identity.

Component-specific settings must carry a stable prefix when their unqualified
meaning could collide, for example `ES_HOST`, `ES_PORT`, `SERVER_MAX_MODEL_LEN`,
or `VLLM_GPU_MEMORY_UTILIZATION`. A generic name is acceptable only when the
launcher has exactly one unambiguous instance of that concept. Shell-local
implementation variables use lowercase and `local`; uppercase is reserved for
configuration and derived launcher constants.

Wrapper launchers may set only the small set of defaults that differ, export
them, and then `exec` the shared launcher. Use the caller-preserving form
`export NAME="${NAME:-default}"`. Do not export `SCRIPT_DIR`, `SCRIPT_PATH`,
`PROJECT_ROOT`, `LOG_FILE`, or `PID_FILE`, and do not recompute lifecycle paths
in the wrapper. Evaluation wrappers set `export JOB_NAME="$EXPERIMENT_ID"`; do
not maintain a second experiment-job label. The shared launcher owns validation, worker mode, logging, PID
handling, and execution. When accepting a legacy variable such as `ENV_NAME`
during migration, translate it once at the boundary, document the alias, and
use only the canonical name internally.

A canonical declaration block is:

```bash
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_PATH="$SCRIPT_DIR/$(basename -- "${BASH_SOURCE[0]}")"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

CONDA_BIN="${CONDA_BIN:-/opt/conda/bin/conda}"
CONDA_ENV_NAME="${CONDA_ENV_NAME:-project-env}"
MODEL_PATH="${MODEL_PATH:-$HOME/models/model-name}"
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-model-name}"
BENCHMARK_ID="${BENCHMARK_ID:-benchmark-name}"
METHOD_ID="${METHOD_ID:-method-name}"
MODEL_ID="${MODEL_ID:-model-name}"
EXPERIMENT_ID="${EXPERIMENT_ID:-method--model-name}"

GPU_IDS="${GPU_IDS:-0}"
PORT="${PORT:-8080}"
LOG_DIR="${LOG_DIR:-$HOME/logs}"
JOB_NAME="$EXPERIMENT_ID"
LOG_FILE="$LOG_DIR/$JOB_NAME.log"
PID_FILE="$LOG_FILE.pid"
```

Logs always go to `$HOME/logs` by default on the server. Do not put runtime logs in
the project repository, and do not require the operator to set a log directory
for the normal case. A project may provide a documented environment-variable
override, but its fallback must remain `$HOME/logs`:

```bash
LOG_DIR="${LOG_DIR:-$HOME/logs}"
JOB_NAME="${JOB_NAME:-descriptive-job-name}"
LOG_FILE="$LOG_DIR/$JOB_NAME.log"
PID_FILE="$LOG_FILE.pid"
```

For evaluations, set `JOB_NAME="$EXPERIMENT_ID"`. For standalone services and
setup jobs, use a stable, descriptive `JOB_NAME` and allow an environment
override. Derive `LOG_FILE` and `PID_FILE` from that name, create `LOG_DIR`, and
reject a duplicate live job before launch.
The PID written after `setsid` is also the process-group ID used for inspection
and shutdown.

A minimal launcher should follow this structure:

```bash
#!/usr/bin/env bash
set -euo pipefail

LOG_DIR="${LOG_DIR:-$HOME/logs}"
JOB_NAME="${JOB_NAME:-descriptive-job-name}"
LOG_FILE="$LOG_DIR/$JOB_NAME.log"
PID_FILE="$LOG_FILE.pid"

mkdir -p "$LOG_DIR"
if [[ -s "$PID_FILE" ]] && kill -0 "$(<"$PID_FILE")" 2>/dev/null; then
    echo "Job is already running as process group $(<"$PID_FILE")" >&2
    exit 1
fi

# Perform cheap input, dependency, port, and service-health checks here.

setsid --wait <command> >"$LOG_FILE" 2>&1 &
pid=$!
echo "$pid" >"$PID_FILE"

echo "Job starting: PID/PGID=$pid"
echo "Log: $LOG_FILE"
echo "Monitor: tail -f '$LOG_FILE'"
echo "Stop: kill -TERM -- -$pid"
```

For a bounded run, place `timeout` inside the same `setsid` group and include a
grace period before forced termination:

```bash
setsid --wait timeout --verbose --signal=TERM --kill-after=120s 24h \
  <command> >"$LOG_FILE" 2>&1 &
```

Launcher scripts should also follow these rules:

- Use `set -euo pipefail` and quote paths and variable expansions.
- Resolve project-relative paths from the launcher's own directory, not the
  caller's current directory.
- Keep hostnames, usernames, ports, model paths, limits, and job names
  configurable through consistently named environment variables.
- Validate required files and local service health before allocating expensive
  resources or starting a long run.
- Use `/opt/conda/bin/conda run --no-capture-output -n <env>` when invoking a
  Conda environment so output reaches the designated log immediately.
- Redirect both stdout and stderr to the single `LOG_FILE`; do not split the
  diagnostic history across terminal output and repository files.
- Print the PID/PGID, log path, monitor command, and process-group stop command
  after launch.
- If a job is resumable, use a stable output path and make completed-unit
  detection explicit. Flush durable progress before marking a unit complete.
- After stopping or failure, inspect the whole process group and GPU users;
  never assume that disappearance of the launcher PID proves worker cleanup.
- Do not combine `setsid` with nested `nohup`, a second background wrapper, or
  per-worker PID files. One launcher owns one process group.
