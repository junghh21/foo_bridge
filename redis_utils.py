import os
import redis
import json


def get_redis_client():
    """Return a configured redis.Redis client or None if creation failed.

    Uses external TLS Redis server by default (168.107.19.251:7933).
    Can be overridden via environment variables:
    - REDIS_HOST (default: 168.107.19.251)
    - REDIS_PORT (default: 7933)
    - REDIS_PASSWORD (default: security)
    - REDIS_DB (default: 0)
    - REDIS_TLS (default: true; set to 0/false to disable)
    - REDIS_CERTFILE (default: client.crt)
    - REDIS_KEYFILE (default: client.key)
    - REDIS_CAFILE (default: ca.crt)
    """
    try:
        host = os.environ.get('REDIS_HOST', '168.107.19.251')
        port = int(os.environ.get('REDIS_PORT', 7933))
        password = os.environ.get('REDIS_PASSWORD', 'security')
        db = int(os.environ.get('REDIS_DB', 0))
        tls = os.environ.get('REDIS_TLS', 'true').lower() in ('1', 'true', 'yes')

        if tls:
            ssl_certfile = os.environ.get('REDIS_CERTFILE', 'client.crt')
            ssl_keyfile = os.environ.get('REDIS_KEYFILE', 'client.key')
            ssl_ca_certs = os.environ.get('REDIS_CAFILE', 'ca.crt')
            return redis.Redis(host=host, port=port, password=password, db=db,
                               ssl=True, ssl_certfile=ssl_certfile,
                               ssl_keyfile=ssl_keyfile, ssl_ca_certs=ssl_ca_certs,
                               decode_responses=True)
        else:
            return redis.Redis(host=host, port=port, password=password, db=db, decode_responses=True)
    except Exception as e:
        print(f"[redis_utils] Failed to create Redis client: {e}")
        return None
