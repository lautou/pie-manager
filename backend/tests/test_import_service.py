"""
Pure unit tests for app/services/import_service.py's resolve_row — no DB, no HTTP.

This is the highest-risk piece of the bulk-import feature: every "Sens" value's mapping to
type/operation/signed quantity/unit_price is exercised explicitly here, one accept-case test
per Sens value plus one reject-case test per validation rule. See CLAUDE.md's "Bulk
transaction import (Excel)" section for the full Sens table this mirrors.
"""
from datetime import date

import pytest

from app.models import Broker, Portfolio, PortfolioAccount, Product
from app.services import import_service as svc


def _ref(portfolios=None, brokers=None, pairs=None, products=None) -> svc.ReferenceData:
    return svc.ReferenceData(
        portfolios_by_name={p.name: p for p in (portfolios or [])},
        brokers_by_name=_group_by_name(brokers or []),
        portfolio_account_pairs=set(pairs or []),
        products_by_ticker={p.ticker: p for p in (products or [])},
    )


def _group_by_name(brokers):
    out: dict[str, list[Broker]] = {}
    for b in brokers:
        out.setdefault(b.name, []).append(b)
    return out


@pytest.fixture
def base_ref():
    portfolio = Portfolio(id=1, name="Portfolio1")
    broker = Broker(id=1, name="Degiro", currency="EUR")
    eur_etf = Product(ticker="FLXC.DE", name="ETF Monde", category="Actif", instrument_type="ETF", currency="EUR")
    usd_action = Product(ticker="AAPL", name="Apple", category="Actif", instrument_type="Action", currency="USD")
    cash_eur = Product(ticker="LIQUIDITE.EURO", name="Cash EUR", category="Actif", instrument_type="Cash", currency="EUR")
    forex_jpy = Product(ticker="JPYEUR=X", name="JPY", category="Actif", instrument_type="Cash", currency="EUR")
    gold = Product(ticker="OR.PHYSIQUE", name="Or", category="Actif", instrument_type="Or physique", currency="EUR")
    frais = Product(ticker="FRAIS.TENUE.EUR", name="Tenue de compte", category="Frais", fee_type="Tenue de compte", currency="EUR")
    ttf_eligible = Product(ticker="TTE.PA", name="TotalEnergies", category="Actif", instrument_type="Action", currency="EUR", is_ttf_eligible=True)
    return _ref(
        portfolios=[portfolio], brokers=[broker], pairs=[(1, 1)],
        products=[eur_etf, usd_action, cash_eur, forex_jpy, gold, frais, ttf_eligible],
    )


def _row(**overrides) -> dict:
    base = {
        "Portefeuille": "Portfolio1", "Compte": "Degiro", "Sens": "Achat", "Ticker": "FLXC.DE",
        "Date": date(2026, 1, 5), "Quantité": 10, "Prix unitaire": 45.2, "Devise": "EUR",
        "Taux de change": 1.0, "Courtage (EUR)": 0, "TTF (EUR)": 0,
    }
    base.update(overrides)
    return base


# ── One accept-case test per Sens value ─────────────────────────────────────

def test_achat_accept(base_ref):
    r = svc.resolve_row(2, _row(Sens="Achat", **{"Courtage (EUR)": 2.5}), base_ref)
    assert r.status == "ok"
    assert r.resolved.type == "Actif" and r.resolved.operation == "Achat"
    assert r.resolved.quantity == -10.0 and r.resolved.unit_price == 45.2
    assert r.resolved.courtage_eur == 2.5


def test_vente_accept(base_ref):
    r = svc.resolve_row(2, _row(Sens="Vente"), base_ref)
    assert r.status == "ok"
    assert r.resolved.operation == "Vente"
    assert r.resolved.quantity == 10.0


def test_achat_or_physique_accept(base_ref):
    row = _row(Sens="Achat Or physique", Ticker="OR.PHYSIQUE", Quantité=1, **{"Prix unitaire": 1850.0})
    r = svc.resolve_row(2, row, base_ref)
    assert r.status == "ok", r.errors
    assert r.resolved.quantity == -1 and r.resolved.unit_price == 1850.0


