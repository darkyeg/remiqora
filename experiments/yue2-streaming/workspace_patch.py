"""Release prefill scratch after copying the KV state, retaining its owning buffer."""
from pathlib import Path


def patch(content, *, always=False):
    release_after_copy = ('''
            release_compute_workspace();''' if always else '''
            const char * release = std::getenv("REMIQORA_LAB_RELEASE_PREFILL");
            if (release != nullptr && std::string(release) == "1") {
                release_compute_workspace();
            }''')
    edits = [
        ('''        ~PrefixStateGraph() {
            core::release_backend_graph_resources(owner->execution.backend(), graph);
            if (gallocr != nullptr) {
                ggml_gallocr_free(gallocr);
            }
            if (state_buffer != nullptr) {''', '''        void release_compute_workspace() {
            ggml_backend_synchronize(owner->execution.backend());
            if (graph != nullptr) {
                core::release_backend_graph_resources(owner->execution.backend(), graph);
            }
            if (gallocr != nullptr) ggml_gallocr_free(gallocr);
            gallocr = nullptr;
            graph = nullptr;
            input = positions = attention_mask = nullptr;
            keys.clear();
            values.clear();
            ctx.reset();
            std::vector<int32_t>().swap(position_values);
            std::vector<ggml_fp16_t>().swap(mask_values);
        }

        ~PrefixStateGraph() {
            release_compute_workspace();
            if (state_buffer != nullptr) {'''),
        ('''        bool matches(int64_t s) const noexcept {
            return steps == s;
        }''', '''        bool matches(int64_t s) const noexcept {
            return steps == s && graph != nullptr;
        }'''),
        ('''            out.keys = key_values;
            out.values = value_values;
            return out;''', '''            out.keys = key_values;
            out.values = value_values;
''' + release_after_copy + '''
            return out;'''),
    ]
    for before, after in edits:
        if content.count(before) != 1:
            raise RuntimeError("Unexpected prefix workspace source")
        content = content.replace(before, after)
    return content


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[2] / "external/audio-stream-lab/source/src/models/yue2/ar_runtime.cpp"
    target.write_text(patch(target.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
