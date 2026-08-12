# Server Principles

This directory is the canonical, machine-independent home for the server (typically named blue)
transport helper templates. Future agents should inspect this file and the two
scripts before touching the remote.

## Operating efficiency

Prefer the shortest path to the requested deliverable. Do not perform
exploratory checks when repository evidence or the operator's stated
assumptions are sufficient. Limit verification to actions that prevent a
likely destructive change or incorrect result. Do not broaden documentation
scope. When the operator asks for commands or links, provide them immediately
and stop unless execution was explicitly requested. After one network timeout,
report it and use an alternative instead of repeatedly probing.

Reuse existing scripts before adding new ones. If two jobs differ only by
model paths, names, limits, prompts, endpoints, devices, or other configuration,
expose those differences through environment variables and use one shared
launcher. Add a separate script only when the execution flow, lifecycle, or
required validation materially differs. Do not copy a launcher merely to
provide different defaults; duplicated scripts increase drift and error risk.

Do not repeatedly assemble nested local-shell, SSH, command-substitution, and
`awk` quoting for routine checks. Put a repeatable check in the responsible
helper script and validate that script locally with `bash -n` and `shellcheck`
before using it remotely. When a one-off remote check is unavoidable, prefer a
plain SSH command or separate local and remote commands over multiple quoting
layers.

For operator-run downloads on a reliable local machine, provide the direct
links and commands by default. Do not write a download script unless the
download needs substantial retry or recovery logic, or covers enough files
that a script materially improves correctness and repeatability.

Do not use `sudo` directly. The operator has sudo access even when the agent
does not. Report a missing required system command to the operator; do not
invent an environment-level substitute that complicate the later operations.

Keep project documentation operational and concise. Record stable requirements,
current configuration, and verified commands only. Do not add dated inventory,
transient resource counts, investigation history, hypothetical fallback lists,
or commentary that does not help reproduce the main task. Verify a script in
its intended environment before documenting it as working.

## Progress control

Keep both this `server` repository and the active controlled vault under
stage-by-stage Git control. Check `git status` before starting work, make a
scoped commit after each verified stage, and do not accumulate unrelated
changes into one commit. Start the next stage only when the current state is
understood and recoverable. Synchronize only committed revisions, and verify
that local and remote resolve to the intended commit. Never commit secrets,
downloaded artifacts, logs, or generated results.

## Experiment results

See [`QUANTITATIVE_ANALYSIS.md`](QUANTITATIVE_ANALYSIS.md) for the
cross-project recording contract, integration boundary, and analysis pipeline.
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

## Environment configuration integrity

See [`AGENT_ENVIRONMENTS.md`](AGENT_ENVIRONMENTS.md) for the cross-project
index of reusable agent environments and their owning setup, service, and
verification hooks. The index points to project-owned implementations; it does
not duplicate those environments inside `server/`.

Treat every project environment as a reproducible experiment artifact. A new
container should be configurable from committed project documentation and
configuration files without rediscovering package versions, installation
order, mirrors, compatibility changes, or validation commands.

Document an environment change in the project's README before considering the
configuration stage complete. This applies to the initial environment and to
every later package install, removal, upgrade, downgrade, rebuild, or
agent-authored compatibility adjustment. The documentation must identify:

- the environment name, Python version, and relevant CUDA, compiler, driver,
  framework, and accelerator-library versions;
- the exact installation order and commands, including Conda channels, pip
  indexes, mirrors, build flags, and required operator-installed system
  packages;
- required environment-variable names and path conventions, while keeping
  secret values and machine-specific connection details out of Git;
- the upstream/original dependency configuration used as the starting point;
- every stable deviation introduced during reproduction, including the changed
  package version, reason, and compatibility evidence;
- verification commands and the observed success criteria, such as imports,
  `pip check`, CUDA visibility, extension loading, and a minimal smoke test;
- known limitations, optional components, and any step that must be performed
  manually because it is large, privileged, or network-sensitive.

Preserve upstream environment files when they are useful evidence. Do not
silently overwrite the original configuration with a locally repaired one.
Add a clearly named reproducible configuration such as `environment-blue.yml`,
requirements or constraints files, or a lock file when it materially improves
replayability, and explain its relationship to the upstream file in the
README. The README remains the entry point: it must state which file to use,
the command that consumes it, required follow-up steps, and which versions or
steps are intentionally different from upstream.

Verify the live behavior first, then keep documentation and machine-readable
environment files synchronized in the same scoped Git commit. After changing
the live environment, update these artifacts before starting the next
experiment.
Do not leave the only record of a successful configuration in shell history,
an agent conversation, a runtime log, or an uncommitted file.

