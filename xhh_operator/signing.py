"""公开网页客户端的路径签名协议；不是账号身份验证或密码加密。"""

import hashlib
import secrets
import time
from itertools import zip_longest

ALPHABET = "AB45STUVWZEFGJ6CH01D237IXYPQRKLMN89"


def _md5(value: str) -> str:
    return hashlib.md5(value.encode(), usedforsecurity=False).hexdigest()


def _double(value):
    return ((value << 1) ^ (27 if value & 128 else 0)) & 255


def _three(value):
    return _double(value) ^ value


def _nine(value):
    return _three(_double(value))


def _eleven(value):
    return _nine(_three(_double(value)))


def _thirteen(value):
    return _eleven(value) ^ _nine(value) ^ _three(value)


def sign(path: str, timestamp: int, nonce: str) -> str:
    path = "/" + "/".join(filter(None, path.split("/"))) + "/"

    def map_chars(value, alphabet):
        return "".join(alphabet[ord(c) % len(alphabet)] for c in value)

    parts = (
        map_chars(str(timestamp + 1), ALPHABET[:-2]),
        map_chars(path, ALPHABET),
        map_chars(nonce, ALPHABET),
    )
    seed = "".join("".join(chars) for chars in zip_longest(*parts, fillvalue=""))[:20]
    digest = _md5(seed)
    a, b, c, d = map(ord, digest[-6:][:4])
    mixed = (
        _thirteen(a) ^ _eleven(b) ^ _nine(c) ^ _three(d),
        _three(a) ^ _thirteen(b) ^ _eleven(c) ^ _nine(d),
        _nine(a) ^ _three(b) ^ _thirteen(c) ^ _eleven(d),
        _eleven(a) ^ _nine(b) ^ _three(c) ^ _thirteen(d),
    )
    # The JS implementation retains its two untouched tail bytes in the checksum.
    checksum = (sum(mixed) + sum(map(ord, digest[-2:]))) % 100
    return map_chars(digest[:5], ALPHABET[:-4]) + f"{checksum:02d}"


def signed_params(path: str, *, timestamp=None, nonce=None) -> dict:
    timestamp = int(time.time()) if timestamp is None else timestamp
    nonce = _md5(f"{timestamp}{secrets.token_hex(16)}").upper() if nonce is None else nonce
    return {"hkey": sign(path, timestamp, nonce), "_time": timestamp, "nonce": nonce}


def workshop_params(params: dict) -> dict:
    """网页写接口使用的公开 Workshop 版本 15 附加签名。"""
    import hmac

    salt = "Z7mFG4tQp9Ws2LxB8H"
    nonce = str(params["nonce"])
    stamp = str(params["_time"])
    message = f"{salt}{nonce}{stamp}:{nonce}"
    digest = hmac.new(salt.encode(), message.encode(), hashlib.sha256).hexdigest()
    return {"_rnd": "15:" + digest}
