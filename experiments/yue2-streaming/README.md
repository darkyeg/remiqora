# Isolated YuE2 listening experiment

This directory contains an opt-in experiment, not an installed-engine update.
It uses the existing YuE2 Q8 model, F16 VAE and ggml CUDA DLLs in LocalAppData.
It does not copy weights, download models, change the desktop installation,
or add experimental native changes to the installer.

Run `Start-Lab.cmd` to open the local listening page. Close generation in the
desktop first. The runner refuses to start alongside another native engine or
build. Only one experiment runs at a time. Stop terminates the lab's own process
tree; generation is not resumable. Audio already published remains on disk.

## Profiles

| Profile | Behavior |
|---|---|
| `installed` | Existing CLI, compact metadata arenas |
| `baseline` | Isolated CLI, experimental behavior disabled |
| `stream` | Publish original VAE output tiles as WAVs as they become ready |
| `workspace` | Streaming plus release of completed prefill scratch; retain copied KV state |
| `chunks` | Acoustic synthesis in 500-frame (20 s) chunks; interleave VAE decoding |

`--release-prefill` combines workspace release with any profile. The listening
page enables it for new chunked runs; the saved `chunks-60s` comparison predates
that combination.

Every profile uses Q8, COT full, guidance 1, eight inference steps and four CPU
threads. Short fixtures use seed 1234, ABC cap 512 and a fixed semantic count.
The user's Japanese fixture uses seed 831001 and the model's normal token caps
(4096 ABC, 9000 semantic), without cutting lyrics to match a duration.

Streaming still waits for the entire ABC and semantic sequence. It is not
immediate singing while lyrics arrive. `chunks` changes acoustic attention
context and can change the voice, arrangement and transitions. Do not infer
equal quality from successful generation. `workspace` retains the entire
attention context and precision; its correctness check compares PCM hashes.

## Reproduce the native build

Prerequisites: Windows x64, Python, Visual Studio 2022 C++ tools, installed
YuE2 v0.8.1 engine and models. Working files live in ignored
`external/audio-stream-lab`, including user lyrics, logs and output audio.

1. Clone `https://github.com/0xShug0/audio.cpp` with submodules at v0.8.1
   into `external/audio-stream-lab/source`. Required commit:
   `f2b4937306daa25f5c78520f3c626ed31495a37a`.
2. Install build tools locally:
   `python -m pip install --no-deps --target external/audio-stream-lab/tooling cmake ninja`.
3. Apply hooks once to the clean pinned checkout:
   `python experiments/yue2-streaming/apply_native_patch.py`.
4. Build: `python experiments/yue2-streaming/build.py`.

The custom build links the installed ggml DLLs through generated import
libraries. CUDA remains available at runtime without installing a CUDA toolkit.
No CUDA kernels or model weights are rebuilt. The native changes are deliberately
outside the main desktop distribution while their quality is evaluated.

Example short probe:

```powershell
python experiments/yue2-streaming/probe.py --profile workspace --name my-workspace-test
```

Full user song (fixtures are local, not committed):

```powershell
python experiments/yue2-streaming/probe.py --profile chunks --release-prefill --full-song --lyrics-file external/audio-stream-lab/user-lyrics.txt --style-file external/audio-stream-lab/user-style.txt --seed 831001 --timeout 610 --name my-song-test
```

Each result directory contains the exact request, native log, timing log,
resource samples, report, completed WAV when successful, and streamed chunks.
Names cannot overwrite previous runs. GPU figures are sampled total device
memory usage, not process-exclusive VRAM or shared GPU memory. These are single
runs with other desktop applications open, not controlled repeated benchmarks.
Reports distinguish forced stopping/timeout from successful completion.
