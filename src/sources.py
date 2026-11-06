"""Pluggable host-list sources, consulted after Curlie (docs/DECISIONS.md, Section O).

A source has a name, a display label, a folder holding its mapping and lookup, a row loader for the build, and a load
function for classification. Adding a source means adding one more entry to SOURCES.
"""
import gzip
import json
from functools import lru_cache

from src.curlie_data import ROOT
from src.normalize import registered_domain
from src.ut1 import load_ut1_rows

LOOKUP_NAME = "lookup.json.gz"
UT1_FOLDER = ROOT / "data" / "sources" / "ut1"


@lru_cache(maxsize=None)
def load_source_lookup(folder):
    """Return {host: precomputed decision}. This loads only when a URL first gets this far."""
    return json.loads(gzip.decompress((folder / LOOKUP_NAME).read_bytes()))


def matching_entry(host, hosts):
    """Return the longest entry that is the host or a parent of it, stopping at the registered domain, or None.

    An entry never applies to sibling hosts, so listing copilot.microsoft.com says nothing about learn.microsoft.com.
    """
    domain = registered_domain(host)
    labels = host.split(".")
    for start in range(len(labels)):
        candidate = ".".join(labels[start:])
        if candidate in hosts:
            return candidate
        if candidate == domain:
            break
    return None


def source_decision(host, source):
    """Return a source's decision for a host as a dict, or None if no entry matches."""
    hosts = source["load"]()
    entry = matching_entry(host, hosts)
    if entry is None:
        return None
    label = source["label"]
    evidence = [f"{label} entry: {entry}", f"{label} categories: {', '.join(hosts[entry]['lists'])}"]
    return {**hosts[entry], "method": source["name"], "label": label, "entry": entry, "evidence": evidence}


UT1 = {
    "name": "ut1",
    "label": "UT1",
    "folder": UT1_FOLDER,
    "load_rows": load_ut1_rows,
    "load": lambda: load_source_lookup(UT1_FOLDER),
}
SOURCES = (UT1,)
