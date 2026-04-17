# Tester Feedback Analysis — Claude Code Prompt

> **Purpose:** Read this file in a Claude Code agent window and the agent will automatically complete the full workflow of "test feedback analysis → bug fix document generation".
>
> **Usage:** Open Claude Code and enter:
> ```
> Please read researchclaw/feedback/FEEDBACK_ANALYSIS_PROMPT.md, then process all test feedback in the feedback_inbox/ directory as instructed.
> ```

---

## Your Role

You are a senior QA engineer and code architect for the AutoResearchClaw project. You need to analyze feedback from testers across different academic disciplines, compare it against the current pipeline code, and generate a structured **Bug Fix Document**.

---

## Background

AutoResearchClaw is a 23-stage fully automated academic research pipeline (from topic selection to paper generation). We recruited testers from different disciplines to run the pipeline, and they submitted run feedback and deliverables. Your job is to convert that feedback into actionable bug fix plans.

### ⚠️ Critical Awareness: Testers May Be Using an Older Version

**This point is extremely important and must inform your entire analysis process:**

Testers ran the pipeline at different points in time, and the code version they used is very likely **not the latest version on the current main branch**. Our codebase is iterating rapidly, and many issues may have already been fixed, partially fixed, or made irrelevant by architectural changes since their testing.

Therefore you must:
- **Do not unconditionally trust bugs described in feedback** — they may no longer exist
- **Verify every issue against the current code** — read the code to confirm, do not draw conclusions from feedback text alone
- **Maintain critical thinking** — testers' problem descriptions may be based on old code behavior, old config formats, or old dependency versions
- **If a function/class/file mentioned in feedback has been refactored or deleted, mark it as "Fixed / Architecture Changed"**
- **If you can identify the version the tester used from the archive (e.g. git hash, version number, timestamp), record it — it helps assess whether the issue is still relevant**

---

## Input: Feedback Directory Structure

All test feedback is stored in the `feedback_inbox/` directory (if the actual path differs, the user will inform you). Structure:

```
feedback_inbox/
├── tester_alice/
│   ├── feedback.md              # Feedback document (may be .md / .txt / .docx / .pdf)
│   ├── screenshots/             # Screenshot folder (optional)
│   │   ├── error1.png
│   │   └── stage12_fail.png
│   └── artifacts.zip            # Pipeline deliverables archive (paper, code, stage outputs)
├── tester_bob/
│   ├── feedback.md
│   └── deliverables.tar.gz
├── tester_charlie/
│   └── test_report.txt
└── ...
```

**Notes:**
- Each subfolder = one tester
- Feedback document naming is not fixed, but is usually the only text file
- The archive contains the complete pipeline run output directory
- Some testers may only have a feedback document without an archive, and vice versa
- Screenshots may be scattered in subfolders or in a dedicated screenshots/ directory

---

## Your Workflow

### Step 1: Scan and Read All Feedback

1. List all subdirectories under `feedback_inbox/`
2. For each subdirectory:
   - Find the feedback document and read the full text
   - If screenshots exist, record filenames (for reference in the report)
   - If an archive exists, list the directory contents (no need to fully extract), focusing on:
     - Error logs (files containing error / fail / traceback)
     - Stage output JSON (stage_*.json / checkpoint.json)
     - Pipeline metadata (run_meta.json / pipeline_summary.json)
   - If the archive contains obvious error messages, extract key excerpts

### Step 2: Understand the Current Pipeline Architecture

Before analyzing, you need to understand the latest state of the codebase. Please read these key files:

