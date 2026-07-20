"""Guardado de API keys en el llavero de macOS.

Tests de integración: tocan el llavero real. Usan una cuenta con prefijo
"pytest-" y la borran en el fixture, para no ensuciar las claves del usuario.
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


def test_sobrescribir_reemplaza_el_valor():
    keychain.set_key(CUENTA, "primera")
    keychain.set_key(CUENTA, "segunda")
    assert keychain.get_key(CUENTA) == "segunda"


def test_borrar_deja_la_cuenta_vacia():
    keychain.set_key(CUENTA, "efimera")
    assert keychain.delete_key(CUENTA) is True
    assert keychain.get_key(CUENTA) is None


def test_secreto_con_acentos_y_simbolos():
    """Las keys son ASCII, pero un base_url o un pegado accidental no tienen por qué."""
    keychain.set_key(CUENTA, "clavé-ñ-€-🔑")
    assert keychain.get_key(CUENTA) == "clavé-ñ-€-🔑"
