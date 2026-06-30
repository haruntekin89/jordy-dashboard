# Tempo volgt de koers — Implementatieplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** De live tempo-sturing laat het beltempo de curve (tijdschema naar 400) volgen — voorligt → omlaag, achterligt → omhoog — i.p.v. vrijwel altijd 100.

**Architecture:** `bereken_tempo` wordt in beide repos vervangen door een curve-volgend model: basis-tempo = curve-successen van dit uur ÷ gemeten bereik, plus een zachte inhaal van het gat met het schema, geklemd op [10, max]. Bestaande helpers blijven staan (ongebruikt) om bestaande tests niet te breken. De aanroep in `motor.py` blijft ongewijzigd.

**Tech Stack:** Pure Python (geen frameworks), losse `python3`-test-runners (`test_tempo_logica.py`, `test_dialer_brein.py`).

## Global Constraints

- **Dagdoel blijft 400** (`DAGDOEL = 400` in beide bestanden, niet wijzigen).
- **Vloer = 10 calls/min, max = via parameter `max_cpm`** (config `tempo_max`, nu 100).
- **Signatuur `bereken_tempo(uur_gewichten, isoweekday, nu_uur, nu_minuut, succ_vandaag, calls_90, succ_90, max_cpm, dagdoel=DAGDOEL, vloer=VLOER, drempel=30)` blijft exact gelijk** — `motor.py` aanroep verandert niet.
- **Bewuste duplicatie**: `tempo_logica.py` (server) en `dialer_brein.py` (dashboard) moeten dezelfde `bereken_tempo` + helpers krijgen; server en dashboard kunnen elkaar niet importeren.
- **Server-code staat niet in git** → backup via `*.bak-curve` vóór overschrijven; dashboard via git.
- **Geen deploy zonder Harun's go + `pratend:0`-moment.**

---

### Task 1: Curve-volgend model in `dialer_brein.py` (dashboard)

`dialer_brein.py` heeft al `verwachte_curve`, `verwacht_tot_nu`, `belvenster`, `bereik_meten`, `uur_profiel_tempo`. We voegen `curve_dit_uur` + `tempo_curve` toe en herschrijven `bereken_tempo`.

**Files:**
- Modify: `~/BotAgent/jordy-dashboard/dialer_brein.py` (voeg 2 functies toe net vóór `bereken_tempo` op regel 323; herschrijf `bereken_tempo` regels 323-339)
- Test: `~/BotAgent/jordy-dashboard/test_dialer_brein.py`

**Interfaces:**
- Consumes: `verwachte_curve(gewichten, uren_venster, dagdoel)`, `verwacht_tot_nu(curve, uren_venster, nu_uur, nu_minuut, dagdoel)`, `belvenster(isoweekday)`, `bereik_meten(succ_90, calls_90)`, `uur_profiel_tempo(uur_gewichten, nu_uur, venster_uren, max_cpm, vloer)` — allemaal al aanwezig.
- Produces:
  - `curve_dit_uur(curve, venster_uren, nu_uur) -> float`
  - `tempo_curve(cdu, gat, resterende_uren, bereik, max_cpm, vloer=VLOER) -> int`
  - `bereken_tempo(...) -> int` (zelfde signatuur, nieuw gedrag)

- [ ] **Step 1: Schrijf de falende tests**

Voeg toe aan `test_dialer_brein.py`. Pas eerst de importregel (regel 2) aan: voeg `curve_dit_uur as db_curve_dit_uur, tempo_curve as db_tempo_curve` toe aan de bestaande `from dialer_brein import ...`.

