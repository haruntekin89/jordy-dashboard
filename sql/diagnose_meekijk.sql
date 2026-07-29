-- TIJDELIJKE MEET-FUNCTIE (29-07-2026), ronde 3. Verandert NIETS aan je data.
-- Doel: het echte queryplan zien. Postgres vertelt dan zelf waar de seconden heen gaan.
-- Plak in Supabase → SQL Editor → Run. Daarna leest Claude het uit vanaf de server.
-- Opruimen kan later met:
--   drop function if exists _diag_meekijk();
--   drop function if exists _diag_plan();
--   drop function if exists _bm_plpgsql(timestamptz, timestamptz);
--   drop function if exists _bm_vast();

create or replace function _diag_plan()
returns table(variant text, regel text)
language plpgsql
as $$
declare
  r record;
  van timestamptz := now() - interval '14 days';
  tot timestamptz := now();
begin
  perform set_config('statement_timeout', '180s', true);

  -- (a) Zoals de API hem aanroept: alle kolommen ophalen.
  variant := 'a. select * from batch_meekijk(van, tot)';
  for r in execute
    'explain (analyze, buffers, verbose, costs off, timing off) '
    || 'select * from batch_meekijk($1, $2)' using van, tot
  loop
    regel := r."QUERY PLAN"; return next;
  end loop;

  -- (b) Zoals ik hem in ronde 1 mat (alleen tellen). Als deze een heel ander plan
  --     heeft, dan was die 0,41s een meetfout van mij en klopt (a) wel.
  variant := 'b. select count(*) from batch_meekijk(van, tot)';
  for r in execute
    'explain (analyze, buffers, verbose, costs off, timing off) '
    || 'select count(*) from batch_meekijk($1, $2)' using van, tot
  loop
    regel := r."QUERY PLAN"; return next;
  end loop;

  -- (c) Ter vergelijking de functie die WEL acceptabel is via de API.
  variant := 'c. select * from uur_profiel_agg(van, tot)';
  for r in execute
    'explain (analyze, buffers, verbose, costs off, timing off) '
    || 'select * from uur_profiel_agg($1, $2)' using van, tot
  loop
    regel := r."QUERY PLAN"; return next;
  end loop;

  return;
end $$;
