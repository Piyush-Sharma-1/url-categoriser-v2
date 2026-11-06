"""Save what a reporting step prints in reports/."""
import contextlib

from src.curlie_data import ROOT

REPORTS = ROOT / "reports"


def write_report(name, step):
    """Run a reporting step and save what it prints."""
    REPORTS.mkdir(exist_ok=True)
    with open(REPORTS / name, "w", encoding="utf-8") as f, contextlib.redirect_stdout(f):
        step()
    print(f"Report: reports/{name}")
