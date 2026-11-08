"""Behavioral checks for the dependency-free fractional response model."""

from copy import deepcopy
from math import exp, isfinite, log

import pytest


def api():
    from app.analysis.algorithms.difficulty_model import Item, Observation, fit, predict

    return Item, Observation, fit, predict


def test_empty_training_uses_teacher_priors_and_remembers_scale():
    Item, _, fit, predict = api()
    easy = Item('easy', {'chapter': 1.0}, 1)
    hard = Item('hard', {'chapter': 1.0}, 5)
    model = fit([hard, easy], [], difficulty_scale=0.5)
    assert model.theta == {}
    assert model.difficulties == {'easy': -1.0, 'hard': 1.0}
    assert model.difficulty_scale == 0.5
    assert model.loss == 0.0
    assert model.iterations == 0 and model.converged
    assert predict(model, 'new', easy) == pytest.approx(0.7310585786300049)
    assert predict(model, 'new', Item('new-item', {'other': 1.0}, 5)) == pytest.approx(0.2689414213699951)


def test_empty_item_universe_has_a_zero_loss_prior():
    _, _, fit, _ = api()
    model = fit([], [])
    assert model.theta == {} and model.difficulties == {}
    assert model.loss == 0 and model.converged


def test_fractional_score_has_an_independently_checked_optimum():
    Item, Observation, fit, predict = api()
    item = Item('one', {'chapter': 1.0}, 3)
    # theta = .5 and b = -.25 give eta = .75. Choose y so that
    # p - y + learner_l2 * theta = 0 and -(p-y) + item_l2*b = 0.
    score = 0.779178699175393
    model = fit([item], [Observation('s', 'one', score)], learner_l2=0.2,
                item_l2=0.4, tolerance=1e-10, max_iterations=200)
    assert model.theta['s']['chapter'] == pytest.approx(0.5, abs=1e-8)
    assert model.difficulties['one'] == pytest.approx(-0.25, abs=1e-8)
    assert predict(model, 's', item) == pytest.approx(0.679178699175393, abs=1e-9)
    assert model.converged


def test_same_observed_score_on_harder_item_yields_higher_ability():
    Item, Observation, fit, _ = api()
    items = [Item('easy', {'c': 1.0}, 1), Item('hard', {'c': 1.0}, 5)]
    model = fit(items, [Observation('easy-student', 'easy', 0.7),
                        Observation('hard-student', 'hard', 0.7)])
    assert model.theta['hard-student']['c'] > model.theta['easy-student']['c']


def test_cross_chapter_weights_change_ability_in_the_correct_proportion():
    Item, Observation, fit, _ = api()
    item = Item('mixed', {'b': 0.25, 'a': 0.75}, 3)
    model = fit([item], [Observation('s', 'mixed', 1.0)], calibrate_items=False,
                tolerance=1e-10, max_iterations=200)
    assert model.theta['s']['a'] > 0
    assert model.theta['s']['a'] == pytest.approx(3 * model.theta['s']['b'], abs=1e-8)


def test_item_calibration_moves_difficulty_and_can_be_disabled():
    Item, Observation, fit, _ = api()
    item = Item('one', {'c': 1.0}, 3)
    observations = [Observation(f's{i}', 'one', 0.1) for i in range(20)]
    calibrated = fit([item], observations)
    fixed = fit([item], observations, calibrate_items=False)
    assert calibrated.difficulties['one'] > 0.5
    assert fixed.difficulties['one'] == 0.0
    assert calibrated.loss < fixed.loss


def test_unobserved_item_and_chapter_retain_prior_values():
    Item, Observation, fit, predict = api()
    items = [Item('seen', {'a': 1.0}, 3), Item('unseen', {'b': 1.0}, 5)]
    model = fit(items, [Observation('s', 'seen', 1.0)])
    assert model.theta['s'].get('b', 0.0) == 0.0
    assert model.difficulties['unseen'] == 1.5
    assert predict(model, 's', items[1]) == pytest.approx(0.18242552380635635)


def test_prediction_uses_fitted_difficulty_for_known_key():
    Item, Observation, fit, predict = api()
    item = Item('one', {'c': 1.0}, 3)
    model = fit([item], [Observation('s', 'one', 0.1)])
    # Changing the teacher annotation after fitting cannot overwrite calibration.
    assert predict(model, 's', Item('one', {'c': 1.0}, 5)) == predict(model, 's', item)


def test_endpoints_and_extreme_valid_anchors_remain_finite():
    Item, Observation, fit, predict = api()
    items = [Item('zero', {'c': 1.0}, 1), Item('one', {'c': 1.0}, 5)]
    model = fit(items, [Observation('s', 'zero', 0.0), Observation('s', 'one', 1.0)],
                difficulty_scale=1000, max_iterations=10)
    assert isfinite(model.loss)
    assert all(isfinite(b) for b in model.difficulties.values())
    assert all(isfinite(v) for values in model.theta.values() for v in values.values())
    assert all(0 <= predict(model, 's', item) <= 1 for item in items)


def test_identical_duplicate_observations_count_once():
    Item, Observation, fit, _ = api()
    item = Item('one', {'c': 1.0}, 3)
    observation = Observation('s', 'one', 0.7)
    assert fit([item], [observation]) == fit([item], [observation, observation])


def test_contradictory_duplicate_observations_are_rejected():
    Item, Observation, fit, _ = api()
    with pytest.raises(ValueError, match='duplicate|Duplicate|DUPLICATE'):
        fit([Item('one', {'c': 1.0}, 3)],
            [Observation('s', 'one', 0.7), Observation('s', 'one', 0.6)])