def test_vente_or_physique_accept(base_ref):
    row = _row(Sens="Vente Or physique", Ticker="OR.PHYSIQUE", Quantité=1, **{"Prix unitaire": 2100.0})
    r = svc.resolve_row(2, row, base_ref)
    assert r.status == "ok", r.errors
    assert r.resolved.quantity == 1 and r.resolved.unit_price == 2100.0


def test_or_physique_blank_quantity_defaults_to_one(base_ref):
    row = _row(Sens="Achat Or physique", Ticker="OR.PHYSIQUE", Quantité=None, **{"Prix unitaire": 1850.0})
    r = svc.resolve_row(2, row, base_ref)
    assert r.status == "ok", r.errors
    assert r.resolved.quantity == -1


def test_attribution_accept(base_ref):
    row = _row(Sens="Attribution", **{"Prix unitaire": 0.0})
    r = svc.resolve_row(2, row, base_ref)
    assert r.status == "ok", r.errors
    assert r.resolved.operation == "Attribution"
    assert r.resolved.quantity == -10.0
    assert r.resolved.unit_price == 0.0


def test_depot_accept(base_ref):
    row = _row(Sens="Dépôt", Ticker="LIQUIDITE.EURO", Quantité=1000, **{"Prix unitaire": None})
    r = svc.resolve_row(2, row, base_ref)
    assert r.status == "ok", r.errors
    assert r.resolved.operation is None
    assert r.resolved.quantity == 1000.0
    assert r.resolved.unit_price == 1.0


def test_retrait_accept_with_withdrawal_fee(base_ref):
    row = _row(Sens="Retrait", Ticker="LIQUIDITE.EURO", Quantité=200, **{"Prix unitaire": None}, **{"Courtage (EUR)": 5.0})
    r = svc.resolve_row(2, row, base_ref)
    assert r.status == "ok", r.errors
    assert r.resolved.quantity == -200.0
    assert r.resolved.courtage_eur == 5.0


def test_revenu_accept(base_ref):
    row = _row(Sens="Revenu", **{"Prix unitaire": 1.35}, Quantité=12)
    r = svc.resolve_row(2, row, base_ref)
    assert r.status == "ok", r.errors
    assert r.resolved.type == "Revenu"
    assert r.resolved.operation is None
    assert r.resolved.quantity == 12.0


def test_frais_accept(base_ref):
    row = _row(Sens="Frais", Ticker="FRAIS.TENUE.EUR", Quantité=1, **{"Prix unitaire": 12.0})
    r = svc.resolve_row(2, row, base_ref)
    assert r.status == "ok", r.errors
    assert r.resolved.type == "Frais"
    assert r.resolved.quantity == -1


def test_frais_blank_quantity_defaults_to_one(base_ref):
    row = _row(Sens="Frais", Ticker="FRAIS.TENUE.EUR", Quantité=None, **{"Prix unitaire": 12.0})
    r = svc.resolve_row(2, row, base_ref)
    assert r.status == "ok", r.errors
    assert r.resolved.quantity == -1


def test_achat_non_eur_with_exchange_rate(base_ref):
    row = _row(Ticker="AAPL", Devise="USD", **{"Taux de change": 0.92}, **{"Prix unitaire": 120.0})
    r = svc.resolve_row(2, row, base_ref)
    assert r.status == "ok", r.errors
    assert r.resolved.currency == "USD" and r.resolved.exchange_rate == 0.92


def test_forex_position_depot_uses_ticker_prefix_currency(base_ref):
    row = _row(Sens="Dépôt", Ticker="JPYEUR=X", Devise="JPY", **{"Taux de change": 0.0061},
               Quantité=50000, **{"Prix unitaire": None})
    r = svc.resolve_row(2, row, base_ref)
    assert r.status == "ok", r.errors
    assert r.resolved.currency == "JPY"
    assert r.resolved.quantity == 50000.0


# ── Reject-case tests, one per validation rule ──────────────────────────────

