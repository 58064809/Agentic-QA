from __future__ import annotations

import base64
import os
from collections.abc import Mapping
from typing import Any

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from harness.domain.models import ApiLoginRequestEncryption

AES_BLOCK_SIZE_BITS = 128
AES_IV_SIZE_BYTES = 16


def encrypt_login_request_body(
    body: Any,
    encryption: ApiLoginRequestEncryption | None,
    env: Mapping[str, str],
) -> Any:
    if encryption is None:
        return body
    if encryption.algorithm != "aes-128-cbc-pkcs7-base64-iv-prefix":
        raise ValueError("unsupported API login request encryption algorithm")
    if not isinstance(body, dict):
        raise ValueError("API login encryption requires an object request body")
    key_value = env.get(encryption.key_env, "")
    if not key_value:
        raise RuntimeError("API login encryption key is empty in the selected local project")
    key = key_value.encode("utf-8")
    if len(key) != AES_IV_SIZE_BYTES:
        raise ValueError("API login AES-128 key must encode to exactly 16 bytes")

    encrypted = dict(body)
    for field in encryption.fields:
        value = encrypted.get(field)
        if not isinstance(value, str) or not value:
            raise ValueError(f"API login encryption field must be a non-empty string: {field}")
        encrypted[field] = _aes_128_cbc_pkcs7_base64_iv_prefix(value, key)
    return encrypted


def _aes_128_cbc_pkcs7_base64_iv_prefix(plaintext: str, key: bytes) -> str:
    iv = os.urandom(AES_IV_SIZE_BYTES)
    padder = padding.PKCS7(AES_BLOCK_SIZE_BITS).padder()
    padded = padder.update(plaintext.encode("utf-8")) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(iv + ciphertext).decode("ascii")