```python
def test_tempo_curve_helper():
    # cdu 33,3 successen dit uur, op schema (gat 0), bereik 1% → 33,3/0,01/60 ≈ 56/min
    assert db_tempo_curve(33.3, 0.0, 8, 0.01, 100) == 56
    # achter (gat +) → hoger dan op schema
    assert db_tempo_curve(33.3, 80.0, 8, 0.01, 100) > 56
    # voor (gat -) → lager dan op schema
    assert db_tempo_curve(33.3, -80.0, 8, 0.01, 100) < 56
    # bereik 0 → vloer
    assert db_tempo_curve(33.3, 0.0, 8, 0.0, 100) == 10
    # heel ver voor (doel dit uur <= 0) → vloer
    assert db_tempo_curve(10.0, -1000.0, 8, 0.01, 100) == 10
    # geen uren meer → vloer
    assert db_tempo_curve(33.3, 0.0, 0, 0.01, 100) == 10


def test_curve_dit_uur():
    venster = list(range(9, 21))
    curve = db_verwachte_curve({}, venster)   # vlak profiel → 400/12 per uur
    # eerste uur: stap vanaf 0
    assert abs(db_curve_dit_uur(curve, venster, 9) - (400 / 12)) < 0.1
    # later uur: stap tussen twee curve-punten, ook ≈ 400/12 bij vlak profiel
    assert abs(db_curve_dit_uur(curve, venster, 15) - (400 / 12)) < 0.1


def test_bereken_tempo_volgt_koers():
    g = {u: 1.0 for u in range(9, 21)}        # vlak profiel; op 13:00 hoort ≈133 binnen
    # genoeg data, bereik 1%
    op_schema = db_bereken_tempo(g, 1, 13, 0, succ_vandaag=133, calls_90=1000, succ_90=10, max_cpm=100)
    voor      = db_bereken_tempo(g, 1, 13, 0, succ_vandaag=180, calls_90=1000, succ_90=10, max_cpm=100)
    achter    = db_bereken_tempo(g, 1, 13, 0, succ_vandaag=80,  calls_90=1000, succ_90=10, max_cpm=100)
    assert voor < op_schema < achter
    for t in (op_schema, voor, achter):
        assert 10 <= t <= 100


def test_bereken_tempo_geen_zaagtand():
    g = {u: 1.0 for u in range(9, 21)}
    vroeg = db_bereken_tempo(g, 1, 13, 5,  succ_vandaag=133, calls_90=1000, succ_90=10, max_cpm=100)
    laat  = db_bereken_tempo(g, 1, 13, 55, succ_vandaag=133, calls_90=1000, succ_90=10, max_cpm=100)
    # binnen het uur mag het tempo maar zacht oplopen, niet naar de max springen
    assert laat - vroeg <= 15
    assert laat < 100


def test_bereken_tempo_randen():
    g = {u: 1.0 for u in range(9, 21)}
    # < 30 calls → terugval op uur-profiel
    assert db_bereken_tempo(g, 1, 13, 0, 50, 10, 1, 100) == \
        db_uur_profiel_tempo(g, 13, list(range(9, 21)), 100)
    # bereik 0 (geen successen) → terugval op uur-profiel
    assert db_bereken_tempo(g, 1, 13, 0, 50, 1000, 0, 100) == \
        db_uur_profiel_tempo(g, 13, list(range(9, 21)), 100)
    # doel binnen → vloer
    assert db_bereken_tempo(g, 1, 13, 0, 400, 1000, 10, 100) == 10
    # zondag → vloer
    assert db_bereken_tempo(g, 7, 13, 0, 50, 1000, 10, 100) == 10
    # vóór venster → vloer
    assert db_bereken_tempo(g, 1, 7, 0, 50, 1000, 10, 100) == 10
```

Voeg aan de importregel ook `verwachte_curve as db_verwachte_curve, uur_profiel_tempo as db_uur_profiel_tempo` toe als die er nog niet staan (controleer regel 2; `verwachte_curve` staat er al, `uur_profiel_tempo` mogelijk niet).

- [ ] **Step 2: Run de tests, verwacht FAIL**

Run: `cd ~/BotAgent/jordy-dashboard && python3 test_dialer_brein.py`
Expected: FAIL — `ImportError: cannot import name 'curve_dit_uur'` (de functies bestaan nog niet).

- [ ] **Step 3: Voeg de twee helpers toe + herschrijf `bereken_tempo`**

Voeg deze twee functies toe **net vóór** `def bereken_tempo` (rond regel 323):

```python
def curve_dit_uur(curve, venster_uren, nu_uur):
    """Successen die het schema aan DIT uur toekent (de curve-stap van dit uur)."""
    idx = venster_uren.index(nu_uur)
    vorig = curve[venster_uren[idx - 1]] if idx > 0 else 0.0
    return curve[nu_uur] - vorig


def tempo_curve(cdu, gat, resterende_uren, bereik, max_cpm, vloer=VLOER):
    """Curve-volgend tempo: basis (cdu/bereik) + zachte inhaal van het gat.
    cdu = curve-successen dit uur; gat>0 = achter, gat<0 = voor. Geklemd [vloer, max]."""
    if bereik <= 0 or resterende_uren <= 0:
        return vloer
    inhaal = gat / resterende_uren
    doel_dit_uur = cdu + inhaal
    if doel_dit_uur <= 0:
        return vloer
    cpm = (doel_dit_uur / bereik) / 60.0
    return int(max(vloer, min(max_cpm, round(cpm))))
```

