# RAOM server operations

This directory is the shared, machine-independent home for the blue-server
transport helpers. Future agents should inspect this file and the two scripts
before touching the remote.

## Required environment

The scripts read `BLUE_HOST`, `BLUE_PORT`, and `BLUE_DIR` from `.env.blue` or
the current shell. Keep `.env.blue` in the local secret/vault location; never
commit it here. Optional `BLUE_GIT_DIR` selects the remote bare repository.

Example, supplied by the operator from the controlled vault:

```bash
set -a
source /path/to/controlled-vault/.env.blue
set +a
```

## Git synchronization

Run `./sync-blue.sh` from the LightThinker checkout after committing local
source changes. It pushes the current branch to a bare Git repository on blue
and fast-forwards the blue working checkout. It refuses to overwrite a remote
directory that is not already a Git checkout.

Run `./fetch-blue.sh` to copy existing `general_reasoning/results/` and selected
LightThinker logs into a timestamped local snapshot. This is a one-way fetch
from blue to the local machine; it does not delete remote files.

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

Check free space before downloading. Keep Hugging Face `.cache` files until a
download completes; `.incomplete` files are resumable and should not be
deleted during a transient network failure. Download one large artifact at a
time unless bandwidth and disk headroom have been checked.
