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
    "Laatste 1 maand": 1,
    "Laatste 2 maanden": 2,
    "Laatste 3 maanden": 3,
    "Laatste 6 maanden": 6,
    "Laatste 12 maanden": 12,
}


def naar_naief_utc(waarde):
    """ISO-tekst -> naïeve UTC-datetime, of None.

    Nodig omdat de twee datumkolommen verschillen: first_attempt is tekst zonder
    tijdzone (naïef UTC), ended_at is timestamptz met '+00:00'. Zo zijn ze
    onderling vergelijkbaar.

    Onleesbare waarden (None, lege string, of ongeldige ISO-tekst) geven None terug.
    """
    if not waarde:
        return None
    try:
        moment = datetime.fromisoformat(waarde)
    except ValueError:
        # Ongeldige ISO-tekst — geen contactmoment bekend
        return None
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
