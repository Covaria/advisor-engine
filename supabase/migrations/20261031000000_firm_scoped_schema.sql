-- Firm-scoped schema for the advisor engine API.
--
-- The API connects as a privileged role but runs every request as `authenticated`
-- with the caller's JWT claims (see SupabaseStore), so row-level security below is
-- enforced on the API's own queries, not just on direct client access. Each policy
-- keys on app.current_firm_id(): an adviser sees and writes only their firm's rows.
--
-- Rules kept here rather than in Python:
-- - audit_events is append-only: no UPDATE or DELETE for anyone but the owner role.
-- - Advisers cannot change their own firm, role or status (no UPDATE grant); onboarding
--   goes through app.ensure_adviser(), which creates a firm on first sign-in.
-- - Only `active` advisers resolve to a firm, so a later CRD check can park new
--   sign-ups as `pending` without touching any policy.

create schema if not exists app;

-- --- tables ---------------------------------------------------------------------------

create table public.firms (
    id          uuid primary key default gen_random_uuid(),
    name        text not null,
    created_at  timestamptz not null default now()
);

create table public.advisers (
    id          uuid primary key references auth.users (id) on delete cascade,
    email       text not null,
    firm_id     uuid not null references public.firms (id),
    role        text not null default 'owner' check (role in ('owner', 'member')),
    status      text not null default 'active' check (status in ('active', 'pending', 'suspended')),
    crd         text,
    created_at  timestamptz not null default now()
);
create index on public.advisers (firm_id);

create table public.clients (
    id          uuid primary key default gen_random_uuid(),
    firm_id     uuid not null references public.firms (id),
    name        text not null check (length(name) between 1 and 200),
    objective   text not null default '',
    tone        text not null default '',
    created_by  uuid not null references public.advisers (id),
    created_at  timestamptz not null default now()
);
create index on public.clients (firm_id);

create table public.portfolios (
    id            uuid primary key default gen_random_uuid(),
    firm_id       uuid not null references public.firms (id),
    client_id     uuid not null references public.clients (id),
    filename      text not null,
    sha256        text not null,
    storage_path  text not null,
    uploaded_by   uuid not null references public.advisers (id),
    created_at    timestamptz not null default now()
);
create index on public.portfolios (firm_id, client_id);

create table public.conversations (
    portfolio_id  uuid primary key references public.portfolios (id),
    firm_id       uuid not null references public.firms (id),
    history       jsonb not null default '[]',
    messages      jsonb not null default '[]',
    updated_at    timestamptz not null default now()
);

create table public.drafts (
    id             uuid primary key default gen_random_uuid(),
    firm_id        uuid not null references public.firms (id),
    portfolio_id   uuid not null references public.portfolios (id),
    created_by     uuid not null references public.advisers (id),
    original       text not null,
    tool_calls     jsonb not null,
    approved       boolean not null default false,
    approved_text  text,
    approved_by    uuid references public.advisers (id),
    approved_at    timestamptz,
    created_at     timestamptz not null default now()
);
create index on public.drafts (firm_id);

create table public.audit_events (
    id            bigint generated always as identity primary key,
    firm_id       uuid not null references public.firms (id),
    portfolio_id  uuid,
    event         text,
    recorded_at   timestamptz not null default now(),
    record        jsonb not null
);
create index on public.audit_events (firm_id, recorded_at);

create table public.usage (
    adviser_id  uuid not null references public.advisers (id) on delete cascade,
    day         date not null,
    turns       integer not null default 0,
    primary key (adviser_id, day)
);

-- --- helpers --------------------------------------------------------------------------

-- The caller's firm, or null if they have no active adviser row. SECURITY DEFINER so
-- policies can read advisers without granting broad SELECT on it.
create function app.current_firm_id() returns uuid
language sql stable security definer set search_path = '' as $$
    select firm_id from public.advisers where id = auth.uid() and status = 'active'
$$;

