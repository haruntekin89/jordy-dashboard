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
| 3 | `status` is niet `finished` (dus `new` of `in-progress`) | blokkeren | nee |
| 4 | Laatste contact binnen de gekozen periode | blokkeren | **ja** |
| 5 | Geen van bovenstaande | importeren | — |

Bij keuze "hele database" vervalt regel 4 en blokkeert elk nummer dat al in `leads`
voorkomt. Dat is exact het huidige gedrag.

Een nummer kan meerdere rijen in `leads` hebben (bijvoorbeeld een outbound- en een
inbound-rij). Blokkeren gebeurt zodra **één** rij een blokkeerregel raakt.

### Waarom deze keuzes

**"Laatste contact" = de laatste van `first_attempt` en `ended_at`**, niet alleen
`first_attempt`. Gemeten op de productiedatabase (29-07): 34.896 rijen hebben géén
`first_attempt` terwijl `status` wel `finished` is. Dat zijn **inkomende** gesprekken —
mensen die ons terugbelden (`ended_reason = 'inbound-ended-call'`, batch `oude_import`).
Wie ons vorige maand nog belde, moet niet als "nooit contact gehad" gelden. Rijen die
béide velden missen bestaan niet: gemeten 0.

`created_at` (importdatum) is bewust géén onderdeel van "laatste contact". De vraag is
"hebben we dit nummer recent gesproken?", niet "wanneer kwam het binnen?".

**Regel 3 kijkt naar `status != 'finished'`**, niet alleen naar `new`. De echte
statuswaarden zijn `finished` (751.515), `new` (21.852) en `in-progress` (7.211). Die
laatste groep is aan de lijn of blijven hangen; hoe dan ook nog niet afgerond, dus niet
opnieuw importeren. Door op "niet finished" te toetsen valt een toekomstige nieuwe status
automatisch aan de veilige kant.

**Standaard blijft "hele database"**, zodat een import zonder nadenken hetzelfde doet als
vandaag.

## Toevoegen of hergebruiken

**Ontdekt tijdens de eindreview (29-07), na het bouwen van taken 1-4.** In `leads` mag
elk telefoonnummer maar **één uitgaande rij** hebben: er ligt een unieke index op `phone`
die alleen voor `direction = 'outbound'` geldt.

Gemeten bewijs:
- 60.000 gescande rijen → 60.000 unieke nummers, nul dubbele
- 142 van 150 gecontroleerde inkomende nummers bestaan óók als uitgaande rij — inkomend
  mág dus wel dubbelen
- `dashboard.py` documenteert de partiële constraint al in een eerdere fix
  ("upsert(on_conflict='phone') werkt niet meer sinds de phone-constraint partieel is")

Dat raakt de kern van deze functie: een nummer dat door regel 4 heen komt, is per
definitie een nummer dát al een uitgaande rij heeft. Een tweede rij toevoegen botst met
de index. Omdat er per 1000 tegelijk wordt weggeschreven, laat één botsing de hele groep
van 1000 mislukken — inclusief de echt nieuwe leads die daar toevallig in zaten.

**Daarom: hergebruiken in plaats van toevoegen.** Nadat `beoordeel_nummer` `"nieuw"`
zegt, splitst de import:

| situatie | actie |
|---|---|
| nummer heeft al een uitgaande rij | die rij **bijwerken**: terug op `status='new'`, `result` leeg, nieuwe `batch_id`, naam en `original_data` uit het nieuwe bestand |
| nummer heeft alleen een inkomende rij, of staat er niet | **nieuwe rij toevoegen** |

Bijwerken gebeurt met `upsert(..., on_conflict='id')` op de primaire sleutel, in groepen
van 1000. Zo blijft het één verzoek per 1000 rijen én kan elke rij toch zijn eigen naam en
`original_data` krijgen. `on_conflict='phone'` kan hier niet: die constraint is partieel
en geeft Error 42P10.

`reset_count` wordt bewust **niet** aangeraakt en **niet** gecontroleerd. Die teller hoort
bij de automatische reset-knop (max 3 rondes per nummer). Een import is een expliciete
handmatige keuze met een expliciete periode; die twee mechanismen door elkaar halen maakt
allebei onduidelijk. Gevolg om te weten: door opnieuw te importeren kun je de
3-pogingen-grens omzeilen.

