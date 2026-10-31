-- Questionnaire answers per client, and labelled portfolio versions.
--
-- Only the answers are stored; the score is recomputed by the engine whenever it is
-- read, so a change to the scoring method (questionnaire.METHOD_VERSION) never leaves
-- stale scores behind. Edited holdings are saved as a new portfolio row (source
-- 'editor'), never by overwriting an uploaded file, so every past analysis still points
-- at the exact holdings it used.

alter table public.clients
    add column questionnaire jsonb,
    add column questionnaire_updated_at timestamptz;

alter table public.portfolios
    add column label text not null default '',
    add column source text not null default 'upload' check (source in ('upload', 'editor'));

-- clients already allow UPDATE for the caller's firm (policy firm_rows); no grant change.
