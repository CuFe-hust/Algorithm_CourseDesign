"""Regularized fractional-response model, using only the Python standard library.

Scores are fractions, including zero and one. The fitted response is
``sigmoid(sum(weight * chapter_ability) - item_difficulty)``. This is a
penalized cross-entropy model; it does not supply posterior uncertainty.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, fsum, isclose, isfinite, log1p
from numbers import Real


@dataclass(frozen=True)
class Item:
    key: str
    weights: dict[str, float]
    difficulty: int


@dataclass(frozen=True)
class Observation:
    student: str
    item: str
    score: float


@dataclass(frozen=True)
class FittedModel:
    theta: dict[str, dict[str, float]]
    difficulties: dict[str, float]
    loss: float
    iterations: int
    converged: bool
    difficulty_scale: float


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + exp(-value))
    e = exp(value)
    return e / (1.0 + e)


def _cross_entropy(eta: float, score: float) -> float:
    # This equivalent softplus form avoids both exp overflow and cancellation
    # for a correctly predicted endpoint with a large absolute predictor.
    if eta >= 0:
        return (1.0 - score) * eta + log1p(exp(-eta))
    return -score * eta + log1p(exp(eta))


def _number(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value):
        raise ValueError(f'{name} must be a finite number')
    return float(value)


def _key(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{name} must be a nonempty string')


def _validated_item(item: Item) -> Item:
    _key(item.key, 'item key')
    if type(item.difficulty) is not int or not 1 <= item.difficulty <= 5:
        raise ValueError('difficulty must be an integer from 1 to 5')
    if not isinstance(item.weights, dict) or not item.weights:
        raise ValueError('item weights must be a nonempty mapping')
    weights = {}
    for chapter, value in item.weights.items():
        _key(chapter, 'chapter key')
        weight = _number(value, 'chapter weight')
        if weight <= 0:
            raise ValueError('chapter weights must be strictly positive')
        weights[chapter] = weight
    if not isclose(fsum(weights.values()), 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError('chapter weights must sum to 1')
    return Item(item.key, dict(sorted(weights.items())), item.difficulty)


def fit(
    items: list[Item],
    observations: list[Observation],
    *,
    learner_l2: float = 1.0,
    item_l2: float = 4.0,
    difficulty_scale: float = 0.75,
    max_iterations: int = 60,
    tolerance: float = 1e-6,
    calibrate_items: bool = True,
) -> FittedModel:
    """Minimize cross entropy plus centered learner/item quadratic penalties.

    Both penalties must be strictly positive, giving a unique optimum on
    observed coordinates. Unobserved coordinates remain at their priors.
    One iteration is one deterministic coordinate-Newton sweep. Newton steps
    are bounded and backtracked against the actual local objective; cached
    predictors make a sweep linear in the sparse response design.

    ``converged`` means the largest absolute gradient of an active coordinate
    is at most ``tolerance``; exhausting the iteration budget is not success.
    Duplicate identical student/item observations count once. No input object
    or mapping is modified.
    """
    learner_l2 = _number(learner_l2, 'learner_l2')
    item_l2 = _number(item_l2, 'item_l2')
    difficulty_scale = _number(difficulty_scale, 'difficulty_scale')
    tolerance = _number(tolerance, 'tolerance')
    if learner_l2 <= 0 or item_l2 <= 0:
        raise ValueError('learner_l2 and item_l2 must be strictly positive')
    if difficulty_scale < 0:
        raise ValueError('difficulty_scale must be nonnegative')
    if tolerance <= 0:
        raise ValueError('tolerance must be strictly positive')
    if type(max_iterations) is not int or max_iterations < 1:
        raise ValueError('max_iterations must be a positive integer')
    if type(calibrate_items) is not bool:
        raise ValueError('calibrate_items must be a boolean')

    item_map: dict[str, Item] = {}
    for original in items:
        item = _validated_item(original)
        if item.key in item_map:
            raise ValueError(f'duplicate item key: {item.key}')
        item_map[item.key] = item
    item_map = dict(sorted(item_map.items()))
    anchors = {key: difficulty_scale * (item.difficulty - 3) for key, item in item_map.items()}
    if not all(isfinite(anchor) for anchor in anchors.values()):
        raise ValueError('difficulty_scale produces nonfinite item anchors')

    unique: dict[tuple[str, str], float] = {}
    for observation in observations:
        _key(observation.student, 'student key')
        _key(observation.item, 'observation item key')
        if observation.item not in item_map:
            raise ValueError(f'unknown item reference: {observation.item}')
        score = _number(observation.score, 'score')
        if not 0.0 <= score <= 1.0:
            raise ValueError('score must be between 0 and 1')
        pair = (observation.student, observation.item)
        if pair in unique and unique[pair] != score:
            raise ValueError(f'duplicate observation has contradictory scores: {pair}')
        unique[pair] = score
    records = sorted(unique.items())
    if not records:
        return FittedModel({}, anchors, 0.0, 0, True, difficulty_scale)

    students = sorted({student for (student, _), _ in records})
    chapters = sorted({chapter for item in item_map.values() for chapter in item.weights})
    learner_keys = sorted({(student, chapter) for (student, key), _ in records
                           for chapter in item_map[key].weights})
    learner_index = {key: index for index, key in enumerate(learner_keys)}
    observed_items = sorted({key for (_, key), _ in records})
    item_index = ({key: len(learner_keys) + i for i, key in enumerate(observed_items)}
                  if calibrate_items else {})

    # Item coordinates are deviations from teacher anchors. All regularizers
    # therefore have center zero, and the initial predictor is -anchor.
    values = [0.0] * (len(learner_keys) + len(item_index))
    penalties = [learner_l2] * len(learner_keys) + [item_l2] * len(item_index)
    adjacent: list[list[tuple[int, float]]] = [[] for _ in values]
    scores = []
    eta = []
    for row, ((student, key), score) in enumerate(records):
        scores.append(score)
        eta.append(-anchors[key])
        for chapter, weight in item_map[key].weights.items():
            adjacent[learner_index[(student, chapter)]].append((row, weight))
        if calibrate_items:
            adjacent[item_index[key]].append((row, -1.0))

    def objective() -> float:
        return fsum(_cross_entropy(z, y) for z, y in zip(eta, scores)) + fsum(
            0.5 * penalty * value * value for value, penalty in zip(values, penalties))

    def stationary() -> bool:
        residuals = [_sigmoid(z) - y for z, y in zip(eta, scores)]
        return all(abs(penalty * value + fsum(coefficient * residuals[row]
                       for row, coefficient in rows)) <= tolerance
                   for value, penalty, rows in zip(values, penalties, adjacent))

    converged = stationary()
    iterations = 0
    while not converged and iterations < max_iterations:
        for coordinate, rows in enumerate(adjacent):
            value = values[coordinate]
            penalty = penalties[coordinate]
            gradient = penalty * value
            curvature = penalty
            for row, coefficient in rows:
                p = _sigmoid(eta[row])
                gradient += coefficient * (p - scores[row])
                curvature += coefficient * coefficient * p * (1.0 - p)
            if abs(gradient) <= tolerance:
                continue
            step = max(-2.0, min(2.0, -gradient / curvature))
            old_losses = [_cross_entropy(eta[row], scores[row]) for row, _ in rows]
            for _ in range(40):
                difference = penalty * step * (value + 0.5 * step) + fsum(
                    _cross_entropy(eta[row] + coefficient * step, scores[row]) - old
                    for (row, coefficient), old in zip(rows, old_losses))
                # A tiny absolute allowance handles cancellation at stationarity.
                if difference <= 1e-14:
                    values[coordinate] = value + step
                    for row, coefficient in rows:
                        eta[row] += coefficient * step
                    break
                step *= 0.5
        iterations += 1
        converged = stationary()

    theta = {student: {chapter: 0.0 for chapter in chapters} for student in students}
    for (student, chapter), coordinate in learner_index.items():
        theta[student][chapter] = values[coordinate]
    difficulties = {key: anchor + (values[item_index[key]] if key in item_index else 0.0)
                    for key, anchor in anchors.items()}
    return FittedModel(theta, difficulties, objective(), iterations, converged, difficulty_scale)


def predict(model: FittedModel, student: str, item: Item) -> float:
    """Predict a fraction, retaining teacher priors for unseen items/students."""
    _key(student, 'student key')
    item = _validated_item(item)
    theta = model.theta.get(student, {})
    difficulty = model.difficulties.get(item.key, model.difficulty_scale * (item.difficulty - 3))
    return _sigmoid(fsum(weight * theta.get(chapter, 0.0)
                         for chapter, weight in item.weights.items()) - difficulty)
