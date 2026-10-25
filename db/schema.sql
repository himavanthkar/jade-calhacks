-- Trade Promotion Autonomy — full DDL.
--
-- Conventions
--   * period         'YYYY-MM' text. History = 2025-01..2025-12, live year = 2026-01..2026-12.
--   * available_at   the simulated date a source row lands in our systems. The month
--                    stepper only ever shows rows with available_at <= the sim date.
--   * valid_time     when a fact was true in the world.
--   * decision_time  when we learned it / posted it (simulated clock, never now()).
--   * Money is NUMERIC(14,2); rates NUMERIC(12,6). No floats anywhere.
--   * The ledger is insert-only. Corrections are new rows with a later decision_time.

-- ─────────────────────────────────────────────────────────────────────────────
-- Simulation clock and actors
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE sim_clock (
  id BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (id),     -- single row
  current_period TEXT NOT NULL,
  sim_date DATE NOT NULL
);

CREATE TABLE actors (
  id TEXT PRIMARY KEY,                -- e.g. 'sales.walmart', 'controller'
  name TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN (
    'sales_lead', 'customer_team_analyst', 'controller', 'close_reviewer',
    'trade_promotion_accountant', 'deduction_analyst', 'agent')),
  customer_id TEXT                    -- set for customer-facing roles
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Layer 0: the source systems
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE customers (
  id TEXT PRIMARY KEY,                -- 'WMT', 'COST', 'KR'
  name TEXT NOT NULL,
  channel TEXT NOT NULL
);

CREATE TABLE trade_programs (
  id TEXT PRIMARY KEY,                -- 'TP-0214'
  customer_id TEXT NOT NULL REFERENCES customers(id),
  document_text TEXT NOT NULL,
  program_type TEXT NOT NULL CHECK (program_type IN ('off_invoice', 'scan_back', 'display', 'mdf')),
  signed_date DATE NOT NULL,
  negotiated_by TEXT NOT NULL REFERENCES actors(id),   -- SoD hinges on this
  available_at DATE NOT NULL
);

-- Amendments arrive as their own documents. effective_date can sit inside a
-- period that is already closed by the time available_at comes round: that gap
-- is what triggers restatement.
CREATE TABLE program_amendments (
  id TEXT PRIMARY KEY,                -- 'AM-02'
  program_id TEXT NOT NULL REFERENCES trade_programs(id),
  document_text TEXT NOT NULL,
  effective_date DATE NOT NULL,       -- valid time
  signed_date DATE NOT NULL,
  available_at DATE NOT NULL          -- when it reaches us
);

CREATE TABLE shipments (
  id TEXT PRIMARY KEY,                -- 'SH-0412'
  customer_id TEXT NOT NULL REFERENCES customers(id),
  program_id TEXT REFERENCES trade_programs(id),       -- null = unpromoted volume
  period TEXT NOT NULL,
  cases INT NOT NULL CHECK (cases >= 0),
  gross_price NUMERIC(12,4) NOT NULL,                  -- per case
  ship_date DATE NOT NULL,
  available_at DATE NOT NULL
);

-- Returns are their own rows because they can reach us after the shipment's
-- period was accrued: promoted volume has to be netted late.
CREATE TABLE returns (
  id TEXT PRIMARY KEY,
  shipment_id TEXT NOT NULL REFERENCES shipments(id),
  customer_id TEXT NOT NULL REFERENCES customers(id),
  cases INT NOT NULL CHECK (cases > 0),
  return_date DATE NOT NULL,
  available_at DATE NOT NULL
);

CREATE TABLE invoices (
  id TEXT PRIMARY KEY,                -- 'INV-…'
  customer_id TEXT NOT NULL REFERENCES customers(id),
  shipment_id TEXT REFERENCES shipments(id),
  period TEXT NOT NULL,
  gross_amount NUMERIC(14,2) NOT NULL,
  off_invoice_amount NUMERIC(14,2) NOT NULL DEFAULT 0, -- allowance taken at invoice
  invoice_date DATE NOT NULL,
  available_at DATE NOT NULL
);

