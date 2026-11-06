import csv

import numpy as np
import pytest
from test_model import small_model

from scripts.classify_with_v1 import main as classify_with_v1
from scripts.confusion_matrix import confusion_counts
from src import evaluate
from src.classify import load_curated, match_curated
from src.curlie_data import CATEGORIES, ROOT
from src.normalize import normalize_url, registered_domain, system_scheme
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
    row = {"url": "a.com", "label": "Undefined", "also_acceptable": "Sports", "in_curated": "", "note": "Recipes"}
    write_gold(tmp_path / "gold.csv", [row], encoding="utf-8-sig")
    assert evaluate.load_gold(tmp_path / "gold.csv") == [row]


@pytest.mark.parametrize("note, tag, expected", [
    ("Indiana sports", "indian", False),
    ("major-app: Gmail inbox", "major-app", True),
    ("Non-English: German news magazine", "non-english", True),
    ("Indian job board", "indian", True),
    ("major-app: Amazon India product page", "indian", False),
])
def test_tags_match_whole_words_only(note, tag, expected):
    assert evaluate.has_tag({"note": note}, tag) is expected


def test_gold_groups_keep_tagged_rows_apart():
    rows = [{"note": "Recipes"}, {"note": "major-app: Gmail"}, {"note": "Indian job board"}]
    groups = dict(evaluate.gold_groups(rows))
    assert groups == {
        "All rows": [0, 1, 2],
        "Drafted candidates": [0, 2],
        "major-app rows": [1],
        "Indian and non-English rows": [2],
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
    rows = [{"url": "slack.com", "label": "Chat & Messaging", "also_acceptable": "", "note": "major-app: Slack"},
            {"url": "banana", "label": "Undefined", "also_acceptable": "", "note": "A bare word"}]
    evaluate.report_gold(rows)
    output = capsys.readouterr().out
    assert "major-app rows, with the curated list: 1 URLs" in output
    assert "major-app rows, without the curated list: 1 URLs" in output
    assert "Indian and non-English rows" not in output  # An empty group is skipped.


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
    hosts = [normalize_url(row["url"]) for row in GOLD_ROWS if not evaluate.has_tag(row, "major-app")]  # The curated list decides those.
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
        normal = normalize_url(row["url"])
        in_list = bool(normal and match_curated(normal[1], normal[2], curated))
        assert row["in_curated"] == ("yes" if in_list else "no"), row["url"]


def test_wrong_rows_list_every_strict_miss_with_its_details():
    rows = [{"url": "a.com", "label": "Sports", "also_acceptable": ""}, {"url": "b.com", "label": "Email", "also_acceptable": "Meeting"}]
    results = [{"category": "Sports", "method": "curlie", "explanation": "Right."},
               {"category": "Meeting", "method": "model", "explanation": "Lenient only."}]
    assert evaluate.wrong_rows(rows, results) == [("b.com", "Email", "Meeting", "Meeting", "model", "Lenient only.")]


# The new gold set.

with open(evaluate.GOLD_V2_PATH, encoding="utf-8", newline="") as f:
    GOLD_V2_ROWS = list(csv.DictReader(f))


def hosts_on_real_domains(rows):
    parsed = [normalize_url(row["url"]) for row in rows if not system_scheme(row["url"])]
    return [normal[1] for normal in parsed if normal]  # The original gold set includes invalid URLs on purpose.


def test_gold_v2_format():
    assert list(GOLD_V2_ROWS[0]) == ["url", "label", "also_acceptable", "in_curated", "note"]
    assert len({row["url"] for row in GOLD_V2_ROWS}) == len(GOLD_V2_ROWS) == 54
    assert {row["note"] for row in GOLD_V2_ROWS} == {"v2-new"}
    assert evaluate.load_gold(evaluate.GOLD_V2_PATH) == GOLD_V2_ROWS


def test_gold_v2_avoids_original_gold_and_probe_domains():
    probed = (ROOT / "data" / "mapping_probe_hosts.txt").read_text(encoding="utf-8").split()
    excluded = {registered_domain(host) for host in probed + hosts_on_real_domains(GOLD_ROWS)}
    assert not {registered_domain(host) for host in hosts_on_real_domains(GOLD_V2_ROWS)} & excluded


def test_gold_v2_leaves_out_the_dropped_rows():
    assert not {"https://www.semrush.com/", "https://www.gov.uk/"} & {row["url"] for row in GOLD_V2_ROWS}


def test_gold_v2_in_curated_column_matches_the_list():
    curated = load_curated()
    for row in GOLD_V2_ROWS:
        normal = normalize_url(row["url"])
        in_list = bool(normal and match_curated(normal[1], normal[2], curated))
        assert row["in_curated"] == ("yes" if in_list else "no"), row["url"]


# Comparing the versions.

@pytest.mark.parametrize("share, total, low, high", [
    (0.5, 10, 0.2366, 0.7634),
    (0.0, 10, 0.0, 0.2775),
    (1.0, 10, 0.7225, 1.0),
])
def test_wilson_interval(share, total, low, high):
    assert evaluate.wilson_interval(share, total) == pytest.approx((low, high), abs=0.0001)


COMPARED_ROWS = [
    {"url": "a.com", "label": "Sports", "also_acceptable": ""},
    {"url": "b.com", "label": "Email", "also_acceptable": "Meeting"},
    {"url": "c.com", "label": "Undefined", "also_acceptable": ""},
    {"url": "d.com", "label": "Gaming", "also_acceptable": ""},
    {"url": "e.com", "label": "Design", "also_acceptable": ""},
]


def answer(category, method, reason=None):
    return {"category": category, "method": method, "undefined_reason": reason, "evidence": [f"{method} evidence"]}


COMPARED_VERSIONS = {
    "v1": [answer("Undefined", "undefined", "model_low_confidence"), answer("Meeting", "model"),
           answer("Undefined", "undefined", "curlie_unmapped"), answer("Undefined", "undefined", "model_low_confidence"), answer("Design", "curated")],
    "v2": [answer("Sports", "ut1"), answer("Meeting", "model"), answer("Shopping", "ut1"),
           answer("Undefined", "undefined", "ut1_ambiguous"), answer("Design", "curated")],
}


@pytest.mark.parametrize("category, status", [
    ("Email", "right"), ("Meeting", "also acceptable"), ("Undefined", "undefined"), ("Sports", "wrong"),
])
def test_answer_status(category, status):
    assert evaluate.answer_status({"label": "Email", "also_acceptable": "Meeting"}, category) == status


def test_undefined_is_right_when_the_label_is_undefined():
    assert evaluate.answer_status({"label": "Undefined", "also_acceptable": ""}, "Undefined") == "right"


def test_version_scores_separate_wrong_answers_from_undefined():
    scores = evaluate.version_scores(COMPARED_ROWS, [result["category"] for result in COMPARED_VERSIONS["v2"]])
    assert scores == pytest.approx({
        "strict accuracy": 2 / 5,
        "lenient accuracy": 3 / 5,
        "coverage": 4 / 5,
        "precision on covered": 2 / 4,
        "precision on covered, lenient": 3 / 4,
        "wrong-answer rate, strict": 2 / 5,
        "wrong-answer rate, lenient": 1 / 5,
    })


def test_versions_report_shows_intervals_baseline_and_pairs(capsys):
    evaluate.report_versions("Example", COMPARED_ROWS, COMPARED_VERSIONS)
    output = capsys.readouterr().out
    assert "strict accuracy, 95% interval" in output and "lenient accuracy, 95% interval" in output
    assert "always " in output and "v1" in output and "v2" in output
    assert "Strict: both right 1, only v1 right 1, only v2 right 1, both missed 2" in output


def test_pipeline_report_breaks_out_ut1(capsys):
    evaluate.report_pipeline("Example", COMPARED_ROWS, COMPARED_VERSIONS["v2"])
    output = capsys.readouterr().out
    assert any(line.strip().startswith("ut1 ") for line in output.splitlines())
    assert "'ut1_ambiguous': 1" in output


def test_missed_rows_list_a_row_either_version_missed(capsys):
    evaluate.report_missed_rows(COMPARED_ROWS, COMPARED_VERSIONS)
    output = capsys.readouterr().out
    assert all(url in output for url in ("a.com", "b.com", "c.com", "d.com"))
    assert "e.com" not in output  # Both versions got this right.
    assert "Undefined (undefined, ut1_ambiguous; undefined)" in output


def test_ut1_rows_include_undefined_decisions_only_from_ut1(capsys):
    evaluate.report_ut1_rows(COMPARED_ROWS, COMPARED_VERSIONS)
    output = capsys.readouterr().out
    assert all(url in output for url in ("a.com", "c.com", "d.com"))
    assert "b.com" not in output and "e.com" not in output


def test_by_label_counts_ut1_answers(capsys):
    evaluate.report_by_label(COMPARED_ROWS, COMPARED_VERSIONS)
    lines = capsys.readouterr().out.splitlines()
    assert next(line for line in lines if line.startswith("Sports")).split() == ["Sports", "1", "0", "1", "1", "1"]
    assert next(line for line in lines if line.startswith("Undefined")).split() == ["Undefined", "1", "1", "0", "1", "0"]


def test_load_predictions_keeps_gold_order_and_restores_empty_reasons(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluate, "REPORTS", tmp_path)
    (tmp_path / "saved.csv").write_text("url,category,method,undefined_reason,confidence\nb.com,Email,curated,,1.0\na.com,Undefined,undefined,invalid_url,0.0\n")
    results = evaluate.load_predictions("saved.csv", [{"url": "a.com"}, {"url": "b.com"}])
    assert [result["url"] for result in results] == ["a.com", "b.com"]
    assert (results[0]["undefined_reason"], results[1]["undefined_reason"]) == ("invalid_url", None)


def test_load_predictions_refuses_a_different_gold_set(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluate, "REPORTS", tmp_path)
    (tmp_path / "saved.csv").write_text("url,category,method,undefined_reason,confidence\nb.com,Email,curated,,1.0\n")
    with pytest.raises(SystemExit, match="doesn't match"):
        evaluate.load_predictions("saved.csv", [{"url": "a.com"}])


@pytest.mark.parametrize("command, report", [("gold", "gold_posthoc_report.txt"), ("gold-v2", "gold_v2_report.txt")])
def test_gold_commands_leave_the_version_1_report_alone(monkeypatch, command, report):
    written = []
    monkeypatch.setattr(evaluate, "write_report", lambda name, function: written.append(name))
    assert evaluate.main([command]) == 0
    assert written == [report]


def test_version_1_script_refuses_version_2_code(tmp_path):
    with pytest.raises(SystemExit, match="version 2's code"):
        classify_with_v1(tmp_path / "gold.csv", tmp_path / "out.csv")


def test_confusion_counts_have_a_row_per_true_category_and_undefined_last():
    labels = np.array(["Sports", "Sports", "Email", "Email"])
    predictions = np.array(["Sports", "Undefined", "Sports", "Gaming"])
    rows, columns, counts = confusion_counts(labels, predictions)
    assert rows == ["Email", "Sports"]
    assert columns == ["Email", "Gaming", "Sports", "Undefined"]
    assert counts.tolist() == [[0, 1, 1, 0], [0, 0, 1, 1]]
