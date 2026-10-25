# Integrations

JADE reads two outside sources. Both appear on the **Integrations** page of the UI.

| Source | What it gives JADE | Code |
|---|---|---|
| **Gmail**: the deductions inbox | Retailer deduction notices, claim backup, forwarded amendments, colleagues' notes | `tpa/mail.py` |
| **SEC EDGAR** | General Mills' 10-K figures that the close's analytical review compares against | `scripts/pull_10k.py`, `tpa/seed/calibration.py` |

## The deductions inbox

Retailers send deduction notices and backup by email, and people forward amendments and their own notes
about deals into a shared deductions inbox. JADE reads that inbox the way it reads contracts. The parser
is deterministic, and every field it reads keeps the sentence it came from. A message is a source
document, never an instruction.

| What the message is | What it becomes |
|---|---|
| Deduction notice (amount, program, claim period, rate, units) | a deduction, and its backup if the notice carries it |
| Claim backup for a deduction already taken | backup: a claim held for missing backup is re-checked and cleared |
| A signed amendment, forwarded | an amendment: read into terms, closed months restated |
| One of our people saying a rate was agreed, with nothing signed | **context only**, quoted on the cards it bears on |
| Anything else | kept and quoted, never acted on |

Source rows go through the same path as live scenarios (`tpa.scenario.inject`), so the engine meets them
on the next step exactly as it meets seeded data, and the evaluator scores them apart from the planted errors.

**How the email changes the decision.** Walmart claims September at $4.50 a case; TP-0214 says $4.20.

| | Without the email | With the sales lead's "$4.50 agreed, paperwork to follow" |
|---|---|---|
| Who gets the card | Customer team analyst | Controller |
| Recommendation | Program as signed: dispute the difference (last year's precedent) | Hold until the signed amendment arrives |
| Why | A source conflict: which document is right? | An email is not an agreement (rule 1); an unsupported claim is held (rule 8); the sales lead negotiated the deal and can't approve its claim |

The note bears only on claims for the months it names, never on months already claimed under the old terms
(`tpa.mail.bears_on`), and only on a claim at the rate it asserts. When the signed amendment arrives, JADE
reads it and sends the controller the restatement.

## Demo runbook

```sh
make db-reset seed
uv run python scripts/step.py --through month-9 --players    # play January to September
uv run python scripts/demo_mail.py run side-letter --no-step  # the note and Walmart's claim, read into October
uv run python scripts/demo_mail.py run amendment              # the signed amendment; October runs
make api                                                      # then open Integrations and the Escalation Inbox
```

`run late-backup` shows the other direction: a claim held for missing backup clears when the scan data
arrives by email, and JADE withdraws its own dispute. `send <scenario>` only sends: show the mail arriving
in Gmail, then press **Sync and run the month** on the Integrations page.

### Gmail

1. Authorise the Google Workspace CLI for Gmail once: `gws auth login -s gmail`.
2. In `.env`: `JADE_MAIL_BACKEND=gmail` and `JADE_MAIL_ADDRESS=you+jade-deductions@gmail.com`. A
   plus-address keeps the demo mail apart from the rest of the mailbox; JADE reads only mail sent to it.
   A separate demo Gmail account works the same way.
3. `uv run python scripts/demo_mail.py run side-letter` sends the messages to that address, waits for Gmail
   to deliver them, reads them and runs the month.

Every demo message is a forward. The original sender, a reserved `.example` address such as
`supplier.claims@walmart.example`, is kept in the forwarded header, so nothing is ever sent as a real
company. Without Gmail, `JADE_MAIL_BACKEND=local` reads `.eml` files from `data/inbox` and runs offline.

The UI's mock mode replays an inbox captured from the API (`scripts/mail_fixture.py`).