def test_reject_unknown_sens(base_ref):
    r = svc.resolve_row(2, _row(Sens="Bourse"), base_ref)
    assert r.status == "error"
    assert any("Sens" in e for e in r.errors)


def test_reject_unknown_portfolio(base_ref):
    r = svc.resolve_row(2, _row(Portefeuille="Ghost"), base_ref)
    assert r.status == "error"
    assert any("Portefeuille" in e for e in r.errors)


def test_blank_portfolio_and_broker_render_as_placeholder_not_python_none(base_ref):
    """A blank cell reads as Python None — must never leak into the error message as the
    literal text "None" (found via live QA testing with a genuinely blank row)."""
    r = svc.resolve_row(2, _row(Portefeuille=None, Compte=None), base_ref)
    assert r.status == "error"
    assert any("(vide)" in e for e in r.errors)
    assert not any("None" in e for e in r.errors)


def test_blank_devise_renders_as_placeholder_not_python_none(base_ref):
    r = svc.resolve_row(2, _row(Devise=None), base_ref)
    assert r.status == "error"
    assert any("(vide)" in e for e in r.errors)
    assert not any("'None'" in e for e in r.errors)


def test_reject_unknown_broker(base_ref):
    r = svc.resolve_row(2, _row(Compte="Ghost Bank"), base_ref)
    assert r.status == "error"
    assert any("Compte" in e for e in r.errors)


def test_reject_ambiguous_broker_name(base_ref):
    base_ref.brokers_by_name["Degiro"].append(Broker(id=2, name="Degiro", currency="EUR"))
    r = svc.resolve_row(2, _row(), base_ref)
    assert r.status == "error"
    assert any("ambigu" in e for e in r.errors)


def test_reject_broker_not_linked_to_portfolio(base_ref):
    base_ref.portfolio_account_pairs.clear()
    r = svc.resolve_row(2, _row(), base_ref)
    assert r.status == "error"
    assert any("rattaché" in e for e in r.errors)


def test_reject_unknown_ticker(base_ref):
    r = svc.resolve_row(2, _row(Ticker="GHOST.PA"), base_ref)
    assert r.status == "error"
    assert any("Ticker" in e for e in r.errors)


def test_reject_achat_on_cash_ticker(base_ref):
    row = _row(Sens="Achat", Ticker="LIQUIDITE.EURO", **{"Prix unitaire": 1.0})
    r = svc.resolve_row(2, row, base_ref)
    assert r.status == "error"
    assert any("compatible" in e for e in r.errors)


def test_reject_depot_on_non_cash_ticker(base_ref):
    r = svc.resolve_row(2, _row(Sens="Dépôt"), base_ref)
    assert r.status == "error"
    assert any("compatible" in e for e in r.errors)


def test_reject_achat_or_physique_on_etf_ticker(base_ref):
    row = _row(Sens="Achat Or physique", Quantité=1, **{"Prix unitaire": 100.0})
    r = svc.resolve_row(2, row, base_ref)
    assert r.status == "error"
    assert any("compatible" in e for e in r.errors)


def test_reject_frais_sens_on_asset_ticker(base_ref):
    row = _row(Sens="Frais", Quantité=1, **{"Prix unitaire": 12.0})
    r = svc.resolve_row(2, row, base_ref)
    assert r.status == "error"
    assert any("compatible" in e for e in r.errors)


def test_reject_devise_mismatch_normal_ticker(base_ref):
    r = svc.resolve_row(2, _row(Devise="USD"), base_ref)
    assert r.status == "error"
    assert any("Devise" in e for e in r.errors)


def test_reject_devise_mismatch_forex_ticker(base_ref):
    row = _row(Sens="Dépôt", Ticker="JPYEUR=X", Devise="EUR", **{"Taux de change": 1.0},
               Quantité=50000, **{"Prix unitaire": None})
    r = svc.resolve_row(2, row, base_ref)
    assert r.status == "error"
    assert any("Devise" in e for e in r.errors)


def test_reject_exchange_rate_zero(base_ref):
    row = _row(Ticker="AAPL", Devise="USD", **{"Taux de change": 0.0}, **{"Prix unitaire": 100.0})
    r = svc.resolve_row(2, row, base_ref)
    assert r.status == "error"
    assert any("Taux de change" in e for e in r.errors)


