import streamlit as st
import pandas as pd
import time
import requests
from supabase import create_client
import io
from datetime import datetime, date, timedelta, timezone
import json
import re

# Tijdzone: de database slaat tijden in UTC op; we tonen alles in Nederlandse tijd.
try:
    from zoneinfo import ZoneInfo
    NL_TZ = ZoneInfo("Europe/Amsterdam")
except Exception:
    NL_TZ = None


def _nl_tijd(iso_str, fmt="%Y-%m-%d %H:%M"):
    """Zet een UTC-tijdstempel (ISO-string) om naar Nederlandse tijd voor weergave."""
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(str(iso_str))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if NL_TZ is not None:
            dt = dt.astimezone(NL_TZ)
        return dt.strftime(fmt)
    except Exception:
        return str(iso_str)[:16].replace("T", " ")

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

# --- 1b. WACHTWOORD-SLOT ---
# App mag openbaar (geen Streamlit-login), maar wel achter een eigen wachtwoord.
# Stel APP_PASSWORD in bij de Streamlit-secrets. Niet ingesteld = vrij toegankelijk.
def check_password():
    try:
        juiste = st.secrets["APP_PASSWORD"]
    except Exception:
        juiste = ""
    if not juiste:
        return True
    if st.session_state.get("auth_ok"):
        return True

    def _check():
        st.session_state["auth_ok"] = st.session_state.get("pw_input", "") == juiste

    st.markdown("### 🔒 Jordy Dialer")
    st.text_input("Wachtwoord", type="password", key="pw_input", on_change=_check)
    if st.session_state.get("auth_ok") is False:
        st.error("Onjuist wachtwoord.")
    return False

if not check_password():
    st.stop()

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

GEEN_GEHOOR_REDENEN = ["customer-did-not-answer", "no-answer-transfer", "voicemail", "silence-timed-out", "geen-mens"]
# Échte mens-gesprekken: lijnen waar een mens daadwerkelijk iets zei (dus geen
# voicemail, stille lijn of niet-opgenomen). Voor de luister-filter zodat je
# niet door honderden voicemails hoeft te scrollen.
ECHT_GESPREK_REDENEN = ["assistant-ended-call", "klant-ended-call", "inbound-ended-call"]

# Losse redenen om exact op te filteren in het gesprekken-overzicht. Label -> de
# echte ended_reason-waarde in de database. Zo kan Harun bv. alleen "klant hing
# op" of alleen "geen-mens" bekijken i.p.v. de grove groepen.
REDEN_FILTERS = {
    "🤖 Jordy rondde af (assistant-ended-call)": "assistant-ended-call",
    "📞 Klant hing op (klant-ended-call)": "klant-ended-call",
    "🔇 Geen mens (geen-mens)": "geen-mens",
    "📩 Voicemail (voicemail)": "voicemail",
    "📴 Niet opgenomen (customer-did-not-answer)": "customer-did-not-answer",
    "🤫 Stilte time-out (silence-timed-out)": "silence-timed-out",
    "📥 Inkomend afgesloten (inbound-ended-call)": "inbound-ended-call",
}

@st.cache_data(ttl=15, show_spinner=False)
def cached_batches_overzicht(van_iso, tot_iso):
    # Server-side aggregatie via Postgres RPC — alle batchcijfers in één query,
    # voor de gekozen periode (van/tot zijn datum-ISO, bv. "2026-06-23").
    res = supabase.rpc('batches_overzicht', {
        "van": f"{van_iso} 00:00:00",
        "tot": f"{tot_iso} 23:59:59",
    }).execute()
    return res.data or []