De belgeschiedenis (`first_attempt`, `ended_at`, `ended_reason`, `sip_status`) blijft
staan. Dat is ook nodig: een vólgende import moet nog kunnen zien wanneer het laatste
contact was. `motor.py` overschrijft `first_attempt` zelf zodra er weer gebeld wordt.

### Gevolg: batchcijfers schuiven (bewust geaccepteerd, besluit Harun 29-07)

Een hergebruikte lead krijgt de **nieuwe** `batch_id`. Doorslaggevende reden: batches zijn
per stuk aan/uit te zetten. Blijft een lead in zijn oude batch en staat die UIT, dan wordt
hij nooit gebeld — dan importeer je 20.000 nummers en gebeurt er niets. Ook toont de
wachtrij van de nieuwe batch nu hetzelfde aantal als het bestand, wat is wat je verwacht.

Wat je daarvoor inlevert:
- **Oude batchrapporten veranderen met terugwerkende kracht.** `batch_meekijk` groepeert op
  de huidige `batch_id`, dus verhuizen er rijen, dan krimpen de cijfers van de oude batch
  over een al gerapporteerde periode, en lijkt de nieuwe batch gebeld te hebben vóórdat hij
  bestond.
- **Een verse batch erft all-time tellers.** `herbelbaar`, `dood_count` en `laatste_poging`
  zijn niet op de periode begrensd, dus een nieuwe batch begint met tellingen uit gesprekken
  die er nooit in gevoerd zijn. De reset-knop kan daardoor een reset voorstellen op een
  batch die nog nooit gebeld is.
- **Niet aan de hand:** de automatische batch-pauze kijkt naar de laatste 14 dagen en de
  `first_attempt` van een hergebruikte lead ligt per definitie vóór de gekozen periode, dus
  een nieuwe batch wordt hier niet per ongeluk op gewicht 0,0 gezet.

### Voorwaarde die vóór gebruik gecontroleerd moet zijn

Het bijwerken stuurt een expliciete `id` mee. Dat mag alleen als `leads.id` **niet**
`GENERATED ALWAYS AS IDENTITY` is; anders weigert Postgres elke rij (SQLSTATE 428C9) en
mislukt élk hergebruik, terwijl nieuwe nummers wél binnenkomen — het lijkt dan half te
werken. Controleren met:

```sql
select is_identity, identity_generation, column_default
from information_schema.columns
where table_name = 'leads' and column_name = 'id';
```

Veilig bij `identity_generation = 'BY DEFAULT'` of leeg met een `nextval`-default.

## Interface

Een `st.radio` boven de importknop, alleen zichtbaar bij "Leads voor Dialer":

```
Ontdubbelen tegen:
  (•) Hele database          ← standaard
  ( ) Laatste 1 maand
  ( ) Laatste 2 maanden
  ( ) Laatste 3 maanden
  ( ) Laatste 6 maanden
  ( ) Laatste 12 maanden

  ℹ️ Blacklist, sales en nummers die nog in de wachtrij staan
     worden altijd geblokkeerd, ongeacht de periode.
```

De opties 1 en 2 maanden zijn er op 29-07 bijgekomen. Reden: de oudste belpoging in
`leads` is 2026-06-02, dus 3/6/12 maanden selecteerden op dat moment **nul** leads en
gedroegen zich alle drie als "Hele database". Met 1 maand vallen er 223.099 afgeronde
outbound-leads binnen bereik. Naarmate de data ouder wordt, worden de langere periodes
vanzelf zinvol.

## Techniek

### Nieuwe functie: opzoeken mét beoordelingsvelden

`existing_phones(table, phones)` (dashboard.py:204) haalt alleen de kolom `phone` op. Die
blijft ongewijzigd voor de blacklist.

Voor leads komt er een aparte functie die dezelfde chunk-aanpak gebruikt (200 nummers per
`IN`-query) maar `phone, status, result, first_attempt, ended_at` ophaalt, en de rijen per
nummer samenvat tot één oordeel:

```python
def bestaande_lead_info(phones, chunk_size=200):
    """phone -> {'sale': bool, 'open': bool, 'laatste_contact': datetime|None}

    Samengevat over ALLE rijen van dat nummer:
      sale            = ergens result == 'SUCCES'
      open            = ergens status != 'finished'
      laatste_contact = hoogste van alle first_attempt- en ended_at-waarden,
                        als naïeve UTC-datetime
    """
```