Vervang de body van `bereken_tempo` (regels 323-339) door:

```python
def bereken_tempo(uur_gewichten, isoweekday, nu_uur, nu_minuut, succ_vandaag,
                  calls_90, succ_90, max_cpm, dagdoel=DAGDOEL, vloer=VLOER, drempel=30):
    """Curve-volgend tempo: volg het schema naar het dagdoel (voor → omlaag,
    achter → omhoog). Terugval op het uur-profiel bij te weinig data."""
    venster = belvenster(isoweekday)
    if venster is None:
        return vloer
    start, eind = venster
    if nu_uur < start or nu_uur >= eind:
        return vloer
    venster_uren = list(range(start, eind))
    if calls_90 < drempel:
        return uur_profiel_tempo(uur_gewichten, nu_uur, venster_uren, max_cpm, vloer)
    bereik = bereik_meten(succ_90, calls_90)
    if bereik <= 0:
        return uur_profiel_tempo(uur_gewichten, nu_uur, venster_uren, max_cpm, vloer)
    if succ_vandaag >= dagdoel:
        return vloer
    curve = verwachte_curve(uur_gewichten, venster_uren, dagdoel)
    verwacht_nu = verwacht_tot_nu(curve, venster_uren, nu_uur, nu_minuut, dagdoel)
    cdu = curve_dit_uur(curve, venster_uren, nu_uur)
    gat = verwacht_nu - succ_vandaag
    resterende_uren = eind - nu_uur
    return tempo_curve(cdu, gat, resterende_uren, bereik, max_cpm, vloer)
```

- [ ] **Step 4: Run de tests, verwacht PASS**

Run: `cd ~/BotAgent/jordy-dashboard && python3 test_dialer_brein.py`
Expected: `ALLE TESTS GESLAAGD` (alle bestaande + nieuwe tests groen). Als een oude test over `bereken_tempo` faalt op aannames van het oude model, herzie die test conform Task 1 step 1 (relatie-asserts i.p.v. vaste oude waardes).

- [ ] **Step 5: Commit (lokaal, nog niet pushen)**

```bash
cd ~/BotAgent/jordy-dashboard
git add dialer_brein.py test_dialer_brein.py docs/superpowers/specs/2026-06-30-tempo-volgt-koers-design.md docs/superpowers/plans/2026-06-30-tempo-volgt-koers.md
git commit -m "feat: curve-volgend beltempo (volgt koers i.p.v. altijd max)"
```

---

### Task 2: Spiegel het model naar `tempo_logica.py` (server/motor)

`tempo_logica.py` mist `verwachte_curve` en `verwacht_tot_nu` — die voegen we toe (verbatim uit `dialer_brein.py`), plus `curve_dit_uur` + `tempo_curve`, en herschrijven `bereken_tempo` identiek aan Task 1.

**Files:**
- Modify: `~/BotAgent/livekit-agent/tempo_logica.py`
- Test: `~/BotAgent/livekit-agent/test_tempo_logica.py`

**Interfaces:**
- Produces: identieke `verwachte_curve`, `verwacht_tot_nu`, `curve_dit_uur`, `tempo_curve`, `bereken_tempo` als Task 1.

- [ ] **Step 1: Schrijf/actualiseer de tests**

In `test_tempo_logica.py`: voeg aan de import (regels 2-4) toe: `verwachte_curve, verwacht_tot_nu, curve_dit_uur, tempo_curve`. Vervang `test_bereken_tempo_terugval_en_model` (regels 88-99) door onderstaande set (zonder `db_`-prefix; functies zijn lokaal geïmporteerd):

