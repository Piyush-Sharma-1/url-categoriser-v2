"""Train the text model and choose its threshold on validation: python -m src.train (docs/DECISIONS.md, Sections H and I)."""
import collections
import random

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from src.curlie_data import iter_retained, load_map, match_row
from src.lookup import vote
from src.model import MODEL_PATH, url_to_text
from src.normalize import registered_domain

SEED = 42
DOMAIN_CAP = 50
CATEGORY_CAP = 2000
MIN_EXAMPLES = 50
MIN_PRECISION = 0.80
MIN_COVERAGE = 0.10
MAX_MODEL_MB = 25
UNMAPPED = "(unmapped)"  # Held-out rows with no We360 category. Never trained on or scored for accuracy.


def load_examples(listings=None):
    """Return (host, domain, label) for each host whose homepage listings give a confident or unmapped label."""
    taxonomy = load_map()
    votes = collections.defaultdict(list)
    for normal, curlie_path in iter_retained() if listings is None else listings:
        if normal and not normal[2]:  # Only homepage listings vote, as in the lookup.
            votes[normal[1]].append(match_row(curlie_path, taxonomy))

    examples = []
    for host, rows in votes.items():
        category, _share, reason, _alternatives = vote(rows)
        if category:
            examples.append((host, registered_domain(host), category))
        elif reason == "curlie_unmapped":
            examples.append((host, registered_domain(host), UNMAPPED))
    return examples


def assign_domains(examples, rng):
    """Put each registered domain in exactly one split, 70/15/15."""
    domains = sorted({domain for _, domain, _ in examples})
    rng.shuffle(domains)
    first_cut = int(0.70 * len(domains))
    second_cut = int(0.85 * len(domains))
    split_of = {}
    for position, domain in enumerate(domains):
        if position < first_cut:
            split_of[domain] = "train"
        elif position < second_cut:
            split_of[domain] = "validation"
        else:
            split_of[domain] = "test"
    return split_of


def cap_rows(rows, key_position, cap, rng):
    """Keep at most cap random rows for each distinct value at key_position (domain or label)."""
    groups = collections.defaultdict(list)
    for row in rows:
        groups[row[key_position]].append(row)
    kept = []
    for key in sorted(groups):
        kept += rng.sample(groups[key], min(cap, len(groups[key])))
    return kept


def split_examples(examples):
    """Return the train, validation, and test rows after dropping unmapped training rows and applying the caps."""
    rng = random.Random(SEED)
    split_of = assign_domains(examples, rng)
    splits = {"train": [], "validation": [], "test": []}
    for example in examples:
        name = split_of[example[1]]
        if name != "train" or example[2] != UNMAPPED:
            splits[name].append(example)

    for name in splits:
        splits[name] = cap_rows(splits[name], 1, DOMAIN_CAP, rng)
    splits["train"] = cap_rows(splits["train"], 2, CATEGORY_CAP, rng)

    counts = collections.Counter(label for _, _, label in splits["train"])
    splits["train"] = [row for row in splits["train"] if counts[row[2]] >= MIN_EXAMPLES]
    return splits


def fit_model(texts, labels, min_df=2):
    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=min_df, sublinear_tf=True)
    classifier = LogisticRegression(C=1.0, class_weight="balanced", max_iter=1000, random_state=SEED)
    classifier.fit(vectorizer.fit_transform(texts), labels)
    return {"vectorizer": vectorizer, "classifier": classifier, "threshold": 0.0, "min_df": min_df}


def score_rows(rows, model):
    """Return (top scores, predicted categories). A host with no known n-gram scores -1, so it is never covered."""
    vectors = model["vectorizer"].transform([url_to_text(host) for host, _, _ in rows])
    probabilities = model["classifier"].predict_proba(vectors)
    scores = probabilities.max(axis=1)
    scores[vectors.getnnz(axis=1) == 0] = -1.0
    return scores, model["classifier"].classes_[probabilities.argmax(axis=1)]


def threshold_table(scores, correct):
    """Return (threshold, coverage, precision) for thresholds 0.00 to 0.95."""
    table = []
    for step in range(20):
        threshold = step / 20
        covered = scores >= threshold
        precision = float(correct[covered].mean()) if covered.any() else 0.0
        table.append((threshold, float(covered.mean()), precision))
    return table


def choose_threshold(table):
    """Return (threshold, met): the lowest reaching the precision target, else the most precise with enough coverage."""
    for threshold, _coverage, precision in table:
        if precision >= MIN_PRECISION:
            return threshold, True
    enough_coverage = [row for row in table if row[1] >= MIN_COVERAGE]
    return max(enough_coverage, key=lambda row: row[2])[0], False


def train_and_tune(train, validation, min_df):
    """Fit a model, choose its threshold on validation, and save it. Returns (model, table, met, size in MB)."""
    model = fit_model([url_to_text(row[0]) for row in train], [row[2] for row in train], min_df)
    scores, predicted = score_rows(validation, model)
    labels = np.array([row[2] for row in validation])
    table = threshold_table(scores, predicted == labels)
    model["threshold"], met = choose_threshold(table)
    joblib.dump(model, MODEL_PATH, compress=3)
    return model, table, met, MODEL_PATH.stat().st_size / 1e6


def main():
    splits = split_examples(load_examples())
    train = splits["train"]
    validation = [row for row in splits["validation"] if row[2] != UNMAPPED]

    print("## Training examples per category")
    for name, n in sorted(collections.Counter(label for _, _, label in train).items()):
        print(f"{n:>6}  {name}")
    print(f"total {len(train)}")

    model, table, met, size = train_and_tune(train, validation, min_df=2)
    if size > MAX_MODEL_MB:
        model, table, met, size = train_and_tune(train, validation, min_df=3)
    print(f"\n## Model: min_df={model['min_df']}, {len(model['vectorizer'].vocabulary_)} n-grams, {size:.1f} MB")

    print("\n## Validation threshold table\nthreshold coverage precision")
    for threshold, coverage, precision in table:
        print(f"{threshold:>9.2f} {coverage:>8.3f} {precision:>9.3f}")
    outcome = "reached" if met else "did not reach"
    print(f"Chosen threshold: {model['threshold']:.2f} ({outcome} {MIN_PRECISION:.2f} precision)")


if __name__ == "__main__":
    main()
