"""Evaluate the model and the whole pipeline (docs/DECISIONS.md, Section K).

python -m src.evaluate validation   Model scores on validation. Safe to repeat.
python -m src.evaluate test         Model scores on the test set. Runs once only.
python -m src.evaluate gold         Whole-pipeline scores on the labelled gold set.
"""
import collections
import csv
import re
import sys

import numpy as np
from sklearn.metrics import f1_score

from src.classify import classify
from src.curlie_data import CATEGORIES, ROOT
from src.model import load_model
from src.reporting import REPORTS, write_report
from src.train import UNMAPPED, load_examples, score_rows, split_examples

GOLD_PATH = ROOT / "data" / "gold_urls.csv"
TEST_REPORT = "test_report.txt"
UNDEFINED = "Undefined"


def overall_scores(labels, predictions):
    """Return accuracy, coverage, and precision on covered rows. A wrong or missing answer counts against accuracy."""
    correct = labels == predictions
    covered = predictions != UNDEFINED
    return {
        "accuracy": float(correct.mean()),
        "coverage": float(covered.mean()),
        "precision on covered": float(correct[covered].mean()) if covered.any() else 0.0,
    }


def majority_baseline(labels):
    """Return (majority label, predictions that always answer with it)."""
    majority = collections.Counter(labels.tolist()).most_common(1)[0][0]
    return majority, np.full(len(labels), majority)


def confused_pairs(labels, predictions, count=10):
    """Return the most common (true label, wrong answer) pairs, ignoring Undefined answers."""
    pairs = collections.Counter()
    for label, prediction in zip(labels.tolist(), predictions.tolist()):
        if label != prediction and prediction != UNDEFINED:
            pairs[(label, prediction)] += 1
    return pairs.most_common(count)


def report_model(rows, model):
    """Print every model score beside the majority-class baseline, with example counts per category."""
    labelled = [row for row in rows if row[2] != UNMAPPED]
    unmapped = [row for row in rows if row[2] == UNMAPPED]
    labels = np.array([row[2] for row in labelled])
    scores, predicted = score_rows(labelled, model)
    majority, baseline = majority_baseline(labels)
    answers = {
        f"threshold {model['threshold']:.2f}": np.where(scores >= model["threshold"], predicted, UNDEFINED),
        "no threshold": np.where(scores >= 0, predicted, UNDEFINED),
        f"baseline: always {majority}": baseline,
    }
    categories = sorted(set(labels.tolist()))
    print(f"{len(labelled)} labelled hosts and {len(unmapped)} unmapped hosts\n")

    print(f"{'score':<22}" + "".join(f"{name:>36}" for name in answers))
    for metric in ("accuracy", "coverage", "precision on covered"):
        print(f"{metric:<22}" + "".join(f"{overall_scores(labels, a)[metric]:>36.3f}" for a in answers.values()))
    macro = [f1_score(labels, a, labels=categories, average="macro", zero_division=0) for a in answers.values()]
    print(f"{'macro-F1':<22}" + "".join(f"{value:>36.3f}" for value in macro))

    print("\nF1 per category")
    print(f"{'category':<24}{'examples':>9}" + "".join(f"{name:>36}" for name in answers))
    per_category = [f1_score(labels, a, labels=categories, average=None, zero_division=0) for a in answers.values()]
    counts = collections.Counter(labels.tolist())
    for i, category in enumerate(categories):
        print(f"{category:<24}{counts[category]:>9}" + "".join(f"{f1[i]:>36.3f}" for f1 in per_category))

    print("\nMost-confused pairs (true category -> answer)")
    for name, answer in list(answers.items())[:2]:
        print(f"At {name}: {confused_pairs(labels, answer)}")
    if unmapped:
        assigned = float((score_rows(unmapped, model)[0] >= model["threshold"]).mean())
        print(f"\nUnmapped hosts the model assigns a category: {assigned:.3f}")


def report_split(name):
    print(f"## Text model on the {name} split")
    report_model(split_examples(load_examples())[name], load_model())


def load_gold(path=GOLD_PATH):
    """Return the gold rows, refusing to score unless every row has a valid label."""
    with open(path, encoding="utf-8-sig", newline="") as f:  # utf-8-sig also reads CSV files saved by Excel.
        rows = list(csv.DictReader(f))
    unlabelled = sum(not row["label"] for row in rows)
    if unlabelled:
        sys.exit(f"{unlabelled} of {len(rows)} gold rows have no label yet.")
    valid = (*CATEGORIES, UNDEFINED)
    invalid = [row["label"] for row in rows if row["label"] not in valid]
    invalid += [row["also_acceptable"] for row in rows if row["also_acceptable"] and row["also_acceptable"] not in valid]
    if invalid:
        sys.exit(f"Invalid gold labels: {invalid}")
    return rows


