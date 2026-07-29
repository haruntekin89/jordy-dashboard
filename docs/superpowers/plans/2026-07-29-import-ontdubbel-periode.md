# Import: kiesbare ontdubbel-periode — Implementatieplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bij het importeren van leads kiezen waartegen ontdubbeld wordt — de hele database of de laatste 3/6/12 maanden — waarbij blacklist, sales en nog niet afgeronde nummers altijd blokkeren.

**Architecture:** De beslislogica komt in een nieuw, puur Python-bestand `import_logica.py` zonder Supabase-afhankelijkheid, met eigen tests. `dashboard.py` krijgt één nieuwe opzoekfunctie die per nummer de beoordelingsvelden uit `leads` haalt, en de importlus roept de pure functie aan. Het aantal database-queries blijft gelijk.

**Tech Stack:** Python 3, Streamlit, supabase-py, pytest, python-dateutil (`relativedelta`).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-29-import-ontdubbel-periode-design.md`
- Repo: `~/BotAgent/jordy-dashboard` (aparte repo, deployt via push naar `main` → Streamlit Cloud).
- **Niet** de server `5.79.88.41` aanraken; dit is dashboard-only.
- `requirements.txt` is volledig gepind (segfault-incident 13-07). **Geen** nieuwe dependency toevoegen — `python-dateutil==2.9.0.post0` staat er al.
- Alleen het importpad "📞 Leads voor Dialer" verandert. Het blacklist-importpad blijft ongemoeid.
- Standaardkeuze blijft "Hele database", zodat gedrag zonder actie identiek is aan vandaag.
- Statuswaarden in `leads`: `finished`, `new`, `in-progress`. "Nog open" = `status != 'finished'`.
- `first_attempt` is tekst zonder tijdzone; `ended_at` is timestamptz mét `+00:00`. Altijd omzetten naar naïeve UTC vóór vergelijken.
- Tests draaien met `python3 -m pytest -q` vanuit de repo-root.

---

### Task 1: Pure beslislogica in `import_logica.py`

**Files:**
- Create: `import_logica.py`
- Test: `test_import_logica.py`

**Interfaces:**
- Consumes: niets (puur Python + `dateutil`)
- Produces:
  - `PERIODE_KEUZES: dict[str, int | None]` — labels voor de radio, waarde = aantal maanden of `None`
  - `naar_naief_utc(waarde: str | None) -> datetime | None`
  - `periode_grens(maanden: int | None, nu: datetime | None = None) -> datetime | None`
  - `beoordeel_nummer(info: dict | None, op_blacklist: bool, grens: datetime | None) -> str`
    met uitkomst `"nieuw" | "blacklist" | "sale" | "nog_open" | "recent_contact"`
  - `info`-vorm: `{"sale": bool, "open": bool, "laatste_contact": datetime | None}`

- [ ] **Step 1: Write the failing test**

Maak `test_import_logica.py`:

```python
from datetime import datetime, timedelta

import pytest

from import_logica import (
    PERIODE_KEUZES,
    beoordeel_nummer,
    naar_naief_utc,
    periode_grens,
)

NU = datetime(2026, 7, 29, 12, 0, 0)


def info(sale=False, open_=False, laatste_contact=None):
    return {"sale": sale, "open": open_, "laatste_contact": laatste_contact}


# --- naar_naief_utc ---

def test_naief_utc_met_en_zonder_tijdzone_geeft_zelfde_moment():
    zonder = naar_naief_utc("2026-06-10T10:44:13.462284")
    met = naar_naief_utc("2026-06-10T10:44:13.462284+00:00")
    assert zonder == met == datetime(2026, 6, 10, 10, 44, 13, 462284)


def test_naief_utc_rekent_andere_tijdzone_om_naar_utc():
    assert naar_naief_utc("2026-06-10T12:44:13+02:00") == datetime(2026, 6, 10, 10, 44, 13)


@pytest.mark.parametrize("leeg", [None, ""])
def test_naief_utc_op_leeg_geeft_none(leeg):
    assert naar_naief_utc(leeg) is None


# --- periode_grens ---

