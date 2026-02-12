# Reverse Proxy Implementation Guide

## Overview

이 거리버스 프록시 시스템은 다음을 지원합니다:

- **백엔드 서버 등록**: 서버들이 리버스 프록시에 자신을 등록
- **클라이언트 터널링**: 클라이언트의 로컬 포트를 리버스 프록시를 통해 백엔드에 연결
- **메시지 중계**: 프록시가 클라이언트와 백엔드 간 통신 중계
- **실시간 대시보드**: 활성 연결, 통계, 상태 모니터링
- **HTTPS/WSS**: SSL 인증서 검증 없이 보안 통신

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Reverse Proxy (Port 3001)                │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ /api/register_server → Server Registration              ││
│  │ /wss/reverse_proxy/{name} → WSS Handler                 ││
│  │ /proxy_dashboard → Status Dashboard                      ││
│  │ /api/proxy_stats → Statistics API                        ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
         ▲                                          ▲
         │                                          │
    WSS Connection                          Client Request
    (Persistent)                           (HTTP/JSON)
         │                                          │
     ────┴────                                 ────┴────
    │          │                              │        │
┌─────────┐ ┌──────────┐                ┌─────────┐ ┌──────────┐
│ Backend │ │ Backend  │                │ Client  │ │ Client   │
│ Server 1│ │ Server 2 │                │ Port    │ │ Port 2   │
│         │ │          │                │ Tunnel  │ │ Tunnel   │
└─────────┘ └──────────┘                └─────────┘ └──────────┘
```

## Quick Start

### 1. Start Reverse Proxy

```bash
cd /home/aaa/__PY/foo_bridge
python3 app.py
```

Proxy will run on `https://0.0.0.0:3001`

### 2. Start Backend Servers

In another terminal:

```bash
cd /home/aaa/__PY/foo_bridge
python3 example_servers.py
```

This starts 3 example servers:
- `echo_server` - Echo service
- `calculator` - Math operations
- `ai_inference` - AI mock service

### 3. Start Client Tunnels

In third terminal:

```bash
cd /home/aaa/__PY/foo_bridge
python3 run_client_tunnels.py
```

This creates local tunnels:
- `http://localhost:11434` → `echo_server`
- `http://localhost:8081` → `calculator`
- `http://localhost:8082` → `ai_inference`

### 4. Test from Client

In fourth terminal:

```bash
python3 example_client_test.py
```

Or visit dashboard: `https://localhost:3001/proxy_dashboard`

## Components

### 1. Reverse Proxy Core (app.py)

**Global State:**
- `registered_servers`: Server registry with metadata
- `server_connections`: Active client connections per server
- `pending_requests`: Request ID → Response mapping
- `proxy_stats`: Global statistics

**Endpoints:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/register_server` | POST | Register backend server |
| `/wss/reverse_proxy/{server_name}` | GET | WebSocket for server/client |
| `/proxy_dashboard` | GET | Status dashboard HTML |
| `/api/proxy_stats` | GET | JSON statistics API |

### 2. Server Library (server_lib.py)

**Class:** `ReverseProxyServer`

Backend servers use this to connect to proxy and handle requests.

**Example:**

```python
from server_lib import ReverseProxyServer

async def my_handler(data):
    # data contains incoming request
    return {"response": "processed"}

server = ReverseProxyServer(
    proxy_url="https://proxy.example.com:3001",
    server_name="my_service",
    request_handler=my_handler,
    params={"version": "1.0"}
)

await server.connect()
```

**Features:**
- Auto-reconnection on failure
- Request/response handling
- Statistics tracking
- Async/await support

### 3. Client Tunnel Library (client_tunnel.py)

**Class:** `ReverseProxyClientTunnel`

Clients use this to tunnel local services through proxy.

**Example:**

```python
from client_tunnel import ReverseProxyClientTunnel

tunnel = ReverseProxyClientTunnel(
    local_port=11434,
    proxy_url="https://proxy.example.com:3001",
    proxy_server_name="ollama1"
)

