"""Console-test voor dialer_brein (run: python3 test_dialer_brein.py)."""
from dialer_brein import is_bereikt, is_dood_nummer, is_herbelbaar


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


if __name__ == "__main__":
    for naam, fn in list(globals().items()):
        if naam.startswith("test_") and callable(fn):
            fn()
            print("OK", naam)
    print("ALLE TESTS GESLAAGD")