def test_periode_grens_none_betekent_hele_database():
    assert periode_grens(None) is None


def test_periode_grens_rekent_maanden_terug():
    assert periode_grens(3, nu=NU) == datetime(2026, 4, 29, 12, 0, 0)


def test_periode_keuzes_bevat_de_vier_opties():
    assert PERIODE_KEUZES == {
        "Hele database": None,
        "Laatste 3 maanden": 3,
        "Laatste 6 maanden": 6,
        "Laatste 12 maanden": 12,
    }


# --- beoordeel_nummer ---

def test_onbekend_nummer_is_nieuw():
    assert beoordeel_nummer(None, op_blacklist=False, grens=None) == "nieuw"


def test_blacklist_wint_van_sale_en_periode():
    oud = info(sale=True, open_=True, laatste_contact=datetime(2020, 1, 1))
    assert beoordeel_nummer(oud, op_blacklist=True, grens=periode_grens(3, nu=NU)) == "blacklist"


def test_blacklist_blokkeert_ook_onbekend_nummer():
    assert beoordeel_nummer(None, op_blacklist=True, grens=None) == "blacklist"


def test_sale_blokkeert_ook_ver_buiten_de_periode():
    oud = info(sale=True, laatste_contact=datetime(2020, 1, 1))
    assert beoordeel_nummer(oud, op_blacklist=False, grens=periode_grens(3, nu=NU)) == "sale"


def test_nog_open_blokkeert_ook_zonder_contactdatum():
    wacht = info(open_=True, laatste_contact=None)
    assert beoordeel_nummer(wacht, op_blacklist=False, grens=periode_grens(3, nu=NU)) == "nog_open"


def test_contact_op_de_grens_blokkeert():
    grens = periode_grens(3, nu=NU)
    assert beoordeel_nummer(info(laatste_contact=grens), op_blacklist=False, grens=grens) == "recent_contact"


def test_contact_net_voor_de_grens_is_nieuw():
    grens = periode_grens(3, nu=NU)
    net_ervoor = grens - timedelta(seconds=1)
    assert beoordeel_nummer(info(laatste_contact=net_ervoor), op_blacklist=False, grens=grens) == "nieuw"


def test_hele_database_blokkeert_elk_bestaand_nummer():
    heel_oud = info(laatste_contact=datetime(2019, 1, 1))
    assert beoordeel_nummer(heel_oud, op_blacklist=False, grens=None) == "recent_contact"


def test_bestaand_nummer_zonder_contactdatum_binnen_periode_is_nieuw():
    # Afgeronde rij zonder eerder contact: mag opnieuw, mits niet 'open'.
    assert beoordeel_nummer(info(), op_blacklist=False, grens=periode_grens(3, nu=NU)) == "nieuw"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/BotAgent/jordy-dashboard && python3 -m pytest test_import_logica.py -q`
Expected: FAIL met `ModuleNotFoundError: No module named 'import_logica'`

- [ ] **Step 3: Write minimal implementation**

Maak `import_logica.py`:

```python
"""Beslislogica voor het ontdubbelen bij lead-import.

Bewust vrij van Supabase en Streamlit, zodat alles zonder database te testen is
(zelfde aanpak als dialer_brein.py). Spec:
docs/superpowers/specs/2026-07-29-import-ontdubbel-periode-design.md
"""

from datetime import datetime, timezone

from dateutil.relativedelta import relativedelta

# Labels voor de radio in het importscherm -> aantal maanden (None = hele database).
PERIODE_KEUZES = {
    "Hele database": None,
    "Laatste 3 maanden": 3,
    "Laatste 6 maanden": 6,
    "Laatste 12 maanden": 12,
}


def naar_naief_utc(waarde):
    """ISO-tekst -> naïeve UTC-datetime, of None.

    Nodig omdat de twee datumkolommen verschillen: first_attempt is tekst zonder
    tijdzone (naïef UTC), ended_at is timestamptz met '+00:00'. Zo zijn ze
    onderling vergelijkbaar.
    """
    if not waarde:
        return None
    moment = datetime.fromisoformat(waarde)
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment


