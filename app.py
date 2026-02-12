import json
import ssl
import asyncio
from aiohttp import web, WSMsgType
import os
import sys
import time
from collections import defaultdict
import traceback
import subprocess
import requests
import aiohttp
import importlib
import random
import threading
import redis
import redis_utils

from client import AioStratumClient
import urls

# Lock per URL
url_locks = defaultdict(asyncio.Lock)

# Global mining clients
mining_clients = {}
mining_tasks_main = []

# Reverse Proxy State Management
registered_servers = {}  # {server_name: {"ws": ws, "params": {...}, "connect_time": time, "stats": {...}}}
server_connections = {}  # {server_name: [client_ws1, client_ws2, ...]}
pending_requests = {}    # {request_id: {"client_ws": ws, "server_name": str, "timestamp": time}}
proxy_stats = {          # Global proxy statistics
	"total_requests": 0,
	"total_bytes_sent": 0,
	"total_bytes_received": 0,
	"active_servers": 0,
	"active_clients": 0,
	"request_id_counter": 0,
	"avg_queue_wait": 0.0,
	"total_queued": 0
}

# Configurable timeout for pending requests (seconds)
PROXY_REQUEST_TIMEOUT = 90

async def handle(request: web.Request) -> web.Response:
	"""A simple handler that greets the user."""
	name = request.match_info.get('name', "Anonymous")
	text = f"Hello, {name}, from integrated mining proxy server!"
	return web.Response(text=text)

info_html = \
"""
<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="UTF-8">
	<title>Auto-Refresh Table</title>
	<style>
		table {
			border-collapse: collapse;
			width: 50%;
			margin: 20px auto;
		}
		th, td {
			border: 1px solid #ccc;
			padding: 8px;
			text-align: left;
		}
		th {
			background-color: #f4f4f4;
		}
	</style>
</head>
<body>

	<h2 style="text-align:center;">Live Data Table</h2>
	<table id="data-table">
		<thead>
			<tr>
				<th>name</th>
				<th>stage</th>
				<th>move</th>
				<th>run time</th>
				<th>cpu usage</th>
				<th>cpu_time</th>
				<th>uptime</th>

			</tr>
		</thead>
		<tbody>
			<!-- Data rows will be inserted here -->
		</tbody>
	</table>

	<script>
		const tableBody = document.querySelector("#data-table tbody");

		async function fetchData() {
			try {
				// Replace with your actual JSON endpoint
				//const response = await fetch("https://api.example.com/data.json");
				//const data = await response.json();
				data = $$json$$;
				// Clear existing rows
				tableBody.innerHTML = "";

				// Populate table with new data
				data.forEach(item => {
					const row = document.createElement("tr");
					row.innerHTML = `
						<td>${item.name}</td>
						<td>${item.stage}</td>
						<td>${item.move}</td>
						<td>${item.run_time}</td>
						<td>${item.cpu_usage}</td>
						<td>${item.cpu_time}</td>
						<td>${item.uptime}</td>
					`;
					tableBody.appendChild(row);
				});
			} catch (error) {
				console.error("Error fetching data:", error);
			}
		}

		// Initial fetch
		fetchData();

		setInterval(() => {
			location.reload();
		}, 10000);
	</script>

</body>
</html>
"""

ws_set = {}#set()
async def handle_info(request: web.Request) -> web.Response:
	json_data = [val.get("noti", {}) for key, val in ws_set.items()]
	html = info_html.replace("$$json$$", json.dumps(json_data))
	#print (html)
	return web.Response(text=html, content_type='text/html')

run_q = asyncio.Queue()
submit_q = asyncio.Queue()
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
	#print(headers['Sec-WebSocket-Key'])
	#print(f"Secure connection: {request.secure}")
	#print(f"Scheme: {request.scheme}")
	#print(f"Path: {request.path}")

	key = headers['Sec-WebSocket-Key']
	#ws_set.add(ws)
	ws_set[key] = {'ws': ws}
	async for msg in ws:
		if msg.type == WSMsgType.TEXT:
			try:
				data = json.loads(msg.data)
				if 'result' in data and data['result'] == "True":
					await submit_q.put(data)
				if 'type' in data and data['type'] == "noti":
					ws_set[key]['noti'] = data
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
	del ws_set[key]

	return ws

MAX_MOVE = 20000
MAX_THREAD = 100

