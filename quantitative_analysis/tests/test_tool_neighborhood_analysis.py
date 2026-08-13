import csv
import json
import tempfile
import unittest
from pathlib import Path

from src import tool_neighborhood_analysis as ANALYZER


class ToolNeighborhoodAnalysisTest(unittest.TestCase):
    def test_neighbors_are_exact_and_within_sample(self):
        rows = [
            {"sample_id": "a", "trajectory_index": 0, "tool": "search"},
            {"sample_id": "a", "trajectory_index": 1, "tool": "note"},
            {"sample_id": "a", "trajectory_index": 2, "tool": "deleteContext"},
            {"sample_id": "a", "trajectory_index": 3, "tool": "read"},
            {"sample_id": "b", "trajectory_index": 0, "tool": "deleteContext"},
            {"sample_id": "b", "trajectory_index": 2, "tool": "deleteContext"},
        ]

        analysis = ANALYZER.analyze_tool_neighborhoods(rows)

        self.assertEqual(analysis.summary["target_call_count"], 3)
        first = analysis.events[0]
        self.assertEqual(first["previous_pair"], "search -> note")
        self.assertEqual(first["next_tool_1"], "read")
        boundary = analysis.events[1]
        self.assertEqual(boundary["previous_tool_1"], "missing_t-1")
        self.assertEqual(boundary["previous_tool_2"], "missing_t-2")
        gap = analysis.events[2]
        self.assertEqual(gap["previous_tool_1"], "missing_t-1")
        self.assertEqual(gap["previous_tool_2"], "deleteContext")
        self.assertEqual(gap["intervening_calls_since_previous_deletion"], 1)
        self.assertEqual(analysis.summary["target_run_length_distribution"]["max"], 1)
        self.assertEqual(
            analysis.summary["target_run_predecessor"][0]["label"], "missing_t-1"
        )

    def test_loader_uses_only_required_columns_and_rejects_duplicates(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "tool_calls.csv"
            path.write_text(
                "sample_id,trajectory_index,tool,large_unused_field\n"
                "x,1,deleteContext,ignored\n",
                encoding="utf-8",
            )
            self.assertEqual(ANALYZER.load_tool_calls(path), [{
                "sample_id": "x", "trajectory_index": 1, "tool": "deleteContext"
            }])
            path.write_text(
                "sample_id,trajectory_index,tool\n"
                "x,1,deleteContext\nx,1,note\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate"):
                ANALYZER.load_tool_calls(path)

    def test_outputs_include_events_report_and_pies(self):
        rows = [
            {"sample_id": "a", "trajectory_index": 0, "tool": "note"},
            {"sample_id": "a", "trajectory_index": 1, "tool": "deleteContext"},
        ]
        analysis = ANALYZER.analyze_tool_neighborhoods(rows)
        with tempfile.TemporaryDirectory() as temporary:
            output = ANALYZER.write_tool_neighborhood_analysis(analysis, temporary)

            self.assertTrue((output / "events.csv").is_file())
            self.assertIn("<svg", (output / "previous_tool_1.svg").read_text())
            self.assertIn("note", (output / "previous_tool_1.svg").read_text())
            summary = json.loads((output / "summary.json").read_text())
            self.assertEqual(summary["previous_tool_1"][0]["label"], "note")


if __name__ == "__main__":
    unittest.main()
