import streamlit as st
import pandas as pd
import time
from supabase import create_client
import io
from datetime import datetime, date
import json
import re

# --- 1. CONFIGURATIE ---
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
except:
    st.error("Geen secrets gevonden. Voeg ze toe in Streamlit Cloud instellingen.")
    st.stop()

# Verbinden met database
@st.cache_resource
def init_connection():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

try:
    supabase = init_connection()
except:
    st.error("Kan geen verbinding maken met Supabase. Check je URL en KEY.")
    st.stop()

st.set_page_config(layout="centered", page_title="Jordy Dialer", page_icon="📞")

# --- 2. DESIGN & CSS ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }

    [data-testid="stAppViewContainer"] { background-color: #f9fafb; }
    .block-container { padding-top: 2rem; padding-bottom: 3rem; max-width: 1100px; }

    /* Page header */
    .app-header {
        display: flex; align-items: center; justify-content: space-between;
        margin-bottom: 28px; padding-bottom: 18px; border-bottom: 1px solid #e5e7eb;
    }
    .app-title { font-size: 22px; font-weight: 700; color: #111827; margin: 0; }
    .app-subtitle { font-size: 13px; color: #6b7280; margin: 2px 0 0 0; }

    /* Status pill */
    .status-pill {
        display: inline-flex; align-items: center; gap: 8px;
        padding: 6px 14px; border-radius: 999px;
        font-size: 13px; font-weight: 600; letter-spacing: 0.2px;
    }
    .pill-active  { background: #d1fae5; color: #065f46; }
    .pill-stopped { background: #fee2e2; color: #991b1b; }
    .pill-warning { background: #fef3c7; color: #92400e; }
    .status-dot { width: 8px; height: 8px; border-radius: 50%; }
    .dot-active  { background: #10b981; box-shadow: 0 0 0 3px rgba(16,185,129,0.15); }
    .dot-stopped { background: #ef4444; box-shadow: 0 0 0 3px rgba(239,68,68,0.15); }
    .dot-warning { background: #f59e0b; box-shadow: 0 0 0 3px rgba(245,158,11,0.15); }

    /* KPI cards */
    [data-testid="metric-container"] {
        background: white;
        border: 1px solid #e5e7eb;
        border-radius: 12px;
        padding: 20px 22px;
        box-shadow: 0 1px 2px rgba(0,0,0,0.03);
    }
    [data-testid="metric-container"] label {
        color: #6b7280 !important;
        font-size: 12px !important;
        font-weight: 500 !important;
        text-transform: uppercase;
        letter-spacing: 0.6px;
    }
    [data-testid="metric-container"] [data-testid="stMetricValue"] {
        font-size: 30px !important;
        font-weight: 700 !important;
        color: #111827 !important;
    }

    /* Buttons */
    .stButton > button {
        width: 100%; height: 42px;
        border-radius: 8px; font-weight: 600; font-size: 14px;
        border: 1px solid #e5e7eb; background: white; color: #374151;
        transition: all 0.15s ease;
    }
    .stButton > button:hover {
        border-color: #d1d5db; background: #f3f4f6;
    }
    .stButton > button[kind="primary"] {
        background: #2563eb; color: white; border: 1px solid #2563eb;
    }
    .stButton > button[kind="primary"]:hover {
        background: #1d4ed8; border-color: #1d4ed8;
    }

    /* Section headers */
    h1, h2, h3 { color: #111827; font-weight: 600; }
    [data-testid="stMarkdownContainer"] h2 { font-size: 18px; margin-top: 8px; }
    [data-testid="stMarkdownContainer"] h3 { font-size: 16px; }

    /* Expanders → cards */
    [data-testid="stExpander"] {
        border: 1px solid #e5e7eb !important;
        border-radius: 10px !important;
        background: white;
        margin-bottom: 8px;
        box-shadow: 0 1px 2px rgba(0,0,0,0.02);
    }
    [data-testid="stExpander"] summary { font-weight: 500; }

    /* Inputs strakker */
    [data-baseweb="input"] > div, [data-baseweb="select"] > div {
        border-radius: 8px;
    }

    /* Dividers subtieler */
    hr { margin: 28px 0; border: none; border-top: 1px solid #e5e7eb; }

    /* File uploader card */
    [data-testid="stFileUploader"] section {
        border-radius: 10px; border: 1px dashed #d1d5db; background: #f9fafb;
    }
</style>
""", unsafe_allow_html=True)

# --- 3. HELPER FUNCTIES ---
def normalize_number(raw_num):
    s = str(raw_num)
    digits = "".join(filter(str.isdigit, s))
    if digits.startswith("0031"): digits = digits[4:]
    if digits.startswith("31"):   digits = digits[2:]
    if digits.startswith("0"):    digits = digits[1:]
    return f"+31{digits}" if len(digits) == 9 else None

def fetch_all(table, columns, page_size=1000):
    # Supabase geeft default max 1000 rows terug — paginate om alles op te halen
    rows = []
    offset = 0
    while True:
        res = supabase.table(table).select(columns).range(offset, offset + page_size - 1).execute()
        page = res.data or []
        rows.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    return rows

def existing_phones(table, phones, chunk_size=200):
    # Check welke nummers al in 'table' staan, via gerichte IN-query in chunks
    if not phones:
        return set()
    unique = list({p for p in phones if p})
    found = set()
    for i in range(0, len(unique), chunk_size):
        res = supabase.table(table).select('phone').in_('phone', unique[i:i+chunk_size]).execute()
        found.update(row['phone'] for row in (res.data or []))
    return found

GEEN_GEHOOR_REDENEN = ["customer-did-not-answer", "no-answer-transfer", "voicemail", "silence-timed-out"]

@st.cache_data(ttl=15, show_spinner=False)
def cached_batches_overzicht():
    # Server-side aggregatie via Postgres RPC — stuurt alleen samenvatting, geen 100k rijen
    res = supabase.rpc('batches_overzicht').execute()
    return res.data or []

@st.cache_data(ttl=15, show_spinner=False)
def cached_batch_stats(batch_id, van_iso, tot_iso):
    van_dt = f"{van_iso} 00:00:00"
    tot_dt = f"{tot_iso} 23:59:59"

    def cnt(builder):
        return builder.execute().count or 0

    totaal_gebeld = cnt(supabase.table('leads').select("*", count='exact', head=True)
        .eq('batch_id', batch_id).gte('ended_at', van_dt).lte('ended_at', tot_dt))

    succes = cnt(supabase.table('leads').select("*", count='exact', head=True)
        .eq('batch_id', batch_id).eq('result', 'SUCCES')
        .gte('ended_at', van_dt).lte('ended_at', tot_dt))

    mislukt = cnt(supabase.table('leads').select("*", count='exact', head=True)
        .eq('batch_id', batch_id).eq('result', 'MISLUKT')
        .gte('ended_at', van_dt).lte('ended_at', tot_dt))

    no_answer = cnt(supabase.table('leads').select("*", count='exact', head=True)
        .eq('batch_id', batch_id).in_('ended_reason', GEEN_GEHOOR_REDENEN)
        .gte('ended_at', van_dt).lte('ended_at', tot_dt))

    return {
        "totaal_gebeld": totaal_gebeld,
        "succes": succes,
        "mislukt": mislukt,
        "no_answer": no_answer,
    }

@st.cache_data(ttl=15, show_spinner=False)
def cached_kpi_counts(vandaag):
    succes = supabase.table('leads').select("*", count='exact', head=True) \
        .eq('result', 'SUCCES') \
        .gte('ended_at', f"{vandaag} 00:00:00").lte('ended_at', f"{vandaag} 23:59:59").execute().count
    fail = supabase.table('leads').select("*", count='exact', head=True) \
        .eq('result', 'MISLUKT') \
        .gte('ended_at', f"{vandaag} 00:00:00").lte('ended_at', f"{vandaag} 23:59:59").execute().count
    todo = supabase.table('leads').select("*", count='exact', head=True).eq('status', 'new').execute().count
    return succes, fail, todo

@st.cache_data(ttl=30, show_spinner=False)
def cached_config(key, default=None):
    try:
        res = supabase.table('config').select("value").eq("key", key).execute()
        return res.data[0]['value'] if res.data else default
    except Exception:
        return default

# --- 4. STATUS CONTROLEREN ---
current_status = cached_config("status", "UIT")
motor_heartbeat = cached_config("motor_heartbeat")
bel_api_status = cached_config("system_health", "OK")

# Leeft de motor nog? (hartslag minder dan 3 minuten oud)
motor_alive = False
if motor_heartbeat:
    try:
        hb = datetime.fromisoformat(motor_heartbeat)
        nu = datetime.now(hb.tzinfo) if hb.tzinfo else datetime.now()
        motor_alive = (nu - hb).total_seconds() < 180
    except Exception:
        pass

if current_status == "AAN" and not motor_alive:
    pill_html = '<span class="status-pill pill-stopped"><span class="status-dot dot-stopped"></span>Motor offline</span>'
elif current_status == "AAN" and bel_api_status == "DOWN":
    pill_html = '<span class="status-pill pill-warning"><span class="status-dot dot-warning"></span>Bel-API onbereikbaar</span>'
elif current_status == "AAN":
    pill_html = '<span class="status-pill pill-active"><span class="status-dot dot-active"></span>Systeem actief</span>'
else:
    pill_html = '<span class="status-pill pill-stopped"><span class="status-dot dot-stopped"></span>Systeem gestopt</span>'

st.markdown(f"""
<div class="app-header">
    <div>
        <h1 class="app-title">📞 Jordy Dialer</h1>
        <p class="app-subtitle">Beheer je belcampagnes en monitor de voortgang</p>
    </div>
    {pill_html}
</div>
""", unsafe_allow_html=True)

# Storingsbanner — alleen tonen als het systeem AAN staat maar er iets mis is.
if current_status == "AAN" and not motor_alive:
    st.error(
        "🔴 **Motor/server offline** — geen recente hartslag van de motor "
        "(> 3 min geleden of nooit). Bellen ligt stil. "
        "Controleer de `jordy-motor`-service op de server."
    )
elif current_status == "AAN" and bel_api_status == "DOWN":
    st.warning(
        "🟠 **Bel-API onbereikbaar** — de motor leeft, maar kan de bel-API niet "
        "bereiken (`jordy-api` / `jordy-agent`?). Gesprekken starten mogelijk niet."
    )

# --- 5. KPI TELLERS (VANDAAG) ---
vandaag = date.today().isoformat()
try:
    count_succes, count_fail, count_todo = cached_kpi_counts(vandaag)
except Exception:
    count_succes, count_fail, count_todo = 0, 0, 0

c1, c2, c3 = st.columns(3)
c1.metric("✅ Succes Vandaag", count_succes)
c2.metric("❌ Mislukt Vandaag", count_fail)
c3.metric("⏳ Wachtrij Totaal", count_todo)

# --- 6. BESTURING ---
st.divider()
with st.expander("⚙️ Besturing", expanded=True):
    col_btn1, col_btn2, col_btn3 = st.columns(3)

    if col_btn1.button("▶ START DIALER", type="primary"):
        supabase.table('config').upsert({"key": "status", "value": "AAN"}).execute()
        st.cache_data.clear(); st.rerun()

    if col_btn2.button("⏹ STOP DIALER"):
        supabase.table('config').upsert({"key": "status", "value": "UIT"}).execute()
        st.cache_data.clear(); st.rerun()

    if col_btn3.button("🔄 VERVERS"):
        st.cache_data.clear(); st.rerun()

    # --- SNELHEID ---
    try:
        current_speed = int(cached_config("speed", "20"))
    except Exception:
        current_speed = 20

    st.markdown(f"##### ⚡ Snelheid &nbsp;·&nbsp; <span style='color:#6b7280;font-weight:500'>{current_speed} calls per minuut</span>", unsafe_allow_html=True)
    new_speed = st.slider("snelheid", min_value=10, max_value=100, value=current_speed, step=5, label_visibility="collapsed")

    if new_speed != current_speed:
        supabase.table('config').upsert({"key": "speed", "value": str(new_speed)}).execute()
        st.cache_data.clear()
        st.success(f"Snelheid aangepast naar {new_speed} calls/minuut!")
        time.sleep(1)
        st.rerun()

# --- BATCH RAPPORTAGE ---
with st.expander("📊 Batch Rapportage", expanded=False):
    try:
        batches_data = cached_batches_overzicht()
    except Exception as e:
        st.error(f"Kan batches niet ophalen: {e}. Heb je de RPC functie 'batches_overzicht' al aangemaakt in Supabase?")
        batches_data = []

    if not batches_data:
        st.info("Nog geen leads in de database.")
    else:
        # Nieuwste batches eerst, 'oude_import' onderaan
        overige = sorted([b for b in batches_data if b['batch_id'] != 'oude_import'],
                         key=lambda b: b['batch_id'], reverse=True)
        oude = [b for b in batches_data if b['batch_id'] == 'oude_import']
        geordend = overige + oude

        # --- Filter rij: status + batch ---
        col_f1, col_f2 = st.columns([1, 2])

        filter_keuze = col_f1.selectbox(
            "Status",
            ["🔥 Actief (nog te bellen)", "✅ Inactief (klaar)", "📋 Alle batches"],
            index=0,
        )

        if filter_keuze.startswith("🔥"):
            zichtbaar = [b for b in geordend if int(b['te_bellen']) > 0]
        elif filter_keuze.startswith("✅"):
            zichtbaar = [b for b in geordend if int(b['te_bellen']) == 0]
        else:
            zichtbaar = geordend

        if not zichtbaar:
            col_f2.selectbox("Batch", ["— geen batches in deze filter —"], disabled=True)
            st.info("Geen batches gevonden voor deze filter.")
        else:
            batch_labels = {
                f"📦 {b['batch_id']}  ·  {int(b['totaal']):,} leads".replace(",", "."): b
                for b in zichtbaar
            }
            gekozen_label = col_f2.selectbox(f"Batch ({len(zichtbaar)})", list(batch_labels.keys()))
            gekozen = batch_labels[gekozen_label]
            batch_id = gekozen['batch_id']

            # --- Periode dropdown + optionele datums ---
            col_p1, col_p2, col_p3 = st.columns([1, 1, 1])
            periode = col_p1.selectbox(
                "Periode",
                ["Vandaag", "Laatste 7 dagen", "Laatste 30 dagen", "Hele looptijd", "Aangepast"],
                index=3,
            )

            vandaag_d = date.today()
            if periode == "Vandaag":
                van_d, tot_d = vandaag_d, vandaag_d
                col_p2.text_input("Van", value=van_d.isoformat(), disabled=True, key=f"van_disp_{batch_id}")
                col_p3.text_input("Tot", value=tot_d.isoformat(), disabled=True, key=f"tot_disp_{batch_id}")
            elif periode == "Laatste 7 dagen":
                van_d, tot_d = vandaag_d - pd.Timedelta(days=6), vandaag_d
                col_p2.text_input("Van", value=van_d.isoformat(), disabled=True, key=f"van_disp_{batch_id}")
                col_p3.text_input("Tot", value=tot_d.isoformat(), disabled=True, key=f"tot_disp_{batch_id}")
            elif periode == "Laatste 30 dagen":
                van_d, tot_d = vandaag_d - pd.Timedelta(days=29), vandaag_d
                col_p2.text_input("Van", value=van_d.isoformat(), disabled=True, key=f"van_disp_{batch_id}")
                col_p3.text_input("Tot", value=tot_d.isoformat(), disabled=True, key=f"tot_disp_{batch_id}")
            elif periode == "Hele looptijd":
                van_d, tot_d = date(2020, 1, 1), vandaag_d
                col_p2.text_input("Van", value="—", disabled=True, key=f"van_disp_{batch_id}")
                col_p3.text_input("Tot", value=vandaag_d.isoformat(), disabled=True, key=f"tot_disp_{batch_id}")
            else:  # Aangepast
                van_d = col_p2.date_input("Van", value=vandaag_d - pd.Timedelta(days=29), key=f"van_{batch_id}")
                tot_d = col_p3.date_input("Tot", value=vandaag_d, key=f"tot_{batch_id}")

            if isinstance(van_d, pd.Timestamp): van_d = van_d.date()
            if isinstance(tot_d, pd.Timestamp): tot_d = tot_d.date()

            # --- Rapportage ---
            try:
                stats = cached_batch_stats(batch_id, van_d.isoformat(), tot_d.isoformat())
            except Exception as e:
                st.error(f"Kan rapportage niet ophalen: {e}")
                stats = None

            totaal = int(gekozen['totaal'])
            wachtrij = int(gekozen['te_bellen'])

            st.markdown(f"##### 📦 {batch_id}")

            m1, m2, m3 = st.columns(3)
            m1.metric("📞 Totaal in batch", f"{totaal:,}".replace(",", "."))
            m2.metric("⏳ Nog te bellen", f"{wachtrij:,}".replace(",", "."))
            m3.metric("📅 Gebeld in periode", f"{(stats['totaal_gebeld'] if stats else 0):,}".replace(",", "."))

            if stats:
                m4, m5, m6 = st.columns(3)
                m4.metric("✅ Succes", f"{stats['succes']:,}".replace(",", "."))
                m5.metric("📵 Geen gehoor", f"{stats['no_answer']:,}".replace(",", "."))
                m6.metric("❌ Mislukt", f"{stats['mislukt']:,}".replace(",", "."))

            st.markdown("&nbsp;", unsafe_allow_html=True)

            # --- Acties ---
            col_r, col_d = st.columns(2)

            if col_r.button("♻️ Reset Geen Gehoor", key=f"reset_{batch_id}"):
                try:
                    res = supabase.table('leads').update({"status": "new", "result": None}) \
                        .eq("batch_id", batch_id).in_("ended_reason", GEEN_GEHOOR_REDENEN).execute()
                    aantal = len(res.data) if res.data else 0
                    st.cache_data.clear()
                    st.success(f"✅ {aantal} leads in '{batch_id}' staan weer in de wachtrij.")
                    time.sleep(1.5); st.rerun()
                except Exception as e:
                    st.error(f"Fout bij reset: {e}")

            bevestig = col_d.checkbox("Bevestig verwijderen", key=f"conf_{batch_id}")
            if col_d.button("🗑️ Verwijder Batch", key=f"del_{batch_id}"):
                if bevestig:
                    try:
                        supabase.table('leads').delete().eq("batch_id", batch_id).execute()
                        st.cache_data.clear()
                        st.warning(f"🗑️ Batch '{batch_id}' is volledig verwijderd.")
                        time.sleep(1.5); st.rerun()
                    except Exception as e:
                        st.error(f"Fout bij verwijderen: {e}")
                else:
                    st.info("Vink eerst 'Bevestig verwijderen' aan.")

# --- 9. IMPORT MODULE ---
with st.expander("📂 Leads & Blacklist Importeren", expanded=False):
    import_doel = st.radio("Waar wil je dit bestand importeren?", ["📞 Leads voor Dialer", "⛔ Nummers voor Blacklist"])
    uploaded_file = st.file_uploader(f"Upload Excel/CSV voor {import_doel}", type=['xlsx', 'csv'])

    if uploaded_file:
        try:
            if uploaded_file.name.endswith('.csv'):
                try: df = pd.read_csv(uploaded_file, dtype=str, sep=None, engine='python')
                except: df = pd.read_csv(uploaded_file, dtype=str, sep=';')
            else:
                df = pd.read_excel(uploaded_file, dtype=str)

            df = df.fillna("")

            cols = df.columns.tolist()
            phone_col = st.selectbox("Welke kolom is het telefoonnummer?", ["Kies..."] + cols)

            name_col = None
            if import_doel == "📞 Leads voor Dialer":
                name_col = st.selectbox("Welke kolom is de naam?", ["Kies..."] + cols)

            if st.button(f"🚀 Start Import naar {import_doel}") and phone_col != "Kies...":
                progress = st.progress(0)
                status_text = st.empty()

                if import_doel == "📞 Leads voor Dialer":
                    # Batch-naam: bestandsnaam (zonder extensie, opgeschoond) + datum/tijd
                    bestandsnaam = re.sub(r'\.[^.]+$', '', uploaded_file.name)
                    bestandsnaam = re.sub(r'[^\w\-]', '_', bestandsnaam).strip('_').lower() or "import"
                    batch_id = f"{bestandsnaam}_{datetime.now().strftime('%Y-%m-%d_%H%M')}"

                    # Pass 1: normaliseer alle nummers één keer
                    clean_phones = [normalize_number(row[phone_col]) for _, row in df.iterrows()]

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

                    if to_upload:
                        # Upload in chunks van 1000
                        for i in range(0, len(to_upload), 1000):
                            try:
                                supabase.table('leads').upsert(to_upload[i:i+1000], on_conflict='phone', ignore_duplicates=True).execute()
                            except Exception as e:
                                print(f"Batch warning: {e}")

                    st.success(f"✅ Import voltooid! Batch: **{batch_id}**")
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("🆕 Toegevoegd", c_new)
                    c2.metric("🔄 Dubbel", c_dup)
                    c3.metric("⛔ Blacklist", c_black)
                    c4.metric("⚠️ Ongeldig", c_inv)

                else:
                    clean_phones = [normalize_number(row[phone_col]) for _, row in df.iterrows()]
                    existing_black = existing_phones('blacklist', [p for p in clean_phones if p])

                    to_blacklist = []
                    c_new, c_dup, c_inv = 0, 0, 0

                    for i, clean in enumerate(clean_phones):
                        if not clean:
                            c_inv += 1
                        elif clean in existing_black:
                            c_dup += 1
                        else:
                            to_blacklist.append({"phone": clean})
                            existing_black.add(clean)
                            c_new += 1
                        if i % 100 == 0: progress.progress(min(i / len(df), 1.0))

                    if to_blacklist:
                        for i in range(0, len(to_blacklist), 1000):
                            try:
                                supabase.table('blacklist').upsert(to_blacklist, on_conflict='phone', ignore_duplicates=True).execute()
                            except: pass

                    st.success("✅ Blacklist bijgewerkt!")
                    c1, c2, c3 = st.columns(3)
                    c1.metric("⛔ Nieuw op Blacklist", c_new)
                    c2.metric("🔄 Stond er al op", c_dup)
                    c3.metric("⚠️ Ongeldig", c_inv)

                progress.progress(1.0)
                st.cache_data.clear()
                time.sleep(2)
                st.rerun()

        except Exception as e:
            st.error(f"Fout bij lezen bestand: {e}")

# --- 10. EXPORT ---
with st.expander("📥 Export Succesvolle Leads", expanded=False):
    col_d1, col_d2 = st.columns(2)
    start_d = col_d1.date_input("Van", value=date.today())
    end_d = col_d2.date_input("Tot", value=date.today())

    if st.button("Download Excel"):
        try:
            res = supabase.table('leads').select("*").eq("result", "SUCCES") \
                .gte("ended_at", str(start_d)).lte("ended_at", str(end_d) + " 23:59:59").execute()

            df_exp = pd.DataFrame(res.data)

            if not df_exp.empty:
                if 'original_data' in df_exp.columns:
                    json_data = pd.json_normalize(df_exp['original_data'])
                    df_raw = pd.concat([df_exp[['phone', 'result', 'duration', 'recording', 'ended_at']], json_data], axis=1)
                else:
                    df_raw = df_exp

                COLUMN_VARIANTS = {
                    "phone":                 ["phone", "telefoon", "telefoonnummer", "tel", "mobiel", "gsm"],
                    "sex":                   ["sex", "geslacht", "gender", "geslacht_mv", "mv", "m_v"],
                    "initialen":             ["initialen", "initials", "voorletters"],
                    "naam":                  ["naam", "voornaam", "first_name", "firstname", "name", "roepnaam"],
                    "tussenvoegsel":         ["tussenvoegsel", "middle_name", "middlename", "tussen"],
                    "achternaam":            ["achternaam", "last_name", "lastname", "surname", "familienaam"],
                    "straat":                ["straat", "adres", "address", "street", "straatnaam"],
                    "huisnummer":            ["huisnummer", "huisnr", "house_number", "housenumber", "nr", "nummer"],
                    "huisnummer_toevoeging": ["huisnummer_toevoeging", "toevoeging", "huisnr_toevoeging", "addition", "huisnummertoevoeging"],
                    "postcode":              ["postcode", "zipcode", "postal_code", "zip"],
                    "stad":                  ["stad", "woonplaats", "plaats", "city"],
                    "email":                 ["email", "e-mail", "emailadres", "e-mailadres", "mail", "mailadres", "e_mail"],
                    "iban":                  ["iban", "iban_nummer", "iban_number", "bankrekening", "rekeningnummer"],
                    "geboortedatum":         ["geboortedatum", "geboorte", "birthdate", "birth_date", "dob", "date_of_birth"],
                }
                EXPORT_ORDER = ["enquete", "phone", "sex", "initialen", "naam", "tussenvoegsel",
                                "achternaam", "straat", "huisnummer", "huisnummer_toevoeging",
                                "postcode", "stad", "email", "iban", "geboortedatum", "enquete_datum",
                                "original_data"]

                # Strip alle niet-alfanumerieke tekens zodat 'E-mailadres', 'e_mailadres'
                # en 'emailadres' allemaal naar 'emailadres' normaliseren.
                def _norm(s):
                    return re.sub(r'[^a-z0-9]', '', str(s).lower())

                norm_map = {col: _norm(col) for col in df_raw.columns}
                df_final = pd.DataFrame(index=df_raw.index)
                for canonical, variants in COLUMN_VARIANTS.items():
                    variant_set = {_norm(v) for v in variants}
                    matching = [col for col, n in norm_map.items() if n in variant_set]
                    if matching:
                        series = df_raw[matching].replace("", pd.NA).bfill(axis=1).iloc[:, 0]
                        df_final[canonical] = series.fillna("")
                    else:
                        df_final[canonical] = ""

                df_final.insert(0, "enquete", "telefonische enquete vrije tijd en ontspanning")
                if 'ended_at' in df_raw.columns:
                    df_final['enquete_datum'] = pd.to_datetime(df_raw['ended_at'], errors='coerce').dt.strftime('%d-%m-%Y')

                # Voeg ruwe original_data als JSON-string toe ter controle.
                if 'original_data' in df_exp.columns:
                    df_final['original_data'] = df_exp['original_data'].apply(
                        lambda v: json.dumps(v, ensure_ascii=False) if v is not None else ""
                    )

                df_final = df_final[[c for c in EXPORT_ORDER if c in df_final.columns]]

                # Controle: meld per rij welke verplichte velden leeg zijn gebleven
                # terwijl original_data wel iets bevatte — dat duidt op een mismatch
                # in COLUMN_VARIANTS en moet onderzocht worden.
                check_cols = [c for c in ["sex", "initialen", "naam", "achternaam",
                                           "straat", "huisnummer", "postcode", "stad",
                                           "email", "iban", "geboortedatum"]
                              if c in df_final.columns]
                missing_report = []
                for idx, row in df_final.iterrows():
                    leeg = [c for c in check_cols if not str(row[c]).strip()]
                    if leeg:
                        phone = row.get("phone", "")
                        missing_report.append(f"• {phone}: leeg → {', '.join(leeg)}")
                if missing_report:
                    st.warning("Let op — sommige velden zijn leeg gebleven na mapping. "
                               "Controleer `original_data` in de Excel:\n" + "\n".join(missing_report[:20]))

                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                    df_final.to_excel(writer, index=False)

                st.download_button("⬇️ Download Excel", buffer, f"leads_{start_d}.xlsx", "application/vnd.ms-excel")
            else:
                st.warning("Geen succesvolle leads gevonden.")

        except Exception as e:
            st.error(f"Fout: {e}")

# --- TELEFOONNUMMERS (4 VAKJES) ---
try:
    raw_ids = cached_config("phone_ids")
    saved_list = json.loads(raw_ids) if raw_ids else ["", "", "", ""]
except Exception:
    saved_list = ["", "", "", ""]

try:
    raw_labels = cached_config("phone_labels")
    labels_map = json.loads(raw_labels) if raw_labels else {}
except Exception:
    labels_map = {}

while len(saved_list) < 4: saved_list.append("")
actief_aantal = sum(1 for x in saved_list if x.strip())

with st.expander(f"📞 Uitbel-nummers (caller-ID) — {actief_aantal} actief", expanded=False):
    st.caption("Vul je uitbel-nummers in (internationaal formaat, bv. +31103180648). "
               "De motor wisselt ze om de beurt af. Let op: een nieuw nummer moet eerst "
               "bij CM.com geregistreerd én aan de trunk toegevoegd zijn — geef dat even door.")

    nieuwe_labels = []
    nieuwe_ids = []
    for i in range(4):
        col_lbl, col_id = st.columns([1, 2])
        huidige_id = saved_list[i]
        huidig_label = labels_map.get(huidige_id, "") if huidige_id else ""
        lbl = col_lbl.text_input(f"Label {i+1}", value=huidig_label, key=f"phone_label_{i}",
                                  placeholder="bv. Rotterdam")
        pid = col_id.text_input(f"Telefoonnummer {i+1}", value=huidige_id, key=f"phone_id_{i}",
                                 placeholder="+31103180648")
        nieuwe_labels.append(lbl.strip())
        nieuwe_ids.append(pid.strip())

    if st.button("💾 Opslaan Nummers"):
        new_id_list = [pid for pid in nieuwe_ids if pid]
        new_label_map = {pid: lbl for pid, lbl in zip(nieuwe_ids, nieuwe_labels) if pid and lbl}
        supabase.table('config').upsert({"key": "phone_ids", "value": json.dumps(new_id_list)}).execute()
        supabase.table('config').upsert({"key": "phone_labels", "value": json.dumps(new_label_map)}).execute()
        st.cache_data.clear()
        st.success(f"Opgeslagen! De motor gebruikt nu {len(new_id_list)} nummers.")
        time.sleep(1); st.rerun()
