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

# Lock per URL
url_locks = defaultdict(asyncio.Lock)

async def handle(request: web.Request) -> web.Response:
	"""A simple handler that greets the user."""
	name = request.match_info.get('name', "Anonymous")
	text = f"Hello, {name}, from your secure aiohttp server!"
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
app.add_routes([
	web.get('/', handle),
	web.get('/info', handle_info),
	web.get('/ws_s', handle_ws),
	web.post('/params', handle_params),
	web.post('/params2', handle_params),
	web.get('/config_file_list', list_config_files),
	web.get('/config_file', get_config_file),
	web.post('/config_file', post_config_file),
])

task_timer = None
async def on_startup(app):
	global task_timer
	task_timer = asyncio.create_task(timer_main())

async def on_cleanup(app):
	global task_timer
	task_timer.cancel()
	try:
		await task_timer
	except asyncio.CancelledError:
		print("task_timer cancelled.")
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
	print(f"Starting secure server on https://{host}:{port}")
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