"""Pure beslis-logica voor de slimme dialer (meekijk-modus).

Geen Supabase/Streamlit/HTTP → volledig unit-testbaar. Alleen stdlib.
De functies krijgen kant-en-klare aggregaten en geven beslissingen terug;
ze VOEREN NIETS UIT (read-only meekijk-modus).
"""

DAGDOEL = 400
VLOER = 10  # laagste calls/min bij tempo-sturing
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


def verwachte_curve(gewichten, uren_venster, dagdoel=DAGDOEL):
    """Verdeel dagdoel over de beluren gewogen volgens het uur-profiel.

    Geeft het cumulatief verwachte aantal successen aan het EINDE van elk uur.
    """
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


def koers(succes_nu, verwacht_nu, dagdoel=DAGDOEL, marge=5):
    """Vergelijk waar we zijn met de curve en geef een tempo-advies.

    marge = speling (successen) waarbinnen we 'op koers' heten → geen jojo.
    """
    verschil = round(succes_nu - verwacht_nu, 2)
    if succes_nu >= dagdoel:
        return {"status": "doel binnen", "tempo": "laag pitje", "verschil": verschil,
                "tekst": f"Doel {dagdoel} binnen ({succes_nu}) → laag pitje."}
    if verschil <= -marge:
        return {"status": "achter", "tempo": "omhoog", "verschil": verschil,
                "tekst": f"{abs(verschil):.0f} achter op de curve → tempo omhoog."}
    if verschil >= marge:
        return {"status": "voor", "tempo": "omlaag", "verschil": verschil,
                "tekst": f"{verschil:.0f} voor op de curve → tempo omlaag."}
    return {"status": "op koers", "tempo": "gelijk", "verschil": verschil,
            "tekst": "Op koers → tempo gelijk houden."}


def batch_scores(batch_rijen, min_calls=150):
    """Scoor elke batch op conversie PER BEREIKT MENS (haalt dode-nummer-confound eruit)."""
    out = []
    for r in batch_rijen:
        gebeld = r.get("gebeld", 0)
        bereikt = r.get("bereikt", 0)
        conversie = (r.get("succes", 0) / bereikt) if bereikt > 0 else 0.0
        dood_pct = (r.get("dood404", 0) / gebeld) if gebeld > 0 else 0.0
        out.append({
            "batch_id": r["batch_id"],
            "conversie": round(conversie, 4),
            "dood_pct": round(dood_pct, 4),
            "genoeg_data": gebeld >= min_calls,
        })
    return out


def batch_gewichten(scores, dood_pauze_pct=0.40, klem=(0.5, 1.5)):
    """Zachte, geklemde gewichten: meer op goede batches, pauze-voorstel bij veel dood."""
    geldig = [s for s in scores if s["genoeg_data"] and s["conversie"] > 0]
    gem = (sum(s["conversie"] for s in geldig) / len(geldig)) if geldig else 0.0
    lo, hi = klem
    out = []
    for s in scores:
        if s["dood_pct"] >= dood_pauze_pct:
            out.append({"batch_id": s["batch_id"], "gewicht": 0.0,
                        "actie": f"pauze-voorstel ({s['dood_pct']*100:.0f}% dood nummers)"})
        elif not s["genoeg_data"]:
            out.append({"batch_id": s["batch_id"], "gewicht": 1.0,
                        "actie": "neutraal (te weinig data)"})
        elif gem == 0:
            out.append({"batch_id": s["batch_id"], "gewicht": 1.0,
                        "actie": "neutraal (nog geen gemiddelde)"})
        else:
            w = max(lo, min(hi, s["conversie"] / gem))
            label = "meer" if w > 1.0 else "minder" if w < 1.0 else "gelijk"
            out.append({"batch_id": s["batch_id"], "gewicht": round(w, 2),
                        "actie": f"{label} (conversie {s['conversie']*100:.2f}% vs gem {gem*100:.2f}%)"})
    return out


