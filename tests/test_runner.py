import os
import sys
import asyncio
import time
import aiohttp
import ssl
import traceback
import json

# Ensure project root is on sys.path so local modules can be imported when
# this script is executed from the tests/ directory.
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from server_lib import ReverseProxyServer
from client_tunnel import ReverseProxyClientTunnel
from redis_utils import get_redis_client

PROXY_URL = "https://localhost:3001"

async def echo_handler(data):
    # immediate response
    return {
        "status": "200 OK",
        "headers": {"Content-Type": "text/plain"},
        "body": f"ECHO:{data.get('path', '/')}: {data.get('body', '')}"
    }

async def slow_handler(data):
    # intentionally slow to trigger timeout
    await asyncio.sleep(10)
    return {
        "status": "200 OK",
        "headers": {"Content-Type": "text/plain"},
        "body": "slow done"
    }

async def calc_handler(data):
    # very small calculator: path /add?a=1&b=2
    path = data.get('path', '/')
    qs = {}
    if '?' in path:
        path, q = path.split('?', 1)
        for pair in q.split('&'):
            if '=' in pair:
                k, v = pair.split('=', 1)
                try:
                    qs[k] = float(v)
                except:
                    qs[k] = v
    a = qs.get('a', 0)
    b = qs.get('b', 0)
    try:
        res = float(a) + float(b)
    except:
        res = 'err'
    return {
        "status": "200 OK",
        "headers": {"Content-Type": "application/json"},
        "body": f"{{\"result\": {res}}}"
    }

async def http_get(url):
    # plain HTTP GET using aiohttp (no SSL for localhost)
    try:
        conn = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=conn) as session:
            async with session.get(url) as resp:
                text = await resp.text()
                return resp.status, text
    except Exception as e:
        return None, str(e)

def test_redis_connection():
    """Test Redis server connectivity."""
    print("\n=== Test Redis Server: Connection ===")
    r = get_redis_client()
    if r is None:
        print("✗ Failed to create Redis client")
        return False
    
    try:
        result = r.ping()
        print(f"✓ Redis ping successful: {result}")
        return True
    except Exception as e:
        print(f"✗ Redis ping failed: {e}")
        return False

def test_redis_proxy_registration():
    """Test Redis proxy endpoint registration and discovery."""
    print("\n=== Test Redis Server: Proxy Registration ===")
    r = get_redis_client()
    if r is None:
        print("✗ Redis client not available")
        return False
    
    try:
        # Check if proxy endpoint is registered
        proxy_info = r.get('reverse_proxy:latest')
        if proxy_info:
            data = json.loads(proxy_info)
            print(f"✓ Proxy endpoint found in Redis:")
            print(f"  - URL: {data.get('url')}")
            print(f"  - Public IP: {data.get('public_ip')}")
            print(f"  - Timestamp: {data.get('timestamp')}")
            return True
        else:
            print("⚠ Proxy endpoint not registered in Redis (proxy may need restart)")
            return False
    except Exception as e:
        print(f"✗ Error reading proxy endpoint: {e}")
        return False

def test_redis_data_operations():
    """Test Redis data write/read operations."""
    print("\n=== Test Redis Server: Data Operations ===")
    r = get_redis_client()
    if r is None:
        print("✗ Redis client not available")
        return False
    
    try:
        # Test SET/GET
        test_key = "test:bridge:data"
        test_value = {"message": "bridge-to-redis", "timestamp": time.time()}
        r.set(test_key, json.dumps(test_value))
        print(f"✓ SET {test_key} -> {test_value}")
        
        retrieved = r.get(test_key)
        if retrieved:
            data = json.loads(retrieved)
            print(f"✓ GET {test_key} -> {data}")
            r.delete(test_key)
            print(f"✓ DEL {test_key}")
            return True
        else:
            print(f"✗ Failed to retrieve {test_key}")
            return False
    except Exception as e:
        print(f"✗ Data operations failed: {e}")
        return False

def test_redis_list_operations():
    """Test Redis list operations for job queue."""
    print("\n=== Test Redis Server: List Operations ===")
    r = get_redis_client()
    if r is None:
        print("✗ Redis client not available")
        return False
    
    try:
        queue_key = "job:queue:bridge_test"
        
        # Clean queue
        r.delete(queue_key)
        
        # Push items
        job1 = json.dumps({"id": 1, "task": "process", "status": "pending"})
        job2 = json.dumps({"id": 2, "task": "validate", "status": "pending"})
        r.rpush(queue_key, job1, job2)
        print(f"✓ RPUSH 2 jobs to {queue_key}")
        
        # Queue length
        length = r.llen(queue_key)
        print(f"✓ Queue length: {length}")
        
        # Pop item
        item = r.lpop(queue_key)
        if item:
            job = json.loads(item)
            print(f"✓ LPOP -> Job ID {job['id']}")
        
        # Clean up
        r.delete(queue_key)
        print(f"✓ Queue cleaned")
        return True
    except Exception as e:
        print(f"✗ List operations failed: {e}")
        return False

