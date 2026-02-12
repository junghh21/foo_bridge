"""
Example client for testing the reverse proxy tunnel.

This demonstrates how to use the client tunnel to access remote services
through the reverse proxy as if they were local.
"""

import asyncio
import aiohttp
import json
import time


class SimpleHTTPClient:
	"""Simple HTTP client for testing"""
	
	def __init__(self, base_url: str):
		self.base_url = base_url.rstrip('/')
		self.session = None
		self.ssl_context = None
	
	async def __aenter__(self):
		import ssl
		self.ssl_context = ssl.create_default_context()
		self.ssl_context.check_hostname = False
		self.ssl_context.verify_mode = ssl.CERT_NONE
		self.session = aiohttp.ClientSession()
		return self
	
	async def __aexit__(self, *args):
		if self.session:
			await self.session.close()
	
	async def post(self, path: str, data: dict) -> dict:
		"""Send POST request"""
		try:
			url = f"{self.base_url}{path}"
			async with self.session.post(
				url,
				json=data,
				ssl=self.ssl_context if self.base_url.startswith("https") else None,
				timeout=aiohttp.ClientTimeout(total=30)
			) as response:
				return await response.json()
		except Exception as e:
			return {"error": str(e)}
	
	async def get(self, path: str) -> dict:
		"""Send GET request"""
		try:
			url = f"{self.base_url}{path}"
			async with self.session.get(
				url,
				ssl=self.ssl_context if self.base_url.startswith("https") else None,
				timeout=aiohttp.ClientTimeout(total=30)
			) as response:
				return await response.text()
		except Exception as e:
			return {"error": str(e)}


async def test_echo_server():
	"""Test echo server through reverse proxy"""
	print("\n" + "="*60)
	print("Testing Echo Server")
	print("="*60)
	
	async with SimpleHTTPClient("http://localhost:11434") as client:
		test_data = {
			"message": "Hello from echo test",
			"timestamp": time.time()
		}
		
		print(f"\n[Client] Sending request: {test_data}")
		response = await client.post("", test_data)
		print(f"[Client] Received response: {json.dumps(response, indent=2)}")


async def test_calculator_server():
	"""Test calculator server through reverse proxy"""
	print("\n" + "="*60)
	print("Testing Calculator Server")
	print("="*60)
	
	async with SimpleHTTPClient("http://localhost:8081") as client:
		test_cases = [
			{"operation": "add", "a": 10, "b": 5},
			{"operation": "multiply", "a": 7, "b": 3},
			{"operation": "subtract", "a": 100, "b": 25},
			{"operation": "divide", "a": 20, "b": 4},
		]
		
		for test in test_cases:
			print(f"\n[Client] Sending: {test}")
			response = await client.post("", test)
			print(f"[Client] Result: {json.dumps(response, indent=2)}")
			await asyncio.sleep(0.5)


async def test_ai_inference_server():
	"""Test AI inference server through reverse proxy"""
	print("\n" + "="*60)
	print("Testing AI Inference Server")
	print("="*60)
	
	async with SimpleHTTPClient("http://localhost:8082") as client:
		test_prompts = [
			{"prompt": "What is machine learning?", "model": "llama2"},
			{"prompt": "Explain quantum computing", "model": "gpt-4"},
			{"prompt": "How does photosynthesis work?", "model": "llama2"},
		]
		
		for test in test_prompts:
			print(f"\n[Client] Sending: {test}")
			response = await client.post("", test)
			print(f"[Client] Response: {json.dumps(response, indent=2)}")
			await asyncio.sleep(1)  # Longer delay to simulate processing


async def test_reverse_proxy_dashboard():
	"""Test reverse proxy dashboard"""
	print("\n" + "="*60)
	print("Testing Reverse Proxy Dashboard")
	print("="*60)
	
	async with SimpleHTTPClient("https://localhost:3001") as client:
		print("\n[Client] Fetching dashboard...")
		dashboard = await client.get("/proxy_dashboard")
		print(f"[Client] Dashboard URL: https://localhost:3001/proxy_dashboard")
		print(f"[Client] Dashboard retrieved (length: {len(dashboard)} chars)")
		
		print("\n[Client] Fetching proxy stats API...")
		stats = await client.get("/api/proxy_stats")
		print(f"[Client] Stats: {stats[:200]}...")


async def run_all_tests():
	"""Run all client tests"""
	print("\n" + "="*60)
	print("Reverse Proxy Client Test Suite")
	print("="*60)
	print("\nMake sure the following services are running:")
	print("  1. Reverse Proxy: https://localhost:3001")
	print("  2. Echo Server: tunneled to localhost:11434")
	print("  3. Calculator Server: tunneled to localhost:8081")
	print("  4. AI Inference Server: tunneled to localhost:8082")
	print("\nStarting tests...\n")
	
	# Give servers time to connect
	await asyncio.sleep(2)
	
	try:
		# Test each server
		await test_echo_server()
		await asyncio.sleep(1)
		
		await test_calculator_server()
		await asyncio.sleep(1)
		
		await test_ai_inference_server()
		await asyncio.sleep(1)
		
		await test_reverse_proxy_dashboard()
	
	except Exception as e:
		print(f"\n[Error] {e}")
		import traceback
		traceback.print_exc()


async def interactive_test():
	"""Interactive client for manual testing"""
	print("\n" + "="*60)
	print("Interactive Reverse Proxy Client")
	print("="*60)
	print("\nUsage:")
	print("  This client exposes local tunnels for testing")
	print("  - Echo: http://localhost:11434")
	print("  - Calculator: http://localhost:8081")
	print("  - AI: http://localhost:8082")
	print("\nMake sure to run example_servers.py and then client_tunnel.py first!")
	print("\nPress Ctrl+C to exit")
	print("="*60 + "\n")
	
	try:
		while True:
			await asyncio.sleep(1)
	except KeyboardInterrupt:
		print("\nExiting interactive mode...")


if __name__ == "__main__":
	import sys
	
	if len(sys.argv) > 1 and sys.argv[1] == "interactive":
		asyncio.run(interactive_test())
	else:
		asyncio.run(run_all_tests())
