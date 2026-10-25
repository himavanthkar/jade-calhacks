"""Render the demo mailbox as a Gmail-style inbox and an opened message, for the pitch deck and the demo plan.

    uv run python scripts/gmail_preview.py --mail-dir data/inbox --out specs/jade-demo-and-close-exports [--open 2]

Reads the same .eml files JADE reads (written by scripts/demo_mail.py), so every subject, sender and line on
screen is the scenario's real mail. The page says "Demo mailbox · simulated" in its header: it is a
rehearsal prop for when the live Gmail account isn't connected, never a copy of anyone's real inbox.
Screenshots are taken with headless Chrome.
"""

import argparse
import subprocess
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tpa.mail import LocalInbox, unwrap  # noqa: E402

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CSS = """
*{box-sizing:border-box}body{margin:0;font:14px Roboto,Arial,sans-serif;color:#1f1f1f;background:#f6f8fc}
.top{display:flex;align-items:center;gap:18px;height:64px;padding:0 16px}
.top img{height:28px}.brand{font-size:22px;color:#444746;display:flex;align-items:center;gap:8px}
.search{flex:1;max-width:720px;height:46px;border-radius:24px;background:#e9eef6;display:flex;align-items:center;padding:0 20px;color:#444746}
.demo{margin-left:auto;font-size:12px;color:#8a4b1d;background:#fbe9df;border:1px solid #f0c9b2;border-radius:12px;padding:4px 10px}
.wrap{display:grid;grid-template-columns:240px 1fr;gap:8px;padding:0 16px 16px}
.nav .compose{display:inline-flex;align-items:center;gap:12px;background:#c2e7ff;border-radius:16px;padding:16px 24px;font-weight:500;margin:4px 0 14px}
.nav div.item{padding:6px 24px;border-radius:0 16px 16px 0;font-size:14px;display:flex;justify-content:space-between}
.nav div.item.on{background:#d3e3fd;font-weight:700}
.pane{background:#fff;border-radius:16px;min-height:640px;overflow:hidden}
.bar{height:48px;border-bottom:1px solid #f1f3f4;display:flex;align-items:center;padding:0 16px;color:#444746;font-size:13px;gap:20px}
.row{display:grid;grid-template-columns:28px 210px 1fr 90px;gap:10px;align-items:center;height:40px;padding:0 16px;border-bottom:1px solid #f1f3f4;font-size:14px}
.row.unread{font-weight:700;background:#fff}.row.read{background:#f2f6fc;font-weight:400}
.row .snip{color:#5f6368;font-weight:400}.row>span:nth-child(3){white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.row .time{text-align:right;font-size:12px}
.row.focus{box-shadow:inset 3px 0 #E86F31}
.label{font-size:11px;font-weight:500;background:#ddd;border-radius:4px;padding:1px 6px;margin-right:6px;color:#444}
.msg{padding:20px 28px 40px}.msg h1{font:400 22px 'Google Sans',Roboto,Arial,sans-serif;margin:8px 0 18px}
.from{display:flex;gap:12px;align-items:center;margin-bottom:18px}.av{width:40px;height:40px;border-radius:50%;background:#E86F31;color:#fff;display:grid;place-items:center;font-weight:700}
.from b{font-size:14px}.from small{color:#5f6368;font-size:12px;display:block}
pre{font:14px/1.6 Roboto,Arial,sans-serif;white-space:pre-wrap;margin:0;color:#222}
.fwd{border-left:2px solid #dadce0;padding-left:14px;margin-top:12px;color:#222}
"""


def page(body: str) -> str:
    return (f"<!doctype html><html><head><meta charset=utf-8><style>{CSS}</style></head><body>"
            f"<div class=top><span class=brand><img src='{(ROOT / 'frontend/public/brand/gmail.svg').as_uri()}' alt=''>Mail</span>"
            f"<div class=search>Search mail</div><span class=demo>Demo mailbox · simulated forwards (.example senders)</span></div>"
            f"<div class=wrap><div class=nav><div class=compose>✎ Compose</div><div class='item on'><span>Deductions</span><span>{{n}}</span></div>"
            f"<div class=item>Inbox</div><div class=item>Starred</div><div class=item>Sent</div></div><div class=pane>{body}</div></div></body></html>")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mail-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--open", type=int, default=2, help="which message to open, 1-based in arrival order")
    args = ap.parse_args()
    msgs = LocalInbox(args.mail_dir).fetch()
    if not msgs:
        sys.exit(f"no .eml files in {args.mail_dir}; run scripts/demo_mail.py first")
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, m in enumerate(reversed(msgs), start=1):
        sender, _, text = unwrap(m)
        snippet = " ".join(text.split())[:110]
        focus = " focus" if len(msgs) - i + 1 == args.open else ""
        rows.append(f"<div class='row {'unread' if i <= 2 else 'read'}{focus}'><span>☆</span><span>{escape(sender.split('@')[0])}</span>"
                    f"<span><span class=label>Deductions</span>{escape(m.subject)} <span class=snip>— {escape(snippet)}</span></span>"
                    f"<span class=time>{m.received_at:%b %-d}</span></div>")
    inbox = page(f"<div class=bar>☐ ⟳ ⋮<span style='margin-left:auto'>1–{len(msgs)} of {len(msgs)}</span></div>{''.join(rows)}").replace("{n}", str(len(msgs)))
    m = msgs[args.open - 1]
    sender, forwarded_by, text = unwrap(m)
    head, _, fwd = m.body.partition("---------- Forwarded message ---------")
    message = page(f"<div class=bar>← ⬚ 🗑 ✉ ⋮</div><div class=msg><h1>{escape(m.subject)} <span class=label>Deductions</span></h1>"
                   f"<div class=from><div class=av>{escape((forwarded_by or sender)[0].upper())}</div><div><b>{escape(forwarded_by or sender)}</b>"
                   f"<small>to deductions · {m.received_at:%b %-d, %Y, %-I:%M %p}</small></div></div><pre>{escape(head.strip())}</pre>"
                   f"<pre class=fwd>---------- Forwarded message ---------{escape(fwd)}</pre></div>").replace("{n}", str(len(msgs)))
    for name, html in (("gmail-inbox", inbox), ("gmail-message", message)):
        src = out / f"{name}.html"
        src.write_text(html)
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--screenshot={out / (name + '.png')}",
                        "--window-size=1440,820", src.as_uri()], check=True, capture_output=True)
        src.unlink()
        print(f"wrote {out / (name + '.png')}")


if __name__ == "__main__":
    main()
