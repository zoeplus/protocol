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
