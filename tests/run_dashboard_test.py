import os
import sys
import asyncio
import traceback

# Ensure project root on sys.path so local modules can be imported when this
# script is executed from the tests/ directory.
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from example_client_test import test_reverse_proxy_dashboard

async def main():
    try:
        await test_reverse_proxy_dashboard()
    except Exception:
        traceback.print_exc()

if __name__ == '__main__':
    asyncio.run(main())