CREATE TABLE deductions (
  id TEXT PRIMARY KEY,                -- 'DD-3391'
  invoice_id TEXT REFERENCES invoices(id),
  customer_id TEXT NOT NULL REFERENCES customers(id),
  program_id TEXT REFERENCES trade_programs(id),       -- often null: the matching problem
  amount NUMERIC(14,2) NOT NULL CHECK (amount > 0),
  reason_code TEXT NOT NULL,
  claimed_rate NUMERIC(12,6),                          -- rate the customer says applies
  taken_date DATE NOT NULL,                            -- months after the promo period
  claimed_period TEXT NOT NULL,                        -- the period the customer says it relates to
  claim_start DATE,                                    -- the activity dates the claim covers
  claim_end DATE,
  cleared_by TEXT REFERENCES actors(id),
  approved_by TEXT REFERENCES actors(id),
  available_at DATE NOT NULL,
  CHECK (cleared_by IS NULL OR approved_by IS NULL OR cleared_by <> approved_by)
);

CREATE TABLE claim_backup (
  id TEXT PRIMARY KEY,
  deduction_id TEXT NOT NULL REFERENCES deductions(id),
  scan_units INT,
  scan_rate NUMERIC(12,6),
  proof_of_performance BOOLEAN NOT NULL DEFAULT FALSE,
  notes TEXT,                                          -- the retailer's own words, verbatim
  received_date DATE NOT NULL,
  available_at DATE NOT NULL
);

CREATE TABLE disputes (
  id TEXT PRIMARY KEY,
  deduction_id TEXT NOT NULL REFERENCES deductions(id),
  disputed_amount NUMERIC(14,2) NOT NULL,
  raised_date DATE NOT NULL,
  resolution TEXT CHECK (resolution IN ('upheld', 'recovered', 'partial')),
  resolved_date DATE,
  resolution_amount NUMERIC(14,2),
  available_at DATE NOT NULL          -- when the resolution reaches us
);

-- What the humans actually did during the history year. Onboarding diffs its
-- deterministic replay against this; every mined control cites rows from here.
CREATE TABLE historical_decisions (
  id TEXT PRIMARY KEY,                -- 'HD-…'
  period TEXT NOT NULL,
  customer_id TEXT NOT NULL REFERENCES customers(id),
  subject_type TEXT NOT NULL CHECK (subject_type IN (
    'deduction', 'accrual', 'shipment', 'claim_backup', 'dispute')),
  subject_id TEXT NOT NULL,
  action TEXT NOT NULL CHECK (action IN (
    'accept_variance', 'adjust', 'reverse_claim', 'recover', 'write_off',
    'escalate', 'release_stale_accrual')),
  amount NUMERIC(14,2),
  variance_pct NUMERIC(12,6),
  reason TEXT NOT NULL,
  decided_by TEXT NOT NULL REFERENCES actors(id),
  decided_at TIMESTAMP NOT NULL,
  journal_id TEXT                     -- the ledger journal it produced, if any
);

-- Things the model-played humans will try to do on a given simulated date,
-- e.g. a sales lead approving a claim on their own program.
-- Rows a person injected live (POST /api/scenario): what they asked for and the source rows it
-- made. The engine handles them like any other data; the evaluator scores them apart, since the
-- answer key never planted them.
CREATE TABLE scenario_injections (
  id TEXT PRIMARY KEY,                -- 'SC-0001'
  kind TEXT NOT NULL,
  payload JSONB NOT NULL,
  created_ids TEXT[] NOT NULL,
  period TEXT NOT NULL,               -- the month it lands in
  sim_date DATE NOT NULL,             -- the day it lands
  injected_by TEXT,
  injected_at TIMESTAMP NOT NULL DEFAULT now()
);

