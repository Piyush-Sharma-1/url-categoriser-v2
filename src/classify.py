"""Classify one URL. The first step that returns a result wins (docs/DECISIONS.md, Section A)."""
import collections
import csv
from functools import lru_cache

from src.curlie_data import ROOT, load_map
from src.lookup import curlie_lookup, load_lookup
from src.model import load_model, predict
from src.normalize import normalize_url, parse_ip, system_scheme

CURATED_PATH = ROOT / "data" / "known_domains.csv"
IN_HOUSE_SUFFIXES = (".local", ".internal", ".corp", ".lan", ".intranet")
UNDEFINED_TEXT = {
    "invalid_url": "The input is not a valid URL.",
    "curlie_deep_page_only": "Curlie lists only individual pages on this domain, which says too little about the site.",
    "curlie_split_votes": "No category reaches 60% of Curlie's homepage listings for this site.",
    "curlie_ambiguous": "Curlie lists this site under a subject that fits more than one category.",
    "curlie_unmapped": "Curlie lists this site under a subject with no matching We360 category.",
    "model_low_confidence": "Curlie does not list this site, and the text model is not confident enough.",
    "model_unavailable": "Curlie does not list this site, and no text model is available.",
}


def load_curated(path=CURATED_PATH):
    """Return {host: {path: row}} from the curated list."""
    curated = collections.defaultdict(dict)
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            host, slash, rest = row["host_or_prefix"].partition("/")
            curated[host][slash + rest] = row
    return curated


@lru_cache(maxsize=1)
def load_data():
    return load_map(), load_lookup(), load_curated()


def longest_prefix(path, table):
    """Return the longest whole-segment prefix of path that is a key of table, or None. "" is the root."""
    parts = path.split("/")
    for end in range(len(parts), 0, -1):
        prefix = "/".join(parts[:end])
        if prefix in table:
            return prefix
    return None


def match_curated(host, path, curated):
    """Return the curated row with the most matching host labels, then the most path segments, or None."""
    labels = host.split(".")
    for start in range(len(labels)):
        paths = curated.get(".".join(labels[start:]), {})
        prefix = longest_prefix(path, paths)
        if prefix is not None:
            return paths[prefix]
    return None


def in_house_rule(host):
    """Return the In House rule that matches the host, or None."""
    ip = parse_ip(host)
    if ip:
        return "loopback or private IP" if ip.is_loopback or ip.is_private else None
    if "." not in host:
        return "host without a dot"
    return "internal host suffix" if host.endswith(IN_HOUSE_SUFFIXES) else None


def make_result(url, normalized, category, confidence, method, explanation, evidence=(), alternatives=(), reason=None):
    return {
        "url": url,
        "normalized": normalized,
        "category": category,
        "confidence": confidence,
        "method": method,
        "explanation": explanation,
        "evidence": list(evidence),
        "alternatives": list(alternatives),
        "undefined_reason": reason,
    }


def undefined(url, normalized, reason, evidence=(), alternatives=()):
    return make_result(url, normalized, "Undefined", 0.0, "undefined", UNDEFINED_TEXT[reason], evidence, alternatives, reason)


def curated_result(url, normalized, row, curlie):
    evidence = [f"Curated list: {row['host_or_prefix']}"]
    alternatives = []
    if row["alternative_category"]:
        for name in row["alternative_category"].split("|"):
            alternatives.append({"category": name, "confidence": None})
    if curlie and curlie["category"] not in (None, row["we360_category"]):
        alternatives.append({"category": curlie["category"], "confidence": curlie["confidence"]})
        evidence += curlie["evidence"]
    explanation = f"The curated list files {row['host_or_prefix']} under {row['we360_category']}: {row['note']}."
    return make_result(url, normalized, row["we360_category"], 1.0, "curated", explanation, evidence, alternatives)


def curlie_result(url, normalized, curlie):
    if curlie["reason"]:
        return undefined(url, normalized, curlie["reason"], curlie["evidence"], curlie["alternatives"])
    explanation = f"{curlie['confidence']:.0%} of Curlie's homepage listings for this site map to {curlie['category']}."
    return make_result(url, normalized, curlie["category"], curlie["confidence"], "curlie", explanation, curlie["evidence"], curlie["alternatives"])


def model_result(url, normalized, host):
    model = load_model()
    if model is None:
        return undefined(url, normalized, "model_unavailable")
    category, score, alternatives, evidence = predict(host, model)
    if category is None:
        return undefined(url, normalized, "model_low_confidence", alternatives=alternatives)
    explanation = f"Curlie does not list this site, and the text model scores {category} highest ({score:.2f}) from its host name."
    return make_result(url, normalized, category, score, "model", explanation, evidence, alternatives)


def classify(url, use_curated=True):
    """Return the category and provenance for one URL (docs/DECISIONS.md, Section J). The evaluation turns the curated list off."""
    scheme = system_scheme(url)
    if scheme:
        return make_result(url, None, "System Processes", 1.0, "rule", f"{scheme}: is a browser or OS address.", [f"Rule: scheme {scheme}"])

    normal = normalize_url(url)
    if normal is None:
        return undefined(url, None, "invalid_url")
    normalized, host, path = normal

    rule = in_house_rule(host)
    if rule:
        return make_result(url, normalized, "In House Tools", 1.0, "rule", f"{host} is a private or intranet host.", [f"Rule: {rule}"])

    taxonomy, lookup, curated = load_data()
    curlie = curlie_lookup(host, lookup, taxonomy)
    row = match_curated(host, path, curated) if use_curated else None
    if row:
        return curated_result(url, normalized, row, curlie)
    if curlie:
        return curlie_result(url, normalized, curlie)
    return model_result(url, normalized, host)