def periode_grens(maanden, nu=None):
    """Ondergrens van het ontdubbel-venster als naïeve UTC-datetime.

    None = 'hele database' (geen ondergrens). 'nu' is er zodat tests een vast
    tijdstip kunnen meegeven.
    """
    if maanden is None:
        return None
    nu = nu or datetime.now(timezone.utc).replace(tzinfo=None)
    return nu - relativedelta(months=maanden)


def beoordeel_nummer(info, op_blacklist, grens):
    """Bepaal wat er met één nummer moet gebeuren bij import.

    info    None als het nummer nog niet in leads staat, anders
            {'sale': bool, 'open': bool, 'laatste_contact': datetime|None},
            samengevat over ALLE rijen van dat nummer.
    grens   ondergrens van het venster, of None voor 'hele database'.

    Geeft: 'blacklist' | 'sale' | 'nog_open' | 'recent_contact' | 'nieuw'.
    De eerste regel die raak is, wint.
    """
    if op_blacklist:
        return "blacklist"
    if info is None:
        return "nieuw"
    if info.get("sale"):
        return "sale"
    if info.get("open"):
        return "nog_open"
    if grens is None:
        # Hele database: alles wat al bestaat blokkeert.
        return "recent_contact"
    laatste = info.get("laatste_contact")
    if laatste is not None and laatste >= grens:
        return "recent_contact"
    return "nieuw"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/BotAgent/jordy-dashboard && python3 -m pytest test_import_logica.py -q`
Expected: PASS, 16 tests

- [ ] **Step 5: Controleer dat de bestaande tests nog draaien**

Run: `cd ~/BotAgent/jordy-dashboard && python3 -m pytest -q`
Expected: PASS, 37 bestaande + 16 nieuwe = 53 tests

- [ ] **Step 6: Commit**

```bash
cd ~/BotAgent/jordy-dashboard
git add import_logica.py test_import_logica.py
git commit -m "feat: pure beslislogica voor ontdubbelen bij import

Blacklist, sales en nog niet afgeronde nummers blokkeren altijd; de
periodegrens geldt alleen voor de rest. Zonder Supabase, dus testbaar.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Opzoekfunctie `bestaande_lead_info` in `dashboard.py`

**Files:**
- Modify: `dashboard.py` — nieuwe functie direct ná `existing_phones` (nu regel 204-213)

**Interfaces:**
- Consumes: `naar_naief_utc` uit Task 1
- Produces: `bestaande_lead_info(phones: list[str], chunk_size: int = 200) -> dict[str, dict]`,
  waarbij elke waarde de `info`-vorm uit Task 1 heeft:
  `{"sale": bool, "open": bool, "laatste_contact": datetime | None}`.
  Nummers die niet in `leads` staan komen niet in de dict voor.

- [ ] **Step 1: Voeg de import toe bovenaan `dashboard.py`**

Zoek het blok met bestaande imports (waar ook `import dialer_brein` staat) en voeg toe:

```python
from import_logica import PERIODE_KEUZES, beoordeel_nummer, naar_naief_utc, periode_grens
```

- [ ] **Step 2: Voeg de opzoekfunctie toe direct ná `existing_phones`**

`existing_phones` blijft ongewijzigd — die wordt nog gebruikt voor de blacklist.
Plaats hieronder:

```python
def bestaande_lead_info(phones, chunk_size=200):
    """Haal per nummer de velden op die nodig zijn om te ontdubbelen.

    Zelfde chunk-aanpak als existing_phones (gerichte IN-query, niet de hele
    tabel ophalen), maar met de kolommen die de beslisregels nodig hebben. Een
    nummer kan meerdere rijen hebben (bv. een outbound- en een inbound-rij);
    die worden hier samengevat tot één oordeel, waarbij één blokkerende rij
    genoeg is.

    Geeft: {phone: {'sale': bool, 'open': bool, 'laatste_contact': datetime|None}}
    Nummers die niet in leads staan ontbreken in de dict.
    """
    if not phones:
        return {}
    unique = list({p for p in phones if p})
    gevonden = {}
    for i in range(0, len(unique), chunk_size):
        res = supabase.table('leads') \
            .select('phone,status,result,first_attempt,ended_at') \
            .in_('phone', unique[i:i + chunk_size]).execute()
        for rij in (res.data or []):
            tel = rij['phone']
            huidig = gevonden.setdefault(
                tel, {"sale": False, "open": False, "laatste_contact": None})
            if rij.get('result') == 'SUCCES':
                huidig["sale"] = True
            if rij.get('status') != 'finished':
                huidig["open"] = True
            for veld in ('first_attempt', 'ended_at'):
                moment = naar_naief_utc(rij.get(veld))
                if moment is not None and (huidig["laatste_contact"] is None
                                           or moment > huidig["laatste_contact"]):
                    huidig["laatste_contact"] = moment
    return gevonden
```

