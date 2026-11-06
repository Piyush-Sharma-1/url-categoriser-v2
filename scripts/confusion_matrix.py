"""Post-hoc: confusion matrices for the test split, made after the test run and every decision based on it.

This scores the test split a second time, at the project owner's request. It changes nothing: reports/test_report.txt
stays as the record of the one test run, and the model and threshold are only read. The scores it prints should match
that report exactly. The Curlie dump may be in another folder, such as version 1's, so its path is an argument.

python -m scripts.confusion_matrix ../url-categoriser/data/raw/curlie-rdf
"""
import csv
import sys
from pathlib import Path

import numpy as np
from sklearn.metrics import f1_score

from src.curlie_data import RAW_DIR, iter_retained
from src.evaluate import UNDEFINED, confused_pairs, overall_scores
from src.model import load_model
from src.reporting import REPORTS, write_report
from src.train import UNMAPPED, load_examples, score_rows, split_examples


def confusion_counts(labels, predictions):
    """Return (true categories, answers, counts), with one row per true category and Undefined as the last column."""
    rows = sorted(set(labels.tolist()))
    columns = sorted((set(rows) | set(predictions.tolist())) - {UNDEFINED}) + [UNDEFINED]
    row_of = {name: i for i, name in enumerate(rows)}
    column_of = {name: i for i, name in enumerate(columns)}
    counts = np.zeros((len(rows), len(columns)), dtype=int)
    for label, prediction in zip(labels.tolist(), predictions.tolist()):
        counts[row_of[label], column_of[prediction]] += 1
    return rows, columns, counts


def save_matrix(name, rows, columns, counts):
    with open(REPORTS / f"test_confusion_{name}.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["true category", *columns])
        for row, values in zip(rows, counts.tolist()):
            writer.writerow([row, *values])


def report_matrices(raw_dir):
    test_rows = split_examples(load_examples(iter_retained(raw_dir)))["test"]
    labelled = [row for row in test_rows if row[2] != UNMAPPED]
    labels = np.array([row[2] for row in labelled])
    model = load_model()
    scores, predicted = score_rows(labelled, model)
    answers = {
        f"threshold_{model['threshold']:.2f}": np.where(scores >= model["threshold"], predicted, UNDEFINED),
        "no_threshold": np.where(scores >= 0, predicted, UNDEFINED),
    }
    print(f"# Post-hoc: confusion matrices from a second scoring of the test split ({len(labelled)} labelled hosts)")
    for name, answer in answers.items():
        rows, columns, counts = confusion_counts(labels, answer)
        save_matrix(name, rows, columns, counts)
        macro = f1_score(labels, answer, labels=rows, average="macro", zero_division=0)
        print(f"\n## {name}: the matrix is in reports/test_confusion_{name}.csv")
        for metric, value in overall_scores(labels, answer).items():
            print(f"{metric:<22}{value:.3f}")
        print(f"{'macro-F1':<22}{macro:.3f}")
        print(f"Most-confused pairs: {confused_pairs(labels, answer)}")


if __name__ == "__main__":
    raw_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else RAW_DIR
    write_report("test_confusion_report.txt", lambda: report_matrices(raw_dir))
