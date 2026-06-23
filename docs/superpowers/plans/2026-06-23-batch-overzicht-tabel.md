# Batch-overzicht als één tabel — Implementatieplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** De "📊 Batch Rapportage"-sectie van het dashboard tonen als één tabel met alle batches tegelijk: status aan/uit per regel (dropdown), plus totaal, afgehandeld, open, gebelde tijd, sales en conversie — met één periodekiezer boven de tabel.

**Architecture:** De bestaande Postgres-RPC `batches_overzicht` wordt vervangen door een versie die periode-parameters accepteert en alle rapportagecijfers in één query teruggeeft (i.p.v. ~6 telvragen per batch). Het dashboard rendert die als `st.data_editor` met een bewerkbare Status-kolom; statuswijzigingen schrijven naar `config.paused_batches`. Reset/verwijderen blijven als apart blokje onder de tabel.

**Tech Stack:** Streamlit, pandas, supabase-py, Postgres (Supabase RPC).

## Global Constraints

- Doelbestand: `dashboard.py` in repo `jordy-dashboard` (aparte repo → Streamlit Cloud). Raakt de live belserver NIET.
- ⚠️ **Deploy-volgorde verplicht:** Harun draait eerst de nieuwe SQL-functie in Supabase (zelfbouw-project `ckpoxeoqbmptbwjgypmb`). Pas daarna mag de dashboard-code naar `main` (Streamlit auto-deploy). Anders crasht het dashboard op een onbekende functie.
- ⚠️ NOOIT naar Supabase-project `yuprgyomjxtrbeqnlqyr` schrijven (productie Vapi).
- Tijden in `ended_at`/`duration` zijn UTC in de DB; periodegrenzen als `van 00:00:00` .. `tot 23:59:59`.
- Streamlit-UI is niet pytest-baar: verifiëren met `python3 -m py_compile dashboard.py` + de app lokaal draaien (`streamlit run dashboard.py`) + visuele check.
- Geen wijzigingen aan motor/agent/dialer. Alleen `dashboard.py` + de SQL-functie.

## File Structure

- `dashboard.py` (modify) — sectie "📊 Batch Rapportage" (nu regels ~710-901), data-functies (`cached_batches_overzicht` ~233-237, `cached_batch_stats` ~239-278), en een nieuwe formatteer-helper bij `_fmt_duur` (~520).
- SQL-functie `batches_overzicht(timestamptz, timestamptz)` in Supabase (draait Harun handmatig; tekst staat in Task 1).

---

### Task 1: Nieuwe SQL-functie `batches_overzicht` (Harun draait dit in Supabase)

Dit is een SQL-wijziging. **De agent schrijft géén code in deze task** — alleen de SQL aanleveren en Harun bevestigen laten dat hij draait. Pas daarna verder.

**Files:**
- Geen bestand in de repo. SQL wordt in de Supabase SQL-editor van project `ckpoxeoqbmptbwjgypmb` gedraaid.

**Interfaces:**
- Produces: RPC `batches_overzicht(van timestamptz, tot timestamptz)` die rijen teruggeeft met kolommen: `batch_id text`, `totaal bigint`, `te_bellen bigint`, `afgehandeld bigint`, `sales bigint`, `gebelde_tijd_sec bigint`.

- [ ] **Stap 1: Lever Harun deze SQL aan**

```sql
-- LET OP: de bestaande no-arg functie batches_overzicht() NIET weggooien.
-- Het nu live dashboard roept die nog aan; weggooien breekt productie tot de
-- nieuwe code is gepusht. De nieuwe variant heeft 2 parameters en bestaat
-- náást de oude (Postgres overload op argumentaantal). We droppen alleen de
-- 2-arg variant, voor het geval je dit script opnieuw draait.
drop function if exists batches_overzicht(timestamptz, timestamptz);

create or replace function batches_overzicht(van timestamptz, tot timestamptz)
returns table (
  batch_id          text,
  totaal            bigint,
  te_bellen         bigint,
  afgehandeld       bigint,
  sales             bigint,
  gebelde_tijd_sec  bigint
)
language sql
stable
as $$
  select
    coalesce(batch_id, 'oude_import')                                          as batch_id,
    count(*)                                                                    as totaal,
    count(*) filter (where status = 'new')                                      as te_bellen,
    count(*) filter (where ended_at >= van and ended_at <= tot)                 as afgehandeld,
    count(*) filter (where result = 'SUCCES'
                       and ended_at >= van and ended_at <= tot)                 as sales,
    coalesce(sum(duration) filter (where ended_at >= van and ended_at <= tot), 0)::bigint
                                                                                as gebelde_tijd_sec
  from leads
  group by coalesce(batch_id, 'oude_import');
$$;
```

