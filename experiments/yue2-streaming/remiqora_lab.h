#pragma once

#include "engine/framework/audio/wav_writer.h"
#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace engine::models::yue2 {

inline void lab_report_tokens(bool abc, int64_t count, int64_t limit) {
    if (count != 1 && count != limit && count % 50 != 0) return;
    const char * directory = std::getenv("REMIQORA_LAB_STREAM_DIR");
    if (!directory || !*directory) return;
    std::ofstream output(std::filesystem::u8path(directory) / "tokens.jsonl", std::ios::app);
    output << "{\"stage\":\"" << (abc ? "abc" : "semantic") << "\",\"tokens\":" << count
           << ",\"limit\":" << limit << "}\n";
}

inline int64_t lab_chunk_frames() {
    const char * value = std::getenv("REMIQORA_LAB_NAR_CHUNK_FRAMES");
    if (!value || !*value) return 0;
    size_t consumed = 0;
    const int64_t count = std::stoll(value, &consumed);
    if (consumed != std::string(value).size() || count < 200 || count > 4500) {
        throw std::runtime_error("Lab NAR chunk size must be 200..4500 frames");
    }
    return count;
}

class LabAudioSink {
public:
    LabAudioSink() : started(std::chrono::steady_clock::now()) {
        const char * value = std::getenv("REMIQORA_LAB_STREAM_DIR");
        if (!value || !*value) return;
        directory = std::filesystem::u8path(value);
        std::filesystem::create_directories(directory);
        events.open(directory / "events.jsonl", std::ios::out | std::ios::trunc);
        if (!events) throw std::runtime_error("Cannot create lab events file");
        phase("planning");
    }

    bool enabled() const { return events.is_open(); }

    void phase(const char * name) {
        if (!enabled()) return;
        events << "{\"phase\":\"" << name << "\",\"run_ms\":" << elapsed_ms() << "}\n";
        events.flush();
    }

    void publish(const std::vector<float> & samples, int rate, int channels, int64_t start_frame) {
        if (!enabled()) return;
        if (start_frame != published_frames || channels <= 0 || samples.size() % channels) {
            throw std::runtime_error("Non-contiguous lab audio output");
        }
        std::ostringstream filename;
        filename << "chunk_" << std::setw(5) << std::setfill('0') << index++ << ".wav";
        const auto final = directory / filename.str();
        auto temporary = final;
        temporary += ".partial";
        engine::audio::write_pcm16_wav(temporary, rate, channels, samples);
        std::filesystem::rename(temporary, final);
        const int64_t frames = static_cast<int64_t>(samples.size()) / channels;
        events << "{\"file\":\"" << filename.str() << "\",\"start_frame\":" << start_frame
               << ",\"frames\":" << frames << ",\"sample_rate\":" << rate
               << ",\"run_ms\":" << elapsed_ms() << "}\n";
        events.flush();
        published_frames += frames;
    }

private:
    double elapsed_ms() const {
        return std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - started).count();
    }
    std::chrono::steady_clock::time_point started;
    std::filesystem::path directory;
    std::ofstream events;
    int index = 0;
    int64_t published_frames = 0;
};

} // namespace engine::models::yue2