De beslissing valt daarna in Python. Het **aantal database-queries blijft gelijk** aan nu;
er komen alleen kolommen bij.

### Datums gelijktrekken

De twee datumkolommen hebben een **verschillend formaat**:

| kolom | voorbeeld | soort |
|---|---|---|
| `first_attempt` | `2026-06-10T10:44:13.462284` | tekst, naïef UTC |
| `ended_at` | `2026-06-08T08:24:34.702106+00:00` | timestamptz, mét tijdzone |

Ze worden daarom niet als tekst vergeleken maar omgezet naar naïeve UTC-datetimes:

```python
def naar_naief_utc(waarde):
    """ISO-tekst (met of zonder tijdzone) -> naïeve UTC-datetime, of None."""
    if not waarde:
        return None
    d = datetime.fromisoformat(waarde)
    if d.tzinfo is not None:
        d = d.astimezone(timezone.utc).replace(tzinfo=None)
    return d
```

Dit gebeurt per nummer in Python, niet in SQL, dus het kost geen extra queries. Tekst
vergelijken zoals in `sql/meekijk_rpc.sql` mag hier juist **niet**: dat werkt alleen bij
één vast formaat, en hier zijn het er twee.

### Periodegrens

```python
from dateutil.relativedelta import relativedelta   # python-dateutil==2.9.0.post0, al gepind

def periode_grens(maanden, nu=None):
    """Ondergrens als naïeve UTC-datetime; None betekent 'hele database'."""
    if maanden is None:
        return None
    nu = nu or datetime.now(timezone.utc).replace(tzinfo=None)
    return nu - relativedelta(months=maanden)
```

`datetime.now(timezone.utc).replace(tzinfo=None)` en niet `datetime.utcnow()`: die laatste
is verouderd en geeft een waarschuwing. De parameter `nu` bestaat zodat de test een vast
tijdstip kan meegeven.

### Uitslag

`st.session_state["import_resultaat"]` krijgt losse tellers in plaats van één `dubbel`:

| veld | betekenis |
|---|---|
| `toegevoegd` | als nieuwe rij toegevoegd |
| `heractief` | bestaande rij hergebruikt (weer belbaar gemaakt) |
| `recent_contact` | geblokkeerd door regel 4 |
| `sale` | geblokkeerd door regel 2 |
| `blacklist` | geblokkeerd door regel 1 |
| `nog_open` | geblokkeerd door regel 3 (in wachtrij of in gesprek) |
| `ongeldig` | nummer kon niet genormaliseerd worden |
| `mislukt` | insert gaf een fout |

De bestaande pop-up (zie geheugen `import_resultaat_popup`) toont deze uitsplitsing, zodat
zichtbaar is of een ruimere periode zou helpen.

Bij "hele database" komt alles wat vroeger `dubbel` heette terecht in `recent_contact`;
dat label klopt dan nog steeds, want de periode is dan oneindig.

## Testen

`test_dialer_brein.py` test pure functies zonder database. Dezelfde aanpak hier: de
beslislogica komt in een nieuw bestand `import_logica.py` met testbestand
`test_import_logica.py`, zodat er geen Supabase aan te pas komt.

Kern is één pure functie:

```python
beoordeel_nummer(info, op_blacklist, grens)
  -> "nieuw" | "blacklist" | "sale" | "nog_open" | "recent_contact"
```

Testgevallen:
- blacklist wint van alles (ook van sale, ook van buiten de periode)
- sale blokkeert ook als het contact vér buiten de periode ligt
- `open=True` blokkeert ook als er helemaal geen contactdatum is
- contact precies óp de grens → blokkeren (grens is inclusief)
- contact één seconde vóór de grens → nieuw
- `grens=None` (hele database) → elk bestaand nummer blokkeert
- onbekend nummer (`info=None`) → nieuw, ook bij `grens=None`

En voor de twee hulpfuncties:
- `naar_naief_utc` op tekst mét tijdzone (`...+00:00`) en zónder → zelfde uitkomst
- `naar_naief_utc(None)` en `naar_naief_utc("")` → `None`
- `periode_grens(None)` → `None`; `periode_grens(3, nu=vast)` → precies 3 maanden terug

## Buiten scope

De import wordt hier **niet sneller**. Een bestand van 50.000 nummers doet nu al ~500
database-rondjes (250 voor leads, 250 voor blacklist) en dat blijft zo. Sneller maken is
een aparte klus.

De blacklist-import verandert niet.