Toelichting voor Harun (in gewone taal): `totaal` en `te_bellen` gaan over de huidige stand van de batch (niet periode-gebonden), de rest (`afgehandeld`, `sales`, `gebelde_tijd_sec`) telt alleen gesprekken met een `ended_at` binnen de gekozen periode. `coalesce(batch_id,'oude_import')` zorgt dat oude leads zonder batchnaam onder `oude_import` vallen.

- [ ] **Stap 2: Harun draait de SQL in de Supabase SQL-editor en bevestigt dat hij zonder fout uitvoert**

- [ ] **Stap 3: Verifieer de functie op de server**

Run (op de server, via de server-Python):
```bash
ssh -i ~/.ssh/leaseweb_jordy -o IdentitiesOnly=yes root@5.79.88.41 \
"/root/livekit-agent/venv/bin/python - <<'PY'
from dotenv import load_dotenv; load_dotenv('/root/livekit-agent/.env')
import os; from supabase import create_client
sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY'])
r = sb.rpc('batches_overzicht', {'van':'2020-01-01 00:00:00','tot':'2030-01-01 23:59:59'}).execute()
print(len(r.data), 'batches'); print(r.data[0] if r.data else 'leeg')
PY"
```
Expected: een aantal batches > 0, en de eerste rij bevat de keys `batch_id, totaal, te_bellen, afgehandeld, sales, gebelde_tijd_sec`.

- [ ] **Stap 4: Geen commit** (geen repo-wijziging in deze task).

---

### Task 2: Dashboard data-laag aanpassen

**Files:**
- Modify: `dashboard.py` — `cached_batches_overzicht` (~233-237), verwijder `cached_batch_stats` (~239-278), voeg helper `_fmt_duur_lang` toe naast `_fmt_duur` (~520).

**Interfaces:**
- Consumes: RPC uit Task 1.
- Produces:
  - `cached_batches_overzicht(van_iso, tot_iso) -> list[dict]` met per batch de keys `batch_id, totaal, te_bellen, afgehandeld, sales, gebelde_tijd_sec`.
  - `_fmt_duur_lang(sec) -> str` die seconden formatteert als `"18u 04m"`.

- [ ] **Stap 1: Vervang `cached_batches_overzicht` zodat hij periode-parameters doorgeeft**

Vervang de bestaande functie (~233-237) door:
```python
@st.cache_data(ttl=15, show_spinner=False)
def cached_batches_overzicht(van_iso, tot_iso):
    # Server-side aggregatie via Postgres RPC — alle batchcijfers in één query,
    # voor de gekozen periode (van/tot zijn datum-ISO, bv. "2026-06-23").
    res = supabase.rpc('batches_overzicht', {
        "van": f"{van_iso} 00:00:00",
        "tot": f"{tot_iso} 23:59:59",
    }).execute()
    return res.data or []
```

- [ ] **Stap 2: Verwijder `cached_batch_stats`**

Verwijder de volledige functie `cached_batch_stats(batch_id, van_iso, tot_iso)` (~239-278). Die wordt niet meer gebruikt na Task 3.

- [ ] **Stap 3: Voeg `_fmt_duur_lang` toe naast `_fmt_duur`**

Voeg direct ná de bestaande `_fmt_duur` (~520) toe:
```python
def _fmt_duur_lang(sec):
    """Totale belduur in seconden -> 'Xu YYm' (bv. 18u 04m)."""
    sec = int(sec or 0)
    uren, minuten = sec // 3600, (sec % 3600) // 60
    return f"{uren}u {minuten:02d}m"
```

- [ ] **Stap 4: Syntax-check**

Run: `python3 -m py_compile dashboard.py`
Expected: geen output (slaagt). Let op: de app kán nu nog niet draaien tot Task 3 de aanroep van de oude `cached_batch_stats`/`cached_batches_overzicht()` vervangt — dat is verwacht. Niet committen vóór Task 3 klaar is.

