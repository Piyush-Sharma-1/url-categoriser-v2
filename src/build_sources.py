"""Build the lookup for each extra source, without touching the Curlie lookup or the model: python -m src.build_sources"""
import collections
import csv
import gzip
import json
import sys

from src.lookup import vote
from src.reporting import write_report
from src.sources import LOOKUP_NAME, SOURCES
from src.ut1 import fetch_ut1, list_categories, read_entries


def load_mapping(folder):
    with open(folder / "mapping.csv", encoding="utf-8", newline="") as f:
        return {row["source_category"]: row for row in csv.DictReader(f)}


def usable_categories(mapping):
    """Return the categories that may vote. Excluded lists are not used at all."""
    return [name for name, row in mapping.items() if row["status"] != "excluded"]


def group_rows(rows):
    """Return {host: [categories]} from (host, category) rows, counting each category once per host."""
    hosts = {}
    for host, category in rows:
        found = hosts.setdefault(host, [])
        if category not in found:
            found.append(category)
    return hosts


def decide_hosts(hosts, mapping, source_name):
    """Return {host: decision} using the 60% vote. Hosts listed only in unmapped lists are left out."""
    decisions = {}
    for host, lists in hosts.items():
        category, share, reason, alternatives = vote([mapping[name] for name in lists])
        if reason == "curlie_unmapped":
            continue
        matched = [name for name in lists if mapping[name]["we360_category"] == category]
        decisions[host] = {
            "category": category,
            "confidence": share,
            "reason": reason.replace("curlie_", f"{source_name}_") if reason else None,
            "alternatives": alternatives,
            "lists": lists,
            "source_category": matched[0] if matched else None,
        }
    return decisions


def write_lookup(decisions, folder):
    payload = json.dumps(decisions, ensure_ascii=False, separators=(",", ":"))
    (folder / LOOKUP_NAME).write_bytes(gzip.compress(payload.encode("utf-8"), mtime=0))


def build_ut1(source):
    fetch_ut1()
    mapping = load_mapping(source["folder"])
    unmapped_lists = sorted(set(list_categories()) - set(mapping))
    if unmapped_lists:
        sys.exit(f"UT1 lists without a mapping row: {unmapped_lists}")

    categories = usable_categories(mapping)
    hosts = group_rows(source["load_rows"](categories))
    decisions = decide_hosts(hosts, mapping, source["name"])
    write_lookup(decisions, source["folder"])

    outcomes = collections.Counter(decision["reason"] or "category" for decision in decisions.values())
    print(f"UT1 lists used: {len(categories)} of {len(mapping)}")
    print(f"UT1 entries read: {sum(len(read_entries(category)) for category in categories)}")
    print(f"Hosts listed: {len(hosts)}")
    print(f"Hosts shipped: {len(decisions)} {dict(outcomes)}")
    print(f"Hosts listed only in unmapped lists, not shipped: {len(hosts) - len(decisions)}")
    print(f"{LOOKUP_NAME}: {(source['folder'] / LOOKUP_NAME).stat().st_size / 1e6:.1f} MB")


def main():
    for source in SOURCES:
        write_report(f"{source['name']}_build_report.txt", lambda: build_ut1(source))


if __name__ == "__main__":
    main()
