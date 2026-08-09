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

## Required environment

Copy both `sync-blue.sh` and `fetch-blue.sh` into the root of each controlled
project repository before using them. The scripts set `PROJECT_ROOT` to the
directory containing their own copied file, so invoking the canonical copies
from this `server` repository would operate on the wrong Git repository. Keep
each project's copies under Git control so synchronization behavior is part of
that project's reproducible configuration.

The copied scripts read `BLUE_HOST`, `BLUE_PORT`, and `BLUE_DIR` from
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

Run the project's copied `./sync-blue.sh` after committing local source
changes. It pushes the current branch to a bare Git repository on blue and
fast-forwards the blue working copy. It refuses to overwrite a remote
directory that is not already a Git working copy.

Run the project's copied `./fetch-blue.sh` to copy the remote project's
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
