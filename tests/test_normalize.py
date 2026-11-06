import socket

import pytest
import tldextract

from src.classify import classify
from src.normalize import TLD_OPTIONS, registered_domain

UNDEFINED, IN_HOUSE, SYSTEM = "Undefined", "In House Tools", "System Processes"


@pytest.mark.parametrize("raw, normalized, category", [
    # Normalisation. None as the category means any category is acceptable here.
    ("https://WWW.Chess.com/play/?x=1#top", "chess.com/play", None),
    ("zoom.us", "zoom.us", "Meeting"),
    ("  zoom.us/j/1/  ", "zoom.us/j/1", "Meeting"),
    ("accounts.google.com/signin?continue=https://mail.google.com", "accounts.google.com/signin", None),
    ("http://example.com:80/a", "example.com/a", None),
    ("https://example.com:443", "example.com", None),
    ("https://example.com:8443/a", "example.com:8443/a", None),
    ("example.com.", "example.com", None),
    ("пример.рф", "xn--e1afmkfd.xn--p1ai", None),
    # In House Tools.
    ("localhost", "localhost", IN_HOUSE),
    ("localhost:3000", "localhost:3000", IN_HOUSE),
    ("192.168.1.5:8080/admin", "192.168.1.5:8080/admin", IN_HOUSE),
    ("http://10.0.0.1/", "10.0.0.1", IN_HOUSE),
    ("127.0.0.1", "127.0.0.1", IN_HOUSE),
    ("[::1]:3000", "[::1]:3000", IN_HOUSE),
    ("wiki.internal/page/", "wiki.internal/page", IN_HOUSE),
    ("build.corp", "build.corp", IN_HOUSE),
    ("printer.local", "printer.local", IN_HOUSE),
    ("nas.lan", "nas.lan", IN_HOUSE),
    ("hr.intranet", "hr.intranet", IN_HOUSE),
    ("http://jira/", "jira", IN_HOUSE),
    ("jira:8080", "jira:8080", IN_HOUSE),
    # System Processes.
    ("chrome://settings", None, SYSTEM),
    ("  CHROME://settings", None, SYSTEM),
    ("edge://flags", None, SYSTEM),
    ("about:blank", None, SYSTEM),
    ("file:///C:/notes.txt", None, SYSTEM),
    ("chrome-extension://abc/page.html", None, SYSTEM),
    ("moz-extension://abc/page.html", None, SYSTEM),
    ("brave://rewards", None, SYSTEM),
    ("opera://settings", None, SYSTEM),
    ("view-source:https://example.com", None, SYSTEM),
    # Invalid.
    ("", None, UNDEFINED),
    ("http://", None, UNDEFINED),
    ("banana", None, UNDEFINED),
    ("not a url", None, UNDEFINED),
    ("http://exa mple.com", None, UNDEFINED),
    ("a..b.com", None, UNDEFINED),
    ("example.com:notaport", None, UNDEFINED),
    ("::1", None, UNDEFINED),
    ("mailto:a@b.com", None, UNDEFINED),
    ("tel:5551234", None, UNDEFINED),
    ("sms:5551234", None, UNDEFINED),
    ("javascript:void(0)", None, UNDEFINED),
    ("data:text/html,hello", None, UNDEFINED),
])
def test_normalisation_and_rules(raw, normalized, category):
    result = classify(raw)
    assert result["normalized"] == normalized
    if category:
        assert result["category"] == category
    if category in (IN_HOUSE, SYSTEM):
        assert (result["method"], result["confidence"]) == ("rule", 1.0)
    if category == UNDEFINED:
        assert result["undefined_reason"] == "invalid_url"


def test_public_ip_is_not_in_house():
    assert classify("8.8.8.8")["category"] != IN_HOUSE


@pytest.mark.parametrize("host, expected", [
    ("bbc.co.uk", "bbc.co.uk"),
    ("news.bbc.co.uk", "bbc.co.uk"),
    ("mail.google.com", "google.com"),
    ("myblog.blogspot.com", "myblog.blogspot.com"),  # Each blog is its own site.
    ("github.io", "github.io"),  # A platform root falls back to the host.
    ("8.8.8.8", "8.8.8.8"),  # So does an IP.
])
def test_registered_domain(host, expected):
    assert registered_domain(host) == expected


def test_domain_extraction_works_with_network_blocked(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    extract = tldextract.TLDExtract(**TLD_OPTIONS)  # A fresh extractor must load its suffix list here.
    assert extract("bbc.co.uk").top_domain_under_public_suffix == "bbc.co.uk"
