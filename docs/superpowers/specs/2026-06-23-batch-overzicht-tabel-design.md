# Batch-overzicht als één tabel — ontwerp

**Datum:** 2026-06-23
**Component:** `jordy-dashboard/dashboard.py` — sectie "📊 Batch Rapportage"
**Doel:** alle batches in één oogopslag zien (geen dropdown-per-batch meer), met
status aan/uit per regel en de rapportagecijfers ernaast.

## Probleem

Nu moet de gebruiker in de "Batch Rapportage"-expander eerst één batch uit een
dropdown kiezen voordat de cijfers verschijnen. Status aan/uit gaat via één losse
knop voor de gekozen batch. Harun wil **alles tegelijk** zien als lijst, kunnen
sorteren op actief/inactief, en de status per regel kunnen omzetten.

## Beslissingen (vastgelegd met de gebruiker)

1. **Eén tabel** met alle batches en alle kolommen (niet twee aparte lijsten).
2. **Periodekiezer boven de tabel** (Vandaag / 7 dagen / 30 dagen / Hele looptijd)
   die op alle regels tegelijk werkt.
3. **Conversie = Sales ÷ Afgehandeld** (als percentage).
4. Status-wijzigen, reset en verwijderen blijven gedrag dat al bestaat; alleen de
   presentatie verandert.

## Kolommen

| Kolom | Betekenis | Bron |
|---|---|---|
| **Batch** | batch_id | bestaand |
| **Status** | dropdown `Actief` / `Inactief`; wijzigen zet de batch direct aan/uit voor de dialer | `config.paused_batches` |
| **Totaal** | alle leads in de batch (niet periode-gebonden) | RPC `totaal` |
| **Afgehandeld** | aantal gebeld in de periode (rijen met `ended_at` in periode) | RPC (nieuw) |
| **Open** | nog te bellen (leads met `status = 'new'`, niet periode-gebonden) | RPC `te_bellen` |
| **Gebelde tijd** | som van `duration` in de periode, getoond als `Xu YYm` | RPC (nieuw) |
| **Sales** | aantal `result = 'SUCCES'` in de periode | RPC (nieuw) |
| **Conversie** | `Sales / Afgehandeld` als % (0% als Afgehandeld = 0) | berekend in dashboard |

- **Sorteren op actief/inactief:** tabel staat standaard gesorteerd op Status
  (Actief eerst). De gebruiker kan op elke kolomkop klikken om anders te sorteren.
- Volgorde bij gelijke status: nieuwste batch boven, `oude_import` onderaan
  (zoals nu).

## Architectuur

### 1. Server-functie `batches_overzicht` uitbreiden (SQL — Harun draait dit zelf)

De bestaande Postgres-RPC `batches_overzicht()` retourneert nu per batch:
`batch_id`, `totaal`, `te_bellen`. Die wordt vervangen door een versie die
periode-parameters accepteert en de rapportagecijfers meelevert in één query:

```
batches_overzicht(van timestamptz, tot timestamptz)
  -> batch_id, totaal, te_bellen, afgehandeld, sales, gebelde_tijd_sec
```

- `totaal` = `count(*)` per batch (alle leads).
- `te_bellen` = `count(*) where status = 'new'` (huidige stand, niet periode-gebonden).
- `afgehandeld` = `count(*) where ended_at between van and tot`.
- `sales` = `count(*) where result = 'SUCCES' and ended_at between van and tot`.
- `gebelde_tijd_sec` = `coalesce(sum(duration),0) where ended_at between van and tot`.

Eén `GROUP BY batch_id` over de `leads`-tabel met geconditioneerde aggregaten
(`count(*) filter (where ...)`). Eén serverquery i.p.v. ~6 telvragen per batch.

**Deploy-volgorde (verplicht):** Harun draait eerst de nieuwe SQL-functie in
Supabase (zelfbouw-project `ckpoxeoqbmptbwjgypmb`). Pas daarna wordt de
dashboard-code gedeployed. Anders crasht het dashboard op een onbekende functie.

### 2. Dashboard: tabel renderen

- `cached_batches_overzicht(van_iso, tot_iso)` roept de RPC met periode-parameters
  aan (cache-key bevat de periode). `cached_batch_stats` (per-batch telvragen)
  vervalt.
- Periodekiezer boven de tabel bepaalt `van`/`tot` (hergebruik van de bestaande
  periode-logica: Vandaag = vandaag; 7/30 dagen = terugtellen; Hele looptijd =
  `date(2020,1,1)`..vandaag).
- Bouw een `pandas.DataFrame` met de kolommen hierboven. Status-kolom afgeleid van
  `paused_batches` (`Inactief` als batch in de lijst staat, anders `Actief`).
  Conversie en `Gebelde tijd` worden in Python berekend/geformatteerd.
- Render met `st.data_editor`:
  - `Status` = `st.column_config.SelectboxColumn(options=["Actief","Inactief"])`,
    bewerkbaar.
  - Alle overige kolommen `disabled=True` (alleen-lezen).
  - `hide_index=True`.

### 3. Status-wijziging verwerken

- Vergelijk de bewerkte DataFrame met de oorspronkelijke status per batch.
- Voor elke gewijzigde regel: `Inactief` → batch_id toevoegen aan `paused_batches`;
  `Actief` → batch_id eruit halen. Schrijf de hele lijst terug via
  `config.upsert({"key":"paused_batches", ...})`, dan `st.cache_data.clear()` +
  `st.rerun()`. Dit is exact het gedrag van de huidige AAN/UIT-knop, maar per regel.

### 4. Reset & Verwijderen (blijven onder de tabel)

`♻️ Reset Geen Gehoor` en `🗑️ Verwijder Batch` (met bevestig-checkbox) passen niet
in een tabelregel en zijn onomkeerbaar. Die blijven als klein blok **onder** de
tabel: eerst een batch kiezen (kleine selectbox), dan de actieknop. Logica
ongewijzigd t.o.v. nu.

## Wat vervalt

- De losse "kies één batch"-dropdown voor rapportage.
- De grote metric-tegels per gekozen batch.
- De losse AAN/UIT-knop (gaat op in de Status-dropdown per regel).

## Foutafhandeling

- RPC faalt → `st.error` met hint dat de nieuwe `batches_overzicht`-functie nog in
  Supabase gedraaid moet worden (zoals de bestaande melding).
- Geen batches → infomelding (zoals nu).
- `Afgehandeld = 0` → conversie toont `0%` (geen deling door nul).

## Testen / verifiëren

- Lokaal: dashboard start zonder fouten, tabel toont alle batches met juiste
  totalen; periodekiezer wisselt de cijfers; Status-dropdown zet een batch in/uit
  `paused_batches`; reset/verwijderen werken onder de tabel.
- Vergelijk een paar batchcijfers met de oude per-batch rapportage om de
  RPC-aggregatie te valideren.
- Tijden in `ended_at`/`duration` zijn UTC in de DB; periodegrenzen consistent
  toepassen zoals de bestaande code (`00:00:00`..`23:59:59`).

## Buiten scope (YAGNI)

- Geen export-knop voor de tabel.
- Geen extra kolommen (geen gehoor / foutief / mislukt) — alleen de afgesproken set.
- Geen wijziging aan dialer, motor of agent.
