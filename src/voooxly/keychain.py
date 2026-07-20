"""API keys en el llavero de macOS.

Se usa el framework Security directamente (SecItemAdd/SecItemCopyMatching) y NO
el binario /usr/bin/security: así la ACL del ítem queda ligada a Voooxly, que es
quien lo crea y quien lo lee. Con el CLI el ítem pertenece a /usr/bin/security y
macOS pide aprobar un diálogo al releerlo — es exactamente lo que le pasa a
notarytool en este proyecto ("No Keychain password item found for profile").
"""
from __future__ import annotations

import logging

log = logging.getLogger("voooxly.keychain")

SERVICE = "com.eduardocrovetto.voooxly"

_ERR_ITEM_NOT_FOUND = -25300


def _base_query(account: str) -> dict:
    import Security

    return {
        Security.kSecClass: Security.kSecClassGenericPassword,
        Security.kSecAttrService: SERVICE,
        Security.kSecAttrAccount: account,
    }


def get_key(account: str) -> str | None:
    """Devuelve el secreto, o None si no existe (o si el llavero no colabora)."""
    try:
        import Security

        query = _base_query(account)
        query[Security.kSecReturnData] = True
        query[Security.kSecMatchLimit] = Security.kSecMatchLimitOne
        status, data = Security.SecItemCopyMatching(query, None)
        if status != 0 or data is None:
            if status != _ERR_ITEM_NOT_FOUND:
                log.warning("Llavero: lectura de %r devolvió estado %s", account, status)
            return None
        return bytes(data).decode("utf-8")
    except Exception:
        log.warning("Llavero: no pude leer %r", account, exc_info=True)
        return None


def set_key(account: str, secret: str) -> bool:
    """Guarda (o reemplaza) el secreto. True si quedó guardado."""
    try:
        import Security

        delete_key(account)  # SecItemAdd falla con duplicados; reemplazar es lo esperado
        attrs = _base_query(account)
        attrs[Security.kSecValueData] = secret.encode("utf-8")
        status, _ = Security.SecItemAdd(attrs, None)
        if status != 0:
            log.warning("Llavero: guardar %r devolvió estado %s", account, status)
            return False
        return True
    except Exception:
        log.warning("Llavero: no pude guardar %r", account, exc_info=True)
        return False


def delete_key(account: str) -> bool:
    """Borra el secreto. True si ya no está (tanto si lo borró como si no existía)."""
    try:
        import Security

        # A diferencia de SecItemAdd/SecItemCopyMatching (que tienen un
        # parámetro de salida CFTypeRef y pyobjc los envuelve en tupla),
        # SecItemDelete no tiene salida: devuelve el OSStatus pelado.
        status = Security.SecItemDelete(_base_query(account))
        return status in (0, _ERR_ITEM_NOT_FOUND)
    except Exception:
        log.warning("Llavero: no pude borrar %r", account, exc_info=True)
        return False
