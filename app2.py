import json
import ssl
import asyncio
from aiohttp import web, WSMsgType
import os
import sys
import time
from collections import defaultdict

# Lock per URL
url_locks = defaultdict(asyncio.Lock)

async def handle(request: web.Request) -> web.Response:
	"""A simple handler that greets the user."""
	name = request.match_info.get('name', "Anonymous")
	text = f"Hello, {name}, from your secure aiohttp server!"
	return web.Response(text=text)

async def handle_info(request: web.Request) -> web.Response:
	json_data = {	'cpu_count': os.cpu_count(),
								'platform': sys.platform,
								'python_version': sys.version,
								'working_directory': os.getcwd(),
								'pid': os.getpid(),
								'cpu_usage': os.popen(f'ps -p {os.getpid()} -o %cpu').read().strip(),
								'memory_usage': os.popen(f'ps -p {os.getpid()} -o %mem').read().strip(),
								'uptime': time.time() - os.path.getmtime('/proc/1/stat'),
							}
	return web.json_response(json_data)

run_q = asyncio.Queue()
submit_q = asyncio.Queue()
ws_set = set()
# WebSocket handler
async def handle_ws(request):
	ws = web.WebSocketResponse()
	await ws.prepare(request)

	#print("🔌 WSS client connected")
	peername = request.transport.get_extra_info('peername')
	headers = dict(request.headers)
	client_ip = peername[0] if peername else 'unknown'
	client_port = peername[1] if peername else 'unknown'
	print(f"Client IP: {client_ip}, Port: {client_port}")
	#print(f"Request headers: {json.dumps(headers, indent=2)}")
	#print(f"Secure connection: {request.secure}")
	#print(f"Scheme: {request.scheme}")
	#print(f"Path: {request.path}")
	ws_set.add(ws)
	async for msg in ws:
		if msg.type == WSMsgType.TEXT:
			try:
				data = json.loads(msg.data)
				await submit_q.put(data)
			except json.JSONDecodeError:
				print("⚠️ Invalid JSON received")
			except Exception as e:
				print(f"⚠️ Error processing message: {e}")
		elif msg.type == WSMsgType.ERROR:
			print(f"⚠️ WebSocket error: {ws.exception()}")
			break
		elif msg.type == WSMsgType.CLOSE:
			print("🔌 WebSocket connection closed by client")
			break
	print("🔌 WSS client disconnected")
	ws_set.remove(ws)
	return ws

async def handle_params(request: web.Request) -> web.StreamResponse:
	async with url_locks[request.path]:  # Wait if another coroutine is using this URL
		try:
			response = web.StreamResponse(
				status=200,
				reason='OK',
				headers={'Content-Type': 'application/json', 'X-Content-Type-Options': 'nosniff'},
			)
			await response.prepare(request)
			await response.write(json.dumps({"start": "True"}).encode('utf-8')+b'\r\n')

			data = await request.json()
			#print(f"📥 Received params: {json.dumps(data, indent=2)}")
			close_list = []
			for ws in ws_set:
				if ws.closed:
					close_list.append(ws)
			for ws in close_list:
				ws_set.remove(ws)
			print(f"++++++ {len(ws_set)} WebSockets connected ++++++")
			for ws in ws_set:
				try:
					if ws.closed:
						continue
					else:
						#print(f"📤 Sending data to WebSocket: {json.dumps(data, indent=2)}")
						await ws.send_json({"req": "run", "path": request.path, "bin": data['bin'], "no": data['no'], "mask": data['mask']})
				except Exception as e:
					print(f"⚠️ Error sending run to WebSocket: {e}")
			while True:
				try:
					item = await asyncio.wait_for(submit_q.get(), 1)
				except asyncio.TimeoutError:
					await response.write(json.dumps({"result": "False"}).encode('utf-8')+b'\r\n')
					continue
				print(f"📤 Submit item : {json.dumps(item, indent=2)}")
				await response.write(json.dumps(item).encode('utf-8')+b'\r\n')
			await response.write_eof()

		except ConnectionResetError:
			print("handle_params Client disconnected during streaming.")
		except Exception as e:
			print(f"An error occurred while handling params: {e}")
		finally:
			for ws in ws_set:
				try:
					if ws.closed:
						continue
					else:
						await ws.send_json({"req": "stop"})
				except Exception as e:
					print(f"⚠️ Error sending stop to WebSocket: {e}")
		return response

# --- Main Application Setup ---
app = web.Application()
app.add_routes([
	web.get('/', handle),
	web.get('/info', handle_info),
	web.get('/ws_s', handle_ws),
	web.post('/params', handle_params),
 	web.post('/params2', handle_params)
])

def main():
	global ws_queue
	#asyncio.create_task(bell())
	#asyncio.create_task(micro())
	ws_queue = asyncio.Queue()
	
	"""Sets up the SSL context and runs the aiohttp application."""
	cert_file = 'cert.pem'
	key_file = 'key.pem'

	# --- SSL Context Setup ---
	# For a robust and secure server, it's recommended to use
	# ssl.create_default_context.
	# ssl.Purpose.CLIENT_AUTH means the context is for a server-side socket,
	# which will authenticate clients.
	ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
	ssl_context.check_hostname = False
	ssl_context.verify_mode = ssl.CERT_NONE
	# Load your server's certificate and private key.
	# In a production environment, you would use a certificate from a
	# trusted Certificate Authority (CA) like Let's Encrypt.
	try:
		ssl_context.load_cert_chain(certfile=cert_file, keyfile=key_file)
		print(f"Successfully loaded certificate from '{cert_file}' and key from '{key_file}'.")
	except FileNotFoundError:
		print("=" * 60)
		print(f"ERROR: Could not find '{cert_file}' or '{key_file}'.")
		print("You can generate a self-signed certificate for development with:")
		print('openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -sha256 -days 365 -nodes -subj "/CN=localhost"')
		print("=" * 60)
		return
	except ssl.SSLError as e:
		print(f"An SSL error occurred: {e}")
		print("Please ensure your certificate and key files are valid and match.")
		return
	# --- Run the application with HTTPS ---
	# Passing the `ssl_context` to `run_app` is what enables HTTPS.
	host = '0.0.0.0'
	port = 3001
	print(f"Starting secure server on https://{host}:{port}")
	web.run_app(app, host=host, port=port, ssl_context=ssl_context)
	#web.run_app(app, host=host, port=port)

if __name__ == '__main__':
	script_dir = os.path.dirname(os.path.abspath(__file__))
	os.chdir(script_dir)
	print(f"Working directory set to: {os.getcwd()}")

	try:
		main()
	except KeyboardInterrupt:
		print("\n[Main] Program terminated by user.")
