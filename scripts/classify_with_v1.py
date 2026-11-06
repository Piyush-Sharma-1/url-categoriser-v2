"""Classify a gold file with the frozen version 1 code, writing nothing in its folder.

Run this from the version 1 folder, with that folder's environment. The output path must be outside that folder.

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python ../url-categoriser-v2/scripts/classify_with_v1.py GOLD_CSV OUTPUT_CSV
"""
import csv
import inspect
import sys

from src.classify import classify

FIELDS = ("url", "category", "method", "undefined_reason", "confidence")


def main(gold_path, output_path):
    if "sources" in inspect.signature(classify).parameters:
        sys.exit("This found version 2's code. Run it from the version 1 folder.")
    with open(gold_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            result = classify(row["url"])
            writer.writerow({field: result[field] for field in FIELDS[1:]} | {"url": row["url"]})


if __name__ == "__main__":
    main(*sys.argv[1:])
