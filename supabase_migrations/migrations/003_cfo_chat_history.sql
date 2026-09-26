-- WealthOS: persist the CFO chat.
-- Run in Supabase Dashboard → SQL → New query → paste → Run.
--
-- The chat previously lived only in st.session_state, so every reload lost the
-- conversation — and a reload also signs the user out. That made it impossible
-- to go back and check whether the figures the agent quoted were correct.
-- Individual tool calls are already recorded in ai_tool_calls; this stores the
-- conversation around them.

create table if not exists public.cfo_chat_messages (
  id bigserial primary key,
  user_id uuid not null references auth.users (id) on delete cascade,
  role text not null check (role in ('user', 'assistant')),
  content text not null default '',
  tool_events jsonb,
  created_at timestamptz not null default now()
);

create index if not exists cfo_chat_messages_user_created_idx
  on public.cfo_chat_messages (user_id, created_at);

grant select, insert, update, delete on public.cfo_chat_messages to authenticated, service_role;
grant usage, select on sequence public.cfo_chat_messages_id_seq to authenticated, service_role;

-- Same owner-only rule as every other user table (see 002).
alter table public.cfo_chat_messages enable row level security;
drop policy if exists "cfo_chat_messages_owner_all" on public.cfo_chat_messages;
create policy "cfo_chat_messages_owner_all"
  on public.cfo_chat_messages
  for all
  to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

-- --------------------------------------------------------------------------
-- Rollback (run manually if this needs to be reverted):
--
-- drop table if exists public.cfo_chat_messages;
-- --------------------------------------------------------------------------
