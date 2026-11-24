"""编审、时间线证据和组卷规则的验收测试。"""
from __future__ import annotations

import unittest
from pathlib import Path

from handover.assessment import assess_learner, correction_impact
from handover.candidates import check_candidate, load_candidate
from handover.planning import plan_for_learner
from handover.repository import Pack
from handover.review import review_question
from handover.variants import is_negation_counterfactual

ROOT = Path(__file__).resolve().parent.parent


class ProjectWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = Pack.load(ROOT / "materials", ROOT / "editorial" / "annotations.json")

    def test_q1_is_unique_and_distractor_is_actual_misread(self):
        result = review_question(self.pack, "Q1")
        self.assertEqual("approved", result["decision"])
        self.assertEqual(1, result["unique_supported_option"])
        self.assertEqual([], result["blockers"])

    def test_q2_cannot_use_later_c2_conclusion_as_0530_evidence(self):
        result = review_question(self.pack, "Q2")
        self.assertEqual("approved", result["decision"])
        self.assertEqual(2, result["unique_supported_option"])
        self.assertEqual("05:30", result["as_of"])
        self.assertTrue(result["evidence"])
        visibility = result["material_visibility"]
        self.assertEqual(["C1"], visibility["visible"])
        self.assertEqual(["C2"], visibility["later"])

    def test_q4_q6_q7_are_approved(self):
        for qid in ("Q4", "Q6", "Q7"):
            with self.subTest(qid=qid):
                result = review_question(self.pack, qid)
                self.assertEqual("approved", result["decision"], result["blockers"])

    def test_q5_is_returned_for_missing_target_not_deleted_option(self):
        result = review_question(self.pack, "Q5")
        self.assertEqual("returned", result["decision"])
        codes = {item["code"] for item in result["blockers"]}
        self.assertIn("non_unique_answer", codes)
        self.assertIn("active_correction_answer_defect", codes)
        non_unique = next(item for item in result["blockers"] if item["code"] == "non_unique_answer")
        self.assertIn("W3", non_unique["supported_by_context"][0][0])
        self.assertIn("不能删选项", non_unique["message"])

    def test_l1_separates_memory_independence_and_answer_defect(self):
        assessment = assess_learner(self.pack, "L1")
        self.assertEqual("independence_failed", assessment["abilities"]["状态边界"]["status"])
        self.assertEqual("evidence_withdrawn", assessment["abilities"]["例外范围"]["status"])

        q3 = next(row for row in assessment["responses"] if row["question"] == "Q3")
        q5 = next(row for row in assessment["responses"] if row["question"] == "Q5")
        self.assertEqual("memory_recognition", q3["independence"])
        self.assertFalse(q3["counts_as_evidence"])
        self.assertEqual("defective", q5["answer_status"])
        self.assertFalse(q5["counts_as_evidence"])

    def test_l3_ambiguous_q5_is_not_used_even_though_key_mismatch(self):
        assessment = assess_learner(self.pack, "L3")
        result = assessment["abilities"]["例外范围"]
        self.assertEqual("answer_defect_needs_retake", result["status"])
        q5 = assessment["responses"][0]
        self.assertEqual(2, q5["selected"])
        self.assertFalse(q5["matched_proposed_key"])
        self.assertEqual("defective", q5["answer_status"])

    def test_l4_keeps_both_abilities_using_q7_and_q6_after_q5_correction(self):
        assessment = assess_learner(self.pack, "L4")
        self.assertEqual("granted", assessment["abilities"]["状态边界"]["status"])
        self.assertEqual("granted", assessment["abilities"]["例外范围"]["status"])

        q5 = next(row for row in assessment["responses"] if row["question"] == "Q5")
        q6 = next(row for row in assessment["responses"] if row["question"] == "Q6")
        self.assertEqual("defective", q5["answer_status"])
        self.assertFalse(q5["counts_as_evidence"])
        self.assertTrue(q6["counts_as_evidence"])
        self.assertEqual(["Q6"], [e["question"] for e in assessment["abilities"]["例外范围"]["evidence"]])

    def test_post_exam_study_does_not_contaminate_l4_original_sitting(self):
        assessment = assess_learner(self.pack, "L4")
        q7 = next(row for row in assessment["responses"] if row["question"] == "Q7")
        self.assertEqual("independent", q7["independence"])
        self.assertTrue(q7["counts_as_evidence"])

    def test_correction_impact_lists_all_three_q5_takers(self):
        impact = correction_impact(self.pack, "R1")
        learners = {item["learner"] for item in impact["affected_responses"]}
        self.assertEqual({"L1", "L3", "L4"}, learners)
        by_learner = {item["learner"]: item for item in impact["affected_responses"]}
        self.assertEqual("granted", by_learner["L4"]["ability_status_after_correction"])
        self.assertEqual("evidence_withdrawn", by_learner["L1"]["ability_status_after_correction"])

    def test_l1_retake_plan_avoids_seen_q1_q3_q5_and_covers_both(self):
        plan = plan_for_learner(self.pack, "L1")
        self.assertTrue(plan["feasible"])
        self.assertEqual(["Q4", "Q7"], plan["selected_questions"])
        self.assertEqual([], plan["missing"])

    def test_l3_makeup_uses_unseen_q6(self):
        plan = plan_for_learner(self.pack, "L3")
        self.assertTrue(plan["feasible"])
        self.assertEqual(["Q6"], plan["selected_questions"])

    def test_l2_can_use_distinct_time_clue_but_strict_family_policy_reports_gap(self):
        plan = plan_for_learner(self.pack, "L2")
        self.assertTrue(plan["feasible"])
        self.assertIn("Q2", plan["selected_questions"])

        strict = plan_for_learner(self.pack, "L2", strict_case_family=True)
        self.assertFalse(strict["feasible"])
        self.assertEqual(["时间边界"], strict["missing"])
        self.assertEqual([], strict["makeup_for_missing"]["时间边界"]["next_session_materials"])
        self.assertTrue(strict["makeup_for_missing"]["时间边界"]["nearest_blocked_materials"])

    def test_exact_seen_case_blocks_even_when_ability_and_clue_differ(self):
        from handover.planning import eligibility_report

        eligibility = eligibility_report(self.pack, "L4")
        self.assertIn("Q2", eligibility["blocked"])
        codes = {
            reason["code"]
            for reason in eligibility["blocked"]["Q2"]["reasons"]
        }
        self.assertIn("seen_case", codes)

    def test_plan_lists_checked_unpromoted_candidate_for_missing_ability(self):
        plan = plan_for_learner(
            self.pack, "L4", candidate_dir=ROOT / "candidates"
        )
        missing = plan["makeup_for_missing"]["状态边界"]
        self.assertEqual("状态边界", plan["missing"][0])
        self.assertTrue(missing["ready_candidates"])
        self.assertIn("state_C8_ready.json", missing["ready_candidates"][0]["path"])

    def test_item_cap_cannot_use_repeated_score_to_cover(self):
        plan = plan_for_learner(self.pack, "L1", max_items=1)
        self.assertFalse(plan["feasible"])
        self.assertEqual(1, len(plan["selected_questions"]))
        self.assertEqual(1, len(plan["missing"]))
        self.assertTrue(plan["makeup_for_missing"][plan["missing"][0]]["next_session_materials"])

    def test_valid_and_ambiguous_candidate_files(self):
        valid = check_candidate(load_candidate(ROOT / "examples" / "candidate_valid.json"), self.pack)
        self.assertEqual("approved", valid["decision"], valid["blockers"])

        ambiguous = check_candidate(
            load_candidate(ROOT / "examples" / "candidate_ambiguous.json"), self.pack
        )
        self.assertEqual("returned", ambiguous["decision"])
        self.assertIn("non_unique_answer", {x["code"] for x in ambiguous["blockers"]})

    def test_negation_counterfactual_detector(self):
        self.assertTrue(is_negation_counterfactual("该批已放行。", "该批未放行。"))
        self.assertFalse(is_negation_counterfactual("蓝签 F2 有回执。", "W3 可直接领用。"))

    def test_approved_candidate_can_be_promoted_into_temp_pack(self):
        import shutil
        import tempfile
        from handover.promotion import promote_candidate

        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            data_dir = target / "materials"
            shutil.copytree(ROOT / "materials", data_dir)
            annotation_path = target / "annotations.json"
            shutil.copy(ROOT / "editorial" / "annotations.json", annotation_path)

            result = promote_candidate(
                ROOT / "examples" / "candidate_valid.json",
                data_dir,
                annotation_path,
                question_id="Q8",
            )
            promoted = Pack.load(data_dir, annotation_path)
            self.assertEqual("Q8", result["promoted_question"])
            self.assertEqual(8, len(promoted.questions))
            self.assertEqual("approved", review_question(promoted, "Q8")["decision"])


if __name__ == "__main__":
    unittest.main()
