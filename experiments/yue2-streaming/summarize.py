"""Summarize saved probes and verify complete streamed PCM coverage."""
import hashlib
import json
from pathlib import Path
import wave

RESULTS = Path(__file__).resolve().parents[2] / "external/audio-stream-lab/results"


def main():
    for directory in sorted(RESULTS.iterdir()):
        path = directory / "report.json"
        if not path.exists():
            continue
        report = json.loads(path.read_text())
        summary = {"name": directory.name, **{key: report.get(key) for key in (
            "returncode", "wall_seconds", "audio_seconds", "first_chunk_seconds",
            "peak_commit_mib", "peak_working_set_mib", "gpu_total_used_peak_mib", "pcm_sha256")}}
        events = report.get("events", [])
        if report.get("returncode") == 0 and any("file" in event for event in events):
            digest = hashlib.sha256()
            frames = 0
            for event in events:
                if "file" not in event:
                    continue
                assert event["start_frame"] == frames, "Stream has a gap or duplicated frames"
                with wave.open(str(directory / "chunks" / event["file"])) as part:
                    assert part.getnframes() == event["frames"]
                    digest.update(part.readframes(part.getnframes()))
                    frames += part.getnframes()
            assert digest.hexdigest() == report["pcm_sha256"], "Stream PCM differs from completed WAV"
            summary["stream_pcm_matches_final"] = True
        print(json.dumps(summary))


if __name__ == "__main__":
    main()