-- Mail that reached the deductions inbox (tpa.mail): the message as received, what the parser read
-- from it, and what the engine did with it. A message is a source document, never an instruction:
-- a deduction notice, backup or signed amendment becomes source rows through `scenario.inject`;
-- anything else is context the judgment engine quotes on the card it concerns.
CREATE TABLE inbound_messages (
  id TEXT PRIMARY KEY,                -- 'EM-0001'
  source TEXT NOT NULL,               -- 'gmail' | 'local'
  message_id TEXT NOT NULL UNIQUE,    -- the mailbox's own id: a message is ingested once
  from_addr TEXT NOT NULL,            -- the original sender (of a forward, the forwarded message's)
  forwarded_by TEXT,
  subject TEXT NOT NULL,
  body TEXT NOT NULL,
  received_at TIMESTAMP NOT NULL,     -- real time, as the mailbox stamped it
  sim_date DATE NOT NULL,             -- the day it lands in the simulation
  period TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('deduction_notice', 'claim_backup', 'amendment', 'unsigned_terms', 'unrecognised')),
  customer_id TEXT REFERENCES customers(id),
  sender_actor TEXT REFERENCES actors(id),   -- set when the sender is one of our own people
  parsed JSONB NOT NULL DEFAULT '{}', -- every field read, each with the line it was read from
  injection_id TEXT REFERENCES scenario_injections(id),
  created_ids TEXT[] NOT NULL DEFAULT '{}'
);

-- Work a colleague hands over half done: a held deduction, what they propose, what they did and
-- what is left. The agent re-checks it rather than trusting it, then finishes it or hands it back.
CREATE TABLE handoffs (
  id TEXT PRIMARY KEY,                -- 'HO-0001'
  sim_date DATE NOT NULL,
  from_actor TEXT NOT NULL REFERENCES actors(id),
  deduction_id TEXT NOT NULL REFERENCES deductions(id),
  proposed_program_id TEXT REFERENCES trade_programs(id),
  proposed_decision TEXT NOT NULL CHECK (proposed_decision IN ('clear', 'dispute')),
  done TEXT,                          -- the colleague's own words: what they did
  left_to_do TEXT,                    -- and what they didn't get to
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'completed', 'returned', 'no_op')),
  outcome JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE scripted_events (
  id TEXT PRIMARY KEY,                -- 'EV-…'
  sim_date DATE NOT NULL,
  actor_id TEXT NOT NULL REFERENCES actors(id),
  action TEXT NOT NULL,               -- 'approve'
  target_type TEXT NOT NULL,          -- 'deduction' | 'restatement'
  target_id TEXT NOT NULL,
  note TEXT
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Layer 1: the context graph
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE program_terms (
  id TEXT PRIMARY KEY,
  program_id TEXT NOT NULL REFERENCES trade_programs(id),
  customer_id TEXT NOT NULL REFERENCES customers(id),
  program_type TEXT NOT NULL CHECK (program_type IN ('off_invoice', 'scan_back', 'display', 'mdf')),
  rate NUMERIC(16,6) NOT NULL,      -- per case, or the lump sum for mdf/display
  rate_unit TEXT NOT NULL CHECK (rate_unit IN ('per_case', 'pct_of_gross', 'lump_sum')),
  base_definition TEXT NOT NULL CHECK (base_definition IN ('shipped_cases', 'scan_units', 'gross_sales', 'fixed')),
  projected_redemption NUMERIC(12,6),  -- scan-back: expected sell-through. The estimate.
  window_start DATE NOT NULL,
  window_end DATE NOT NULL,
  requires_proof BOOLEAN NOT NULL DEFAULT FALSE,
  source_clause_id TEXT,               -- e.g. 'TP-0214#4.2'
  amendment_id TEXT REFERENCES program_amendments(id),
  valid_from DATE NOT NULL,
  valid_to DATE,                       -- null = open-ended
  decision_time TIMESTAMP NOT NULL,    -- when WE learned this term existed
  CHECK (window_end >= window_start),
  CHECK (valid_to IS NULL OR valid_to >= valid_from)
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Layer 2: the controls library
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE controls (
  id TEXT PRIMARY KEY,                -- stable slug, e.g. 'CTL-DED-GT-ACCRUAL'
  name TEXT NOT NULL,
  condition TEXT NOT NULL,            -- an evaluable expression, not prose
  threshold NUMERIC(14,6),
  threshold_unit TEXT CHECK (threshold_unit IN ('usd', 'pct', 'periods')),
  owner_role TEXT NOT NULL,           -- who this escalates to
  precedent_ids TEXT[] NOT NULL DEFAULT '{}',   -- historical_decisions that taught it
  mined_at TIMESTAMP NOT NULL,
  learned BOOLEAN NOT NULL DEFAULT FALSE,       -- added after onboarding
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'retired', 'tuned'))
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Layer 3: judgment
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE findings (
  id TEXT PRIMARY KEY,
  period TEXT NOT NULL,
  customer_id TEXT NOT NULL REFERENCES customers(id),
  control_id TEXT NOT NULL REFERENCES controls(id),
  severity TEXT NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
  amount NUMERIC(14,2),
  exposure NUMERIC(14,2),             -- dollars at risk, drives escalation lane
  confidence NUMERIC(5,4),            -- below threshold → low_confidence escalation
  state TEXT NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'auto_resolved', 'escalated', 'resolved')),
  escalation_type TEXT CHECK (escalation_type IN ('authority', 'source_conflict', 'low_confidence', 'sod')),
  conflict_type TEXT,                 -- precedent match key
  evidence JSONB NOT NULL DEFAULT '{}',   -- ids of every row that triggered it
  created_at TIMESTAMP NOT NULL
);

