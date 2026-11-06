"""Text model prediction (docs/DECISIONS.md, Section H). Training is in src/train.py."""
import re
from functools import lru_cache

from src.curlie_data import ROOT

MODEL_PATH = ROOT / "data" / "model.joblib"
DROP_TOKENS = {"www", "http", "https", "html", "htm", "php", "asp", "aspx", "index", "xn"}


def url_to_text(host):
    """Turn a host into the only text the model sees, for both training and prediction. We360 categorises the site, not the page."""
    tokens = re.sub(r"[^a-z0-9]", " ", host.lower()).split()
    return " ".join(token for token in tokens if token not in DROP_TOKENS)


@lru_cache(maxsize=1)
def load_model():
    if not MODEL_PATH.exists():
        return None
    import joblib  # Imported here so URLs answered by earlier steps don't pay to load scikit-learn.

    return joblib.load(MODEL_PATH)


def top_ngrams(vector, class_index, model, count=5):
    """Return the n-grams that contribute most to a class: TF-IDF value x the class's coefficient."""
    contributions = vector.data * model["classifier"].coef_[class_index][vector.indices]
    names = model["vectorizer"].get_feature_names_out()
    strongest = contributions.argsort()[::-1][:count]
    return [f"N-gram '{names[vector.indices[i]]}': {contributions[i]:.2f}" for i in strongest]


def predict(host, model):
    """Return (category or None, score, alternatives, evidence). The category is None below the threshold."""
    vector = model["vectorizer"].transform([url_to_text(host)])
    if vector.nnz == 0:
        return None, 0.0, [], []  # No known n-gram means no evidence at all.

    classes = model["classifier"].classes_
    scores = model["classifier"].predict_proba(vector)[0]
    ranked = scores.argsort()[::-1]
    alternatives = [{"category": str(classes[i]), "confidence": round(float(scores[i]), 3)} for i in ranked[:3]]
    best = ranked[0]
    if scores[best] < model["threshold"]:
        return None, 0.0, alternatives, []
    return str(classes[best]), round(float(scores[best]), 3), alternatives, top_ngrams(vector, best, model)