## Required environment

Keep `server/` and each controlled project as sibling directories under the
same parent vault. Track project-local relative symbolic links to the canonical
helpers instead of copying their implementations:

```bash
cd /path/to/vault/project
ln -s ../server/sync-blue.sh sync-blue.sh
ln -s ../server/fetch-blue.sh fetch-blue.sh
git add sync-blue.sh fetch-blue.sh
```

Always invoke a helper through the project-local link, for example
`./sync-blue.sh`. The scripts intentionally derive `PROJECT_ROOT` from the path
used to invoke them, so running `/path/to/vault/server/sync-blue.sh` directly
would operate on the `server` repository instead. Git records the relative
links while the helper implementation remains canonical in `server/`; a helper
fix therefore does not need to be copied into every controlled project.

The links may be unresolved in a remote project checkout that does not also
contain a sibling `server/` checkout. This is acceptable because transport is
initiated from the local controlled vault, not from blue. Runtime launchers
needed on blue must remain real project files rather than links to `server/`.

The project-local helper links read `BLUE_HOST`, `BLUE_PORT`, and `BLUE_DIR` from
`.env.blue` in that project root or from the current shell. Keep `.env.blue`
local and ignored; never commit it. Optional `BLUE_GIT_DIR` selects the remote
bare repository.

Example, supplied by the operator from the controlled vault:

```bash
set -a
source /path/to/controlled-vault/.env.blue
set +a
```

## Tsinghua package mirrors

The following Tsinghua endpoints were checked from blue on 2026-08-08 and
returned HTTP 200:

```text
https://pypi.tuna.tsinghua.edu.cn/simple/
https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main/
https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/r/
https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge/
https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/pytorch/
```

Check the required endpoint from blue before starting a large installation:

```bash
curl -L --fail --silent --show-error --output /dev/null \
  --connect-timeout 8 --max-time 25 \
  --write-out '%{http_code} %{time_total}s %{speed_download}B/s\n' \
  https://pypi.tuna.tsinghua.edu.cn/simple/

curl -L --fail --silent --show-error --output /dev/null \
  --connect-timeout 8 --max-time 25 \
  --write-out '%{http_code} %{time_total}s %{speed_download}B/s\n' \
  https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main/linux-64/current_repodata.json
```

Prefer explicit per-command configuration instead of changing machine-wide
Conda or pip settings:

```bash
/opt/conda/bin/conda create -n <env-name> python=<version> pip -y \
  --override-channels \
  -c https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main

/opt/conda/bin/conda run --no-capture-output -n <env-name> \
  python -m pip install -r <requirements-file> \
  --index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

## Git synchronization

Run the project's linked `./sync-blue.sh` after committing local source
changes. It pushes the current branch to a bare Git repository on blue and
fast-forwards the blue working copy. It refuses to overwrite a remote
directory that is not already a Git working copy.

Run the project's linked `./fetch-blue.sh` with an explicit project-relative
remote path. There is deliberately no default result source, and a
`BLUE_RESULTS_PATH` stored in `.env.blue` is ignored. This prevents a stale
project path from silently fetching an unrelated result tree. Prefer CLI
arguments so separate non-exported shell assignments cannot be mistaken for
script configuration:

```bash
./fetch-blue.sh \
  --remote-path agentic_reasoning/results-inference/searchqa-eval-phase1 \
  --dest "$PWD/agentic_reasoning/results-inference/searchqa-eval-phase1" \
  --delete
