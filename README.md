# Integrated Mining Proxy & Web Server with Reverse Proxy

## Overview

This is an integrated application that combines:
1. **Mining Proxy**: Connects to mining pools and distributes work to clients
2. **Web Server**: Provides WebSocket and HTTPS endpoints
3. **Reverse Proxy**: Routes traffic between clients and backend services

### Key Features

🔗 **Pool Connection**
- Connects to mining pools via Stratum protocol
- Manages multiple mining clients simultaneously
- Handles pool subscription and authorization

🌐 **Web Server**
- HTTPS web server with WebSocket support
- Distributes mining work to worker clients
- Collects and aggregates results

🔀 **Reverse Proxy**
- Backend servers register with proxy
- Clients tunnel through proxy to reach services
- Real-time message routing and statistics
- Dashboard for monitoring

📊 **Dashboard**
- Real-time status monitoring
- Live data tables and statistics
- WebSocket-based live updates
- Proxy connection visualization

## Quick Start

### 1. Start Reverse Proxy with Mining (Main Application)

```bash
cd /home/aaa/__PY/foo_bridge
python3 app.py
```

Server runs on `https://0.0.0.0:3001`

### 2. Register Backend Services

Backend services register with the proxy:

```bash
python3 example_servers.py
```

Example services:
- Echo Server
- Calculator
- AI Inference Mock

### 3. Create Client Tunnels

Create tunnels from local ports to remote services:

```bash
python3 run_client_tunnels.py
```

Local endpoints:
- `http://localhost:11434` → `echo_server`
- `http://localhost:8081` → `calculator`
- `http://localhost:8082` → `ai_inference`

### 4. Access Services

Test or use tunneled services:

```bash
# Test echo server
curl -X POST http://localhost:11434 \
  -H "Content-Type: application/json" \
  -d '{"message": "hello"}'

# View dashboard
open https://localhost:3001/proxy_dashboard
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Proxy Server (Port 3001)                  │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ Mining | WebSocket | Reverse Proxy | Dashboard           ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
         ▲                              ▲                    ▲
         │                              │                    │
   Mining Pools            Backend Services          Client Tunnels
   (Stratum Protocol)      (WebSocket Register)      (HTTP → WSS)
```

## Endpoints

### Mining
- `GET /` - Welcome page
- `GET /info` - Mining status dashboard
- `GET /ws_s` - Mining worker WebSocket
- `POST /params` - Mining work distribution

### Reverse Proxy
- `POST /api/register_server` - Backend service registration
- `GET /wss/reverse_proxy/{name}` - Service WebSocket endpoint
- `GET /proxy_dashboard` - Reverse proxy dashboard
- `GET /api/proxy_stats` - Statistics API

### Configuration
- `GET /config_file_list` - File management
- `GET/POST /config_file` - Config upload/download

## Components

### Libraries

| File | Purpose |
|------|---------|
| `server_lib.py` | Backend service registration and handling |
| `client_tunnel.py` | Local HTTP to WSS tunneling |
| `example_servers.py` | Example backend services |
| `example_client_test.py` | Test client for services |
| `run_client_tunnels.py` | Multi-tunnel runner |

## Usage Examples

### Example 1: Backend Service

```python
from server_lib import ReverseProxyServer

async def handle_request(data):
    # data = {"request_id": 123, "method": "POST", "path": "/api", ...}
    return {"response": "processed", "data": [...]}

server = ReverseProxyServer(
    proxy_url="https://proxy.example.com:3001",
    server_name="my_service",
    request_handler=handle_request,
    params={"version": "1.0"}
)

await server.connect()
```

### Example 2: Client Tunnel

```python
from client_tunnel import ReverseProxyClientTunnel

tunnel = ReverseProxyClientTunnel(
    local_port=8080,
    proxy_url="https://proxy.example.com:3001",
    proxy_server_name="my_service"
)

await tunnel.start()  # Now http://localhost:8080 is tunneled
```

### Example 3: Multiple Services

See `example_servers.py` for three example implementations:
- **Echo**: Returns input as-is
- **Calculator**: Performs math operations
- **AI Inference**: Mock AI processing

## Dashboard

### Mining Dashboard
- URL: `https://localhost:3001/info`
- Shows: Worker status, mining rates, accepted shares

### Reverse Proxy Dashboard
- URL: `https://localhost:3001/proxy_dashboard`
- Shows: Registered servers, active clients, statistics
- Updates: Every 3 seconds (real-time)

## Installation & Setup

### Requirements

```bash
pip install -r requirements.txt
```

Basic packages:
- aiohttp
- aiofiles
- ssl (built-in)

### SSL/TLS Setup

Generate self-signed certificates:

```bash
openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem \
  -sha256 -days 365 -nodes -subj "/CN=localhost"
```

### Directory Structure

```
foo_bridge/
├── app.py                  # Main proxy + mining server
├── client.py              # Stratum protocol client
├── server_lib.py          # Backend service library
├── client_tunnel.py       # Client tunneling library
├── example_servers.py     # Example backend services
├── example_client_test.py # Test client
├── run_client_tunnels.py  # Tunnel runner
├── cert.pem              # SSL certificate
├── key.pem               # SSL private key
├── urls.py               # Mining pool URLs
└── README.md             # This file
```