# Mining worker function (integrated from taskman.py)
async def worker(id, url, client, job, no):
	cert_file = 'cert.pem'
	key_file = 'key.pem'
	ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
	ssl_context.check_hostname = False
	ssl_context.verify_mode = ssl.CERT_NONE
	ssl_context.load_cert_chain(certfile='cert.pem', keyfile='key.pem')

	try:
		async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=90)) as session:
			async def send_submit (data, job, no_show):
				if "result" in data:
					#print(data)
					if data['result'] == "True":
						import struct
						algo, job_id, bin, mask = struct.unpack("II32sI", bytes.fromhex(data['bin']))
						cur_job_id = int(job['job_id'], 16)
						if cur_job_id == job_id:
							print(f"{client.name}({id}) : {mask:08x} <= {job['mask']}")
							await client.submit(job['job_id'], job['extranonce2'], job['ntime'], data['no'])
						else:
							print (f"Invalid Job {cur_job_id:08x} : {job_id:08x}")
					if no_show == 0:
						print(f"{client.name}({id}) ... {url}")

			import struct
			ALGO = struct.pack("<I", client.algo).hex()
			JOB_ID = int(job['job_id'], 16).to_bytes(4, byteorder='little').hex()
			MASK = struct.pack("<I", client.mask).hex()
			COUNT = struct.pack("<I", client.hash_cnt).hex()
			data_bin = ALGO + \
										JOB_ID + \
										job['bin'] + \
										MASK + \
										COUNT
			if ".vercel.app/" in url \
				or ":3000/" in url:    # or ".fly.dev" in url
				while True:
					async with session.post(url,
								json={'bin': data_bin, 'no': f"{no:08x}", 'id': f"{id:08x}"},
								ssl=ssl_context) as response:
						try:
							content = await response.text()
							data = json.loads(content)
							await send_submit (data, job, 1)
							no = int(data['no'], 16)+1
						except Exception as e:
							print(content, e)
							break
			else:
				async with session.post(url,
							json={'bin': data_bin, 'no': f"{no:08x}", 'id': f"{id:08x}"},
							ssl=ssl_context) as response:
					cnt = 0
					async for line in response.content:
						#print(line)
						line = line.decode('utf-8')
						data = json.loads(line)
						cnt += 1
						await send_submit (data, job, cnt%10)

	except asyncio.CancelledError:
		pass
		#print(f"Worker {id} cancelled.")
	except aiohttp.ClientConnectorError as e:
		print(f"Connection error to {url}: {e}")
	except aiohttp.ClientResponseError as e:
		print(f"Client response error from {url}: {e.status} - {e.message}")
	except json.JSONDecodeError:
		print(f"JSON decode error from {url}. Response was not valid JSON.")
	except  asyncio.TimeoutError:
		print(f"Request timed out! {url}.")
	except Exception as e:
		print(f"An unexpected error occurred in worker {id} for {url}: {e}")
		traceback.print_exc()

# Task manager for mining (integrated from taskman.py)
async def task_manager_loop (CLIENT_NAME, CLIENT_URLS, CLIENT_HASH_CNT, CLIENT_BLOCK_TIME, ALGO, POOL_HOST, POOL_PORT, WALLET_ADDRESS, WORKER_NAME, POOL_PASSWORD, AGENT):
	client = AioStratumClient(CLIENT_NAME, CLIENT_URLS, CLIENT_HASH_CNT, CLIENT_BLOCK_TIME, ALGO, POOL_HOST, POOL_PORT, f"{WALLET_ADDRESS}.{WORKER_NAME}", POOL_PASSWORD, AGENT)
	mining_clients[CLIENT_NAME] = client
	while True:
		try:
			try:
				job = await asyncio.wait_for(client.job_queue.get(), timeout=1)
				client.job_queue.task_done()
			except asyncio.TimeoutError:
				if client._is_closed:
					await client.shutdown_mining_tasks()
					await asyncio.sleep(5)
					await client.connect()
					await client.subscribe()
					await client.authorize()
					await client.subscribe_extranonce()
				continue
			if job['type'] == 1:
				# When a new job arrives, cancel all previous mining tasks
				await client.shutdown_mining_tasks()
				print(f"[{client.name}] Got new job: {job['job_id']}.")			#
				no = random.randint(0x7000000, 0xB0000000)#os.urandom(4).hex()#"40000000"#
				importlib.reload(urls)
				url_list = urls.urls_all[client.urls]
				for i, url in enumerate(url_list):					
					task = asyncio.create_task(worker(i, url, client, job, no))
					client.mining_tasks.append(task)
					no += MAX_MOVE*MAX_THREAD
		except (KeyboardInterrupt, asyncio.CancelledError):
			print(f"[Manager] The manager task itself was cancelled")
			await client.shutdown_mining_tasks()
			break # The manager task itself was cancelled
		except Exception as e:
			print(f"[Manager] Error in manager loop: {e}")
			traceback.print_exc()

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
			bin_data = bytes.fromhex(data['bin'])
			no = int(data['no'], 16)
			id = data['id']
			print(f"Client Req : {request.path} {no=:08x} {id=}")
			print(f"++++++ {len(ws_set)} WebSockets connected ++++++")
			dd = 0
			for key, val in ws_set.items():
				try:
					ws = val['ws']
					if ws.closed:
						del ws_set[key]
						continue
					else:
						new_no = f"{(no+dd):08x}"
						dd += MAX_MOVE*MAX_THREAD
						#print(f"📤 Sending data to WebSocket: {json.dumps(data, indent=2)}")
						await ws.send_json({"req": "run", "path": request.path, "bin": data['bin'], "no": new_no})
				except Exception as e:
					print(f"⚠️ Error sending run to WebSocket: {e}")
			start_time = time.time()
			while True:
				try:
					if time.time() - start_time > 90:
						print(f"Request Timeout : {request.path} {no=:08x} {id=}")
						await response.write_eof()
						break
					item = await asyncio.wait_for(submit_q.get(), 1)
					submit_q.task_done()
					#print(f"📤 Submit item : {json.dumps(item, indent=2)}")
					if 'result' in item and item['result'] == "True":
						print(f"... {item['no']}")
						await response.write(json.dumps(item).encode('utf-8')+b'\r\n')
				except asyncio.TimeoutError:
					#await response.write(json.dumps({"result": "False"}).encode('utf-8')+b'\r\n')
					continue

		except ConnectionResetError:
			print("handle_params Client disconnected during streaming.")
		except Exception as e:
			print(f"An error occurred while handling params: {e}")
		finally:
			for key, val in ws_set.items():
				try:
					ws = val['ws']
					if ws.closed:
						del ws_set[key]
						continue
					else:
						await ws.send_json({"req": "stop"})
				except Exception as e:
					print(f"⚠️ Error sending stop to WebSocket: {e}")

		return response

