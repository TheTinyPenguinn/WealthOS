-- WealthOS: row-level security for the tables created in 001.
-- Run AFTER 001_wealthos_phase_tables.sql, in Supabase Dashboard → SQL → New query.
--
-- Mirrors the policy pattern already used on the v1 tables (expenses, accounts,
-- obligations, user_settings, investments): a user can only read and write their
-- own rows. Safe to re-run — every policy is dropped by name and recreated, so
-- this never touches policies belonging to other tables.

-- Per-user tables: owner-only access -----------------------------------------
do $$
declare
  t text;
begin
  foreach t in array array[
    'user_profile', 'illiquid_assets', 'credit_cards', 'tax_investments',
    'capital_gains', 'insurance_policies', 'emergency_fund', 'goals',
    'score_history', 'ai_tool_calls', 'transactions'
  ] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('drop policy if exists %I on public.%I', t || '_owner_all', t);
    execute format(
      'create policy %I on public.%I for all to authenticated '
      'using (user_id = auth.uid()) with check (user_id = auth.uid())',
      t || '_owner_all', t
    );
  end loop;
end $$;

-- Shared caches: no user_id, readable and writable by any signed-in user ------
-- These hold public market data (mutual-fund NAVs, FX rates), not user data.
do $$
declare
  t text;
begin
  foreach t in array array['mf_nav_cache', 'fx_rates'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('drop policy if exists %I on public.%I', t || '_authenticated_all', t);
    execute format(
      'create policy %I on public.%I for all to authenticated '
      'using (true) with check (true)',
      t || '_authenticated_all', t
    );
  end loop;
end $$;

-- Verify (optional): every table below should show rls_on = true
-- select tablename, rowsecurity as rls_on from pg_tables
-- where schemaname = 'public' order by tablename;

-- --------------------------------------------------------------------------
-- Rollback (run manually if this needs to be reverted):
--
-- do $$ declare t text; begin
--   foreach t in array array['user_profile','illiquid_assets','credit_cards',
--     'tax_investments','capital_gains','insurance_policies','emergency_fund',
--     'goals','score_history','ai_tool_calls','transactions','mf_nav_cache','fx_rates']
--   loop
--     execute format('alter table public.%I disable row level security', t);
--   end loop;
-- end $$;
-- --------------------------------------------------------------------------
