# Paper Lantern Integration — Design & Implementation

## Overview

Paper Lantern is a Claude Code MCP tool that provides research-backed AI analysis: landscape surveys, approach comparisons, technique deep-dives, and feasibility assessments. This document describes how it is integrated into the AutoResearchClaw 23-stage pipeline.

---

## Problem Statement

AutoResearchClaw generates research hypotheses and experiment designs using only the LLM's parametric knowledge and the literature it collects. This means:
- Hypotheses may miss established approaches or reinvent the wheel
- Experiment designs may be infeasible given the user's hardware/timeline
- Code generation lacks implementation-level guidance (hyperparameters, failure modes)
- PROCEED/PIVOT decisions at Stage 15 lack external feasibility validation

Paper Lantern addresses all four gaps with evidence-backed analysis grounded in research literature.

---

## Architecture

The integration uses a **two-layer design**:

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: Claude Code SKILL.md (Orchestration)              │
│                                                             │
│  Pre-pipeline  → explore_approaches()                       │
│  Stage 9 gate  → compare_approaches() + check_feasibility() │
│  Pre-Stage 10  → deep_dive()                                │
│  Post-Stage 15 → check_feasibility() (on PIVOT)             │
│                                                             │
│  Writes artifact files to run directory                     │
└───────────────────────┬─────────────────────────────────────┘
                        │ artifact files (markdown)
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  Layer 2: Python Pipeline (Awareness)                       │
│                                                             │
│  Stage 8  reads  paper_lantern_landscape.md                 │
│  Stage 9  reads  paper_lantern_comparison.md                │
│                + paper_lantern_feasibility.md               │
│  Stage 10 reads  paper_lantern_deep_dive.md                 │
│  Stage 15 reads  paper_lantern_feasibility_s15.md           │
│                                                             │
│  Graceful degradation: skips if files absent                │
└─────────────────────────────────────────────────────────────┘
```

**Key design principle**: Paper Lantern is an MCP tool (only callable from Claude Code), so the Python pipeline cannot call it directly. Instead, the pipeline is made *aware* of Paper Lantern artifacts — it reads them if present and skips gracefully if not. This means the pipeline works identically with or without Paper Lantern.

---

## Artifact File Map

| File | Written by | Read at stage | Paper Lantern tool |
|------|-----------|--------------|-------------------|
| `paper_lantern_landscape.md` | SKILL.md (pre-pipeline) | Stage 8 (Hypothesis Gen) | `explore_approaches` |
| `paper_lantern_comparison.md` | SKILL.md (Stage 9 gate) | Stage 9 (Experiment Design) | `compare_approaches` |
| `paper_lantern_feasibility.md` | SKILL.md (Stage 9 gate) | Stage 9 (Experiment Design) | `check_feasibility` |
| `paper_lantern_deep_dive.md` | SKILL.md (pre-Stage 10) | Stage 10 (Code Generation) | `deep_dive` |
| `paper_lantern_feasibility_s15.md` | SKILL.md (post-Stage 15, on PIVOT) | Stage 15 (Research Decision) | `check_feasibility` |

All files live directly in the run directory: `artifacts/<run-id>/`.

---

## Files Changed

### 1. `researchclaw/config.py`

**Added**: `PaperLanternConfig` dataclass

```python
@dataclass(frozen=True)
class PaperLanternConfig:
    enabled: bool = False
    inject_at_stages: tuple[int, ...] = (8, 9, 10, 15)
    constraints: str = ""
```

**Added to `RCConfig`**:
```python
paper_lantern_bridge: PaperLanternConfig = field(default_factory=PaperLanternConfig)
```

**Added parsing** in `RCConfig.from_dict()` (after `calendar` parsing):
```python
paper_lantern_bridge=PaperLanternConfig(
    enabled=bool(paper_lantern_data.get("enabled", False)),
    inject_at_stages=tuple(int(s) for s in paper_lantern_data.get("inject_at_stages", (8, 9, 10, 15))),
    constraints=str(paper_lantern_data.get("constraints", "")),
),
```

---

### 2. `researchclaw/pipeline/_helpers.py`

**Added**: `_PL_ARTIFACT_MAP` and `_read_paper_lantern_context()` (after `_read_prior_artifact`)

```python
_PL_ARTIFACT_MAP: dict[int, str] = {
    8: "paper_lantern_landscape.md",
    9: "paper_lantern_comparison.md",
    10: "paper_lantern_deep_dive.md",
    15: "paper_lantern_feasibility_s15.md",
}