CREATE TABLE escalations (
  id TEXT PRIMARY KEY,
  finding_id TEXT NOT NULL REFERENCES findings(id),
  to_role TEXT NOT NULL,
  question TEXT NOT NULL,
  options JSONB NOT NULL DEFAULT '[]',
  answer TEXT,
  answered_by TEXT REFERENCES actors(id),
  answered_at TIMESTAMP,
  recommended TEXT,                   -- the option the agent recommends, and why
  recommendation_basis TEXT,
  became_precedent_id TEXT,
  created_at TIMESTAMP NOT NULL
);

CREATE TABLE precedents (
  id TEXT PRIMARY KEY,
  control_id TEXT NOT NULL REFERENCES controls(id),
  conflict_type TEXT NOT NULL,
  customer_id TEXT NOT NULL REFERENCES customers(id),
  decision TEXT NOT NULL,             -- which source won, or approve | reject
  reasoning TEXT NOT NULL,            -- rejections carry reasoning
  decided_by TEXT NOT NULL REFERENCES actors(id),
  decided_at TIMESTAMP NOT NULL,
  exposure_limit NUMERIC(14,2),       -- authority decisions apply silently only up to the exposure decided on
  overrode TEXT,                      -- the agent's recommendation this decision turned down, if it did
  from_escalation_id TEXT REFERENCES escalations(id)
);

ALTER TABLE escalations
  ADD CONSTRAINT escalations_precedent_fk
  FOREIGN KEY (became_precedent_id) REFERENCES precedents(id) DEFERRABLE INITIALLY DEFERRED;