@st.cache_data(ttl=15, show_spinner=False)
def cached_kpi_counts(vandaag, paused_json="[]"):
    # Uitbel-tellers: sluit inkomende (terugbel) gesprekken uit.
    succes = supabase.table('leads').select("*", count='exact', head=True) \
        .eq('result', 'SUCCES').neq('direction', 'inbound') \
        .gte('ended_at', f"{vandaag} 00:00:00").lte('ended_at', f"{vandaag} 23:59:59").execute().count
    fail_total = supabase.table('leads').select("*", count='exact', head=True) \
        .eq('result', 'MISLUKT').neq('direction', 'inbound') \
        .gte('ended_at', f"{vandaag} 00:00:00").lte('ended_at', f"{vandaag} 23:59:59").execute().count
    # Foutief nummer = SIP 404 (onbestaand/niet-routeerbaar). Apart van "mislukt".
    foutief = supabase.table('leads').select("*", count='exact', head=True) \
        .eq('result', 'MISLUKT').eq('sip_status', '404').neq('direction', 'inbound') \
        .gte('ended_at', f"{vandaag} 00:00:00").lte('ended_at', f"{vandaag} 23:59:59").execute().count
    # Geen gehoor = niemand nam echt op (did-not-answer / voicemail / stille lijn /
    # geen-mens). Géén gevoerd gesprek → hoort NIET bij "mislukt". 404 zit hier in
    # en wordt eruit gehaald, zodat "geen gehoor" alleen GELDIGE nummers telt.
    geen_gehoor_total = supabase.table('leads').select("*", count='exact', head=True) \
        .eq('result', 'MISLUKT').in_('ended_reason', GEEN_GEHOOR_REDENEN).neq('direction', 'inbound') \
        .gte('ended_at', f"{vandaag} 00:00:00").lte('ended_at', f"{vandaag} 23:59:59").execute().count
    geen_gehoor_404 = supabase.table('leads').select("*", count='exact', head=True) \
        .eq('result', 'MISLUKT').in_('ended_reason', GEEN_GEHOOR_REDENEN).eq('sip_status', '404').neq('direction', 'inbound') \
        .gte('ended_at', f"{vandaag} 00:00:00").lte('ended_at', f"{vandaag} 23:59:59").execute().count
    geen_gehoor = max((geen_gehoor_total or 0) - (geen_gehoor_404 or 0), 0)  # geen gehoor van GELDIGE nummers
    # Échte mislukte gesprekken = totaal MISLUKT − foutieve nummers − geen gehoor.
    fail = max((fail_total or 0) - (foutief or 0) - geen_gehoor, 0)
    # Wachtrij telt ALLEEN leads in AAN-staande batches (gepauzeerde batches eruit).
    try:
        paused = json.loads(paused_json) if paused_json else []
    except Exception:
        paused = []

    def _wachtrij(soort):
        q = supabase.table('leads').select("*", count='exact', head=True).eq('status', 'new')
        if paused:
            q = q.not_.in_("batch_id", paused)
        if soort == "mobiel":
            q = q.like("phone", "+316%")
        elif soort == "vast":
            q = q.like("phone", "+31%").not_.like("phone", "+316%")
        return q.execute().count or 0

    todo_mobiel = _wachtrij("mobiel")
    todo_vast = _wachtrij("vast")
    return succes, fail, geen_gehoor, foutief, todo_mobiel, todo_vast

@st.cache_data(ttl=15, show_spinner=False)
def cached_inbound_counts(vandaag):
    # Inkomende (terugbel) gesprekken van vandaag, gesplitst in succes/mislukt.
    succes = supabase.table('leads').select("*", count='exact', head=True) \
        .eq('direction', 'inbound').eq('result', 'SUCCES') \
        .gte('ended_at', f"{vandaag} 00:00:00").lte('ended_at', f"{vandaag} 23:59:59").execute().count
    fail = supabase.table('leads').select("*", count='exact', head=True) \
        .eq('direction', 'inbound').eq('result', 'MISLUKT') \
        .gte('ended_at', f"{vandaag} 00:00:00").lte('ended_at', f"{vandaag} 23:59:59").execute().count
    return succes, fail

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
paused_json = cached_config("paused_batches", "[]") or "[]"
try:
    count_succes, count_fail, count_geen_gehoor, count_foutief, todo_mobiel, todo_vast = cached_kpi_counts(vandaag, paused_json)
except Exception:
    count_succes, count_fail, count_geen_gehoor, count_foutief, todo_mobiel, todo_vast = 0, 0, 0, 0, 0, 0

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("✅ Succes Vandaag", count_succes)
c2.metric("❌ Mislukt Vandaag", count_fail, help="Alleen échte gevoerde gesprekken die niet slaagden. Niet-opgenomen calls staan onder 'Geen gehoor'.")
c3.metric("📵 Geen gehoor", f"{count_geen_gehoor:,}".replace(",", "."), help="Niemand nam echt op: did-not-answer, voicemail, stille lijn, geen-mens (geldige nummers).")
c4.metric("🚫 Foutief nummer", f"{count_foutief:,}".replace(",", "."))
c5.metric("⏳ Wachtrij mobiel", f"{todo_mobiel:,}".replace(",", "."))
c6.metric("⏳ Wachtrij vast", f"{todo_vast:,}".replace(",", "."))

