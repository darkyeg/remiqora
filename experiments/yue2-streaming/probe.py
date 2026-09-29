"""Run one isolated Q8 fixture; sample memory and collect early-audio events."""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import wave

ROOT = Path(__file__).resolve().parents[2]
LAB = ROOT / "external/audio-stream-lab"
ARENAS = {"model_weight_context_mb": 64, "vae_weight_context_mb": 64,
          "ar_prefill_graph_arena_mb": 256, "ar_decode_graph_arena_mb": 128,
          "nar_graph_arena_mb": 256, "vae_graph_arena_mb": 128}


class Counters(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
        (name, ctypes.c_size_t) for name in (
            "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
            "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage", "PrivateUsage")]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=["installed", "baseline", "stream", "chunks", "workspace"], required=True)
    parser.add_argument("--frames", type=int, default=1500)
    parser.add_argument("--chunk-frames", type=int, default=500)
    parser.add_argument("--release-prefill", action="store_true", help="Combine a profile with freeing completed prefix scratch")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--name", required=True)
    parser.add_argument("--lyrics-file", type=Path)
    parser.add_argument("--style-file", type=Path)
    parser.add_argument("--full-song", action="store_true", help="Use the installed model's normal token limits instead of the short fixture caps")
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--engine", type=Path, default=Path(os.environ["LOCALAPPDATA"]) / "Remiqora/engines/YuE2")
    parser.add_argument("--exe", type=Path, help="Test a separately built native CLI against the installed model")
    parser.add_argument("--track-progress", action="store_true")
    args = parser.parse_args()
    if args.profile == "installed" and args.release_prefill:
        parser.error("The installed engine does not contain the workspace experiment")
    if args.frames < 200 or args.frames > 4500 or args.chunk_frames < 200:
        parser.error("Use 200..4500 frames and chunks >=200 frames for this bounded experiment")
    if not args.name.replace("-", "").replace("_", "").isalnum():
        parser.error("name must contain only letters, numbers, - and _")
    active = subprocess.check_output(["tasklist", "/fo", "csv", "/nh"], text=True, errors="replace")
    if any(name in active.lower() for name in ("audiocpp_cli.exe", "audiocpp_server.exe", "ninja.exe", "cl.exe", "nvcc.exe")):
        raise RuntimeError("Another engine or build is active; wait before starting the probe")
    output = LAB / "results" / args.name
    output.mkdir(parents=True, exist_ok=False)
    lyrics = args.lyrics_file.read_text(encoding="utf-8") if args.lyrics_file else "[Verse] A quiet melody under the morning sky.\n[Chorus] We carry the light, we sing through the night."
    style = args.style_file.read_text(encoding="utf-8").strip() if args.style_file else "gentle pop, clear female vocal"
    (output / "input.json").write_text(json.dumps({"lyrics": lyrics, "style": style, "seed": args.seed, "full_song": args.full_song}, ensure_ascii=False, indent=2), encoding="utf-8")
    bindir = args.engine.resolve() / "build/windows-cuda-release/bin"
    exe = args.exe.resolve() if args.exe else (bindir / "audiocpp_cli.exe" if args.profile == "installed" else LAB / "build/bin/audiocpp_cli.exe")
    env = os.environ.copy()
    env["PATH"] = str(bindir) + os.pathsep + env["PATH"]
    if args.track_progress:
        env["REMIQORA_YUE2_PROGRESS_PATH"] = str(output / "progress.json")
    for key in list(env):
        if key.startswith("REMIQORA_LAB_"):
            del env[key]
    if args.profile in ("stream", "chunks", "workspace"):
        env["REMIQORA_LAB_STREAM_DIR"] = str(output / "chunks")
    if args.profile == "workspace" or args.release_prefill:
        env["REMIQORA_LAB_RELEASE_PREFILL"] = "1"
    if args.profile == "chunks":
        env["REMIQORA_LAB_NAR_CHUNK_FRAMES"] = str(args.chunk_frames)
    command = [str(exe), "--task", "gen", "--family", "yue2", "--model", str(args.engine.resolve() / "models/Yue2-3B-GGUF"),
               "--backend", "cuda", "--threads", "4", "--lyrics", lyrics,
               "--request-option", f"style={style}", "--request-option", "cot=full",
               "--request-option", "guidance_scale=1", "--request-option", "num_inference_steps=8",
               "--seed", str(args.seed), "--metrics",
               "--log-file", str(output / "timing.log"), "--out", str(output / "final.wav"),
               "--session-option", "yue2.model_gguf=yue2-3b-q8_0.gguf"]
    if not args.full_song:
        command += ["--request-option", f"semantic_min_tokens={args.frames}",
                    "--request-option", f"semantic_max_tokens={args.frames}",
                    "--request-option", "abc_max_tokens=512"]
    for key, value in ARENAS.items():
        command += ["--session-option", f"yue2.{key}={value}"]
    get_memory = ctypes.windll.psapi.GetProcessMemoryInfo
    get_memory.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    get_memory.restype = wintypes.BOOL
    gpu_samples = []
    done = threading.Event()
    started = time.monotonic()

    def sample_gpu():
        while not done.is_set():
            try:
                value = subprocess.check_output(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                                text=True, timeout=3, creationflags=subprocess.CREATE_NO_WINDOW)
                gpu_samples.append([round(time.monotonic() - started, 3), int(value.splitlines()[0])])
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
            done.wait(0.8)

    monitor = threading.Thread(target=sample_gpu, daemon=True)
    peak_commit = peak_rss = 0
    first_chunk_seconds = None
    progress_samples = {}
    failure = None
    monitor.start()
    with (output / "process.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, cwd=bindir, env=env, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        print(f"{args.profile}: PID {process.pid}, output {output}", flush=True)
        try:
            while process.poll() is None:
                counters = Counters()
                counters.cb = ctypes.sizeof(counters)
                if get_memory(wintypes.HANDLE(int(process._handle)), ctypes.byref(counters), counters.cb):
                    peak_commit = max(peak_commit, counters.PeakPagefileUsage)
                    peak_rss = max(peak_rss, counters.PeakWorkingSetSize)
                if first_chunk_seconds is None and (output / "chunks/chunk_00000.wav").exists():
                    first_chunk_seconds = round(time.monotonic() - started, 3)
                    print(f"First audio chunk ready after {first_chunk_seconds}s", flush=True)
                if args.track_progress:
                    try:
                        snapshot = json.loads((output / "progress.json").read_text(encoding="utf-8"))
                        progress_samples[snapshot["phase"]] = max(
                            progress_samples.get(snapshot["phase"], 0), snapshot["current"])
                    except (OSError, ValueError, KeyError):
                        pass
                if time.monotonic() - started > args.timeout:
                    raise TimeoutError("Probe reached its timeout")
                time.sleep(0.1)
        except BaseException as exc:
            failure = str(exc)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            elapsed = time.monotonic() - started
            done.set()
            monitor.join(timeout=4)
    report = {"profile": args.profile, "fixed_frames": None if args.full_song else args.frames, "full_song": args.full_song, "chunk_frames": args.chunk_frames,
              "release_prefill": args.profile == "workspace" or args.release_prefill,
              "wall_seconds": round(elapsed, 3), "returncode": process.returncode, "failure": failure,
              "first_chunk_seconds": first_chunk_seconds,
              "peak_commit_mib": round(peak_commit / 1048576, 1), "peak_working_set_mib": round(peak_rss / 1048576, 1),
              "gpu_total_used_peak_mib": max((sample[1] for sample in gpu_samples), default=None),
              "gpu_samples": gpu_samples, "command": command}
    if args.track_progress:
        try:
            snapshot = json.loads((output / "progress.json").read_text(encoding="utf-8"))
            progress_samples[snapshot["phase"]] = max(progress_samples.get(snapshot["phase"], 0), snapshot["current"])
        except (OSError, ValueError, KeyError):
            pass
        report["progress_phases"] = progress_samples
    wav = output / "final.wav"
    if wav.exists():
        report["wav_sha256"] = hashlib.sha256(wav.read_bytes()).hexdigest()
        with wave.open(str(wav)) as audio:
            report["audio_seconds"] = audio.getnframes() / audio.getframerate()
            report["pcm_sha256"] = hashlib.sha256(audio.readframes(audio.getnframes())).hexdigest()
    events = output / "chunks/events.jsonl"
    if events.exists():
        report["events"] = [json.loads(line) for line in events.read_text().splitlines()]
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key not in ("command", "gpu_samples", "events")}), flush=True)
    if failure or process.returncode:
        print((output / "process.log").read_text(errors="replace")[-4000:], flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