- [ ] **Stap 5: Geen aparte commit** — Task 2 en Task 3 raken dezelfde sectie en worden samen gecommit aan het eind van Task 3.

---

### Task 3: Batch-tabel renderen + status-dropdown + reset/verwijderen eronder

Dit is de kern: vervang het hele blok binnen `with st.expander("📊 Batch Rapportage", ...)` (~711-901) door de tabelweergave. Eén samenhangende deliverable; te verifiëren door de app te draaien.

**Files:**
- Modify: `dashboard.py` — het volledige blok onder `with st.expander("📊 Batch Rapportage", expanded=False):` (~711-901).

**Interfaces:**
- Consumes: `cached_batches_overzicht(van_iso, tot_iso)`, `_fmt_duur_lang`, `cached_config`, `GEEN_GEHOOR_REDENEN`, `_nl_tijd` (allemaal bestaand).

- [ ] **Stap 1: Vervang het volledige expander-blok**

Vervang alles vanaf `with st.expander("📊 Batch Rapportage", expanded=False):` tot en met het einde van dat blok (de huidige `else: st.info("Vink eerst ...")` op ~901) door:

```python
with st.expander("📊 Batch Rapportage", expanded=False):
    vandaag_d = date.today()

    # --- Periodekiezer (werkt op de hele tabel) ---
    periode = st.selectbox(
        "Periode",
        ["Vandaag", "Laatste 7 dagen", "Laatste 30 dagen", "Hele looptijd"],
        index=3,
        key="batch_periode",
    )
    if periode == "Vandaag":
        van_d, tot_d = vandaag_d, vandaag_d
    elif periode == "Laatste 7 dagen":
        van_d, tot_d = vandaag_d - pd.Timedelta(days=6), vandaag_d
    elif periode == "Laatste 30 dagen":
        van_d, tot_d = vandaag_d - pd.Timedelta(days=29), vandaag_d
    else:  # Hele looptijd
        van_d, tot_d = date(2020, 1, 1), vandaag_d
    if isinstance(van_d, pd.Timestamp): van_d = van_d.date()
    if isinstance(tot_d, pd.Timestamp): tot_d = tot_d.date()

    try:
        batches_data = cached_batches_overzicht(van_d.isoformat(), tot_d.isoformat())
    except Exception as e:
        st.error(f"Kan batches niet ophalen: {e}. Heb je de nieuwe RPC-functie "
                 "'batches_overzicht(van, tot)' al in Supabase gedraaid?")
        batches_data = []

    if not batches_data:
        st.info("Nog geen leads in de database.")
    else:
        # Gepauzeerde batches (dialer belt deze NIET). Lijst staat in config.
        try:
            paused_list = json.loads(cached_config("paused_batches", "[]") or "[]")
        except Exception:
            paused_list = []

        # Reset-historie per batch (geen-gehoor -> wachtrij), JSON-dict in config.
        try:
            reset_history = json.loads(cached_config("reset_history", "{}") or "{}")
            if not isinstance(reset_history, dict):
                reset_history = {}
        except Exception:
            reset_history = {}

        # Sorteer: Actief eerst, daarbinnen nieuwste boven, oude_import onderaan.
        # Stabiel sorteren: eerst op batch_id aflopend (nieuwste boven), daarna
        # op (inactief, oude_import) zodat die als groep zakken maar de
        # batch_id-volgorde binnen elke groep bewaard blijft.
        rijen = sorted(batches_data, key=lambda b: b["batch_id"], reverse=True)
        rijen = sorted(rijen, key=lambda b: (
            b["batch_id"] in paused_list,      # Actief (False) eerst
            b["batch_id"] == "oude_import",    # oude_import onderaan
        ))

        # Bouw de tabel-data.
        tabel = []
        for b in rijen:
            bid = b["batch_id"]
            afgehandeld = int(b.get("afgehandeld", 0))
            sales = int(b.get("sales", 0))
            conv = (sales / afgehandeld * 100) if afgehandeld else 0.0
            tabel.append({
                "Batch": bid,
                "Status": "Inactief" if bid in paused_list else "Actief",
                "Totaal": int(b.get("totaal", 0)),
                "Afgehandeld": afgehandeld,
                "Open": int(b.get("te_bellen", 0)),
                "Gebelde tijd": _fmt_duur_lang(b.get("gebelde_tijd_sec", 0)),
                "Sales": sales,
                "Conversie": f"{conv:.1f}%".replace(".", ","),
            })
        df = pd.DataFrame(tabel)

        st.caption("Klik op een kolomkop om te sorteren. Wijzig **Status** om een "
                   "batch direct aan/uit te zetten voor de dialer.")

        bewerkt = st.data_editor(
            df,
            hide_index=True,
            use_container_width=True,
            key="batch_tabel",
            column_config={
                "Status": st.column_config.SelectboxColumn(
                    "Status", options=["Actief", "Inactief"], required=True),
                "Batch": st.column_config.TextColumn("Batch", disabled=True),
                "Totaal": st.column_config.NumberColumn("Totaal", disabled=True),
                "Afgehandeld": st.column_config.NumberColumn("Afgehandeld", disabled=True),
                "Open": st.column_config.NumberColumn("Open", disabled=True),
                "Gebelde tijd": st.column_config.TextColumn("Gebelde tijd", disabled=True),
                "Sales": st.column_config.NumberColumn("Sales", disabled=True),
                "Conversie": st.column_config.TextColumn("Conversie", disabled=True),
            },
        )

        # --- Statuswijzigingen verwerken ---
        nieuwe_paused = set(paused_list)
        gewijzigd = False
        for _, rij in bewerkt.iterrows():
            bid = rij["Batch"]
            wil_inactief = (rij["Status"] == "Inactief")
            nu_inactief = (bid in nieuwe_paused)
            if wil_inactief and not nu_inactief:
                nieuwe_paused.add(bid); gewijzigd = True
            elif not wil_inactief and nu_inactief:
                nieuwe_paused.discard(bid); gewijzigd = True

        if gewijzigd:
            try:
                supabase.table('config').upsert(
                    {"key": "paused_batches", "value": json.dumps(sorted(nieuwe_paused))}
                ).execute()
                st.cache_data.clear()
                st.success("✅ Status bijgewerkt.")
                time.sleep(0.8); st.rerun()
            except Exception as e:
                st.error(f"Fout bij status wijzigen: {e}")

        st.markdown("&nbsp;", unsafe_allow_html=True)

        # --- Acties per batch (onomkeerbaar): reset / verwijderen ---
        st.markdown("##### ⚙️ Acties per batch")
        batch_ids = [b["batch_id"] for b in rijen]
        akb = st.selectbox("Kies batch voor actie", batch_ids, key="actie_batch")

        hist = reset_history.get(akb, [])
        if hist:
            laatste = hist[-1]
            st.caption(
                f"♻️ Laatste reset: **{_nl_tijd(laatste.get('ts'))}** "
                f"({laatste.get('leads', 0)} leads) · in totaal **{len(hist)}× gereset**"
            )
        else:
            st.caption("♻️ Nog niet gereset")

        col_r, col_d = st.columns(2)

        if col_r.button("♻️ Reset Geen Gehoor", key=f"reset_{akb}"):
            try:
                res = supabase.table('leads').update({"status": "new", "result": None}) \
                    .eq("batch_id", akb).in_("ended_reason", GEEN_GEHOOR_REDENEN) \
                    .neq("sip_status", "404").execute()
                aantal = len(res.data) if res.data else 0
                hist.append({"ts": datetime.now(timezone.utc).isoformat(), "leads": aantal})
                reset_history[akb] = hist
                supabase.table('config').upsert(
                    {"key": "reset_history", "value": json.dumps(reset_history)}).execute()
                st.cache_data.clear()
                st.success(f"✅ {aantal} leads in '{akb}' staan weer in de wachtrij.")
                time.sleep(1.5); st.rerun()
            except Exception as e:
                st.error(f"Fout bij reset: {e}")

        bevestig = col_d.checkbox("Bevestig verwijderen", key=f"conf_{akb}")
        if col_d.button("🗑️ Verwijder Batch", key=f"del_{akb}"):
            if bevestig:
                try:
                    supabase.table('leads').delete().eq("batch_id", akb).execute()
                    st.cache_data.clear()
                    st.warning(f"🗑️ Batch '{akb}' is volledig verwijderd.")
                    time.sleep(1.5); st.rerun()
                except Exception as e:
                    st.error(f"Fout bij verwijderen: {e}")
            else:
                st.info("Vink eerst 'Bevestig verwijderen' aan.")
```

