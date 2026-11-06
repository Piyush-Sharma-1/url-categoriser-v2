import csv

import pytest

from src.curlie_data import CATEGORIES, IGNORED_BRANCHES, MAP_PATH, load_map, match_row

with open(MAP_PATH, encoding="utf-8", newline="") as f:
    ROWS = list(csv.DictReader(f))
TAXONOMY = load_map()


def test_columns_are_exact():
    assert list(ROWS[0]) == ["curlie_path", "we360_category", "status", "note"]


def test_paths_are_unique():
    assert len(TAXONOMY) == len(ROWS)


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row["curlie_path"])
def test_row_is_valid(row):
    assert row["note"].strip()
    assert row["curlie_path"].split("/")[0] not in IGNORED_BRANCHES | {"Top"}
    assert "*" not in row["curlie_path"]
    names = row["we360_category"].split("|") if row["we360_category"] else []
    if row["status"] == "confident":
        assert len(names) == 1
    elif row["status"] == "ambiguous":
        assert len(names) >= 2
    else:
        assert row["status"] == "unmapped" and not names
    assert set(names) <= set(CATEGORIES)


@pytest.mark.parametrize("branch", ["Adult", "Arts", "Business", "Computers", "Games", "Health", "Home", "News", "Recreation",
                                    "Reference", "Science", "Shopping", "Society", "Sports"])
def test_every_retained_branch_has_a_default(branch):
    assert branch in TAXONOMY


@pytest.mark.parametrize("path, expected", [
    ("Adult/Arts", "Adult"),  # Adult listings stay as unmapped votes.
    ("Sports/Cricket/Teams", "Sports"),
    ("Reference/Education/Colleges", "Reference/Education"),  # A deeper row beats its parent.
    ("Business/Healthcare/Employment/Recruitment_and_Staffing/Recruiters", "Business/Healthcare/Employment/Recruitment_and_Staffing"),
    ("Business/Financial_Services/Employment", "Business/Financial_Services/Employment"),  # Not Banking & Finance.
    ("Computers/Internet_Fax", "Computers"),  # Whole segments only: not Computers/Internet.
])
def test_longest_whole_segment_prefix_wins(path, expected):
    assert match_row(path, TAXONOMY)["curlie_path"] == expected


def test_unknown_branch_has_no_match():
    assert match_row("NotInTheMap/Foo", TAXONOMY) is None