def test_fitting_is_deterministic_and_does_not_mutate_inputs():
    Item, Observation, fit, _ = api()
    items = [Item('b', {'y': 0.25, 'x': 0.75}, 2), Item('a', {'y': 1.0}, 4)]
    observations = [Observation('b', 'b', 0.1), Observation('a', 'a', 0.8),
                    Observation('a', 'b', 0.4)]
    original = deepcopy((items, observations))
    first = fit(items, observations)
    reordered = [Item(i.key, dict(reversed(list(i.weights.items()))), i.difficulty)
                 for i in reversed(items)]
    assert first == fit(reordered, list(reversed(observations)))
    assert (items, observations) == original


def test_reported_loss_is_the_requested_regularized_cross_entropy():
    Item, Observation, fit, predict = api()
    items = [Item('a', {'c': 1.0}, 2), Item('b', {'c': 1.0}, 4)]
    observations = [Observation('s', 'a', 0.2), Observation('s', 'b', 0.9)]
    model = fit(items, observations, learner_l2=0.7, item_l2=2.5)
    expected = 0.0
    for observation, item in zip(observations, items):
        p = predict(model, observation.student, item)
        expected -= observation.score * log(p) + (1-observation.score) * log(1-p)
    expected += 0.7 / 2 * sum(v*v for values in model.theta.values() for v in values.values())
    expected += 2.5 / 2 * sum((model.difficulties[i.key] - 0.75*(i.difficulty-3))**2 for i in items)
    assert model.loss == pytest.approx(expected, abs=1e-12)


def test_converged_fit_is_stationary_for_both_parameter_families():
    Item, Observation, fit, predict = api()
    items = [Item('a', {'a': 0.7, 'b': 0.3}, 2), Item('b', {'b': 1.0}, 4)]
    observations = [Observation('s1', 'a', 0.3), Observation('s1', 'b', 0.9),
                    Observation('s2', 'a', 1.0), Observation('s2', 'b', 0.0)]
    model = fit(items, observations, tolerance=1e-9, max_iterations=200)
    item_map = {item.key: item for item in items}
    assert model.converged
    for student, values in model.theta.items():
        for chapter, theta in values.items():
            gradient = theta + sum(
                (predict(model, student, item_map[o.item])-o.score) * item_map[o.item].weights.get(chapter, 0.0)
                for o in observations if o.student == student)
            assert abs(gradient) < 1e-8
    for item in items:
        gradient = 4*(model.difficulties[item.key] - 0.75*(item.difficulty-3))
        gradient -= sum(predict(model, o.student, item)-o.score for o in observations if o.item == item.key)
        assert abs(gradient) < 1e-8


def test_iteration_limit_reports_nonconvergence_instead_of_success():
    Item, Observation, fit, _ = api()
    model = fit([Item('one', {'c': 1.0}, 3)], [Observation('s', 'one', 1.0)],
                max_iterations=1, tolerance=1e-14)
    assert model.iterations == 1 and not model.converged


@pytest.mark.parametrize('name,value', [
    ('learner_l2', 0), ('learner_l2', -1), ('learner_l2', float('nan')),
    ('item_l2', 0), ('item_l2', float('inf')), ('difficulty_scale', -1),
    ('difficulty_scale', float('nan')), ('max_iterations', 0),
    ('max_iterations', 1.5), ('max_iterations', True), ('tolerance', 0),
    ('tolerance', float('nan')), ('calibrate_items', 1),
])
def test_invalid_optimizer_parameters_are_rejected(name, value):
    _, _, fit, _ = api()
    with pytest.raises(ValueError):
        fit([], [], **{name: value})


@pytest.mark.parametrize('weights', [{}, {'c': 0.0}, {'c': -1.0}, {'c': 0.5},
    {'c': float('nan')}, {'c': float('inf')}, {'': 1.0}, {'c': True}])
def test_invalid_item_weights_are_rejected(weights):
    Item, _, fit, _ = api()
    with pytest.raises(ValueError):
        fit([Item('one', weights, 3)], [])


@pytest.mark.parametrize('difficulty', [0, 6, 2.5, True])
def test_teacher_difficulty_must_be_an_integer_level(difficulty):
    Item, _, fit, _ = api()
    with pytest.raises(ValueError):
        fit([Item('one', {'c': 1.0}, difficulty)], [])


@pytest.mark.parametrize('score', [-0.01, 1.01, float('nan'), float('inf'), True])
def test_invalid_observed_scores_are_rejected(score):
    Item, Observation, fit, _ = api()
    with pytest.raises(ValueError):
        fit([Item('one', {'c': 1.0}, 3)], [Observation('s', 'one', score)])


def test_unknown_item_reference_is_rejected():
    _, Observation, fit, _ = api()
    with pytest.raises(ValueError, match='unknown|Unknown|UNKNOWN'):
        fit([], [Observation('s', 'absent', 0.5)])


def test_duplicate_item_keys_are_rejected():
    Item, _, fit, _ = api()
    with pytest.raises(ValueError, match='duplicate|Duplicate|DUPLICATE'):
        fit([Item('same', {'c': 1.0}, 3), Item('same', {'c': 1.0}, 4)], [])


@pytest.mark.parametrize('student,item', [('', 'one'), ('s', '')])
def test_empty_observation_keys_are_rejected(student, item):
    Item, Observation, fit, _ = api()
    with pytest.raises(ValueError):
        fit([Item('one', {'c': 1.0}, 3)], [Observation(student, item, 0.5)])


def test_zero_difficulty_scale_supports_the_no_difficulty_ablation():
    Item, Observation, fit, _ = api()
    model = fit([Item('one', {'c': 1.0}, 5)], [Observation('s', 'one', 0.8)],
                difficulty_scale=0.0, calibrate_items=False)
    assert model.difficulties['one'] == 0.0