```python
def test_tempo_curve_helper():
    assert tempo_curve(33.3, 0.0, 8, 0.01, 100) == 56
    assert tempo_curve(33.3, 80.0, 8, 0.01, 100) > 56
    assert tempo_curve(33.3, -80.0, 8, 0.01, 100) < 56
    assert tempo_curve(33.3, 0.0, 8, 0.0, 100) == 10
    assert tempo_curve(10.0, -1000.0, 8, 0.01, 100) == 10
    assert tempo_curve(33.3, 0.0, 0, 0.01, 100) == 10


def test_curve_dit_uur():
    venster = list(range(9, 21))
    curve = verwachte_curve({}, venster)
    assert abs(curve_dit_uur(curve, venster, 9) - (400 / 12)) < 0.1
    assert abs(curve_dit_uur(curve, venster, 15) - (400 / 12)) < 0.1


def test_bereken_tempo_volgt_koers():
    g = {u: 1.0 for u in range(9, 21)}
    op_schema = bereken_tempo(g, 1, 13, 0, succ_vandaag=133, calls_90=1000, succ_90=10, max_cpm=100)
    voor      = bereken_tempo(g, 1, 13, 0, succ_vandaag=180, calls_90=1000, succ_90=10, max_cpm=100)
    achter    = bereken_tempo(g, 1, 13, 0, succ_vandaag=80,  calls_90=1000, succ_90=10, max_cpm=100)
    assert voor < op_schema < achter
    for t in (op_schema, voor, achter):
        assert 10 <= t <= 100


def test_bereken_tempo_geen_zaagtand():
    g = {u: 1.0 for u in range(9, 21)}
    vroeg = bereken_tempo(g, 1, 13, 5,  succ_vandaag=133, calls_90=1000, succ_90=10, max_cpm=100)
    laat  = bereken_tempo(g, 1, 13, 55, succ_vandaag=133, calls_90=1000, succ_90=10, max_cpm=100)
    assert laat - vroeg <= 15
    assert laat < 100


def test_bereken_tempo_randen():
    g = {u: 1.0 for u in range(9, 21)}
    assert bereken_tempo(g, 1, 13, 0, 50, 10, 1, 100) == \
        uur_profiel_tempo(g, 13, list(range(9, 21)), 100)
    assert bereken_tempo(g, 1, 13, 0, 50, 1000, 0, 100) == \
        uur_profiel_tempo(g, 13, list(range(9, 21)), 100)
    assert bereken_tempo(g, 1, 13, 0, 400, 1000, 10, 100) == 10
    assert bereken_tempo(g, 7, 13, 0, 50, 1000, 10, 100) == 10
    assert bereken_tempo(g, 1, 7, 0, 50, 1000, 10, 100) == 10
```

- [ ] **Step 2: Run de tests, verwacht FAIL**

Run: `cd ~/BotAgent/livekit-agent && python3 test_tempo_logica.py`
Expected: FAIL — `ImportError: cannot import name 'verwachte_curve'`.

- [ ] **Step 3: Voeg helpers toe + herschrijf `bereken_tempo`**

Voeg `verwachte_curve` en `verwacht_tot_nu` toe (verbatim kopie uit `dialer_brein.py`, regels 69-99), net vóór de bestaande `bereik_meten`/`resterend_gewicht`-helpers:

```python
def verwachte_curve(gewichten, uren_venster, dagdoel=DAGDOEL):
    """Verdeel dagdoel over de beluren gewogen volgens het uur-profiel.
    Geeft het cumulatief verwachte aantal successen aan het EINDE van elk uur."""
    w = {u: gewichten.get(u, 1.0) for u in uren_venster}
    som = sum(w.values()) or 1.0
    curve = {}
    loper = 0.0
    for u in uren_venster:
        loper += dagdoel * (w[u] / som)
        curve[u] = round(loper, 2)
    return curve


def verwacht_tot_nu(curve, uren_venster, nu_uur, nu_minuut, dagdoel=DAGDOEL):
    """Verwacht aantal successen tot dit moment (interpoleert binnen het uur)."""
    if not uren_venster:
        return 0.0
    if nu_uur < uren_venster[0]:
        return 0.0
    if nu_uur > uren_venster[-1]:
        return float(dagdoel)
    vorige = 0.0
    for u in uren_venster:
        eind = curve[u]
        if u == nu_uur:
            aandeel = eind - vorige
            return round(vorige + aandeel * (nu_minuut / 60.0), 2)
        vorige = eind
    return float(dagdoel)
```

