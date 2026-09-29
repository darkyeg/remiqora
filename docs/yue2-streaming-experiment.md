# YuE2: streaming and prefill workspace experiment

Measured on 2026-09-29, Windows, RTX 5060 8 GB. The installed engine and model
files were reused read-only. All native changes, tools and outputs live in the
ignored `external/audio-stream-lab` directory. The adopted workspace change is
now built separately from clean v0.8.1 source for desktop version 0.2.3. The
20-second chunk experiment remains outside the installer.

## Why the memory change helps

In audio.cpp v0.8.1, `PrefixStateGraph::run_device` computes the prefix KV state,
then copies its keys and values into a separately owned `state_buffer`.
However, the graph allocator, compute tensors and causal-mask host storage
remain alive during acoustic synthesis. They are no longer needed to consume
the copied state.

The `workspace` profile synchronizes the backend and frees that completed
compute workspace while retaining `state_ctx`, `state_buffer` and the returned
KV tensors. Graph reuse now requires a live graph; a later prefill rebuilds it.
Precision, weights, full attention context, token limits and ODE steps stay the
same. This is an allocation-lifetime change, not reduced model quality or
splitting the lyrics.

On the full song, a live sample after this release measured approximately
6.36 GB process working set and 7.83 GB private commit, compared with 9.21 GB
and 12.44 GB respectively during the original acoustic stage. These are
point samples, not peak measurements. Device memory remained close to full.

## Short fixture: equivalence check

One minute of generated audio, short English lyrics, seed 1234, Q8, COT full,
ABC cap 512, fixed 1500 semantic frames, 8 steps, guidance 1, four CPU threads.
All runs include compact metadata arenas already described in
[the performance notes](yue2-performance.md).

| Profile | Wall s | First published audio s | Peak commit MiB | Peak working set MiB | Peak total GPU MiB |
|---|---:|---:|---:|---:|---:|
| Installed CLI | 26.816 | — | 6728.6 | 4865.5 | 6366 |
| Isolated baseline | 26.236 | — | 6487.3 | 4858.7 | 6488 |
| Original VAE streaming | 25.982 | 23.774 | 6487.4 | 4857.2 | 6450 |
| Workspace release + streaming | 27.116 | 24.503 | 6125.8 | 4856.7 | 5772 |
| 20 s acoustic chunks, before workspace release | 25.665 | 20.142 | 7537.6 | 5090.7 | 6655 |

The first four profiles produced byte-identical WAVs:
`ccb44f598c1b58fc03a4cdeaf28d55d1cd16b65fe4a17caca733c2c236e9d417`.
Their PCM SHA-256 is
`81cdf1c2ccabf1b68cd50e94c02745720e2bf709ad4a7d97da2cc0a48828c7b3`.

The chunked version changed PCM and increased peak memory on this short
fixture. It is not a universal speed or memory improvement.

## User's full Japanese song

The complete provided lyrics and style were preserved, with seed 831001,
Q8, COT full, 8 steps and the normal model limits. Suno's approximately four
minute result is a reference, not a duration constraint imposed on YuE2.
YuE2 produced 3666 ABC tokens and 8084 semantic frames without truncation,
corresponding to **323.359 seconds (5:23)** of audio.

| Profile | Outcome | Wall s | First audio s | Peak commit MiB | Peak working set MiB | Peak total GPU MiB |
|---|---|---:|---:|---:|---:|---:|
| Original acoustic processing + streaming | Manually stopped before any audio | 609.582 | — | 11874.3 | 8785.7 | 7672 |
| Workspace release + streaming | Completed 5:23 audio | 251.913 | 240.870 | 11178.0 | 8316.8 | 7612 |
| 20 s acoustic chunks + workspace release | Completed 5:23 audio | 272.958 | 172.456 | 9469.2 | 6252.6 | 7636 |

The original run was still consuming GPU resources when stopped. Its
completion time is unknown and exceeds 609.582 seconds; this does not prove
a deadlock. The modified run completed in 4:12. Peak memory still includes
the expensive prefix construction, so freeing its workspace primarily helps
the subsequent acoustic stage rather than eliminating that construction peak.

The full-song original never completed, so there is no full-song original PCM
hash for a byte-for-byte comparison. Equivalence was demonstrated on the
short fixture, not every possible song. These are single runs with desktop
applications open; GPU memory is total sampled device usage, not a
process-exclusive measurement, and shared GPU memory is not separately sampled.

Chunking began publishing audio 68.414 seconds earlier, but completed 21.045
seconds later than workspace release alone. It reduced peak process working
set by 2064.2 MiB and peak commit by 1708.8 MiB relative to that run. Total
peak GPU usage remained similar because earlier stages still need memory.
The chunked full-song PCM differs, as expected from changed acoustic context.

`summarize.py` verified every streamed result by concatenating PCM chunks in
frame order and comparing their hash with the corresponding final WAV. Both
full-song streams cover all frames without gaps or duplicates. This checks
transport/assembly, not whether musical transitions sound natural.

Full WAVs and VBR quality-2 MP3 copies are saved locally. Workspace MP3 is
7,232,396 bytes; chunked MP3 is 7,473,788 bytes. MP3 is lossy; PCM comparisons
above use the original WAVs. The page offers both MP3s for listening/download.

The local browser player also completed a 60-second workspace run in 23.8 s,
receiving the first piece after 22.7 s. No browser console errors were reported.
A subsequent active generation was cancelled through the page: its native
process exited and sampled GPU use returned to approximately 1060 MiB / 2%.
A fresh generation immediately after cancellation completed successfully in
24.6 s (first browser audio 24.1 s), without a model-busy error. Playback was
stopped afterward and no native engine process was left running.

## Listening and limitations

Run `experiments/yue2-streaming/Start-Lab.cmd`. The page provides the saved
audio and lets you start a new isolated run. New chunked runs also release the
completed prefill workspace. Playback schedules published WAV pieces in order.
Stopping kills only the lab's owned generation process tree and stops queued
playback. It does not resume a partially generated song.

Original VAE streaming keeps the generated samples but publishes them near
the end of processing. Experimental acoustic chunks publish earlier, but
change the context used to generate each section. Full ABC and semantic
generation still precede both approaches. This is not immediate Suno-style
streaming, and no listening-quality parity is claimed for acoustic chunking.

For build details and reproducible commands, see
[the experiment README](../experiments/yue2-streaming/README.md).

## Adopted desktop build (0.2.3)

The shipped Windows server is built from the clean pinned v0.8.1 source with
only `external/patches/yue-workspace-release.patch`, with YuE2, SheetSage2,
MuScriptor and native model management enabled. The original server executable
remains available under its original name. The new executable is copied beside
it as `remiqora_yue2_server.exe` and selected by the desktop backend.

The production CLI produced the same 60-second WAV SHA-256 as the installed
baseline: `ccb44f598c1b58fc03a4cdeaf28d55d1cd16b65fe4a17caca733c2c236e9d417`.
It completed in 25.917 s; peak process commit was 6121.0 MiB and sampled
total GPU usage peaked at 5706 MiB. The production server passed `/health`
and `/v1/models` checks with the app's CUDA and UI-management arguments.

The 0.2.3 NSIS installer is 115,843,321 bytes. Its unpacked resources contain
the backend, frontend, patches and the new 11,183,616-byte server; the bundled
server hash matches the locally tested binary. A read-only setup-plan check
against the existing `%LOCALAPPDATA%/Remiqora` state marked only
`engine-workspace` pending: 11,183,616 bytes, `network: false`. Installed
models and the original engine were marked done. The installer itself was not
run during this check; the user can now install and test generation in the app.
