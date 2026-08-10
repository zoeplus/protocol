# RAOM server operations

This directory is the canonical, machine-independent home for the blue-server
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

Do not use `sudo` directly. The operator has sudo access even when the agent
does not. If a system command is missing, ask the operator to install its
normal system package first (for example, `sudo apt install rsync`) instead of
installing the command into Conda or creating a workaround. Use Conda only for
software that belongs in a project environment.

## Progress control

Keep both this `server` repository and the active controlled vault under
stage-by-stage Git control. Check `git status` before starting work, make a
scoped commit after each verified stage, and do not accumulate unrelated
changes into one commit. Start the next stage only when the current state is
understood and recoverable. Synchronize only committed revisions, and verify
that local and remote resolve to the intended commit. Never commit secrets,
downloaded artifacts, logs, or generated results.

## Environment configuration integrity

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
- every deviation introduced during reproduction, including the changed
  package version, reason, compatibility evidence, and date or revision;
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

Keep documentation and machine-readable environment files synchronized in the
same scoped Git commit. After changing the live environment, update these
artifacts immediately and verify them before starting the next experiment.
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

Run the project's linked `./fetch-blue.sh` to copy the remote project's
`results/` into a timestamped local snapshot. Set `BLUE_RESULTS_PATH` when the
project uses another relative results directory. Set `BLUE_LOG_PATTERN` (for
example, `statelm-*`) to fetch matching files from `~/logs`; logs are skipped
when it is unset. This is a one-way fetch from blue to the local machine and
does not delete remote files.

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
