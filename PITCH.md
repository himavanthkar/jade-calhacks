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

**Shot list.** Follow the usage flow in `specs/jade-demo-and-close-exports.html` ("Usage flow: Walmart's October close"),
beat for beat: its voice-over lines, the buttons to click (shown as orange callouts in its screenshots), and the
journal entry behind each step. The arc is the close itself:

| Time | Close step | Screen and click | Land this line |
|---|---|---|---|
| 0:00 | The problem | Home | $493M of trade promotion accruals, a critical accounting estimate |
| 0:25 | Contract set-up | Setup → Read the agreements | Each term cites its clause |
| 0:45 | Deduction intake | Mailbox → Integrations → the deduction notice | Parsed by code, every field keeps its line |
| 1:15 | Exceptions | Home → Review | Three items need a person, each with a recommendation |
| 1:30 | Segregation of duties | Answer as the sales lead → Approve | Refused, in code |
| 1:50 | Change in estimate | Approve the restatement | $190,415.99 catch-up; then and now both on record |
| 2:15 | Exception with evidence | Customer's claimed rate → reason → Decide | The reason becomes the precedent |
| 2:40 | Reconciliation | Kroger → Release the accrual | No claim in five months |
| 2:55 | Sign-off | Close → Sign off | A failing check blocks the close |
| 3:15 | Close binder | Close report | Every number traceable to its journal line |

Record the screen from the demo state (Phase 1 of the plan), never from a database someone has been clicking in.

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
