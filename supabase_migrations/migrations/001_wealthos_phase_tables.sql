-- WealthOS: phase tables missing from older projects (fixes PGRST205 for user_profile, etc.)
-- Run in Supabase Dashboard → SQL → New query → paste → Run.
-- Uses auth.users FK so rows tie to real accounts. service_role bypasses RLS if you enable it later.

-- user_profile (dashboard, tax, insurance, agent)
create table if not exists public.user_profile (
  user_id uuid primary key references auth.users (id) on delete cascade,
  age integer not null default 0,
  target_retirement_age integer not null default 60,
  monthly_income double precision not null default 0,
  income_type text not null default 'salaried',
  tax_bracket integer not null default 30,
  tax_regime text not null default 'new',
  updated_at timestamptz default now()
);

create table if not exists public.illiquid_assets (
  id bigserial primary key,
  user_id uuid not null references auth.users (id) on delete cascade,
  asset_type text not null default 'other',
  name text not null default 'Unnamed Asset',
  estimated_value double precision not null default 0,
  loan_outstanding double precision not null default 0,
  notes text not null default ''
);
create index if not exists illiquid_assets_user_id_idx on public.illiquid_assets (user_id);

create table if not exists public.credit_cards (
  id bigserial primary key,
  user_id uuid not null references auth.users (id) on delete cascade,
  card_name text not null default 'Unnamed Card',
  credit_limit double precision not null default 0,
  current_outstanding double precision not null default 0,
  billing_date integer not null default 1,
  payment_due_date integer not null default 1,
  apr_percent double precision not null default 0,
  min_due_amount double precision not null default 0
);
create index if not exists credit_cards_user_id_idx on public.credit_cards (user_id);

create table if not exists public.tax_investments (
  id bigserial primary key,
  user_id uuid not null references auth.users (id) on delete cascade,
  financial_year text not null,
  instrument_type text not null default 'other_80c',
  amount_invested double precision not null default 0,
  notes text not null default ''
);
create index if not exists tax_investments_user_fy_idx on public.tax_investments (user_id, financial_year);

create table if not exists public.capital_gains (
  id bigserial primary key,
  user_id uuid not null references auth.users (id) on delete cascade,
  asset_name text not null default 'Unknown Asset',
  asset_type text not null default 'other',
  buy_date date not null default (current_date),
  buy_price double precision not null default 0,
  sell_date date,
  sell_price double precision,
  units double precision not null default 0,
  notes text not null default ''
);
create index if not exists capital_gains_user_id_idx on public.capital_gains (user_id);

create table if not exists public.insurance_policies (
  id bigserial primary key,
  user_id uuid not null references auth.users (id) on delete cascade,
  policy_name text not null default 'Unknown Policy',
  policy_type text not null default 'other',
  insurer text not null default '',
  annual_premium double precision not null default 0,
  sum_assured double precision,
  maturity_value double precision,
  start_date date,
  maturity_date date,
  is_active boolean not null default true,
  notes text not null default ''
);
create index if not exists insurance_policies_user_id_idx on public.insurance_policies (user_id);

create table if not exists public.emergency_fund (
  user_id uuid primary key references auth.users (id) on delete cascade,
  target_months integer not null default 6,
  current_amount double precision not null default 0,
  account_name text not null default '',
  updated_at timestamptz default now()
);

create table if not exists public.goals (
  id bigserial primary key,
  user_id uuid not null references auth.users (id) on delete cascade,
  name text not null default 'Goal',
  goal_type text not null default 'other',
  target_amount double precision not null default 0,
  target_date date not null default (current_date),
  current_amount double precision not null default 0,
  priority integer not null default 5,
  is_ring_fenced boolean not null default false,
  recommended_instrument text not null default '',
  notes text not null default ''
);
create index if not exists goals_user_id_idx on public.goals (user_id);

create table if not exists public.score_history (
  id bigserial primary key,
  user_id uuid not null references auth.users (id) on delete cascade,
  date date not null,
  score integer not null,
  tier text not null,
  unique (user_id, date)
);
create index if not exists score_history_user_id_idx on public.score_history (user_id);

create table if not exists public.ai_tool_calls (
  id bigserial primary key,
  user_id uuid not null,
  tool_name text not null,
  arguments jsonb,
  result text,
  created_at timestamptz
);
create index if not exists ai_tool_calls_user_id_idx on public.ai_tool_calls (user_id);

create table if not exists public.mf_nav_cache (
  scheme_code text primary key,
  nav double precision not null,
  nav_date text not null default '',
  fetched_at timestamptz
);

create table if not exists public.fx_rates (
  currency_pair text primary key,
  rate double precision not null,
  fetched_at timestamptz
);

-- OCR pipeline (confirm_and_save)
create table if not exists public.transactions (
  id bigserial primary key,
  user_id uuid not null references auth.users (id) on delete cascade,
  merchant text not null,
  amount double precision not null,
  date date not null,
  currency text not null default 'INR',
  category text not null default 'other',
  source text not null default 'ocr',
  created_at timestamptz default now()
);
create index if not exists transactions_user_id_idx on public.transactions (user_id);

-- Grants (adjust if you use strict RLS)
grant usage on schema public to postgres, anon, authenticated, service_role;

grant select, insert, update, delete on all tables in schema public to authenticated, service_role;
grant select, insert, update, delete on all tables in schema public to anon;

grant usage, select on all sequences in schema public to authenticated, service_role;
grant usage, select on all sequences in schema public to anon;
