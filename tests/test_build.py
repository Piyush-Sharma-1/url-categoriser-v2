import gzip
import json

from src import build, reporting


def test_build_report_records_dropped_listings(tmp_path, monkeypatch):
    listings = [(("a.com", "a.com", ""), "Sports"), (("a.com/x", "a.com", "/x"), "Games"), (None, "Sports")]
    monkeypatch.setattr(build, "iter_retained", lambda: listings)
    monkeypatch.setattr(build, "LOOKUP_PATH", tmp_path / "lookup.json.gz")
    monkeypatch.setattr(reporting, "REPORTS", tmp_path)

    reporting.write_report("build_report.txt", build.build_lookup)

    assert "1 listings dropped" in (tmp_path / "build_report.txt").read_text(encoding="utf-8")
    lookup = json.loads(gzip.decompress((tmp_path / "lookup.json.gz").read_bytes()))
    assert lookup["paths"] == ["Sports", "Games"]
    assert lookup["hosts"]["a.com"] == [[0], [1]]