# Inkomende (terugbel) gesprekken — apart van de uitbel-tellers hierboven.
try:
    in_succes, in_fail = cached_inbound_counts(vandaag)
except Exception:
    in_succes, in_fail = 0, 0
ic1, ic2 = st.columns(2)
ic1.metric("📥 Inbound Succes Vandaag", in_succes)
ic2.metric("📥 Inbound Mislukt Vandaag", in_fail)

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

    # Werkelijk gemeten tempo = aantal calls die de motor in de laatste 60s
    # startte (first_attempt). Sinds de bulk-lead-fix (16-06) volgt dit het
    # streeftempo; zo is de balk controleerbaar i.p.v. een loos getal.
    try:
        sinds = (datetime.utcnow() - timedelta(seconds=60)).isoformat()
        _rt = supabase.table('leads').select('id', count='exact', head=True) \
            .gte('first_attempt', sinds).execute()
        echt_tempo = _rt.count
    except Exception:
        echt_tempo = None

    # 'speed' is nu echt het streeftempo in calls/min (geen rem meer per lead).
    # CM staat 5/sec (=300/min) + 100 gelijktijdig toe; de praktijkgrens is
    # Cartesia (15 stemmen) + de eigen 25-cap → ~60-80/min is zinvol.
    SPEED_MAX = 120
    tempo_txt = (f" &nbsp;·&nbsp; <span style='color:#16a34a;font-weight:600'>"
                 f"nu echt: {echt_tempo}/min</span>") if echt_tempo is not None else ""
    st.markdown(
        f"##### ⚡ Snelheid &nbsp;·&nbsp; <span style='color:#6b7280;font-weight:500'>"
        f"streef: {current_speed} calls/min</span>{tempo_txt}", unsafe_allow_html=True)
    new_speed = st.slider("snelheid", min_value=10, max_value=SPEED_MAX,
                          value=min(current_speed, SPEED_MAX), step=5, label_visibility="collapsed",
                          help="Streeftempo in calls/min. CM kan 5/sec (300/min); de echte grens "
                               "is Cartesia (15 stemmen) + de 25-cap, dus ~60-80 is zinvol. "
                               "Hoger leunt vaker op het TTS-vangnet.")

    if new_speed != current_speed:
        supabase.table('config').upsert({"key": "speed", "value": str(new_speed)}).execute()
        st.cache_data.clear()
        st.success(f"Streeftempo aangepast naar {new_speed} calls/minuut!")
        time.sleep(1)
        st.rerun()

    # --- MOBIEL/VAST-VERHOUDING ---
    huidige_ratio = cached_config("mobiel_ratio", "")
    ratio_uit = huidige_ratio in (None, "")
    try:
        ratio_start = int(huidige_ratio) if not ratio_uit else 65
    except (ValueError, TypeError):
        ratio_start = 65
    stand = "UIT (belt zoals vanouds)" if ratio_uit else f"{ratio_start}% mobiel / {100 - ratio_start}% vast"
    st.markdown(f"##### 📱 Mobiel/vast &nbsp;·&nbsp; <span style='color:#6b7280;font-weight:500'>{stand}</span>", unsafe_allow_html=True)
    nieuwe_ratio = st.slider("mobiel_ratio", 0, 100, ratio_start, step=5, label_visibility="collapsed",
                             help="65 = 65% mobiel / 35% vast. 100 = alleen mobiel. 0 = alleen vast.")
    st.caption(f"{nieuwe_ratio}% mobiel / {100 - nieuwe_ratio}% vast")
    colr1, colr2 = st.columns(2)
    if colr1.button("Verhouding opslaan"):
        supabase.table('config').upsert({"key": "mobiel_ratio", "value": str(nieuwe_ratio)}).execute()
        st.cache_data.clear()
        st.success(f"Verhouding ingesteld: {nieuwe_ratio}% mobiel / {100 - nieuwe_ratio}% vast.")
        time.sleep(1)
        st.rerun()
    if colr2.button("Verhouding UIT (belt zoals vanouds)"):
        supabase.table('config').upsert({"key": "mobiel_ratio", "value": ""}).execute()
        st.cache_data.clear()
        st.info("Verhouding uit: geen mobiel/vast-sturing meer.")
        time.sleep(1)
        st.rerun()

