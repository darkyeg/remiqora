"""Apply the optional lab hooks to the pinned checkout, never the installed engine."""
from pathlib import Path
import shutil
from workspace_patch import patch as patch_workspace

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1] / "external/audio-stream-lab/source"


def main():
    paths = ["src/models/yue2/pipeline.cpp", "src/models/yue2/nar_runtime.cpp", "include/engine/models/yue2/nar_runtime.h", "src/models/yue2/ar_runtime.cpp"]
    contents = {name: (SOURCE / name).read_text(encoding="utf-8") for name in paths}
    if '#include "remiqora_lab.h"' in contents[paths[0]]:
        raise RuntimeError("Lab patch is already applied")

    def replace(name, before, after, count=1):
        if contents[name].count(before) != count:
            raise RuntimeError(f"Unexpected pinned source in {name}: {before[:75]!r}")
        contents[name] = contents[name].replace(before, after)

    pipeline, nar, header, ar = paths
    for name in (pipeline, nar, ar):
        contents[name] = '#include "remiqora_lab.h"\n' + contents[name]
    replace(ar, '            emitted.push_back(token);',
            '            emitted.push_back(token);\n            lab_report_tokens(compact_abc, static_cast<int64_t>(emitted.size()), window.max_tokens);', count=2)

    replace(header, '        int64_t context);',
            '        int64_t context,\n        const std::function<void(const std::vector<float> &, int64_t)> & on_chunk = {});')
    replace(nar, '        int64_t context) {\n        const auto total_start',
            '        int64_t context,\n        const std::function<void(const std::vector<float> &, int64_t)> & on_chunk) {\n        const auto total_start')
    replace(nar, '    int64_t context) {\n    return impl_->synthesize(prefix, codec, prefill_state, noise, seed, ode_steps, context);',
            '    int64_t context,\n    const std::function<void(const std::vector<float> &, int64_t)> & on_chunk) {\n    return impl_->synthesize(prefix, codec, prefill_state, noise, seed, ode_steps, context, on_chunk);')
    replace(nar, '    const int64_t chunk = std::min((context - prefix_tokens - 3) / 2, context);',
            '    int64_t chunk = std::min((context - prefix_tokens - 3) / 2, context);\n    if (const auto cap = lab_chunk_frames(); cap > 0) chunk = std::min(chunk, cap);')
    replace(nar, '            out.insert(out.end(), chunk.begin(), chunk.end());',
            '            out.insert(out.end(), chunk.begin(), chunk.end());\n            if (on_chunk) {\n                graph.reset();\n                on_chunk(out, end);\n            }')

    replace(pipeline, '        uint64_t seed) {\n        const auto codec',
            '        uint64_t seed,\n        const std::function<void(const std::vector<float> &, int64_t)> & on_chunk = {}) {\n        const auto codec')
    replace(pipeline, '            generation.context);', '            generation.context, on_chunk);')
    replace(pipeline, '    runtime::AudioBuffer decode_audio(const std::vector<float> & latents, int64_t frames) {',
            '    runtime::AudioBuffer decode_audio(const std::vector<float> & latents, int64_t frames, LabAudioSink * sink = nullptr) {')
    replace(pipeline, '            return audio;\n        }\n\n        const int64_t total_output_frames',
            '            if (sink) sink->publish(audio.samples, audio.sample_rate, audio.channels, 0);\n            return audio;\n        }\n\n        const int64_t total_output_frames')
    replace(pipeline, '            ++tiles;', '''            if (sink) {
                const auto first = audio.samples.begin() + out_start * audio.channels;
                sink->publish(std::vector<float>(first, first + copy_frames * audio.channels),
                              audio.sample_rate, audio.channels, out_start);
            }
            ++tiles;''')
    replace(pipeline, '    Yue2RunResult run(const Yue2Request & request) {', '''    void decode_available(const std::vector<float> & latents, int64_t total_frames,
                          int64_t & next_frame, runtime::AudioBuffer & audio, LabAudioSink & sink) {
        const int64_t latent_channels = assets->config.model.latent_dim;
        const int64_t available = static_cast<int64_t>(latents.size()) / latent_channels;
        const int64_t ratio = assets->config.vae.downsampling_ratio;
        const int64_t halo = assets->config.vae.decode_halo_frames;
        const int64_t core = 250; // 10 seconds; keep the original decoder's overlap.
        while (next_frame < total_frames) {
            const int64_t end = std::min(total_frames, next_frame + core);
            const int64_t left = std::max<int64_t>(0, next_frame - halo);
            const int64_t right = std::min(total_frames, end + halo);
            if (right > available) break; // Do not emit audio whose right context is still missing.
            ensure_vae();
            const int64_t tile_frames = right - left;
            std::vector<float> planar(static_cast<size_t>(latent_channels * tile_frames));
            for (int64_t t = 0; t < tile_frames; ++t) {
                for (int64_t c = 0; c < latent_channels; ++c) {
                    planar[c * tile_frames + t] = latents[(left + t) * latent_channels + c];
                }
            }
            auto tile = vae->decode(planar, 1, tile_frames).front();
            const int64_t out_start = next_frame * ratio;
            const int64_t out_end = std::min(end * ratio, total_frames * ratio - 64);
            const int64_t count = out_end - out_start;
            const int64_t crop = (next_frame - left) * ratio;
            if (count <= 0 || crop + count > static_cast<int64_t>(tile.samples.size()) / tile.channels) {
                throw std::runtime_error("Lab VAE tile coverage is incomplete");
            }
            const auto first = tile.samples.begin() + crop * audio.channels;
            std::vector<float> piece(first, first + count * audio.channels);
            std::copy(piece.begin(), piece.end(), audio.samples.begin() + out_start * audio.channels);
            sink.publish(piece, audio.sample_rate, audio.channels, out_start);
            next_frame = end;
        }
        // The next NAR graph can use the decoder's temporary GPU allocations.
        vae.reset();
    }

    Yue2RunResult run(const Yue2Request & request) {
        LabAudioSink sink;''')
    replace(pipeline, '        const auto semantic_start = Clock::now();', '        sink.phase("semantic");\n        const auto semantic_start = Clock::now();')
    replace(pipeline, '''        const auto nar_start = Clock::now();
        auto latents = synthesize_latents(semantic, request.generation, request.nar_noise, request.seed);''', '''        sink.phase("acoustic");
        const bool interleave = lab_chunk_frames() > 0;
        runtime::AudioBuffer audio;
        int64_t next_frame = 0;
        const int64_t total_frames = static_cast<int64_t>(codec_from_semantic_tokens(semantic.tokens).size());
        if (interleave) {
            audio.sample_rate = assets->config.vae.sample_rate;
            audio.channels = static_cast<int>(assets->config.vae.channels);
            if (total_frames <= 0) throw std::runtime_error("No frames for lab synthesis");
            audio.samples.assign(static_cast<size_t>((total_frames * assets->config.vae.downsampling_ratio - 64) * audio.channels), 0.0F);
        }
        std::function<void(const std::vector<float> &, int64_t)> on_chunk;
        if (interleave) {
            on_chunk = [&](const std::vector<float> & ready, int64_t) {
                ar->release_runtime_graphs();
                decode_available(ready, total_frames, next_frame, audio, sink);
            };
        }
        const auto nar_start = Clock::now();
        auto latents = synthesize_latents(semantic, request.generation, request.nar_noise, request.seed, on_chunk);''')
    replace(pipeline, '        auto audio = decode_audio(latents, frames);', '''        if (!interleave) {
            sink.phase("decode");
            audio = decode_audio(latents, frames, &sink);
        } else if (next_frame != total_frames) {
            throw std::runtime_error("Lab stream did not cover the final audio");
        }
        sink.phase("complete");''')
    contents[ar] = patch_workspace(contents[ar])
    for name, content in contents.items():
        (SOURCE / name).write_text(content, encoding="utf-8", newline="\n")
    shutil.copyfile(HERE / "remiqora_lab.h", SOURCE / "src/models/yue2/remiqora_lab.h")
    print("Applied optional streaming hooks to", SOURCE)


if __name__ == "__main__":
    main()
