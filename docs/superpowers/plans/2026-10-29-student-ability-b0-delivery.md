# Student Ability B0 Delivery Implementation Plan

> For agentic workers: use executing-plans for integration and independent bounded tasks for algorithm/UI. Steps use checkbox syntax.

**Goal:** Ship reproducible chapter-performance B0 through existing persisted task framework and a student panel, with labeled synthetic meeting demo.
**Architecture:** New ability-only contracts/core; new explicitly versioned B0 pipeline alongside legacy ability batches; frozen input and real deterministic B0 even for marked demo fixtures. Student projection filters self; formal and synthetic routes separate.
**Tech Stack:** Existing FastAPI/SQLAlchemy/PostgreSQL and Vue/TypeScript/SVG.
**Spec:** research-notes/student-ability-research/student-ability-b0-detailed-design.md (parent workspace); subsequent first-version-decisions override hidden unassigned axes and course accumulation.

## Global Constraints
- No assignment total/rating/CI. CHAPTER_WEIGHT only. 11 taxonomy chapters; backend always emits 11/student, UI hides NOT_COVERED.
- Programming+subjective included. Pending/unsubmitted never zero. Valid scored zero remains zero.
- Existing synthetic/legacy pipelines and historical hashes unchanged. No secrets/private roster.
- Synthetic fixture marked is_mock and provenance, persisted through worker; separate demo projection. Formal missing upstream returns structured wait.
- Clean primary checkout used for integrated local demonstration; no push/merge, no environment replacement.

## Review Focus
- Student with zero assigned pairs emits 11 NOT_COVERED via explicit student_keys.
- Duplicate/conflicting scores and state/value inconsistencies rejected.
- Demo artifacts cannot leak into formal panel or another student; course membership required.
- Zero and missing distinct; fewer than 3 visible chapters uses points/table, no fabricated polygon.
- Concurrent newer assignment-scoped batches cannot replace COURSE B0 view.

### Task 1: Core + versioned mapping
- [x] Failing tests for exact weighted score, mixed types, null/states, 11 chapters, duplicate validation.
- [x] Add ability_b0 contracts/core; copy validated taxonomy/mapping to data/analysis.
- [x] Targeted tests pass; pure function only.
### Task 2: Frozen task integration + projection
- [x] Tests for create DEMO B0, worker persistence, input hash, self projection, formal no-result, role isolation.
- [x] Add B0 pipeline/catalog entry and adapter without changing legacy ability; new create/projection routes.
- [x] Demo builds deterministic scores keyed to actual question mapping for existing demo students, not random estimates.
- [x] Run persisted DB fixture through actual service/worker and verify output.
### Task 3: Personal panel
- [x] Tests for visibility/zero/insufficient/empty and chart geometry.
- [x] Vue panel, SVG radar, evidence table, student route/navigation, explicit demo switch.
- [x] Typecheck/build/test.
### Task 4: Delivery
- [x] Focused backend+frontend regressions, broad backend suite and frontend build.
- [x] Independent review, resolve actionable issues.
- [x] Running local demonstration and meeting walkthrough/design documentation with limitations.

## Execution record

2026-10-29: B0/core and panel were implemented as independent bounded tasks; parent integrated persisted task/projection. Independent integration review found and resolved input inspector metadata and waiting-vs-failed status issues. All work remains local and uncommitted. No migration, roster, credential reset, or upstream scoring policy change. Full formal scoring domain remains a documented dependency.