- [ ] **Stap 2: Syntax-check**

Run: `python3 -m py_compile dashboard.py`
Expected: geen output (slaagt).

- [ ] **Stap 3: App lokaal draaien en visueel verifiëren**

Run: `streamlit run dashboard.py`
Controleer in de browser onder "📊 Batch Rapportage":
- Eén tabel met álle batches, kolommen: Batch, Status, Totaal, Afgehandeld, Open, Gebelde tijd, Sales, Conversie.
- Actieve batches staan boven, `oude_import` onderaan.
- Periodekiezer wisselt de cijfers (Vandaag vs Hele looptijd).
- Status-dropdown in een regel op `Inactief` zetten → na rerun staat die batch in `paused_batches` (en blijft `Inactief`); terug op `Actief` → eruit.
- Onder de tabel: batch kiezen → Reset / Verwijderen werken zoals voorheen.

- [ ] **Stap 4: Vergelijk een batch met de oude cijfers**

Kies één batch, periode "Hele looptijd", en vergelijk `Sales` en `Afgehandeld` met wat de oude per-batch rapportage gaf (uit git-historie of geheugen). Wijken ze af, controleer de RPC-filters uit Task 1.

- [ ] **Stap 5: Commit**

```bash
git add dashboard.py docs/superpowers/plans/2026-06-23-batch-overzicht-tabel.md
git commit -m "Batch Rapportage: één tabel met alle batches + status-dropdown per regel"
```