def _read_paper_lantern_context(run_dir: Path, stage_num: int) -> str:
    """Return Paper Lantern research intelligence for the given stage, or empty string."""
    fname = _PL_ARTIFACT_MAP.get(stage_num)
    if not fname:
        return ""
    content = _read_prior_artifact(run_dir, fname) or ""
    if stage_num == 9:
        feasibility = _read_prior_artifact(run_dir, "paper_lantern_feasibility.md") or ""
        if feasibility:
            content = (content + "\n\n" + feasibility).strip()
    if not content:
        return ""
    return f"\n\n## Paper Lantern Research Intelligence\n{content}\n"
```

---

### 3. `researchclaw/pipeline/stage_impls/_synthesis.py` (Stage 8)

**Added** after hypothesis generation, before HITL guidance:

```python
from researchclaw.pipeline._helpers import _read_paper_lantern_context
pl_context = _read_paper_lantern_context(run_dir, 8)
if pl_context and llm is not None:
    logger.info("Applying Paper Lantern landscape to hypotheses")
    try:
        resp = llm.chat([{"role": "user", "content": (
            f"Refine the following hypotheses using the research landscape survey below. "
            f"Ensure hypotheses address real gaps and use proven approaches where appropriate.\n\n"
            f"## Current Hypotheses\n{hypotheses_md}\n"
            f"{pl_context}\n"
            f"Produce improved hypotheses that are grounded in the research landscape."
        )}], max_tokens=4096)
        hypotheses_md = resp.content
    except Exception:
        logger.debug("Paper Lantern hypothesis refinement failed (non-blocking)")
```

**Effect**: After the initial multi-perspective debate generates hypotheses, Paper Lantern's landscape survey is used to refine them — grounding hypotheses in known research approaches and identified gaps.

---

### 4. `researchclaw/pipeline/stage_impls/_experiment_design.py` (Stage 9)

**Added** after building context preamble:

```python
from researchclaw.pipeline._helpers import _read_paper_lantern_context
preamble += _read_paper_lantern_context(run_dir, 9)
```

**Effect**: The experiment design prompt includes Paper Lantern's approach comparison and feasibility assessment, steering the LLM toward approaches validated as feasible for the user's hardware.

---

### 5. `researchclaw/pipeline/stage_impls/_code_generation.py` (Stage 10)

**Added** after reading `exp_plan`:

```python
from researchclaw.pipeline._helpers import _read_paper_lantern_context
_pl_deep_dive = _read_paper_lantern_context(run_dir, 10)
```

**Injected** into the legacy single-shot code generation prompt:

```python
pkg_hint=pkg_hint + "\n" + compute_budget + "\n" + extra_guidance + _pl_deep_dive,
```

**Effect**: The code generation prompt includes Paper Lantern's deep dive on the primary method — hyperparameters, implementation steps, calibration guidance, and known failure modes. This produces better experiment code.

---

### 6. `researchclaw/pipeline/stage_impls/_analysis.py` (Stage 15)

**Added** before LLM decision call:

```python
from researchclaw.pipeline._helpers import _read_paper_lantern_context
_pl_feasibility = _read_paper_lantern_context(run_dir, 15)
_user = sp.user + _degenerate_hint + _diagnosis_hint + _ablation_refine_hint + _pl_feasibility
```

**Effect**: The PROCEED/PIVOT/REFINE decision incorporates Paper Lantern's feasibility verdict on the proposed new direction (only relevant after a pivot cycle).

---

### 7. `config.arc.yaml`

**Added section**:
```yaml
paper_lantern_bridge:
  enabled: true
  inject_at_stages: [8, 9, 10, 15]
  constraints: "128GB unified memory, AMD Ryzen AI MAX+ 395, 40 GPU CUs (Radeon 8060S), 16-core CPU, Fedora Linux, local Ollama gemma4:31b"
