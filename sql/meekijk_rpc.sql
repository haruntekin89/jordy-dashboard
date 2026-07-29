-- Meekijk-modus snelle data-helpers (READ-ONLY, stable).
-- Plak dit hele blok in Supabase → SQL Editor → Run. Project: ckpoxeoqbmptbwjgypmb.
--
-- LET OP: first_attempt is een TEKST-kolom (naïef UTC) → cast via nullif(...,'')::timestamp
-- (veilig tegen NULL en lege strings), daarna omrekenen naar Europe/Amsterdam.
--
-- VERSIE 2 (29-07-2026) — waarom herschreven:
--   1) SNELHEID. De leads-tabel is naar ~780k rijen gegroeid. De oude versie deed de
--      dure tekst→timestamp-cast van first_attempt 8x PER RIJ (één keer in elke
--      count-filter). Dat zijn ~6 miljoen casts per aanroep en dat kroop over de
--      Postgres statement-timeout van 8s heen → de RPC faalde. Nu wordt de cast ÉÉN
--      keer per rij gedaan in een CTE, en de venstergrenzen worden één keer vooraf
--      omgerekend i.p.v. per rij.
--   2) JUISTE 'herbelbaar'. De oude definitie (alles wat niet-bereikt is) week af van
--      wat de resetknop echt terugzet, dus telde het dashboard het zelf opnieuw met
--      één query PER BATCH (~78 extra queries per paginalading). Deze versie spiegelt
--      reset_geen_gehoor() in dashboard.py exact, zodat die lus weg kan.

-- 1) Uur-profiel: per NL-dag/uur het aantal outbound-calls + successen.
create or replace function uur_profiel_agg(van timestamptz, tot timestamptz)
returns table(datum date, weekdag int, uur int, gebeld bigint, succes bigint)
language sql stable as $$
  with basis as (
    -- Cast eenmalig per rij; nl = hetzelfde moment in Europe/Amsterdam.
    select
      l.result,
      ((nullif(l.first_attempt,'')::timestamp at time zone 'UTC') at time zone 'Europe/Amsterdam') as nl
    from leads l
    where l.direction = 'outbound'
      and nullif(l.first_attempt,'') is not null
      -- Venstergrenzen als naïef-UTC constanten: geen per-rij tijdzone-omrekening
      -- meer nodig om te filteren.
      and nullif(l.first_attempt,'')::timestamp >= (van at time zone 'UTC')
      and nullif(l.first_attempt,'')::timestamp <  (tot at time zone 'UTC')
  )
  select
    nl::date                                          as datum,
    (extract(isodow from nl)::int - 1)                as weekdag,  -- 0=ma .. 6=zo
    extract(hour from nl)::int                        as uur,
    count(*)::bigint                                  as gebeld,
    count(*) filter (where result = 'SUCCES')::bigint as succes
  from basis
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
  with basis as (
    select
      l.batch_id      as bid,
      l.direction     as dir,
      l.status        as st,
      l.result        as res,
      l.ended_reason  as reden,
      l.sip_status    as sip,
      l.reset_count   as rc,
      nullif(l.first_attempt,'')::timestamp as fa   -- ÉÉN cast per rij (naïef UTC)
    from leads l
    where l.batch_id is not null
  ),
  gemarkeerd as (
    select b.*,
      (b.dir = 'outbound' and b.fa is not null
        and b.fa >= (van at time zone 'UTC')
        and b.fa <  (tot at time zone 'UTC')) as in_venster
    from basis b
  )
  select
    bid                                                                    as batch_id,
    count(*) filter (where in_venster)::bigint                             as gebeld,
    count(*) filter (where in_venster
      and reden in ('klant-ended-call','assistant-ended-call'))::bigint    as bereikt,
    count(*) filter (where in_venster and res = 'SUCCES')::bigint          as succes,
    count(*) filter (where in_venster and sip = '404')::bigint             as dood404,
    count(*) filter (where st = 'new')::bigint                             as new_count,
    (max(fa) filter (where dir = 'outbound') at time zone 'UTC')           as laatste_poging,
    -- Herbelbaar = precies wat reset_geen_gehoor() in dashboard.py terugzet:
    -- geen-gehoor-reden, nog geen 3 belpogingen (reset_count < 2; NULL telt niet mee,
    -- want die zet de resetknop ook niet terug) en geen dood nummer (404).
    count(*) filter (where reden in ('customer-did-not-answer','no-answer-transfer',
                                     'voicemail','silence-timed-out','geen-mens')
                       and rc < 2
                       and (sip is null or sip <> '404'))::bigint          as herbelbaar,
    count(*) filter (where dir = 'outbound' and sip = '404')::bigint       as dood_count
  from gemarkeerd
  group by bid
$$;

-- Snelle controle (mag je ook draaien) — kijk vooral naar de looptijd onderaan:
-- select * from uur_profiel_agg(now() - interval '14 days', now()) order by uur;
-- select * from batch_meekijk(now() - interval '14 days', now()) limit 5;
