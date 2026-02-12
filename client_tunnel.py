"""
Reverse Proxy Client Local Port Tunnel Library
Clients use this library to tunnel local services through the reverse proxy.

Example:
  - Local: http://localhost:11434 (Ollama API)
  - Remote: wss://proxy.example.com:3001/wss/reverse_proxy/ollama1
  - Client: Creates tunnel mapping localhost:11434 → ollama1
"""

import asyncio
import ssl
import json
import aiohttp
import traceback
import time
import urllib.parse
import random
from typing import Dict, Optional, Tuple, List
from http.server import BaseHTTPRequestHandler
from io import BytesIO
import os
import redis


class HTTPRequestParser:
	"""Parse HTTP requests from raw bytes"""
	
	@staticmethod
	def parse(data: bytes) -> Optional[Dict]:
		"""Parse HTTP request from bytes"""
		try:
			lines = data.split(b'\r\n')
			if not lines:
				return None
			
			# Parse request line
			request_line = lines[0].decode('utf-8', errors='ignore')
			parts = request_line.split(' ')
			if len(parts) < 3:
				return None
			
			method, path, protocol = parts[0], parts[1], parts[2]
			
			# Parse headers
			headers = {}
			i = 1
			body_start = -1
			for i in range(1, len(lines)):
				if not lines[i]:
					body_start = i + 1
					break
				header_line = lines[i].decode('utf-8', errors='ignore')
				if ':' in header_line:
					key, value = header_line.split(':', 1)
					headers[key.strip().lower()] = value.strip()
			
			# Get body
			body = b''
			if body_start > 0 and body_start < len(lines):
				body = b'\r\n'.join(lines[body_start:])
			
			return {
				'method': method,
				'path': path,
				'protocol': protocol,
				'headers': headers,
				'body': body,
				'raw': data
			}
		except Exception as e:
			print(f"[HTTPParser] Error parsing request: {e}")
			return None