```

---

### 8. `config.researchclaw.example.yaml`

**Added section** (disabled by default for new users):
```yaml
paper_lantern_bridge:
  enabled: false
  inject_at_stages: [8, 9, 10, 15]
  constraints: ""  # e.g. "16GB VRAM, A100 GPU, 48-hour time budget"
```

---

### 9. `.claude/skills/researchclaw/SKILL.md`

**Added**: `Paper Lantern Integration` section with step-by-step orchestration instructions for Claude Code agents. See the SKILL.md for the full instructions.

---

## Configuration Reference

```yaml
paper_lantern_bridge:
  enabled: true              # Master switch
  inject_at_stages: [8, 9, 10, 15]  # Which stages receive PL context
  constraints: "..."         # Hardware/timeline constraints for PL tools
```

The `constraints` field is passed to all Paper Lantern tool calls. Include:
- GPU/VRAM details
- RAM available
- Time budget
- OS and runtime environment

---

## Claude Code Orchestration Flow

When running via Claude Code with `paper_lantern_bridge.enabled: true`:

```
User: "research SLM tool calling"
         │
         ▼
[SKILL] 1. Call explore_approaches(topic, constraints)
           → write paper_lantern_landscape.md
         │
         ▼
[CLI]  researchclaw run --config config.arc.yaml --output artifacts/my-run
         │
         ▼  Stages 1-7 run automatically
         │
         ▼  Stage 8: reads landscape.md → refines hypotheses ✓
         │
         ▼  Stages continue to Stage 9 gate → pipeline PAUSES
         │
[SKILL] 2. Read hypotheses.md → extract top 3 approaches
           Call compare_approaches(approaches, topic, constraints)
           → write paper_lantern_comparison.md
           Call check_feasibility(exp_plan, constraints, topic)
           → write paper_lantern_feasibility.md
           Use PL verdict to approve/reject gate
         │
         ▼  [Gate approved]
         │
[SKILL] 3. Read exp_plan.yaml → identify primary method
           Call deep_dive(method, topic, constraints)
           → write paper_lantern_deep_dive.md
         │
         ▼  Stage 9 continues → Stage 10: reads deep_dive.md ✓
         │
         ▼  Stages 10-14 run automatically
         │
         ▼  Stage 15: reads feasibility_s15.md (if pivot) ✓
         │
         ▼  Stages 16-23 run automatically → paper exported
```

---

## Graceful Degradation

If Paper Lantern artifacts are absent (standalone CLI run, or PL not available):
- `_read_paper_lantern_context()` returns `""` — no effect on prompts
- All stages behave identically to pre-integration behavior
- No errors, no warnings

The integration is purely additive.

---

## Verification Steps

1. **Config parses correctly**:
   ```bash
   researchclaw doctor
   ```

2. **Artifact injection works** — manually place a test file and run in simulated mode:
   ```bash
   mkdir -p artifacts/test-run
   echo "## Approach Families\n- LoRA fine-tuning\n- Full fine-tuning" \
     > artifacts/test-run/paper_lantern_landscape.md
   researchclaw run --config config.arc.yaml --output artifacts/test-run \
     --from-stage HYPOTHESIS_GEN
   # Check stage-8/hypotheses.md for evidence of PL influence
   ```

3. **Graceful degradation** — run without any PL artifacts:
   ```bash
   researchclaw run --config config.arc.yaml --output artifacts/clean-run \
     --from-stage HYPOTHESIS_GEN
   # Should complete identically to pre-integration behavior
   ```

4. **End-to-end via Claude Code**:
   - Invoke the `researchclaw` skill
   - Verify Paper Lantern is called pre-pipeline and at Stage 9 gate
   - Confirm artifacts are written to run directory
   - Verify Stage 9 experiment design reflects PL comparison
