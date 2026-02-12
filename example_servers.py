"""
Simple example servers for testing the reverse proxy.

These are sample applications that register with the reverse proxy
and respond to requests.
"""

import asyncio
import json
import aiohttp
from server_lib import ReverseProxyServer


# ===== Example 1: Echo Server =====
async def echo_handler(data):
	"""Simple echo server that returns what it receives"""
	if isinstance(data, dict):
		return {
			"echo": data,
			"timestamp": asyncio.get_event_loop().time()
		}
	return {"error": "Invalid request"}


async def run_echo_server():
	"""Run echo server"""
	server = ReverseProxyServer(
		proxy_url="https://localhost:3001",
		server_name="echo_server",
		request_handler=echo_handler,
		params={"type": "echo", "version": "1.0"},
		verify_ssl=False
	)
	
	print("[Echo Server] Starting...")
	await server.connect()


# ===== Example 2: Math Calculator Server =====
async def calculator_handler(data):
	"""Simple math calculator"""
	try:
		if not isinstance(data, dict):
			return {"error": "Expected JSON object"}
		
		operation = data.get("operation")
		a = data.get("a")
		b = data.get("b")
		
		if operation == "add":
			result = a + b
		elif operation == "subtract":
			result = a - b
		elif operation == "multiply":
			result = a * b
		elif operation == "divide":
			result = a / b
		else:
			return {"error": f"Unknown operation: {operation}"}
		
		return {
			"operation": operation,
			"a": a,
			"b": b,
			"result": result
		}
	
	except Exception as e:
		return {"error": str(e)}


async def run_calculator_server():
	"""Run calculator server"""
	server = ReverseProxyServer(
		proxy_url="https://localhost:3001",
		server_name="calculator",
		request_handler=calculator_handler,
		params={"type": "calculator", "version": "1.0"},
		verify_ssl=False
	)
	
	print("[Calculator Server] Starting...")
	await server.connect()


# ===== Example 3: AI Inference Mock Server =====
async def ai_handler(data):
	"""Mock AI inference handler"""
	try:
		if not isinstance(data, dict):
			return {"error": "Expected JSON object"}
		
		prompt = data.get("prompt", "")
		model = data.get("model", "default")
		
		# Simulate some processing
		await asyncio.sleep(0.5)
		
		# Mock response
		return {
			"model": model,
			"prompt": prompt,
			"response": f"Mock response from {model} for prompt: {prompt[:50]}...",
			"tokens_used": len(prompt.split()) * 2
		}
	
	except Exception as e:
		return {"error": str(e)}


async def run_ai_server():
	"""Run AI inference mock server"""
	server = ReverseProxyServer(
		proxy_url="https://localhost:3001",
		server_name="ai_inference",
		request_handler=ai_handler,
		params={"type": "ai", "model": "llama2", "version": "1.0"},
		verify_ssl=False
	)
	
	print("[AI Inference Server] Starting...")
	await server.connect()


# ===== Run Multiple Servers =====
async def run_all_servers():
	"""Run all example servers simultaneously"""
	tasks = [
		asyncio.create_task(run_echo_server()),
		asyncio.create_task(run_calculator_server()),
		asyncio.create_task(run_ai_server()),
	]
	
	try:
		await asyncio.gather(*tasks)
	except KeyboardInterrupt:
		print("\n[Services] Shutting down...")
		for task in tasks:
			task.cancel()
		await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
	print("=" * 60)
	print("Reverse Proxy Example Servers")
	print("=" * 60)
	print("Running servers:")
	print("  1. Echo Server (echo_server)")
	print("  2. Calculator (calculator)")
	print("  3. AI Inference Mock (ai_inference)")
	print()
	print("Make sure the reverse proxy is running on https://localhost:3001")
	print("=" * 60)
	print()
	
	try:
		asyncio.run(run_all_servers())
	except KeyboardInterrupt:
		print("\nExiting...")