Let op: `gewichten.get(u, 1.0)` werkt alleen met int-keys. De config levert string-keys; `motor.py` geeft `cfg["uur_gewichten"]` door. **Controleer hoe `uur_gewichten` in `motor.py` wordt ingelezen** (regel ~289-331). Als het string-keys zijn, normaliseer in `verwachte_curve` met `_gewicht`:

```python
    w = {u: _gewicht(gewichten, u) for u in uren_venster}
```

(`_gewicht` bestaat al in `tempo_logica.py` en accepteert int/str keys; gebruik die variant in beide repos voor robuustheid.)

Voeg daarna `curve_dit_uur` + `tempo_curve` toe en herschrijf `bereken_tempo` — **exact dezelfde code als Task 1 Step 3** (kopieer verbatim).

- [ ] **Step 4: Run de tests, verwacht PASS**

Run: `cd ~/BotAgent/livekit-agent && python3 test_tempo_logica.py`
Expected: `ALLE TESTS GESLAAGD`.

- [ ] **Step 5: Syntax-check**

Run: `cd ~/BotAgent/livekit-agent && python3 -m py_compile tempo_logica.py && echo OK`
Expected: `OK`.

---

### Task 3: Veilige uitrol (alleen na Harun's go)

**Niet uitvoeren zonder Harun's expliciete "ja" én een `pratend:0`-moment.**

- [ ] **Step 1: Check of het veilig is om te herstarten**

Run: `ssh -i ~/.ssh/leaseweb_jordy -o IdentitiesOnly=yes root@5.79.88.41 'curl -s localhost:8080/health'`
Expected: JSON met `"pratend":0`. Zo niet → wachten tot 0.

- [ ] **Step 2: Backup op de server**

Run: `ssh -i ~/.ssh/leaseweb_jordy -o IdentitiesOnly=yes root@5.79.88.41 'cp /root/livekit-agent/tempo_logica.py /root/livekit-agent/tempo_logica.py.bak-curve'`
Expected: geen output (gelukt).

- [ ] **Step 3: Kopieer het nieuwe bestand**

Run: `scp -i ~/.ssh/leaseweb_jordy -o IdentitiesOnly=yes ~/BotAgent/livekit-agent/tempo_logica.py root@5.79.88.41:/root/livekit-agent/`
Expected: `tempo_logica.py 100% ...`.

- [ ] **Step 4: Herstart de motor**

Run: `ssh -i ~/.ssh/leaseweb_jordy -o IdentitiesOnly=yes root@5.79.88.41 'systemctl restart jordy-motor && sleep 3 && systemctl is-active jordy-motor && journalctl -u jordy-motor -n 20 --no-pager'`
Expected: `active` + logregels zonder traceback.

- [ ] **Step 5: Push het dashboard**

```bash
cd ~/BotAgent/jordy-dashboard && git push origin main
```
Expected: push geslaagd; Streamlit Cloud herdeployt (~1-2 min). Controleer in het dashboard dat "Stuurt op" nu een lager getal toont wanneer Jordy voorligt, en dat het overeenkomt met de richting van "Tempo-advies".

- [ ] **Step 6: Werk de memory bij**

Voeg een memory-bestand toe (`tempo_volgt_koers.md`) + pointer in `MEMORY.md`: curve-volgend tempo LIVE, doel 400, rollback `tempo_logica.py.bak-curve` / knop "zet uit", zaagtand gefixt, meten vanaf de dag erna.

---

## Self-Review

- **Spec coverage:** rekenmodel (Task 1/2 step 3), randgevallen weinig-data/bereik-0/doel-binnen/ver-voor/buiten-venster (tests step 1), beide repos (Task 1+2), zaagtand-fix (delen door 60 + test geen-zaagtand), tests (step 1), backup+kill-switch+deploy+rollback (Task 3), memory (Task 3 step 6). Gedekt.
- **Placeholder scan:** geen TBD/TODO; alle code voluit. Eén bewuste verificatiestap (string- vs int-keys in `motor.py`) met concrete instructie (`_gewicht` gebruiken) — geen placeholder.
- **Type consistency:** `curve_dit_uur(curve, venster_uren, nu_uur)`, `tempo_curve(cdu, gat, resterende_uren, bereik, max_cpm, vloer)`, `bereken_tempo(...)` identiek in beide repos en in alle tests; `verwachte_curve`/`verwacht_tot_nu` identieke signaturen.
