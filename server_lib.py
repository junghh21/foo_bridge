"""
Reverse Proxy Server Library
Backend servers use this library to register with the reverse proxy and handle incoming requests.
"""

import asyncio
import json
import ssl
import aiohttp
import traceback
import time
import random
from typing import Callable, Dict, Any, Optional


class ReverseProxyServer:
	"""
	Backend server connection to reverse proxy.
	
	Example usage:
	```python
	async def handle_request(data):
		# data['query'] contains the request
		result = await process_request(data['query'])
		return {"response": result}
	
	server = ReverseProxyServer(
		proxy_url="https://proxy.example.com:3001",
		server_name="ollama1",
		request_handler=handle_request,
		params={"model": "llama2", "context": "4k"}
	)
	
	await server.connect()
	```
	"""
	
	def __init__(
		self,
		proxy_url: str,
		server_name: str,
		request_handler: Callable,
		params: Optional[Dict[str, Any]] = None,
		verify_ssl: bool = False,
		retry_interval: int = 5,
		max_retries: int = 0  # 0 = infinite
	):
		"""
		Initialize reverse proxy server connection.
		
		Args:
			proxy_url: URL of the reverse proxy (e.g., "https://localhost:3001")
			server_name: Unique name for this server (used in URL path)
			request_handler: Async function to handle incoming requests
			params: Dictionary of parameters to send during registration
			verify_ssl: Whether to verify SSL certificates
			retry_interval: Seconds to wait before reconnecting
			max_retries: Maximum retry attempts (0 = infinite)
		"""
		self.proxy_url = proxy_url.rstrip('/')
		self.server_name = server_name
		self.request_handler = request_handler
		self.params = params or {}
		self.verify_ssl = verify_ssl
		self.retry_interval = retry_interval
		self.max_retries = max_retries
		
		self.ws = None
		self.session = None
		self.ssl_context = None
		self.is_connected = False
		self.retry_count = 0
		
		# Statistics
		self.stats = {
			"requests_received": 0,
			"requests_processed": 0,
			"errors": 0,
			"bytes_received": 0,
			"bytes_sent": 0,
			"connect_time": None,
			"total_uptime": 0
		}
	
	def _setup_ssl(self):
		"""Setup SSL context without certificate verification"""
		self.ssl_context = ssl.create_default_context()
		if not self.verify_ssl:
			self.ssl_context.check_hostname = False
			self.ssl_context.verify_mode = ssl.CERT_NONE
	
	async def register(self) -> bool:
		"""Register this server with the reverse proxy"""
		try:
			if not self.session:
				self._setup_ssl()
				self.session = aiohttp.ClientSession()
			
			register_url = f"{self.proxy_url}/api/register_server"
			payload = {
				"name": self.server_name,
				"params": self.params
			}
			
			async with self.session.post(
				register_url,
				json=payload,
				ssl=self.ssl_context,
				timeout=aiohttp.ClientTimeout(total=5)
			) as response:
				if response.status == 200:
					data = await response.json()
					print(f"[ReverseProxyServer] Successfully registered as '{self.server_name}'")
					print(f"[ReverseProxyServer] Response: {data}")
					return True
				else:
					print(f"[ReverseProxyServer] Registration failed: {response.status}")
					return False
		except Exception as e:
			print(f"[ReverseProxyServer] Registration error: {e}")
			return False
	
	async def connect(self):
		"""Connect to the reverse proxy via WebSocket"""
		if not self.session:
			self._setup_ssl()
			self.session = aiohttp.ClientSession()
		
		retry_count = 0
		backoff = max(1, self.retry_interval)
		max_backoff = 300
		
		while True:
			try:
				# First, register with proxy
				if not await self.register():
					if self.max_retries > 0 and retry_count >= self.max_retries:
						print(f"[ReverseProxyServer] Max retries reached")
						break
					await asyncio.sleep(self.retry_interval)
					retry_count += 1
					continue
				
				# Then connect via WebSocket
				ws_url = f"{self.proxy_url}/wss/reverse_proxy/{self.server_name}"
				ws_url = ws_url.replace("https://", "wss://").replace("http://", "ws://")
				
				print(f"[ReverseProxyServer] Connecting to {ws_url}...")
				
				async with self.session.ws_connect(
					ws_url,
					ssl=self.ssl_context,
					timeout=aiohttp.ClientTimeout(total=30)
				) as ws:
					self.ws = ws
					self.is_connected = True
					self.retry_count = 0
					self.stats["connect_time"] = time.time()
					print(f"[ReverseProxyServer] Connected to reverse proxy as '{self.server_name}'")
					
					# Handle incoming messages
					await self._handle_messages()
			
			except asyncio.CancelledError:
				print(f"[ReverseProxyServer] Connection cancelled")
				break
			except Exception as e:
				self.is_connected = False
				print(f"[ReverseProxyServer] Connection error: {e}")
				traceback.print_exc()
				
				if self.max_retries > 0 and retry_count >= self.max_retries:
					print(f"[ReverseProxyServer] Max retries reached")
					break
			# Exponential backoff with jitter
			wait = min(max_backoff, backoff)
			jitter = wait * 0.1 * (random.random())
			print(f"[ReverseProxyServer] Retrying in {wait + jitter:.1f}s...")
			await asyncio.sleep(wait + jitter)
			retry_count += 1
			backoff = min(max_backoff, backoff * 2)
		
		await self.close()
	
	async def _handle_messages(self):
		"""Handle incoming messages from the reverse proxy"""
		try:
			async for msg in self.ws:
				if msg.type == aiohttp.WSMsgType.TEXT:
					try:
						data = json.loads(msg.data)
						print(f"[ReverseProxyServer] Received request data: {str(data)[:200]}")
						self.stats["bytes_received"] += len(msg.data)
						self.stats["requests_received"] += 1
						
						# Call the request handler
						try:
							response = await self.request_handler(data)
							if response is None:
								response = {"error": "No response from handler"}
						except Exception as e:
							print(f"[ReverseProxyServer] Handler error: {e}")
							self.stats["errors"] += 1
							response = {"error": str(e)}
						
						# Send response back with request_id.
						# Ensure response fields are top-level so client tunnels can parse them.
						response_data = {"request_id": data.get("request_id")}
						if isinstance(response, dict):
							# merge expected keys like 'status', 'headers', 'body'
							response_data.update(response)
						else:
							# treat non-dict as raw body
							response_data.update({"status": "200 OK", "headers": {}, "body": response})
				
						response_str = json.dumps(response_data)
						await self.ws.send_str(response_str)
						print(f"[ReverseProxyServer] Sent response for request_id={response_data.get('request_id')}")
						self.stats["bytes_sent"] += len(response_str)
						self.stats["requests_processed"] += 1
					
					except json.JSONDecodeError:
						print(f"[ReverseProxyServer] Invalid JSON received")
				
				elif msg.type == aiohttp.WSMsgType.BINARY:
					self.stats["bytes_received"] += len(msg.data)
					self.stats["requests_received"] += 1
					
					# Handle binary data
					try:
						response = await self.request_handler(msg.data)
						if isinstance(response, bytes):
							await self.ws.send_bytes(response)
							self.stats["bytes_sent"] += len(response)
						self.stats["requests_processed"] += 1
					except Exception as e:
						print(f"[ReverseProxyServer] Handler error: {e}")
						self.stats["errors"] += 1
				
				elif msg.type == aiohttp.WSMsgType.ERROR:
					print(f"[ReverseProxyServer] WebSocket error: {self.ws.exception()}")
					break
				
				elif msg.type == aiohttp.WSMsgType.CLOSED:
					print(f"[ReverseProxyServer] WebSocket closed")
					break
		
		except Exception as e:
			print(f"[ReverseProxyServer] Error in message handler: {e}")
			traceback.print_exc()
	
	async def send_notification(self, data: Dict[str, Any]):
		"""Send a notification to connected clients"""
		if self.ws and not self.ws.closed:
			try:
				msg = json.dumps({"notification": data})
				await self.ws.send_str(msg)
				self.stats["bytes_sent"] += len(msg)
			except Exception as e:
				print(f"[ReverseProxyServer] Error sending notification: {e}")
	
	async def close(self):
		"""Close the connection"""
		self.is_connected = False
		if self.ws:
			await self.ws.close()
		if self.session:
			await self.session.close()
		print(f"[ReverseProxyServer] Connection closed")
	
	def get_stats(self) -> Dict[str, Any]:
		"""Get connection statistics"""
		uptime = 0
		if self.stats["connect_time"]:
			uptime = time.time() - self.stats["connect_time"]
		
		return {
			**self.stats,
			"total_uptime": uptime,
			"is_connected": self.is_connected
		}


# Example usage function
async def example_request_handler(data: Dict[str, Any]) -> Dict[str, Any]:
	"""
	Example request handler for a backend service.
	This would be replaced with your actual business logic.
	"""
	print(f"[Example] Received request: {data}")
	
	# Simulate some processing
	await asyncio.sleep(0.1)
	
	return {
		"status": "ok",
		"echo": data.get("query", ""),
		"processed_at": time.time()
	}


async def example_server():
	"""Example usage of ReverseProxyServer"""
	server = ReverseProxyServer(
		proxy_url="https://localhost:3001",
		server_name="example_server",
		request_handler=example_request_handler,
		params={"type": "example", "version": "1.0"},
		verify_ssl=False
	)
	
	try:
		await server.connect()
	except KeyboardInterrupt:
		print("Shutting down...")
		await server.close()


if __name__ == "__main__":
	# Run example server
	asyncio.run(example_server())