await tunnel.start()
# Now http://localhost:11434 connects to ollama1
```

**Features:**
- Local HTTP server
- HTTP to WebSocket tunneling
- Request/response forwarding
- Statistics tracking

### 4. Example Servers (example_servers.py)

Three example backend servers:

1. **Echo Server** - Returns what it receives
2. **Calculator** - Math operations (add, subtract, multiply, divide)
3. **AI Inference Mock** - Simulates AI service

### 5. Example Client (example_client_test.py)

Test client that:
- Connects to each tunnel
- Sends test requests
- Validates responses
- Checks dashboard

### 6. Client Tunnel Runner (run_client_tunnels.py)

Runs multiple tunnels with configuration:
- Multiple ports
- Multiple servers
- Statistics reporting

## Registration Flow

### Server Registration

```
1. Backend Server calls /api/register_server (HTTP POST)
   - Payload: {"name": "server1", "params": {...}}
   
2. Proxy stores server metadata
   - registered_servers["server1"] = {ws: None, params: {...}, ...}
   
3. Server connects to /wss/reverse_proxy/server1 (WebSocket)
   - Proxy detects server and sets ws reference
   - Server-client link established
```

### Client Connection

```
1. Client connects to /wss/reverse_proxy/server1 (WebSocket)
   - Proxy adds client to server_connections["server1"]
   
2. Client sends request via WebSocket
   - Proxy forwards to backend server
   - Request ID tracked for response routing
   
3. Server processes and responds
   - Proxy routes response back to specific client
```

## Data Flow

### HTTP Request → WebSocket

```
Client HTTP Request:
  POST http://localhost:11434/api/query
  Content-Type: application/json
  
  {"query": "SELECT * FROM table"}

↓ (Client Tunnel)

WebSocket to Proxy:
  {
    "request_id": 12345,
    "method": "POST",
    "path": "/api/query",
    "headers": {...},
    "body": "{\"query\": \"...\"}"
  }

↓ (Proxy Routing)

WebSocket to Backend:
  (same JSON with request_id)

↓ (Backend Processing)

WebSocket Response:
  {
    "request_id": 12345,
    "response": {"status": "ok", "data": [...]}
  }

↓ (Proxy Routing)

WebSocket to Client:
  (same JSON)

↓ (Client Tunnel)

HTTP Response:
  200 OK
  Content-Type: application/json
  
  {"status": "ok", "data": [...]}
```

## Dashboard

Access at: `https://localhost:3001/proxy_dashboard`

**Features:**
- Real-time server status
- Active client connections
- Request statistics
- Data transfer metrics
- Server parameters display
- Auto-refreshing every 3 seconds

**Statistics Tracked:**
- Total requests
- Total bytes sent/received
- Active servers (online/offline)
- Active clients per server
- Per-server metrics

## Configuration

### Environment Variables

None required, but you can modify:

1. **Proxy Port**: Edit `app.py` main() function (default: 3001)
2. **SSL Certificates**: cert.pem and key.pem files
3. **Server Parameters**: Pass in registration or server_lib config

### Server Registration Parameters

Pass custom parameters during registration:

```python
server = ReverseProxyServer(
    proxy_url="https://localhost:3001",
    server_name="ollama",
    request_handler=handler,
    params={
        "model": "llama2",
        "context_size": "4k",
        "gpu_enabled": True,
        "max_tokens": 2048
    }
)
```

These appear in the dashboard.

## Security Notes

### Current Implementation (Demo)

- ✅ HTTPS/WSS enabled
- ⚠️ No SSL certificate verification (for demo)
- ⚠️ No authentication
- ⚠️ No authorization

### For Production

Recommended additions:

1. **SSL Verification**: Set `verify_ssl=True`
2. **Authentication**: Add token/JWT validation in `/api/register_server`
3. **Authorization**: Validate client access to specific servers
4. **Rate Limiting**: Add request rate limits
5. **Encryption**: Encrypt sensitive data in payloads
6. **Logging**: Comprehensive audit logging

## Performance Considerations

### Limits

- **Max Concurrent Connections**: Limited by system resources
- **Request Timeout**: 90 seconds (configurable in client_tunnel.py)
- **Message Size**: Limited by aiohttp (usually > 1GB)

### Optimization

1. **Connection Pooling**: Reuse connections
2. **Batching**: Group multiple requests
3. **Compression**: Enable gzip for large payloads
4. **Async Processing**: Use asyncio for many connections

## Troubleshooting

### Server Registration Failed

```
[ReverseProxy] Registration failed: 500
```

Solution:
- Check proxy is running on correct port
- Verify proxy_url is correct
- Check network connectivity