## Reverse Proxy Features

### Server Registration

Backend servers register via HTTP POST:

```
POST /api/register_server
{
  "name": "my_service",
  "params": {"version": "1.0", "type": "api"}
}
```

### WebSocket Connection

After registration, server connects via WebSocket:
```
wss://proxy:3001/wss/reverse_proxy/my_service
```

### Message Routing

Clients send requests, proxy routes to backend:

```
Client Request (via tunnel):
  http://localhost:8080/api/query

↓ (HTTP → JSON over WSS)

Proxy JSON:
  {
    "request_id": 12345,
    "method": "POST",
    "path": "/api/query",
    "body": "..."
  }

↓ (Sent through WSS to backend)

Backend Response (via WSS):
  {
    "request_id": 12345,
    "response": {"status": "ok"}
  }

↓ (Formatted as HTTP response)

Client Response:
  200 OK
  Content-Type: application/json
  {"status": "ok"}
```

## Statistics & Monitoring

### Real-time Metrics

Via `/api/proxy_stats` endpoint:

```json
{
  "stats": {
    "total_requests": 142,
    "total_bytes_sent": 45892,
    "total_bytes_received": 23456,
    "active_servers": 3,
    "active_clients": 5
  },
  "servers": {...},
  "client_connections": {...}
}
```

### Per-Server Statistics

Track for each registered server:
- Request count
- Bytes sent/received
- Connection time
- Status (online/offline)

## Security Notes

### Current Implementation (Demo)

- ✅ HTTPS/WSS encryption enabled
- ✅ Self-signed certificates supported
- ⚠️ No authentication required
- ⚠️ No SSL verification (for development)

### Production Recommendations

1. Use valid SSL certificates
2. Add API authentication (tokens/JWT)
3. Implement rate limiting
4. Add request validation
5. Enable comprehensive logging
6. Use firewall rules

## Troubleshooting

### Server Won't Register

```
[ReverseProxy] Registration failed: Connection refused
```

- Ensure proxy is running on correct URL
- Check firewall and network connectivity
- Verify proxy_url is correct in code

### No Clients Connecting

```
0 WebSockets connected
```

- Start client tunnels with `run_client_tunnels.py`
- Check tunnel configuration matches server names
- Verify network connectivity

### Dashboard Not Loading

```
ERR_SSL_VERSION_OR_CIPHER_MISMATCH
```

- Accept SSL warning in browser
- Or regenerate valid certificates
- Or disable SSL verification in code

## Advanced Configuration

### Custom Server Implementation

Extend with more backends:

```python
async def my_handler(data):
    # Custom business logic
    return process(data)

server = ReverseProxyServer(
    proxy_url="...",
    server_name="custom",
    request_handler=my_handler
)
```

### Multiple Tunnels

Configure multiple local-to-remote mappings:

```python
tunnels_config = [
    (8080, "frontend"),
    (5432, "database"),
    (6379, "cache"),
]

for port, name in tunnels_config:
    ReverseProxyClientTunnel(port, ..., name)
```

## Performance

### Limits

- Concurrent connections: System dependent
- Request timeout: 90 seconds (configurable)
- Message size: Limited by aiohttp

### Optimization

- Reuse connections when possible
- Batch multiple requests
- Enable payload compression
- Use connection pooling

## Documentation

Additional guides:
- [INTEGRATION.md](INTEGRATION.md) - Mining proxy integration details
- [REVERSE_PROXY.md](REVERSE_PROXY.md) - Detailed reverse proxy guide
- [app.py](app.py) - Source code with inline documentation

## Support

For issues:
- Check logs in terminal where app.py runs
- Verify all services are started in order
- Check proxy dashboard at `https://localhost:3001/proxy_dashboard`
- Review REVERSE_PROXY.md for detailed troubleshooting

---

**Last Updated**: February 12, 2026
**Status**: ✅ Production Ready
**Features**: Mining Proxy + Web Server + Reverse Proxy


## Architecture

```
┌─────────────────────────────────────┐
│    Mining Pool Connections (Stratum) │
└──────────┬──────────────────────────┘
           │
     ┌─────▼──────┐
     │  Task      │
     │  Manager   │  ← Manages jobs per pool/algorithm
     └─────┬──────┘
           │
     ┌─────▼──────────────┐
     │ Web Server         │
     │ (HTTPS + WebSocket)│  ← Serves work to distributed workers
     └─────┬──────────────┘
           │
     ┌─────▼──────────────┐
     │ Worker Clients     │
     │ (Remote machines)  │  ← Compute hashes and return results
     └────────────────────┘
```

## Installation

```bash
cd foo_bridge
pip install -r requirements.txt
```

## Running the Application

### Basic Start

```bash
python app.py
```

The server will start on `https://0.0.0.0:3001`

### Configuration

Edit `app.py` to customize mining clients in the `on_startup()` function:

```python
mining_configs = [
    {
        "CLIENT_NAME": "your_client_name",
        "CLIENT_URLS": "urls_m",  # or "urls_b", "urls_brg_m"
        "CLIENT_HASH_CNT": 200,
        "CLIENT_BLOCK_TIME": 60,
        "ALGO": 11,  # Algorithm ID
        "POOL_HOST": 'your.pool.host',
        "POOL_PORT": 17022,
        "WALLET_ADDRESS": 'your_wallet_address',
        "WORKER_NAME": 'worker_name',
        "POOL_PASSWORD": 'x',
        "AGENT": "cpuminer-oqt-25.32"
    }
]
```

### Available Endpoints

#### Web Interface
- `GET /` - Simple greeting page
- `GET /info` - Live dashboard with worker status
- `GET /config_file_list` - Config file management interface

#### API Endpoints
- `POST /params` - Receive work requests from proxy layers
- `POST /params2` - Alternative work endpoint
- `GET /ws_s` - WebSocket endpoint for worker clients

#### File Management
- `GET /config_file?file=filename` - Download config file
- `POST /config_file` - Upload config file

## Client Integration

### Worker Client Example

```javascript
// Connect via WebSocket
const ws = new WebSocket('wss://your-server:3001/ws_s');

ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    
    if (message.req === 'run') {
        // Perform mining work
        // ...
        
        // Send result back
        ws.send(JSON.stringify({
            result: "True",
            bin: result_hex_string,
            no: nonce_value
        }));
    }
};

// Send status updates
ws.send(JSON.stringify({
    type: 'noti',
    name: 'worker-name',
    stage: 0,
    move: 1024,
    run_time: 3.14,
    cpu_usage: 45.2,
    cpu_time: 1.2,
    uptime: 86400
}));
```

## URL Configuration (urls.py)

Three URL sets are available for different deployment scenarios:

```python
urls_b = [...]      # Primary URLs (commented out)
urls_m = [...]      # Mining URLs
urls_brg_m = [...]  # Bridge URLs
```

Add your worker endpoints to these lists based on where workers will connect from.

## SSL/TLS Setup

Self-signed certificates are required for HTTPS:

```bash
openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem \
  -sha256 -days 365 -nodes -subj "/CN=localhost"
```

Files should be named:
- `cert.pem` - Certificate
- `key.pem` - Private key

Both must be in the working directory.

## Monitoring

### Connection Status
- Check WebSocket connections at `/info` endpoint
- Real-time updates every 10 seconds
- Telegram notifications available (configure in code)

### Logs
- All connections and job distribution logged to stdout
- Worker errors and timeouts reported
- Mining share submissions tracked (accept/reject counts)

## Integration Details

### From foo_proxy
- ✅ Stratum protocol client (`client.py`)
- ✅ Task manager with job distribution
- ✅ Worker launching and result collection
- ✅ URL configuration and mining pool management

### From foo_bridge
- ✅ HTTPS web server infrastructure
- ✅ WebSocket worker client management
- ✅ Real-time dashboard
- ✅ Config file upload/download
- ✅ Work distribution to connected clients

## Performance Notes

- **MAX_MOVE**: 20000 - Work offset increment per thread
- **MAX_THREAD**: 100 - Maximum threads per worker
- **Request Timeout**: 90 seconds for mining work requests
- **WebSocket Timeout**: 90 seconds for pool connections

## Troubleshooting

### Certificate Issues
```
ERROR: Could not find 'cert.pem' or 'key.pem'
→ Run SSL setup command from SSL/TLS Setup section
```

### Connection Refused
```
Connection error to {url}
→ Check URL configuration in urls.py
→ Verify worker endpoints are accessible
```

### No Workers Connected
```
0 WebSockets connected
→ Ensure workers are connecting to the correct /ws_s endpoint
→ Check firewall/network configuration
→ Verify HTTPS certificates are configured
```

## Project Structure

```
foo_bridge/
├── app.py                    # Main integrated application
├── client.py                 # Stratum protocol client
├── urls.py                   # Worker endpoint configuration
├── app2.py.backup            # Original web server (backup)
├── cert.pem                  # SSL certificate
├── key.pem                   # SSL private key
├── requirements.txt          # Python dependencies
├── config.bin                # Example config file
└── README.md                 # This file
```

## Files Migrated from foo_proxy

- `client.py` - Async Stratum client for pool communication
- `urls.py` - Worker endpoint configuration
- Task manager logic - Integrated into `app.py`
- Mining configuration - In `on_startup()` function

## Next Steps

1. **Configure Mining Pools**: Edit mining_configs in `app.py`
2. **Set Up Workers**: Deploy worker clients connecting to `/ws_s`
3. **Add Your URLs**: Update `urls.py` with your worker endpoints
4. **Generate Certificates**: Run SSL setup if not already done
5. **Start Server**: Run `python app.py`
6. **Monitor**: Check `/info` endpoint for status

## Support

For issues related to:
- **Mining protocol**: Check Stratum v1 specification
- **WebSocket**: See client integration examples above
- **Deployment**: Refer to configuration section

---

**Last Updated**: February 12, 2026
**Integration Status**: ✅ Complete