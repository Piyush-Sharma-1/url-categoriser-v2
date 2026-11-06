"""Evaluate the model and the whole pipeline (docs/DECISIONS.md, Section K).

python -m src.evaluate validation   Model scores on validation. Safe to repeat.
python -m src.evaluate test         Model scores on the test set. Runs once only.
python -m src.evaluate gold-v2      Version 2 beside version 1 on the new gold set. This is version 2's headline.
python -m src.evaluate gold         Version 2 beside version 1 on the original gold set, which is post-hoc for version 2.

reports/gold_report.txt stays as the record of version 1's run, so neither gold command writes to it.
"""
import collections
import csv
import math
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
GOLD_V2_PATH = ROOT / "data" / "gold_v2_urls.csv"
TEST_REPORT = "test_report.txt"
UNDEFINED = "Undefined"
METHODS = ("rule", "curated", "curlie", "ut1", "model", "undefined")


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
    for method in METHODS:
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


def wilson_interval(share, total, z=1.96):
    """Return the 95% Wilson interval for a share. It stays between 0 and 1 and behaves on small samples."""
    spread = z * z / total
    centre = (share + spread / 2) / (1 + spread)
    margin = z * math.sqrt(share * (1 - share) / total + spread / (4 * total)) / (1 + spread)
    return max(0.0, centre - margin), min(1.0, centre + margin)


def answer_status(row, category):
    """Return how one answer compares with its gold row."""
    if category == row["label"]:
        return "right"
    if category == row["also_acceptable"]:
        return "also acceptable"
    return "undefined" if category == UNDEFINED else "wrong"


def answer_text(row, result):
    reason = f", {result['undefined_reason']}" if result["undefined_reason"] else ""
    return f"{result['category']} ({result['method']}{reason}; {answer_status(row, result['category'])})"


def version_scores(rows, answers):
    """Return one version's scores. A wrong answer gives a category that the gold row doesn't accept."""
    labels = np.array([row["label"] for row in rows])
    also_acceptable = np.array([row["also_acceptable"] for row in rows])
    predictions = np.array(answers)
    covered = predictions != UNDEFINED
    lenient_right = (labels == predictions) | (also_acceptable == predictions)
    scores = gold_scores(labels, also_acceptable, predictions)
    scores["precision on covered, lenient"] = float(lenient_right[covered].mean()) if covered.any() else 0.0
    scores["wrong-answer rate, strict"] = float((covered & (labels != predictions)).mean())
    scores["wrong-answer rate, lenient"] = float((covered & ~lenient_right).mean())
    return scores


def report_versions(title, rows, versions):
    """Print each version's scores beside the baseline, with 95% intervals, then how their answers pair up."""
    majority, baseline = majority_baseline(np.array([row["label"] for row in rows]))
    columns = {name: version_scores(rows, [result["category"] for result in results]) for name, results in versions.items()}
    columns[f"always {majority}"] = version_scores(rows, baseline.tolist())
    print(f"\n## {title}: {len(rows)} URLs")
    print(f"{'score':<36}" + "".join(f"{name:>22}" for name in columns))
    for metric in next(iter(columns.values())):
        print(f"{metric:<36}" + "".join(f"{scores[metric]:>22.3f}" for scores in columns.values()))
    for metric in ("strict accuracy", "lenient accuracy"):
        intervals = [wilson_interval(scores[metric], len(rows)) for scores in columns.values()]
        print(f"{metric + ', 95% interval':<36}" + "".join(f"{f'{low:.3f} to {high:.3f}':>22}" for low, high in intervals))

    first, second = versions.values()
    for name, accepted in (("Strict", ("right",)), ("Lenient", ("right", "also acceptable"))):
        pairs = collections.Counter(
            (answer_status(row, old["category"]) in accepted, answer_status(row, new["category"]) in accepted)
            for row, old, new in zip(rows, first, second)
        )
        print(f"{name}: both right {pairs[(True, True)]}, only v1 right {pairs[(True, False)]}, "
              f"only v2 right {pairs[(False, True)]}, both missed {pairs[(False, False)]}")


