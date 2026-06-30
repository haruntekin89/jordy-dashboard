# Tempo volgt de koers (curve-volgend beltempo)

**Datum:** 2026-06-30
**Status:** ontwerp, akkoord Harun
**Raakt:** `tempo_logica.py` (server/motor), `dialer_brein.py` (dashboard), tests in beide repos

## Probleem

De live tempo-sturing belt vrijwel altijd 100/min, ook wanneer Jordy vóórligt op
schema en het dashboard-"Tempo-advies" juist "omlaag" zegt.

Oorzaak: de motor (`tempo_logica.bereken_tempo`) rekent **absoluut**:

```
nog_nodig = dagdoel(400) − succes_vandaag
calls_totaal = nog_nodig / bereik
```

Bij ~1% bereik kost 400 successen ~52.000 belletjes per dag. Dat is meer dan een
maximale dag oplevert (29-06: 38.601 belletjes → 299 successen). Daardoor blijft
`nog_nodig` de hele dag groot en plakt het tempo tegen de max (100).

Daarbovenop een tweede, kleiner mankement (zaagtand): het uur-quotum wordt gedeeld
door de **resterende minuten van dit uur** (`60 − minuut`), zonder de al-gebelde
calls af te trekken. Daardoor kruipt het tempo elk uur omhoog naar 100 en valt het
bij het nieuwe uur terug.

Tot slot lopen er twee breinen langs elkaar: het dashboard toont zowel
"Tempo-advies" (`koers`, kijkt naar voor/achter op de curve) als "Stuurt op"
(`bereken_tempo`, absoluut). Ze spreken elkaar tegen; de motor luistert alleen naar
de absolute. Het advies wordt nergens gebruikt.

## Doel

Het dagdoel blijft **400**. Het beltempo moet de **koers** volgen:
- vóórligt op schema → tempo omlaag (rustig doorbellen op curve-tempo),
- achterligt → tempo omhoog,
- niet meer standaard 100.

Keuzes van Harun (2026-06-30):
- Bij voorsprong: **rustig doorbellen op curve-tempo** (nooit helemaal stil).
- Reactiestijl: **geleidelijk** (zacht bijsturen, geen jojo).

## Aanpak (gekozen: curve-volgend)

De motor stuurt op de **curve** (het schema dat 400 over de dag uitsmeert volgens
het uur-profiel) in plaats van op de absolute berg. Dit sluit aan op `koers`, dat
al naar dezelfde curve kijkt. Afgewogen alternatieven: woord-vertaling
("omhoog"=+10%) — jojo't en vergt geheugen; vaste nudge op uur-profiel —
basistempo willekeurig. Beide afgevallen.

## Het rekenmodel

Per herberekening (motor doet dit ~elke config-cyclus; dashboard live):

1. **Belvenster bepalen** (weekdag 9–21, za 10–16, zo geen). Buiten venster → vloer.
2. **Te weinig data**: `calls_90 < drempel` (30) → terugval op `uur_profiel_tempo`
   (ongewijzigd gedrag). Voorkomt wilde sprongen op ruis.
3. **Bereik meten**: `bereik = succ_90 / calls_90`. `bereik == 0` → terugval op
   `uur_profiel_tempo`.
4. **Doel binnen**: `succes_vandaag >= dagdoel` → vloer (laag pitje).
5. **Curve & koers**:
   - `curve = verwachte_curve(gewichten, venster, dagdoel)` — cumulatief verwacht.
   - `verwacht_nu = verwacht_tot_nu(curve, venster, uur, minuut)`.
   - `curve_dit_uur = curve[uur] − curve[vorig_uur]` (per-uur deel van 400;
     voor het eerste uur is `vorig` = 0).
   - `gat = verwacht_nu − succes_vandaag` (>0 = achter, <0 = voor).
6. **Geleidelijke inhaal**: `resterende_uren = aantal uren van nu t/m laatste beluur`.
   `inhaal_dit_uur = gat / resterende_uren` (zacht uitgesmeerd).
7. **Doel-successen dit uur**: `doel_dit_uur = curve_dit_uur + inhaal_dit_uur`.
8. **Tempo**: `cpm = (doel_dit_uur / bereik) / 60`, geklemd op `[vloer(10), max_cpm(100)]`.
   Delen door 60 (heel uur) i.p.v. resterende minuten → **zaagtand verdwijnt**.