async def list_config_files(request: web.Request) -> web.Response:
		directory = "./"
		files = [f for f in os.listdir(directory) if os.path.isfile(os.path.join(directory, f))]

		# Generate HTML with download links
		html = """
	<html>
	<head>
		<title>Upload Config File</title>
		<style>
			body {
				font-family: sans-serif;
				padding: 2em;
			}
			.upload-box {
				border: 1px solid #ccc;
				padding: 1em;
				width: 300px;
				margin: auto;
				text-align: center;
				background-color: #f9f9f9;
				border-radius: 8px;
			}
			input[type="file"] {
				margin-bottom: 1em;
			}
			button {
				padding: 0.5em 1em;
				font-size: 1em;
				cursor: pointer;
			}
		</style>
	</head>
	<body>
		<script>
			document.querySelector('input[type="file"]').addEventListener('change', function() {
			const file = this.files[0];
			console.log(file.name); // e.g., "config.json"
		});
		</script>
		<div class="upload-box">
			<h2>Upload Config File</h2>
			<form action="/config_file" method="post" enctype="multipart/form-data">
				<input type="file" name="file" required>
				<br>
				<button type="submit">Upload</button>
			</form>
		</div>
		##insert##
	</body>
	</html>
		"""
		html2 = "<h2>Available Config Files</h2><ul>"
		for file_name in files:
				href = f"/config_file?file={file_name}"
				html2 += f'<li><a href="{href}" download>{file_name}</a></li>'
		html2 += "</ul>"
		html = html.replace("##insert##", html2)
		return web.Response(content_type="text/html", text=html)
	
async def get_config_file(request: web.Request) -> web.StreamResponse:
	try:
		file_name = os.path.basename(request.query.get('file', 'config.json'))
		file_path = f"./{file_name}"

		if not os.path.exists(file_path):
			return web.Response(status=404, text=f"{file_name} not found")

		return web.FileResponse(
			path=file_path,
			headers={'Content-Disposition': f'attachment; filename="{file_name}"'}
		)
	except Exception as e:
		return web.Response(status=500, text=f"Error: {str(e)}")

async def post_config_file(request: web.Request) -> web.Response:
	reader = await request.multipart()
	# Expecting a field named 'file'
	field = await reader.next()
	if field.name != 'file':
		return web.Response(status=400, text="Missing 'file' field")
	# Get filename and sanitize it
	filename = os.path.basename(field.filename)
	save_path = os.path.join("./", filename)
	# Save file to disk
	try:
		with open(save_path, 'wb') as f:
			while True:
				chunk = await field.read_chunk()  # Default chunk size is 8192 bytes
				if not chunk:
					break
				f.write(chunk)
		return web.Response(status=302,headers={'Location': '/config_file_list'})
	except Exception as e:
		return web.Response(status=500, text=f"Upload failed: {str(e)}")

# --- Main Application Setup ---
app = web.Application()
# Routes are registered after handler definitions to avoid NameError

