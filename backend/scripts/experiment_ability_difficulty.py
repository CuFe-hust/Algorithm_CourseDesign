"""Reproducible synthetic stress tests, without database or scientific dependencies.

Run from backend: python -m scripts.experiment_ability_difficulty
Validation seeds select the frozen configuration before final seeds are generated.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import time


SCENARIOS = ('difficulty_signal', 'mislabeled_teacher', 'sparse', 'mnar',
             'no_difficulty', 'nonlinear_mismatch')
VALIDATION_SEEDS = (1103, 2207)
FINAL_SEEDS = (31001, 32003, 33013, 34019, 35023, 36037)
GRID = (
    {'learner_l2': .05, 'item_l2': .3, 'difficulty_scale': .75},
    {'learner_l2': .15, 'item_l2': 1., 'difficulty_scale': .75},
    {'learner_l2': .5, 'item_l2': 4., 'difficulty_scale': .75},
    {'learner_l2': .15, 'item_l2': 4., 'difficulty_scale': .75},
    {'learner_l2': .15, 'item_l2': 1., 'difficulty_scale': .4},
    {'learner_l2': .5, 'item_l2': 1., 'difficulty_scale': .4},
)
OPTIMIZER = {'max_iterations': 180, 'tolerance': 1e-6}


@dataclass(frozen=True)
class ItemSpec:
    key: str
    weights: dict[str, float]
    difficulty: int


@dataclass(frozen=True)
class Row:
    student: str
    item: str
    score: float


@dataclass(frozen=True)
class Dataset:
    chapters: tuple[str, ...]
    items: tuple[ItemSpec, ...]
    rows: tuple[Row, ...]
    truth: dict[tuple[str, str], float]
    theta: dict[str, dict[str, float]]
    difficulties: dict[str, float]


def sigmoid(x: float) -> float:
    if x >= 0:
        return 1 / (1 + math.exp(-x))
    value = math.exp(x)
    return value / (1 + value)


def generate_dataset(scenario: str, seed: int, *, students: int = 80,
                     items_per_chapter: int = 6) -> Dataset:
    """Beta partial grades; teacher labels are noisy and are never the truth."""
    if scenario not in SCENARIOS:
        raise ValueError(f'Unknown scenario: {scenario}')
    rng = random.Random(seed)
    chapters = tuple(f'CH{i:02}' for i in range(1, 12))
    theta: dict[str, dict[str, float]] = {}
    for s in range(students):
        general = rng.gauss(0, .85)
        theta[f's{s:03}'] = {c: general + rng.gauss(0, .65) for c in chapters}
    items, difficulties, discriminations = [], {}, {}
    for index in range(len(chapters) * items_per_chapter):
        chapter_index = index // items_per_chapter
        primary = chapters[chapter_index]
        # Every third item has a fractional mapping to an adjacent chapter.
        weights = {primary: 1.}
        if index % 3 == 0:
            weights = {primary: .65, chapters[(chapter_index + 1) % 11]: .35}
        true_level = (index % items_per_chapter) % 5 + 1
        difficulty = .75 * (true_level - 3) + rng.gauss(0, .25)
        label = max(1, min(5, round(true_level + rng.gauss(0, .45))))
        if scenario == 'mislabeled_teacher':
            # 70% independent labels; the residual 30% retain teacher signal.
            if rng.random() < .7:
                label = rng.randint(1, 5)
        if scenario == 'no_difficulty':
            difficulty, label = 0., rng.randint(1, 5)
        key = f'i{index:03}'
        items.append(ItemSpec(key, weights, label))
        difficulties[key] = difficulty
        discriminations[key] = rng.uniform(.4, 2.2) if scenario == 'nonlinear_mismatch' else 1.
    rows, truth = [], {}
    for student, skills in theta.items():
        for item in items:
            ability = sum(weight * skills[c] for c, weight in item.weights.items())
            linear = discriminations[item.key] * (ability - difficulties[item.key])
            if scenario == 'nonlinear_mismatch' and len(item.weights) > 1:
                vals = [skills[c] for c in item.weights]
                linear += .65 * vals[0] * vals[1]
            mean = sigmoid(linear)
            truth[student, item.key] = mean
            observed_probability = .72
            if scenario == 'sparse':
                observed_probability = .2
            elif scenario == 'mnar':
                observed_probability = sigmoid(.2 + 2.8 * (mean - .5) + .55 * ability)
            # Selection precedes the grade draw and depends on unobserved ability
            # in MNAR; observed scores are not sampled until a pair is selected.
            if rng.random() < observed_probability:
                concentration = 14.
                score = rng.betavariate(mean * concentration, (1 - mean) * concentration)
                rows.append(Row(student, item.key, score))
    return Dataset(chapters, tuple(items), tuple(rows), truth, theta, difficulties)


def split_pairs(rows: list[Row] | tuple[Row, ...], seed: int
                ) -> tuple[list[Row], list[Row], list[Row]]:
    """60/20/20 per learner, with all repeats of a student×item kept together."""
    groups: dict[str, dict[str, list[Row]]] = {}
    for row in rows:
        groups.setdefault(row.student, {}).setdefault(row.item, []).append(row)
    rng = random.Random(seed)
    parts: tuple[list[Row], list[Row], list[Row]] = ([], [], [])
    for student in sorted(groups):
        keys = sorted(groups[student])
        rng.shuffle(keys)
        n_train, n_validation = max(1, int(len(keys) * .6)), int(len(keys) * .2)
        for index, key in enumerate(keys):
            target = 0 if index < n_train else 1 if index < n_train + n_validation else 2
            parts[target].extend(groups[student][key])
    return parts


def split_unseen_items(dataset: Dataset, seed: int) -> tuple[list[Row], list[Row]]:
    """Hold out one complete item in each primary chapter (11 novel items)."""
    rng = random.Random(seed)
    by_primary: dict[str, list[str]] = {}
    for item in dataset.items:
        primary = max(item.weights, key=item.weights.get)
        by_primary.setdefault(primary, []).append(item.key)
    heldout = {rng.choice(sorted(keys)) for keys in by_primary.values()}
    return ([row for row in dataset.rows if row.item not in heldout],
            [row for row in dataset.rows if row.item in heldout])


def fit_b0(items: list[ItemSpec] | tuple[ItemSpec, ...], rows: list[Row]) -> dict:
    item_map = {item.key: item for item in items}
    sums, weights = {}, {}
    for row in rows:
        for chapter, weight in item_map[row.item].weights.items():
            key = row.student, chapter
            sums[key] = sums.get(key, 0.) + weight * row.score
            weights[key] = weights.get(key, 0.) + weight
    return {key: value / weights[key] for key, value in sums.items()}


def predict_b0(model: dict, student: str, item: ItemSpec) -> float:
    # A prior mean of 0.5 is used ONLY for a predictive benchmark with absent
    # training chapters; product radar output still leaves absent evidence blank.
    return sum(weight * model.get((student, chapter), .5) for chapter, weight in item.weights.items())


def evaluate(rows: list[Row], predictions: dict[tuple[str, str], float],
             truth: dict[tuple[str, str], float]) -> dict[str, float | int]:
    if not rows:
        raise ValueError('Cannot evaluate an empty test split')
    missing = {(row.student, row.item) for row in rows} - truth.keys()
    if missing:
        raise ValueError(f'Missing truth for {len(missing)} pairs')
    errors, absolute, expected, bins = [], [], [], {}
    for row in rows:
        p = predictions[row.student, row.item]
        errors.append((p - row.score) ** 2)
        absolute.append(abs(p - row.score))
        expected.append((p - truth[row.student, row.item]) ** 2)
        bin_key = min(9, int(p * 10))
        bins.setdefault(bin_key, []).append((p, row.score))
    calibration = sum(len(values) * abs(statistics.mean(x[0] for x in values) -
                        statistics.mean(x[1] for x in values)) for values in bins.values()) / len(rows)
    return {'n_test': len(rows), 'rmse': math.sqrt(statistics.mean(errors)),
            'mae': statistics.mean(absolute), 'expected_rmse': math.sqrt(statistics.mean(expected)),
            'calibration_gap_10bins': calibration}


def correlation(first: list[float], second: list[float]) -> float | None:
    if len(first) < 2 or statistics.pstdev(first) == 0 or statistics.pstdev(second) == 0:
        return None
    return statistics.correlation(first, second)


def run_model(name: str, dataset: Dataset, train: list[Row], test: list[Row], params: dict) -> dict:
    """Only training responses enter any fitter, including item calibration."""
    started = time.perf_counter()
    if name == 'B0':
        model = fit_b0(dataset.items, train)
        predictions = {(row.student, row.item): predict_b0(model, row.student, item)
                       for row in test for item in dataset.items if item.key == row.item}
        meta = {'converged': None, 'iterations': None, 'loss': None,
                'theta_correlation': None, 'difficulty_correlation': None}
    else:
        # Lazy import permits split/generator protocol tests independent of the
        # optimizer and makes this experiment depend on the shipped core.
        from app.analysis.algorithms.difficulty_model import Item, Observation, fit, predict
        items = [Item(item.key, item.weights, item.difficulty) for item in dataset.items]
        item_map = {item.key: item for item in items}
        actual_params = {**params, **OPTIMIZER}
        if name == 'D0':
            actual_params.update(difficulty_scale=0., calibrate_items=False)
        elif name == 'Fixed':
            actual_params.update(calibrate_items=False)
        model = fit(items, [Observation(r.student, r.item, r.score) for r in train], **actual_params)
        predictions = {(r.student, r.item): predict(model, r.student, item_map[r.item]) for r in test}
        learned, real = [], []
        for student, chapters in model.theta.items():
            for chapter, value in chapters.items():
                learned.append(value)
                real.append(dataset.theta[student][chapter])
        meta = {'converged': model.converged, 'iterations': model.iterations, 'loss': model.loss,
                'theta_correlation': correlation(learned, real),
                'difficulty_correlation': correlation([model.difficulties[i.key] for i in dataset.items],
                                                      [dataset.difficulties[i.key] for i in dataset.items])}
    return {**evaluate(test, predictions, dataset.truth), **meta,
            'seconds': time.perf_counter() - started, 'n_train': len(train)}


def summarize(records: list[dict]) -> list[dict]:
    result = []
    for task, scenario in sorted({(r['task'], r['scenario']) for r in records}):
        for name in ('B0', 'D0', 'Fixed', 'D1'):
            rows = [r for r in records if (r['task'], r['scenario'], r['model']) == (task, scenario, name)]
            if not rows:
                continue
            base_by_seed = {r['seed']: r for r in records if
                            (r['task'], r['scenario'], r['model']) == (task, scenario, 'B0')}
            d0_by_seed = {r['seed']: r for r in records if
                          (r['task'], r['scenario'], r['model']) == (task, scenario, 'D0')}
            diffs = [r['rmse'] - base_by_seed[r['seed']]['rmse'] for r in rows]
            d0_diffs = [r['rmse'] - d0_by_seed[r['seed']]['rmse'] for r in rows]
            mae_diffs = [r['mae'] - base_by_seed[r['seed']]['mae'] for r in rows]
            result.append({'task': task, 'scenario': scenario, 'model': name, 'repeats': len(rows),
                           **{f'{metric}_mean': statistics.mean(r[metric] for r in rows)
                              for metric in ('rmse', 'mae', 'expected_rmse', 'calibration_gap_10bins', 'seconds')},
                           'rmse_sd': statistics.stdev(r['rmse'] for r in rows),
                           'paired_rmse_minus_B0_mean': statistics.mean(diffs),
                           'paired_rmse_minus_B0_sd': statistics.stdev(diffs),
                           'paired_rmse_minus_D0_mean': statistics.mean(d0_diffs),
                           'paired_mae_minus_B0_mean': statistics.mean(mae_diffs),
                           'wins_vs_B0': sum(d < 0 for d in diffs),
                           'converged': sum(r['converged'] is True for r in rows),
                           'theta_correlation_mean': nullable_mean(r['theta_correlation'] for r in rows),
                           'difficulty_correlation_mean': nullable_mean(r['difficulty_correlation'] for r in rows)})
    return result


def nullable_mean(values) -> float | None:
    values = [value for value in values if value is not None]
    return statistics.mean(values) if values else None


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def draw_figure(path: Path, summary: list[dict]) -> None:
    """Scientific SVG: explicit axes, independent-dataset mean ± 1 SD."""
    rows = [r for r in summary if r['task'] == 'known_item']
    colors = {'B0': '#72767c', 'D0': '#c78228', 'Fixed': '#6d62a7', 'D1': '#087d8c'}
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="1160" height="670" viewBox="0 0 1160 670">',
           '<rect width="1160" height="670" fill="white"/>',
           '<g font-family="Arial,sans-serif" fill="#18212b">',
           '<text x="65" y="38" font-size="23">Held-out fractional score prediction</text>',
           '<text x="65" y="64" font-size="14">80 synthetic learners × 66 items; six independent dataset seeds per scenario; mean ± 1 SD</text>']
    x0, xend, top, bottom = 80, 1110, 110, 530
    ymax = max(.4, max(r['rmse_mean'] + r['rmse_sd'] for r in rows) * 1.12)
    y = lambda value: bottom - value / ymax * (bottom - top)
    for tick in range(6):
        val = ymax * tick / 5
        py = y(val)
        svg.append(f'<line x1="{x0}" x2="{xend}" y1="{py:.2f}" y2="{py:.2f}" stroke="#e2e7ec"/>')
        svg.append(f'<text x="68" y="{py+5:.2f}" text-anchor="end" font-size="12">{val:.2f}</text>')
    svg.append(f'<line x1="{x0}" x2="{xend}" y1="{bottom}" y2="{bottom}" stroke="#293645"/>')
    svg.append('<text x="24" y="330" font-size="14" transform="rotate(-90 24 330)">Test RMSE (fraction of full score; lower is better)</text>')
    labels = ['Difficulty', 'Teacher noise', 'Sparse', 'MNAR', 'No difficulty', 'Nonlinear']
    for index, scenario in enumerate(SCENARIOS):
        center = x0 + (index + .5) * (xend - x0) / len(SCENARIOS)
        svg.append(f'<text x="{center}" y="557" text-anchor="middle" font-size="13">{labels[index]}</text>')
        for offset, name in enumerate(colors):
            row = next(r for r in rows if r['scenario'] == scenario and r['model'] == name)
            px = center + (offset - 1.5) * 23
            low, high = y(row['rmse_mean'] - row['rmse_sd']), y(row['rmse_mean'] + row['rmse_sd'])
            svg.extend([f'<line x1="{px}" x2="{px}" y1="{high:.2f}" y2="{low:.2f}" stroke="{colors[name]}" stroke-width="2"/>',
                        f'<line x1="{px-5}" x2="{px+5}" y1="{high:.2f}" y2="{high:.2f}" stroke="{colors[name]}"/>',
                        f'<line x1="{px-5}" x2="{px+5}" y1="{low:.2f}" y2="{low:.2f}" stroke="{colors[name]}"/>',
                        f'<circle cx="{px}" cy="{y(row["rmse_mean"]):.2f}" r="5" fill="{colors[name]}"/>'])
    for index, (name, color) in enumerate(colors.items()):
        px = 110 + index * 240
        svg.append(f'<circle cx="{px}" cy="603" r="5" fill="{color}"/><text x="{px+13}" y="608" font-size="14">{name}</text>')
    svg.append('<text x="80" y="647" font-size="12">Synthetic simulation only. Error bars describe Monte Carlo spread, not confidence in real students.</text></g></svg>')
    path.write_text('\n'.join(svg), encoding='utf-8')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[2] / 'data/analysis/experiments/difficulty-v1')
    parser.add_argument('--students', type=int, default=80)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    validation = []
    for grid_index, params in enumerate(GRID):
        for scenario_index, scenario in enumerate(SCENARIOS):
            for seed in VALIDATION_SEEDS:
                effective_seed = seed + scenario_index * 100_000
                dataset = generate_dataset(scenario, effective_seed, students=args.students)
                train, valid, _ = split_pairs(dataset.rows, effective_seed + 719)
                validation.append({'grid_index': grid_index, 'scenario': scenario, 'seed': seed,
                                   **params, **run_model('D1', dataset, train, valid, params)})
        print(f'validation grid {grid_index + 1}/{len(GRID)} finished', flush=True)
    ranked = sorted((statistics.mean(r['rmse'] for r in validation if r['grid_index'] == index), index)
                    for index in range(len(GRID)))
    selected = dict(GRID[ranked[0][1]])
    d0_validation = []
    for learner_l2 in sorted({params['learner_l2'] for params in GRID}):
        for scenario_index, scenario in enumerate(SCENARIOS):
            for seed in VALIDATION_SEEDS:
                effective_seed = seed + scenario_index * 100_000
                dataset = generate_dataset(scenario, effective_seed, students=args.students)
                train, valid, _ = split_pairs(dataset.rows, effective_seed + 719)
                d0_params = {**selected, 'learner_l2': learner_l2}
                d0_validation.append({'scenario': scenario, 'seed': seed, 'learner_l2': learner_l2,
                                      **run_model('D0', dataset, train, valid, d0_params)})
    selected_d0_l2 = min((statistics.mean(r['rmse'] for r in d0_validation if r['learner_l2'] == penalty), penalty)
                         for penalty in sorted({p['learner_l2'] for p in GRID}))[1]
    protocol = {'version': 'difficulty-v1', 'created_utc': datetime.now(timezone.utc).isoformat(),
                'students_per_dataset': args.students, 'items': 66, 'chapters': 11,
                'grade_distribution': 'Beta(14*mu,14*(1-mu)); mu is scenario-specific logistic mean',
                'known_item_split': 'student-item grouped, per-student shuffled 60/20/20',
                'final_training': 'train+validation partitions (80%) after configuration freezes; final test 20%',
                'unseen_item_split': 'one whole item per primary chapter; separate task, 11 held-out items',
                'selection_objective': 'unweighted mean validation score RMSE across six scenarios × two dataset seeds',
                'validation_seeds': VALIDATION_SEEDS, 'final_seeds': FINAL_SEEDS,
                'scenario_seed_offset': 'scenario_index * 100000; split seed = effective seed + 719',
                'unseen_split_seed': 'effective seed + 991', 'hypergrid': GRID,
                'selected_grid_index': ranked[0][1], 'selected_parameters': selected,
                'd0_learner_l2_candidates': sorted({params['learner_l2'] for params in GRID}),
                'd0_selected_learner_l2': selected_d0_l2,
                'fixed_baseline_parameters': 'same as D1, calibrate_items=False; ablation rather than independently tuned',
                'optimizer': OPTIMIZER,
                'uncertainty_unit': 'independent generated dataset, six final replicates per scenario',
                'baseline_unobserved_chapter_prediction': '.5 predictive prior, never a product radar value',
                'test_seeds_used_for_selection': False,
                'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'core_sha256': hashlib.sha256((Path(__file__).resolve().parents[1] / 'app/analysis/algorithms/difficulty_model.py').read_bytes()).hexdigest()}
    # Freeze and persist before generating any final data.
    (args.output / 'protocol.json').write_text(json.dumps(protocol, indent=2), encoding='utf-8')
    frozen = {**selected, **protocol['optimizer'], 'calibrate_items': True}
    (args.output / 'selected-parameters.json').write_text(json.dumps(frozen, indent=2), encoding='utf-8')
    write_csv(args.output / 'validation.csv', validation)
    write_csv(args.output / 'd0-validation.csv', d0_validation)
    print('FROZEN PARAMETERS ' + json.dumps(selected), flush=True)
    final = []
    for scenario_index, scenario in enumerate(SCENARIOS):
        for seed in FINAL_SEEDS:
            effective_seed = seed + scenario_index * 100_000
            dataset = generate_dataset(scenario, effective_seed, students=args.students)
            train, valid, test = split_pairs(dataset.rows, effective_seed + 719)
            train = train + valid
            for name in ('B0', 'D0', 'Fixed', 'D1'):
                fitted_params = {**selected, 'learner_l2': selected_d0_l2} if name == 'D0' else selected
                final.append({'task': 'known_item', 'scenario': scenario, 'seed': seed,
                              'model': name, **run_model(name, dataset, train, test, fitted_params)})
            # A separate novel-item test covers both informative and unreliable labels.
            if scenario in ('difficulty_signal', 'mislabeled_teacher'):
                train_new, test_new = split_unseen_items(dataset, effective_seed + 991)
                for name in ('B0', 'D0', 'Fixed', 'D1'):
                    fitted_params = {**selected, 'learner_l2': selected_d0_l2} if name == 'D0' else selected
                    final.append({'task': 'unseen_item', 'scenario': scenario, 'seed': seed,
                                  'model': name, **run_model(name, dataset, train_new, test_new, fitted_params)})
        print(f'final scenario {scenario} finished', flush=True)
    summary = summarize(final)
    write_csv(args.output / 'per_repeat.csv', final)
    write_csv(args.output / 'summary.csv', summary)
    (args.output / 'per_repeat.json').write_text(json.dumps(final, indent=2), encoding='utf-8')
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    draw_figure(args.output / 'rmse_by_scenario.svg', summary)
    print(json.dumps({'selected_parameters': selected, 'total_seconds': time.perf_counter() - started,
                      'replicate_model_evaluations': len(final), 'validation_fits': len(validation),
                      'd0_validation_fits': len(d0_validation),
                      'final_nonconverged': [r for r in final if r['converged'] is False]}, indent=2), flush=True)


if __name__ == '__main__':
    main()
