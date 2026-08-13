# Server Principles

This directory is the canonical, machine-independent home for the server
(typically named blue) transport helper templates. Future agents should inspect
this file before touching the remote, then read the document relevant to the
task.

## Documentation map

| Task | Required document |
|---|---|
| Source synchronization, result transfer, or vault layout | [`PROJECT_SYNC.md`](PROJECT_SYNC.md) |
| Long-running services, evaluations, process control, or launcher variables | [`LAUNCHER_PROTOCOL.md`](LAUNCHER_PROTOCOL.md) |
| Package mirrors, downloads, or large installations | [`DOWNLOADS.md`](DOWNLOADS.md) |
| Agent environment setup or reuse | [`AGENT_ENVIRONMENTS.md`](AGENT_ENVIRONMENTS.md) |
| Experiment results, trajectories, metrics, or analysis | [`QUANTITATIVE_ANALYSIS.md`](QUANTITATIVE_ANALYSIS.md) |

Read only the relevant focused documents unless a task crosses their
boundaries. The operating-efficiency and progress-control rules below apply to
all work.

Reusable reference implementations live beside their governing document:
`result_recorder.py` covers capture, and
[`quantitative_analysis/`](quantitative_analysis/README.md) covers deterministic
derived analysis. Both must be copied and adapted into the owning project, not
imported across repository boundaries.

Before creating or renaming any launcher, check the filename routine in
[`LAUNCHER_PROTOCOL.md`](LAUNCHER_PROTOCOL.md). A public experiment entrypoint
and an internal implementation layer must not use the same naming form.

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
