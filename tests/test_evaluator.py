from decimal import Decimal

import pandas as pd
import pytest

from fsq_agent.validation import evaluator as ev


# --- tagging -----------------------------------------------------------------

def test_untagged_case_counts_as_easy():
    """The 30 pre-existing cases carry no tags and must not be lost."""
    assert ev.case_tags({"question": "q"}) == ("easy",)


def test_empty_tag_list_falls_back_to_easy():
    assert ev.case_tags({"tags": []}) == ("easy",)


def test_declared_tags_are_kept_in_order():
    assert ev.case_tags({"tags": ["hard", "vietnamese"]}) == ("hard", "vietnamese")


# --- per-tag accounting ------------------------------------------------------

def test_case_counts_towards_every_tag_it_carries():
    report = ev.EvalReport()
    report.record(("hard", "vietnamese"), passed=True)
    report.record(("hard", "type-trap"), passed=False)

    assert report.by_tag["hard"] == {"total": 2, "passed": 1}
    assert report.by_tag["vietnamese"] == {"total": 1, "passed": 1}
    assert report.by_tag["type-trap"] == {"total": 1, "passed": 0}


def test_tag_totals_may_exceed_overall_total():
    """Tags are overlapping views, not a partition — this is intended."""
    report = ev.EvalReport(total=1)
    report.record(("hard", "ambiguous"), passed=True)
    assert sum(b["total"] for b in report.by_tag.values()) > report.total


def test_accuracy_is_zero_for_an_empty_run():
    assert ev.EvalReport().accuracy == 0.0


# --- reporting ---------------------------------------------------------------

def test_headline_groups_are_printed_before_sub_groups():
    lines = ev.format_by_tag({
        "vietnamese": {"total": 4, "passed": 3},
        "hard": {"total": 10, "passed": 6},
        "easy": {"total": 27, "passed": 25},
    })
    order = [line.strip().split()[0] for line in lines]
    assert order == ["easy", "hard", "vietnamese"]


def test_sub_groups_are_indented_deeper_than_headline_groups():
    lines = ev.format_by_tag({
        "hard": {"total": 2, "passed": 1},
        "date": {"total": 1, "passed": 1},
    })
    by_tag = {line.strip().split()[0]: line for line in lines}
    leading = lambda s: len(s) - len(s.lstrip())  # noqa: E731
    assert leading(by_tag["date"]) > leading(by_tag["hard"])


# --- result comparison -------------------------------------------------------

def test_row_order_does_not_affect_the_match():
    a = pd.DataFrame({"x": [1, 2], "y": ["a", "b"]})
    b = pd.DataFrame({"x": [2, 1], "y": ["b", "a"]})
    assert ev.results_match(a, b)


def test_column_names_do_not_affect_the_match():
    a = pd.DataFrame({"total": [5]})
    b = pd.DataFrame({"so_luong": [5]})
    assert ev.results_match(a, b)


def test_different_values_do_not_match():
    """The Rank trap depends on this: same shape, different rows."""
    correct = pd.DataFrame({"sym": ["BTC", "ETH", "USDT"]})
    lexicographic = pd.DataFrame({"sym": ["BTC", "ADA", "TEL"]})
    assert not ev.results_match(correct, lexicographic)


def test_different_shapes_do_not_match():
    assert not ev.results_match(pd.DataFrame({"x": [1]}), pd.DataFrame({"x": [1, 2]}))


@pytest.mark.parametrize("value", [1.00001, 1.00004])
def test_float_drift_below_4dp_still_matches(value):
    """Equivalent aggregates should not fail on last-digit noise."""
    assert ev.results_match(pd.DataFrame({"x": [1.0]}), pd.DataFrame({"x": [value]}))


def test_float_difference_above_4dp_does_not_match():
    """Documents where the tolerance stops: _normalize rounds to 4 places."""
    assert not ev.results_match(pd.DataFrame({"x": [1.0]}), pd.DataFrame({"x": [1.0001]}))


def test_int_and_float_of_the_same_value_match():
    """MAX(x::int) vs MAX(x::numeric) is an arbitrary authoring choice, not
    a wrong answer — this previously failed a correct query."""
    gold = pd.DataFrame({"max_index": [42]})          # int64
    generated = pd.DataFrame({"m": [42.0]})           # float64
    assert ev.results_match(gold, generated)


def test_decimal_and_float_of_the_same_value_match():
    gold = pd.DataFrame({"price": [Decimal("90287.95")]})
    generated = pd.DataFrame({"p": [90287.95]})
    assert ev.results_match(gold, generated)


def test_numeric_strings_stay_distinct_from_numbers():
    """The text-typed Rank column is only a trap while '1' != 1."""
    as_text = pd.DataFrame({"rank": ["1", "10", "2"]})
    as_number = pd.DataFrame({"rank": [1, 10, 2]})
    assert not ev.results_match(as_text, as_number)


def test_booleans_stay_distinct_from_numbers():
    flags = pd.DataFrame({"ok": [True, False]})
    numbers = pd.DataFrame({"ok": [1, 0]})
    assert not ev.results_match(flags, numbers)