task_timer = None
pending_sweeper_task = None
async def on_startup(app):
	global task_timer, mining_tasks_main
	global pending_sweeper_task
	task_timer = asyncio.create_task(timer_main())
	# start pending request sweeper
	pending_sweeper_task = asyncio.create_task(_pending_request_sweeper())
	
	# Initialize mining clients from main.py config
	# These can be customized in config files later
	mining_configs = [
		{
			"CLIENT_NAME": "micro1",
			"CLIENT_URLS": "urls_m",
			"CLIENT_HASH_CNT": 200,
			"CLIENT_BLOCK_TIME": 60,
			"ALGO": 11,
			"POOL_HOST": 'stratum-eu.rplant.xyz',
			"POOL_PORT": 17022,
			"WALLET_ADDRESS": 'MdVtFbZSobabqiZL7P4Za4ZUZBWwm3VqSS',
			"WORKER_NAME": 'aa',
			"POOL_PASSWORD": 'x',
			"AGENT": "cpuminer-oqt-25.32"
		},
		{
			"CLIENT_NAME": "micro_brg1",
			"CLIENT_URLS": "urls_brg_m",
			"CLIENT_HASH_CNT": 100,
			"CLIENT_BLOCK_TIME": 60,
			"ALGO": 11,
			"POOL_HOST": 'stratum-eu.rplant.xyz',
			"POOL_PORT": 17022,
			"WALLET_ADDRESS": 'MdVtFbZSobabqiZL7P4Za4ZUZBWwm3VqSS',
			"WORKER_NAME": 'hh',
			"POOL_PASSWORD": 'x',
			"AGENT": "cpuminer-oqt-25.32"
		}
	]
	
	for config in mining_configs:
		task = asyncio.create_task(task_manager_loop(
			config["CLIENT_NAME"],
			config["CLIENT_URLS"],
			config["CLIENT_HASH_CNT"],
			config["CLIENT_BLOCK_TIME"],
			config["ALGO"],
			config["POOL_HOST"],
			config["POOL_PORT"],
			config["WALLET_ADDRESS"],
			config["WORKER_NAME"],
			config["POOL_PASSWORD"],
			config["AGENT"]
		))
		mining_tasks_main.append(task)
	
	# Connect all mining clients
	for client_name, client in mining_clients.items():
		task = asyncio.create_task(client.connect())
		mining_tasks_main.append(task)
		await asyncio.sleep(1)  # Stagger connections
		task = asyncio.create_task(client.subscribe())
		mining_tasks_main.append(task)
		await asyncio.sleep(1)

	# Attempt to update Redis with this proxy's public endpoint info
	try:
		r = redis_utils.get_redis_client()
		if r is None:
			print("[ReverseProxy] Redis client not available; skipping write")
		else:
			# get public ip
			public_ip = None
			try:
				resp = requests.get('https://api.ipify.org?format=json', timeout=3)
				public_ip = resp.json().get('ip')
			except Exception:
				public_ip = os.environ.get('PUBLIC_IP', '127.0.0.1')

			proxy_info = {
				"url": f"https://{public_ip}:3001",
				"timestamp": time.time(),
				"public_ip": public_ip
			}
			try:
				r.set('reverse_proxy:latest', json.dumps(proxy_info))
				print(f"[ReverseProxy] Wrote proxy info to Redis: {proxy_info}")
			except Exception as e:
				print(f"[ReverseProxy] Failed to write to Redis: {e}")
	except Exception as e:
		print(f"[ReverseProxy] Redis not configured or unavailable: {e}")
		task = asyncio.create_task(client.authorize())
		mining_tasks_main.append(task)
		await asyncio.sleep(1)
		task = asyncio.create_task(client.subscribe_extranonce())
		mining_tasks_main.append(task)
		await asyncio.sleep(1)

async def on_cleanup(app):
	global task_timer, mining_tasks_main
	global pending_sweeper_task
	task_timer.cancel()
	try:
		await task_timer
	except asyncio.CancelledError:
		print("task_timer cancelled.")
	
	for task in mining_tasks_main:
		task.cancel()
	if pending_sweeper_task:
		pending_sweeper_task.cancel()
	try:
		await asyncio.gather(*mining_tasks_main, return_exceptions=True)
	except:
		pass

app.on_startup.append(on_startup)
app.on_cleanup.append(on_cleanup)

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
	print(f"Starting integrated mining proxy + web server on https://{host}:{port}")
	# runner = web.AppRunner(app)
	# await runner.setup()
	# site = web.TCPSite(runner, host, port, ssl_context=ssl_context)
	# await site.start()
	web.run_app(app, host=host, port=port, ssl_context=ssl_context)
	#web.run_app(app, host=host, port=port)

def telegram_send_message(message, token=None, c_id=None):
	url = f"https://api.telegram.org/bot{token}/sendMessage"
	response = requests.post(url, data={'chat_id': c_id, 'text': message})
	print(response.json())

# ========== REVERSE PROXY HANDLERS ==========

async def register_server(request: web.Request) -> web.Response:
	"""Register a server backend to the reverse proxy"""
	try:
		data = await request.json()
		server_name = data.get('name')
		params = data.get('params', {})
		
		if not server_name:
			return web.Response(status=400, text="Missing 'name' parameter")
		
		registered_servers[server_name] = {
			"name": server_name,
			"params": params,
			"connect_time": time.time(),
			"stats": {
				"requests": 0,
				"bytes_sent": 0,
				"bytes_received": 0,
				"queue_wait_total": 0.0,
				"queue_processed": 0
			},
			"ws": None,  # Will be set when WSS connects
			"queue": [],  # queued payloads when backend temporarily unavailable
			"max_queue": 500
		}
		server_connections[server_name] = []
		
		print(f"[ReverseProxy] Server registered: {server_name} with params: {params}")
		return web.Response(
			status=200,
			text=json.dumps({"status": "ok", "message": f"Server {server_name} registered"}),
			content_type='application/json'
		)
	except Exception as e:
		print(f"[ReverseProxy] Error registering server: {e}")
		return web.Response(status=500, text=f"Error: {str(e)}")


async def _pending_request_sweeper():
	"""Background task that removes stale pending requests and notifies clients."""
	try:
		while True:
			now = time.time()
			expired = []
			for req_id, info in list(pending_requests.items()):
				if now - info.get("timestamp", 0) > PROXY_REQUEST_TIMEOUT:
					expired.append(req_id)

			for req_id in expired:
				info = pending_requests.pop(req_id, None)
				if not info:
					continue
				client_ws = info.get("client_ws")
				try:
					if client_ws and not client_ws.closed:
						await client_ws.send_str(json.dumps({
							"error": "request_timeout",
							"request_id": req_id
						}))
				except Exception:
					pass
				proxy_stats["total_requests"] += 1

			await asyncio.sleep(5)
	except asyncio.CancelledError:
		return
	except Exception as e:
		print(f"[ReverseProxy] pending_request_sweeper error: {e}")

