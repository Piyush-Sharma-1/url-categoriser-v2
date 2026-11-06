import numpy as np
import pytest

from src.classify import classify
from src.model import MODEL_PATH, load_model, predict, url_to_text
from src.train import UNMAPPED, choose_threshold, fit_model, load_examples, score_rows, split_examples, threshold_table


@pytest.mark.parametrize("host, expected", [
    ("chess-puzzles.net", "chess puzzles net"),
    ("www.Example.COM", "example com"),
    ("xn--e1afmkfd.xn--p1ai", "e1afmkfd p1ai"),
    ("my_site.co.uk", "my site co uk"),
])
def test_url_to_text(host, expected):
    assert url_to_text(host) == expected


def small_model(threshold=0.0):
    texts = ["chess games play", "poker games play", "football sports team", "cricket sports team", "bank money loan", "credit money loan"]
    labels = ["Gaming", "Gaming", "Sports", "Sports", "Banking & Finance", "Banking & Finance"]
    model = fit_model(texts, labels)
    model["threshold"] = threshold
    return model


def test_prediction_gives_category_other_candidates_and_ngrams():
    category, score, alternatives, evidence = predict("football-sports.example", small_model())
    assert category == "Sports" and 0 < score <= 1
    assert len(alternatives) == 2 and "Sports" not in [item["category"] for item in alternatives]
    assert 1 <= len(evidence) <= 5 and evidence[0].startswith("N-gram")


def test_prediction_below_threshold_has_no_category():
    category, score, alternatives, evidence = predict("football-sports.example", small_model(threshold=0.99))
    assert (category, score, evidence) == (None, 0.0, [])
    assert len(alternatives) == 3


def test_url_with_no_known_ngram_is_never_covered():
    model = small_model()
    assert predict("zzqqxx.zzqq", model) == (None, 0.0, [], [])
    assert score_rows([("zzqqxx.zzqq", "d", "Sports")], model)[0][0] == -1.0


def test_threshold_table_measures_coverage_and_precision():
    table = threshold_table(np.array([0.9, 0.5, -1.0, 0.1]), np.array([True, False, True, True]))
    assert table[0] == (0.0, 0.75, 2 / 3)  # A score of -1 is not covered even at threshold 0.
    assert table[2] == (0.1, 0.75, 2 / 3)
    assert table[10] == (0.5, 0.5, 0.5)
    assert table[19] == (0.95, 0.0, 0.0)


@pytest.mark.parametrize("table, expected", [
    ([(0.0, 1.0, 0.5), (0.05, 0.6, 0.8), (0.1, 0.3, 0.9)], (0.05, True)),  # The lowest that reaches 0.80.
    ([(0.0, 1.0, 0.5), (0.05, 0.2, 0.7), (0.1, 0.05, 0.79)], (0.05, False)),  # Otherwise most precise with 10% coverage.
])
def test_choose_threshold(table, expected):
    assert choose_threshold(table) == expected


def test_examples_use_one_row_per_host_from_homepage_listings_only():
    listings = [
        (("sports.com", "sports.com", ""), "Sports"),
        (("sports.com", "sports.com", ""), "Sports"),
        (("sports.com", "sports.com", ""), "Games"),
        (("sports.com/chess", "sports.com", "/chess"), "Games"),  # Deep pages don't vote or add examples.
        (("deep-only.com/a", "deep-only.com", "/a"), "Sports"),
        (("split.com", "split.com", ""), "Sports"),
        (("split.com", "split.com", ""), "Games"),
        (("society.com", "society.com", ""), "Society"),
        (None, "Sports"),
    ]
    assert load_examples(listings) == [("sports.com", "sports.com", "Sports"), ("society.com", "society.com", UNMAPPED)]


def make_examples():
    examples = []
    for domain_number in range(200):
        for host_number in range(60 if domain_number == 0 else 2):
            examples.append((f"a{host_number}.site{domain_number}.com", f"site{domain_number}.com", "Sports"))
            examples.append((f"b{host_number}.site{domain_number}.com", f"site{domain_number}.com", UNMAPPED))
    return examples


def test_each_domain_is_in_exactly_one_split():
    splits = split_examples(make_examples())
    domains = [{row[1] for row in splits[name]} for name in ("train", "validation", "test")]
    assert not (domains[0] & domains[1] or domains[0] & domains[2] or domains[1] & domains[2])
    assert 130 <= len(domains[0]) <= 150


def test_unmapped_rows_stay_out_of_training_only():
    splits = split_examples(make_examples())
    assert all(row[2] != UNMAPPED for row in splits["train"])
    assert any(row[2] == UNMAPPED for row in splits["validation"])
    assert any(row[2] == UNMAPPED for row in splits["test"])


def test_caps_and_minimum_examples():
    examples = [(f"big.com/{i}", "big.com", "Sports") for i in range(500)]
    examples += [(f"s{i}.com/{j}", f"s{i}.com", "Sports") for i in range(4000) for j in range(1)]
    examples += [(f"t{i}.com", f"t{i}.com", "Meeting") for i in range(20)]
    train = split_examples(examples)["train"]
    labels = [row[2] for row in train]
    assert sum(row[1] == "big.com" for row in train) <= 50
    assert labels.count("Sports") == 2000
    assert "Meeting" not in labels  # Fewer than 50 training examples keeps a category out of the model.


def test_splits_are_reproducible():
    assert split_examples(make_examples()) == split_examples(make_examples())


def test_saved_model_stays_within_the_size_limit():
    assert MODEL_PATH.stat().st_size <= 25e6


def test_saved_model_excludes_categories_with_no_examples():
    classes = set(load_model()["classifier"].classes_)
    assert not classes & {"In House Tools", "System Processes", UNMAPPED}


def test_unlisted_site_uses_the_model_or_abstains():
    result = classify("chess-puzzle-club-for-tests.example")
    assert result["method"] in ("model", "undefined")
    assert result["undefined_reason"] in (None, "model_low_confidence")
    assert result["alternatives"]


def test_the_path_does_not_change_the_model_answer():
    assert classify("chess-puzzle-club-for-tests.example")["category"] == classify("chess-puzzle-club-for-tests.example/any/page")["category"]


def test_non_latin_host_returns_undefined():
    result = classify("пример.рф")
    assert result["category"] == "Undefined" and result["undefined_reason"] == "model_low_confidence"
