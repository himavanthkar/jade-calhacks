# People and controls

## Who decides what

| Decision | Who | How it's held to account |
|---|---|---|
| Every amount: accruals, clearing, catch-ups, ratios | Deterministic code | Debits equal credits on every journal; gates block the period; CSV exports recompute in Excel |
| Clearing what the agreement supports, within the mined tolerance | The agent | The mined control and the past cases that taught it are on the entry |
| Disputing duplicates, missing proof, unsupported amounts | The agent | Holding is always allowed; disputing never writes off |
| Anything the agreement can't settle, or over a threshold | A person, on a card with the agent's recommendation | Overruling the recommendation needs a reason; the reason becomes the precedent |
| Restatements, write-offs, signing the close | The controller / close reviewer, by name | The engine alone never approves or signs; SoD throws on the negotiator and on the agent |
| Wording of cards and answers (optional) | Claude | A rewrite that changes any number or id is thrown away |

## Working with people

- **Ask at the right moment.** Each card names who it's for (source conflict → customer team, can't verify → controller, needs authority → the control's owner), the evidence, the options, and what the agent recommends and why.
- **Answers stick.** An answer is stored as a precedent on (control, specific conflict, customer) and the next match is settled without asking. A standing approval covers only up to the largest amount a person approved; a bigger case asks again, saying why. In the played year, 37 of 40 repeat situations settled silently; the 3 asked again were each larger than any amount approved so far.
- **The controller says no.** Overruling the recommendation requires reasoning that isn't just the option's label. The precedent records what it overruled, and later cases follow the person, not the agent (`make says-no`; ask the interrogation box "What if the controller had said no?").
- **Busy approvers.** A card that has sat through a close unanswered for more than 10 days goes up to the controller, saying who didn't answer and that the close is waiting.
- **Work handed over half done.** A colleague's handoff is re-checked, never trusted: finished if every control passes, handed back with the reason if not, refused if the proposed program's terms don't cover the claim.
- **Segregation of duties.** `can_approve` throws when the approver negotiated the program, when no program can be traced (unverifiable), or when the approver is the agent.

The accounting rules every decision follows are in [`.claude/rules/`](../.claude/rules/).
