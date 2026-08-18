import json
import tempfile
import unittest
from pathlib import Path

from src import experiment_analysis as ANALYZER


class AnalyzeExperimentTest(unittest.TestCase):
    def test_common_prefix_length(self):
        self.assertEqual(ANALYZER.common_prefix_length([1, 2, 3], [1, 2, 4]), 2)
        self.assertEqual(ANALYZER.common_prefix_length([1, 2], [1, 2, 3]), 2)
        self.assertEqual(ANALYZER.common_prefix_length([], [1]), 0)

    def test_cache_retention_by_action_is_token_weighted_and_importable(self):
        transitions = [
            {
                "action_name": "delete",
                "next_call_observed": True,
                "retained_ratio": 0.5,
                "previous_token_count": 100,
                "common_prefix_token_count": 50,
                "invalidated_previous_token_count": 50,
            },
            {
                "action_name": "delete",
                "next_call_observed": True,
                "retained_ratio": 0.8,
                "previous_token_count": 300,
                "common_prefix_token_count": 240,
                "invalidated_previous_token_count": 60,
            },
            {
                "action_name": "search",
                "next_call_observed": True,
                "retained_ratio": 1.0,
                "previous_token_count": 100,
                "common_prefix_token_count": 100,
                "invalidated_previous_token_count": 0,
            },
            {
                "action_name": "terminal",
                "next_call_observed": False,
                "retained_ratio": 1.0,
                "previous_token_count": 100,
                "common_prefix_token_count": 100,
                "invalidated_previous_token_count": 0,
            },
        ]

        summary = ANALYZER.cache_retention_by_action(
            transitions, action_field="action_name"
        )

        self.assertEqual([row["action"] for row in summary], ["delete", "search"])
        self.assertEqual(summary[0]["transition_count"], 2)
        self.assertEqual(summary[0]["weighted_retention_rate"], 290 / 400)
        self.assertEqual(summary[0]["per_transition_retention"]["mean"], 0.65)
        self.assertEqual(summary[0]["invalidated_previous_token_count"], 110)

    def test_tool_colors_are_generic_and_accept_overrides(self):
        colors = ANALYZER.assign_tool_colors(
            ("customSearch", "customDelete"), {"customDelete": "#123456"}
        )

        self.assertEqual(colors["customDelete"], "#123456")
        self.assertRegex(colors["customSearch"], r"^#[0-9a-f]{6}$")

    def test_extract_option_requires_an_explicit_leading_answer(self):
        self.assertEqual(ANALYZER.extract_option("A. First option"), "A")
        self.assertEqual(ANALYZER.extract_option("Answer: (d) because..."), "D")
        self.assertIsNone(ANALYZER.extract_option("Based on the evidence, choose B"))
        self.assertIsNone(ANALYZER.extract_option("No final answer"))

    def test_extract_explicit_option_accepts_labelled_trailing_answer(self):
        self.assertEqual(
            ANALYZER.extract_explicit_option(
                "Evidence and reasoning first. Therefore, the correct answer is: **D. Choice**"
            ),
            "D",
        )
        self.assertEqual(ANALYZER.extract_explicit_option("Final answer: \\boxed{B}"), "B")
        self.assertIsNone(ANALYZER.extract_explicit_option("Option A is wrong; option B may fit"))

    def test_context_error_token_breakdown(self):
        parsed = ANALYZER.request_token_breakdown(
            "requested 272410 tokens (270362 in the messages, 2048 in the completion)"
        )
        self.assertEqual(parsed, {
            "requested_tokens": 272410,
            "message_tokens": 270362,
            "completion_tokens": 2048,
        })

    def test_rates_separate_raw_completed_and_valid_terminal_scores(self):
        rows = [
            {
                "status": "completed",
                "score": 1.0,
                "correct": True,
                "valid_completed_score": 1.0,
                "parsed_answer_correct": True,
            },
            {
                "status": "completed",
                "score": 0.0,
                "correct": False,
                "valid_completed_score": None,
                "parsed_answer_correct": None,
            },
            {
                "status": "failed",
                "score": 1.0,
                "correct": True,
                "valid_completed_score": None,
                "parsed_answer_correct": None,
            },
        ]

        summary = ANALYZER.rate_summary(rows, denominator=3)

        self.assertEqual(summary["raw_score_count"], 3)
        self.assertEqual(summary["completed_count"], 2)
        self.assertEqual(summary["binary_accuracy_completed"], 0.5)
        self.assertEqual(summary["parsed_completed_count"], 1)
        self.assertEqual(summary["parsed_completed_accuracy"], 1.0)
        self.assertEqual(summary["parsed_end_to_end_correct_rate"], 1 / 3)
        self.assertEqual(summary["valid_terminal_count"], 1)
        self.assertEqual(summary["valid_terminal_coverage"], 1 / 3)
        self.assertEqual(summary["valid_terminal_accuracy"], 1.0)
        self.assertEqual(summary["strict_end_to_end_correct_rate"], 1 / 3)
        self.assertEqual(summary["end_to_end_correct_rate"], 1 / 3)

    def test_observation_error_field_is_a_tool_failure(self):
        self.assertFalse(ANALYZER.observation_succeeded({"error": "not found"}))
        self.assertFalse(ANALYZER.observation_succeeded({"status": "failed"}))
        self.assertFalse(ANALYZER.observation_succeeded({}, "trajectory failed"))
        self.assertTrue(ANALYZER.observation_succeeded({"status": "success"}))

    def test_context_selection_prioritizes_failures_and_long_runs(self):
        rows = [
            {"sample_id": "failed", "status": "failed", "correct": False,
             "max_prompt_tokens": 120000, "api_call_count": 80,
             "rejected_message_tokens": 140000},
            {"sample_id": "correct-long", "status": "completed", "correct": True,
             "max_prompt_tokens": 30000, "api_call_count": 50,
             "rejected_message_tokens": None},
            {"sample_id": "correct-short", "status": "completed", "correct": True,
             "max_prompt_tokens": 10000, "api_call_count": 10,
             "rejected_message_tokens": None},
            {"sample_id": "wrong-long", "status": "completed", "correct": False,
             "max_prompt_tokens": 40000, "api_call_count": 60,
             "rejected_message_tokens": None},
            {"sample_id": "wrong-short", "status": "completed", "correct": False,
             "max_prompt_tokens": 9000, "api_call_count": 8,
             "rejected_message_tokens": None},
        ]

        selected = ANALYZER.select_context_samples(rows, limit=3)

        self.assertEqual(
            [item["sample_id"] for item in selected],
            ["failed", "correct-long", "wrong-long"],
        )

    def test_context_svg_colors_segments_by_starting_tool(self):
        selected = [{"sample_id": "1", "reason": "example"}]
        rows = [{"sample_id": "1", "status": "completed", "score": 1.0,
                 "api_call_count": 3, "max_prompt_tokens": 5000}]
        records = [
            {"sample_id": "1", "trajectory_index": 0, "prompt_tokens": 1000,
             "tool": "readChunk"},
            {"sample_id": "1", "trajectory_index": 1, "prompt_tokens": 5000,
             "tool": "deleteContext"},
            {"sample_id": "1", "trajectory_index": 2, "prompt_tokens": 1500,
             "tool": "finish"},
        ]

        colors = ANALYZER.assign_tool_colors(
            ("readChunk", "deleteContext", "finish")
        )
        svg = ANALYZER.render_context_evolution_svg(
            selected, rows, records, colors
        )

        self.assertIn(colors["readChunk"], svg)
        self.assertIn(colors["deleteContext"], svg)
        self.assertIn("Context evolution in selected trajectories", svg)
        self.assertIn("delta +4,000", svg)
        self.assertIn("delta -3,500", svg)

    def test_public_analysis_api_separates_reads_from_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            experiment = Path(temporary) / "experiment"
            sample = experiment / "samples" / "sample-1"
            sample.mkdir(parents=True)
            (experiment / "report.json").write_text(
                json.dumps({"metrics": {"token_usage": {"prompt_tokens": 10}}})
            )
            (sample / "result.json").write_text(json.dumps({
                "sample_id": "sample-1",
                "status": "completed",
                "score": 1.0,
                "correct_answer": "A",
                "final_answer": "A. answer",
                "metrics": {"api_call_count": 1, "tool_call_count": 1},
            }))
            (sample / "trajectory_0.json").write_text(json.dumps({
                "trajectory_index": 0,
                "status": "completed",
                "response": {"usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 2,
                    "total_tokens": 12,
                }},
                "action": {"name": "finish", "arguments": {"answer": "A"}},
                "observation": {"final_answer": "A. answer"},
                "state_after": {},
            }))

            analysis = ANALYZER.analyze_experiment(experiment)

            self.assertEqual(len(analysis.samples), 1)
            self.assertEqual(analysis.samples[0]["valid_completed_score"], 1.0)
            self.assertFalse((experiment / "analysis").exists())
            output = ANALYZER.write_analysis(analysis)
            self.assertEqual(output, (experiment / "analysis").resolve())
            self.assertTrue((output / "report.md").is_file())
            self.assertTrue((output / "context_evolution.svg").is_file())
            self.assertTrue((output / "cache_transitions.csv").is_file())

            strict = ANALYZER.analyze_experiment(
                experiment,
                profile=ANALYZER.AnalysisProfile(
                    terminal_tool="finish",
                    answer_parser=ANALYZER.extract_option,
                    parsed_answer_label="explicit leading A-D answer",
                ),
            )
            self.assertEqual(strict.samples[0]["parsed_answer"], "A")
            self.assertEqual(strict.samples[0]["terminal_mode"], "finish")
            self.assertEqual(strict.samples[0]["valid_completed_score"], 1.0)

    def test_analysis_reports_sample_progress(self):
        with tempfile.TemporaryDirectory() as temporary:
            experiment = Path(temporary) / "experiment"
            for sample_id in ("a", "b"):
                sample = experiment / "samples" / sample_id
                sample.mkdir(parents=True)
                (sample / "result.json").write_text(json.dumps({
                    "sample_id": sample_id,
                    "status": "completed",
                    "score": 0.0,
                    "metrics": {},
                }))
            progress = []

            ANALYZER.analyze_experiment(
                experiment,
                progress_callback=lambda completed, total, sample_id: progress.append(
                    (completed, total, sample_id)
                ),
            )

            self.assertEqual(progress, [(1, 2, "a"), (2, 2, "b")])

    def test_cache_retention_uses_only_observed_next_calls(self):
        def tokenize(messages, tools, add_generation_prompt):
            role_tokens = {"system": 10, "user": 20, "assistant": 30, "tool": 40}
            tokens = [role_tokens[message["role"]] for message in messages]
            if add_generation_prompt:
                tokens.append(30)
            return tokens

        with tempfile.TemporaryDirectory() as temporary:
            experiment = Path(temporary) / "experiment"
            sample = experiment / "samples" / "sample-1"
            sample.mkdir(parents=True)
            (sample / "result.json").write_text(json.dumps({
                "sample_id": "sample-1", "status": "completed", "score": 1.0,
                "metrics": {},
            }))
            initial = {"messages": [
                {"role": "system", "content": "s"},
                {"role": "user", "content": "u"},
            ], "tools": []}
            after_first = {"messages": [
                *initial["messages"],
                {"role": "assistant", "content": "a"},
                {"role": "tool", "content": "o"},
            ], "tools": []}
            after_second = {"messages": [
                *after_first["messages"],
                {"role": "assistant", "content": "done"},
            ], "tools": []}
            for index, before, after in (
                (0, initial, after_first), (1, after_first, after_second)
            ):
                (sample / f"trajectory_{index}.json").write_text(json.dumps({
                    "trajectory_index": index,
                    "status": "completed",
                    "initial_context": before,
                    "resulting_context": after,
                    "response": {
                        "choices": [{"message": after["messages"][len(before["messages"]) ]}],
                        "usage": {"prompt_tokens": 3, "completion_tokens": 1,
                                  "total_tokens": 4},
                    },
                }))

            analysis = ANALYZER.analyze_experiment(
                experiment,
                context_tokenizer=tokenize,
                context_tokenizer_name="test-tokenizer",
            )

            cache = analysis.summary["behavior"]["theoretical_cache_retention"]
            self.assertEqual(len(analysis.cache_transitions), 2)
            self.assertEqual(cache["observed_transition_count"], 1)
            self.assertEqual(cache["terminal_snapshot_count"], 1)
            self.assertEqual(cache["weighted_retention_rate"], 1.0)
            self.assertEqual(cache["by_action"][0]["action"], "no_tool")
            self.assertEqual(cache["by_action"][0]["weighted_retention_rate"], 1.0)
            report = ANALYZER.markdown_report(analysis.summary)
            self.assertIn("Retention by preceding action", report)
            self.assertIn("| no_tool | 1 | 100.0% |", report)
            self.assertEqual(analysis.cache_transitions[0]["common_prefix_token_count"], 3)
            self.assertFalse(analysis.cache_transitions[1]["next_call_observed"])

    def test_cache_retention_excludes_trajectory_index_gaps(self):
        def tokenize(messages, tools, add_generation_prompt):
            return list(range(len(messages) + int(add_generation_prompt)))

        with tempfile.TemporaryDirectory() as temporary:
            experiment = Path(temporary) / "experiment"
            sample = experiment / "samples" / "sample-1"
            sample.mkdir(parents=True)
            before = {"messages": [{"role": "user", "content": "u"}]}
            after = {"messages": [
                *before["messages"], {"role": "assistant", "content": "a"}
            ]}
            for index in (0, 2):
                (sample / f"trajectory_{index}.json").write_text(json.dumps({
                    "trajectory_index": index,
                    "initial_context": before,
                    "resulting_context": after,
                    "response": {"choices": [{"message": after["messages"][-1]}]},
                }))

            analysis = ANALYZER.analyze_experiment(
                experiment, context_tokenizer=tokenize
            )

            cache = analysis.summary["behavior"]["theoretical_cache_retention"]
            self.assertEqual(cache["observed_transition_count"], 0)
            self.assertFalse(analysis.cache_transitions[0]["next_call_observed"])


if __name__ == "__main__":
    unittest.main()
