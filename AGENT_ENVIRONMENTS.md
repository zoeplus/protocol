# Reusable Agent Environments

This file is the entry point for reproducible agent environments in the
controlled vault. It stays brief: detailed introductions, configuration,
verification, and reuse boundaries live under `agent_environments/`.

The directory contains documentation and hooks, not copies of every
environment's source code. The owning project remains authoritative for
dependencies, setup scripts, runtime configuration, and compatibility fixes.

## Index

| Environment | Capability | Guide | Owner |
|---|---|---|---|
| StateLM agent environment (Elasticsearch BM25) | Long-document agent runtime with local BM25 retrieval and context-management tools | [`agent_environments/statelm_elasticsearch_bm25/`](agent_environments/statelm_elasticsearch_bm25/README.md) | `StateLM/` |

## Adding an environment

Create `agent_environments/<environment-id>/README.md` and add one row above.
The guide should identify:

- the environment's capability and reuse boundary;
- authoritative project-owned setup, configuration, and lifecycle hooks;
- verified versions and external system requirements;
- configuration and verification steps;
- what a consuming agent must implement rather than assume.

Keep executable environment changes in the owning project. Update its guide
and this index in the same stage when hooks or stable capabilities change.

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
- every stable deviation introduced during reproduction, including the changed
  package version, reason, and compatibility evidence;
- verification commands and the observed success criteria, such as imports,
  `pip check`, CUDA visibility, extension loading, and a minimal smoke test;
- known limitations, optional components, and any step that must be performed
  manually because it is large, privileged, or network-sensitive.

Preserve upstream environment files when they are useful evidence. Do not
silently overwrite the original configuration with a locally repaired one.
Add a clearly named reproducible configuration such as `environment-[project name].yml`,
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
