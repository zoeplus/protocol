# Project Synchronization

## Required environment

Keep `$PROT` and each controlled project as separate projects. Track project-local relative symbolic links to the canonical
helpers instead of copying their implementations:

```bash
cd /path/to/vault/project
ln -s $PROT/sync.sh sync.sh
ln -s $PROT/fetch.sh fetch.sh
git add sync.sh fetch.sh
```

Always invoke a helper through the project-local link, for example
`./sync.sh`. The scripts intentionally derive `PROJECT_ROOT` from the path
used to invoke them, so running `$PROT/sync.sh` directly
would operate on the `$PROT` repository instead. Git records the relative
links while the helper implementation remains canonical in `$PROT`; a helper
fix therefore does not need to be copied into every controlled project.

The links may be unresolved in a remote project checkout that does not also
contain a `$PROT` checkout. This is acceptable because transport is
initiated from the local controlled vault, not from the server. Runtime launchers
needed on the server must remain real project files rather than links to `$PROT`.

The project-local helper links read `HOST`, `PORT`, and `DIR` from
`.env` in that project root or from the current shell. Keep `.env`
local and ignored; never commit it (yet you can inspect it, it's no secret file, actually). 
Optional `GIT_DIR` selects the remote bare repository.

Example, supplied by the operator from the controlled vault:

```bash
set -a
source /path/to/controlled-vault/.env
set +a
```


## Synchronization

Run the project's linked `./sync.sh` after committing local source
changes. It pushes the current branch to a bare Git repository on the server and
fast-forwards the server working copy. It refuses to overwrite a remote
directory that is not already a Git working copy.

Run the project's linked `./fetch.sh` with an explicit project-relative
remote path. There is deliberately no default result source, and a
`RESULTS_PATH` stored in `.env` is ignored. This prevents a stale
project path from silently fetching an unrelated result tree. Prefer CLI
arguments so separate non-exported shell assignments cannot be mistaken for
script configuration:

```bash
./fetch.sh \
  --remote-path results/ \
  --dest "$PWD/results" \
  --delete
```

`--dest` keeps remote and local project-relative paths identical. `--delete`
removes local entries that no longer exist remotely, but never deletes remote
files. `--log-pattern 'statelm-*'` additionally fetches matching files from
`~/logs`; logs are skipped when it is unset. The exported environment variables
`RESULTS_PATH`, `RESULTS_DEST`, `FETCH_DELETE`, and
`LOG_PATTERN` remain supported, but ordinary unexported assignments made
on earlier command lines are not visible to a child script. This is always a
one-way fetch from server to the local machine.

Quote a glob in `--remote-path` so the remote shell expands it; every match is
then copied into `--dest` under its own name, which fetches several
same-prefix condition directories in one call:

```bash
./fetch.sh \
  --remote-path 'results/webshop/raom-consolidate--qwen3-32b*' \
  --dest "$PWD/results/webshop"
```

After transferring results, `fetch.sh` always performs a checksum-based
`rsync --dry-run --delete` comparison. It exits with an error and prints the
differences if the local destination is not an exact mirror of the remote
result tree. Do not repeat the comparison with an ad hoc SSH checksum command.

Do not use rsync in both directions for source code. Use Git for source and
`fetch.sh` for results/logs.
