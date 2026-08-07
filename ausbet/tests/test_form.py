"""Racing form loader + probability model tests."""

from __future__ import annotations

from pathlib import Path

import pytest

import ausbet
from ausbet.form import (
    FormRunner,
    form_probabilities,
    load_form,
    load_form_csv,
    load_form_json,
    race_scan,
)

SAMPLE_FORM = Path(ausbet.__file__).resolve().parent / "data" / "sample_form.csv"


def test_load_form_csv():
    runners = load_form_csv(SAMPLE_FORM)
    assert len(runners) == 8
    mo = next(r for r in runners if r.name == "Mighty Mo")
    assert mo.number == 1
    assert mo.weight == 58.5
    assert mo.form_figures == "231x45"
    assert mo.career_starts == 12
    assert mo.career_wins == 3
    assert mo.last_start == 5
    assert not mo.scratched


def test_scratched_flag_parsed():
    runners = load_form_csv(SAMPLE_FORM)
    velvet = next(r for r in runners if r.name == "Velvet Hammer")
    assert velvet.scratched


def test_recent_finishes_ignores_x():
    r = FormRunner(number=1, name="A", form_figures="231x45")
    assert r.recent_finishes == [1, 4, 5]
    assert FormRunner(number=1, name="B").recent_finishes == []


def test_last_start_defaults_from_form_figures(tmp_path):
    r = FormRunner(number=1, name="C", form_figures="1123")
    assert r.last_start is None  # explicit field only
    j = tmp_path / "f.json"
    j.write_text('{"runners": [{"number": 1, "name": "D", "form_figures": "1123"}]}', encoding="utf-8")
    assert load_form_json(j)[0].last_start == 3  # loader fills from figures


def test_probabilities_sum_to_one_and_exclude_scratches():
    runners = load_form_csv(SAMPLE_FORM)
    probs = form_probabilities(runners)
    assert "Velvet Hammer" not in probs
    assert len(probs) == 7
    assert sum(probs.values()) == pytest.approx(1.0, abs=0.005)
    for p in probs.values():
        assert 0.0 < p < 1.0


def test_unraced_runner_gets_floor_probability():
    runners = load_form_csv(SAMPLE_FORM)
    runners[0].last_start = None
    runners[0].form_figures = ""
    probs = form_probabilities(runners)
    assert probs["Mighty Mo"] > 0.0


def test_all_scratched_raises():
    runners = load_form_csv(SAMPLE_FORM)
    for r in runners:
        r.scratched = True
    with pytest.raises(ValueError, match="scratched"):
        form_probabilities(runners)


def test_race_scan_finds_value_pick():
    runners = load_form_csv(SAMPLE_FORM)
    probs, picks = race_scan(
        runners,
        [("Mighty Mo", 6.00), ("Rocket Red", 6.50), ("Lucky Lass", 7.50)],
    )
    assert probs["Rocket Red"] > probs["Mighty Mo"]  # model favours Rocket Red
    by_name = {p.selection: p for p in picks}
    assert by_name["Rocket Red"].is_value  # 6.50 vs fair ~5.05
    assert not by_name["Mighty Mo"].is_value  # 6.00 vs fair ~6.4
    assert picks[0].selection == "Rocket Red"


def test_race_scan_without_odds_returns_probs_only():
    runners = load_form_csv(SAMPLE_FORM)
    probs, picks = race_scan(runners)
    assert picks == []
    assert len(probs) == 7


def test_load_form_dispatch_by_suffix(tmp_path):
    assert len(load_form(SAMPLE_FORM)) == 8
    j = tmp_path / "form.json"
    j.write_text('{"runners": [{"number": 1, "name": "E"}]}', encoding="utf-8")
    assert load_form(j)[0].name == "E"


def test_empty_form_raises(tmp_path):
    empty = tmp_path / "empty.csv"
    empty.write_text("number,name\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no runners"):
        load_form(empty)
