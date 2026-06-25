"""Console-test voor dialer_brein (run: python3 test_dialer_brein.py)."""
from dialer_brein import is_bereikt, is_dood_nummer, is_herbelbaar, uur_gewichten, verwachte_curve, verwacht_tot_nu, koers, batch_scores, batch_gewichten


def test_is_bereikt():
    assert is_bereikt("klant-ended-call", "MISLUKT") is True
    assert is_bereikt("assistant-ended-call", "MISLUKT") is True
    assert is_bereikt("voicemail", "SUCCES") is True          # SUCCES telt altijd
    assert is_bereikt("customer-did-not-answer", "MISLUKT") is False
    assert is_bereikt("geen-mens", "MISLUKT") is False
    assert is_bereikt(None, None) is False


def test_is_dood_nummer():
    assert is_dood_nummer("404") is True
    assert is_dood_nummer(404) is True
    assert is_dood_nummer("480") is False
    assert is_dood_nummer(None) is False


def test_is_herbelbaar():
    # geen-gehoor op een belbare lijn => herbelbaar
    assert is_herbelbaar("customer-did-not-answer", None, "MISLUKT") is True
    assert is_herbelbaar("geen-mens", "486", "MISLUKT") is True   # bezet = tijdelijk
    # bereikt mens => niet herbelbaar (al gesproken)
    assert is_herbelbaar("klant-ended-call", None, "MISLUKT") is False
    # dood nummer => nooit herbelbaar
    assert is_herbelbaar("customer-did-not-answer", "404", "MISLUKT") is False


def _rij(datum, weekdag, uur, gebeld, succes):
    return {"datum": datum, "weekdag": weekdag, "uur": uur,
            "gebeld": gebeld, "succes": succes}


def test_uur_gewichten_goed_vs_slecht_uur():
    # 3 weekdagen data; uur 16 scoort 2x het gemiddelde, uur 19 de helft.
    rijen = []
    for i, d in enumerate(["2026-06-22", "2026-06-23", "2026-06-24"]):
        rijen.append(_rij(d, i, 16, 200, 4))   # 2% conversie
        rijen.append(_rij(d, i, 19, 200, 1))   # 0.5% conversie
    g = uur_gewichten(rijen, is_zaterdag=False, min_dagen=3, min_uur_calls=150)
    assert g[16] > g[19]
    assert g[16] > 1.0 and g[19] < 1.0


def test_uur_gewichten_dunne_data_plat():
    # te weinig calls per uur => alles 1.0 (fail-safe plat profiel)
    rijen = [_rij("2026-06-24", 2, 16, 10, 1)]
    g = uur_gewichten(rijen, min_dagen=3, min_uur_calls=150)
    assert all(w == 1.0 for w in g.values())


def test_uur_gewichten_scheidt_zaterdag():
    # weekdag-rijen mogen het zaterdagprofiel niet beïnvloeden
    rijen = [_rij("2026-06-24", 2, 16, 300, 9)]   # woensdag
    g = uur_gewichten(rijen, is_zaterdag=True, min_dagen=1, min_uur_calls=1)
    assert g == {}   # geen zaterdag-data => leeg


def test_verwachte_curve_eindigt_op_dagdoel():
    venster = list(range(9, 21))                       # 09..20
    gewichten = {u: 1.0 for u in venster}              # plat profiel
    curve = verwachte_curve(gewichten, venster, dagdoel=400)
    assert round(curve[20]) == 400                     # einde dag = dagdoel
    assert curve[9] < curve[14] < curve[20]            # monotoon stijgend


def test_verwachte_curve_weegt_goede_uren_zwaarder():
    venster = [9, 10]
    gewichten = {9: 0.5, 10: 1.5}                       # uur 10 telt 3x zo zwaar
    curve = verwachte_curve(gewichten, venster, dagdoel=400)
    aandeel_9 = curve[9]
    aandeel_10 = curve[10] - curve[9]
    assert round(aandeel_10 / aandeel_9, 1) == 3.0


def test_verwacht_tot_nu_interpoleert():
    venster = list(range(9, 21))
    gewichten = {u: 1.0 for u in venster}
    curve = verwachte_curve(gewichten, venster, dagdoel=400)
    # halverwege uur 14 = curve[13] + helft van uur 14's aandeel
    halverwege = verwacht_tot_nu(curve, venster, 14, 30, dagdoel=400)
    aandeel_14 = curve[14] - curve[13]
    assert abs(halverwege - (curve[13] + aandeel_14 * 0.5)) < 0.01
    # vóór het venster = 0, na het venster = dagdoel
    assert verwacht_tot_nu(curve, venster, 7, 0) == 0.0
    assert round(verwacht_tot_nu(curve, venster, 23, 0)) == 400


def test_koers_doel_binnen():
    k = koers(succes_nu=405, verwacht_nu=380, dagdoel=400)
    assert k["status"] == "doel binnen"
    assert k["tempo"] == "laag pitje"


def test_koers_achter():
    k = koers(succes_nu=300, verwacht_nu=340, dagdoel=400)
    assert k["status"] == "achter"
    assert k["tempo"] == "omhoog"
    assert k["verschil"] == -40


def test_koers_voor():
    k = koers(succes_nu=360, verwacht_nu=330, dagdoel=400)
    assert k["status"] == "voor"
    assert k["tempo"] == "omlaag"


def test_koers_op_koers():
    k = koers(succes_nu=331, verwacht_nu=330, dagdoel=400)   # binnen marge
    assert k["status"] == "op koers"
    assert k["tempo"] == "gelijk"


def test_batch_scores_conversie_per_bereikt_mens():
    rijen = [{"batch_id": "A", "gebeld": 1000, "bereikt": 200, "succes": 4, "dood404": 50}]
    s = batch_scores(rijen, min_calls=150)[0]
    assert s["conversie"] == 0.02              # 4/200, NIET 4/1000
    assert s["dood_pct"] == 0.05               # 50/1000
    assert s["genoeg_data"] is True


def test_batch_gewichten_zacht_en_geklemd():
    # batch B converteert 2x het gemiddelde => meer gewicht, maar geklemd op 1.5
    scores = [
        {"batch_id": "A", "conversie": 0.01, "dood_pct": 0.02, "genoeg_data": True},
        {"batch_id": "B", "conversie": 0.04, "dood_pct": 0.02, "genoeg_data": True},
    ]
    g = {r["batch_id"]: r for r in batch_gewichten(scores, klem=(0.5, 1.5))}
    assert g["B"]["gewicht"] == 1.5            # geklemd (zacht), niet 2.5+
    assert g["A"]["gewicht"] < 1.0


def test_batch_gewichten_dood_pauze_voorstel():
    scores = [{"batch_id": "Z", "conversie": 0.0, "dood_pct": 0.61, "genoeg_data": True}]
    g = batch_gewichten(scores, dood_pauze_pct=0.40)[0]
    assert g["gewicht"] == 0.0
    assert "dood" in g["actie"].lower()


def test_batch_gewichten_te_weinig_data_neutraal():
    scores = [{"batch_id": "N", "conversie": 0.09, "dood_pct": 0.0, "genoeg_data": False}]
    g = batch_gewichten(scores)[0]
    assert g["gewicht"] == 1.0                 # geen gok op ruis
    assert "data" in g["actie"].lower()


if __name__ == "__main__":
    for naam, fn in list(globals().items()):
        if naam.startswith("test_") and callable(fn):
            fn()
            print("OK", naam)
    print("ALLE TESTS GESLAAGD")
