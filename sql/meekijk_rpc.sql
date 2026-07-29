-- Meekijk-modus snelle data-helpers (READ-ONLY, stable).
-- Plak dit hele blok in Supabase → SQL Editor → Run. Project: ckpoxeoqbmptbwjgypmb.
--
-- VERSIE 3 (29-07-2026) — de echte fix. Gemeten oorzaak van de trage meekijk-modus:
--
--   first_attempt is een TEKST-kolom. Elke tel-filter die op het tijdvenster let, deed
--   z'n eigen tekst→timestamp-omzetting over alle ~780k rijen. Gemeten kosten per
--   kolom (via de API):
--     geen tellingen ............................. 0,48s
--     3 tellingen ZONDER datum ................... 0,73s   (~0,08s per telling)
--     1 telling MET datum ........................ 1,93s   (+1,45s !)
--     4 tellingen MET datum ...................... 5,56s   (lineair: ~1,3s per stuk)
--     alles ...................................... 6,75s   → over de 8s-timeout
--
--   Versie 2 probeerde dit met een CTE op te lossen (cast 1x per rij). Dat werkte NIET:
--   Postgres vouwt zo'n CTE weer uit, waarna de omzetting alsnog per filter gebeurt.
--
-- OPLOSSING: helemaal niet meer omzetten. first_attempt heeft altijd exact hetzelfde
-- formaat ('2026-06-10T10:44:13.462284', 26 tekens, naïef UTC — geschreven door
-- motor.py met datetime.now().isoformat()). Bij dat vaste formaat is tekst-vergelijken
-- identiek aan datum-vergelijken. De venstergrenzen worden één keer naar diezelfde
-- tekstvorm gezet en daarna vergelijkt Postgres alleen nog bytes. Dat is precies wat
-- motor.py zelf ook al doet (.gte("first_attempt", s_90)).
--
-- COLLATE "C" = vergelijk op byte-volgorde. Nodig omdat sommige taal-collaties
-- leestekens anders wegen; op dit vaste formaat is byte-volgorde exact chronologisch.
-- plpgsql (i.p.v. sql) zodat de grenzen gegarandeerd één keer worden uitgerekend en
-- als vaste waarde de query in gaan.
--
-- Randgeval: als de microseconden ooit exact 0 zijn laat Python ze weg (19 i.p.v. 26
-- tekens). Zo'n rij valt dan hooguit één seconde aan de verkeerde kant van een
-- vensterrand. Verwaarloosbaar voor deze statistieken, en niet voorgekomen in een
-- steekproef van 1600 rijen verspreid over de hele tabel.

-- 1) Uur-profiel: per NL-dag/uur het aantal outbound-calls + successen.
create or replace function uur_profiel_agg(van timestamptz, tot timestamptz)
returns table(datum date, weekdag int, uur int, gebeld bigint, succes bigint)
language plpgsql stable as $$
declare
  g_van text := to_char(van at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US');
  g_tot text := to_char(tot at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US');
begin
  return query
  with gefilterd as (
    -- Filteren op tekst = geen omzetting over de hele tabel. Alleen de rijen die
    -- overblijven (14 dagen belwerk) worden nog omgezet naar NL-tijd.
    select
      l.result as res,
      ((nullif(l.first_attempt,'')::timestamp at time zone 'UTC')
         at time zone 'Europe/Amsterdam') as nl
    from leads l
    where l.direction = 'outbound'
      and l.first_attempt collate "C" >= g_van
      and l.first_attempt collate "C" <  g_tot
  )
  select
    f.nl::date                                          as datum,
    (extract(isodow from f.nl)::int - 1)                as weekdag,  -- 0=ma .. 6=zo
    extract(hour from f.nl)::int                        as uur,
    count(*)::bigint                                    as gebeld,
    count(*) filter (where f.res = 'SUCCES')::bigint    as succes
  from gefilterd f
  group by 1, 2, 3;
end $$;

-- 2) Batch-meekijk: per batch alles wat het brein nodig heeft.
--    Windowed (van..tot) voor scoring; all-time voor reset-boekhouding.
create or replace function batch_meekijk(van timestamptz, tot timestamptz)
returns table(
  batch_id text, gebeld bigint, bereikt bigint, succes bigint, dood404 bigint,
  new_count bigint, laatste_poging timestamptz, herbelbaar bigint, dood_count bigint
)
language plpgsql stable as $$
declare
  g_van text := to_char(van at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US');
  g_tot text := to_char(tot at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US');
begin
  return query
  select
    l.batch_id,
    count(*) filter (where l.direction = 'outbound'
      and l.first_attempt collate "C" >= g_van
      and l.first_attempt collate "C" <  g_tot)::bigint                as gebeld,
    count(*) filter (where l.direction = 'outbound'
      and l.first_attempt collate "C" >= g_van
      and l.first_attempt collate "C" <  g_tot
      and l.ended_reason in ('klant-ended-call','assistant-ended-call'))::bigint as bereikt,
    count(*) filter (where l.direction = 'outbound'
      and l.first_attempt collate "C" >= g_van
      and l.first_attempt collate "C" <  g_tot
      and l.result = 'SUCCES')::bigint                                 as succes,
    count(*) filter (where l.direction = 'outbound'
      and l.first_attempt collate "C" >= g_van
      and l.first_attempt collate "C" <  g_tot
      and l.sip_status = '404')::bigint                                as dood404,
    count(*) filter (where l.status = 'new')::bigint                   as new_count,
    -- Grootste tekstwaarde pakken en pas DAARNA één keer omzetten.
    (nullif(max(l.first_attempt collate "C")
              filter (where l.direction = 'outbound'), '')::timestamp
       at time zone 'UTC')                                             as laatste_poging,
    -- Herbelbaar = precies wat reset_geen_gehoor() in dashboard.py terugzet:
    -- geen-gehoor-reden, nog geen 3 belpogingen (reset_count < 2; NULL telt niet mee,
    -- want die zet de resetknop ook niet terug) en geen dood nummer (404).
    count(*) filter (where l.ended_reason in ('customer-did-not-answer','no-answer-transfer',
                                              'voicemail','silence-timed-out','geen-mens')
                       and l.reset_count < 2
                       and (l.sip_status is null or l.sip_status <> '404'))::bigint as herbelbaar,
    count(*) filter (where l.direction = 'outbound'
                       and l.sip_status = '404')::bigint               as dood_count
  from leads l
  where l.batch_id is not null
  group by l.batch_id;
end $$;

-- Meet-functies van het onderzoek opruimen (mogen weg, waren tijdelijk).
drop function if exists _diag_meekijk();
drop function if exists _diag_plan();
drop function if exists _bm_plpgsql(timestamptz, timestamptz);
drop function if exists _bm_vast();
