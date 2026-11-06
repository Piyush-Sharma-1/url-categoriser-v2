"""URL normalisation and offline registered-domain extraction, shared by the build and classification."""
import ipaddress
import re
from urllib.parse import urlsplit

import tldextract

SYSTEM_SCHEMES = ("chrome", "edge", "about", "file", "chrome-extension", "moz-extension", "brave", "opera", "view-source")
NON_WEB_PREFIXES = ("mailto:", "tel:", "sms:", "javascript:", "data:")
HAS_SCHEME = re.compile(r"[a-z][a-z0-9+.-]*://", re.I)
VALID_HOST = re.compile(r"[a-z0-9._-]+")

# Bundled suffix list only, with no network or cache. Private suffixes make each *.blogspot.com blog its own site.
TLD_OPTIONS = {"suffix_list_urls": (), "cache_dir": None, "include_psl_private_domains": True}
_extract = tldextract.TLDExtract(**TLD_OPTIONS)


def registered_domain(host):
    """Return the host's registered domain, or the host itself for IPs and platform roots such as github.io."""
    return _extract(host).top_domain_under_public_suffix or host


def system_scheme(raw):
    """Return the system scheme that starts the input, or None."""
    text = raw.strip().lower()
    return next((scheme for scheme in SYSTEM_SCHEMES if text.startswith(scheme + ":")), None)


def parse_ip(host):
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def normalize_url(raw):
    """Return (normalized, host, path), or None if the input is invalid. The host excludes any port."""
    text = raw.strip()
    has_scheme = bool(HAS_SCHEME.match(text))
    if not has_scheme and text.lower().startswith(NON_WEB_PREFIXES):
        return None
    if not has_scheme and not system_scheme(text):
        text = "http://" + text
    try:
        parts = urlsplit(text)
        host, port = parts.hostname, parts.port
    except ValueError:
        return None
    if not host:
        return None
    if not parse_ip(host):
        try:
            host = host.lower().encode("idna").decode()
        except UnicodeError:
            return None
        host = host.removesuffix(".").removeprefix("www.")
        if not VALID_HOST.fullmatch(host):
            return None
        if "." not in host and host != "localhost" and not has_scheme and port is None:
            return None  # A bare word such as "banana" is not a URL.
    path = parts.path.rstrip("/")
    netloc = f"[{host}]" if ":" in host else host
    if port not in (None, 80, 443):
        netloc += f":{port}"
    return netloc + path, host, path