class ReverseProxyClientTunnel:
	"""
	Local HTTP server that tunnels requests through reverse proxy.
	
	Usage:
	```python
	tunnel = ReverseProxyClientTunnel(
		local_port=11434,
		proxy_url="https://proxy.example.com:3001",
		proxy_server_name="ollama1"
	)
	
	await tunnel.start()
	# Now http://localhost:11434 is tunneled to the reverse proxy
	```
	"""
	
	def __init__(
		self,
		local_port: int,
		proxy_url: str,
		proxy_server_name: str,
		local_host: str = "127.0.0.1",
		verify_ssl: bool = False,
		request_timeout: int = 90
	):
		"""
		Initialize reverse proxy client tunnel.
		
		Args:
			local_port: Local port to listen on (e.g., 11434)
			proxy_url: Reverse proxy URL (e.g., "https://proxy.example.com:3001")
			proxy_server_name: Name of the remote server (e.g., "ollama1")
			local_host: Local host to bind to (default: 127.0.0.1)
			verify_ssl: Whether to verify SSL certificates
			request_timeout: Timeout for requests in seconds
		"""
		self.local_port = local_port
		self.local_host = local_host
		self.proxy_url = proxy_url.rstrip('/')
		self.proxy_server_name = proxy_server_name
		self.verify_ssl = verify_ssl
		self.request_timeout = request_timeout
		
		self.server = None
		self.session = None
		self.ws = None
		self.ssl_context = None
		self.request_queue = asyncio.Queue()
		self.response_map = {}  # Maps request_id to response future
		self.is_running = False
		self.request_id_counter = int(time.time() * 1000) % 0xFFFFFFFF
		
		# Statistics
		self.stats = {
			"requests_tunneled": 0,
			"responses_received": 0,
			"errors": 0,
			"bytes_received": 0,
			"bytes_sent": 0,
			"start_time": None,
			"uptime": 0
		}
	
	def _setup_ssl(self):
		"""Setup SSL context without certificate verification"""
		self.ssl_context = ssl.create_default_context()
		if not self.verify_ssl:
			self.ssl_context.check_hostname = False
			self.ssl_context.verify_mode = ssl.CERT_NONE

	async def _resolve_proxy_url_from_redis(self, key: str = 'reverse_proxy:latest', max_wait: int = 10) -> Optional[str]:
		try:
			from redis_utils import get_redis_client
		except Exception as e:
			print(f"[ReverseProxyClientTunnel] Could not import redis_utils: {e}")
			return None

		r = get_redis_client()
		if r is None:
			return None

		deadline = time.time() + max_wait
		while time.time() < deadline:
			try:
				payload = r.get(key)
				if payload:
					data = json.loads(payload)
					url = data.get('url')
					if url:
						print(f"[ReverseProxyClientTunnel] Resolved proxy URL from Redis: {url}")
						return url
			except Exception as e:
				print(f"[ReverseProxyClientTunnel] Error reading Redis key: {e}")
			await asyncio.sleep(1)
		return None
	
	async def _handle_client_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
		"""Handle a single client connection"""
		try:
			peername = writer.get_extra_info('peername')
			print(f"[ReverseProxyClientTunnel] Client connected from {peername}")
			
			# Read HTTP request
			data = b''
			while True:
				try:
					chunk = await asyncio.wait_for(reader.read(4096), timeout=10)
					if not chunk:
						break
					data += chunk
					
					# Check if we have complete HTTP request
					if b'\r\n\r\n' in data:
						break
				except asyncio.TimeoutError:
					break
			
			if not data:
				writer.close()
				await writer.wait_closed()
				return
			
			# Parse HTTP request
			request = HTTPRequestParser.parse(data)
			if not request:
				response = b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n"
				writer.write(response)
				await writer.drain()
				writer.close()
				await writer.wait_closed()
				return
			
			self.stats["requests_tunneled"] += 1
			self.stats["bytes_received"] += len(data)
			
			# Forward to reverse proxy via WebSocket
			self.request_id_counter = (self.request_id_counter + 1) % 0xFFFFFFFF
			request_id = self.request_id_counter
			
			ws_request = {
				"request_id": request_id,
				"method": request['method'],
				"path": request['path'],
				"headers": request['headers'],
				"body": request['body'].decode('utf-8', errors='ignore') if request['body'] else ""
			}
			
			# Send through WebSocket
			if self.ws and not self.ws.closed:
				try:
					await self.ws.send_str(json.dumps(ws_request))
					
					# Wait for response
					response_future = asyncio.Future()
					self.response_map[request_id] = response_future
					
					try:
						response_data = await asyncio.wait_for(
							response_future,
							timeout=self.request_timeout
						)
						
						# Format HTTP response
						response_headers = response_data.get('headers', {})
						response_body = response_data.get('body', '')
						
						# Build response
						status = response_data.get('status', '200 OK')
						response_line = f"HTTP/1.1 {status}\r\n"
						
						headers_str = ""
						content_length = len(response_body.encode() if isinstance(response_body, str) else response_body)
						headers_str += f"Content-Length: {content_length}\r\n"
						
						for key, value in response_headers.items():
							headers_str += f"{key}: {value}\r\n"
						
						http_response = response_line + headers_str + "\r\n"
						
						writer.write(http_response.encode())
						if isinstance(response_body, str):
							writer.write(response_body.encode())
						else:
							writer.write(response_body)
						
						await writer.drain()
						self.stats["responses_received"] += 1
						
					except asyncio.TimeoutError:
						response = b"HTTP/1.1 504 Gateway Timeout\r\nContent-Length: 0\r\n\r\n"
						writer.write(response)
						await writer.drain()
						self.stats["errors"] += 1
					
					finally:
						self.response_map.pop(request_id, None)
				
				except Exception as e:
					print(f"[ReverseProxyClientTunnel] Error forwarding request: {e}")
					response = b"HTTP/1.1 500 Internal Server Error\r\nContent-Length: 0\r\n\r\n"
					writer.write(response)
					await writer.drain()
					self.stats["errors"] += 1
			else:
				response = b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n"
				writer.write(response)
				await writer.drain()
				self.stats["errors"] += 1
		
		except Exception as e:
			print(f"[ReverseProxyClientTunnel] Client handler error: {e}")
			self.stats["errors"] += 1
		
		finally:
			writer.close()
			try:
				await writer.wait_closed()
			except:
				pass
	
	async def _ws_message_handler(self):
		"""Handle WebSocket messages from reverse proxy"""
		try:
			async for msg in self.ws:
				if msg.type == aiohttp.WSMsgType.TEXT:
					try:
						data = json.loads(msg.data)
						self.stats["bytes_sent"] += len(msg.data)
						
						request_id = data.get('request_id')
						if request_id in self.response_map:
							response_future = self.response_map[request_id]
							if not response_future.done():
								response_future.set_result(data)
					
					except json.JSONDecodeError:
						print(f"[ReverseProxyClientTunnel] Invalid JSON from proxy")
				
				elif msg.type == aiohttp.WSMsgType.ERROR:
					print(f"[ReverseProxyClientTunnel] WebSocket error: {self.ws.exception()}")
					break
				
				elif msg.type == aiohttp.WSMsgType.CLOSED:
					print(f"[ReverseProxyClientTunnel] WebSocket closed by proxy")
					break
		
		except Exception as e:
			print(f"[ReverseProxyClientTunnel] Message handler error: {e}")

	async def _heartbeat(self, ws: aiohttp.ClientWebSocketResponse):
		"""Periodic ping to keep the WebSocket alive and detect failures."""
		try:
			while not ws.closed and self.is_running:
				await asyncio.sleep(20)
				try:
					await ws.ping()
				except Exception:
					# ping failure -> break and allow reconnect
					break
		except asyncio.CancelledError:
			return
		except Exception as e:
			print(f"[ReverseProxyClientTunnel] Heartbeat error: {e}")
	
	async def _connect_to_proxy(self):
		"""Connect to reverse proxy via WebSocket"""
		# If proxy_url wasn't provided, attempt to discover via Redis
		if not self.proxy_url:
			found = await self._resolve_proxy_url_from_redis()
			if found:
				self.proxy_url = found.rstrip('/')
			else:
				print("[ReverseProxyClientTunnel] Could not resolve proxy URL from Redis; using configured proxy_url")

		if not self.session:
			self._setup_ssl()
			self.session = aiohttp.ClientSession()
		backoff = max(1, 2)
		max_backoff = 300
		
		while self.is_running:
			try:
				ws_url = f"{self.proxy_url}/wss/reverse_proxy/{self.proxy_server_name}"
				ws_url = ws_url.replace("https://", "wss://").replace("http://", "ws://")
				
				print(f"[ReverseProxyClientTunnel] Connecting to proxy at {ws_url}...")
				
				async with self.session.ws_connect(
					ws_url,
					ssl=self.ssl_context,
					timeout=aiohttp.ClientTimeout(total=15)
				) as ws:
					self.ws = ws
					print(f"[ReverseProxyClientTunnel] Connected to proxy reverse_proxy/{self.proxy_server_name}")
					# start heartbeat
					hb_task = asyncio.create_task(self._heartbeat(ws))
					# Handle messages
					await self._ws_message_handler()
					# cancel heartbeat when connection closed
					if not hb_task.done():
						hb_task.cancel()
			
			except Exception as e:
				print(f"[ReverseProxyClientTunnel] Proxy connection error: {e}")
				if self.is_running:
					# exponential backoff with jitter
					wait = min(max_backoff, backoff)
					jitter = wait * 0.1 * (random.random())
					print(f"[ReverseProxyClientTunnel] Retrying in {wait + jitter:.1f}s...")
					await asyncio.sleep(wait + jitter)
					backoff = min(max_backoff, backoff * 2)
	
	async def start(self):
		"""Start the local tunnel server"""
		try:
			self.is_running = True
			self.stats["start_time"] = time.time()
			
			# Start WebSocket connection to proxy
			proxy_task = asyncio.create_task(self._connect_to_proxy())
			
			# Give proxy connection time to establish
			await asyncio.sleep(1)
			
			# Start local TCP server
			server = await asyncio.start_server(
				self._handle_client_connection,
				self.local_host,
				self.local_port
			)
			
			self.server = server
			print(f"[ReverseProxyClientTunnel] Local tunnel listening on {self.local_host}:{self.local_port}")
			print(f"[ReverseProxyClientTunnel] Proxy server: {self.proxy_server_name}")
			print(f"[ReverseProxyClientTunnel] Proxy URL: {self.proxy_url}")
			
			async with server:
				await server.serve_forever()
		
		except Exception as e:
			print(f"[ReverseProxyClientTunnel] Start error: {e}")
			traceback.print_exc()
		
		finally:
			await self.close()
	
	async def close(self):
		"""Close the tunnel"""
		self.is_running = False
		
		if self.server:
			self.server.close()
			await self.server.wait_closed()
		
		if self.ws:
			await self.ws.close()
		
		if self.session:
			await self.session.close()
		
		print(f"[ReverseProxyClientTunnel] Tunnel closed")
	
	def get_stats(self) -> Dict:
		"""Get tunnel statistics"""
		uptime = 0
		if self.stats["start_time"]:
			uptime = time.time() - self.stats["start_time"]
		
		return {
			**self.stats,
			"uptime": uptime,
			"local_endpoint": f"{self.local_host}:{self.local_port}",
			"proxy_server": self.proxy_server_name
		}


async def example_client_tunnel():
	"""Example usage of ReverseProxyClientTunnel"""
	
	# Example 1: Tunnel Ollama on port 11434
	tunnel_ollama = ReverseProxyClientTunnel(
		local_port=11434,
		proxy_url="https://localhost:3001",
		proxy_server_name="ollama1",
		verify_ssl=False
	)
	
	# Example 2: Tunnel Playwright on port 8080
	tunnel_playwright = ReverseProxyClientTunnel(
		local_port=8080,
		proxy_url="https://localhost:3001",
		proxy_server_name="playwright_test",
		verify_ssl=False
	)
	
	# Run both tunnels
	tasks = [
		asyncio.create_task(tunnel_ollama.start()),
		asyncio.create_task(tunnel_playwright.start()),
	]
	
	try:
		await asyncio.gather(*tasks)
	except KeyboardInterrupt:
		print("Shutting down tunnels...")
		await tunnel_ollama.close()
		await tunnel_playwright.close()


if __name__ == "__main__":
	# Run example tunnels
	try:
		asyncio.run(example_client_tunnel())
	except KeyboardInterrupt:
		print("\nExiting...")
