"""One-off analysis of the UT1 lists and what the shipped lookup can answer.

Needs the extracted archive in data/raw/ut1 and the built lookup: python -m scripts.inspect_ut1
"""
import collections
import random
import re

from src.build_sources import group_rows, load_mapping, usable_categories
from src.classify import classify, load_curated, match_curated
from src.curlie_data import load_map
from src.evaluate import load_gold
from src.lookup import curlie_lookup, load_lookup
from src.normalize import normalize_url, parse_ip, registered_domain
from src.reporting import write_report
from src.sources import UT1_FOLDER, load_source_lookup, matching_entry
from src.ut1 import UT1_DIR, list_categories, load_ut1_rows, read_entries

SEED = 42
SAMPLE_SIZE = 10000
ADULT_OR_MALWARE_LISTS = {"adult", "mixed_adult", "malware", "phishing", "cryptojacking", "hacking"}
ADULT_WORDS = re.compile(r"sex|porn|xx|3x|gay|tranny|glory|teen|ados|escort|nude|milf|erotic|hentai|boner|cam|pussy|babe|adult|fuck|penis|dick|flirt|zoo|anal", re.I)


def english_descriptions():
    """Return {category: English description} from the archive's global_usage file."""
    text = (UT1_DIR / "global_usage").read_text(encoding="utf-8", errors="replace")
    described = {}
    for block in re.split(r"\n\s*\n", text):
        name = re.search(r"^NAME:\s*(\S+)", block, re.M)
        description = re.search(r"^DESC EN:\s*(.+)$", block, re.M)
        if name and description:
            described[name.group(1)] = description.group(1).strip()
    return described


def gold_domains():
    """Return the gold set's registered domains. Examples and samples stay away from them."""
    parsed = (normalize_url(row["url"]) for row in load_gold())
    return {registered_domain(item[1]) for item in parsed if item}


def safe_sample(hosts, gold):
    """Return up to five hosts without adult terms or gold domains, written so that they can't be clicked."""
    clean = sorted(host for host in hosts if not ADULT_WORDS.search(host) and registered_domain(host) not in gold)
    chosen = random.Random(SEED).sample(clean, min(5, len(clean)))
    return ", ".join(host.replace(".", "[.]") for host in chosen)


def report_categories(mapping, gold):
    described = english_descriptions()
    print("## UT1 lists (status, domains, description, examples). Excluded lists are not read, and unmapped lists show no examples.")
    for category in list_categories():
        status = mapping[category]["status"]
        if status == "excluded":
            print(f"{category}\texcluded\t\t\t")
            continue
        entries = read_entries(category)
        examples = "(not shown)" if status == "unmapped" else safe_sample(entries, gold)
        print(f"{category}\t{status}\t{len(entries)}\t{described.get(category, '(no description)')}\t{examples}")


def report_coverage(decisions, gold):
    taxonomy, curlie_data, curated = load_map(), load_lookup(), load_curated()
    outcome = collections.defaultdict(collections.Counter)
    undecided = collections.Counter()
    new_hosts = collections.defaultdict(list)
    ip_hosts = 0
    for host, decision in decisions.items():
        category = decision["category"]
        if not category:
            undecided[decision["reason"]] += 1
            continue
        ip_hosts += parse_ip(host) is not None
        curlie = curlie_lookup(host, curlie_data, taxonomy)
        if match_curated(host, "", curated):
            outcome[category]["curated"] += 1
        elif curlie is None:
            outcome[category]["new"] += 1
            new_hosts[category].append(host)
        elif curlie["category"]:
            outcome[category]["curlie_answers"] += 1
        else:
            outcome[category]["curlie_no_answer"] += 1

    print("\n## What the lookup can answer, per shipped host")
    print("UT1 answers a host when it is new or Curlie gives no category. Matching also covers each host's subdomains.")
    print("we360_category\tentries\tut1_can_answer\tnew\tcurlie_no_answer\tcurlie_answers\tcurated")
    totals = collections.Counter()
    for category in sorted(outcome):
        counts = outcome[category]
        totals.update(counts)
        answers = counts["new"] + counts["curlie_no_answer"]
        print(f"{category}\t{sum(counts.values())}\t{answers}\t{counts['new']}\t{counts['curlie_no_answer']}\t{counts['curlie_answers']}\t{counts['curated']}")
    answers = totals["new"] + totals["curlie_no_answer"]
    print(f"total\t{sum(totals.values())}\t{answers}\t{totals['new']}\t{totals['curlie_no_answer']}\t{totals['curlie_answers']}\t{totals['curated']}")
    print(f"shipped hosts with no category: {dict(undecided)}")
    print(f"hosts that are bare IP addresses, among those with a category: {ip_hosts}")

    print("\n## Five new hosts per We360 category")
    for category in sorted(new_hosts):
        print(f"{category}\t{safe_sample(new_hosts[category], gold)}")


def report_dropped(mapping, decisions, gold):
    """Show what happens to hosts listed only in unmapped lists, which the lookup leaves out."""
    hosts = group_rows(load_ut1_rows(usable_categories(mapping)))
    dropped = {host: lists for host, lists in hosts.items() if host not in decisions}
    largest = collections.Counter(name for lists in dropped.values() for name in lists).most_common(8)
    print("\n## Hosts listed only in unmapped lists, which the lookup leaves out")
    print(f"hosts: {len(dropped)}")
    print(f"largest lists, where a host can be on several: {largest}")

    parents = collections.Counter()
    for host in dropped:
        entry = matching_entry(host, decisions)
        if entry:
            parents[decisions[entry]["reason"] or "category"] += 1
    print(f"hosts that match a shipped parent entry, by that entry's outcome: {dict(parents)}")

    # Gold domains are left out, so this never classifies a gold URL.
    eligible = sorted(host for host in dropped if registered_domain(host) not in gold)
    outcomes = collections.Counter()
    for host in random.Random(SEED).sample(eligible, SAMPLE_SIZE):
        result = classify(host)
        outcomes[result["undefined_reason"] or result["method"]] += 1
    print(f"outcomes on {SAMPLE_SIZE} random hosts, with no host from a gold domain: {outcomes.most_common()}")

    mixed = [decision for decision in decisions.values() if ADULT_OR_MALWARE_LISTS & set(decision["lists"])]
    with_category = sum(1 for decision in mixed if decision["category"])
    print(f"shipped hosts that also have a vote from an adult or malware list: {len(mixed)}, with a category: {with_category}")


def main():
    mapping = load_mapping(UT1_FOLDER)
    decisions = load_source_lookup(UT1_FOLDER)
    gold = gold_domains()
    print("mapping rows by status:", dict(collections.Counter(row["status"] for row in mapping.values())))
    report_categories(mapping, gold)
    report_coverage(decisions, gold)
    report_dropped(mapping, decisions, gold)


if __name__ == "__main__":
    write_report("ut1_report.txt", main)