-- First sign-in: create a firm owned by the caller (open sign-up). Idempotent.
create function app.ensure_adviser() returns public.advisers
language plpgsql security definer set search_path = '' as $$
declare
    uid   uuid := auth.uid();
    email text := coalesce(auth.jwt() ->> 'email', '');
    row   public.advisers;
    fid   uuid;
begin
    if uid is null then
        raise exception 'not signed in';
    end if;
    select * into row from public.advisers where id = uid;
    if found then
        return row;
    end if;
    insert into public.firms (name)
        values (coalesce(nullif(split_part(email, '@', 2), ''), 'My firm'))
        returning id into fid;
    insert into public.advisers (id, email, firm_id)
        values (uid, email, fid)
        returning * into row;
    return row;
end
$$;

-- Count one assistant turn for the caller today (UTC); false once `max_turns` is reached.
create function app.bump_turns(max_turns integer) returns boolean
language plpgsql security definer set search_path = '' as $$
declare
    n integer;
begin
    if app.current_firm_id() is null then
        return false;
    end if;
    insert into public.usage (adviser_id, day, turns)
        values (auth.uid(), (now() at time zone 'utc')::date, 1)
        on conflict (adviser_id, day) do update set turns = public.usage.turns + 1
            where public.usage.turns < max_turns
        returning turns into n;
    return n is not null;
end
$$;

-- --- row-level security ---------------------------------------------------------------

alter table public.firms         enable row level security;
alter table public.advisers      enable row level security;
alter table public.clients       enable row level security;
alter table public.portfolios    enable row level security;
alter table public.conversations enable row level security;
alter table public.drafts        enable row level security;
alter table public.audit_events  enable row level security;
alter table public.usage         enable row level security;

create policy firm_read on public.firms for select to authenticated
    using (id = app.current_firm_id());

create policy same_firm_read on public.advisers for select to authenticated
    using (firm_id = app.current_firm_id());

create policy firm_rows on public.clients for all to authenticated
    using (firm_id = app.current_firm_id()) with check (firm_id = app.current_firm_id());
create policy firm_rows on public.portfolios for all to authenticated
    using (firm_id = app.current_firm_id()) with check (firm_id = app.current_firm_id());
create policy firm_rows on public.conversations for all to authenticated
    using (firm_id = app.current_firm_id()) with check (firm_id = app.current_firm_id());
create policy firm_rows on public.drafts for all to authenticated
    using (firm_id = app.current_firm_id()) with check (firm_id = app.current_firm_id());

create policy firm_read on public.audit_events for select to authenticated
    using (firm_id = app.current_firm_id());
create policy firm_append on public.audit_events for insert to authenticated
    with check (firm_id = app.current_firm_id());

create policy own_usage on public.usage for select to authenticated
    using (adviser_id = auth.uid());

-- --- grants ---------------------------------------------------------------------------
-- Supabase grants broad table rights to anon/authenticated by default; narrow them so
-- the policies above are not the only line, and so audit rows can never be edited.

revoke all on all tables in schema public from anon, authenticated;
grant usage on schema app to authenticated;
grant execute on function app.current_firm_id(), app.ensure_adviser(), app.bump_turns(integer)
    to authenticated;
revoke execute on function app.current_firm_id(), app.ensure_adviser(), app.bump_turns(integer)
    from public, anon;

grant select on public.firms, public.advisers, public.usage to authenticated;
grant select, insert, update on public.clients, public.portfolios, public.conversations,
    public.drafts to authenticated;
grant select, insert on public.audit_events to authenticated;

-- --- storage --------------------------------------------------------------------------
-- Private bucket for holdings CSVs, written and read only by the API with the secret
-- key (paths are <firm_id>/<portfolio_id>.csv). Skipped where Storage isn't installed.

do $$
begin
    if to_regclass('storage.buckets') is not null then
        insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
            values ('holdings', 'holdings', false, 2097152,
                    array['text/csv', 'application/vnd.ms-excel', 'text/plain'])
            on conflict (id) do nothing;
    end if;
end
$$;
