"""IEEPA tariff actions by country, with the dates and rates used to test a price.

Every refundable rate below is taken from a CBP notice or a Federal Register
presidential document. Section 232 and Section 301 are listed so a reviewer
can see them, and they never enter the refundable rate.

Not modeled, and said so in the README: USMCA-qualifying goods, the 10%
energy and potash rates, in-transit exceptions, and the European Union rule
that the extra duty is 15% minus the Column 1 rate (this table uses 15% for
an EU good, which is the extra duty when Column 1 is zero).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from functools import lru_cache

# Share of the unit price treated as import cost when a SKU does not say.
DEFAULT_IMPORT_SHARE = Decimal("0.6")

_CBP_FACTSHEET = "https://www.cbp.gov/sites/default/files/2025-05/new_tariff_requirements_2025_factsheet_05-02-25.pdf"
_CBP_STATEMENT = "https://www.cbp.gov/newsroom/announcements/official-cbp-statement-tariffs"
_EO_14257 = "https://www.federalregister.gov/documents/2025/04/07/2025-06063/regulating-imports-with-a-reciprocal-tariff-to-rectify-trade-practices-that-contribute-to-large-and"
_CSMS_64649265 = "https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3da7831"
_FR_2025_06462 = "https://www.federalregister.gov/documents/2025/04/15/2025-06462/modifying-reciprocal-tariff-rates-to-reflect-trading-partner-retaliation-and-alignment"
_CBP_FAQ = "https://www.cbp.gov/trade/programs-administration/trade-remedies/IEEPA-FAQ"
_EO_14298 = "https://www.whitehouse.gov/presidential-actions/2025/05/modifying-reciprocal-tariff-rates-to-reflect-discussions-with-the-peoples-republic-of-china/"
_CSMS_65573545 = "https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3e892a9"
_EO_14326 = "https://www.whitehouse.gov/presidential-actions/2025/07/further-modifying-the-reciprocal-tariff-rates/"
_CSMS_65829726 = "https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3ec7b5e"


@dataclass(frozen=True)
class RateIncrease:
    """One day the stacked IEEPA rate for a country went up."""

    country: str
    effective: date
    rate_before: Decimal
    rate_after: Decimal
    actions: tuple[TariffAction, ...]


@dataclass(frozen=True)
class TariffAction:
    action_id: str
    country: str
    name: str
    rate: Decimal
    effective: date
    ends: date | None
    refundable: bool
    citation: str
    source_url: str
    note: str = ""


def _row(
    action_id: str,
    country: str,
    name: str,
    rate: str,
    effective: date,
    ends: date | None,
    citation: str,
    source_url: str,
    note: str = "",
    refundable: bool = True,
) -> TariffAction:
    return TariffAction(action_id, country, name, Decimal(rate), effective, ends, refundable, citation, source_url, note)


# Country-specific reciprocal rates from Annex I of EO 14326, goods entered on
# or after August 7, 2025. A country that is not listed stays at the 10% baseline.
_ANNEX_I_AUG7: dict[str, str] = {
    "AF": "0.15", "DZ": "0.30", "AO": "0.15", "BD": "0.20", "BO": "0.15", "BA": "0.30",
    "BW": "0.15", "BR": "0.10", "BN": "0.25", "KH": "0.19", "CM": "0.15", "TD": "0.15",
    "CR": "0.15", "CI": "0.15", "CD": "0.15", "EC": "0.15", "GQ": "0.15", "FK": "0.10",
    "FJ": "0.15", "GH": "0.15", "GY": "0.15", "IS": "0.15", "IN": "0.25", "ID": "0.19",
    "IQ": "0.35", "IL": "0.15", "JP": "0.15", "JO": "0.15", "KZ": "0.25", "LA": "0.40",
    "LS": "0.15", "LY": "0.30", "LI": "0.15", "MG": "0.15", "MW": "0.15", "MY": "0.19",
    "MU": "0.15", "MD": "0.25", "MZ": "0.15", "MM": "0.40", "NA": "0.15", "NR": "0.15",
    "NZ": "0.15", "NI": "0.18", "NG": "0.15", "MK": "0.15", "NO": "0.15", "PK": "0.19",
    "PG": "0.15", "PH": "0.19", "RS": "0.35", "ZA": "0.30", "KR": "0.15", "LK": "0.20",
    "CH": "0.39", "SY": "0.41", "TW": "0.20", "TH": "0.19", "TT": "0.15", "TN": "0.25",
    "TR": "0.15", "UG": "0.15", "GB": "0.10", "VU": "0.15", "VE": "0.15", "VN": "0.20",
    "ZM": "0.15", "ZW": "0.15",
}

# The EU rate is not a flat Annex I number. For a good whose Column 1 duty is
# under 15%, the reciprocal duty brings the sum to 15%. This table uses 15%,
# which is that extra duty when Column 1 is zero.
_EU = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
    "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK",
    "SI", "ES", "SE",
}

_NAMES = {
    "US": "US", "USA": "US", "UNITED STATES": "US", "UNITED STATES OF AMERICA": "US",
    "CN": "CN", "CHINA": "CN", "PRC": "CN",
    "HK": "CN", "HONG KONG": "CN", "MO": "CN", "MACAU": "CN", "MACAO": "CN",
    "CA": "CA", "CANADA": "CA", "MX": "MX", "MEXICO": "MX",
    "IT": "IT", "ITALY": "IT", "VN": "VN", "VIETNAM": "VN", "VIET NAM": "VN",
    "GB": "GB", "UK": "GB", "UNITED KINGDOM": "GB",
    "JP": "JP", "JAPAN": "JP", "KR": "KR", "SOUTH KOREA": "KR", "KOREA": "KR",
    "TW": "TW", "TAIWAN": "TW", "IN": "IN", "INDIA": "IN",
    "DE": "DE", "GERMANY": "DE", "FR": "FR", "FRANCE": "FR",
}


def normalize_country(raw: str | None) -> str | None:
    if raw is None:
        return None
    key = " ".join(raw.strip().upper().split())
    if not key:
        return None
    if key in _NAMES:
        return _NAMES[key]
    if len(key) == 2 and key.isalpha():
        return key
    return None


def _border_actions(country: str) -> list[TariffAction]:
    if country == "CN":
        return [
            _row("cn-fentanyl-10", "CN", "China fentanyl IEEPA tariff", "0.10", date(2025, 2, 4), date(2025, 3, 4),
                 "CBP factsheet, May 2, 2025; additional China tariff effective February 4, 2025", _CBP_FACTSHEET,
                 "Replaced by the 20% rate on March 4, 2025. Hong Kong and Macau follow China."),
            _row("cn-fentanyl-20", "CN", "China fentanyl IEEPA tariff", "0.20", date(2025, 3, 4), None,
                 "CBP statement on tariffs; China and Hong Kong additional duty increased from 10% to 20% on March 4, 2025",
                 _CBP_STATEMENT, "Stacks with the reciprocal tariff."),
        ]
    if country == "CA":
        return [
            _row("ca-border-25", "CA", "Canada border IEEPA tariff", "0.25", date(2025, 3, 4), None,
                 "CBP statement on tariffs; additional 25% on non-USMCA goods from Canada, in force March 4, 2025",
                 _CBP_STATEMENT, "USMCA-qualifying goods, and the 10% energy rate, are not modeled."),
        ]
    if country == "MX":
        return [
            _row("mx-border-25", "MX", "Mexico border IEEPA tariff", "0.25", date(2025, 3, 4), None,
                 "CBP factsheet, May 2, 2025; Mexico tariff effective March 4, 2025. USMCA exemption amended March 7, 2025",
                 _CBP_FACTSHEET, "The 10% potash rate is not modeled."),
        ]
    return []


def _reciprocal_action(country: str, day: date) -> TariffAction | None:
    if country in {"CA", "MX"} or day < date(2025, 4, 5):
        return None
    if country == "CN":
        if day < date(2025, 4, 9):
            return _row("cn-reciprocal-10", "CN", "China reciprocal tariff", "0.10", date(2025, 4, 5), date(2025, 4, 9),
                        "CSMS 64649265; HTS 9903.01.25 additional 10% from April 5, 2025", _CSMS_64649265,
                        "Stacked on the fentanyl tariff.")
        if day < date(2025, 4, 10):
            return _row("cn-reciprocal-84", "CN", "China reciprocal tariff", "0.84", date(2025, 4, 9), date(2025, 4, 10),
                        "CBP IEEPA FAQ; HTS 9903.01.63 additional 84% on April 9, 2025", _CBP_FAQ,
                        "One day. Replaced by 125% on April 10.")
        if day < date(2025, 5, 14):
            return _row("cn-reciprocal-125", "CN", "China reciprocal tariff", "1.25", date(2025, 4, 10), date(2025, 5, 14),
                        "90 FR 15625 (April 15, 2025), EO 14266; HTS 9903.01.63 additional 125% from April 10 through May 13, 2025",
                        _FR_2025_06462, "Stacked on the 20% fentanyl tariff.")
        return _row("cn-reciprocal-10-may", "CN", "China reciprocal tariff", "0.10", date(2025, 5, 14), None,
                    "EO 14298 (May 12, 2025), additional 10% from May 14, 2025. CSMS 65829726 (August 7, 2025) leaves this 10% in place",
                    _EO_14298, "Stacked on the 20% fentanyl tariff. Later revisions after that CSMS are not in this table.")
    if day < date(2025, 8, 7):
        return _row("reciprocal-10", "OTHER", "Reciprocal baseline", "0.10", date(2025, 4, 5), date(2025, 8, 7),
                    "EO 14257, 90 FR 15041; 10% from April 5, 2025. Country-specific rates were suspended April 10 and the suspension was extended to August 1",
                    _EO_14257, "Canada and Mexico are carved out. CSMS 65573545 extended the 10% baseline to August 1, 2025.")
    if country in _EU:
        return _row("eu-reciprocal-15", "EU", "European Union reciprocal tariff", "0.15", date(2025, 8, 7), None,
                    "EO 14326 (July 31, 2025), Annex I, goods entered on or after August 7, 2025",
                    _EO_14326, "The order sets the extra duty so Column 1 plus the reciprocal duty equals 15%, and sets the extra duty to zero when Column 1 is already 15% or more. This table uses 15%, the extra duty when Column 1 is zero.")
    rate = _ANNEX_I_AUG7.get(country, "0.10")
    if country in _ANNEX_I_AUG7:
        return _row(f"annex-{country.lower()}", country, f"{_place(country)} reciprocal tariff", rate, date(2025, 8, 7), None,
                    "EO 14326 (July 31, 2025), Annex I, goods entered on or after August 7, 2025",
                    _EO_14326, "Replaces the 10% baseline for this country.")
    return _row("reciprocal-10-continuing", "OTHER", "Reciprocal baseline", "0.10", date(2025, 8, 7), None,
                "EO 14326 (July 31, 2025); a trading partner not listed in Annex I stays at 10%",
                _EO_14326)


def actions_on(country: str | None, day: date, *, refundable_only: bool = True) -> list[TariffAction]:
    code = normalize_country(country)
    if code is None or code == "US":
        return []
    found = [action for action in _border_actions(code) if _in_force(action, day)]
    reciprocal = _reciprocal_action(code, day)
    if reciprocal is not None and _in_force(reciprocal, day):
        found.append(reciprocal)
    if refundable_only:
        return [action for action in found if action.refundable]
    return found


def _in_force(action: TariffAction, day: date) -> bool:
    if day < action.effective:
        return False
    if action.ends is not None and day >= action.ends:
        return False
    return True


def ieepa_rate(country: str | None, day: date) -> Decimal:
    return sum((action.rate for action in actions_on(country, day)), Decimal("0"))


def first_ieepa_date(country: str | None) -> date | None:
    increases = rate_increases(country)
    return increases[0].effective if increases else None


def _change_dates(country: str) -> list[date]:
    dates: set[date] = set()
    for action in _border_actions(country):
        dates.add(action.effective)
        if action.ends is not None:
            dates.add(action.ends)
    if country not in {"CA", "MX"}:
        dates.add(date(2025, 4, 5))
        if country == "CN":
            dates.update({date(2025, 4, 9), date(2025, 4, 10), date(2025, 5, 14)})
        else:
            dates.add(date(2025, 8, 7))
    return sorted(dates)


@lru_cache(maxsize=256)
def rate_increases(country: str | None) -> tuple[RateIncrease, ...]:
    """Days the stacked IEEPA rate went up. A later cut, such as China on May 14, is not one."""
    code = normalize_country(country)
    if code is None or code == "US":
        return ()
    found: list[RateIncrease] = []
    for day in _change_dates(code):
        before = ieepa_rate(code, day - timedelta(days=1))
        active = tuple(actions_on(code, day))
        after = sum((action.rate for action in active), Decimal("0"))
        if after <= before:
            continue
        started = tuple(action for action in active if action.effective == day) or active
        found.append(RateIncrease(code, day, before, after, started))
    return tuple(found)


def match_increase(country: str | None, jump: date, *, window_days: int = 90) -> RateIncrease | None:
    """The latest IEEPA rate increase whose 0-to-window_days window covers the jump."""
    covers = [
        inc
        for inc in rate_increases(country)
        if inc.effective <= jump <= inc.effective + timedelta(days=window_days)
    ]
    if not covers:
        return None
    return max(covers, key=lambda inc: inc.effective)


def increase_label(inc: RateIncrease) -> str:
    names = " and ".join(action.name for action in inc.actions) or "IEEPA tariff"
    before = f"{inc.rate_before * 100:.0f}%"
    after = f"{inc.rate_after * 100:.0f}%"
    return f"{names}, effective {inc.effective.isoformat()} (total rate {before} to {after})"


def _place(country: str) -> str:
    return {
        "VN": "Vietnam",
        "JP": "Japan",
        "KR": "South Korea",
        "TW": "Taiwan",
        "IN": "India",
        "GB": "United Kingdom",
        "DE": "Germany",
        "FR": "France",
        "TH": "Thailand",
        "ID": "Indonesia",
        "MY": "Malaysia",
        "BR": "Brazil",
        "CH": "Switzerland",
    }.get(country, country)


def rate_label(country: str | None, day: date) -> str:
    code = normalize_country(country) or "unknown"
    actions = actions_on(country, day)
    if not actions:
        return f"{code} has no IEEPA tariff in effect on {day.isoformat()}."
    parts = [f"{(action.rate * 100):.0f}% {action.name}" for action in actions]
    total = ieepa_rate(country, day) * 100
    return f"{code} total {total:.0f}% on {day.isoformat()}: " + "; ".join(parts) + "."


def documented_actions() -> list[TariffAction]:
    """The rows the README cites. One representative row per sourced action."""
    rows = _border_actions("CN") + _border_actions("CA") + _border_actions("MX")
    rows.append(_reciprocal_action("IT", date(2025, 4, 5)))
    rows.append(_reciprocal_action("CN", date(2025, 4, 5)))
    rows.append(_reciprocal_action("CN", date(2025, 4, 9)))
    rows.append(_reciprocal_action("CN", date(2025, 4, 10)))
    rows.append(_reciprocal_action("CN", date(2025, 5, 14)))
    rows.append(_reciprocal_action("IT", date(2025, 8, 7)))
    rows.append(_reciprocal_action("VN", date(2025, 8, 7)))
    rows.append(
        _row("section-232", "ANY", "Section 232 steel and aluminum", "0", date(2018, 3, 23), None,
             "Trade Expansion Act of 1962, section 232. Not an IEEPA action",
             "https://www.cbp.gov/trade/programs-administration/entry-summary/232-tariffs-aluminum-and-steel",
             "Not refundable. A Section 232 surcharge is tracked and never claimed.", refundable=False)
    )
    rows.append(
        _row("section-301", "CN", "Section 301 China tariffs", "0", date(2018, 7, 6), None,
             "Trade Act of 1974, section 301. Not an IEEPA action",
             "https://www.cbp.gov/trade/programs-administration/entry-summary/section-301-trade-remedies",
             "Not refundable. A Section 301 adjustment is tracked and never claimed.", refundable=False)
    )
    return [row for row in rows if row is not None]