def has_tag(row, tag):
    """Tags are whole words in the note, so "indian" does not match "indiana"."""
    return tag in re.findall(r"[\w-]+", row["note"].lower())


def gold_scores(labels, also_acceptable, predictions):
    """Return strict accuracy (label only), lenient accuracy (label or also_acceptable), coverage, and precision."""
    scores = overall_scores(labels, predictions)
    lenient = (labels == predictions) | (also_acceptable == predictions)
    return {
        "strict accuracy": scores["accuracy"],
        "lenient accuracy": float(lenient.mean()),
        "coverage": scores["coverage"],
        "precision on covered": scores["precision on covered"],
    }


def report_pipeline(title, rows, results):
    """Print strict and lenient scores overall and per method, the baseline, and the Undefined rate by reason."""
    labels = np.array([row["label"] for row in rows])
    also_acceptable = np.array([row["also_acceptable"] for row in rows])
    predictions = np.array([result["category"] for result in results])
    majority, baseline = majority_baseline(labels)
    scores = gold_scores(labels, also_acceptable, predictions)
    baseline_scores = gold_scores(labels, also_acceptable, baseline)
    print(f"\n## {title}: {len(rows)} URLs")
    print(f"{'score':<22}{'pipeline':>10}   baseline (always {majority})")
    for metric, value in scores.items():
        print(f"{metric:<22}{value:>10.3f}   {baseline_scores[metric]:.3f}")

    print("Per method (share of rows, strict accuracy, lenient accuracy):")
    for method in ("rule", "curated", "curlie", "model", "undefined"):
        chosen = np.array([result["method"] == method for result in results])
        if chosen.any():
            method_scores = gold_scores(labels[chosen], also_acceptable[chosen], predictions[chosen])
            print(f"  {method:<10} {chosen.mean():.3f}  {method_scores['strict accuracy']:.3f}  {method_scores['lenient accuracy']:.3f}")

    reasons = collections.Counter(result["undefined_reason"] for result in results if result["undefined_reason"])
    print(f"Undefined rate: {(predictions == UNDEFINED).mean():.3f}; by reason: {dict(reasons)}")


def curated_overrides(rows, with_curated, without_curated):
    """Return (url, curated category, Curlie category, label) wherever the curated list overrode a Curlie answer."""
    overrides = []
    for row, curated, curlie in zip(rows, with_curated, without_curated):
        if curated["method"] == "curated" and curlie["method"] == "curlie" and curated["category"] != curlie["category"]:
            overrides.append((row["url"], curated["category"], curlie["category"], row["label"]))
    return overrides


def wrong_rows(rows, results):
    """Return the details of every row whose answer differs from its label."""
    wrong = []
    for row, result in zip(rows, results):
        if result["category"] != row["label"]:
            wrong.append((row["url"], row["label"], row["also_acceptable"], result["category"], result["method"], result["explanation"]))
    return wrong


def gold_groups(rows):
    """Return (title, row positions) for each group the gold report covers."""
    def positions(test):
        return [i for i, row in enumerate(rows) if test(row)]

    return [
        ("All rows", positions(lambda row: True)),
        ("Drafted candidates", positions(lambda row: not has_tag(row, "major-app"))),
        ("major-app rows", positions(lambda row: has_tag(row, "major-app"))),
        ("Indian and non-English rows", positions(lambda row: has_tag(row, "indian") or has_tag(row, "non-english"))),
    ]


def report_gold(rows):
    with_curated = [classify(row["url"]) for row in rows]
    without_curated = [classify(row["url"], use_curated=False) for row in rows]
    for title, chosen in gold_groups(rows):
        if chosen:
            subset = [rows[i] for i in chosen]
            report_pipeline(f"{title}, with the curated list", subset, [with_curated[i] for i in chosen])
            report_pipeline(f"{title}, without the curated list", subset, [without_curated[i] for i in chosen])

    print("\n## Curated list overrides (URL, curated, Curlie, your label)")
    for override in curated_overrides(rows, with_curated, without_curated):
        print(override)

    print("\n## Rows the pipeline got wrong on strict accuracy (URL, label, also acceptable, prediction, method, explanation)")
    for wrong in wrong_rows(rows, with_curated):
        print(wrong)


def main(args):
    command = args[0] if args else None
    if command == "validation":
        write_report("validation_report.txt", lambda: report_split("validation"))
    elif command == "test":
        if (REPORTS / TEST_REPORT).exists():
            sys.exit("The test set has already been run. See reports/test_report.txt.")
        write_report(TEST_REPORT, lambda: report_split("test"))
    elif command == "gold":
        rows = load_gold()
        write_report("gold_report.txt", lambda: report_gold(rows))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
