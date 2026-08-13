# Reusable Quantitative Analysis Toolkit

This directory is a copy-and-adapt reference for deterministic analysis of
agent experiments recorded under the contract in
[`../QUANTITATIVE_ANALYSIS.md`](../QUANTITATIVE_ANALYSIS.md). It is deliberately
not a plugin and projects must not import it across repository boundaries at
runtime. Copy `src/`, the needed CLI adapters from `scripts/`, and their tests
into the project that owns the results.

The toolkit excludes all LLM-judge code. It reads raw result artifacts without
changing them and atomically writes derivatives to an `analysis/` directory.

## Included capabilities

`src/experiment_analysis.py` provides a read-only analysis API and a separate
writer. It derives:

- coverage, status, score, completion, strict end-to-end, and Wilson interval
  statistics with explicit denominators;
- failure categories and checks against aggregate recorder metrics;
- sample, tool, call, token, latency, and score-conditioned distributions;
- trajectory-index and adjacent-context integrity diagnostics;
- per-call context size and tool-colored context-growth/reduction charts;
- optional theoretical token-prefix KV retention using the experiment's exact
  tokenizer and chat template.

`src/tool_neighborhood_analysis.py` performs a fast second-stage analysis from
the generated `tool_calls.csv`. For any selected tool it reports exact
within-sample `t-1`, `(t-2, t-1)`, and `t+1` neighbors, consecutive target-tool
runs, spacing distributions, event rows, and pie-chart SVGs. It does not reread
trajectories or repeat tokenizer work.

## Copy and run

From this directory, a compatible experiment can be analyzed directly:

```bash
python scripts/analyze_experiment.py /path/to/results/benchmark/method--model
```

The input needs `samples/<sample-id>/result.json` and numbered trajectory JSON
files. `report.json` is recommended for source reconciliation and configuration
capture. Outputs default to `<experiment>/analysis/`:

```text
summary.json
samples.csv
tools.csv
tool_calls.csv
context_evolution.csv
context_evolution.svg
cache_transitions.csv
report.md
```

Common optional conventions are explicit rather than baked into the toolkit:

```bash
python scripts/analyze_experiment.py EXPERIMENT \
  --terminal-tool finish \
  --parse-leading-option \
  --context-samples 8 \
  --progress-every 10
```

Prefix-retention analysis additionally requires Transformers and the exact
local tokenizer revision used by generation:

```bash
python scripts/analyze_experiment.py EXPERIMENT \
  --tokenizer-path /path/to/frozen-tokenizer
```

Then analyze any target tool without rerunning the main analysis:

```bash
python scripts/analyze_tool_neighborhoods.py \
  EXPERIMENT/analysis/tool_calls.csv \
  --target-tool deleteContext
```

The default output is
`EXPERIMENT/analysis/tool_neighborhoods/<target-tool>/` and contains
`summary.json`, `events.csv`, `report.md`, and predecessor pie charts.

## Library adaptation

Project code can import the implementation after copying it locally:

```python
from src.experiment_analysis import AnalysisProfile, analyze_experiment, write_analysis

analysis = analyze_experiment(
    experiment_dir,
    profile=AnalysisProfile(terminal_tool="finish"),
)
write_analysis(analysis)
```

The core module has no third-party dependency. Token-prefix analysis accepts a
project-supplied `context_tokenizer(messages, tools, add_generation_prompt)`
callback, so frameworks can bind their exact renderer without depending on
Transformers. Keep model-, benchmark-, prompt-, answer-format-, and tool-name
assumptions in the project CLI or profile rather than the shared source.

## Interpretation rules

- Treat raw trajectories and results as immutable; derived outputs are
  replaceable snapshots.
- Record source counts and analysis time, especially for incomplete runs.
- Separate completed-only accuracy from strict end-to-end correctness.
- Validate experimental configuration before any cross-run comparison.
- Treat tool/score relationships as associations, not causal effects.
- Call token-prefix retention theoretical. The token-weighted rate estimates
  the fraction of prior KV entries retained across all eligible tokens; the
  unweighted mean describes the typical transition. Neither measures actual
  server cache hits, block alignment, eviction, or routing.
- Keep sequence analysis within sample boundaries and require exact adjacent
  trajectory indices; do not bridge missing calls.

## Verification

Run the dependency-free tests from this directory:

```bash
python -m unittest discover -s tests -v
```
