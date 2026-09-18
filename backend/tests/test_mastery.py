from app.services.mastery import update_probability


def test_correct_increases_mastery_without_many_hints():
    assert update_probability(0.4, True, 0) > 0.4


def test_wrong_decreases_mastery():
    assert update_probability(0.7, False, 0) < 0.7


def test_many_hints_reduce_learning_credit():
    no_hints = update_probability(0.4, True, 0)
    many_hints = update_probability(0.4, True, 5)
    assert many_hints < no_hints