```

`--dest` keeps remote and local project-relative paths identical. `--delete`
removes local entries that no longer exist remotely, but never deletes remote
files. `--log-pattern 'statelm-*'` additionally fetches matching files from
`~/logs`; logs are skipped when it is unset. The exported environment variables
`BLUE_RESULTS_PATH`, `BLUE_RESULTS_DEST`, `BLUE_FETCH_DELETE`, and
`BLUE_LOG_PATTERN` remain supported, but ordinary unexported assignments made
on earlier command lines are not visible to a child script. This is always a
one-way fetch from blue to the local machine.

After transferring results, `fetch-blue.sh` always performs a checksum-based
`rsync --dry-run --delete` comparison. It exits with an error and prints the
differences if the local destination is not an exact mirror of the remote
result tree. Do not repeat the comparison with an ad hoc SSH checksum command.

Do not use rsync in both directions for source code. Use Git for source and
`fetch-blue.sh` for results/logs.

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

### Variable protocol

Use one meaning per variable name across launchers. Declare variables near the
top of the script in this order: derived script paths, executable environment,
input/model configuration, experiment configuration, runtime resources, and
job lifecycle. Do not use several aliases for the same value in one script.

| Variable | Meaning | Rule |
|---|---|---|
| `SCRIPT_DIR` | Absolute directory containing the invoked script | Derive from `BASH_SOURCE[0]`; never accept it from the environment or export it. |
| `SCRIPT_PATH` | Absolute path of the invoked script when it reinvokes a worker mode | Derive from `SCRIPT_DIR`; omit it when the script does not reinvoke itself. |
| `PROJECT_ROOT` | Root of the project that owns the launcher | Derive from `SCRIPT_DIR`; use this name instead of mixing `REPO_ROOT`, `PROJECT_DIR`, and similar aliases. |
| `CONDA_BIN` | Conda executable path | Operator-configurable; default to the verified installation path. |
| `CONDA_ENV_NAME` | Conda environment used to execute the job | Operator-configurable. New scripts must not use the ambiguous `ENV_NAME`. |
| `MODEL_PATH` | Local checkpoint or model directory passed to the serving/runtime command | This is a filesystem path, never a model label. |
| `SERVED_MODEL_NAME` | Model name exposed by an inference endpoint and used in API requests | Keep it aligned with the endpoint configuration. Do not call it `MODEL_NAME`. |
| `BENCHMARK_ID` | Stable filesystem-safe benchmark identity | Used as the first project-local result level. |
| `METHOD_ID` | Stable filesystem-safe agent or evaluation-method identity | Describes the method independently of the checkpoint. |
| `MODEL_ID` | Stable filesystem-safe checkpoint/model identity | Describes the model independently of its API alias. |
| `EXPERIMENT_ID` | Stable project-local result identity, normally `<method>--<model>[--<condition>]` | Determines the result directory; it must not contain a timestamp or change merely to preserve logs. |
| `JOB_NAME` | One process/service invocation identity | Determines operational log and PID filenames; it may distinguish smoke, collection, or service jobs without changing `EXPERIMENT_ID`. |
| `LOG_DIR` | Directory for operational logs | Default to `${BLUE_LOG_DIR:-$HOME/logs}` on blue. `BLUE_LOG_DIR` is the optional host-level override; launcher logic uses `LOG_DIR` afterward. |
| `LOG_FILE` | Log path for this invocation | Always derive as `$LOG_DIR/$JOB_NAME.log`; do not accept an independent override. |
| `PID_FILE` | PID/PGID path for this invocation | Always derive as `$LOG_FILE.pid`; do not accept an independent override. |

`EXPERIMENT_ID`, `JOB_NAME`, and `CONDA_ENV_NAME` identify different things and
must never be substituted for one another. Do not introduce a generic
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
in the wrapper. The shared launcher owns validation, worker mode, logging, PID
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
LOG_DIR="${BLUE_LOG_DIR:-$HOME/logs}"
JOB_NAME="${JOB_NAME:-method-model-name-collect}"
LOG_FILE="$LOG_DIR/$JOB_NAME.log"
PID_FILE="$LOG_FILE.pid"
```

Logs always go to `$HOME/logs` by default on blue. Do not put runtime logs in
the project repository, and do not require the operator to set a log directory
for the normal case. A project may provide a documented environment-variable
override, but its fallback must remain `$HOME/logs`:

```bash
LOG_DIR="${BLUE_LOG_DIR:-$HOME/logs}"
JOB_NAME="${JOB_NAME:-descriptive-job-name}"
LOG_FILE="$LOG_DIR/$JOB_NAME.log"
PID_FILE="$LOG_FILE.pid"
```

Use a stable, descriptive `JOB_NAME` that identifies the service or experiment
configuration. Allow an environment override so independent runs can use
separate logs without editing the script. Derive `LOG_FILE` and `PID_FILE` from
that name, create `LOG_DIR`, and reject a duplicate live job before launch.
The PID written after `setsid` is also the process-group ID used for inspection
and shutdown.

A minimal launcher should follow this structure:

```bash
#!/usr/bin/env bash
set -euo pipefail

LOG_DIR="${BLUE_LOG_DIR:-$HOME/logs}"
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

## Large downloads

Agents must not start large downloads or long package installations. Prepare a
committed, project-local script and let the operator run it. The script itself
must contain the reproducible settings, mirror selection, retry behavior, log
redirection, and PID recording needed for the operation. Agent responses should
provide only the short script invocation and log-monitoring commands instead of
wrapping a long list of settings in an ad hoc shell command.

Check free space before downloading. Keep Hugging Face `.cache` files until a
download completes; `.incomplete` files are resumable and should not be
deleted during a transient network failure. Download one large artifact at a
time unless bandwidth and disk headroom have been checked.