async def handle_reverse_proxy_ws(request: web.Request) -> web.WebSocketResponse:
	"""Handle WebSocket connections for reverse proxy (both servers and clients)"""
	server_name = request.match_info.get('server_name')
	
	if not server_name:
		return web.Response(status=400, text="Missing server name")
	
	ws = web.WebSocketResponse()
	await ws.prepare(request)
	
	peername = request.transport.get_extra_info('peername')
	client_ip = peername[0] if peername else 'unknown'
	
	# Check if this is a server or client connection
	is_server = False
	
	# Server connects first after registration
	if server_name in registered_servers and registered_servers[server_name].get("ws") is None:
		# This is the backend server connecting (or re-connecting when previous ws was cleared)
		registered_servers[server_name]["ws"] = ws
		is_server = True
		registered_servers[server_name]["connect_time"] = time.time()
		print(f"[ReverseProxy] Backend server '{server_name}' connected from {client_ip}")
		# flush queued requests
		queue = registered_servers[server_name].get("queue", [])
		if queue:
			print(f"[ReverseProxy] Flushing {len(queue)} queued requests to backend '{server_name}'")
			while queue:
				entry = queue.pop(0)
				payload = entry['payload']
				enqueue_time = entry.get('enqueue_time', None)
				try:
					await ws.send_str(json.dumps(payload))
					print(f"[ReverseProxy] Flushed request {payload.get('request_id')} to {server_name}")
					if enqueue_time:
						wait = time.time() - enqueue_time
						proxy_stats['avg_queue_wait'] = (proxy_stats.get('avg_queue_wait', 0) + wait) / 2
				except Exception as e:
					print(f"[ReverseProxy] Failed to flush to {server_name}: {e}")
					# push back and stop flushing to avoid busy-loop
					queue.insert(0, payload)
					break
	else:
		# This is a client connecting
		if server_name not in registered_servers:
			await ws.close(code=1008, message="Server not registered")
			return ws
		
		if server_name not in server_connections:
			server_connections[server_name] = []
		server_connections[server_name].append(ws)
		print(f"[ReverseProxy] Client connected to '{server_name}' from {client_ip}")
		proxy_stats["active_clients"] = sum(len(v) for v in server_connections.values())
	
	try:
		async for msg in ws:
			if msg.type == WSMsgType.TEXT:
				try:
					data = json.loads(msg.data)
					
					if is_server:
						# Server sending response to a client request
						request_id = data.get('request_id')
						if request_id and request_id in pending_requests:
							info = pending_requests.get(request_id)
							if not info:
								continue
							# HTTP client waiting via Future
								if "http_future" in info:
									fut = info.pop("http_future")
									try:
										if not fut.done():
											fut.set_result(data)
									except Exception:
										pass
									# compute queue wait if present
									enqueue_time = info.get('enqueue_time') or info.get('timestamp')
									if enqueue_time:
										wait = time.time() - enqueue_time
										# update per-server stats
										srv = registered_servers.get(server_name)
										if srv:
											srv['stats']['queue_wait_total'] += wait
											srv['stats']['queue_processed'] += 1
										# update global avg incrementally
										prev_total = proxy_stats.get('avg_queue_wait', 0.0)
										processed = sum(s.get('stats', {}).get('queue_processed', 0) for s in registered_servers.values())
										if processed > 0:
											# recompute avg across servers
											total_wait = sum(s.get('stats', {}).get('queue_wait_total', 0.0) for s in registered_servers.values())
											proxy_stats['avg_queue_wait'] = total_wait / processed
									print(f"[ReverseProxy] Delivered response for {request_id} to HTTP waiter (wait={wait:.3f}s)")
									proxy_stats["total_requests"] += 1
									pending_requests.pop(request_id, None)
							# WebSocket client waiting
							elif "client_ws" in info:
								client_ws = info.get("client_ws")
								if client_ws and not client_ws.closed:
									try:
										await client_ws.send_str(msg.data)
										print(f"[ReverseProxy] Forwarded response for {request_id} to client WS")
										proxy_stats["total_requests"] += 1
									except Exception:
										print(f"[ReverseProxy] Error sending response to client WS for {request_id}")
									pending_requests.pop(request_id, None)
					else:
						# Client sending request to server
						server_ws = registered_servers[server_name].get("ws")
						if server_ws and not server_ws.closed:
							# Preserve client-supplied request_id when present, otherwise assign one
							if 'request_id' in data and isinstance(data['request_id'], int):
								request_id = data['request_id']
							else:
								request_id = proxy_stats["request_id_counter"]
								proxy_stats["request_id_counter"] += 1
							data['request_id'] = request_id
							pending_requests[request_id] = {
								"client_ws": ws,
								"server_name": server_name,
								"timestamp": time.time(),
								"enqueue_time": time.time()
							}
							try:
								await server_ws.send_str(json.dumps(data))
								registered_servers[server_name]["stats"]["requests"] += 1
								print(f"[ReverseProxy] Forwarded request {request_id} to backend '{server_name}'")
							except Exception as e:
								# If sending to the backend fails, notify client and cleanup
								print(f"[ReverseProxy] Error forwarding to backend {server_name}: {e}")
								try:
									if not ws.closed:
										await ws.send_str(json.dumps({"error": "backend_unavailable", "request_id": request_id}))
								except Exception:
									pass
								pending_requests.pop(request_id, None)
						else:
							# backend not connected: queue payload for later flush
							request_id = proxy_stats["request_id_counter"]
							proxy_stats["request_id_counter"] += 1
							data['request_id'] = request_id
							pending_requests[request_id] = {
								"client_ws": ws,
								"server_name": server_name,
								"timestamp": time.time(),
								"enqueue_time": time.time()
							}
							q = registered_servers[server_name].get('queue')
							if q is None:
								registered_servers[server_name]['queue'] = []
							q = registered_servers[server_name]['queue']
							if len(q) >= registered_servers[server_name].get('max_queue', 500):
								# queue full: notify client and drop
								try:
									if not ws.closed:
										await ws.send_str(json.dumps({"error": "queue_full", "request_id": request_id}))
								except Exception:
									pass
								pending_requests.pop(request_id, None)
							else:
								# store payload with enqueue_time and track queued count
								entry = { 'payload': data, 'enqueue_time': pending_requests[request_id]['enqueue_time'] }
								q.append(entry)
								proxy_stats['total_queued'] = proxy_stats.get('total_queued', 0) + 1
								print(f"[ReverseProxy] Queued request {request_id} for backend '{server_name}' (queue_size={len(q)})")
				except json.JSONDecodeError:
					print(f"[ReverseProxy] Invalid JSON from {server_name}")
			
			elif msg.type == WSMsgType.BINARY:
				# Handle binary data
				if is_server:
					request_id = None
					try:
						# Try to extract request_id from first bytes
						if len(msg.data) >= 4:
							import struct
							request_id = struct.unpack('>I', msg.data[:4])[0]
						
						if request_id and request_id in pending_requests:
							client_ws = pending_requests[request_id]["client_ws"]
							if not client_ws.closed:
								await client_ws.send_bytes(msg.data)
								del pending_requests[request_id]
					except:
						pass
				else:
					server_ws = registered_servers[server_name]["ws"]
					if server_ws and not server_ws.closed:
						await server_ws.send_bytes(msg.data)
	
	except asyncio.CancelledError:
		pass
	except Exception as e:
		print(f"[ReverseProxy] Error in WSS handler: {e}")
	finally:
		if is_server:
			registered_servers[server_name]["ws"] = None
			print(f"[ReverseProxy] Backend server '{server_name}' disconnected")
		else:
			if server_name in server_connections:
				try:
					server_connections[server_name].remove(ws)
				except ValueError:
					pass
			print(f"[ReverseProxy] Client disconnected from '{server_name}'")
		
		proxy_stats["active_clients"] = sum(len(v) for v in server_connections.values())
	
	return ws

