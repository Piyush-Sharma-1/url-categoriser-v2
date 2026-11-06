import csv
import json

import pytest

from src.classify import CURATED_PATH, classify, load_curated, match_curated
from src.cli import main
from src.curlie_data import CATEGORIES

FIELDS = {"url", "normalized", "category", "confidence", "method", "explanation", "evidence", "alternatives", "undefined_reason"}
with open(CURATED_PATH, encoding="utf-8", newline="") as f:
    CURATED_ROWS = list(csv.DictReader(f))


def test_curated_rows_are_valid():
    assert list(CURATED_ROWS[0]) == ["host_or_prefix", "we360_category", "alternative_category", "note"]
    assert len({row["host_or_prefix"] for row in CURATED_ROWS}) == len(CURATED_ROWS)
    assert "khanacademy.org" in {row["host_or_prefix"] for row in CURATED_ROWS}
    for row in CURATED_ROWS:
        assert row["we360_category"] in CATEGORIES and row["note"]
        alternatives = row["alternative_category"].split("|") if row["alternative_category"] else []
        assert set(alternatives) <= set(CATEGORIES)


@pytest.mark.parametrize("host, path, expected", [
    ("mail.google.com", "/u/0", "mail.google.com"),  # More host labels win.
    ("maps.google.com", "", "google.com"),  # Whole labels match subdomains.
    ("notgoogle.com", "", None),  # But never part of a label.
    ("linkedin.com", "/jobs/view/1", "linkedin.com/jobs"),  # More path segments win.
    ("linkedin.com", "/jobsearch", "linkedin.com"),  # Whole segments only.
    ("uk.linkedin.com", "/jobs", "linkedin.com/jobs"),
    ("acme.atlassian.net", "/wiki/spaces/HR", "atlassian.net/wiki"),
    ("acme.atlassian.net", "/browse/ABC-1", "atlassian.net"),
])
def test_curated_matching(host, path, expected):
    row = match_curated(host, path, load_curated())
    assert (row["host_or_prefix"] if row else None) == expected


@pytest.mark.parametrize("url", ["chrome://settings", "banana", "localhost:3000", "zoom.us", "canva.com", "chess-puzzles.example"])
def test_every_result_has_all_fields(url):
    result = classify(url)
    assert set(result) == FIELDS
    assert result["url"] == url
    assert result["explanation"]


def test_curated_list_beats_curlie_and_keeps_its_answer_as_an_alternative():
    result = classify("https://www.canva.com/design")
    assert (result["category"], result["method"], result["confidence"]) == ("Design", "curated", 1.0)
    assert {"category": "Lifestyle", "confidence": 1.0} in result["alternatives"]


def test_curated_alternative_has_no_confidence():
    assert classify("teams.microsoft.com")["alternatives"][0] == {"category": "Chat & Messaging", "confidence": None}


def test_curlie_answer_when_the_curated_list_is_silent():
    result = classify("https://www.rottentomatoes.com/m/some_movie")
    assert (result["category"], result["method"]) == ("News & Entertainment", "curlie")
    assert result["evidence"] == ["Arts/Movies/Reviews/Hubs"]


def test_ai_assistant_lists_both_alternatives():
    result = classify("https://claude.ai/chat")
    assert result["category"] == "Research & Reference"
    assert [item["category"] for item in result["alternatives"]][:2] == ["Developer", "Office Apps"]


def test_deep_page_on_a_listed_site_uses_the_homepage_answer():
    assert classify("theguardian.com/world/2024/jan/01/story")["category"] == "News & Entertainment"


def test_unlisted_site_is_undefined_without_a_model(monkeypatch):
    monkeypatch.setattr("src.classify.load_model", lambda: None)
    result = classify("no-such-site-for-tests.example")
    assert (result["category"], result["undefined_reason"], result["confidence"]) == ("Undefined", "model_unavailable", 0.0)


def test_cli_prints_json(capsys):
    assert main(["https://zoom.us"]) == 0
    assert json.loads(capsys.readouterr().out)["category"] == "Meeting"


def test_cli_requires_a_url(capsys):
    assert main([]) == 2
