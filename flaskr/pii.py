"""Authenticated encryption helpers for user profile data."""

import base64
import binascii
import hashlib
import hmac
import secrets
from datetime import date, datetime

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


ENCRYPTED_PREFIX = "enc:v1:"
PROFILE_FIELDS = (
    "name", "age", "dob", "gender", "income", "caste", "states",
    "occupation", "aadhar", "pan", "doc_type", "doc_verified",
)
ELIGIBILITY_FIELDS = (
    "name", "age", "dob", "gender", "income", "caste", "states",
    "occupation",
)


class SensitiveDataError(Exception):
    """Raised when encrypted profile data cannot be authenticated or read."""


def decode_key(encoded_key):
    if not encoded_key:
        raise SensitiveDataError("Personal data encryption is not configured.")
    try:
        key = base64.b64decode(encoded_key, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise SensitiveDataError("Personal data encryption key is invalid.") from exc
    if len(key) != 32:
        raise SensitiveDataError("Personal data encryption key must be 32 bytes.")
    return key


def configured_key():
    from flask import current_app

    return decode_key(current_app.config.get("PERSONAL_DATA_ENCRYPTION_KEY"))


def email_lookup(email, key):
    """Return a keyed exact-match index without storing a reversible address."""
    normalized = email.strip().casefold().encode("utf-8")
    index_key = hmac.new(key, b"sarkarisahayata:email-lookup:v1", hashlib.sha256).digest()
    return hmac.new(index_key, normalized, hashlib.sha256).hexdigest()


def encrypt_email(email, username, key):
    return encrypt_value(email, "email", username, key, context="user")


def decrypt_email(value, username, key):
    return decrypt_value(value, "email", username, key, context="user")


def _text(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def encrypt_value(value, field, owner_id, key, context="user_details"):
    if value is None or value == "":
        return value
    if isinstance(value, str) and value.startswith(ENCRYPTED_PREFIX):
        raise SensitiveDataError("Input uses a reserved encrypted-data format.")
    nonce = secrets.token_bytes(12)
    encrypted = AESGCM(key).encrypt(nonce, _text(value).encode("utf-8"),
                                    f"sarkarisahayata:{context}:{owner_id}:{field}".encode("utf-8"))
    return ENCRYPTED_PREFIX + base64.urlsafe_b64encode(nonce + encrypted).decode("ascii")


def decrypt_value(value, field, owner_id, key, context="user_details"):
    if value is None or value == "":
        return value
    if not isinstance(value, str) or not value.startswith(ENCRYPTED_PREFIX):
        # Allows safe reads while an operator-run migration is only partly complete.
        return value
    try:
        payload = base64.b64decode(value[len(ENCRYPTED_PREFIX):], altchars=b"-_", validate=True)
        if len(payload) < 12 + 16:
            raise ValueError("Encrypted payload is too short.")
        plaintext = AESGCM(key).decrypt(payload[:12], payload[12:],
                                        f"sarkarisahayata:{context}:{owner_id}:{field}".encode("utf-8"))
        return plaintext.decode("utf-8")
    except (ValueError, UnicodeDecodeError, InvalidTag, binascii.Error) as exc:
        raise SensitiveDataError("Saved profile data could not be authenticated.") from exc


def encrypt_profile(values, owner_id, key):
    return {
        field: encrypt_value(values.get(field), field, owner_id, key)
        for field in PROFILE_FIELDS if field in values
    }


def encrypt_legacy_profile(values, owner_id, key):
    """Encrypt only plaintext fields so interrupted migrations can be rerun."""
    protected = {}
    for field in PROFILE_FIELDS:
        if field not in values:
            continue
        value = values[field]
        if isinstance(value, str) and value.startswith(ENCRYPTED_PREFIX):
            # A marker alone is not proof of encryption; authenticate it first.
            decrypt_value(value, field, owner_id, key)
            continue
        protected[field] = encrypt_value(value, field, owner_id, key)
    return protected


def decrypt_profile(values, owner_id, key, fields=PROFILE_FIELDS):
    decrypted = dict(values)
    for field in fields:
        if field in decrypted:
            decrypted[field] = decrypt_value(decrypted[field], field, owner_id, key)
    return decrypted


def mask_identifier(value):
    """Mask Aadhaar/PAN for any authorized display that needs an identifier."""
    if value is None:
        return ""
    value = str(value)
    visible = min(4, len(value))
    return "*" * max(0, len(value) - visible) + value[-visible:] if visible else ""


def mask_email(value):
    if not value or "@" not in value:
        return ""
    local, domain = value.rsplit("@", 1)
    return f"{local[:1]}***@{domain}"
