# Import: kiesbare ontdubbel-periode

**Datum:** 2026-07-29
**Status:** ontwerp goedgekeurd

## Probleem

De lead-import ontdubbelt altijd tegen de héle `leads`-tabel. Die telt inmiddels ~780.000
rijen, waarvan het overgrote deel maanden oud is. Een nummer dat een half jaar geleden
één keer niet opnam, blokkeert daardoor voor altijd een nieuwe import — terwijl zo'n
nummer prima opnieuw gebeld mag worden.

Tegelijk zijn er nummers die juist *nooit* opnieuw gebeld mogen worden, ongeacht hoe lang
geleden: de blacklist en nummers waar al een sale uit is gekomen.

## Wat we bouwen

Bij het importeren van leads kiest Harun waartegen ontdubbeld wordt: de hele database, of
alleen de laatste 3, 6 of 12 maanden. Blacklist, sales en nummers die nog in de wachtrij
staan blokkeren altijd, los van die keuze.

Alleen het importscherm voor **"📞 Leads voor Dialer"** verandert. De blacklist-import
blijft ongemoeid.

## Beslisregels

Per genormaliseerd nummer geldt de eerste regel die raak is:

| # | Regel | Gevolg | Hangt af van periodekeuze? |
|---|---|---|---|
| 1 | Staat op de blacklist | blokkeren | nee |
| 2 | Heeft ooit `result = 'SUCCES'` (sale) | blokkeren | nee |
| 3 | Staat nog op `status = 'new'` (nog te bellen) | blokkeren | nee |
| 4 | Laatste belpoging binnen de gekozen periode | blokkeren | **ja** |
| 5 | Geen van bovenstaande | importeren | — |

Bij keuze "hele database" vervalt regel 4 en blokkeert elk nummer dat al in `leads`
voorkomt. Dat is exact het huidige gedrag.

Een nummer kan meerdere rijen in `leads` hebben (bijvoorbeeld een outbound- en een
inbound-rij). Blokkeren gebeurt zodra **één** rij een blokkeerregel raakt.

### Waarom deze keuzes

- **Periode wordt gemeten op `first_attempt`** (laatste belpoging), niet op `created_at`
  (importdatum). De vraag is "hebben we dit nummer recent nog gebeld?", niet "wanneer
  kwam het binnen?". Rijen zonder `first_attempt` zijn nooit gebeld en vallen al onder
  regel 3.
- **Regel 3 bestaat** omdat een nummer anders twee keer in de wachtrij kan komen: de
  bestaande rij is nog niet gebeld, dus regel 4 zou 'm doorlaten.
- **Standaard blijft "hele database"**, zodat een import zonder nadenken hetzelfde doet
  als vandaag.

## Interface

Een `st.radio` boven de importknop, alleen zichtbaar bij "Leads voor Dialer":

```
Ontdubbelen tegen:
  (•) Hele database          ← standaard
  ( ) Laatste 3 maanden
  ( ) Laatste 6 maanden
  ( ) Laatste 12 maanden

  ℹ️ Blacklist, sales en nummers die nog in de wachtrij staan
     worden altijd geblokkeerd, ongeacht de periode.
```

## Techniek

### Nieuwe functie: opzoeken mét beoordelingsvelden

`existing_phones(table, phones)` (dashboard.py:204) haalt alleen de kolom `phone` op. Die
blijft ongewijzigd voor de blacklist.

Voor leads komt er een aparte functie die dezelfde chunk-aanpak gebruikt (200 nummers per
`IN`-query) maar `phone, status, result, first_attempt` ophaalt, en per nummer een
samengevat oordeel teruggeeft:

```python
def bestaande_lead_info(phones, chunk_size=200):
    """phone -> {'sale': bool, 'in_wachtrij': bool, 'laatste_poging': str|None}

    laatste_poging = hoogste first_attempt over alle rijen van dat nummer, als tekst
    (naïef UTC). Tekstvergelijking is hier geldig: het formaat is vast — zie
    sql/meekijk_rpc.sql v3 en motor.py:362.
    """
```

De beslissing valt daarna in Python. Het **aantal database-queries blijft gelijk** aan nu;
er komen alleen kolommen bij.

### Periodegrens

De grens wordt één keer berekend als tekst in hetzelfde formaat als `first_attempt`:
**naïef UTC**, zonder tijdzone-achtervoegsel, want zo schrijft `motor.py` de kolom
(`datetime.now().isoformat()` op een server die op UTC staat).

```python
from dateutil.relativedelta import relativedelta   # python-dateutil==2.9.0.post0, al gepind

grens = None if maanden is None else (
    datetime.now(timezone.utc).replace(tzinfo=None) - relativedelta(months=maanden)
).isoformat()
```

`datetime.now(timezone.utc).replace(tzinfo=None)` en niet `datetime.utcnow()`: die laatste
is verouderd en geeft een waarschuwing.

`grens is None` betekent "hele database".

### Uitslag

`st.session_state["import_resultaat"]` krijgt losse tellers in plaats van één `dubbel`:

| veld | betekenis |
|---|---|
| `toegevoegd` | geïmporteerd |
| `recent_gebeld` | geblokkeerd door regel 4 |
| `sale` | geblokkeerd door regel 2 |
| `blacklist` | geblokkeerd door regel 1 |
| `in_wachtrij` | geblokkeerd door regel 3 |
| `ongeldig` | nummer kon niet genormaliseerd worden |
| `mislukt` | insert gaf een fout |

De bestaande pop-up (zie geheugen `import_resultaat_popup`) toont deze uitsplitsing, zodat
zichtbaar is of een ruimere periode zou helpen.

Bij "hele database" telt alles wat vroeger `dubbel` heette nu als `recent_gebeld`; dat
label blijft kloppen omdat de periode dan oneindig is.

## Testen

`test_dialer_brein.py` test nu pure functies zonder database. De beslislogica wordt
daarom als **pure functie** geschreven (`beoordeel_nummer(info, op_blacklist, grens)` →
`"nieuw" | "blacklist" | "sale" | "in_wachtrij" | "recent_gebeld"`), zodat die zonder
Supabase getest kan worden.

Testgevallen:
- blacklist wint van alles (ook van sale en van buiten de periode)
- sale blokkeert ook als de belpoging vér buiten de periode ligt
- `status='new'` blokkeert ook zonder `first_attempt`
- belpoging net binnen de grens → blokkeren; net erbuiten → nieuw
- `grens=None` (hele database) → elk bestaand nummer blokkeert
- nummer met meerdere rijen: één blokkerende rij is genoeg

## Buiten scope

De import wordt hier **niet sneller**. Een bestand van 50.000 nummers doet nu al ~500
database-rondjes (250 voor leads, 250 voor blacklist) en dat blijft zo. Sneller maken is
een aparte klus.

De blacklist-import verandert niet.