# --- GESPREKKEN-OVERZICHT (zoeken + filteren + opname afspelen) ---
try:
    REC_BASE = st.secrets["RECORDINGS_URL"].rstrip("/")
    REC_TOKEN = st.secrets["RECORDINGS_TOKEN"]
except Exception:
    REC_BASE, REC_TOKEN = "", ""

LOG_PAGE_SIZE = 25
LOG_COLS = "name,phone,result,ended_reason,duration,ring_seconds,ring_count,sip_status,ended_at,recording,vapi_analysis,caller_id,direction"

# Echte reden waarom er geen contact kwam, o.b.v. de SIP-status van de telefoon-
# maatschappij. 408 zit hier NIET in: dat is "ging echt over, geen gehoor" → dan
# tonen we het aantal keer overgaan i.p.v. een reden.
SIP_REDENEN = {
    "404": "📵 Nummer bestaat niet / niet in gebruik",
    "480": "📵 Toestel onbereikbaar (uit of geen bereik)",
    "486": "📵 In gesprek (bezet)",
    "487": "📵 Oproep afgebroken",
    "503": "⚙️ Systeem belde even te snel (CPS-limiet) — geen schuld van het nummer",
    "603": "📵 Oproep geweigerd",
}


def _fmt_duur(s):
    try:
        s = int(s or 0)
        return f"{s // 60}:{s % 60:02d}"
    except Exception:
        return "0:00"


def _fmt_duur_lang(sec):
    """Totale belduur in seconden -> 'Xu YYm' (bv. 18u 04m)."""
    sec = int(sec or 0)
    uren, minuten = sec // 3600, (sec % 3600) // 60
    return f"{uren}u {minuten:02d}m"


@st.cache_data(ttl=600, show_spinner=False)
def _fetch_gesprekken(zoek, res_filter, periode, page, _nonce):
    """Eén pagina gesprekken — GECACHET zodat de lijst niet verschuift terwijl je
    'm bekijkt (anders open je per ongeluk een ander gesprek als er ondertussen
    nieuwe calls bijkomen). Ververst alleen bij filter/pagina-wijziging of de
    Ververs-knop (_nonce)."""
    def _apply(q):
        vd = date.today()
        if periode == "Vandaag":
            q = q.gte("ended_at", vd.isoformat())
        elif periode == "Gisteren":
            q = q.gte("ended_at", (vd - timedelta(days=1)).isoformat()).lt("ended_at", vd.isoformat())
        elif periode == "Laatste 7 dagen":
            q = q.gte("ended_at", (vd - timedelta(days=6)).isoformat())
        elif periode == "Laatste 14 dagen":
            q = q.gte("ended_at", (vd - timedelta(days=13)).isoformat())
        # "Alles" → geen datumfilter
        if res_filter == "✅ Succes":
            q = q.eq("result", "SUCCES")
        elif res_filter == "❌ Mislukt":
            q = q.eq("result", "MISLUKT")
        elif res_filter == "📵 Geen gehoor":
            q = q.in_("ended_reason", GEEN_GEHOOR_REDENEN)
        elif res_filter == "🗣️ Echte gesprekken":
            q = q.in_("ended_reason", ECHT_GESPREK_REDENEN)
        elif res_filter == "🏁 Compleet afgerond":
            q = q.eq("ended_reason", "assistant-ended-call")
        elif res_filter in REDEN_FILTERS:
            q = q.eq("ended_reason", REDEN_FILTERS[res_filter])
        z = re.sub(r"[^A-Za-z0-9]", "", zoek or "")
        if z:
            q = q.or_(f"phone.ilike.*{z}*,name.ilike.*{z}*")
        return q

    totaal = _apply(
        supabase.table("leads").select(LOG_COLS, count="exact", head=True)
        .not_.is_("ended_at", "null")
    ).execute().count or 0
    start = page * LOG_PAGE_SIZE
    rows = _apply(
        supabase.table("leads").select(LOG_COLS).not_.is_("ended_at", "null")
    ).order("ended_at", desc=True).range(start, start + LOG_PAGE_SIZE - 1).execute().data or []
    return rows, totaal