- [ ] **Step 3: Controleer de syntax**

Run: `cd ~/BotAgent/jordy-dashboard && python3 -m py_compile dashboard.py`
Expected: geen uitvoer (geslaagd)

- [ ] **Step 4: Controleer de functie tegen de echte database (alleen lezen)**

Deze functie praat met Supabase en valt dus buiten de unit-tests. Verifieer hem
één keer handmatig tegen bekende nummers. Draai vanaf de server, want de
`.env` met de sleutels staat daar:

```bash
ssh -i ~/.ssh/leaseweb_jordy -o IdentitiesOnly=yes root@5.79.88.41 \
  "cd /root/livekit-agent && ./venv/bin/python -c \"
from dotenv import load_dotenv; load_dotenv('/root/livekit-agent/.env')
import os
from supabase import create_client
s=create_client(os.getenv('SUPABASE_URL'),os.getenv('SUPABASE_KEY'))
# een sale, een nummer in de wachtrij, en een onbekend nummer
sale=s.table('leads').select('phone').eq('result','SUCCES').limit(1).execute().data[0]['phone']
open_=s.table('leads').select('phone').eq('status','new').limit(1).execute().data[0]['phone']
print('sale-nummer :', sale)
print('open nummer :', open_)
for tel in (sale, open_):
    rijen=s.table('leads').select('phone,status,result,first_attempt,ended_at').eq('phone',tel).execute().data
    print(tel, '->', len(rijen), 'rij(en):', [(r['status'], r['result']) for r in rijen])
\""
```

Verwacht: het sale-nummer heeft minstens één rij met `result='SUCCES'`, het
open nummer minstens één rij met `status='new'`. Controleer dat
`bestaande_lead_info` op diezelfde rijen `sale=True` respectievelijk
`open=True` zou opleveren.

- [ ] **Step 5: Commit**

```bash
cd ~/BotAgent/jordy-dashboard
git add dashboard.py
git commit -m "feat: bestaande_lead_info haalt ontdubbel-velden per nummer op

Zelfde chunk-aanpak als existing_phones, maar met status/result/first_attempt/
ended_at, samengevat per nummer. Aantal queries blijft gelijk.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Radio-keuze en bedrading in de importlus

**Files:**
- Modify: `dashboard.py` — importscherm, nu regel 1304-1376

**Interfaces:**
- Consumes: `PERIODE_KEUZES`, `periode_grens`, `beoordeel_nummer` (Task 1); `bestaande_lead_info` (Task 2)
- Produces: `st.session_state["import_resultaat"]` met de sleutels
  `soort, batch_id, totaal, toegevoegd, recent_contact, sale, blacklist, nog_open, ongeldig, mislukt`
  (let op: `dubbel` bestaat niet meer)

- [ ] **Step 1: Voeg de radio toe onder de naam-kolomkeuze**

Zoek in `dashboard.py`:

```python
            name_col = None
            if import_doel == "📞 Leads voor Dialer":
                name_col = st.selectbox("Welke kolom is de naam?", ["Kies..."] + cols)
```

Vervang door:

```python
            name_col = None
            periode_keuze = "Hele database"
            if import_doel == "📞 Leads voor Dialer":
                name_col = st.selectbox("Welke kolom is de naam?", ["Kies..."] + cols)
                periode_keuze = st.radio(
                    "Ontdubbelen tegen:", list(PERIODE_KEUZES.keys()), index=0,
                    help="Bepaalt hoe ver terug een eerder contact een nummer blokkeert.")
                st.caption(
                    "ℹ️ Blacklist, sales en nummers die nog in de wachtrij staan of "
                    "in gesprek zijn, worden altijd geblokkeerd — ongeacht de periode.")
