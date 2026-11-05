-- Mock ERP schema, owned only by services/erp-mock (§B5). Synthetic data only.
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE SCHEMA IF NOT EXISTS erp;

CREATE TABLE IF NOT EXISTS erp.vendors (
  org_id text NOT NULL, id text NOT NULL, name text NOT NULL, aliases jsonb NOT NULL DEFAULT '[]',
  tax_id text NOT NULL, category text NOT NULL, currency char(3) NOT NULL, country text NOT NULL,
  address text NOT NULL, payment_terms_days int NOT NULL, cost_center text NOT NULL,
  created_by text, contract_id text, status text NOT NULL DEFAULT 'active',
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (org_id, id)
);
CREATE TABLE IF NOT EXISTS erp.vendor_bank_accounts (
  org_id text NOT NULL, vendor_id text NOT NULL, account_hash text NOT NULL,
  last4 char(4) NOT NULL CHECK (last4 ~ '^[0-9]{4}$'), effective_from date NOT NULL,
  effective_to date, changed_by text,
  PRIMARY KEY (org_id, vendor_id, effective_from),
  FOREIGN KEY (org_id, vendor_id) REFERENCES erp.vendors (org_id, id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS erp.employees (
  org_id text NOT NULL, id text NOT NULL, name text NOT NULL, email text NOT NULL, role text NOT NULL,
  bank_hash text NOT NULL, bank_last4 char(4) NOT NULL,
  PRIMARY KEY (org_id, id)
);
CREATE TABLE IF NOT EXISTS erp.gl_accounts (
  org_id text NOT NULL, code text NOT NULL, name text NOT NULL, guidance text NOT NULL,
  PRIMARY KEY (org_id, code)
);
CREATE TABLE IF NOT EXISTS erp.cost_centers (
  org_id text NOT NULL, code text NOT NULL, name text NOT NULL, PRIMARY KEY (org_id, code)
);
CREATE TABLE IF NOT EXISTS erp.contracts (
  org_id text NOT NULL, id text NOT NULL, vendor_id text NOT NULL, description text NOT NULL,
  monthly_cap_minor bigint NOT NULL, currency char(3) NOT NULL, start_date date NOT NULL, end_date date NOT NULL,
  PRIMARY KEY (org_id, id)
);
CREATE TABLE IF NOT EXISTS erp.purchase_orders (
  org_id text NOT NULL, po_number text NOT NULL, vendor_id text NOT NULL, currency char(3) NOT NULL,
  order_date date NOT NULL, requester_id text NOT NULL, status text NOT NULL DEFAULT 'open',
  PRIMARY KEY (org_id, po_number)
);
CREATE TABLE IF NOT EXISTS erp.po_lines (
  org_id text NOT NULL, po_number text NOT NULL, line_no int NOT NULL, description text NOT NULL,
  quantity numeric NOT NULL CHECK (quantity > 0), uom text NOT NULL,
  unit_price_minor bigint NOT NULL, gl_account text NOT NULL, cost_center text NOT NULL,
  is_service boolean NOT NULL DEFAULT false, billed_qty numeric NOT NULL DEFAULT 0,
  PRIMARY KEY (org_id, po_number, line_no),
  FOREIGN KEY (org_id, po_number) REFERENCES erp.purchase_orders (org_id, po_number) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS erp.goods_receipts (
  org_id text NOT NULL, grn_number text NOT NULL, po_number text NOT NULL, received_date date NOT NULL,
  PRIMARY KEY (org_id, grn_number)
);
CREATE TABLE IF NOT EXISTS erp.grn_lines (
  org_id text NOT NULL, grn_number text NOT NULL, po_line int NOT NULL, quantity numeric NOT NULL CHECK (quantity >= 0),
  PRIMARY KEY (org_id, grn_number, po_line),
  FOREIGN KEY (org_id, grn_number) REFERENCES erp.goods_receipts (org_id, grn_number) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS erp.posted_invoices (
  org_id text NOT NULL, erp_ref text NOT NULL, idempotency_key text NOT NULL, vendor_id text,
  invoice_number text NOT NULL, amount_minor bigint NOT NULL, currency char(3) NOT NULL,
  route text NOT NULL, posted_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (org_id, erp_ref), UNIQUE (org_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS erp.payments (
  org_id text NOT NULL, payment_ref text NOT NULL, erp_ref text NOT NULL, idempotency_key text NOT NULL,
  amount_minor bigint NOT NULL CHECK (amount_minor > 0), currency char(3) NOT NULL, due_date date NOT NULL,
  approval_jti text, scheduled_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (org_id, payment_ref), UNIQUE (org_id, idempotency_key), UNIQUE (approval_jti)
);
CREATE TABLE IF NOT EXISTS erp.vendor_change_requests (
  org_id text NOT NULL, id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, vendor_id text NOT NULL,
  field text NOT NULL, requested_by text NOT NULL, note text NOT NULL, status text NOT NULL DEFAULT 'open',
  created_at timestamptz NOT NULL DEFAULT now()
);
