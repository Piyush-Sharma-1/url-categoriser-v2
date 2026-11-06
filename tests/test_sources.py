import csv
import hashlib

import pytest

from src.build_sources import decide_hosts, group_rows, load_mapping, usable_categories
from src.classify import classify
from src.curlie_data import CATEGORIES, ROOT
from src.sources import UT1_FOLDER, load_source_lookup, matching_entry, source_decision
from src.ut1 import load_ut1_rows

with open(UT1_FOLDER / "mapping.csv", encoding="utf-8", newline="") as f:
    MAPPING_ROWS = list(csv.DictReader(f))
EXCLUDED = {"child", "liste_blanche", "liste_bu", "exceptions_liste_bu", "special", "reaffected", "dynamic-dns",
            "strict_redirector", "strong_redirector", "examen_pix", "tricheur_pix"}

MAPPING = {
    "bank": {"we360_category": "Banking & Finance", "status": "confident"},
    "shopping": {"we360_category": "Shopping", "status": "confident"},
    "blog": {"we360_category": "Social Media|News & Entertainment", "status": "ambiguous"},
    "malware": {"we360_category": "", "status": "unmapped"},
    "phishing": {"we360_category": "", "status": "unmapped"},
}


def fake_source(hosts):
    decisions = decide_hosts(hosts, MAPPING, "ut1")
    return {"name": "ut1", "label": "UT1", "load": lambda: decisions}


# The mapping.

def test_mapping_columns_are_exact_and_the_curlie_map_is_unchanged():
    assert list(MAPPING_ROWS[0]) == ["source_category", "we360_category", "status", "note"]
    with open(ROOT / "data" / "taxonomy_map.csv", encoding="utf-8", newline="") as f:
        assert next(csv.reader(f)) == ["curlie_path", "we360_category", "status", "note"]


@pytest.mark.parametrize("row", MAPPING_ROWS, ids=lambda row: row["source_category"])
def test_mapping_row_is_valid(row):
    assert row["note"].strip()
    names = row["we360_category"].split("|") if row["we360_category"] else []
    if row["status"] == "confident":
        assert len(names) == 1
    elif row["status"] == "ambiguous":
        assert len(names) >= 2
    else:
        assert row["status"] in ("unmapped", "excluded") and not names
    assert set(names) <= set(CATEGORIES)


def test_mapping_decisions():
    by_name = {row["source_category"]: row for row in MAPPING_ROWS}
    assert len(by_name) == len(MAPPING_ROWS) == 69
    assert {name for name, row in by_name.items() if row["status"] == "excluded"} == EXCLUDED
    assert by_name["jobsearch"]["status"] == by_name["publicite"]["status"] == "unmapped"
    assert not set(usable_categories(load_mapping(UT1_FOLDER))) & EXCLUDED


# The loader.

def write_list(folder, category, text):
    (folder / category).mkdir()
    (folder / category / "domains").write_text(text, encoding="utf-8")


def test_loader_returns_normalised_hosts_with_their_category(tmp_path):
    write_list(tmp_path, "bank", "# a comment\n\nWWW.Example-Bank.com\nsecure.other.com\nbad host\nsite.com/path\n")
    rows = list(load_ut1_rows(["bank"], tmp_path))
    assert rows == [("example-bank.com", "bank"), ("secure.other.com", "bank")]


def test_loader_never_reads_a_list_it_was_not_given(tmp_path):
    write_list(tmp_path, "bank", "bank.com\n")
    write_list(tmp_path, "examen_pix", "secret.example\n")
    assert list(load_ut1_rows(["bank"], tmp_path)) == [("bank.com", "bank")]


def test_each_list_counts_once_per_host():
    rows = [("a.com", "bank"), ("a.com", "bank"), ("a.com", "shopping"), ("b.com", "bank")]
    assert group_rows(rows) == {"a.com": ["bank", "shopping"], "b.com": ["bank"]}


# Precomputing decisions.