def test_reject_exchange_rate_missing_for_non_eur(base_ref):
    row = _row(Ticker="AAPL", Devise="USD", **{"Taux de change": None}, **{"Prix unitaire": 100.0})
    r = svc.resolve_row(2, row, base_ref)
    assert r.status == "error"
    assert any("Taux de change requis" in e for e in r.errors)


def test_reject_exchange_rate_not_one_on_eur_row(base_ref):
    r = svc.resolve_row(2, _row(**{"Taux de change": 1.2}), base_ref)
    assert r.status == "error"
    assert any("1.0" in e for e in r.errors)


def test_blank_exchange_rate_defaults_to_one_on_eur_row(base_ref):
    r = svc.resolve_row(2, _row(**{"Taux de change": None}), base_ref)
    assert r.status == "ok", r.errors
    assert r.resolved.exchange_rate == 1.0


def test_reject_unparseable_price(base_ref):
    r = svc.resolve_row(2, _row(**{"Prix unitaire": "abc"}), base_ref)
    assert r.status == "error"
    assert any("Prix unitaire" in e for e in r.errors)


def test_reject_unparseable_exchange_rate(base_ref):
    r = svc.resolve_row(2, _row(**{"Taux de change": "abc"}), base_ref)
    assert r.status == "error"
    assert any("Taux de change" in e for e in r.errors)


def test_reject_unparseable_courtage(base_ref):
    r = svc.resolve_row(2, _row(**{"Courtage (EUR)": "abc"}), base_ref)
    assert r.status == "error"
    assert any("Courtage" in e for e in r.errors)


def test_reject_unparseable_ttf(base_ref):
    r = svc.resolve_row(2, _row(**{"TTF (EUR)": "abc"}), base_ref)
    assert r.status == "error"
    assert any("TTF" in e for e in r.errors)


def test_attribution_blank_price_defaults_to_zero(base_ref):
    row = _row(Sens="Attribution", **{"Prix unitaire": None})
    r = svc.resolve_row(2, row, base_ref)
    assert r.status == "ok", r.errors
    assert r.resolved.unit_price == 0.0


def test_reject_attribution_negative_price(base_ref):
    row = _row(Sens="Attribution", **{"Prix unitaire": -5.0})
    r = svc.resolve_row(2, row, base_ref)
    assert r.status == "error"
    assert any("négatif" in e for e in r.errors)


def test_reject_ttf_negative(base_ref):
    r = svc.resolve_row(2, _row(**{"TTF (EUR)": -1.0}), base_ref)
    assert r.status == "error"
    assert any("TTF" in e for e in r.errors)


def test_reject_quantity_zero_or_negative(base_ref):
    r = svc.resolve_row(2, _row(Quantité=0), base_ref)
    assert r.status == "error"
    assert any("Quantité" in e for e in r.errors)


def test_reject_or_physique_quantity_not_one(base_ref):
    row = _row(Sens="Achat Or physique", Ticker="OR.PHYSIQUE", Quantité=5, **{"Prix unitaire": 1850.0})
    r = svc.resolve_row(2, row, base_ref)
    assert r.status == "error"
    assert any("Quantité doit valoir" in e for e in r.errors)


def test_reject_price_zero_or_negative_as_entered(base_ref):
    r = svc.resolve_row(2, _row(**{"Prix unitaire": 0}), base_ref)
    assert r.status == "error"
    assert any("Prix unitaire" in e for e in r.errors)


def test_reject_depot_price_not_one(base_ref):
    row = _row(Sens="Dépôt", Ticker="LIQUIDITE.EURO", Quantité=1000, **{"Prix unitaire": 2.0})
    r = svc.resolve_row(2, row, base_ref)
    assert r.status == "error"
    assert any("1.0" in e for e in r.errors)


def test_reject_courtage_negative(base_ref):
    r = svc.resolve_row(2, _row(**{"Courtage (EUR)": -1}), base_ref)
    assert r.status == "error"
    assert any("Courtage" in e for e in r.errors)


