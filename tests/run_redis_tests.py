import sys
import traceback

from test_runner import (
    test_redis_connection,
    test_redis_proxy_registration,
    test_redis_data_operations,
    test_redis_list_operations,
    test_redis_hash_operations,
)


def main():
    print("Running Redis-only tests from test_runner.py")
    all_ok = True
    try:
        if not test_redis_connection():
            all_ok = False
        if not test_redis_data_operations():
            all_ok = False
        if not test_redis_list_operations():
            all_ok = False
        if not test_redis_hash_operations():
            all_ok = False
        # proxy registration is optional but included
        if not test_redis_proxy_registration():
            print("Proxy registration test failed or not present.")
            all_ok = False
    except Exception:
        traceback.print_exc()
        all_ok = False
    print("\nRedis tests completed. Overall:", "PASS" if all_ok else "FAIL")
    sys.exit(0 if all_ok else 2)


if __name__ == '__main__':
    main()