@pytest.mark.parametrize("lists, category, confidence, reason", [
    (["bank"], "Banking & Finance", 1.0, None),
    (["bank", "shopping"], None, 0.0, "ut1_split_votes"),
    (["bank", "malware", "phishing"], None, 0.0, "ut1_split_votes"),  # Unmapped lists count in the denominator.
    (["blog"], None, 0.0, "ut1_ambiguous"),
])
def test_decision_applies_the_vote_rule(lists, category, confidence, reason):
    decision = decide_hosts({"site.com": lists}, MAPPING, "ut1")["site.com"]
    assert (decision["category"], decision["confidence"], decision["reason"]) == (category, confidence, reason)
    assert decision["lists"] == lists


def test_undecided_hosts_keep_their_candidates():
    assert {item["category"] for item in decide_hosts({"a.com": ["blog"]}, MAPPING, "ut1")["a.com"]["alternatives"]} == {"Social Media", "News & Entertainment"}
    assert decide_hosts({"a.com": ["bank", "malware"]}, MAPPING, "ut1")["a.com"]["alternatives"][0]["category"] == "Banking & Finance"


def test_hosts_listed_only_in_unmapped_lists_are_left_out():
    assert decide_hosts({"bad.com": ["malware", "phishing"]}, MAPPING, "ut1") == {}


# Host-scoped matching.

HOSTS = {
    "copilot.microsoft.com": "ai",
    "jpager.yahoo.com": "chat",
    "fg.download.windowsupdate.com.c.footprint.net": "update",
    "bankofamerica.com": "bank",
    "shop.bankofamerica.com": "shopping",
    "blogspot.com": "blog",
}


@pytest.mark.parametrize("host", [
    "learn.microsoft.com",  # A copilot.microsoft.com entry does not label a sibling.
    "microsoft.com",
    "mail.yahoo.com",  # A jpager.yahoo.com entry does not label a sibling.
    "other.footprint.net",  # A footprint.net subdomain entry does not label other footprint.net hosts.
    "footprint.net",
    "notbankofamerica.com",  # Whole labels only.
    "bankofamerica.com.evil.net",
    "myblog.blogspot.com",  # Each blog is its own registered domain, so matching stops before blogspot.com.
])
def test_an_entry_does_not_label_sibling_or_lookalike_hosts(host):
    assert matching_entry(host, HOSTS) is None


@pytest.mark.parametrize("host, entry", [
    ("copilot.microsoft.com", "copilot.microsoft.com"),
    ("eu.copilot.microsoft.com", "copilot.microsoft.com"),
    ("bankofamerica.com", "bankofamerica.com"),
    ("secure.bankofamerica.com", "bankofamerica.com"),  # A bankofamerica.com entry labels its subdomains.
    ("shop.bankofamerica.com", "shop.bankofamerica.com"),  # The longest entry wins.
    ("a.shop.bankofamerica.com", "shop.bankofamerica.com"),
])
def test_an_entry_labels_its_own_host_and_subdomains(host, entry):
    assert matching_entry(host, HOSTS) == entry


def test_decision_uses_only_the_longest_entry():
    decision = source_decision("x.site.com", fake_source({"site.com": ["bank"], "x.site.com": ["blog"]}))
    assert (decision["entry"], decision["reason"]) == ("x.site.com", "ut1_ambiguous")


def test_no_decision_without_a_matching_entry():
    assert source_decision("site.com", fake_source({"other.com": ["bank"]})) is None


# The pipeline step.

UNLISTED = "only-in-ut1-for-tests.example"


def test_ut1_answers_a_site_no_earlier_step_knows():
    result = classify(f"https://www.{UNLISTED}/page", sources=(fake_source({UNLISTED: ["bank"]}),))
    assert (result["category"], result["method"], result["confidence"]) == ("Banking & Finance", "ut1", 1.0)
    assert result["undefined_reason"] is None
    assert "bank" in result["explanation"] and UNLISTED in result["explanation"]
    assert f"UT1 entry: {UNLISTED}" in result["evidence"]


