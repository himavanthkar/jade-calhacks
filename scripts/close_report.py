"""Print the close report to PDF (headless Chrome), for the close binder or the pitch deck.

    uv run python scripts/close_report.py 2026-10 [--out reports/] [--api http://127.0.0.1:8000]

The same page as Close → Close report in the UI (GET /api/period/{period}/export/close_report.html).
"""

import argparse
import subprocess
import sys
from pathlib import Path

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("period")
    ap.add_argument("--out", default="reports")
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    args = ap.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    pdf = out / f"jade-close-{args.period}.pdf"
    url = f"{args.api}/api/period/{args.period}/export/close_report.html"
    r = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={pdf}", url],
                       capture_output=True, text=True)
    if r.returncode or not pdf.exists():
        sys.exit(f"could not print {url}: {r.stderr.strip()[:300]}")
    print(f"wrote {pdf}")


if __name__ == "__main__":
    main()
