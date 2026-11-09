# Student-ability difficulty-v1 replay (2026-11-09)

This directory is a fresh replay of the archived `difficulty-v1` experiment for the
student-ability report. It does not overwrite
`data/analysis/experiments/difficulty-v1/`.

## Command

From `backend/`:

```powershell
python -m scripts.experiment_ability_difficulty --output ../data/analysis/experiments/replay-2026-11-09
```

Environment: Python 3.11.9, Windows 10 IoT Enterprise LTSC 2021
(`Windows-10-10.0.19044-SP0`). The script uses only the standard library and the
shipped pure optimizer. It opens no database and makes no network request.

## Receipt

- 72 D1 validation fits and 36 independently selected D0 validation fits.
- 192 final task × dataset × model evaluations; 144 include an optimizer.
- All 144 final optimizer fits converged; maximum 134/180 coordinate sweeps.
- Total wall time 93.11 s. D1 mean 1.19 s per fit-and-evaluate; B0 mean 0.0117 s.
- Frozen D1 parameters: `learner_l2=0.05`, `item_l2=0.3`,
  `difficulty_scale=0.75`, `max_iterations=180`, `tolerance=1e-6`,
  `calibrate_items=true`. D0 independently selected `learner_l2=0.5`.
- See `execution.json` for the machine-readable receipt.

## Comparison with the archived run

`protocol.json` is equal to the archived protocol after removing `created_utc`.
The source and core SHA-256 values match the archived protocol. Across all 192
final evaluations:

- RMSE, MAE, loss and iteration counts are bit-for-bit equal.
- A few auxiliary aggregates (binned calibration gap, simulated parameter
  correlations) differ by at most `2.22e-16`.
- Wall-clock values necessarily differ.

The archived README states Python 3.12+; this replay used Python 3.11.9. The
headline results are therefore reproducible to display precision, while the
last-bit differences are documented rather than rounded away.

## Files

| File | Meaning |
|---|---|
| `protocol.json` | Frozen seeds, splits, grid and source/core hashes. |
| `selected-parameters.json` | Exact D1 parameters copied into product snapshots. |
| `validation.csv`, `d0-validation.csv` | All validation fits. |
| `per_repeat.csv`, `per_repeat.json` | All 192 final evaluations. |
| `summary.csv`, `summary.json` | Scenario means, paired differences and diagnostics. |
| `rmse_by_scenario.svg` | Chart written by the experiment. |
| `execution.json` | Replay receipt and comparison with the archive. |
| `worked-example-output.json` | Output of the B0 same-code/two-assignment example. |
| `worked-example.log` | Assertion result for the worked example. |
| `replay-2026-11-09-run.log` (parent) | Captured CLI output. |

The worked example is produced by
`backend/scripts/check_ability_worked_example.py`; it uses the real
`ability_b0.analyze` function on a synthetic input. It demonstrates that two
assignments reusing problem code `P-001` remain two independent item instances,
and that missing or unsubmitted evidence stays `null` rather than becoming zero.

All learners and grades here are synthetic. These results support statements
about the controlled simulation only, not real-student validity.