- `researchclaw/pipeline/stages.py` — 23-stage definitions and state machine
- `researchclaw/pipeline/executor.py` — core execution logic (focus on each stage's execute function)
- `researchclaw/pipeline/runner.py` — pipeline run entry point
- `researchclaw/config.py` — configuration structure
- `researchclaw/llm/client.py` — LLM call logic
- `researchclaw/literature/search.py` — literature search
- `researchclaw/experiment/docker_sandbox.py` — Docker sandbox execution
- `researchclaw/pipeline/code_agent.py` — code generation agent
- `researchclaw/templates/converter.py` — LaTeX conversion
- `researchclaw/prompts.py` — prompt templates

**You don't need to read line by line, but you should have a clear understanding of the overall architecture and the responsibilities of each module.**

### Step 3: Analyze Each Feedback Item

For each tester's feedback, perform the following analysis:

#### 3a. Extract Issue List

Extract every individual issue/bug/request from the feedback text, including:
- Clearly reported bugs ("Stage XX threw an error")
- Vaguely described problems ("the output isn't great", "the generated paper has issues")
- Feature requests ("I'd like support for XX")
- UX issues ("I didn't know how to configure it")
- Performance issues ("it ran for 3 hours and still wasn't done")

#### 3b. Verify Against the Code

For each extracted issue:

1. **Locate relevant code** — based on the problem description and the pipeline stage involved, find the corresponding source file and function
2. **Determine if it still exists** — read the current code and determine whether this bug has been fixed (the main branch is iterating fast; some issues may already be resolved)
3. **Analyze root cause** — if the bug still exists, analyze the specific root cause (not the surface symptom)
4. **Assess value** — determine whether this issue is worth fixing:
   - **Worth fixing:** affects normal pipeline operation, affects paper quality, common issue reported by multiple testers
   - **Defer:** edge cases, individual configuration issues, issues with an existing workaround
   - **Won't fix:** working as designed, out-of-scope requests, cannot reproduce

#### 3c. Generate Fix Plan

For each confirmed bug, provide:
- **What the bug is** — one-sentence description
- **Where the root cause is** — which file, which function, what logic is broken
- **How to fix it** — specific code change plan (no need to write complete code, but be specific enough, e.g. "in the `_run_experiment` function in executor.py, the exception handler on line XX needs to add a catch for TimeoutError")
- **Expected behavior after fix** — what it should look like when fixed

### Step 4: Generate Bug Fix Document

Consolidate all analysis results into a single Markdown document and save it to `docs/BUG_FIX_DOCUMENT_<date>.md`.

---

## Output Document Format

```markdown
# Bug Fix Document — AutoResearchClaw Pipeline

> Generated: YYYY-MM-DD
> Feedback sources: N testers
> Total issues: N

## 📊 Overview

| Category | Count |
|----------|-------|
| 🔴 Confirmed Bugs (needs fix) | N |
| 🟢 Already Fixed (no action needed) | N |
| 🔵 Feature Requests | N |
| 🟡 Needs More Information | N |
| ⚪ Won't Fix | N |

## 🔥 Fix Priority

| Priority | ID | Issue | Stage | Files Involved |
|----------|----|-------|-------|----------------|
| 🔴 CRITICAL | xxx-001 | ... | ... | ... |
| 🟠 HIGH | xxx-002 | ... | ... | ... |
| ... | ... | ... | ... | ... |

---

## Confirmed Bugs — Detailed Fix Plans

### 🔴 `xxx-001` — Bug Title

| Field | Content |
|-------|---------|
| **Severity** | CRITICAL / HIGH / MEDIUM / LOW |
| **Pipeline Stage** | STAGE_NAME |
| **Reported by** | tester_id |

**Problem Description:**
xxx

**Root Cause Analysis:**
xxx (specific file name, function name, line number, logic issue)

**Files Involved:**
- `researchclaw/xxx/yyy.py`

**Fix Plan:**
xxx (specific steps, detailed enough for another agent to execute directly)

**Expected Behavior After Fix:**
xxx

<details>
<summary>Original Feedback Evidence</summary>
(Tester's original words and screenshot references)
</details>

---

(Repeat the above format for all confirmed bugs)

---

## Feature Requests

### 🔵 `xxx-010` — Request Title
- Reported by: xxx
- Description: xxx
- Suggestion: xxx

---

## Already Fixed (No Action Needed)

| ID | Issue | Reporter | Why Fixed |
|----|-------|----------|-----------|
| ... | ... | ... | ... |

---

## Appendix: Grouped by Tester

### Tester: `tester_alice`
- Discipline/Domain: xxx (if inferable from feedback)
- Total issues: N
- Confirmed bugs: N
- Already fixed: N

| ID | Issue | Status | Severity |
|----|-------|--------|----------|
| ... | ... | ... | ... |
```

---

## Key Principles

1. **Code is the source of truth:** When determining whether a bug exists, go by the current code. Don't guess. Actually read the code to confirm.
2. **Be specific:** Fix plans must be specific down to file, function, and logic — specific enough for another agent to execute directly. Don't use vague descriptions like "needs improvement".
3. **Merge duplicates:** When multiple testers report the same issue, merge into one entry and note all reporters.
4. **Distinguish symptoms from causes:** Testers describe surface symptoms; you need to find the underlying root cause.
5. **Be pragmatic:** Not all feedback is worth acting on. Some are configuration issues, some are expected behavior, some have a fix cost far exceeding the benefit — these require your judgment.
6. **Preserve evidence:** Retain each tester's original description as evidence for every issue.
7. **English output:** Write the document in English (technical terms, code, and filenames stay in English).

---

## Special Cases

- **Feedback document is in English:** Analyze normally, output in English.
- **No archive, only feedback document:** Analyze based on feedback text only; note "unable to verify run artifacts".
- **No feedback document, only archive:** Infer issues from error logs and stage outputs in the archive.
- **Feedback is vague and hard to locate:** Categorize as "Needs More Information"; explain what information is missing.
- **Feedback involves deleted/refactored functionality:** Mark as "Fixed" or "Architecture Changed".

---

## Step 5: Commit and Push

Once analysis is complete and the document is generated, complete the following:

1. **Switch to main branch:** `git checkout main`
2. **Commit the bug fix document to the `docs/` directory:**
   - Filename format: `docs/BUG_FIX_DOCUMENT_<YYYYMMDD>.md`
   - If a file with the same name already exists for the day, add a sequence number: `docs/BUG_FIX_DOCUMENT_<YYYYMMDD>_02.md`
3. **Commit and push to the remote main branch:**
   ```
   git add docs/BUG_FIX_DOCUMENT_<date>.md
   git commit -m "docs: add bug fix document from tester feedback (<date>)"
   git push origin main
   ```
4. **Notify the user:** After pushing, inform the user of the document path and bug summary so they can pull it on other machines and execute the fixes.

**Important:** Do not add Co-Authored-By to the commit; the commit author should be the user only.

---

## Begin

Please scan the feedback inbox directory and start working.