def report_by_label(rows, versions):
    """Print, per gold label, how many rows each version gets right and what UT1 answered."""
    first, second = versions.values()
    print("\n## By label (label, rows, v1 strict right, v2 strict right, UT1 answers, UT1 answers accepted)")
    for label in sorted({row["label"] for row in rows}):
        chosen = [i for i, row in enumerate(rows) if row["label"] == label]
        right = [sum(results[i]["category"] == label for i in chosen) for results in (first, second)]
        ut1 = [i for i in chosen if second[i]["method"] == "ut1"]
        accepted = sum(answer_status(rows[i], second[i]["category"]) != "wrong" for i in ut1)
        print(f"{label:<24}{len(chosen):>4}{right[0]:>4}{right[1]:>4}{len(ut1):>4}{accepted:>4}")


def report_ut1_rows(rows, versions):
    """Print every row that UT1 decided, including the ones where it stopped the model with Undefined."""
    first, second = versions.values()
    print("\n## Rows UT1 decided (URL, label, also acceptable, v1, v2, evidence)")
    for row, old, new in zip(rows, first, second):
        if new["method"] == "ut1" or (new["undefined_reason"] or "").startswith("ut1_"):
            print((row["url"], row["label"], row["also_acceptable"], answer_text(row, old), answer_text(row, new), new["evidence"]))


def report_missed_rows(rows, versions):
    """Print every row that either version missed on strict accuracy."""
    first, second = versions.values()
    print("\n## Rows either version missed on strict accuracy (URL, label, also acceptable, v1, v2)")
    for row, old, new in zip(rows, first, second):
        if old["category"] != row["label"] or new["category"] != row["label"]:
            print((row["url"], row["label"], row["also_acceptable"], answer_text(row, old), answer_text(row, new)))


def load_predictions(name, rows):
    """Return version 1's saved answers in gold-row order. scripts/classify_with_v1.py writes them."""
    with open(REPORTS / name, encoding="utf-8", newline="") as f:
        saved = {row["url"]: {**row, "undefined_reason": row["undefined_reason"] or None} for row in csv.DictReader(f)}
    if set(saved) != {row["url"] for row in rows}:
        sys.exit(f"{name} doesn't match the gold set. Regenerate it with scripts/classify_with_v1.py.")
    return [saved[row["url"]] for row in rows]


def answer_key(result):
    return result["category"], result["method"], result["undefined_reason"]


def report_comparison(title, rows, predictions_name, groups):
    """Print version 1 and version 2 side by side on one gold set."""
    versions = {"v1": load_predictions(predictions_name, rows), "v2": [classify(row["url"]) for row in rows]}
    print(f"# {title}")
    differs = [row["url"] for row, old in zip(rows, versions["v1"]) if answer_key(classify(row["url"], sources=())) != answer_key(old)]
    print(f"Rows where v2 with UT1 switched off differs from v1: {differs}")
    for group, chosen in groups:
        if chosen:
            subset = {name: [results[i] for i in chosen] for name, results in versions.items()}
            report_versions(group, [rows[i] for i in chosen], subset)
    for name, results in versions.items():
        report_pipeline(f"{name} by method and Undefined reason", rows, results)
    report_by_label(rows, versions)
    report_ut1_rows(rows, versions)
    report_missed_rows(rows, versions)


def report_new_gold(rows):
    title = "Version 2 headline: new gold set (data/gold_v2_urls.csv)"
    report_comparison(title, rows, "gold_v2_v1_predictions.csv", [("All rows", list(range(len(rows))))])


def report_posthoc(rows):
    title = "Post-hoc: seen while building v2 (original gold set, data/gold_urls.csv)"
    report_comparison(title, rows, "gold_v1_predictions.csv", gold_groups(rows))
    report_gold(rows)


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
        write_report("gold_posthoc_report.txt", lambda: report_posthoc(rows))
    elif command == "gold-v2":
        rows = load_gold(GOLD_V2_PATH)
        write_report("gold_v2_report.txt", lambda: report_new_gold(rows))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
