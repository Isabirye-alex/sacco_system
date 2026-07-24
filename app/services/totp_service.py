import base64
import hashlib
import hmac
import secrets
import struct
import time

def generate_totp_secret() -> str:
    """Generates a random 20-byte base32 TOTP secret."""
    raw_bytes = secrets.token_bytes(20)
    return base64.b32encode(raw_bytes).decode('utf-8').replace('=', '')

def generate_provisioning_uri(secret: str, user_email: str, issuer: str = "SACCO Pro") -> str:
    """Generates an otpauth:// URI suitable for QR codes and authenticator apps."""
    from urllib.parse import quote
    return f"otpauth://totp/{quote(issuer)}:{quote(user_email)}?secret={secret}&issuer={quote(issuer)}"

def verify_totp_code(secret: str, code: str, window: int = 1) -> bool:
    """
    Verifies a 6-digit TOTP code against the secret.
    Allows a time window drift (default 1 step = +/- 30s) to account for clock skew.
    """
    if not secret or not code or len(code) != 6 or not code.isdigit():
        return False
        
    secret_clean = secret.strip().upper()
    missing_padding = len(secret_clean) % 8
    if missing_padding != 0:
        secret_clean += '=' * (8 - missing_padding)
        
    try:
        key = base64.b32decode(secret_clean, casefold=True)
    except Exception:
        return False

    current_interval = int(time.time()) // 30
    
    for t in range(current_interval - window, current_interval + window + 1):
        msg = struct.pack(">Q", t)
        h = hmac.new(key, msg, hashlib.sha1).digest()
        offset = h[-1] & 0x0F
        binary = struct.unpack(">I", h[offset:offset+4])[0] & 0x7FFFFFFF
        totp_calculated = str(binary % 1000000).zfill(6)
        if hmac.compare_digest(totp_calculated, code):
            return True

    return False