```

- [ ] **Step 2: Vervang de ontdubbel-lus**

Zoek dit blok (nu regel 1323-1349):

```python
                    # Check alleen de nummers uit dit bestand tegen DB (niet hele tabel ophalen)
                    geldige = [p for p in clean_phones if p]
                    existing_numbers = existing_phones('leads', geldige)
                    blacklist_numbers = existing_phones('blacklist', geldige)

                    to_upload = []
                    c_new, c_dup, c_black, c_inv = 0, 0, 0, 0

                    for i, (index, row) in enumerate(df.iterrows()):
                        clean = clean_phones[i]
                        if not clean:
                            c_inv += 1
                        elif clean in blacklist_numbers:
                            c_black += 1
                        elif clean in existing_numbers:
                            c_dup += 1
                        else:
                            clean_naam = str(row[name_col]) if name_col and name_col != "Kies..." else "Klant"
                            to_upload.append({
                                "phone": clean,
                                "name": clean_naam,
                                "status": "new",
                                "batch_id": batch_id,
                                "original_data": row.to_dict()
                            })
                            existing_numbers.add(clean)
                            c_new += 1

                        if i % 100 == 0: progress.progress(min(i / len(df), 1.0))
```

Vervang door:

```python
                    # Check alleen de nummers uit dit bestand tegen DB (niet hele tabel ophalen)
                    geldige = [p for p in clean_phones if p]
                    lead_info = bestaande_lead_info(geldige)
                    blacklist_numbers = existing_phones('blacklist', geldige)
                    grens = periode_grens(PERIODE_KEUZES[periode_keuze])

                    to_upload = []
                    tellers = {"nieuw": 0, "blacklist": 0, "sale": 0,
                               "nog_open": 0, "recent_contact": 0}
                    c_inv = 0

                    for i, (index, row) in enumerate(df.iterrows()):
                        clean = clean_phones[i]
                        if not clean:
                            c_inv += 1
                        else:
                            oordeel = beoordeel_nummer(
                                lead_info.get(clean), clean in blacklist_numbers, grens)
                            tellers[oordeel] += 1
                            if oordeel == "nieuw":
                                clean_naam = str(row[name_col]) if name_col and name_col != "Kies..." else "Klant"
                                to_upload.append({
                                    "phone": clean,
                                    "name": clean_naam,
                                    "status": "new",
                                    "batch_id": batch_id,
                                    "original_data": row.to_dict()
                                })
                                # Zelfde nummer verderop in het bestand telt als
                                # 'nog open', want het staat nu in de wachtrij.
                                lead_info[clean] = {"sale": False, "open": True,
                                                    "laatste_contact": None}

                        if i % 100 == 0: progress.progress(min(i / len(df), 1.0))
```

- [ ] **Step 3: Vervang de uitslag-dict**

Zoek:

```python
                    st.session_state["import_resultaat"] = {
                        "soort": "leads",
                        "batch_id": batch_id,
                        "totaal": len(df),
                        "toegevoegd": c_new - fouten,
                        "dubbel": c_dup,
                        "blacklist": c_black,
                        "ongeldig": c_inv,
                        "mislukt": fouten,
                    }
```

Vervang door:

```python
                    st.session_state["import_resultaat"] = {
                        "soort": "leads",
                        "batch_id": batch_id,
                        "totaal": len(df),
                        "periode": periode_keuze,
                        "toegevoegd": tellers["nieuw"] - fouten,
                        "recent_contact": tellers["recent_contact"],
                        "sale": tellers["sale"],
                        "blacklist": tellers["blacklist"],
                        "nog_open": tellers["nog_open"],
                        "ongeldig": c_inv,
                        "mislukt": fouten,
                    }
