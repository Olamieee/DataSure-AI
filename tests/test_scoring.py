"""Tests for the quality scoring engine: formulas, bounds, transparency."""
from __future__ import annotations

from math import isclose

import pytest

from datasure.profiling.profile import profile_dataset
from datasure.profiling.scoring import WEIGHTS, compute_scores


def scores_for(data):
    import pandas as pd

    return compute_scores(profile_dataset(pd.DataFrame(data)))


def test_perfect_dataset_scores_100():
    import pandas as pd

    df = pd.DataFrame({
        "a": [1, 2, 3, 4, 5, 6, 7, 8],
        "b": ["x", "y", "x", "y", "x", "y", "x", "y"],
        "c": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8],
    })
    result = compute_scores(profile_dataset(df))
    assert result["overall"] == 100.0
    for dimension in result["dimensions"].values():
        assert dimension["score"] == 100.0


def test_scores_dimensions_and_weights_present():
    result = scores_for({"a": [1, 2, 3]})
    assert set(result["dimensions"].keys()) == {
        "completeness", "uniqueness", "validity", "consistency", "distribution"
    }
    assert isclose(sum(WEIGHTS.values()), 1.0)
    assert "disclaimer" in result and "heuristic" in result["disclaimer"]


def test_overall_is_weighted_mean_of_dimensions():
    result = scores_for({"a": [1, 2, 3]})
    expected = isclose(
        sum(
            result["dimensions"][name]["score"] * WEIGHTS[name]
            for name in WEIGHTS
        ),
        result["overall"],
        abs_tol=0.05,
    )
    assert expected


def test_missing_values_reduce_completeness():
    result = scores_for({"a": [1, None, 3, None]})
    completeness = result["dimensions"]["completeness"]
    assert completeness["score"] == pytest.approx(50.0)
    assert completeness["inputs"]["missing_cells"] == 2
    assert completeness["inputs"]["total_cells"] == 4


def test_duplicate_rows_reduce_uniqueness():
    result = scores_for({"a": [1, 1, 1, 1], "b": [2, 2, 2, 2]})
    uniqueness = result["dimensions"]["uniqueness"]
    assert uniqueness["score"] == pytest.approx(30.0)
    # 0.7 * 1.0 (all rows duplicated) + 0.3*0 columns = 70 penalty
    assert uniqueness["breakdown"][0]["penalty"] == pytest.approx(70.0)


def test_empty_column_penalty_in_validity():
    result = scores_for({"a": [1, 2, 3], "empty": [None, None, None]})
    validity = result["dimensions"]["validity"]
    penalties = [item["penalty"] for item in validity["breakdown"]]
    assert 6 in penalties
    assert validity["score"] == pytest.approx(94.0)


def test_whitespaced_data_reduces_consistency():
    result = scores_for({"a": [" x", "y ", " z", "w"]})
    consistency = result["dimensions"]["consistency"]
    assert consistency["score"] < 100.0
    causes = [item["cause"] for item in consistency["breakdown"]]
    assert any("whitespace" in cause for cause in causes)


def test_skew_reduces_distribution_score():
    result = scores_for({"a": [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 200, 5000]})
    distribution = result["dimensions"]["distribution"]
    assert distribution["breakdown"], "highly skewed column should produce penalty"


def test_every_score_documented_with_formula_and_inputs():
    result = scores_for({"a": [1, 2, 3], "b": ["x", None, "z"]})
    for name, dimension in result["dimensions"].items():
        assert isinstance(dimension["formula"], str) and len(dimension["formula"]) > 10
        assert isinstance(dimension["breakdown"], list)
        for entry in dimension["breakdown"]:
            assert "penalty" in entry and "cause" in entry


def test_hand_recomputation_matches_reported_scores():
    """Re-implement the documented formula from scratch and compare."""
    df = {"a": [1, None, 3, 4], "b": ["x", "y", "x", "y"]}
    # completeness from formula: 100*(1 - 1/8)
    result = scores_for(df)
    assert result["dimensions"]["completeness"]["score"] == pytest.approx(87.5)
    # no duplicates in rows/columns -> uniqueness 100
    assert result["dimensions"]["uniqueness"]["score"] == 100.0
