---
name: researchclaw
description: Run the ResearchClaw autonomous research pipeline from a topic, config, and output directory.
---

# ResearchClaw — Autonomous Research Pipeline Skill

## Description

Run ResearchClaw's 23-stage autonomous research pipeline. Given a research topic, this skill orchestrates the entire research workflow: literature review → hypothesis generation → experiment design → code generation & execution → result analysis → paper writing → peer review → final export.

## Trigger Conditions

Activate this skill when the user:
- Asks to "research [topic]", "write a paper about [topic]", or "investigate [topic]"
- Wants to run an autonomous research pipeline
- Asks to generate a research paper from scratch
- Mentions "ResearchClaw" by name

## Instructions

### Prerequisites Check

1. Verify config file exists:
   ```bash
   ls config.yaml || ls config.researchclaw.example.yaml
   ```
2. If no `config.yaml`, create one from the example:
   ```bash
   cp config.researchclaw.example.yaml config.yaml
   ```
3. Ensure the user's LLM API key is configured in `config.yaml` under `llm.api_key` or via `llm.api_key_env` environment variable.

### Running the Pipeline

**Option A: CLI (recommended)**

```bash
researchclaw run --topic "Your research topic here" --auto-approve
```

Options:
- `--topic` / `-t`: Override the research topic from config
- `--config` / `-c`: Config file path (default: `config.yaml`)
- `--output` / `-o`: Output directory (default: `artifacts/rc-YYYYMMDD-HHMMSS-HASH/`)
- `--from-stage`: Resume from a specific stage (e.g., `PAPER_OUTLINE`)
- `--auto-approve`: Auto-approve gate stages (5, 9, 20) without human input

**Option B: Python API**

```python
from researchclaw.pipeline.runner import execute_pipeline
from researchclaw.config import RCConfig
from researchclaw.adapters import AdapterBundle
from pathlib import Path

config = RCConfig.load("config.yaml", check_paths=False)
results = execute_pipeline(
    run_dir=Path("artifacts/my-run"),
    run_id="research-001",
    config=config,
    adapters=AdapterBundle(),
    auto_approve_gates=True,
)

# Check results
for r in results:
    print(f"Stage {r.stage.name}: {r.status.value}")
```

**Option C: Iterative Pipeline (multi-round improvement)**

```python
from researchclaw.pipeline.runner import execute_iterative_pipeline

results = execute_iterative_pipeline(
    run_dir=Path("artifacts/my-run"),
    run_id="research-001",
    config=config,
    adapters=AdapterBundle(),
    max_iterations=3,
    convergence_rounds=2,
)
```

### Output Structure

After a successful run, the output directory contains:

```
artifacts/<run-id>/
├── stage-1/                # TOPIC_INIT outputs
├── stage-2/                # PROBLEM_DECOMPOSE outputs
├── ...
├── stage-10/
│   └── experiment.py       # Generated experiment code
├── stage-12/
│   └── runs/run-1.json     # Experiment execution results
├── stage-14/
│   ├── experiment_summary.json  # Aggregated metrics
│   └── results_table.tex        # LaTeX results table
├── stage-17/
│   └── paper_draft.md      # Full paper draft
├── stage-22/
│   └── charts/             # Generated visualizations
│       ├── metric_trajectory.png
│       └── experiment_comparison.png
└── pipeline_summary.json   # Overall pipeline status
```

### Experiment Modes

| Mode | Description | Config |
|------|-------------|--------|
| `simulated` | LLM generates synthetic results (no code execution) | `experiment.mode: simulated` |
| `sandbox` | Execute generated code locally via subprocess | `experiment.mode: sandbox` |
| `ssh_remote` | Execute on remote GPU server via SSH | `experiment.mode: ssh_remote` |

### Troubleshooting

- **Config validation error**: Run `researchclaw validate --config config.yaml`
- **LLM connection failure**: Check `llm.base_url` and API key
- **Sandbox execution failure**: Verify `experiment.sandbox.python_path` exists and has numpy installed
- **Gate rejection**: Use `--auto-approve` or manually approve at stages 5, 9, 20

### Paper Lantern Integration (Optional)

If `paper_lantern_bridge.enabled: true` in config and the Paper Lantern MCP tool is available, enrich the pipeline at key stages by calling Paper Lantern and writing result artifacts to the run directory **before** the pipeline reaches each stage.

Run the pipeline **without** `--auto-approve` so you can intercept gate stages:

```bash
researchclaw run --topic "..." --config config.arc.yaml --output artifacts/my-run
```

#### Pre-pipeline (before `researchclaw run`)

Call `explore_approaches` to survey the research landscape:
- Query: the research topic
- Constraints: value from `paper_lantern_bridge.constraints` in config
- Write the full response to `artifacts/my-run/paper_lantern_landscape.md`

The pipeline picks this up automatically at Stage 8 (Hypothesis Generation).

#### At Stage 9 Gate (EXPERIMENT_DESIGN)

When the pipeline pauses at the Stage 9 gate:
1. Read `hypotheses.md` from the run artifacts — extract top 2-3 proposed approaches
2. Call `compare_approaches` with those names, topic as context, hardware constraints
3. Read `exp_plan.yaml` from the run artifacts
4. Call `check_feasibility` with the experiment approach, constraints, and topic context
5. Write `compare_approaches` result to `artifacts/my-run/paper_lantern_comparison.md`
6. Write `check_feasibility` result to `artifacts/my-run/paper_lantern_feasibility.md`
7. Use the Paper Lantern verdict to inform gate decision:
   - **GO** → approve the gate
   - **PROTOTYPE** → approve with a note, or ask user
   - **RECONSIDER** → reject the gate (rolls back to Stage 8 to revise hypotheses)

#### Between Stage 9 and Stage 10 (before code generation)

After approving the Stage 9 gate:
1. Read `exp_plan.yaml` — identify the primary proposed method
2. Call `deep_dive` on that method with topic context and hardware constraints
3. Write result to `artifacts/my-run/paper_lantern_deep_dive.md`

The pipeline injects this implementation guide into Stage 10 (Code Generation).

#### After Stage 15 (Research Decision)

After Stage 15 completes:
1. Read `decision_structured.json` from the artifacts
2. If `decision` is `"pivot"`:
   - Call `check_feasibility` on the proposed new direction
   - Write result to `artifacts/my-run/paper_lantern_feasibility_s15.md`
   - This is injected in the next Stage 15 iteration

#### Writing artifact files

```bash
# Example: save Paper Lantern landscape result
cat > artifacts/my-run/paper_lantern_landscape.md << 'EOF'
<paper lantern response here>
EOF
```

## Tools Required

- File read/write (for config and artifacts)
- Bash (for CLI execution)
- Paper Lantern MCP (`mcp__claude_ai_Paper_Lantern__*`) for research intelligence (optional)