```

- [ ] **Step 4: Controleer dat `c_new` nergens meer gebruikt wordt in het leads-pad**

Run: `cd ~/BotAgent/jordy-dashboard && grep -n "c_new\|c_dup\|c_black" dashboard.py`
Expected: alleen treffers in het **blacklist**-pad (nu rond regel 1383-1393). Als
er nog een treffer in het leads-pad staat, is stap 2 of 3 niet volledig toegepast.

- [ ] **Step 5: Controleer de syntax**

Run: `cd ~/BotAgent/jordy-dashboard && python3 -m py_compile dashboard.py`
Expected: geen uitvoer

- [ ] **Step 6: Commit**

```bash
cd ~/BotAgent/jordy-dashboard
git add dashboard.py
git commit -m "feat: kiesbare ontdubbel-periode bij lead-import

Radio met hele database / 3 / 6 / 12 maanden; standaard hele database, dus
zonder actie identiek aan het oude gedrag. Tellers per blokkeerreden.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Uitgesplitste uitslag in de pop-up

**Files:**
- Modify: `dashboard.py` — `toon_import_resultaat`, nu regel 1252-1272

**Interfaces:**
- Consumes: de uitslag-dict uit Task 3
- Produces: niets (alleen weergave)

- [ ] **Step 1: Vervang het leads-deel van `toon_import_resultaat`**

Zoek:

```python
def toon_import_resultaat(r):
    if r.get("soort") == "leads":
        st.markdown(f"**Batch:** `{r['batch_id']}`")
        a, b = st.columns(2)
        a.metric("📄 Regels in bestand", r["totaal"])
        b.metric("🆕 Toegevoegd aan wachtrij", r["toegevoegd"])
        c, d = st.columns(2)
        c.metric("🔄 Dubbel (al in systeem)", r["dubbel"])
        d.metric("⛔ Op blacklist", r["blacklist"])
        e, f = st.columns(2)
        e.metric("⚠️ Ongeldig nummer", r["ongeldig"])
        f.metric("❌ Mislukt (DB-fout)", r["mislukt"])
        if r["mislukt"]:
            st.error(f"{r['mislukt']} leads konden NIET worden opgeslagen "
                     "(databasefout — zie logs).")
        elif r["toegevoegd"] == 0:
            st.warning("Er is **niets** aan de wachtrij toegevoegd. Alle nummers "
                       "waren al in het systeem (dubbel), op de blacklist, of ongeldig. "
                       "Daarom steeg de wachtrij niet.")
        else:
            st.success(f"{r['toegevoegd']} nieuwe leads staan nu in de wachtrij.")
```

Vervang door:

```python
def toon_import_resultaat(r):
    if r.get("soort") == "leads":
        st.markdown(f"**Batch:** `{r['batch_id']}`")
        st.caption(f"Ontdubbeld tegen: **{r.get('periode', 'Hele database')}**")
        a, b = st.columns(2)
        a.metric("📄 Regels in bestand", r["totaal"])
        b.metric("🆕 Toegevoegd aan wachtrij", r["toegevoegd"])
        c, d, e = st.columns(3)
        c.metric("🔄 Recent contact", r["recent_contact"],
                 help="Al eerder gebeld of teruggebeld binnen de gekozen periode.")
        d.metric("💰 Sale", r["sale"],
                 help="Hier is al een succes uit gekomen — nooit opnieuw bellen.")
        e.metric("⏳ Nog open", r["nog_open"],
                 help="Staat al in de wachtrij of is in gesprek.")
        f, g, h = st.columns(3)
        f.metric("⛔ Op blacklist", r["blacklist"])
        g.metric("⚠️ Ongeldig nummer", r["ongeldig"])
        h.metric("❌ Mislukt (DB-fout)", r["mislukt"])
        if r["mislukt"]:
            st.error(f"{r['mislukt']} leads konden NIET worden opgeslagen "
                     "(databasefout — zie logs).")
        elif r["toegevoegd"] == 0:
            st.warning("Er is **niets** aan de wachtrij toegevoegd. Alle nummers "
                       "waren al in het systeem, op de blacklist, of ongeldig. "
                       "Daarom steeg de wachtrij niet.")
        else:
            st.success(f"{r['toegevoegd']} nieuwe leads staan nu in de wachtrij.")
        if r["recent_contact"] and r.get("periode") != "Hele database":
            st.info(f"💡 {r['recent_contact']} nummers vielen af op 'recent contact'. "
                    "Met een kortere periode zouden er meer doorkomen.")
```