async def proxy_dashboard(request: web.Request) -> web.Response:
	"""Dashboard for reverse proxy status and statistics"""
	
	dashboard_html = """
<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="UTF-8">
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<title>Reverse Proxy Dashboard</title>
	<style>
		* {
			margin: 0;
			padding: 0;
			box-sizing: border-box;
		}
		body {
			font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
			background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
			min-height: 100vh;
			padding: 20px;
		}
		.container {
			max-width: 1200px;
			margin: 0 auto;
		}
		header {
			color: white;
			margin-bottom: 30px;
		}
		header h1 {
			font-size: 2.5em;
			margin-bottom: 10px;
		}
		header p {
			font-size: 1.1em;
			opacity: 0.9;
		}
		
		.stats-grid {
			display: grid;
			grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
			gap: 15px;
			margin-bottom: 30px;
		}
		
		.stat-card {
			background: white;
			border-radius: 8px;
			padding: 20px;
			box-shadow: 0 4px 6px rgba(0,0,0,0.1);
		}
		
		.stat-label {
			color: #666;
			font-size: 0.9em;
			margin-bottom: 10px;
			text-transform: uppercase;
			letter-spacing: 0.5px;
		}
		
		.stat-value {
			font-size: 2em;
			font-weight: bold;
			color: #667eea;
		}
		
		.section {
			background: white;
			border-radius: 8px;
			padding: 20px;
			margin-bottom: 20px;
			box-shadow: 0 4px 6px rgba(0,0,0,0.1);
		}
		
		.section h2 {
			color: #333;
			margin-bottom: 15px;
			border-bottom: 2px solid #667eea;
			padding-bottom: 10px;
		}
		
		table {
			width: 100%;
			border-collapse: collapse;
		}
		
						try:
							await ws.send_str(json.dumps(payload))
							print(f"[ReverseProxy] Flushed request {payload.get('request_id')} to {server_name}")
							if enqueue_time:
								wait = time.time() - enqueue_time
								proxy_stats['avg_queue_wait'] = (proxy_stats.get('avg_queue_wait', 0) + wait) / 2
						except Exception as e:
							print(f"[ReverseProxy] Failed to flush to {server_name}: {e}")
							# push back and stop flushing to avoid busy-loop
							queue.insert(0, entry)
							break
			border-bottom: 1px solid #eee;
		}
		
		tr:hover {
			background: #f9f9f9;
		}
		
		.status-badge {
			display: inline-block;
			padding: 4px 12px;
			border-radius: 20px;
			font-size: 0.85em;
			font-weight: 600;
		}
		
		.status-online {
			background: #4caf50;
			color: white;
		}
		
		.status-offline {
			background: #f44336;
			color: white;
		}
		
		.status-empty {
			background: #ff9800;
			color: white;
		}
		
		.empty-state {
			text-align: center;
			color: #999;
			padding: 40px 20px;
		}
		
		.refresh-info {
			text-align: center;
			color: #999;
			font-size: 0.9em;
			margin-top: 20px;
		}
	</style>
</head>
<body>
	<div class="container">
		<header>
			<h1>🔀 Reverse Proxy Dashboard</h1>
			<p>Real-time monitoring and statistics</p>
		</header>
		
		<div class="stats-grid">
			<div class="stat-card">
				<div class="stat-label">Total Requests</div>
				<div class="stat-value" id="total-requests">0</div>
			</div>
			<div class="stat-card">
				<div class="stat-label">Active Servers</div>
				<div class="stat-value" id="active-servers">0</div>
			</div>
			<div class="stat-card">
				<div class="stat-label">Active Clients</div>
				<div class="stat-value" id="active-clients">0</div>
			</div>
			<div class="stat-card">
				<div class="stat-label">Data Sent (KB)</div>
				<div class="stat-value" id="data-sent">0</div>
			</div>
		</div>
		
		<div class="section">
			<h2>📡 Registered Servers</h2>
			<table id="servers-table">
				<thead>
					<tr>
						<th>Server Name</th>
						<th>Status</th>
						<th>Connected Since</th>
						<th>Requests</th>
						<th>Data Sent (KB)</th>
						<th>Parameters</th>
					</tr>
				</thead>
				<tbody id="servers-tbody">
					<tr><td colspan="6" class="empty-state">No servers registered</td></tr>
				</tbody>
			</table>
		</div>
		
		<div class="section">
			<h2>👥 Active Client Connections</h2>
			<table id="clients-table">
				<thead>
					<tr>
						<th>Server Name</th>
						<th>Connected Clients</th>
						<th>Connection IDs</th>
					</tr>
				</thead>
				<tbody id="clients-tbody">
					<tr><td colspan="3" class="empty-state">No active clients</td></tr>
				</tbody>
			</table>
		</div>
		
		<div class="refresh-info">
			Auto-refreshing data every 3 seconds...
		</div>
	</div>
	
	<script>
		async function updateDashboard() {
			try {
				const response = await fetch('/api/proxy_stats');
				const data = await response.json();
				
				// Update stats
				document.getElementById('total-requests').textContent = data.stats.total_requests;
				document.getElementById('active-servers').textContent = data.stats.active_servers;
				document.getElementById('active-clients').textContent = data.stats.active_clients;
				document.getElementById('data-sent').textContent = (data.stats.total_bytes_sent / 1024).toFixed(2);
				
				// Update servers table
				const serversTbody = document.getElementById('servers-tbody');
				if (Object.keys(data.servers).length > 0) {
					serversTbody.innerHTML = Object.entries(data.servers).map(([name, server]) => `
						<tr>
							<td><strong>${name}</strong></td>
							<td>
								<span class="status-badge ${server.ws ? 'status-online' : 'status-offline'}">
									${server.ws ? 'Online' : 'Offline'}
								</span>
							</td>
							<td>${new Date(server.connect_time * 1000).toLocaleString()}</td>
							<td>${server.stats.requests}</td>
							<td>${(server.stats.bytes_sent / 1024).toFixed(2)}</td>
							<td><pre style="margin: 0; font-size: 0.85em;">${JSON.stringify(server.params, null, 2)}</pre></td>
						</tr>
					`).join('');
				} else {
					serversTbody.innerHTML = '<tr><td colspan="6" class="empty-state">No servers registered</td></tr>';
				}
				
				// Update clients table
				const clientsTbody = document.getElementById('clients-tbody');
				if (Object.keys(data.client_connections).length > 0) {
					clientsTbody.innerHTML = Object.entries(data.client_connections).map(([serverName, count]) => `
						<tr>
							<td><strong>${serverName}</strong></td>
							<td>${count}</td>
							<td><span class="status-badge status-online">Connected</span></td>
						</tr>
					`).join('');
				} else {
					clientsTbody.innerHTML = '<tr><td colspan="3" class="empty-state">No active connections</td></tr>';
				}
			} catch (error) {
				console.error('Error updating dashboard:', error);
			}
		}
		
		// Initial update
		updateDashboard();
		
		// Auto-refresh every 3 seconds
		setInterval(updateDashboard, 3000);
	</script>
</body>
</html>
	"""
	
	return web.Response(text=dashboard_html, content_type='text/html')

