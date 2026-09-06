from time import time

_cache = {}


def get_cache(key: str):
    item = _cache.get(key)
    if not item:
        return None
    expires_at, value = item
    if time() > expires_at:
        _cache.pop(key, None)
        return None
    return value


def set_cache(key: str, value, ttl_seconds: int):
    _cache[key] = (time() + ttl_seconds, value)