"""Read the Curlie dump and the taxonomy map."""
import csv
from pathlib import Path

from src.normalize import normalize_url

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw" / "curlie-rdf"
MAP_PATH = ROOT / "data" / "taxonomy_map.csv"

# Ignored completely: neither votes nor training data. Adult stays in the map as unmapped.
IGNORED_BRANCHES = {"World", "Regional", "Kids_and_Teens"}
CATEGORIES = (
    "Analytics", "Banking & Finance", "Calling & Phone", "Chat & Messaging", "Design", "Developer", "E-commerce",
    "Education", "Email", "File Sharing", "Gaming", "Hiring & Recruitment", "In House Tools", "Internet", "Job Search",
    "Knowledge Management", "Lifestyle", "Marketing", "Meeting", "Music & Videos", "News & Entertainment", "Office Apps",
    "Photos", "Research & Reference", "Shopping", "Social Media", "Sports", "System Processes",
)  # The 29th category, Undefined, is an outcome rather than a mapping target.

csv.field_size_limit(10**7)  # Some category descriptions are very long.


def read_tsv(path):
    with open(path, encoding="utf-8", errors="replace", newline="") as f:
        yield from csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE)


def read_categories(raw_dir=RAW_DIR):
    """Yield (category_id, curlie_path, description) for every category in the dump."""
    for path in sorted(raw_dir.glob("*-s.tsv")):
        for row in read_tsv(path):
            yield row[0], row[1], row[3]


def iter_listings(raw_dir=RAW_DIR):
    """Yield (url, title, description, category_id) for every site listing in the dump."""
    for path in sorted(raw_dir.glob("*-c.tsv")):
        yield from read_tsv(path)


def iter_retained(raw_dir=RAW_DIR):
    """Yield (normalize_url result or None, curlie_path) for every listing outside the ignored branches."""
    path_of = {category_id: path for category_id, path, _ in read_categories(raw_dir)}
    for url, _title, _description, category_id in iter_listings(raw_dir):
        curlie_path = path_of[category_id]
        if curlie_path.split("/")[0] not in IGNORED_BRANCHES:
            yield normalize_url(url), curlie_path


def load_map(path=MAP_PATH):
    with open(path, encoding="utf-8", newline="") as f:
        return {row["curlie_path"]: row for row in csv.DictReader(f)}


def match_row(curlie_path, taxonomy):
    """Return the map row with the longest whole-segment prefix of curlie_path, or None."""
    parts = curlie_path.split("/")
    for end in range(len(parts), 0, -1):
        row = taxonomy.get("/".join(parts[:end]))
        if row:
            return row
    return None
