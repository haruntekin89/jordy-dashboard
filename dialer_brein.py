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


def uur_gewichten(daguur_rijen, is_zaterdag=False, min_dagen=3, min_uur_calls=150):
    """Leer per uur-van-de-dag een gewicht uit historische conversie.

    Gewicht = (succes/gebeld van dat uur) / (gemiddelde succes/gebeld).
    Uren met te weinig data (min_uur_calls of min_dagen) krijgen 1.0.
    Weekdagen (ma-vr) en zaterdag worden gescheiden via is_zaterdag.
    """
    relevante = [r for r in daguur_rijen
                 if (r["weekdag"] == 5) == is_zaterdag and r["weekdag"] != 6]
    per_uur = {}
    for r in relevante:
        u = per_uur.setdefault(r["uur"], {"gebeld": 0, "succes": 0, "dagen": set()})
        u["gebeld"] += r["gebeld"]
        u["succes"] += r["succes"]
        if r["gebeld"] > 0:
            u["dagen"].add(r["datum"])

    totaal_gebeld = sum(u["gebeld"] for u in per_uur.values())
    totaal_succes = sum(u["succes"] for u in per_uur.values())
    if totaal_gebeld == 0:
        return {}
    gem_rate = totaal_succes / totaal_gebeld

    gewichten = {}
    for uur, u in per_uur.items():
        genoeg = u["gebeld"] >= min_uur_calls and len(u["dagen"]) >= min_dagen
        if not genoeg or gem_rate == 0:
            gewichten[uur] = 1.0
            continue
        rate = u["succes"] / u["gebeld"]
        w = rate / gem_rate
        gewichten[uur] = round(max(0.3, min(2.0, w)), 2)
    return gewichten
