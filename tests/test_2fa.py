import pytest
import struct
import hmac
import hashlib
import time
import base64

def _calc_totp(secret: str) -> str:
    secret_clean = secret.strip().upper()
    missing_padding = len(secret_clean) % 8
    if missing_padding != 0:
        secret_clean += '=' * (8 - missing_padding)
    key = base64.b32decode(secret_clean, casefold=True)
    t = int(time.time()) // 30
    msg = struct.pack(">Q", t)
    h = hmac.new(key, msg, hashlib.sha1).digest()
    offset = h[-1] & 0x0F
    binary = struct.unpack(">I", h[offset:offset+4])[0] & 0x7FFFFFFF
    return str(binary % 1000000).zfill(6)

def test_2fa_full_lifecycle(client, admin_headers):
    # 1. Setup 2FA
    setup_res = client.post("/api/v1/auth/2fa/setup", headers=admin_headers)
    assert setup_res.status_code == 200
    data = setup_res.json()
    assert "secret" in data
    assert "otpauth://" in data["provisioning_uri"]
    secret = data["secret"]

    # 2. Invalid code fails enable
    fail_res = client.post("/api/v1/auth/2fa/enable", json={"code": "000000"}, headers=admin_headers)
    assert fail_res.status_code == 400

    # 3. Valid TOTP code enables 2FA
    valid_code = _calc_totp(secret)
    enable_res = client.post("/api/v1/auth/2fa/enable", json={"code": valid_code}, headers=admin_headers)
    assert enable_res.status_code == 200

    # 4. Verify 2FA code
    verify_res = client.post("/api/v1/auth/2fa/verify", json={"code": valid_code}, headers=admin_headers)
    assert verify_res.status_code == 200
    assert verify_res.json()["valid"] is True

    # 5. Disable 2FA with valid code
    disable_res = client.post("/api/v1/auth/2fa/disable", json={"code": valid_code}, headers=admin_headers)
    assert disable_res.status_code == 200
