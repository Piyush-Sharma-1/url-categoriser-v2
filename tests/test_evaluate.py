import csv

import numpy as np
import pytest
from test_model import small_model

from src import evaluate
from src.classify import load_curated, match_curated
from src.curlie_data import CATEGORIES, ROOT
from src.normalize import normalize_url, registered_domain
from src.train import UNMAPPED


def test_overall_scores_count_undefined_as_wrong():
    labels = np.array(["Sports", "Sports", "Gaming", "Email"])
    predictions = np.array(["Sports", "Undefined", "Sports", "Undefined"])
    assert evaluate.overall_scores(labels, predictions) == {"accuracy": 0.25, "coverage": 0.5, "precision on covered": 0.5}


def test_undefined_gold_label_is_correct_when_predicted():
    scores = evaluate.overall_scores(np.array(["Undefined", "Sports"]), np.array(["Undefined", "Sports"]))
    assert scores["accuracy"] == 1.0 and scores["coverage"] == 0.5


def test_lenient_accuracy_also_accepts_the_second_category():
    labels = np.array(["Meeting", "Meeting", "Sports", "Email"])
    also_acceptable = np.array(["Chat & Messaging", "Chat & Messaging", "", ""])
    predictions = np.array(["Meeting", "Chat & Messaging", "Gaming", "Undefined"])
    scores = evaluate.gold_scores(labels, also_acceptable, predictions)
    assert (scores["strict accuracy"], scores["lenient accuracy"]) == (0.25, 0.5)


def test_empty_also_acceptable_never_matches_an_answer():
    scores = evaluate.gold_scores(np.array(["Sports"]), np.array([""]), np.array(["Gaming"]))
    assert scores["lenient accuracy"] == 0.0


def test_majority_baseline_always_answers_the_commonest_label():
    majority, baseline = evaluate.majority_baseline(np.array(["Sports", "Sports", "Email"]))
    assert majority == "Sports" and baseline.tolist() == ["Sports"] * 3


def test_confused_pairs_ignore_correct_and_undefined_answers():
    labels = np.array(["Sports", "Sports", "Sports", "Email"])
    predictions = np.array(["Sports", "Gaming", "Undefined", "Gaming"])
    assert evaluate.confused_pairs(labels, predictions) == [(("Sports", "Gaming"), 1), (("Email", "Gaming"), 1)]


def test_model_report_shows_baseline_and_example_counts(capsys):
    rows = [("football-sports.example", "a", "Sports"), ("cricket-sports.example", "b", "Sports"),
            ("chess-games.example", "c", "Gaming"), ("religion.example", "d", UNMAPPED)]
    evaluate.report_model(rows, small_model(threshold=0.2))
    output = capsys.readouterr().out
    assert "3 labelled hosts and 1 unmapped hosts" in output
    assert "baseline: always Sports" in output and "macro-F1" in output
    assert any(line.startswith("Sports") and " 2 " in line for line in output.splitlines())
    assert "Unmapped hosts the model assigns a category" in output


def write_gold(path, rows, encoding="utf-8"):
    with open(path, "w", encoding=encoding, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["url", "label", "also_acceptable", "in_curated", "note"])
        writer.writeheader()
        writer.writerows(rows)


@pytest.mark.parametrize("label, also_acceptable, message", [
    ("", "", "no label"),
    ("Spots", "", "Invalid"),
    ("Sports", "Gamng", "Invalid"),
    ("Sports", "Gaming|Email", "Invalid"),  # Only one extra category is allowed.
])
def test_gold_set_must_be_fully_and_validly_labelled(tmp_path, label, also_acceptable, message):
    write_gold(tmp_path / "gold.csv", [{"url": "a.com", "label": label, "also_acceptable": also_acceptable, "in_curated": "no", "note": ""}])
    with pytest.raises(SystemExit, match=message):
        evaluate.load_gold(tmp_path / "gold.csv")


def test_gold_set_saved_by_excel_still_loads(tmp_path):
    row = {"url": "a.com", "label": "Undefined", "also_acceptable": "Sports", "in_curated": "", "note": "own"}
    write_gold(tmp_path / "gold.csv", [row], encoding="utf-8-sig")
    assert evaluate.load_gold(tmp_path / "gold.csv") == [row]


@pytest.mark.parametrize("note, tag, expected", [
    ("own", "own", True),
    ("own: HR portal", "own", True),
    ("Unknown consultancy", "own", False),
    ("major-app: Gmail inbox", "major-app", True),
    ("Non-English: German news magazine", "non-english", True),
    ("Indian job board", "indian", True),
    ("major-app: Amazon India product page", "indian", False),
])
def test_tags_match_whole_words_only(note, tag, expected):
    assert evaluate.has_tag({"note": note}, tag) is expected


def test_gold_groups_keep_tagged_rows_apart():
    rows = [{"note": "Recipes"}, {"note": "major-app: Gmail"}, {"note": "own: wiki"}, {"note": "Indian job board"}]
    groups = dict(evaluate.gold_groups(rows))
    assert groups == {
        "All rows": [0, 1, 2, 3],
        "Drafted candidates": [0, 3],
        "major-app rows": [1],
        "own rows": [2],
        "Indian and non-English rows": [3],
    }


