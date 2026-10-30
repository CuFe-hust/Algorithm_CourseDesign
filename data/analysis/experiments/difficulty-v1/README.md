# Difficulty-v1 synthetic experiment receipt

All learners and grades are generated, never imported from course records. The independent unit is one generated dataset, with six final dataset seeds per scenario. Read the complete interpretation and failure cases in [the report](../../../../docs/design/analysis/difficulty-experiments.md).

From the project root, reproduce the experiment with Python 3.12+ and the existing project environment:

```powershell
Set-Location backend
../.venv/Scripts/python.exe -m scripts.experiment_ability_difficulty
```

The script uses only the Python standard library and the shipped pure optimizer. It opens no database, sends no network requests, and writes this directory by default. Do not rerun against real student data by replacing identifiers; the generator is deliberately synthetic.

The exact default evaluation is 80 learners × 66 items × 11 chapters, six stress scenarios, six fresh final seeds per scenario, and a separate complete-item holdout for two scenarios. An explicit `--students` flag is available for runtime checks; changing it produces a different experiment and rewrites the protocol, so use `--output PATH` to preserve this receipt.

| File | Meaning |
|---|---|
| `protocol.json` | Validation/final seeds, generator and splits, full hypergrid, choice objective, optimizer budget, selected D1 and independently selected D0 prior, source SHA-256 hashes. Frozen before the final loop. |
| `selected-parameters.json` | Exact flat D1 parameters read by the persisted demonstration. These are copied into each new input snapshot. |
| `validation.csv` | All 72 D1 validation fits, including every candidate and scenario. |
| `d0-validation.csv` | All 36 D0 validation fits across its independent learner-penalty candidates. |
| `per_repeat.csv`, `per_repeat.json` | All 192 final task × dataset × model evaluations. `converged=null` applies to 48 B0 evaluations with no optimizer. |
| `summary.csv`, `summary.json` | Means, between-dataset SD, paired RMSE/MAE changes, win counts, calibration and simulated parameter diagnostics. |
| `rmse_by_scenario.svg` | Reproducible scientific chart written by the experiment: explicit axes, mean ± one dataset SD, all six scenarios. |
| `rmse_by_scenario.png` | SVG rendered at 2× resolution with the bundled Sharp library and visually inspected. It is a preview, not a separate plotting implementation. |
| `execution.json` | Receipt copied from successful CLI output: 99.26 s, 144 final optimizer fits all converged, maximum 134/180 sweeps. This receipt is not rewritten by the harness. |

The final configuration is `learner_l2=0.05`, `item_l2=0.3`, `difficulty_scale=0.75`, `max_iterations=180`, `tolerance=1e-6`, `calibrate_items=true`. D0 independently selected `learner_l2=0.5`. Fixed shares D1's parameters with item calibration disabled; it is an ablation, not separately tuned.

In the no-difficulty scenario D1 is worse than B0 in all six repeats (RMSE 0.13903 vs 0.13595). On new items with noisy teacher labels D1 wins only four of six repeats. These negative findings remain in every raw and summary output. Strong results on observed items cannot establish calibration for entirely new items or validity for real students.

To regenerate the optional PNG from its SVG without installing a project dependency, use a system SVG renderer or the bundled Node.js `sharp` package. Both SVG and PNG use the same axes, positions and labels. The figure's error bars are Monte Carlo spread, not model confidence intervals.

## Additional publication figure

`difficulty-model-validation.png` (3840×2160) and same-name SVG include known-item and entirely-unseen-item tasks. They are drawn by `scripts/plot_ability_experiments.py` using Matplotlib from frozen summary.json, without refitting. Matplotlib is optional offline tooling, installed locally outside the product dependencies. Original single-panel SVG/PNG remain for comparison.
