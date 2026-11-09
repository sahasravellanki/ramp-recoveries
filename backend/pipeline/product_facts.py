"""Country of origin and HTS chapter for a SKU.

A country printed on the invoice is used as stated. A country the rules (or,
in live mode, the model) fill in for a blank invoice is marked inferred. A
price claim that rests only on inferred origin is capped at Low strength.
"""

from __future__ import annotations

from .tariffs import normalize_country

# Longest prefix wins. Chapters are the sample catalog's, not a binding ruling.
_HTS_PREFIXES: list[tuple[str, str]] = sorted(
    [
        ("HP-TAMP", "82"),
        ("HP-PITCH", "82"),
        ("HP-", "84"),
        ("NWP-LID", "39"),
        ("NWP-HLID", "39"),
        ("NWP-CLID", "39"),
        ("NWP-", "48"),
        ("ALT-", "85"),
        ("KST-APR", "62"),
        ("KST-TEE", "62"),
        ("KST-CAP", "62"),
        ("KST-", "63"),
        ("BOS-", "48"),
        ("MLA-", "72"),
        ("GWG-TAMP", "82"),
        ("GWG-", "84"),
        ("MKT-", "69"),
        ("HMK-", "69"),
        ("ERP-", "48"),
        ("LVP-TWL", "63"),
        ("LVP-", "48"),
        ("CIM-", "84"),
        ("LUM-", "48"),
    ],
    key=lambda pair: len(pair[0]),
    reverse=True,
)

_DESCRIPTION_ORIGINS: list[tuple[str, str]] = [
    ("made in the usa", "US"),
    ("made in usa", "US"),
    ("made in italy", "IT"),
    ("made in vietnam", "VN"),
    ("made in china", "CN"),
    ("(usa)", "US"),
    ("(us)", "US"),
    ("(italy)", "IT"),
    ("(vietnam)", "VN"),
    ("(china)", "CN"),
    ("italy", "IT"),
    ("vietnam", "VN"),
    ("china", "CN"),
    ("mexico", "MX"),
    ("canada", "CA"),
]


def resolve_origin(stated: str | None, description: str) -> tuple[str | None, bool]:
    """Return (country, inferred). A stated country is never inferred."""
    code = normalize_country(stated)
    if code is not None:
        return code, False
    text = description.lower()
    for needle, country in _DESCRIPTION_ORIGINS:
        if needle in text:
            return country, True
    # The sample leaves origin off one espresso part on purpose. The suggestion
    # is marked inferred and cannot support a High or Medium claim by itself.
    if "group head" in text or "origin not printed" in text:
        return "IT", True
    return None, True


def resolve_hts(stated: str | None, sku: str, description: str) -> tuple[str | None, bool]:
    if stated and stated.strip():
        return stated.strip(), False
    for prefix, chapter in _HTS_PREFIXES:
        if sku.startswith(prefix):
            return chapter, True
    text = description.lower()
    if "steel" in text or "aluminum" in text:
        return "72", True
    if "group head" in text or "espresso" in text:
        return "84", True
    return None, False
