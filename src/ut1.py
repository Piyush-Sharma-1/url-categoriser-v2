"""UT1 source: download the archive and read its domain lists (docs/DECISIONS.md, Section O)."""
import hashlib
import tarfile
import urllib.request

from src.curlie_data import ROOT
from src.normalize import normalize_url

ARCHIVE_URL = "https://dsi.ut-capitole.fr/blacklists/download/blacklists.tar.gz"
ARCHIVE = ROOT / "data" / "raw" / "ut1" / "blacklists.tar.gz"
SNAPSHOT_SHA256 = "e12f93efa8687f641132b54ad37ce8e4889f1e8c1be646f357b200d93e329d96"
UT1_DIR = ARCHIVE.parent / "blacklists"


def fetch_ut1():
    """Download and extract the archive unless it is already here, and warn if it differs from the recorded snapshot."""
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    if not ARCHIVE.exists():
        print(f"Downloading {ARCHIVE_URL} (about 27 MB)")
        partial = ARCHIVE.with_suffix(".part")
        urllib.request.urlretrieve(ARCHIVE_URL, partial)
        partial.replace(ARCHIVE)
    if hashlib.sha256(ARCHIVE.read_bytes()).hexdigest() != SNAPSHOT_SHA256:
        print("WARNING: this UT1 archive differs from the recorded snapshot, so numbers may change.")
    if not UT1_DIR.exists():
        with tarfile.open(ARCHIVE) as tar:
            tar.extractall(ARCHIVE.parent, filter="data")


def list_categories(raw_dir=UT1_DIR):
    """Return the real category folders, skipping aliases such as porn -> adult."""
    return sorted(path.name for path in raw_dir.iterdir() if path.is_dir() and not path.is_symlink())


def read_entries(category, raw_dir=UT1_DIR):
    """Return the non-empty, non-comment lines of a category's domains file."""
    path = raw_dir / category / "domains"
    if not path.exists():
        return []
    lines = (line.strip() for line in path.read_text(encoding="utf-8", errors="replace").splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def load_ut1_rows(categories, raw_dir=UT1_DIR):
    """Yield (host, source_category) for the given categories. Other lists are never opened."""
    for category in categories:
        for entry in read_entries(category, raw_dir):
            normal = normalize_url(entry)
            if normal and not normal[2]:  # An entry must be a host: anything invalid or with a path is skipped.
                yield normal[1], category
