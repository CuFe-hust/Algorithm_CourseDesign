"""Experiment protocol safeguards; these tests never connect to a database."""
from dataclasses import replace

import pytest

from scripts import experiment_ability_difficulty as experiment


def test_split_keeps_entire_student_item_group_together_and_is_reproducible():
    rows = [experiment.Row(f's{i // 6}', f'i{i % 6}', i / 30) for i in range(30)]
    rows.extend([replace(rows[0]), replace(rows[9])])
    first = experiment.split_pairs(rows, 194)
    assert first == experiment.split_pairs(rows, 194)
    groups = [{(row.student, row.item) for row in part} for part in first]
    assert all(groups)
    assert not groups[0] & groups[1]
    assert not groups[0] & groups[2]
    assert not groups[1] & groups[2]
    assert sum(map(len, first)) == len(rows)


def test_missing_truth_is_an_error_and_never_becomes_a_zero_score():
    rows = [experiment.Row('s1', 'i1', .4)]
    with pytest.raises(ValueError, match='Missing truth'):
        experiment.evaluate(rows, {('s1', 'i1'): .5}, {})


def test_generator_has_fractional_scores_eleven_chapters_and_unique_pairs():
    dataset = experiment.generate_dataset('difficulty_signal', 830, students=12, items_per_chapter=3)
    assert len(dataset.chapters) == 11
    assert any(len(item.weights) > 1 for item in dataset.items)
    assert all(abs(sum(item.weights.values()) - 1) < 1e-12 for item in dataset.items)
    pairs = [(row.student, row.item) for row in dataset.rows]
    assert len(pairs) == len(set(pairs))
    assert all(0 < row.score < 1 for row in dataset.rows)
    assert all(pair in dataset.truth for pair in pairs)
    assert dataset == experiment.generate_dataset('difficulty_signal', 830, students=12, items_per_chapter=3)


def test_unseen_item_split_holds_out_whole_items_without_losing_students():
    dataset = experiment.generate_dataset('difficulty_signal', 642, students=20, items_per_chapter=3)
    train, test = experiment.split_unseen_items(dataset, 23)
    assert not {row.item for row in train} & {row.item for row in test}
    assert {row.student for row in test} <= {row.student for row in train}
    assert len({row.item for row in test}) == 11


def test_b0_predicts_a_cross_chapter_item_from_weighted_observed_means():
    items = [experiment.ItemSpec('a', {'c1': 1.}, 3),
             experiment.ItemSpec('b', {'c2': 1.}, 3),
             experiment.ItemSpec('cross', {'c1': .25, 'c2': .75}, 3)]
    baseline = experiment.fit_b0(items, [experiment.Row('s', 'a', .2), experiment.Row('s', 'b', .8)])
    assert experiment.predict_b0(baseline, 's', items[2]) == pytest.approx(.65)
