# YuE2 memory and cancellation

The desktop uses audio.cpp v0.8.1, Q8 main weights and the F16 VAE by default.
No model download is required for these changes.

## Host memory reservations

The pinned engine creates several `ggml_init` contexts with `no_alloc=true`.
Their arenas hold graph and tensor metadata; backend allocators separately
allocate the weights, KV cache and activations. The original arena defaults
reserve multiple GiB of Windows commit even when most of that memory is never
touched. Reducing these arenas changes their capacity, not tensor precision,
sampling, attention, or the number of inference steps.

The app now passes these session options:

| Arena | Old MiB | New MiB |
|---|---:|---:|
| Main weight metadata | 6144 | 64 |
| VAE weight metadata | 1536 | 64 |
| AR prefill graph | 4096 | 256 |
| AR decode graph | 1536 | 128 |
| NAR graph | 6144 | 256 |
| VAE graph | 1536 | 128 |

The graph capacities retain headroom above the pinned engine's node caps.
Upstream's [memory instrumentation change](https://github.com/0xShug0/audio.cpp/pull/688)
describes the distinction between reserved host arenas and backend tensors.
The [unmerged arena-sizing proposal](https://github.com/0xShug0/audio.cpp/pull/657)
also documents the AR prefix and NAR graph caps. This app uses the existing
session options; it does not incorporate that unmerged native patch.

Measured on 2026-09-29, Windows, RTX 5060 8 GB, installed v0.8.1 CLI, Q8 main,
F16 VAE, seed 1234, 8 inference steps, guidance 1.0, four CPU threads:

| Fixture | Profile | Peak commit MiB | Peak working set MiB | Process wall time |
|---|---|---:|---:|---:|
| 200 semantic frames, COT off, about 8 s audio | Original | 27853.1 | 4837.9 | 7.244 s |
| Same request | Compact arenas | 5923.4 | 4837.9 | 6.940 s |
| 1000 semantic frames, COT full, about 40 s audio | Original | 28451.3 | 4847.4 | 19.593 s |
| Same request | Compact arenas | 6519.9 | 4847.5 | 19.709 s |

Each pair produced byte-identical WAV files. SHA-256:

- 8 s pair: `52630034cda74bdaa85592f7d704e7db1196f0e1214632a7d9e39790cca8f116`
- 40 s pair: `89f6e4da153bc0240b53eb43a0907f9045edb1558df785292a22038ebeb85b09`

These are single runs, not a speed benchmark. The confirmed reduction is about
21.4 GiB of peak Windows commit. Physical working set and GPU requirements are
not reduced by the same amount. Longer inputs still increase KV-cache and
activation memory, and may spill beyond dedicated VRAM. The fixtures do not
prove that every song length fits an 8 GB GPU.

A longer compact-arena smoke run also completed: 4500 semantic frames,
COT full, ABC limited to 512 tokens, the same short lyric fixture and settings
above. It produced 179.999 s of stereo 48 kHz audio in 84.734 s including
process startup (native inference reported 80.496 s), with peak commit
8182.0 MiB and peak working set 4982.1 MiB. This run checks longer audio against
the reduced arenas; it is not a comparison against the original profile or a
prediction for long lyrics and unrestricted ABC planning.

## Model residency and audio buffers

The native server keeps at most one model resident. Loading SheetSage or
MuScriptor evicts idle weights from the previous task, instead of keeping
multiple large models on the GPU. Loading another model can consequently take
longer, but its precision is unchanged. Generation and melody extraction are
mutually exclusive in the form.

The frontend checks actual server session options before reusing a loaded model.
It decodes base64 audio in slices, releases the base64 result before upload,
and revokes temporary Blob URLs once a track is saved or removed.

## Cancellation and progress

The native YuE2 task API has no cooperative cancellation endpoint. Aborting
`fetch` alone leaves inference running. Cancel now aborts the HTTP request,
restarts only the YuE2 process, waits for it to stop and become ready again,
then marks the track cancelled. A queued track cannot start during that reset.
The form remains mounted across the restart so lyrics and options survive.
Restart reloads weights from disk on the next generation; it does not download
them. A busy-error card also provides a reset action for old orphaned requests.

Desktop 0.2.4 adds an optional native progress snapshot written under the data
directory. YuE2 reports melody planning and music token counts, then actual
acoustic solver steps and waveform decode tiles. Token limits are upper bounds,
so the UI gives an exact percentage only for the acoustic and decode stages.
The estimated time range comes from recent tracks with similar lyrics, COT and
precision and the same acoustic step count. It remains an estimate because
token generation can stop before its cap. Completion adds an
unread badge; a header setting enables desktop notifications. ACE-Step uses its
reported progress and stage with an approximate remaining time.

The sidecar lists 32 acoustic steps, but the current engine request parser
uses 8 whenever `num_inference_steps` is absent. Both the earlier 4:12
experiment and the user's 5:10 song generated in 17:10 used 8 steps; they
cannot be treated as a before/after speed comparison. Desktop 0.2.5 shows
8 as the effective default and sends the selected step count explicitly.
Song length comes from semantic codec tokens until the model emits its music
end token or reaches `semantic_max_tokens` (9000 by default). At 25 latent
frames per second, that cap is about six minutes; it is an upper bound, not a
requested duration. Acoustic step count changes synthesis work and potentially
sound, not the number of audio frames. Installed tracks 10 and 11 used the
same lyrics and seed with 8 and 32 steps respectively; both produced 293.6 s.
The old Electron document
cache also caused one installed 0.2.3 session to send empty model session
options. The backend now fills in the compact metadata arenas at model load even
if an old cached renderer sends no options, and the desktop version keys its
document URL to avoid reusing an older frontend bundle.

YuE2 v0.8.1 supports offline generation. Listening while a song is still being
generated needs native incremental audio output, plus cancellation/checkpoints
inside the AR, NAR and VAE loops. It cannot be added by animating the player or
splitting lyrics without changing the musical context. See the
[pinned model implementation](https://github.com/0xShug0/audio.cpp/blob/v0.8.1/src/models/yue2/session.cpp).

An isolated native experiment tested incremental VAE output, acoustic
chunking and early release of completed prefill scratch. See the
[measured streaming experiment](yue2-streaming-experiment.md). Desktop 0.2.3
includes the prefill workspace release on Windows. Acoustic chunking remains
an isolated experiment because the user heard weaker audio at each boundary.

## Targeted checks

From `frontend`: `node --test test/yue2.test.cjs`, then `npm run build`.
From `backend`: `python -m unittest discover -s tests -p test_yue_reset.py -v`.
The Windows native reset was also exercised with the installed server on an
isolated port: the old process exited before its replacement became ready.
