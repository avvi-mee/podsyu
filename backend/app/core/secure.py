"""Encrypt OAuth tokens at rest with Windows DPAPI (bound to the current Windows user account)."""
import ctypes
import sys
from ctypes import wintypes


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _call(fn, data: bytes) -> bytes:
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in, blob_out = _Blob(len(data), buf), _Blob()
    if not fn(ctypes.byref(blob_in), None, None, None, None, 0x01, ctypes.byref(blob_out)):  # UI_FORBIDDEN
        raise OSError("DPAPI call failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def encrypt(data: bytes) -> bytes:
    if sys.platform != "win32":
        return data  # shortcut: no OS keystore off Windows; file permissions only. Upgrade with `keyring` if needed.
    return b"DPAPI" + _call(ctypes.windll.crypt32.CryptProtectData, data)


def decrypt(data: bytes) -> bytes:
    if data.startswith(b"DPAPI"):
        return _call(ctypes.windll.crypt32.CryptUnprotectData, data[5:])
    return data


def _keys_path():
    from app.core.config import SECRETS_DIR

    return SECRETS_DIR / "api_keys.bin"


def get_key(name: str) -> str:
    """Third-party API key (Reddit, Pexels...) stored encrypted on this PC. Empty string when not set."""
    import json

    p = _keys_path()
    return json.loads(decrypt(p.read_bytes())).get(name, "") if p.exists() else ""


def set_key(name: str, value: str):
    import json

    p = _keys_path()
    keys = json.loads(decrypt(p.read_bytes())) if p.exists() else {}
    if value:
        keys[name] = value
    else:
        keys.pop(name, None)
    p.write_bytes(encrypt(json.dumps(keys).encode()))


if __name__ == "__main__":
    secret = b'{"refresh_token": "abc"}'
    enc = encrypt(secret)
    assert enc != secret and decrypt(enc) == secret
    print("dpapi ok")
