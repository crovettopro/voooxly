"""API keys in the macOS keychain.

This uses the Security framework directly (SecItemAdd/SecItemCopyMatching) and
NOT the /usr/bin/security binary: that way the item's ACL is bound to Voooxly,
which is what creates it and what reads it. With the CLI the item belongs to
/usr/bin/security and macOS puts up a dialog to approve every re-read — exactly
what happens to notarytool in this project ("No Keychain password item found
for profile").
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
    """Return the secret, or None if it doesn't exist (or the keychain won't play)."""
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

        delete_key(account)  # SecItemAdd fails on duplicates; replacing is what's expected
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