def test_reject_courtage_on_attribution(base_ref):
    row = _row(Sens="Attribution", **{"Prix unitaire": 0.0}, **{"Courtage (EUR)": 5.0})
    r = svc.resolve_row(2, row, base_ref)
    assert r.status == "error"
    assert any("Courtage" in e for e in r.errors)


def test_reject_ttf_on_vente(base_ref):
    row = _row(Sens="Vente", **{"TTF (EUR)": 1.0})
    r = svc.resolve_row(2, row, base_ref)
    assert r.status == "error"
    assert any("TTF" in e for e in r.errors)


def test_reject_ttf_on_depot(base_ref):
    row = _row(Sens="Dépôt", Ticker="LIQUIDITE.EURO", Quantité=1000, **{"Prix unitaire": None}, **{"TTF (EUR)": 1.0})
    r = svc.resolve_row(2, row, base_ref)
    assert r.status == "error"
    assert any("TTF" in e for e in r.errors)


def test_ttf_soft_warning_when_product_not_eligible(base_ref):
    row = _row(**{"TTF (EUR)": 1.5})
    r = svc.resolve_row(2, row, base_ref)
    assert r.status == "ok", r.errors
    assert any("éligible TTF" in w for w in r.warnings)


def test_ttf_no_warning_when_product_eligible(base_ref):
    row = _row(Ticker="TTE.PA", **{"TTF (EUR)": 1.5})
    r = svc.resolve_row(2, row, base_ref)
    assert r.status == "ok", r.errors
    assert r.warnings == []


def test_reject_invalid_date(base_ref):
    r = svc.resolve_row(2, _row(Date="not-a-date"), base_ref)
    assert r.status == "error"
    assert any("Date" in e for e in r.errors)


def test_reject_missing_date(base_ref):
    r = svc.resolve_row(2, _row(Date=None), base_ref)
    assert r.status == "error"
    assert any("Date manquante" in e for e in r.errors)


def test_date_accepts_iso_string(base_ref):
    r = svc.resolve_row(2, _row(Date="2026-01-05"), base_ref)
    assert r.status == "ok", r.errors
    assert r.resolved.date == date(2026, 1, 5)


def test_date_accepts_datetime(base_ref):
    from datetime import datetime
    r = svc.resolve_row(2, _row(Date=datetime(2026, 1, 5, 10, 30)), base_ref)
    assert r.status == "ok", r.errors
    assert r.resolved.date == date(2026, 1, 5)


def test_reject_non_numeric_quantity(base_ref):
    r = svc.resolve_row(2, _row(Quantité="abc"), base_ref)
    assert r.status == "error"
    assert any("Quantité" in e for e in r.errors)


def test_multiple_errors_accumulate(base_ref):
    r = svc.resolve_row(2, _row(Portefeuille="Ghost", Ticker="GHOST.PA"), base_ref)
    assert r.status == "error"
    assert len(r.errors) >= 2


def test_comma_decimal_separator_accepted(base_ref):
    row = _row(**{"Prix unitaire": "45,20"})
    r = svc.resolve_row(2, row, base_ref)
    assert r.status == "ok", r.errors
    assert r.resolved.unit_price == 45.2


def test_whitespace_on_text_fields_is_stripped_before_lookup(base_ref):
    """A cell with stray leading/trailing whitespace (common from copy-pasting a broker
    statement into Excel) must still resolve — found via live QA testing."""
    row = _row(
        Portefeuille=" Portfolio1 ", Compte=" Degiro", Sens=" Achat ", Ticker="FLXC.DE ", Devise=" EUR ",
    )
    r = svc.resolve_row(2, row, base_ref)
    assert r.status == "ok", r.errors
    assert r.resolved.ticker == "FLXC.DE"
    assert r.resolved.currency == "EUR"


def test_whitespace_only_portfolio_is_treated_as_blank(base_ref):
    row = _row(Portefeuille="   ")
    r = svc.resolve_row(2, row, base_ref)
    assert r.status == "error"
    assert any("(vide)" in e for e in r.errors)
