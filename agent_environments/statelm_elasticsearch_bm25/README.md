# StateLM Agent Environment (Elasticsearch BM25)

## Purpose

This environment supports StateLM-style agent evaluation over long documents.
Its reusable retrieval component is a local Elasticsearch BM25 service used by
the `buildIndex` and `searchEngine` tools. Each evaluation item supplies the
document to index, so the service requires no separate corpus download.

The environment has three distinct layers:

1. The `statelm` Conda environment provides the model client, evaluation
   dependencies, Elasticsearch Python client, and optional vLLM serving stack.
2. Elasticsearch provides a user-space, CPU-only BM25 index service.
3. The StateLM project provides the tool schemas, indexing/search behavior,
   prompts, agent loop, and benchmark adapters.

Elasticsearch alone is not a complete agent environment. A different project
may reuse the service, but it must supply its own indexing lifecycle, query
mapping, tool interface, result recording, and evaluation runner.

## Authoritative hooks

Resolve these paths from the controlled vault root. If not clear, as the operator for help.

| Concern                                    | Hook                                                |
| ------------------------------------------ | --------------------------------------------------- |
| Environment overview and verified versions | `StateLM/README.md`, Setup                          |
| Python dependency pins                     | `StateLM/requirements_min.txt`                      |
| Conda environment setup                    | `StateLM/scripts/setup_inference_env.sh`            |
| Offline wheelhouse preparation             | `StateLM/scripts/download_inference_wheelhouse.sh`  |
| Elasticsearch procedure                    | `StateLM/elasticsearch_setup.md`                    |
| Elasticsearch archive preparation          | `StateLM/scripts/download_elasticsearch_archive.sh` |
| Elasticsearch installation                 | `StateLM/scripts/setup_elasticsearch.sh`            |
| Elasticsearch lifecycle                    | `StateLM/scripts/elasticsearch_service.sh`          |
| Elasticsearch runtime configuration        | `StateLM/config/elasticsearch/`                     |
| StateLM tool definitions                   | `StateLM/tools_and_prompt/statelm_tools.json`       |
| Example evaluation launcher                | `StateLM/scripts/run_vllm_infbench_statelm_8b.sh`   |

Inspect the owning project's README and Elasticsearch guide before executing a
hook. Do not reconstruct their commands from this guide when the committed
scripts already encode them.

## Verified configuration

The current project hooks define:

| Component                   | Configuration                                     |
| --------------------------- | ------------------------------------------------- |
| Conda environment           | `statelm`, Python 3.12.11                         |
| PyTorch                     | 2.6.0, CUDA 12.4 build                            |
| Transformers                | 4.55.3                                            |
| datasets                    | 4.0.0                                             |
| vLLM                        | 0.8.5.post1                                       |
| Elasticsearch Python client | 9.1.1                                             |
| Elasticsearch service       | 9.1.5 Linux x86_64 archive with bundled JDK       |
| Service endpoint            | `http://127.0.0.1:9200`                           |
| Elasticsearch heap          | 1 GB                                              |
| Accelerator requirement     | None for Elasticsearch; model serving is separate |

The Elasticsearch configuration is single-node, loopback-only, with security
and Elasticsearch machine learning disabled. It is an evaluation service, not
a network-exposed or production deployment.

## Configuration path

From the StateLM project root, prepare the Python environment:

```bash
CONDA_BIN=/opt/conda/bin/conda ENV_NAME=statelm \
  ./scripts/setup_inference_env.sh
```

On a machine with poor package connectivity, follow the wheelhouse path in the
StateLM README instead of changing dependency pins or global mirror settings.
Large archive or wheel downloads remain operator-run operations.

Prepare Elasticsearch only after its archive and checksum have been placed in
the paths required by `elasticsearch_setup.md`:

```bash
./scripts/setup_elasticsearch.sh
```

The setup script installs the service and project configuration but does not
start it. Start and verify it separately:

```bash
./scripts/elasticsearch_service.sh start
./scripts/elasticsearch_service.sh status
```

An evaluation using the BM25 tools must expose the local endpoint:

```bash
export ES_HOST="http://127.0.0.1:9200"
```

The existing StateLM evaluation launcher supplies this default. A consuming
project should make the endpoint configurable and keep it loopback-only.

## Verification contract

The Python setup is ready only when its script completes `pip check`, verifies
the pinned package versions, and confirms the expected CUDA visibility for any
model-serving work. Elasticsearch is ready only when both checks succeed:

```bash
./scripts/elasticsearch_service.sh status

ES_HOST=http://127.0.0.1:9200 \
  /opt/conda/bin/conda run --no-capture-output -n statelm \
  python -c 'from elasticsearch import Elasticsearch; print(Elasticsearch("http://127.0.0.1:9200").info()["version"]["number"])'
```

Before relying on this environment in a new agent framework, run one tool-level
smoke test that builds an index from a small document and retrieves a known
term. Service health alone does not verify the framework's tool adapter.

## Reuse boundary

Reuse the full StateLM environment when the evaluation needs its agent loop,
context-management tools, and BM25 search behavior. Reuse only the
Elasticsearch layer when another agent already has its own runtime and merely
needs a local lexical index. In the latter case, install the consuming
project's compatible Elasticsearch client separately and implement its adapter
inside that project.

Do not use this hook as evidence that an environment provides web search,
dense retrieval, a persistent benchmark corpus, or production Elasticsearch
security. Evaluations that do not enable `buildIndex` or `searchEngine`, such
as StateLM's search-free NIAH configuration, do not require the Elasticsearch
service.

Stop the service through its owning lifecycle hook when it is no longer needed:

```bash
./scripts/elasticsearch_service.sh stop
```

Runtime logs, PID files, installed services, indices, models, datasets, and
wheelhouses remain outside Git in the locations documented by StateLM. Only
the project-owned configuration and hooks are source-controlled.
