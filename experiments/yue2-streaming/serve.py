"""Local, opt-in listening lab. It never starts or updates the installed app."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse
import webbrowser

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parents[1] / "external/audio-stream-lab/results"
TOKEN = secrets.token_urlsafe(24)
LOCK = threading.Lock()
process = None
job = None
log_file = None


def stop_owned():
    global process, log_file
    with LOCK:
        if process is not None and process.poll() is None:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            process.wait(timeout=15)
        if log_file is not None:
            log_file.close()
            log_file = None


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def reply(self, value, code=200):
        body = json.dumps(value).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            body = (HERE / "index.html").read_text(encoding="utf-8").replace("__LAB_TOKEN__", TOKEN).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/status":
            with LOCK:
                status = {"job": job, "running": process is not None and process.poll() is None, "events": []}
                if job:
                    directory = RESULTS / job["name"]
                    events = directory / "chunks/events.jsonl"
                    if events.exists():
                        for line in events.read_text().splitlines():
                            try:
                                status["events"].append(json.loads(line))
                            except json.JSONDecodeError:
                                pass
                    tokens = directory / "chunks/tokens.jsonl"
                    if tokens.exists():
                        lines = tokens.read_text().splitlines()
                        for line in reversed(lines[-2:]):
                            try:
                                status["tokens"] = json.loads(line)
                                break
                            except json.JSONDecodeError:
                                pass
                    report = directory / "report.json"
                    if report.exists():
                        try:
                            status["report"] = json.loads(report.read_text())
                        except json.JSONDecodeError:
                            pass
                    if not status["running"] and process is not None:
                        status["exitcode"] = process.returncode
            self.reply(status)
            return
        # Only audio files from the lab results can be served, with no directory listings.
        target = (RESULTS / path.lstrip("/")).resolve()
        if not target.is_relative_to(RESULTS.resolve()) or target.suffix not in (".wav", ".mp3") or not target.is_file():
            self.send_error(404)
            return
        super().do_GET()

    def do_POST(self):
        global process, job, log_file
        if self.headers.get("X-Lab-Token") != TOKEN:
            self.reply({"error": "Invalid local session"}, 403)
            return
        if self.path == "/stop":
            stop_owned()
            self.reply({"stopped": True})
            return
        if self.path != "/start":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 1024:
                raise ValueError("Invalid request size")
            request = json.loads(self.rfile.read(length))
            profile = request.get("profile")
            seconds = request.get("seconds")
            sample = request.get("sample", "fixture")
            if profile not in ("baseline", "stream", "chunks", "workspace") or seconds not in (60, 180) or sample not in ("fixture", "song"):
                raise ValueError("Choose a listed profile and duration")
            lab = RESULTS.parent
            if sample == "song" and not all((lab / file).exists() for file in ("user-lyrics.txt", "user-style.txt")):
                raise ValueError("The local song fixture is missing")
            with LOCK:
                if process is not None and process.poll() is None:
                    self.reply({"error": "The lab is already generating"}, 409)
                    return
                name = f"listen-{time.time_ns()}"
                RESULTS.mkdir(parents=True, exist_ok=True)
                if log_file is not None:
                    log_file.close()
                log_file = (RESULTS / f"{name}.log").open("w", encoding="utf-8")
                command = [sys.executable, str(HERE / "probe.py"), "--profile", profile,
                           "--frames", str(seconds * 25), "--name", name]
                if profile == "chunks":
                    command += ["--release-prefill"]
                if sample == "song":
                    command += ["--full-song", "--lyrics-file", str(lab / "user-lyrics.txt"),
                                "--style-file", str(lab / "user-style.txt"), "--seed", "831001", "--timeout", "1200"]
                process = subprocess.Popen(command,
                                           stdout=log_file, stderr=subprocess.STDOUT,
                                           creationflags=subprocess.CREATE_NO_WINDOW)
                job = {"name": name, "profile": profile, "seconds": seconds, "sample": sample}
            self.reply(job)
        except (ValueError, OSError) as exc:
            self.reply({"error": str(exc)}, 400)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8897)
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), partial(Handler, directory=str(RESULTS)))
    print(f"YuE2 listening lab: http://127.0.0.1:{server.server_port}", flush=True)
    if args.open:
        webbrowser.open(f"http://127.0.0.1:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_owned()
        server.server_close()


if __name__ == "__main__":
    main()
