"""Pure beslis-logica voor de slimme dialer (meekijk-modus).

Geen Supabase/Streamlit/HTTP → volledig unit-testbaar. Alleen stdlib.
De functies krijgen kant-en-klare aggregaten en geven beslissingen terug;
ze VOEREN NIETS UIT (read-only meekijk-modus).
"""

DAGDOEL = 400
BEREIKT_REDENEN = {"klant-ended-call", "assistant-ended-call"}


def is_bereikt(ended_reason, result):
    """True als er een mens aan de lijn was (gesprek of succes)."""
    if result == "SUCCES":
        return True
    return ended_reason in BEREIKT_REDENEN


def is_dood_nummer(sip_status):
    """True als het nummer niet bestaat (SIP 404)."""
    return str(sip_status) == "404"


def is_herbelbaar(ended_reason, sip_status, result):
    """True voor geen-gehoor op een belbare lijn (niet bereikt, niet dood)."""
    if is_bereikt(ended_reason, result):
        return False
    if is_dood_nummer(sip_status):
        return False
    return True
