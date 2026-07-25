"""Which provider the user chose, stored in prefs.json.

Separate from app.py on purpose: instantiating VoooxlyApp builds AppKit menus
and can't be done in a test. There are only dictionaries here.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import providers

CLAVE_PROVEEDOR = "ai_provider"
CLAVE_BASE_URL = "ai_base_url"
CLAVE_MODELO = "ai_model"


@dataclass(frozen=True)
class Selection:
    provider: providers.Provider
    base_url: str
    model: str


def load(prefs: dict) -> Selection | None:
    """The saved choice, or None if there is no valid one."""
    key = prefs.get(CLAVE_PROVEEDOR)
    if not key:
        return None
    # A corrupt prefs.json can have ai_provider as a list or another type.
    # We don't raise: the app must start anyway.
    if not isinstance(key, str):
        return None
    prov = providers.get(key)
    if prov is None:
        # A preset removed in a later version can't take down the startup.
        return None
    return Selection(
        provider=prov,
        base_url=prefs.get(CLAVE_BASE_URL) or prov.base_url,
        model=prefs.get(CLAVE_MODELO) or prov.default_model,
    )


def save(prefs: dict, provider_key: str, base_url: str, model: str) -> dict:
    """Returns prefs with the choice set. Doesn't write to disk."""
    prov = providers.get(provider_key)
    if prov is None:
        raise ValueError(f"Proveedor desconocido: {provider_key!r}")
    prefs = dict(prefs)
    prefs[CLAVE_PROVEEDOR] = prov.key
    prefs[CLAVE_BASE_URL] = base_url or prov.base_url
    prefs[CLAVE_MODELO] = model or prov.default_model
    return prefs
