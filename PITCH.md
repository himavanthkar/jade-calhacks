# JADE — the pitch

Deterministic JADE Engine: autonomous trade promotion accounting for General Mills. Cal Hacks 13.0,
Hyphenate track.

## The problem

| | |
|---|---|
| **$18.4B** | General Mills net sales, FY2026 (10-K) |
| **22%** | of it to Walmart (10-K) |
| **$493M** | accrued trade and coupon promotions, a named critical accounting estimate (10-K) |
| **~20%** | of CPG gross sales goes to trade (Strategy&/PwC) |
| **−13 / +7 pts** | Q4 operating profit growth moved by trade timing, FY2025 / FY2026 (earnings releases) |
| **~$97** | to process one deduction by hand (CRF benchmark) |

The failure that matters is not a bad claim; it is a good document nobody entered. In the simulation,
Walmart and General Mills sign an amendment in February (TP-0214, $3.80 → $4.20 a case). It is filed and
forgotten; six months close short. When it surfaces, someone must re-price closed months, explain the
catch-up, and stop the sales lead who negotiated it from approving it. Real books show the same mechanism
in public: General Mills told investors that trade expense timing cost 3 points of Q4 sales growth in
FY2024 and added 7 points of Q4 profit growth in FY2026.

These facts live in one place, [`tpa/problem.py`](tpa/problem.py): the Overview shows them, and the agent
answers "What problem does JADE solve?" from them in the Ask box. Change them there, never in prose.

## What JADE is

JADE takes the trade promotion accountant's and the deduction analyst's seats. It accrues on shipment,
matches each deduction to its program, clears what the agreement supports, disputes what it doesn't,
restates closed months when terms change, and packages the close for a person to sign.

- **Deterministic where money moves.** Every number is computed by code into an insert-only ledger; a
  model only drafts sentences, and a rewrite that changes a number is thrown away.
- **Taught, not configured.** Onboarding replays last year's books and mines its controls from the
  decisions people made in them.
- **Asks once.** A person's answer becomes a precedent; the same situation settles silently next time.
- **Shows why.** Every card carries the path it took through the judgment gate.
- **Can't approve its own deal.** Segregation of duties is a check that throws, not a prompt.

## The demo, in four beats (3½ minutes)

The word-for-word transcript, with the click for each line and a screenshot per beat, is in
[`specs/jade-demo-and-close-exports.html`](specs/jade-demo-and-close-exports.html).

1. **The problem** (Overview): the six numbers above, on screen.
2. **It reopens its own books** (Restatement Comparison): the forgotten amendment, $1,391,636.52 across
   February–July, found in August; then and now side by side.
3. **It reads the email; it doesn't obey it** (Integrations → Escalation Inbox): the sales lead's "$4.50,
   paperwork to follow" sends Walmart's claim to the controller with a hold, and the tree shows why; the
   sales lead's own approval is refused.
4. **The close leaves** (Backtest → Flux): tested on sixteen years of General Mills' 10-Ks; the flux
   commentary cites its journal lines; the package exports.

## Proof

- 50 planted errors, 100% precision and recall on seed 1337 and two unseen seeds ([Proof](docs/proof.md)).
- Backtested on real filings: audited books swing up to 22.1% a year; carry-forward misses by 9.4%,
  scaling by sales by 12.3% ([Backtest](docs/presenting.md)).
- Simulation beside sourced industry figures, gaps explained ([Benchmarks](docs/benchmarks.md)).

## Say it right

- Say "simulation" for every transaction. General Mills, its customers and the 10-K figures are real; the
  transactions are generated, because transaction-level trade data is never public.
- JADE is a deterministic engine. It does not use LangGraph or any agent framework for decisions.
- The Gmail demo reads a deductions mailbox; retailers mostly send deductions through portals and
  remittance files, which take the same path (planned).

---

## Brief for the video agent

A video agent produces the 2–3 minute demo video from this repo. The agent definition is
[`.claude/agents/jade-video.md`](.claude/agents/jade-video.md); start it with
"Use the jade-video agent to make the demo video." What follows is its brief.

**Deliverable.** `video/jade-demo.mp4`, 1920×1080, 30 fps, 2:30–3:00, with burned-in captions and a separate
`video/jade-demo.srt`. A 20-second cut (`video/jade-teaser.mp4`) of beats 1 and 3 for social.

**Inputs, all in the repo.**

| Need | Where |
|---|---|
| Script, beat by beat | `specs/jade-demo-and-close-exports.html` (Demo transcript) |
| The problem's facts | `tpa/problem.py` (quote exactly) |
| Screenshots of the real UI | `docs/images/ui-*.jpg` |
| Brand: parchment `#fbf8f3`, orange `#E86F31`, oxblood `#5b241d`, EB Garamond headings | `README.md` art, `frontend/src/*.css` |
| Live app for screen capture | `make api` and the frontend (`docs/getting-started.md`), or the preview state in `docs/integrations.md` |
| Story photography | `docs/images/gm-*.jpg` (credits in `docs/images/CREDITS.md`) |

**Shot list.**

| Time | Shot | On screen | Voice |
|---|---|---|---|
| 0:00–0:20 | Cereal table photo, slow push | Title: JADE | The cereal we grew up on was sold on a promise to the retailer. |
| 0:20–0:45 | Overview, the problem strip | The six numbers, one at a time | $493M of those promises, a critical estimate in General Mills' 10-K. |
| 0:45–1:25 | Restatement Comparison | Then / now | An amendment nobody entered; JADE finds $1.39M on its own. |
| 1:25–2:05 | Integrations map → the email card → its decision tree | The tree's lit path | It reads the email; it doesn't obey it. |
| 2:05–2:30 | Backtest charts | 22.1%, 9.4% vs 12.3% | Tested on sixteen years of real filings. |
| 2:30–2:50 | Flux & Close Review, export | The narrative's journal ids | The close explains itself and leaves signed. |
| 2:50–3:00 | Logo on parchment | Deterministic JADE Engine | Deterministic where money moves. |

**Rules for the video agent.**

- Every number on screen or in the voiceover comes from `tpa/problem.py`, the transcript, or the UI capture;
  never round differently, never invent one.
- Label simulated screens "Simulation" once, in the corner, the first time they appear.
- No General Mills, Walmart, Kroger or Costco logos; product names only where the README already uses them.
- Don't claim LangGraph, real-time accounting, or a live QuickBooks connection.
- Voiceover: calm, plain, one idea per sentence; captions match the voiceover word for word.
- Tools: the `explainer-video` skill for script-to-storyboard and caption sync; Remotion or ffmpeg for the cut;
  ElevenLabs (if connected) for the voice, picking a clear, neutral voice.
- Before handing over: watch the full cut once, check every number against its source, and list the sources
  in `video/SOURCES.md`.
