"""
Example client tunnel configuration.

Run this to create local port tunnels that route through the reverse proxy.
"""

import asyncio
from client_tunnel import ReverseProxyClientTunnel


async def run_client_tunnels():
	"""Run multiple local tunnels"""
	
	# Configuration for multiple tunnels
	# Each tuple is (local_port, proxy_server_name)
	tunnel_config = [
		(11434, "echo_server"),         # localhost:11434 → echo_server
		(8081, "calculator"),            # localhost:8081 → calculator
		(8082, "ai_inference"),          # localhost:8082 → ai_inference
	]
	
	print("="*60)
	print("Reverse Proxy Client Tunnels")
	print("="*60)
	print("\nConfiguration:")
	for local_port, server_name in tunnel_config:
		print(f"  http://localhost:{local_port} → {server_name}")
	print("\nMake sure the reverse proxy is running on https://localhost:3001")
	print("="*60)
	print()
	
	tunnels = []
	for local_port, server_name in tunnel_config:
		tunnel = ReverseProxyClientTunnel(
			local_port=local_port,
			proxy_url="https://localhost:3001",
			proxy_server_name=server_name,
			local_host="127.0.0.1",
			verify_ssl=False,
			request_timeout=30
		)
		tunnels.append(tunnel)
	
	# Start all tunnels
	tasks = [asyncio.create_task(tunnel.start()) for tunnel in tunnels]
	
	try:
		await asyncio.gather(*tasks)
	except KeyboardInterrupt:
		print("\n\nShutting down tunnels...")
		for tunnel in tunnels:
			await tunnel.close()
		
		print("\nTunnel statistics:")
		for tunnel in tunnels:
			stats = tunnel.get_stats()
			print(f"\n{stats['local_endpoint']} → {stats['proxy_server']}:")
			print(f"  Requests tunneled: {stats['requests_tunneled']}")
			print(f"  Responses received: {stats['responses_received']}")
			print(f"  Errors: {stats['errors']}")
			print(f"  Bytes sent: {stats['bytes_sent']}")
			print(f"  Bytes received: {stats['bytes_received']}")
			print(f"  Uptime: {stats['uptime']:.1f}s")


if __name__ == "__main__":
	try:
		asyncio.run(run_client_tunnels())
	except KeyboardInterrupt:
		print("\nExiting...")