def reset_voorstellen(reset_info, wacht_dagen=2):
    """Bepaal per uitgebelde batch of een reset van HERBELBARE leads mag.

    Reset alleen herbelbare geen-gehoor; dode nummers tellen NIET mee en blijven
    geparkeerd. (De max-3-rondes-grens vereist een DB-kolom en zit NIET in de
    meekijk-modus — dit zijn round-1 voorstellen.)
    """
    out = []
    for r in reset_info:
        bid = r["batch_id"]
        if r["new_count"] > 0:
            out.append({"batch_id": bid, "resetbaar": False,
                        "herbelbaar_count": r["herbelbaar_count"],
                        "reden": f"niet uitgebeld ({r['new_count']} leads nog 'new')"})
        elif r["laatste_poging_dagen"] < wacht_dagen:
            out.append({"batch_id": bid, "resetbaar": False,
                        "herbelbaar_count": r["herbelbaar_count"],
                        "reden": f"wacht nog ({r['laatste_poging_dagen']:.0f}/{wacht_dagen} dagen)"})
        elif r["herbelbaar_count"] <= 0:
            out.append({"batch_id": bid, "resetbaar": False,
                        "herbelbaar_count": 0,
                        "reden": "geen herbelbare leads (alleen dode nummers over)"})
        else:
            out.append({"batch_id": bid, "resetbaar": True,
                        "herbelbaar_count": r["herbelbaar_count"],
                        "reden": f"uitgebeld + {r['laatste_poging_dagen']:.0f} dagen geleden → "
                                 f"{r['herbelbaar_count']} herbelbare leads terugzetbaar"})
    return out


def banner_checks(succes_nu, belbare_leads, verwachte_conversie,
                  recente_conversie, baseline_conversie, dagdoel=DAGDOEL,
                  daling_factor=0.7):
    """Bepaal of de 'laad nieuwe data bij'-banner aan moet. Read-only signalen."""
    waarschuwingen = []
    max_haalbaar = succes_nu + belbare_leads * verwachte_conversie
    if max_haalbaar < dagdoel:
        waarschuwingen.append({
            "type": "te weinig verse leads",
            "tekst": f"Met de huidige leads is ~{max_haalbaar:.0f} haalbaar "
                     f"(doel {dagdoel}). Laad nieuwe data bij."})
    if baseline_conversie > 0 and recente_conversie < baseline_conversie * daling_factor:
        waarschuwingen.append({
            "type": "conversie zakt",
            "tekst": f"Conversie zakt: recent {recente_conversie*100:.2f}% vs "
                     f"normaal {baseline_conversie*100:.2f}%. Leads raken op/moe — "
                     f"laad nieuwe data bij."})
    return waarschuwingen


def tempo_plan(uur_gewichten, venster_uren, max_cpm, vloer=10):
    """Calls/min per uur: beste uur ≈ max_cpm, zwak uur ≈ vloer (lineair op gewicht)."""
    if not venster_uren:
        return {}
    gewichten = {u: uur_gewichten.get(u, 1.0) for u in venster_uren}
    max_g = max(gewichten.values()) or 1.0
    plan = {}
    for u in venster_uren:
        cpm = vloer + (max_cpm - vloer) * (gewichten[u] / max_g)
        plan[u] = int(max(vloer, min(max_cpm, round(cpm))))
    return plan


# Duplicaat van tempo_logica.py (server) — identiek houden (repos delen geen code).
def dag_fractie(uur, minuut, venster_start=9, venster_eind=21):
    """Deel van het belvenster van vandaag dat verstreken is (0..1)."""
    lengte = venster_eind - venster_start
    if lengte <= 0:
        return 0.0
    return max(0.0, min(1.0, ((uur + minuut / 60.0) - venster_start) / lengte))


def week_verwacht(isoweekday, dag_fr, week_target=2000):
    """Verwacht aantal successen tot nu deze week (lineair over 5 weekdagen)."""
    if isoweekday >= 6:
        return float(week_target)
    return week_target * ((isoweekday - 1) + dag_fr) / 5.0


