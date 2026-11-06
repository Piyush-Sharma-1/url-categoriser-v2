"""One-off dataset analysis behind the dump statistics in docs/DECISIONS.md. Needs the dump: python -m scripts.inspect_dump"""
import collections
import re

from src.curlie_data import CATEGORIES, IGNORED_BRANCHES, iter_listings, load_map, match_row, read_categories
from src.normalize import normalize_url, registered_domain
from src.reporting import write_report

TOPIC_BRANCHES = {"Arts", "Business", "Computers", "Games", "Health", "Home", "News", "Recreation", "Reference", "Science",
                  "Shopping", "Society", "Sports"}
INDIAN_LANGUAGES = ("Hindi", "Tamil", "Telugu", "Gujarati", "Marathi", "Urdu", "Bangla", "Kannada", "Punjabi_Gurmukhi")
LINK = re.compile(r'href="?/?([^"> ]+)', re.I)
KIDS_INTERNATIONAL, KIDS_ENGLISH, RETAINED, OTHER = 1, 2, 4, 8  # Which parts of the dump list a domain.


def flag_for(path):
    top = path.split("/")[0]
    if path.startswith("Kids_and_Teens/International"):
        return KIDS_INTERNATIONAL
    return KIDS_ENGLISH if top == "Kids_and_Teens" else OTHER if top in IGNORED_BRANCHES else RETAINED


def report_mapping(path_listings, category_domains, taxonomy):
    status, category, by_row = collections.Counter(), collections.Counter(), collections.Counter()
    for path, n in path_listings.items():
        if path.split("/")[0] not in IGNORED_BRANCHES:
            row = match_row(path, taxonomy)
            status[row["status"]] += n
            by_row[row["curlie_path"]] += n
            category[row["we360_category"]] += n if row["status"] == "confident" else 0
    print(f"\n## Retained listings by status\n{dict(status)} total {sum(status.values())}")
    print("\n## Listings and registered domains per We360 category")
    for name in CATEGORIES:
        print(f"{category[name]:>7} {len(category_domains[name]):>7}  {name}{'  BELOW 50' if category[name] < 50 else ''}")
    print("\n## Listings per taxonomy row")
    for path, row in taxonomy.items():
        print(f"{by_row[path]:>7}  {path}  [{row['status']}] {row['we360_category']}")
    print("rows matching no listing:", [path for path in taxonomy if not by_row[path]])


def report_world(path_listings):
    languages = collections.Counter()
    for path, n in path_listings.items():
        if path.startswith("World/"):
            languages[path.split("/")[1]] += n
    print(f"\n## World: {sum(languages.values())} listings in {len(languages)} languages")
    for language, n in languages.most_common(10):
        print(f"{n:>7}  {language}")
    indian = {name: languages[name] for name in INDIAN_LANGUAGES}
    print("Indian languages:", indian, "total", sum(indian.values()))


def report_cross_language(descriptions, path_listings):
    links = set()
    for path, description in descriptions.items():
        if path.startswith("World/"):
            for link in LINK.findall(description):
                target = link.strip("/")
                if target.split("/")[0] in TOPIC_BRANCHES:
                    links.add((path, target))
    sources = {path for path, _ in links}
    world_categories = sum(path.startswith("World/") for path in descriptions)
    direct_listings = sum(path_listings[path] for path in sources)
    print("\n## Cross-language links (free text in category descriptions; the dump has no altlang field)")
    print(f"World to English: {len(links)} links from {len(sources)} of {world_categories} World categories, "
          f"which directly hold {direct_listings} listings")
    for path, target in sorted(links, key=lambda link: -path_listings[link[0]])[:5]:
        print(f"  {path_listings[path]:>4} listings  {path}  ->  {target}")


def report_regional(path_listings):
    listings, india, parents = collections.Counter(), collections.Counter(), collections.defaultdict(set)
    regional_total = india_total = 0
    for path, n in path_listings.items():
        parts = path.split("/")
        if parts[0] != "Regional":
            continue
        in_india = parts[1:3] == ["Asia", "India"]
        regional_total += n
        india_total += n if in_india else 0
        for i, segment in enumerate(parts[1:], start=1):
            parents[segment].add("/".join(parts[:i]))
        for segment in set(parts[1:]):
            listings[segment] += n
            india[segment] += n if in_india else 0
    # A topic recurs under many places, while a place name has few parents. Localities only organises places.
    topics = [segment for segment in parents if len(parents[segment]) >= 100 and segment != "Localities"]
    print(f"\n## Regional: {regional_total} listings; Asia/India: {india_total}")
    print("Top topic segments, all Regional:", sorted(((listings[s], s) for s in topics), reverse=True)[:15])
    print("Top topic segments, India:", sorted(((india[s], s) for s in topics), reverse=True)[:15])


def count_domains(domain_flags, has_flag, lacks_flag):
    """Count domains that have any of the has_flag bits and none of the lacks_flag bits."""
    return sum(1 for flags in domain_flags.values() if flags & has_flag and not flags & lacks_flag)


def report_kids(domain_flags):
    kids = KIDS_ENGLISH | KIDS_INTERNATIONAL
    everything_else = RETAINED | OTHER
    print("\n## Registered domains in Kids_and_Teens")
    print(f"listed only in Kids_and_Teens: {count_domains(domain_flags, kids, everything_else)} "
          f"(with an English listing: {count_domains(domain_flags, KIDS_ENGLISH, everything_else)})")
    print(f"no retained listing: {count_domains(domain_flags, kids, RETAINED)} "
          f"(with an English listing: {count_domains(domain_flags, KIDS_ENGLISH, RETAINED)})")


def main():
    taxonomy = load_map()
    path_of, descriptions = {}, {}
    for category_id, path, description in read_categories():
        path_of[category_id], descriptions[path] = path, description
    path_listings, domain_flags, category_domains = collections.Counter(), collections.defaultdict(int), collections.defaultdict(set)
    for url, _title, _description, category_id in iter_listings():
        path = path_of[category_id]
        path_listings[path] += 1
        normal = normalize_url(url)
        if normal:
            domain = registered_domain(normal[1])
            domain_flags[domain] |= flag_for(path)
            row = None if path.split("/")[0] in IGNORED_BRANCHES else match_row(path, taxonomy)
            if row and row["status"] == "confident":
                category_domains[row["we360_category"]].add(domain)
    branches = collections.Counter()
    for path, n in path_listings.items():
        branches[path.split("/")[0]] += n
    print(f"## Listings per top-level branch ({sum(branches.values())} in total)")
    for branch, n in branches.most_common():
        print(f"{n:>8}  {branch}{'  (ignored)' if branch in IGNORED_BRANCHES else ''}")
    report_mapping(path_listings, category_domains, taxonomy)
    report_world(path_listings)
    report_cross_language(descriptions, path_listings)
    report_regional(path_listings)
    report_kids(domain_flags)


if __name__ == "__main__":
    write_report("dump_report.txt", main)
