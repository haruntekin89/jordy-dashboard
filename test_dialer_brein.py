"""Console-test voor dialer_brein (run: python3 test_dialer_brein.py)."""
from dialer_brein import is_bereikt, is_dood_nummer, is_herbelbaar, uur_gewichten


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


if __name__ == "__main__":
    for naam, fn in list(globals().items()):
        if naam.startswith("test_") and callable(fn):
            fn()
            print("OK", naam)
    print("ALLE TESTS GESLAAGD")
