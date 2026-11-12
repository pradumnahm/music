"""
YouTube Audio Local Helper & Server for Slowed + Reverb + 8D Studio
Supports PC and Smartphone browsers on the same local network.
"""

import glob
import http.server
import json
import os
import socket
import subprocess
import sys
import urllib.parse

PORT = int(os.environ.get("PORT", 5000))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = os.path.join(BASE_DIR, "yt_cache")
os.makedirs(TEMP_DIR, exist_ok=True)

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'

class YouTubeAudioHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.send_header('Access-Control-Allow-Private-Network', 'true')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        # Serve the Studio application at root
        if parsed.path in ('', '/'):
            self.path = '/slowed-reverb-8d-studio.html'
            return super().do_GET()

        if parsed.path == '/api/ping':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status":"ok","message":"Local helper active"}')
            return

        if parsed.path == '/api/audio':
            params = urllib.parse.parse_qs(parsed.query)
            target_url = params.get('url', [''])[0]
            if not target_url:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error":"Missing url parameter"}')
                return

            print(f"[Helper] Extracting audio for: {target_url}")
            try:
                cmd = [
                    sys.executable, "-m", "yt_dlp",
                    "--no-warnings",
                    "--no-playlist",
                    "--no-simulate",
                    "-f", "bestaudio[ext=m4a]/bestaudio/best",
                    "-P", TEMP_DIR,
                    "-o", "%(id)s.%(ext)s",
                    "--print", "title",
                    "--print", "filename",
                    target_url
                ]
                proc = subprocess.run(cmd, capture_output=True, text=True)
                if proc.returncode != 0:
                    err = proc.stderr.strip().split("\n")[-1] if proc.stderr else "Extraction failed"
                    raise Exception(err)

                lines = [l.strip() for l in proc.stdout.strip().split("\n") if l.strip()]
                if not lines:
                    raise Exception("yt-dlp produced no output")

                title = lines[0] if len(lines) >= 2 else "YouTube Audio"
                file_path = lines[-1]
                filename = os.path.basename(file_path)

                # Confirm file exists on disk
                if not os.path.exists(os.path.join(TEMP_DIR, filename)):
                    stem = os.path.splitext(filename)[0]
                    matches = glob.glob(os.path.join(TEMP_DIR, f"{stem}.*"))
                    if matches:
                        filename = os.path.basename(matches[0])
                    else:
                        raise Exception(f"File {filename} was not saved to cache")

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                resp = json.dumps({
                    "status": "success",
                    "title": title,
                    "streamUrl": f"/yt_cache/{filename}"
                })
                self.wfile.write(resp.encode('utf-8'))
                print(f"[Helper] Successfully extracted: {title} -> {filename}")

            except Exception as e:
                print(f"[Helper Error] {e}")
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
            return

        return super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == '/api/convert-mp3':
            try:
                length = int(self.headers.get('Content-Length', 0))
                wav_bytes = self.rfile.read(length)
                proc = subprocess.Popen(
                    ['ffmpeg', '-y', '-i', 'pipe:0', '-f', 'mp3', '-b:a', '320k', 'pipe:1'],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                mp3_bytes, err = proc.communicate(input=wav_bytes)
                if proc.returncode != 0:
                    raise Exception(err.decode('utf-8', errors='ignore'))

                self.send_response(200)
                self.send_header('Content-Type', 'audio/mpeg')
                self.send_header('Content-Length', str(len(mp3_bytes)))
                self.end_headers()
                self.wfile.write(mp3_bytes)
                print(f"[Helper] Converted and served MP3 ({len(mp3_bytes)} bytes)")
            except Exception as e:
                print(f"[Helper MP3 Error] {e}")
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
            return

        if parsed.path == '/api/render-video':
            try:
                length = int(self.headers.get('Content-Length', 0))
                wav_bytes = self.rfile.read(length)
                temp_wav = os.path.join(TEMP_DIR, f"render_{os.getpid()}.wav")
                temp_mp4 = os.path.join(TEMP_DIR, f"render_{os.getpid()}.mp4")
                with open(temp_wav, "wb") as f:
                    f.write(wav_bytes)

                cmd = [
                    'ffmpeg', '-y',
                    '-i', temp_wav,
                    '-filter_complex', '[0:a]showwaves=s=1280x720:mode=cline:colors=0x00f0ff|0xa855f7[v]',
                    '-map', '[v]', '-map', '0:a',
                    '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
                    '-c:a', 'aac', '-b:a', '192k',
                    temp_mp4
                ]
                proc = subprocess.run(cmd, capture_output=True)
                if proc.returncode != 0:
                    raise Exception(proc.stderr.decode('utf-8', errors='ignore'))

                with open(temp_mp4, "rb") as f:
                    mp4_bytes = f.read()

                for p in (temp_wav, temp_mp4):
                    if os.path.exists(p):
                        try: os.remove(p)
                        except: pass

                self.send_response(200)
                self.send_header('Content-Type', 'video/mp4')
                self.send_header('Content-Length', str(len(mp4_bytes)))
                self.end_headers()
                self.wfile.write(mp4_bytes)
                print(f"[Helper] Rendered and served MP4 video ({len(mp4_bytes)} bytes)")
            except Exception as e:
                print(f"[Helper Video Error] {e}")
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
            return

        self.send_response(404)
        self.end_headers()

def run():
    server_address = ('0.0.0.0', PORT)
    httpd = http.server.HTTPServer(server_address, YouTubeAudioHandler)
    lan_ip = get_local_ip()
    print("=" * 60)
    print("  Slowed + Reverb + 8D Studio is LIVE!")
    print(f"  💻 Computer: http://127.0.0.1:{PORT}")
    print(f"  📱 Phone:    http://{lan_ip}:{PORT} (connect to same Wi-Fi)")
    print("=" * 60)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping helper...")
        httpd.server_close()

if __name__ == '__main__':
    run()
