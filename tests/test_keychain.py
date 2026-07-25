"""Storing API keys in the macOS keychain.

Integration tests: they touch the real keychain. They use an account with the
"pytest-" prefix and delete it in the fixture, so as not to pollute the user's keys.
"""

import pytest

from voooxly import keychain

CUENTA = "pytest-proveedor-falso"


@pytest.fixture(autouse=True)
def limpia():
    keychain.delete_key(CUENTA)
    yield
    keychain.delete_key(CUENTA)


def test_guardar_y_recuperar():
    assert keychain.set_key(CUENTA, "sk-secreto-123") is True
    assert keychain.get_key(CUENTA) == "sk-secreto-123"


def test_cuenta_inexistente_da_none():
    assert keychain.get_key("pytest-no-existe-jamas") is None


def test_overwrite_replaces_value():
    keychain.set_key(CUENTA, "primera")
    keychain.set_key(CUENTA, "segunda")
    assert keychain.get_key(CUENTA) == "segunda"


def test_borrar_deja_la_cuenta_vacia():
    keychain.set_key(CUENTA, "efimera")
    assert keychain.delete_key(CUENTA) is True
    assert keychain.get_key(CUENTA) is None


def test_secreto_con_acentos_y_simbolos():
    """Keys are ASCII, but a base_url or an accidental paste need not be."""
    keychain.set_key(CUENTA, "clavé-ñ-€-🔑")
    assert keychain.get_key(CUENTA) == "clavé-ñ-€-🔑"