def test_redis_hash_operations():
    """Test Redis hash operations for server metadata."""
    print("\n=== Test Redis Server: Hash Operations ===")
    r = get_redis_client()
    if r is None:
        print("✗ Redis client not available")
        return False
    
    try:
        server_key = "server:bridge_test:metadata"
        
        # Clean
        r.delete(server_key)
        
        # Set hash fields
        r.hset(server_key, mapping={
            "name": "bridge_test_server",
            "port": "3001",
            "status": "running",
            "requests": "0",
            "timestamp": str(time.time())
        })
        print(f"✓ HSET {server_key} with metadata")
        
        # Get all fields
        data = r.hgetall(server_key)
        print(f"✓ HGETALL -> {len(data)} fields")
        for k, v in data.items():
            print(f"  - {k}: {v}")
        
        # Update field
        r.hincrby(server_key, "requests", 1)
        requests = r.hget(server_key, "requests")
        print(f"✓ HINCRBY requests -> {requests}")
        
        # Clean up
        r.delete(server_key)
        print(f"✓ Server metadata cleaned")
        return True
    except Exception as e:
        print(f"✗ Hash operations failed: {e}")
        return False

async def run_tests():
    print("TEST RUNNER: Ensure the proxy is running at https://localhost:3001 before running this script.")
    # create servers
    echo_srv = ReverseProxyServer(proxy_url=PROXY_URL, server_name='echo_test', request_handler=echo_handler, verify_ssl=False)
    calc_srv = ReverseProxyServer(proxy_url=PROXY_URL, server_name='calc_test', request_handler=calc_handler, verify_ssl=False)
    slow_srv = ReverseProxyServer(proxy_url=PROXY_URL, server_name='slow_test', request_handler=slow_handler, verify_ssl=False)

    echo_task = asyncio.create_task(echo_srv.connect())
    calc_task = asyncio.create_task(calc_srv.connect())
    slow_task = asyncio.create_task(slow_srv.connect())


    # give backends time to register and connect
    await asyncio.sleep(3)

    # HTTP client session that skips SSL verification for local testing
    connector = aiohttp.TCPConnector(ssl=False)
    session = aiohttp.ClientSession(connector=connector)

    # Test 1: basic echo
    print("Test 1: basic echo")
    status, body = await http_get(f"{PROXY_URL}/proxy/echo_test/ping")
    print(' ->', status, body[:200])

    # Test 2: calc
    print("Test 2: calc add")
    status, body = await http_get(f"{PROXY_URL}/proxy/calc_test/add?a=5&b=2")
    print(' ->', status, body[:200])

    # Test 3: slow -> expect timeout from client tunnel (504)
    print("Test 3: slow handler timeout (expect 504)")
    status, body = await http_get(f"{PROXY_URL}/proxy/slow_test/test")
    print(' ->', status, body[:200])

    # Test 4: server disconnect and reconnect
    print("Test 4: server disconnect/reconnect")
    # stop echo server
    await echo_srv.close()
    print(" -> echo server closed; request should fail or get 502")
    await asyncio.sleep(2)
    status, body = await http_get(f"{PROXY_URL}/proxy/echo_test/ping")
    print(' -> after close:', status, body[:200])

    # restart echo server
    echo_srv2 = ReverseProxyServer(proxy_url=PROXY_URL, server_name='echo_test', request_handler=echo_handler, verify_ssl=False)
    echo_task2 = asyncio.create_task(echo_srv2.connect())
    await asyncio.sleep(4)
    status, body = await http_get(f"{PROXY_URL}/proxy/echo_test/ping")
    print(' -> after restart:', status, body[:200])

    # cleanup
    print("Cleaning up...")
    for t in [echo_task, calc_task, slow_task, echo_task2]:
        try:
            t.cancel()
        except:
            pass
    for srv in [echo_srv, calc_srv, slow_srv, echo_srv2]:
        try:
            await srv.close()
        except:
            pass
    try:
        await session.close()
    except:
        pass

    # cancel client tunnel tasks
    # no local tunnel tasks to cancel when using /proxy endpoints

    print("Test run complete.")

if __name__ == '__main__':
    try:
        asyncio.run(run_tests())
    except Exception:
        traceback.print_exc()
