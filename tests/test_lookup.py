import pytest

from src.lookup import curlie_lookup, vote

SPORTS, GAMES, RETAIL, SOCIETY = 0, 1, 2, 3
TAXONOMY = {
    "Sports": {"curlie_path": "Sports", "we360_category": "Sports", "status": "confident"},
    "Games": {"curlie_path": "Games", "we360_category": "Gaming", "status": "confident"},
    "Retail": {"curlie_path": "Retail", "we360_category": "E-commerce|Shopping", "status": "ambiguous"},
    "Society": {"curlie_path": "Society", "we360_category": "", "status": "unmapped"},
}
LOOKUP = {
    "paths": ["Sports", "Games", "Retail", "Society"],
    # Each host is [homepage listings, deep-page listings].
    "hosts": {
        "solo.com": [[SPORTS], []],
        "withdeep.com": [[SPORTS], [GAMES, GAMES, GAMES]],
        "majority.com": [[SPORTS, SPORTS, SPORTS, GAMES, SOCIETY], []],
        "split.com": [[SPORTS, GAMES], []],
        "halfunmapped.com": [[SPORTS, SOCIETY], []],
        "ambiguous.com": [[RETAIL], []],
        "unmapped.com": [[SOCIETY], []],
        "deep.com": [[], [SPORTS, GAMES]],
        "news.parent.com": [[GAMES], []],
        "www2.parent.com": [[SPORTS], []],
        "agree.sibling.com": [[SPORTS], []],
        "also.sibling.com": [[SPORTS], [GAMES]],
        "only.deepsub.com": [[], [GAMES]],
    },
    "domain_hosts": {
        "parent.com": ["news.parent.com", "www2.parent.com"],
        "sibling.com": ["agree.sibling.com", "also.sibling.com"],
        "deepsub.com": ["only.deepsub.com"],
    },
}


def run(host):
    return curlie_lookup(host, LOOKUP, TAXONOMY)


@pytest.mark.parametrize("host, category, confidence", [
    ("solo.com", "Sports", 1.0),
    ("withdeep.com", "Sports", 1.0),  # Deep-page listings never vote when a homepage listing exists.
    ("majority.com", "Sports", 0.6),  # Exactly 60% is enough, counting all listings.
    ("news.parent.com", "Gaming", 1.0),  # The same host comes before the registered domain.
    ("unlisted.sibling.com", "Sports", 1.0),  # Otherwise, homepage listings of any host under the domain.
])
def test_category(host, category, confidence):
    decision = run(host)
    assert (decision["category"], decision["confidence"], decision["reason"]) == (category, confidence, None)


@pytest.mark.parametrize("host, reason, candidates", [
    ("split.com", "curlie_split_votes", {"Sports", "Gaming"}),
    ("unlisted.parent.com", "curlie_split_votes", {"Sports", "Gaming"}),
    ("halfunmapped.com", "curlie_split_votes", {"Sports"}),  # Unmapped listings count in the denominator.
    ("ambiguous.com", "curlie_ambiguous", {"E-commerce", "Shopping"}),
    ("unmapped.com", "curlie_unmapped", set()),
    ("deep.com", "curlie_deep_page_only", {"Sports", "Gaming"}),
    ("another.deepsub.com", "curlie_deep_page_only", {"Gaming"}),
])
def test_undefined(host, reason, candidates):
    decision = run(host)
    assert (decision["category"], decision["confidence"], decision["reason"]) == (None, 0.0, reason)
    assert {item["category"] for item in decision["alternatives"]} == candidates


def test_a_share_just_below_60_percent_does_not_pass_after_rounding():
    rows = [TAXONOMY["Sports"]] * 1499 + [TAXONOMY["Society"]] * 1001  # 59.96%, which rounds to 0.600.
    category, confidence, reason, alternatives = vote(rows)
    assert (category, confidence, reason) == (None, 0.0, "curlie_split_votes")
    assert alternatives[0] == {"category": "Sports", "confidence": 0.6}


def test_unlisted_site_goes_to_the_model():
    assert run("nowhere.com") is None


def test_evidence_lists_curlie_paths():
    assert run("unmapped.com")["evidence"] == ["Society"]
