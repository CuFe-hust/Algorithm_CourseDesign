# Difficulty-Aware Assessment Implementation Plan

> For agentic workers: executing-plans for integration; independent bounded model/experiment/UI tasks. User explicitly delegates final design and acceptance.

**Goal:** Implement and honestly evaluate difficulty-aware chapter modeling, then deliver persisted demo alongside B0.
**Architecture:** Dedicated pure optimizer + input wrapper; versioned auxiliary plugin/pipeline; existing frozen tasks and authenticated projections; independent synthetic experiment harness.
**Tech Stack:** Python stdlib/Pydantic/SQLAlchemy/PostgreSQL; Vue/TS/SVG; plotting via bundled runtime if needed.
**Spec:** docs/design/analysis/student-ability-difficulty-model.md

## Global Constraints
- Preserve uncommitted B0 delivery and legacy15slot catalog; no destructive operations or credential changes.
- Keep partial grades, native11chapters, no unassigned imputation, no assignmenttotal.
- Deterministic positive regularization, parameters frozen, stable0/1/endpoints; no posterior/CI claim.
- Validation/test seed isolation; include loss cases; do not manufacture evidence.

## Review Focus
- Identical grade/different difficulty; model reflects calibrated anchors without unbounded parameters.
- Empty/sparse/all0/all1; hidden/noevidence status preserved.
- No heldout responses in fitting/calibration; chronological/history leakage avoided.
- Formal vs synthetic and student identity isolation unchanged.
- B0 vs D1 numeric semantics explicit; don't compare scores as same target.

### Task 1: Pure model
- [x] Failing tests for stable fitting/prediction/ordering/positivepenalties/no mutation.
- [x] Implement deterministic regularized fractional-logit optimizer and dedicated contracts/adapter.
- [x] Verify core tests, finite loss/convergence and exact reproducibility.
### Task 2: Independent experiments
- [x] Generator + leakage-safe split + B0/D0/D1/fixedbaseline.
- [x] Choose hyperparameters on validation only; run independent final seeds across stress scenarios.
- [x] Save results, figures and factual report, including regression cases.
### Task 3: Task/API/UI integration
- [x] Integration tests red then register auxiliaryD1, frozen wrapper and demo fixtures.
- [x] Preserve formal no-input wait; self-only projection; show B0 comparisons and optional process evidence.
- [x] Vue switch/semantics/tests and build.
### Task 4: Delivery
- [x] Review/fix, broad and focused tests, liveHTTP/browserchecks.
- [x] Run persisted D1 meeting demo, record evidence and design/experiment docs.

## Execution receipt

2026-10-29: model/experiments/panel implemented with bounded independent tasks; integration owner ran tests, actualHTTP and browser checks. Independent review found and fixed two edgecases via red/green regressions. Sourcehashes and all192rawmetrics independently audited. No test-driven parameter retuning. Plotting dependencies installed only into ignored .logs/plot-runtime, no app dependency added. No migration or credentials reset. Work remains local/uncommitted.
