"""Classify URLs from the command line: python -m src.cli https://zoom.us"""
import json
import sys

from src.classify import classify


def main(urls):
    if not urls:
        print("Usage: python -m src.cli URL [URL ...]", file=sys.stderr)
        return 2
    for url in urls:
        print(json.dumps(classify(url), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