### Gedrag dat hieruit volgt
- **Op schema** (`gat≈0`): `cpm ≈ curve_dit_uur / bereik / 60` = basis-tempo.
- **Voorligt** (`gat<0`): `doel_dit_uur` onder de basis → tempo onder basis;
  bij kleine voorsprong ≈ curve-tempo (rustig doorbellen); bij grote voorsprong
  → vloer (10), nooit helemaal stil.
- **Achterligt** (`gat>0`): tempo boven basis, tot max (100).

### Eerlijke verwachting
Omdat 400 ambitieus is, ligt Jordy ná de ochtend vaak achter op de curve → dan
belt hij hoog/max. Dat is correct (achter op doel = harder bellen). De winst t.o.v.
nu: hij gaat **wél omlaag wanneer je echt voorligt** (zoals 's ochtends), i.p.v.
altijd 100.

## Componenten

### `tempo_logica.py` (server/motor — leidend voor het echte bellen)
- Nieuwe/aangepaste `bereken_tempo(...)` met het curve-volgend model.
  **Signatuur en aanroep in `motor.py` blijven gelijk** (zelfde argumenten).
- Curve-helpers `verwachte_curve` + `verwacht_tot_nu` worden hier toegevoegd
  (bewuste duplicatie met `dialer_brein.py`, conform bestaand patroon: server en
  dashboard kunnen elkaar niet importeren).
- `uur_profiel_tempo`, `belvenster`, `bereik_meten`, vloer/max blijven bestaan.
- De oude absolute helpers (`resterend_gewicht`, `tempo_behoefte`) vervallen of
  worden ongebruikt; opruimen.

### `dialer_brein.py` (dashboard — kijkglas)
- `bereken_tempo` krijgt hetzelfde curve-volgend model, zodat "Stuurt op" exact
  toont wat de motor doet en in lijn is met `koers`.
- `koers`, `verwachte_curve`, `verwacht_tot_nu` blijven (worden hergebruikt).

### `motor.py`
- Geen wijziging aan de aanroep; blijft `bereken_tempo(cfg[...], ...)` aanroepen.

### Dashboard-weergave (optioneel, klein)
- Niet vereist voor de werking. Eventueel later: "Tempo-advies" en "Stuurt op"
  samenvoegen tot één regel nu ze hetzelfde zeggen. Buiten scope van deze wijziging.

## Tests (TDD, beide repos waar de functie leeft)

In `test_tempo_logica.py` (server) en `test_dialer_brein.py` (dashboard):
- **op schema** (`succes ≈ verwacht_nu`) → tempo ≈ basis (curve_dit_uur/bereik/60).
- **voorligt** (succes > verwacht_nu) → tempo lager dan op-schema-geval.
- **achterligt** (succes < verwacht_nu) → tempo hoger dan op-schema-geval, ≤ max.
- **doel binnen** (succes ≥ 400) → vloer.
- **weinig data** (calls_90 < 30) → terugval op uur-profiel (gelijk aan
  `uur_profiel_tempo`).
- **bereik 0** → terugval op uur-profiel.
- **heel ver voor** → vloer, nooit onder vloer (10).
- **geen zaagtand**: zelfde inputs, alleen minuut variërend binnen een uur →
  tempo verandert niet sprongsgewijs richting max.
- **buiten venster** (zondag / vóór 9 / na 21) → vloer.

## Veiligheid & uitrol

- **Tests groen** vóór deploy.
- **Backups**: `tempo_logica.py.bak-curve` op de server vóór overschrijven;
  `dialer_brein.py` via git (revert-bare).
- **Kill-switch**: bestaande dashboard-knop "⏹️ Zet uit (mijn eigen speed)"
  (`tempo_sturing_aan=false`) zet alles terug naar handmatige speed.
- **Deploy** (server) alleen op een `pratend:0`-moment:
  `py_compile` → `scp` → `systemctl restart jordy-motor` → `journalctl` checken.
- **Dashboard** via git push naar `main` (Streamlit auto-deploy).
- **Meten** vanaf de dag erna: zakt het tempo zichtbaar wanneer Jordy voorligt
  (ochtend), en klopt "Stuurt op" met het werkelijk gemeten tempo?

## Rollback

1. Dashboard-knop "Zet uit" → handmatige speed (directe noodrem).
2. Server: `cp tempo_logica.py.bak-curve tempo_logica.py` + restart `jordy-motor`.
3. Dashboard: `git revert` van de betreffende commit.
