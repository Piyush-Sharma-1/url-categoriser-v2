"""Curlie lookup: decide from a site's homepage listings (docs/DECISIONS.md, Section G)."""
import collections
import gzip
import json

from src.curlie_data import ROOT, match_row
from src.normalize import registered_domain

LOOKUP_PATH = ROOT / "data" / "lookup.json.gz"
MIN_SHARE = 0.60

# Each host's entry in the lookup is [homepage listings, deep-page listings].
HOMEPAGE, DEEP = 0, 1


def load_lookup(path=LOOKUP_PATH):
    return json.loads(gzip.decompress(path.read_bytes()))


def shares(rows):
    """Return the confident categories among rows with their share of all rows, largest first."""
    counts = collections.Counter(row["we360_category"] for row in rows if row["status"] == "confident")
    return [{"category": name, "confidence": round(n / len(rows), 3)} for name, n in counts.most_common()]


def ambiguous_candidates(rows):
    """Return the candidate categories named by ambiguous rows, without a measured share."""
    names = []
    for row in rows:
        if row["status"] == "ambiguous":
            names += [name for name in row["we360_category"].split("|") if name not in names]
    return [{"category": name, "confidence": None} for name in names]


def vote(rows):
    """Return (category or None, share, reason, alternatives). Also labels the model's training URLs."""
    ranked = shares(rows)
    if ranked and ranked[0]["confidence"] >= MIN_SHARE:
        return ranked[0]["category"], ranked[0]["confidence"], None, ranked[1:3]
    if ranked:
        return None, 0.0, "curlie_split_votes", ranked[:3]
    candidates = ambiguous_candidates(rows)
    if candidates:
        return None, 0.0, "curlie_ambiguous", candidates
    return None, 0.0, "curlie_unmapped", []


def curlie_lookup(host, lookup, taxonomy):
    """Return the Curlie decision for a site as a dict, or None if Curlie does not list it."""
    hosts = lookup["hosts"]
    domain = registered_domain(host)
    domain_hosts = lookup["domain_hosts"].get(domain) or ([domain] if domain in hosts else [])
    if not domain_hosts:
        return None

    listing_ids = hosts[host][HOMEPAGE] if host in hosts else []
    if not listing_ids:
        listing_ids = [i for name in domain_hosts for i in hosts[name][HOMEPAGE]]
    deep_only = not listing_ids
    if deep_only:
        listing_ids = [i for name in domain_hosts for i in hosts[name][DEEP]]

    curlie_paths = [lookup["paths"][i] for i in listing_ids]
    rows = [match_row(curlie_path, taxonomy) for curlie_path in curlie_paths]
    if deep_only:
        category, share, reason, alternatives = None, 0.0, "curlie_deep_page_only", shares(rows)[:5]
    else:
        category, share, reason, alternatives = vote(rows)
    evidence = [name for name, _ in collections.Counter(curlie_paths).most_common(5)]
    return {"category": category, "confidence": share, "reason": reason, "alternatives": alternatives, "evidence": evidence}
