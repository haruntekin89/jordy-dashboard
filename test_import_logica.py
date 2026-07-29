from datetime import datetime, timedelta

import pytest

from import_logica import (
    PERIODE_KEUZES,
    beoordeel_nummer,
    naar_naief_utc,
    periode_grens,
)

NU = datetime(2026, 7, 29, 12, 0, 0)


def info(sale=False, open_=False, laatste_contact=None):
    return {"sale": sale, "open": open_, "laatste_contact": laatste_contact}


# --- naar_naief_utc ---

def test_naief_utc_met_en_zonder_tijdzone_geeft_zelfde_moment():
    zonder = naar_naief_utc("2026-06-10T10:44:13.462284")
    met = naar_naief_utc("2026-06-10T10:44:13.462284+00:00")
    assert zonder == met == datetime(2026, 6, 10, 10, 44, 13, 462284)


def test_naief_utc_rekent_andere_tijdzone_om_naar_utc():
    assert naar_naief_utc("2026-06-10T12:44:13+02:00") == datetime(2026, 6, 10, 10, 44, 13)


@pytest.mark.parametrize("leeg", [None, ""])
def test_naief_utc_op_leeg_geeft_none(leeg):
    assert naar_naief_utc(leeg) is None


def test_naief_utc_op_duidelijk_ongeldige_tekst_geeft_none():
    assert naar_naief_utc("geen datum") is None


def test_naief_utc_op_onmogelijke_datum_geeft_none():
    assert naar_naief_utc("2026-13-45T99:99:99") is None


# --- periode_grens ---

def test_periode_grens_none_betekent_hele_database():
    assert periode_grens(None) is None


def test_periode_grens_rekent_maanden_terug():
    assert periode_grens(3, nu=NU) == datetime(2026, 4, 29, 12, 0, 0)


def test_periode_keuzes_bevat_de_vier_opties():
    assert PERIODE_KEUZES == {
        "Hele database": None,
        "Laatste 3 maanden": 3,
        "Laatste 6 maanden": 6,
        "Laatste 12 maanden": 12,
    }


# --- beoordeel_nummer ---

def test_onbekend_nummer_is_nieuw():
    assert beoordeel_nummer(None, op_blacklist=False, grens=None) == "nieuw"


def test_blacklist_wint_van_sale_en_periode():
    oud = info(sale=True, open_=True, laatste_contact=datetime(2020, 1, 1))
    assert beoordeel_nummer(oud, op_blacklist=True, grens=periode_grens(3, nu=NU)) == "blacklist"


def test_blacklist_blokkeert_ook_onbekend_nummer():
    assert beoordeel_nummer(None, op_blacklist=True, grens=None) == "blacklist"


def test_sale_blokkeert_ook_ver_buiten_de_periode():
    oud = info(sale=True, laatste_contact=datetime(2020, 1, 1))
    assert beoordeel_nummer(oud, op_blacklist=False, grens=periode_grens(3, nu=NU)) == "sale"


def test_nog_open_blokkeert_ook_zonder_contactdatum():
    wacht = info(open_=True, laatste_contact=None)
    assert beoordeel_nummer(wacht, op_blacklist=False, grens=periode_grens(3, nu=NU)) == "nog_open"


def test_contact_op_de_grens_blokkeert():
    grens = periode_grens(3, nu=NU)
    assert beoordeel_nummer(info(laatste_contact=grens), op_blacklist=False, grens=grens) == "recent_contact"


def test_contact_net_voor_de_grens_is_nieuw():
    grens = periode_grens(3, nu=NU)
    net_ervoor = grens - timedelta(seconds=1)
    assert beoordeel_nummer(info(laatste_contact=net_ervoor), op_blacklist=False, grens=grens) == "nieuw"


def test_hele_database_blokkeert_elk_bestaand_nummer():
    heel_oud = info(laatste_contact=datetime(2019, 1, 1))
    assert beoordeel_nummer(heel_oud, op_blacklist=False, grens=None) == "recent_contact"


def test_bestaand_nummer_zonder_contactdatum_binnen_periode_is_nieuw():
    # Afgeronde rij zonder eerder contact: mag opnieuw, mits niet 'open'.
    assert beoordeel_nummer(info(), op_blacklist=False, grens=periode_grens(3, nu=NU)) == "nieuw"
