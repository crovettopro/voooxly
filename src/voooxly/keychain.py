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
                log.warning("Keychain: read of %r returned status %s", account, status)
            return None
        return bytes(data).decode("utf-8")
    except Exception:
        log.warning("Keychain: couldn't read %r", account, exc_info=True)
        return None


def set_key(account: str, secret: str) -> bool:
    """Stores (or replaces) the secret. True if it was saved."""
    try:
        import Security

        delete_key(account)  # SecItemAdd falla con duplicados; reemplazar es lo esperado
        attrs = _base_query(account)
        attrs[Security.kSecValueData] = secret.encode("utf-8")
        status, _ = Security.SecItemAdd(attrs, None)
        if status != 0:
            log.warning("Keychain: save of %r returned status %s", account, status)
            return False
        return True
    except Exception:
        log.warning("Keychain: couldn't save %r", account, exc_info=True)
        return False


def delete_key(account: str) -> bool:
    """Deletes the secret. True if it's gone (whether it deleted it or it never existed)."""
    try:
        import Security

        # Unlike SecItemAdd/SecItemCopyMatching (which take a CFTypeRef output
        # parameter that pyobjc wraps in a tuple), SecItemDelete has no
        # output: it returns the bare OSStatus.
        status = Security.SecItemDelete(_base_query(account))
        return status in (0, _ERR_ITEM_NOT_FOUND)
    except Exception:
        log.warning("Keychain: couldn't delete %r", account, exc_info=True)
        return False