# Duplicaat van tempo_logica.py (server) — identiek houden. Voor het TONEN van het
# echte geregelde tempo op het dashboard (hetzelfde getal als de motor berekent).
def week_nudge(week_succes, week_verw, week_target=2000, gevoeligheid=3.0, lo=0.6, hi=1.4):
    """Tempo-factor o.b.v. weekstand: achter→>1, voor→<1, zacht begrensd."""
    factor = 1.0 + gevoeligheid * (week_verw - week_succes) / week_target
    return max(lo, min(hi, factor))


def tempo_nu(plan, nu_uur, nudge, max_cpm, vloer=10):
    """Calls/min voor het huidige uur: plan[uur] × nudge, geklemd [vloer, max_cpm].
    plan-keys mogen int of string zijn (JSON-config geeft string-keys)."""
    base = plan.get(nu_uur)
    if base is None:
        base = plan.get(str(nu_uur))
    if base is None:
        base = vloer
    return int(max(vloer, min(max_cpm, round(base * nudge))))


# Tempo-model functies (identiek aan server tempo_logica.py)
def belvenster(isoweekday):
    """(start_uur, eind_uur) van het belvenster vandaag; eind exclusief. Zo → None."""
    if isoweekday == 7:
        return None
    if isoweekday == 6:
        return (10, 16)
    return (9, 21)


def _gewicht(uur_gewichten, uur):
    """Gewicht voor een uur; accepteert int- of string-keys; default 1.0."""
    g = uur_gewichten.get(uur)
    if g is None:
        g = uur_gewichten.get(str(uur))
    if g is None:
        return 1.0
    try:
        return float(g)
    except (TypeError, ValueError):
        return 1.0


def bereik_meten(succ_90, calls_90):
    """Successen per gebelde lead over de meetperiode; geen calls → 0.0."""
    if calls_90 <= 0:
        return 0.0
    return succ_90 / calls_90


def resterend_gewicht(uur_gewichten, nu_uur, eind_uur):
    """(gewicht van dit uur, som van de gewichten van nu t/m laatste beluur)."""
    gewicht_nu = _gewicht(uur_gewichten, nu_uur)
    som = sum(_gewicht(uur_gewichten, u) for u in range(nu_uur, eind_uur))
    return gewicht_nu, som


def tempo_behoefte(nog_nodig, bereik, gewicht_nu, som_rest, resterende_min, max_cpm, vloer=VLOER):
    """Calls/min nu = (nog_nodig / bereik) × (dit uur z'n deel) / resterende minuten."""
    if nog_nodig <= 0 or bereik <= 0 or som_rest <= 0 or resterende_min <= 0:
        return vloer
    calls_totaal = nog_nodig / bereik
    calls_dit_uur = calls_totaal * (gewicht_nu / som_rest)
    cpm = calls_dit_uur / resterende_min
    return int(max(vloer, min(max_cpm, round(cpm))))


def uur_profiel_tempo(uur_gewichten, nu_uur, venster_uren, max_cpm, vloer=VLOER):
    """Terugval-tempo: beste uur ≈ max_cpm, zwak ≈ vloer (lineair op gewicht)."""
    if not venster_uren:
        return vloer
    max_g = max(_gewicht(uur_gewichten, u) for u in venster_uren) or 1.0
    cpm = vloer + (max_cpm - vloer) * (_gewicht(uur_gewichten, nu_uur) / max_g)
    return int(max(vloer, min(max_cpm, round(cpm))))


def bereken_tempo(uur_gewichten, isoweekday, nu_uur, nu_minuut, succ_vandaag,
                  calls_90, succ_90, max_cpm, dagdoel=DAGDOEL, vloer=VLOER, drempel=30):
    """Het volledige tempo-model: dag-target + gemeten bereik, terugval bij weinig data."""
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
    nog_nodig = max(0, dagdoel - succ_vandaag)
    gewicht_nu, som_rest = resterend_gewicht(uur_gewichten, nu_uur, eind)
    return tempo_behoefte(nog_nodig, bereik, gewicht_nu, som_rest,
                          60 - nu_minuut, max_cpm, vloer)
