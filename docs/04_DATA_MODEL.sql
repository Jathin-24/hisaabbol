-- HisaabBol server schema (SQLite). Source of truth: backend/app/db.py (created automatically on first start).
-- Money = INTEGER paise. Timestamps = UTC ISO-8601. Raw SMS/notification text is never stored.

CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY, name TEXT, token_hash TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings (
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, key TEXT NOT NULL, value TEXT NOT NULL,
  PRIMARY KEY (user_id, key));
CREATE TABLE IF NOT EXISTS captures (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  dedupe_key TEXT NOT NULL,
  direction TEXT NOT NULL CHECK (direction IN ('debit','credit')),
  amount_paise INTEGER NOT NULL CHECK (amount_paise > 0),
  counterparty TEXT, counterparty_is_person INTEGER,
  upi_ref TEXT, account_last4 TEXT, instrument TEXT,
  source TEXT NOT NULL, occurred_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',      -- pending | answered | skipped | auto_categorized
  prompted INTEGER NOT NULL DEFAULT 0,         -- 1 = user was asked now; 0 = waits for the digest
  transaction_id INTEGER, created_at TEXT NOT NULL,
  UNIQUE (user_id, dedupe_key));
CREATE INDEX IF NOT EXISTS idx_cap_user_status ON captures(user_id, status);
CREATE TABLE IF NOT EXISTS transactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  capture_id INTEGER REFERENCES captures(id) ON DELETE SET NULL,
  direction TEXT NOT NULL, amount_paise INTEGER NOT NULL,
  counterparty TEXT, occurred_at TEXT NOT NULL, instrument TEXT, account_last4 TEXT,
  user_note TEXT, note_language TEXT, confidence REAL, needs_review INTEGER NOT NULL DEFAULT 0,
  source TEXT NOT NULL DEFAULT 'voice', created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_tx_user_time ON transactions(user_id, occurred_at);
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  transaction_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL, label TEXT NOT NULL, amount_paise INTEGER NOT NULL, category TEXT NOT NULL, note TEXT);
CREATE INDEX IF NOT EXISTS idx_items_tx ON items(transaction_id);
CREATE INDEX IF NOT EXISTS idx_items_user_cat ON items(user_id, category);
CREATE TABLE IF NOT EXISTS merchant_rules (
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, merchant_key TEXT NOT NULL,
  category TEXT NOT NULL, times_confirmed INTEGER NOT NULL DEFAULT 1, auto_apply INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, merchant_key));
CREATE TABLE IF NOT EXISTS people (
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL COLLATE NOCASE, phone TEXT, UNIQUE (user_id, name));
CREATE TABLE IF NOT EXISTS udhaar (
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  person_id INTEGER NOT NULL REFERENCES people(id),
  direction TEXT NOT NULL CHECK (direction IN ('i_lent','i_borrowed')),
  amount_paise INTEGER NOT NULL, settled_paise INTEGER NOT NULL DEFAULT 0,
  due_date TEXT, status TEXT NOT NULL DEFAULT 'open', note TEXT,
  transaction_id INTEGER, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_udhaar_user ON udhaar(user_id, status);
CREATE TABLE IF NOT EXISTS budgets (
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  category TEXT NOT NULL,                       -- '*' = overall monthly budget
  limit_paise INTEGER NOT NULL CHECK (limit_paise > 0), UNIQUE (user_id, category));
CREATE TABLE IF NOT EXISTS budget_alerts (
  user_id TEXT NOT NULL, category TEXT NOT NULL, month TEXT NOT NULL, threshold INTEGER NOT NULL,
  PRIMARY KEY (user_id, category, month, threshold));
CREATE TABLE IF NOT EXISTS reports (
  user_id TEXT NOT NULL, month TEXT NOT NULL, fingerprint TEXT NOT NULL, language TEXT NOT NULL,
  insights_json TEXT NOT NULL, provider TEXT, generated_at TEXT NOT NULL, PRIMARY KEY (user_id, month, language));
CREATE TABLE IF NOT EXISTS idempotency (
  user_id TEXT NOT NULL, key TEXT NOT NULL, response_json TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY (user_id, key));
CREATE TABLE IF NOT EXISTS api_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, route TEXT, method TEXT, status INTEGER,
  latency_ms INTEGER, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS gnani_usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, kind TEXT NOT NULL, ok INTEGER NOT NULL,
  latency_ms INTEGER, audio_bytes INTEGER, chars INTEGER, created_at TEXT NOT NULL);
