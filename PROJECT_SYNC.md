# Project Synchronization

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