async def proxy_stats_api(request: web.Request) -> web.Response:
	"""API endpoint for proxy statistics"""
	try:
		stats = {
			"stats": proxy_stats,
			"servers": {
				name: {
					"name": server.get("name"),
					"params": server.get("params"),
					"connect_time": server.get("connect_time"),
					"stats": server.get("stats"),
					"ws": server.get("ws") is not None
				}
				for name, server in registered_servers.items()
			},
			"client_connections": {
				name: len(clients) for name, clients in server_connections.items()
			}
		}
		
		# Update active servers count
		stats["stats"]["active_servers"] = sum(1 for s in registered_servers.values() if s.get("ws"))
		
		return web.Response(
			text=json.dumps(stats),
			content_type='application/json'
		)
	except Exception as e:
		return web.Response(
			status=500,
			text=json.dumps({"error": str(e)}),
			content_type='application/json'
		)


async def handle_http_proxy(request: web.Request) -> web.Response:
	"""Forward incoming HTTP requests to a registered backend over WS and return the backend response."""
	server_name = request.match_info.get('server_name')
	tail = request.match_info.get('tail', '')

	if server_name not in registered_servers:
		return web.Response(status=404, text=f"Server {server_name} not registered")

	# read body first and build payload
	body = await request.read()
	try:
		body_text = body.decode('utf-8')
	except Exception:
		body_text = ''

	payload = {
		'method': request.method,
		'path': '/' + tail,
		'headers': {k: v for k, v in request.headers.items()},
		'body': body_text
	}

	# assign request id and prepare future
	request_id = proxy_stats['request_id_counter']
	proxy_stats['request_id_counter'] += 1
	payload['request_id'] = request_id

	loop = asyncio.get_event_loop()
	fut = loop.create_future()
	pending_requests[request_id] = {
		'http_future': fut,
		'server_name': server_name,
		'timestamp': time.time()
	}

	server_ws = registered_servers[server_name].get('ws')

	if server_ws and not server_ws.closed:
		# forward directly
		try:
			await server_ws.send_str(json.dumps(payload))
		except Exception as e:
			pending_requests.pop(request_id, None)
			return web.Response(status=502, text=f"Failed to forward to backend: {e}")
	else:
		# enqueue for later flush
		q = registered_servers[server_name].setdefault('queue', [])
		if len(q) >= registered_servers[server_name].get('max_queue', 500):
			pending_requests.pop(request_id, None)
			return web.Response(status=503, text='Backend queue full')
		q.append(payload)
		print(f"[ReverseProxy] Queued HTTP request {request_id} for backend '{server_name}' (queue_size={len(q)})")

	# wait for response (either from direct forward or flushed payload)
	try:
		resp_data = await asyncio.wait_for(fut, timeout=PROXY_REQUEST_TIMEOUT)
	except asyncio.TimeoutError:
		pending_requests.pop(request_id, None)
		return web.Response(status=504, text='Gateway Timeout')
	except Exception as e:
		pending_requests.pop(request_id, None)
		return web.Response(status=500, text=str(e))

	# Build response
	status_line = resp_data.get('status', '200 OK')
	try:
		status_code = int(str(status_line).split(' ')[0])
	except Exception:
		status_code = 200

	headers = resp_data.get('headers', {}) or {}
	body = resp_data.get('body', '')
	if isinstance(body, str):
		body_bytes = body.encode('utf-8')
	else:
		body_bytes = body

	proxy_stats['total_bytes_received'] += len(body_bytes)

	return web.Response(status=status_code, body=body_bytes, headers=headers)