---

### Task 4: Naar productie (Streamlit Cloud)

**Files:** geen codewijziging — alleen uitrol.

- [ ] **Stap 1: Controleer dat Task 1 (SQL) écht in Supabase staat** (anders crasht de live app). Verificatie-commando uit Task 1 Stap 3 nogmaals draaien.

- [ ] **Stap 2: Push naar `main`**

```bash
git push origin main
```

- [ ] **Stap 3: Wacht ~1-2 min op auto-deploy; open de Streamlit-app.** Soms "Reboot app" nodig om nieuwe code te laden. Controleer dezelfde punten als Task 3 Stap 3 in productie.

- [ ] **Stap 4: Werk het geheugen bij**

Werk `~/.claude/projects/-Users-haruntekin-BotAgent/memory/` bij (nieuw bestand of bestaande dashboard-memory) dat de Batch Rapportage nu één tabel is met status-dropdown per regel + periodekiezer, RPC `batches_overzicht(van,tot)` uitgebreid. Pointer in MEMORY.md.

---

## Self-Review

**Spec coverage:**
- Eén tabel met alle batches → Task 3. ✓
- Sorteren op actief/inactief → standaardsortering Actief eerst + klikbare kolomkoppen, Task 3. ✓
- Status-dropdown per regel zet aan/uit → Task 3 (`paused_batches`). ✓
- Kolommen Totaal + Open(nog te bellen) → Task 1 (RPC) + Task 3. ✓
- Rapportagekolommen actief/totaal/afgehandeld/gebelde tijd/sales/conversie/open → Task 1 + Task 3. ✓
- Conversie = Sales ÷ Afgehandeld → Task 3. ✓
- Periodekiezer over hele tabel → Task 3. ✓
- Snelheid (één query i.p.v. ~6 per batch) → Task 1 RPC. ✓
- Reset/Verwijderen behouden onder tabel → Task 3. ✓
- Deploy-volgorde (SQL eerst) → Global Constraints + Task 1 + Task 4. ✓

**Placeholder scan:** geen TBD/TODO; alle code-stappen bevatten volledige, definitieve code.

**Type consistency:** RPC-keys (`totaal, te_bellen, afgehandeld, sales, gebelde_tijd_sec`) consistent tussen Task 1 (productie) en Task 2/3 (consumptie). `cached_batches_overzicht(van_iso, tot_iso)` signatuur consistent tussen Task 2 (definitie) en Task 3 (aanroep). `_fmt_duur_lang` consistent gedefinieerd (Task 2) en gebruikt (Task 3).
