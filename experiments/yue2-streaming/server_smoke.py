"""Start the adopted native server briefly against installed runtime DLLs."""
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
EXE = ROOT / "desktop/native/win32-x64/remiqora_yue2_server.exe"
ENGINE = Path(os.environ["LOCALAPPDATA"]) / "Remiqora/engines/YuE2"
BINDIR = ENGINE / "build/windows-cuda-release/bin"
LOG = ROOT / "external/audio-stream-lab/results/release-server-smoke.log"


def main():
    active = subprocess.check_output(["tasklist", "/fo", "csv", "/nh"], text=True, errors="replace").lower()
    if any(name in active for name in ("audiocpp_cli.exe", "audiocpp_server.exe", "ninja.exe", "cl.exe", "nvcc.exe", "cmake.exe")):
        raise RuntimeError("Another native engine or build is active")
    env = os.environ.copy()
    env["PATH"] = str(BINDIR) + os.pathsep + env["PATH"]
    for key in list(env):
        if key.startswith("REMIQORA_LAB_"):
            del env[key]
    with LOG.open("w", encoding="utf-8") as out:
        process = subprocess.Popen([str(EXE), "--ui", "--ui-management", "--backend", "cuda",
                                    "--max-loaded-models", "1", "--host", "127.0.0.1", "--port", "8898"],
                                   cwd=ENGINE, env=env, stdout=out, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"Server exited {process.returncode}: {LOG.read_text(errors='replace')[-2000:]}")
                try:
                    with urlopen("http://127.0.0.1:8898/health", timeout=2) as response:
                        health = response.status
                    with urlopen("http://127.0.0.1:8898/v1/models", timeout=2) as response:
                        models = json.load(response)
                    print(json.dumps({"health": health, "models_response": models, "pid": process.pid}))
                    return
                except OSError:
                    time.sleep(0.25)
            raise TimeoutError(f"Server was not healthy: {LOG.read_text(errors='replace')[-2000:]}")
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