with st.expander("🎙️ Gesprekken-overzicht", expanded=False):
    # --- Filterbalk ---
    fc1, fc2, fc3, fc4 = st.columns([2, 1, 1, 1])
    zoek = fc1.text_input("Zoek op naam of nummer", key="log_zoek",
                          placeholder="bv. Jansen of laatste cijfers")
    res_filter = fc2.selectbox("Filter",
                               ["Alle", "🗣️ Echte gesprekken", "🏁 Compleet afgerond",
                                "✅ Succes", "❌ Mislukt", "📵 Geen gehoor",
                                *REDEN_FILTERS.keys()], key="log_res",
                               help="🗣️ = alleen calls waar een mens echt praatte (geen voicemail/stille lijn). "
                                    "De redenen onderaan filteren op exact die ended_reason.")
    periode = fc3.selectbox("Periode",
                            ["Vandaag", "Gisteren", "Laatste 7 dagen", "Laatste 14 dagen", "Alles"],
                            key="log_per",
                            help="Opnames worden 14 dagen bewaard; daarvoor zie je geen opname meer.")
    fc4.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    if fc4.button("🔄 Ververs", key="log_refresh", use_container_width=True):
        st.session_state["log_nonce"] = st.session_state.get("log_nonce", 0) + 1
        st.session_state["log_page"] = 0
        st.rerun()

    # Paginanummer terugzetten als een filter wijzigt
    filter_sig = f"{zoek}|{res_filter}|{periode}"
    if st.session_state.get("log_filter_sig") != filter_sig:
        st.session_state["log_filter_sig"] = filter_sig
        st.session_state["log_page"] = 0
    page = st.session_state.get("log_page", 0)
    nonce = st.session_state.get("log_nonce", 0)

    try:
        rows, totaal = _fetch_gesprekken(zoek, res_filter, periode, page, nonce)
    except Exception as e:
        st.error(f"Kan gesprekken niet ophalen: {e}")
        rows, totaal = [], 0

    if totaal == 0:
        st.info("Geen gesprekken gevonden voor deze filters.")
    else:
        max_page = max(0, (totaal - 1) // LOG_PAGE_SIZE)

        tabel = pd.DataFrame([{
            "Datum/tijd": _nl_tijd(r.get("ended_at")),
            "Naam": r.get("name") or "",
            "Nummer": r.get("phone") or "",
            "Uitbelnummer": ("📥 inkomend" if r.get("direction") == "inbound"
                             else (r.get("caller_id") or "—")),
            "Resultaat": r.get("result") or "",
            "Reden": r.get("ended_reason") or "",
            "Duur": _fmt_duur(r.get("duration")),
            "🎙️": "✓" if r.get("recording") else "—",
        } for r in rows])

        seln = st.dataframe(
            tabel, hide_index=True, use_container_width=True,
            on_select="rerun", selection_mode="single-row", key=f"log_tabel_{page}",
        )

        # Paginering
        pc1, pc2, pc3 = st.columns([1, 2, 1])
        if pc1.button("◀ vorige", disabled=(page <= 0), key="log_prev", use_container_width=True):
            st.session_state["log_page"] = page - 1
            st.rerun()
        pc2.markdown(
            f"<div style='text-align:center;color:#6b7280;padding-top:8px'>"
            f"pagina {page + 1} / {max_page + 1} · {totaal} gesprekken</div>",
            unsafe_allow_html=True,
        )
        if pc3.button("volgende ▶", disabled=(page >= max_page), key="log_next", use_container_width=True):
            st.session_state["log_page"] = page + 1
            st.rerun()

        # --- Detailpaneel voor de geselecteerde rij ---
        try:
            sel_rows = list(seln.selection.rows)
        except Exception:
            sel_rows = []

        if not sel_rows:
            st.caption("👆 Klik op een rij om de opname en antwoorden te zien.")
        else:
            r = rows[sel_rows[0]]
            st.divider()
            st.markdown(f"#### {r.get('name', '?')} · {r.get('phone', '')}")
            d1, d2, d3, d4 = st.columns(4)
            d1.metric("Resultaat", r.get("result") or "—")
            d2.metric("Reden", r.get("ended_reason") or "—")
            d3.metric("Duur", _fmt_duur(r.get("duration")))
            d4.metric("Datum", _nl_tijd(r.get("ended_at"), "%Y-%m-%d %H:%M") or "—")

            # Echte reden tonen i.p.v. een gokje uit de seconden. Bij een afwijzing
            # (404/480/486/…) zegt de SIP-status precies wat er was; ging de telefoon
            # echt over zonder gehoor (408/opgenomen) dan tonen we het aantal keer.
            ss = str(r.get("sip_status") or "")
            rs = r.get("ring_seconds")
            rc = r.get("ring_count") or 0
            if ss in SIP_REDENEN:
                st.caption(SIP_REDENEN[ss])
            elif rs is not None:
                if rc >= 1:
                    st.caption(f"📞 Ging ~{rc}x over ({rs:g}s).")
                else:
                    st.caption(f"📞 Vrijwel direct opgenomen ({rs:g}s).")

            rec = r.get("recording")
            if not rec:
                st.caption("Geen opname voor dit gesprek.")
            elif not (REC_BASE and REC_TOKEN):
                st.caption("Opname-server niet geconfigureerd (RECORDINGS_URL/TOKEN in secrets).")
            else:
                try:
                    resp = requests.get(f"{REC_BASE}/recordings/{rec}",
                                        headers={"X-Recordings-Token": REC_TOKEN}, timeout=20)
                    if resp.status_code == 200:
                        st.audio(resp.content, format="audio/ogg")
                    elif resp.status_code == 404:
                        st.caption("⏳ Opname is verlopen (opnames blijven 14 dagen bewaard).")
                    else:
                        st.caption(f"Opname niet beschikbaar (status {resp.status_code}).")
                except Exception as e:
                    st.caption(f"Opname laden mislukt: {e}")

            analyse = r.get("vapi_analysis") or {}
            data = (analyse.get("structuredData") if isinstance(analyse, dict) else None) or {}
            if data:
                labels = {
                    "deelnemer_meegedaan": "Meegedaan",
                    "antwoordVraag1": "Vraag 1",
                    "antwoordVraag2": "Vraag 2",
                    "antwoordVraag3": "Vraag 3",
                    "toon": "Toon",
                    "succes": "Succes",
                }
                regels = [f"- **{lbl}:** {data.get(k)}"
                          for k, lbl in labels.items() if data.get(k) not in (None, "")]
                if regels:
                    st.markdown("**Enquête-antwoorden:**\n" + "\n".join(regels))

# --- BATCH RAPPORTAGE ---
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

        # Status-labels: kleurbol + ▾-pijltje, zodat in één oogopslag zichtbaar is
        # dat de cel een aanklikbaar dropdown-menu is.
        ST_ACTIEF = "🟢 Actief ▾"
        ST_INACTIEF = "🔴 Inactief ▾"

        # Bouw de tabel-data.
        tabel = []
        for b in rijen:
            bid = b["batch_id"]
            afgehandeld = int(b.get("afgehandeld", 0))
            sales = int(b.get("sales", 0))
            conv = (sales / afgehandeld * 100) if afgehandeld else 0.0
            tabel.append({
                "Kies": False,
                "Batch": bid,
                "Status": ST_INACTIEF if bid in paused_list else ST_ACTIEF,
                "Totaal": int(b.get("totaal", 0)),
                "Afgehandeld": afgehandeld,
                "Open": int(b.get("te_bellen", 0)),
                "Gebelde tijd": _fmt_duur_lang(b.get("gebelde_tijd_sec", 0)),
                "Sales": sales,
                "Conversie": f"{conv:.1f}%".replace(".", ","),
            })
        df = pd.DataFrame(tabel)

        st.caption("Klik op een kolomkop om te sorteren. Wijzig **Status** om een "
                   "batch direct aan/uit te zetten. Vink **Kies** aan om er onderaan "
                   "een actie (reset/verwijderen) op te doen.")

        bewerkt = st.data_editor(
            df,
            hide_index=True,
            use_container_width=True,
            key=f"batch_tabel_{periode}",
            column_config={
                "Kies": st.column_config.CheckboxColumn(
                    "Kies", default=False,
                    help="Vink aan om hieronder een actie (reset/verwijderen) op deze batch te doen"),
                "Status": st.column_config.SelectboxColumn(
                    "Status", options=[ST_ACTIEF, ST_INACTIEF], required=True,
                    help="Klik om deze batch aan/uit te zetten voor de dialer"),
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
            wil_inactief = ("Inactief" in str(rij["Status"]))
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
        # Actie-batch = de in de tabel aangevinkte rij (kolom "Kies").
        gekozen_rows = [r["Batch"] for _, r in bewerkt.iterrows() if bool(r.get("Kies"))]
        akb = gekozen_rows[0] if gekozen_rows else None
        if len(gekozen_rows) > 1:
            st.caption(f"ℹ️ Meerdere batches aangevinkt — ik gebruik de bovenste: **{akb}**.")

        if not akb:
            st.info("Vink in de tabel (kolom **Kies**) een batch aan om er een actie op te doen.")
        else:
            st.caption(f"Geselecteerd: **{akb}**")
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

# --- 9. IMPORT MODULE ---
@st.dialog("📊 Import resultaat")
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
    else:
        st.markdown("**Blacklist bijgewerkt**")
        a, b = st.columns(2)
        a.metric("📄 Regels in bestand", r["totaal"])
        b.metric("⛔ Nieuw op blacklist", r["nieuw"])
        c, d = st.columns(2)
        c.metric("🔄 Stond er al op", r["dubbel"])
        d.metric("⚠️ Ongeldig", r["ongeldig"])
    if st.button("Sluiten"):
        st.session_state.pop("import_resultaat", None)
        st.rerun()

# Pop-up tonen zodra een import net klaar is (overleeft de auto-refresh)
if "import_resultaat" in st.session_state:
    toon_import_resultaat(st.session_state["import_resultaat"])

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

                    fouten = 0
                    if to_upload:
                        # Gewone insert: dubbele nummers zijn hierboven al
                        # weggefilterd. upsert(on_conflict='phone') werkt niet
                        # meer sinds de phone-constraint partieel is (alleen
                        # outbound) → gaf Error 42P10 en stille mislukte imports.
                        for i in range(0, len(to_upload), 1000):
                            chunk = to_upload[i:i+1000]
                            try:
                                supabase.table('leads').insert(chunk).execute()
                            except Exception as e:
                                fouten += len(chunk)
                                print(f"Batch fout: {e}")

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

                    st.session_state["import_resultaat"] = {
                        "soort": "blacklist",
                        "totaal": len(df),
                        "nieuw": c_new,
                        "dubbel": c_dup,
                        "ongeldig": c_inv,
                    }

                progress.progress(1.0)
                st.cache_data.clear()
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

            # Terugbellers (inbound) krijgen een eigen rij zónder original_data;
            # de leadgegevens staan op de outbound-rij met hetzelfde nummer.
            # Vul die hier aan, anders blijven de kolommen in de export leeg.
            if not df_exp.empty and 'original_data' in df_exp.columns:
                _leeg = df_exp['original_data'].apply(lambda v: not isinstance(v, dict) or not v)
                _phones = df_exp.loc[_leeg, 'phone'].dropna().unique().tolist()
                if _phones:
                    _src = supabase.table('leads').select("phone, original_data, ended_at") \
                        .in_("phone", _phones).not_.is_("original_data", "null").execute()
                    _lookup = {}
                    for _r in sorted(_src.data, key=lambda r: r.get('ended_at') or ""):
                        if isinstance(_r.get('original_data'), dict) and _r['original_data']:
                            _lookup[_r['phone']] = _r['original_data']
                    df_exp['original_data'] = df_exp.apply(
                        lambda row: _lookup.get(row['phone'])
                        if (not isinstance(row['original_data'], dict) or not row['original_data'])
                        else row['original_data'],
                        axis=1
                    )

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
                    _ed = pd.to_datetime(df_raw['ended_at'], errors='coerce', utc=True)
                    try:
                        _ed = _ed.dt.tz_convert('Europe/Amsterdam')
                    except Exception:
                        pass
                    df_final['enquete_datum'] = _ed.dt.strftime('%d-%m-%Y')

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
