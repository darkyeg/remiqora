import json
import unittest

from app.api.routes_proxy import _compact_yue2_load


class YueLoadOptionsTests(unittest.TestCase):
    def test_cached_ui_gets_compact_arenas(self):
        old_request = {"id": "yue2", "family": "yue2", "session_options": {}}
        options = json.loads(_compact_yue2_load(json.dumps(old_request).encode()))["session_options"]
        self.assertEqual(options["yue2.model_weight_context_mb"], "64")
        self.assertEqual(options["yue2.nar_graph_arena_mb"], "256")

    def test_precision_and_explicit_options_survive(self):
        request = {"id": "yue2", "session_options": {
            "yue2.model_gguf": "yue2-3b-q4_0.gguf", "yue2.nar_graph_arena_mb": "512",
        }}
        options = json.loads(_compact_yue2_load(json.dumps(request).encode()))["session_options"]
        self.assertEqual(options["yue2.model_gguf"], "yue2-3b-q4_0.gguf")
        self.assertEqual(options["yue2.nar_graph_arena_mb"], "512")

    def test_other_models_are_unchanged(self):
        request = b'{"id":"sheetsage2","session_options":{}}'
        self.assertEqual(_compact_yue2_load(request), request)


if __name__ == "__main__":
    unittest.main()