- [ ] **Step 2: Controleer de syntax**

Run: `cd ~/BotAgent/jordy-dashboard && python3 -m py_compile dashboard.py`
Expected: geen uitvoer

- [ ] **Step 3: Controleer dat de oude sleutel nergens meer gelezen wordt**

Run: `cd ~/BotAgent/jordy-dashboard && grep -n 'r\["dubbel"\]\|r\[.dubbel.\]' dashboard.py`
Expected: alleen de treffer in het **blacklist**-deel van de pop-up (regel ~1279),
want die uitslag houdt zijn eigen `dubbel`-teller.

- [ ] **Step 4: Draai alle tests**

Run: `cd ~/BotAgent/jordy-dashboard && python3 -m pytest -q`
Expected: PASS, 53 tests

- [ ] **Step 5: Commit**

```bash
cd ~/BotAgent/jordy-dashboard
git add dashboard.py
git commit -m "feat: import-uitslag uitgesplitst per blokkeerreden

Toont recent contact / sale / nog open apart, zodat zichtbaar is of een
andere periode zou helpen.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Handmatige eindtest en uitrollen

**Files:** geen wijzigingen — dit is de controle vóór de deploy.

- [ ] **Step 1: Start het dashboard lokaal**

```bash
cd ~/BotAgent/jordy-dashboard && python3 -m streamlit run dashboard.py
```

Log in met het wachtwoord uit `APP_PASSWORD`.

- [ ] **Step 2: Maak een testbestand met bekende nummers**

Haal drie nummers op waarvan je het antwoord kent (een sale, een nummer in de
wachtrij, en een verzonnen nummer dat nergens voorkomt):

```bash
ssh -i ~/.ssh/leaseweb_jordy -o IdentitiesOnly=yes root@5.79.88.41 \
  "cd /root/livekit-agent && ./venv/bin/python -c \"
from dotenv import load_dotenv; load_dotenv('/root/livekit-agent/.env')
import os
from supabase import create_client
s=create_client(os.getenv('SUPABASE_URL'),os.getenv('SUPABASE_KEY'))
print('sale :', s.table('leads').select('phone').eq('result','SUCCES').limit(1).execute().data[0]['phone'])
print('open :', s.table('leads').select('phone').eq('status','new').limit(1).execute().data[0]['phone'])
\""
```

Zet die twee plus `+31600000001` in een CSV met kolommen `telefoon,naam`.

- [ ] **Step 3: Importeer met "Hele database" en controleer**

Verwacht: 1 toegevoegd (het verzonnen nummer), 1 sale, 1 nog open.
De wachtrij-teller op het dashboard stijgt met 1.

- [ ] **Step 4: Importeer hetzelfde bestand nogmaals met "Laatste 3 maanden"**

Verwacht: 0 toegevoegd, want het verzonnen nummer staat nu zelf in de wachtrij
en valt onder "nog open". Dit bewijst dat regel 3 werkt.

- [ ] **Step 5: Ruim de testleads op**

Verwijder de testbatch via de bestaande knop "Batch verwijderen" in het
dashboard, zodat `+31600000001` niet echt gebeld wordt.

- [ ] **Step 6: Uitrollen**

```bash
cd ~/BotAgent/jordy-dashboard && git push origin main
```

Streamlit Cloud deployt binnen 1-2 minuten. Controleer daarna in het live
dashboard dat de radio zichtbaar is en dat "Hele database" voorgeselecteerd staat.

- [ ] **Step 7: Werk het geheugen bij**

Nieuw memory-bestand in `~/.claude/projects/-Users-haruntekin-BotAgent/memory/`
met de beslisregels en de gemeten aantallen (34.896 inbound-rijen zonder
`first_attempt`, statussen `finished`/`new`/`in-progress`), plus een regel in
`MEMORY.md`.
