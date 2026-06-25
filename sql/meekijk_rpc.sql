-- Meekijk-modus snelle data-helpers (READ-ONLY, stable).
-- Vervangen ~650 losse tel-queries door 2 RPC-aanroepen.
-- Plak dit hele blok in Supabase → SQL Editor → Run. Project: ckpoxeoqbmptbwjgypmb.
-- LET OP: first_attempt is een TEKST-kolom (naïef UTC) → cast via nullif(...,'')::timestamp
-- (veilig tegen NULL en lege strings), daarna omrekenen naar Europe/Amsterdam.

-- 1) Uur-profiel: per NL-dag/uur het aantal outbound-calls + successen.
create or replace function uur_profiel_agg(van timestamptz, tot timestamptz)
returns table(datum date, weekdag int, uur int, gebeld bigint, succes bigint)
language sql stable as $$
  select
    (nullif(first_attempt,'')::timestamp at time zone 'UTC' at time zone 'Europe/Amsterdam')::date as datum,
    (extract(isodow from (nullif(first_attempt,'')::timestamp at time zone 'UTC' at time zone 'Europe/Amsterdam'))::int - 1) as weekdag,  -- 0=ma .. 6=zo
    extract(hour from (nullif(first_attempt,'')::timestamp at time zone 'UTC' at time zone 'Europe/Amsterdam'))::int as uur,
    count(*)::bigint                                   as gebeld,
    count(*) filter (where result = 'SUCCES')::bigint  as succes
  from leads
  where direction = 'outbound'
    and nullif(first_attempt,'') is not null
    and (nullif(first_attempt,'')::timestamp at time zone 'UTC') >= van
    and (nullif(first_attempt,'')::timestamp at time zone 'UTC') <  tot
  group by 1, 2, 3
$$;

-- 2) Batch-meekijk: per batch alles wat het brein nodig heeft.
--    Windowed (van..tot) voor scoring; all-time voor reset-boekhouding.
create or replace function batch_meekijk(van timestamptz, tot timestamptz)
returns table(
  batch_id text, gebeld bigint, bereikt bigint, succes bigint, dood404 bigint,
  new_count bigint, laatste_poging timestamptz, herbelbaar bigint, dood_count bigint
)
language sql stable as $$
  select
    batch_id,
    count(*) filter (where direction='outbound' and (nullif(first_attempt,'')::timestamp at time zone 'UTC') >= van and (nullif(first_attempt,'')::timestamp at time zone 'UTC') < tot)::bigint as gebeld,
    count(*) filter (where direction='outbound' and (nullif(first_attempt,'')::timestamp at time zone 'UTC') >= van and (nullif(first_attempt,'')::timestamp at time zone 'UTC') < tot and ended_reason in ('klant-ended-call','assistant-ended-call'))::bigint as bereikt,
    count(*) filter (where direction='outbound' and (nullif(first_attempt,'')::timestamp at time zone 'UTC') >= van and (nullif(first_attempt,'')::timestamp at time zone 'UTC') < tot and result='SUCCES')::bigint as succes,
    count(*) filter (where direction='outbound' and (nullif(first_attempt,'')::timestamp at time zone 'UTC') >= van and (nullif(first_attempt,'')::timestamp at time zone 'UTC') < tot and sip_status='404')::bigint as dood404,
    count(*) filter (where status='new')::bigint as new_count,
    (max(nullif(first_attempt,'')::timestamp) filter (where direction='outbound') at time zone 'UTC') as laatste_poging,
    count(*) filter (where direction='outbound' and status<>'new'
                       and (ended_reason is null or ended_reason not in ('klant-ended-call','assistant-ended-call'))
                       and (sip_status is null or sip_status <> '404'))::bigint as herbelbaar,
    count(*) filter (where direction='outbound' and sip_status='404')::bigint as dood_count
  from leads
  where batch_id is not null
  group by batch_id
$$;

-- Snelle controle (mag je ook draaien):
-- select * from uur_profiel_agg(now() - interval '2 days', now()) order by uur;
-- select * from batch_meekijk(now() - interval '14 days', now()) limit 5;