### No Servers Connected

```
[ReverseProxy] 0 WebSockets connected
```

Solution:
- Start backend servers with `python3 example_servers.py`
- Check server logs for errors
- Verify network between server and proxy

### Client Connection Refused

```
Connection error to {url}
```

Solution:
- Start client tunnels with `python3 run_client_tunnels.py`
- Check tunnel configuration in code
- Verify backend server is connected

### Dashboard Not Loading

```
ERR_INVALID_SSL_VERSION
```

Solution:
- Bypass certificate warning in browser
- Or regenerate valid certificates
- Or use `verify_ssl=False` in configuration

## Advanced Usage

### Custom Server Implementation

```python
from server_lib import ReverseProxyServer

async def handle_requests(data):
    # data is parsed request JSON
    if data.get("method") == "POST":
        # Handle POST
        return process_post(data)
    else:
        # Handle GET
        return process_get(data)

server = ReverseProxyServer(
    proxy_url="https://proxy:3001",
    server_name="my_api",
    request_handler=handle_requests
)

await server.connect()
```

### Custom Client Configuration

```python
from client_tunnel import ReverseProxyClientTunnel

tunnels = []
for config in my_config:
    tunnel = ReverseProxyClientTunnel(
        local_port=config['port'],
        proxy_url=config['proxy'],
        proxy_server_name=config['name']
    )
    tunnels.append(tunnel)

# Start all tunnels
await asyncio.gather(*[t.start() for t in tunnels])
```

### Real-time Monitoring

```python
# Get proxy stats
import aiohttp

async with aiohttp.ClientSession() as session:
    async with session.get("https://localhost:3001/api/proxy_stats") as r:
        stats = await r.json()
        print(f"Active servers: {stats['stats']['active_servers']}")
        print(f"Total requests: {stats['stats']['total_requests']}")
```

## File Reference

| File | Purpose |
|------|---------|
| `app.py` | Main proxy server with endpoints |
| `server_lib.py` | Backend server connection library |
| `client_tunnel.py` | Client local tunnel library |
| `example_servers.py` | Example backend servers |
| `example_client_test.py` | Example client tests |
| `run_client_tunnels.py` | Run multiple tunnels |

## Examples

### Example 1: Echo Service

```python
# Server
async def echo_handler(data):
    return {"echo": data}

server = ReverseProxyServer(..., request_handler=echo_handler)
await server.connect()

# Client
tunnel = ReverseProxyClientTunnel(11434, ..., "echo_server")
await tunnel.start()

# Test
curl -X POST http://localhost:11434 \
  -H "Content-Type: application/json" \
  -d '{"message": "hello"}'
```

### Example 2: Database Service

```python
# Server
async def db_handler(data):
    query = data.get("query")
    result = await db.execute(query)
    return {"result": result}

# Client
tunnel = ReverseProxyClientTunnel(5432, ..., "postgres")
# Now postgresql://localhost:5432 connects to remote DB
```

### Example 3: Multiple Services

```python
# Start different services separately
echo = ReverseProxyServer(..., server_name="echo")
db = ReverseProxyServer(..., server_name="database")
api = ReverseProxyServer(..., server_name="api")

# Start tunnels for each
tunnel1 = ReverseProxyClientTunnel(11434, ..., "echo")
tunnel2 = ReverseProxyClientTunnel(5432, ..., "database")
tunnel3 = ReverseProxyClientTunnel(8080, ..., "api")

await asyncio.gather(
    echo.connect(),
    db.connect(),
    api.connect(),
    tunnel1.start(),
    tunnel2.start(),
    tunnel3.start()
)
```

## Statistics API

Endpoint: `GET /api/proxy_stats`

Response:
```json
{
  "stats": {
    "total_requests": 142,
    "total_bytes_sent": 45892,
    "total_bytes_received": 23456,
    "active_servers": 3,
    "active_clients": 5
  },
  "servers": {
    "echo_server": {
      "name": "echo_server",
      "params": {"type": "echo"},
      "connect_time": 1707800000,
      "stats": {
        "requests": 45,
        "bytes_sent": 12345,
        "bytes_received": 6789
      },
      "ws": true
    }
  },
  "client_connections": {
    "echo_server": 2
  }
}
```

---

**Last Updated**: February 12, 2026
**Version**: 1.0
**Status**: Complete Implementation