def test_ut1_answers_when_curlie_lists_a_site_without_a_category():
    result = classify("angelfire.com", sources=(fake_source({"angelfire.com": ["shopping"]}),))
    assert (result["category"], result["method"]) == ("Shopping", "ut1")


def test_curlie_reason_stands_when_ut1_gives_no_category():
    assert classify("angelfire.com", sources=(fake_source({}),))["undefined_reason"] == "curlie_split_votes"
    assert classify("angelfire.com", sources=(fake_source({"angelfire.com": ["blog"]}),))["undefined_reason"] == "curlie_split_votes"


def test_earlier_steps_win_over_ut1():
    source = (fake_source({"slack.com": ["bank"], "rottentomatoes.com": ["bank"]}),)
    assert classify("slack.com", sources=source)["method"] == "curated"
    assert classify("rottentomatoes.com", sources=source)["method"] == "curlie"
    assert classify("localhost:3000", sources=source)["method"] == "rule"


@pytest.mark.parametrize("lists, reason", [(["bank", "shopping"], "ut1_split_votes"), (["blog"], "ut1_ambiguous")])
def test_ut1_undefined_reasons_stop_the_model(lists, reason):
    result = classify(UNLISTED, sources=(fake_source({UNLISTED: lists}),))
    assert (result["category"], result["method"], result["undefined_reason"]) == ("Undefined", "undefined", reason)
    assert f"UT1 entry: {UNLISTED}" in result["evidence"] and result["explanation"]


def test_a_host_only_in_unmapped_lists_reaches_the_model():
    result = classify("chess-puzzle-club-for-tests.example", sources=(fake_source({"chess-puzzle-club-for-tests.example": ["malware"]}),))
    assert result["method"] == "model" or result["undefined_reason"] == "model_low_confidence"


# The shipped lookup.

def test_shipped_lookup_has_no_excluded_list_and_no_unmapped_only_host():
    decisions = load_source_lookup(UT1_FOLDER)
    assert decisions
    for decision in decisions.values():
        assert not set(decision["lists"]) & EXCLUDED
        assert decision["category"] or decision["reason"] in ("ut1_split_votes", "ut1_ambiguous")


@pytest.mark.parametrize("host, not_entry", [
    ("learn.microsoft.com", "copilot.microsoft.com"),
    ("mail.yahoo.com", "jpager.yahoo.com"),
    ("other.footprint.net", "fg.download.windowsupdate.com.c.footprint.net"),
])
def test_shipped_lookup_does_not_label_siblings(host, not_entry):
    assert matching_entry(host, load_source_lookup(UT1_FOLDER)) != not_entry


def test_shipped_lookup_labels_a_subdomain():
    assert matching_entry("secure.bankofamerica.com", load_source_lookup(UT1_FOLDER)) == "bankofamerica.com"


def test_licence_notice_is_complete():
    notice = (UT1_FOLDER / "README.md").read_text(encoding="utf-8")
    for required in ("CC BY-SA 4.0", "https://creativecommons.org/licenses/by-sa/4.0/", "https://dsi.ut-capitole.fr/blacklists/", "What was changed"):
        assert required in notice


# Version 1 stays unchanged.

@pytest.mark.parametrize("path, checksum", [
    ("data/model.joblib", "a3854ba22d4b3abf"),
    ("data/lookup.json.gz", "b3039fa44b6863cb"),
    ("data/taxonomy_map.csv", "a455d6cdb1948832"),
    ("data/known_domains.csv", "ec2b7f9654b4edfe"),
])
def test_version_1_files_are_unchanged(path, checksum):
    assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest().startswith(checksum)


def test_training_does_not_use_extra_sources():
    source = (ROOT / "src" / "train.py").read_text(encoding="utf-8").lower()
    assert "ut1" not in source and "src.sources" not in source
