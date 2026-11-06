"""Download the Curlie dump and regenerate the lookup and model: python -m src.build"""
import collections
import gzip
import hashlib
import json
import tarfile
import urllib.request

from src import evaluate, train
from src.curlie_data import RAW_DIR, iter_retained
from src.lookup import DEEP, HOMEPAGE, LOOKUP_PATH
from src.normalize import registered_domain
from src.reporting import write_report

DUMP_URL = "https://curlie.org/directory-dl"
ARCHIVE = RAW_DIR.parent / "curlie-rdf-all.tar.gz"
SNAPSHOT_SHA256 = "696098a50485445886e763c70f330a32e9214036316b0d66e67dbd54a71b0e04"


def fetch_dump():
    """Download and extract the dump unless it is already here, and warn if it differs from the README's snapshot."""
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    if not ARCHIVE.exists():
        print(f"Downloading {DUMP_URL} (about 177 MB)")
        partial = ARCHIVE.with_suffix(".part")
        urllib.request.urlretrieve(DUMP_URL, partial)
        partial.replace(ARCHIVE)
    if hashlib.sha256(ARCHIVE.read_bytes()).hexdigest() != SNAPSHOT_SHA256:
        print("WARNING: this dump differs from the README's snapshot, so numbers may change.")
    if not RAW_DIR.exists():
        with tarfile.open(ARCHIVE) as tar:
            tar.extractall(RAW_DIR.parent, filter="data")


def build_lookup():
    """Write every retained listing to the lookup: {host: [homepage listings, deep-page listings]}."""
    names, index = [], {}
    hosts = collections.defaultdict(lambda: ([], []))
    dropped = 0
    for normal, curlie_path in iter_retained():
        if normal is None:
            dropped += 1
            continue
        if curlie_path not in index:
            index[curlie_path] = len(names)
            names.append(curlie_path)
        _normalized, host, path = normal
        hosts[host][DEEP if path else HOMEPAGE].append(index[curlie_path])

    domains = collections.defaultdict(list)
    for host in hosts:
        domains[registered_domain(host)].append(host)
    # A domain whose only host is the domain itself needs no entry, which keeps the file small.
    domain_hosts = {domain: members for domain, members in domains.items() if members != [domain]}

    payload = json.dumps({"paths": names, "hosts": hosts, "domain_hosts": domain_hosts}, ensure_ascii=False, separators=(",", ":"))
    LOOKUP_PATH.write_bytes(gzip.compress(payload.encode("utf-8"), mtime=0))
    print(f"Lookup: {len(hosts)} hosts, {dropped} listings dropped because their URLs failed normalisation")
    print(f"{LOOKUP_PATH.name}: {LOOKUP_PATH.stat().st_size / 1e6:.1f} MB")


def main():
    fetch_dump()
    build_lookup()
    write_report("training_report.txt", train.main)
    evaluate.main(["validation"])


if __name__ == "__main__":
    main()