def test_pipeline_report_shows_strict_lenient_methods_and_reasons(capsys):
    rows = [{"label": "Sports", "also_acceptable": ""}, {"label": "Undefined", "also_acceptable": ""}]
    results = [{"category": "Sports", "method": "curlie", "undefined_reason": None},
               {"category": "Undefined", "method": "undefined", "undefined_reason": "invalid_url"}]
    evaluate.report_pipeline("Example", rows, results)
    output = capsys.readouterr().out
    assert "strict accuracy" in output and "lenient accuracy" in output
    assert "curlie" in output and "{'invalid_url': 1}" in output and "baseline" in output


def test_gold_report_covers_each_group_with_and_without_the_curated_list(capsys):
    rows = [{"url": "zoom.us", "label": "Meeting", "also_acceptable": "", "note": "major-app: Zoom"},
            {"url": "banana", "label": "Undefined", "also_acceptable": "", "note": "A bare word"}]
    evaluate.report_gold(rows)
    output = capsys.readouterr().out
    assert "major-app rows, with the curated list: 1 URLs" in output
    assert "major-app rows, without the curated list: 1 URLs" in output
    assert "own rows" not in output  # An empty group is skipped.


def test_curated_overrides_only_list_real_disagreements():
    rows = [{"url": "a.com", "label": "Design"}, {"url": "b.com", "label": "Email"}, {"url": "c.com", "label": "Email"}]
    with_curated = [{"method": "curated", "category": "Design"}, {"method": "curated", "category": "Email"}, {"method": "curated", "category": "Email"}]
    without = [{"method": "curlie", "category": "Lifestyle"}, {"method": "curlie", "category": "Email"}, {"method": "model", "category": "Sports"}]
    assert evaluate.curated_overrides(rows, with_curated, without) == [("a.com", "Design", "Lifestyle", "Design")]


def test_test_set_runs_only_once(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluate, "REPORTS", tmp_path)
    (tmp_path / evaluate.TEST_REPORT).write_text("already run")
    monkeypatch.setattr(evaluate, "report_split", lambda name: pytest.fail("the test set must not run twice"))
    with pytest.raises(SystemExit, match="already been run"):
        evaluate.main(["test"])


def test_command_is_required():
    assert evaluate.main([]) == 2


with open(evaluate.GOLD_PATH, encoding="utf-8-sig", newline="") as f:
    GOLD_ROWS = list(csv.DictReader(f))


def is_exempt(row):
    """major-app rows are decided by the curated list, and own rows come from real browsing."""
    return evaluate.has_tag(row, "major-app") or evaluate.has_tag(row, "own")


def test_gold_columns_and_size():
    assert list(GOLD_ROWS[0]) == ["url", "label", "also_acceptable", "in_curated", "note"]
    assert 80 <= len(GOLD_ROWS) <= 110
    assert len({row["url"] for row in GOLD_ROWS}) == len(GOLD_ROWS)
    assert all(row["label"] in ("", "Undefined", *CATEGORIES) for row in GOLD_ROWS)


def test_gold_notes_do_not_suggest_labels():
    assert not [row["url"] for row in GOLD_ROWS if "expected" in row["note"].lower() or "undefined" in row["note"].lower()]


def test_gold_avoids_every_site_seen_while_building():
    probed = (ROOT / "data" / "mapping_probe_hosts.txt").read_text(encoding="utf-8").split()
    excluded = {registered_domain(host) for host in probed}
    hosts = [normalize_url(row["url"]) for row in GOLD_ROWS if not is_exempt(row)]
    assert not {registered_domain(normal[1]) for normal in hosts if normal} & excluded


def test_major_app_rows_are_decided_by_the_curated_list():
    curated = load_curated()
    major_apps = [row for row in GOLD_ROWS if evaluate.has_tag(row, "major-app")]
    assert len(major_apps) == 10
    for row in major_apps:
        _normalized, host, path = normalize_url(row["url"])
        assert match_curated(host, path, curated), row["url"]


def test_gold_in_curated_column_matches_the_list():
    curated = load_curated()
    for row in GOLD_ROWS:
        if evaluate.has_tag(row, "own") and not row["in_curated"]:
            continue  # Blank is fine for rows added by hand, because the evaluation does not read this column.
        normal = normalize_url(row["url"])
        in_list = bool(normal and match_curated(normal[1], normal[2], curated))
        assert row["in_curated"] == ("yes" if in_list else "no"), row["url"]


def test_wrong_rows_list_every_strict_miss_with_its_details():
    rows = [{"url": "a.com", "label": "Sports", "also_acceptable": ""}, {"url": "b.com", "label": "Email", "also_acceptable": "Meeting"}]
    results = [{"category": "Sports", "method": "curlie", "explanation": "Right."},
               {"category": "Meeting", "method": "model", "explanation": "Lenient only."}]
    assert evaluate.wrong_rows(rows, results) == [("b.com", "Email", "Meeting", "Meeting", "model", "Lenient only.")]