# Now register routes (after handlers are defined)
app.add_routes([
	web.get('/', handle),
	web.get('/info', handle_info),
	web.get('/ws_s', handle_ws),
	web.post('/params', handle_params),
	web.post('/params2', handle_params),
	web.get('/config_file_list', list_config_files),
	web.get('/config_file', get_config_file),
	web.post('/config_file', post_config_file),
	# Reverse Proxy Routes
	web.post('/api/register_server', register_server),
	web.get('/wss/reverse_proxy/{server_name}', handle_reverse_proxy_ws),
	web.get('/proxy_dashboard', proxy_dashboard),
	web.get('/api/proxy_stats', proxy_stats_api),
	# HTTP reverse-proxy endpoint: forwards HTTP requests to registered backend via WS
	web.route('*', '/proxy/{server_name}/{tail:.*}', lambda request: handle_http_proxy(request)),
])

async def timer_main():
	next_noti = time.time()+30#3600/2
	while True:
		try:
			await asyncio.sleep(30)
			cur_time = time.time()
			if cur_time > next_noti:
				# report connection
				conns = 0
				sum_stage = 0
				sum_move = 0
				for key, val in ws_set.items():
					if "noti" in val:
						noti = val["noti"]
						if noti["name"] != "undefined":
							conns += 1
							sum_stage += noti["stage"] if isinstance(noti["stage"], int) else 0
							sum_move += noti["move"] if isinstance(noti["move"], int) else 0
				#print(f"Conns:{conns} {sum_stage}/{sum_move}")
				telegram_send_message (f"Conns:{conns} {sum_stage}/{sum_move}", "8490037832:AAHmmxVAkA5DqQjJno2O5Oqy2JEHgsDb9Dg", -1003016231971)
				next_noti = time.time()+3600/2
		except Exception as e:
			print(f"timer_main : {e}")

if __name__ == '__main__':
	script_dir = os.path.dirname(os.path.abspath(__file__))
	os.chdir(script_dir)
	print(f"Working directory set to: {os.getcwd()}")

	result = subprocess.run(['git', 'pull'], capture_output=True, text=True)
	print("STDOUT:", result.stdout)
	print("STDERR:", result.stderr)

	try:
		main()
	except KeyboardInterrupt:
		print("\n[Main] Program terminated by user.")