CREATE INDEX precedents_match_idx ON precedents (control_id, conflict_type, customer_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- Layer 4: the bitemporal ledger
-- ─────────────────────────────────────────────────────────────────────────────

-- One row per period per customer: the cycle runs per customer, and a period is
-- closed for sign-off when every customer row for it is SIGNED.
CREATE TABLE periods (
  period TEXT NOT NULL,
  customer_id TEXT NOT NULL REFERENCES customers(id),
  state TEXT NOT NULL DEFAULT 'OPEN' CHECK (state IN (
    'OPEN', 'ACCRUED', 'CONTROLLED', 'ESCALATED', 'REVIEWED', 'SIGNED', 'CLOSED', 'RESTATED')),
  signed_by TEXT REFERENCES actors(id),
  signed_at TIMESTAMP,
  gate_results JSONB NOT NULL DEFAULT '{}',
  PRIMARY KEY (period, customer_id)
);

-- Every signature, kept forever. periods.signed_by/at is the latest; a period
-- re-signed after restatement keeps its original sign-off here.
CREATE TABLE period_signoffs (
  id BIGSERIAL PRIMARY KEY,
  period TEXT NOT NULL,
  customer_id TEXT NOT NULL REFERENCES customers(id),
  signed_by TEXT NOT NULL REFERENCES actors(id),
  signed_at TIMESTAMP NOT NULL,
  gate_results JSONB NOT NULL,
  FOREIGN KEY (period, customer_id) REFERENCES periods(period, customer_id)
);

CREATE TABLE ledger_entries (
  id TEXT PRIMARY KEY,                -- 'JE-1184-1' (journal id + line number)
  journal_id TEXT NOT NULL,           -- 'JE-1184'; debits = credits per journal
  entry_type TEXT NOT NULL CHECK (entry_type IN (
    'opening', 'revenue', 'accrual', 'reversal', 'clearing', 'dispute', 'restatement', 'adjustment')),
  period TEXT NOT NULL,
  customer_id TEXT NOT NULL REFERENCES customers(id),
  program_id TEXT REFERENCES trade_programs(id),
  account TEXT NOT NULL,
  debit NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (debit >= 0),
  credit NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (credit >= 0),
  memo TEXT,
  reversal_of TEXT REFERENCES ledger_entries(id),   -- the accrual line this reverses
  restates TEXT REFERENCES ledger_entries(id),      -- the line this restates
  source_finding_id TEXT REFERENCES findings(id),
  deduction_id TEXT REFERENCES deductions(id),      -- the deduction a clearing or dispute line settles
  -- valid_time: the last day of the activity period the money relates to. For
  -- accrual and clearing lines that is the shipment (origin) period, so a Feb
  -- accrual cleared in July still carries valid_time 2026-02-28.
  valid_time DATE NOT NULL,
  decision_time TIMESTAMP NOT NULL,   -- when we knew it
  approved_by TEXT REFERENCES actors(id),
  CHECK ((debit = 0) <> (credit = 0))  -- exactly one side per line
);

CREATE SEQUENCE journal_seq START 1000;   -- JE-1000, JE-1001, … allocated by tpa.ledger.post_journal

CREATE INDEX ledger_asof_idx ON ledger_entries (period, decision_time);
CREATE INDEX ledger_program_idx ON ledger_entries (program_id, period);
CREATE INDEX ledger_journal_idx ON ledger_entries (journal_id);

-- The close's analytical review: the period's total trade promotion liability against an
-- expectation from public filings (the latest 10-K at the time). Judgment, not a gate: outside
-- the range it needs the reviewer's explanation before signing. One per period.
CREATE TABLE analytical_reviews (
  id TEXT PRIMARY KEY,                -- 'AR-2026-08'
  period TEXT NOT NULL UNIQUE,
  measure TEXT NOT NULL,
  liability NUMERIC(16,2) NOT NULL,
  net_sales_annualized NUMERIC(16,2) NOT NULL,
  ratio NUMERIC(12,8) NOT NULL,
  expectation NUMERIC(12,8),          -- NULL when no filing was public yet
  low NUMERIC(12,8),
  high NUMERIC(12,8),
  within_range BOOLEAN,
  source JSONB NOT NULL DEFAULT '{}', -- the filing: fiscal year, accession, url, the quoted sentence
  drivers JSONB NOT NULL DEFAULT '[]',
  narrative TEXT NOT NULL,
  decision_time TIMESTAMP NOT NULL
);

CREATE TABLE flux_commentary (
  id TEXT PRIMARY KEY,
  period TEXT NOT NULL,
  account TEXT NOT NULL,
  current_balance NUMERIC(14,2) NOT NULL,
  prior_balance NUMERIC(14,2) NOT NULL,
  pct_change NUMERIC(12,6),
  narrative TEXT NOT NULL,
  driver_entry_ids TEXT[] NOT NULL DEFAULT '{}',
  decision_time TIMESTAMP NOT NULL,
  approved_by TEXT REFERENCES actors(id),
  approved_at TIMESTAMP
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Ledger guarantees, enforced by the database rather than by convention
-- ─────────────────────────────────────────────────────────────────────────────

-- 1. Insert-only.
CREATE FUNCTION ledger_forbid_mutation() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION '% is insert-only (% rejected); post a reversing or restating entry instead', TG_TABLE_NAME, TG_OP;
END
$$ LANGUAGE plpgsql;

CREATE TRIGGER ledger_no_update_delete
  BEFORE UPDATE OR DELETE ON ledger_entries
  FOR EACH ROW EXECUTE FUNCTION ledger_forbid_mutation();

CREATE TRIGGER ledger_no_truncate
  BEFORE TRUNCATE ON ledger_entries
  FOR EACH STATEMENT EXECUTE FUNCTION ledger_forbid_mutation();

CREATE TRIGGER signoffs_no_update_delete
  BEFORE UPDATE OR DELETE ON period_signoffs
  FOR EACH ROW EXECUTE FUNCTION ledger_forbid_mutation();

-- 2. A period that has ever been signed only accepts restating entries, including
--    while it is RESTATED and working back through review to a new signature.
CREATE FUNCTION ledger_check_period_open() RETURNS trigger AS $$
DECLARE
  s TEXT;
  signed TIMESTAMP;
BEGIN
  SELECT state, signed_at INTO s, signed FROM periods
   WHERE period = NEW.period AND customer_id = NEW.customer_id;
  IF (s IN ('SIGNED', 'CLOSED') OR signed IS NOT NULL) AND NEW.restates IS NULL THEN
    RAISE EXCEPTION 'period % for % is %; only restating entries may be written to it',
      NEW.period, NEW.customer_id, s;
  END IF;
  RETURN NEW;
END
$$ LANGUAGE plpgsql;

CREATE TRIGGER ledger_period_lock
  BEFORE INSERT ON ledger_entries
  FOR EACH ROW EXECUTE FUNCTION ledger_check_period_open();

-- 3. Debits equal credits per journal, checked at commit so a journal's lines
--    can be inserted one at a time inside a transaction.
CREATE FUNCTION ledger_check_journal_balanced() RETURNS trigger AS $$
DECLARE
  d NUMERIC;
  c NUMERIC;
BEGIN
  SELECT COALESCE(SUM(debit), 0), COALESCE(SUM(credit), 0) INTO d, c
    FROM ledger_entries WHERE journal_id = NEW.journal_id;
  IF d <> c THEN
    RAISE EXCEPTION 'journal % does not balance: debits % <> credits %', NEW.journal_id, d, c;
  END IF;
  RETURN NULL;
END
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER ledger_journal_balanced
  AFTER INSERT ON ledger_entries
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION ledger_check_journal_balanced();

-- 4. Signed periods cannot be quietly unsigned or edited back to OPEN.
CREATE FUNCTION periods_check_transition() RETURNS trigger AS $$
BEGIN
  IF OLD.signed_at IS NOT NULL AND NEW.signed_at IS NULL THEN
    RAISE EXCEPTION 'period % for % was signed; a signature cannot be removed', OLD.period, OLD.customer_id;
  END IF;
  IF OLD.state IN ('SIGNED', 'CLOSED') AND NEW.state NOT IN ('SIGNED', 'CLOSED', 'RESTATED') THEN
    RAISE EXCEPTION 'period % for % is %; it can only move to RESTATED', OLD.period, OLD.customer_id, OLD.state;
  END IF;
  RETURN NEW;
END
$$ LANGUAGE plpgsql;

CREATE TRIGGER periods_transition_guard
  BEFORE UPDATE ON periods
  FOR EACH ROW EXECUTE FUNCTION periods_check_transition();
