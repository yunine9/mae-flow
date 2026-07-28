import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import time
import types
import unittest
import sys


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "mae_flow_checkpoint_test", os.path.join(ROOT, "scripts", "mae-flow.py"))
mf = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mf)
FLOW = json.load(open(os.path.join(ROOT, "flow", "flow.json"), encoding="utf-8"))
mf.FLOW = FLOW


def git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, text=True,
        capture_output=True).stdout.strip()


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.email", "checkpoint@test.invalid")
        git(self.repo, "config", "user.name", "Checkpoint Test")
        os.makedirs(os.path.join(self.repo, "src"))
        with open(os.path.join(self.repo, "src", "main.cpp"), "w", encoding="utf-8") as f:
            f.write("int value = 1;\n")
        git(self.repo, "add", "src/main.cpp")
        git(self.repo, "commit", "-qm", "base")
        self.base = git(self.repo, "rev-parse", "HEAD")
        self.old_cwd = os.getcwd()
        os.chdir(self.repo)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def state(self, current="tw_pace", mode=None, checkpoints=2):
        now = "2026-07-28 10:00:00"
        state = {
            "current": current,
            "config": {
                "单号": "REQ1", "单号类型": "fix",
                "CHANGE_NAME": "checkpoint-test",
            },
            "choices": {"workflow": "tweak"},
            "history": [], "started": now,
            "step_heads": {current: self.base},
            "initial_dirty": [], "initial_dirty_fingerprints": {},
        }
        if mode:
            state["development_review"] = {
                "version": 1, "status": "active", "mode": mode,
                "delivery_base": self.base,
                "last_reviewed_head": self.base,
                "current_index": 0,
                "task_structure_sha256": "",
                "checkpoints": [
                    {
                        "id": "CP%d" % (i + 1),
                        "title": "batch %d" % (i + 1),
                        "status": "coding",
                        "attempt": 1,
                        "fixed_base": self.base if i == 0 else "",
                    }
                    for i in range(checkpoints)
                ],
            }
        return state

    def save(self, state):
        mf.save_state(state)
        return mf.load_state()

    def message(self, state, text):
        with open(mf.STATE_PATH + ".usermsg", "w", encoding="utf-8") as f:
            json.dump([{
                "text": text, "step": state["current"],
                "at": "9999-12-31 23:59:59",
            }], f, ensure_ascii=False)

    def commit_source(self, text, message):
        with open("src/main.cpp", "a", encoding="utf-8") as f:
            f.write(text + "\n")
        git(self.repo, "add", "src/main.cpp")
        git(self.repo, "commit", "-qm", message)
        return git(self.repo, "rev-parse", "HEAD")

    def compile_receipt(self, state, checkpoint):
        head = git(self.repo, "rev-parse", "HEAD")
        state.setdefault("agent_tasks", {})["COMPILE"] = {
            "step": state["current"], "head": head, "sha256": "task-" + checkpoint,
            "scope": checkpoint, "checkpoint": checkpoint,
        }
        self.save(state)
        with open(mf.STATE_PATH + ".tokens", "w", encoding="utf-8") as f:
            json.dump({"COMPILE": {
                "at": "9999-12-31 23:59:59", "step": state["current"],
                "head": head, "status": "OK",
            }}, f)

    def test_plan_confirmed_before_code_and_continuous_batch_does_not_wait(self):
        state = self.save(self.state())
        with contextlib.redirect_stdout(io.StringIO()):
            mf.cmd_checkpoint_plan(state, types.SimpleNamespace(
                item=["core behavior", "compatibility"]))
        state = mf.load_state()
        self.message(state, json.dumps({
            "answer": "一次完成全部代码，最终统一检视"
        }, ensure_ascii=False))
        with contextlib.redirect_stdout(io.StringIO()):
            mf.cmd_done(FLOW, state, types.SimpleNamespace(
                ack=None, choice="continuous", set=[]))
        state = mf.load_state()
        self.assertEqual(state["current"], "tw_change")
        self.assertEqual(state["development_review"]["mode"], "continuous")

        self.commit_source("int second = 2;", "[REQ1][fix]first batch")
        state = mf.load_state()
        self.compile_receipt(state, "CP1")
        state = mf.load_state()
        with contextlib.redirect_stdout(io.StringIO()):
            mf.cmd_checkpoint_ready(
                FLOW, state, types.SimpleNamespace(checkpoint_id="CP1"))
        state = mf.load_state()
        self.assertEqual(
            state["development_review"]["checkpoints"][0]["status"], "completed")
        self.assertEqual(state["development_review"]["current_index"], 1)
        self.assertEqual(
            state["development_review"]["checkpoints"][1]["status"], "coding")

    def test_review_with_no_confirmed_fixes_does_not_deadlock_on_empty_checkpoint(self):
        state = self.state(current="rf_pace")
        state["choices"]["workflow"] = "review"
        state = self.save(state)
        with contextlib.redirect_stdout(io.StringIO()):
            mf.cmd_checkpoint_plan(state, types.SimpleNamespace(
                item=["no code changes after triage"]))
        state = mf.load_state()
        self.assertTrue(state["development_review"]["no_code_plan"])
        mf._activate_checkpoint_plan(state, "staged")
        self.assertTrue(mf.ev_checkpoint_plan_complete({}, state)[0])
        self.assertEqual(state["development_review"]["current_index"], 1)

    def test_staged_revise_keeps_original_base(self):
        state = self.save(self.state(current="tw_change", mode="staged", checkpoints=1))
        rejected_head = self.commit_source(
            "int rejected = 2;", "[REQ1][fix]candidate")
        state = mf.load_state()
        self.compile_receipt(state, "CP1")
        state = mf.load_state()
        with contextlib.redirect_stdout(io.StringIO()):
            mf.cmd_checkpoint_ready(
                FLOW, state, types.SimpleNamespace(checkpoint_id="CP1"))

        remote = os.path.join(self.tmp, "remote.git")
        git(self.tmp, "init", "--bare", "-q", remote)
        git(self.repo, "remote", "add", "origin", remote)
        git(self.repo, "push", "-qu", "origin", "HEAD")
        state = mf.load_state()
        with contextlib.redirect_stdout(io.StringIO()):
            mf.cmd_checkpoint_status(state)
        state = mf.load_state()
        receipt = state["development_review"]["checkpoints"][0]["receipt"]
        self.assertEqual(receipt["head"], rejected_head)
        self.assertEqual(receipt["base"], self.base)

        self.message(state, mf.CHECKPOINT_REVISE_ACK)
        with contextlib.redirect_stdout(io.StringIO()):
            mf.cmd_checkpoint_decide(FLOW, state, types.SimpleNamespace(
                choice="revise", ack=mf.CHECKPOINT_REVISE_ACK))
        state = mf.load_state()
        item = state["development_review"]["checkpoints"][0]
        self.assertEqual(item["status"], "coding")
        self.assertEqual(item["fixed_base"], self.base)
        self.assertNotIn("receipt", item)

        self.commit_source("int corrected = 3;", "[REQ1][fix]correct candidate")
        state = mf.load_state()
        self.compile_receipt(state, "CP1")
        state = mf.load_state()
        with contextlib.redirect_stdout(io.StringIO()):
            mf.cmd_checkpoint_ready(
                FLOW, state, types.SimpleNamespace(checkpoint_id="CP1"))
        git(self.repo, "push", "-q")
        state = mf.load_state()
        with contextlib.redirect_stdout(io.StringIO()):
            mf.cmd_checkpoint_status(state)
        state = mf.load_state()
        receipt = state["development_review"]["checkpoints"][0]["receipt"]
        self.assertEqual(receipt["base"], self.base)
        self.assertNotEqual(receipt["head"], rejected_head)
        self.message(state, mf.CHECKPOINT_CONTINUE_ACK)
        with contextlib.redirect_stdout(io.StringIO()):
            mf.cmd_checkpoint_decide(FLOW, state, types.SimpleNamespace(
                choice="continue", ack=mf.CHECKPOINT_CONTINUE_ACK))
        state = mf.load_state()
        self.assertEqual(
            state["development_review"]["checkpoints"][0]["status"], "accepted")
        self.assertEqual(state["development_review"]["current_index"], 1)

    def test_switch_to_continuous_keeps_valid_compile_and_closes_mixed_states(self):
        state = self.state(current="tw_change", mode="staged", checkpoints=3)
        state["development_review"]["checkpoints"][0].update({
            "status": "accepted", "accepted_head": self.base,
        })
        state["development_review"]["current_index"] = 1
        state["development_review"]["checkpoints"][1]["fixed_base"] = self.base
        state = self.save(state)

        cp2_head = self.commit_source(
            "int second_batch = 2;", "[REQ1][fix]second batch")
        state = mf.load_state()
        self.compile_receipt(state, "CP2")
        with contextlib.redirect_stdout(io.StringIO()):
            mf.cmd_checkpoint_ready(
                FLOW, mf.load_state(),
                types.SimpleNamespace(checkpoint_id="CP2"))

        remote = os.path.join(self.tmp, "remote.git")
        git(self.tmp, "init", "--bare", "-q", remote)
        git(self.repo, "remote", "add", "origin", remote)
        git(self.repo, "push", "-qu", "origin", "HEAD")
        with contextlib.redirect_stdout(io.StringIO()):
            mf.cmd_checkpoint_status(mf.load_state())
        state = mf.load_state()
        self.message(state, mf.CHECKPOINT_CONTINUOUS_ACK)
        with contextlib.redirect_stdout(io.StringIO()):
            mf.cmd_checkpoint_decide(FLOW, state, types.SimpleNamespace(
                choice="continuous", ack=mf.CHECKPOINT_CONTINUOUS_ACK))
        state = mf.load_state()
        data = state["development_review"]
        self.assertEqual(data["mode"], "continuous")
        self.assertEqual(data["current_index"], 2)
        self.assertEqual(data["checkpoints"][1]["status"], "completed")
        self.assertEqual(data["checkpoints"][1]["completed_head"], cp2_head)
        self.assertEqual(data["checkpoints"][2]["status"], "coding")

        self.commit_source("int third_batch = 3;", "[REQ1][fix]third batch")
        state = mf.load_state()
        self.compile_receipt(state, "CP3")
        with contextlib.redirect_stdout(io.StringIO()):
            mf.cmd_checkpoint_ready(
                FLOW, mf.load_state(),
                types.SimpleNamespace(checkpoint_id="CP3"))
        self.assertTrue(mf.ev_checkpoint_plan_complete({}, mf.load_state())[0])

    def test_final_review_catches_quality_delta_but_ignores_docs_only(self):
        state = self.state(
            current="delivery_review", mode="continuous", checkpoints=1)
        state["development_review"]["checkpoints"][0].update({
            "status": "completed", "completed_head": self.base,
        })
        state["development_review"]["current_index"] = 1
        self.save(state)
        code_head = self.commit_source(
            "int quality_fix = 3;", "[REQ1][fix]quality fix")
        state = mf.load_state()
        ok, _ = mf.ev_final_review_clear({}, state)
        self.assertFalse(ok)

        with contextlib.redirect_stdout(io.StringIO()):
            mf.cmd_checkpoint_final(state)
        state = mf.load_state()
        self.assertEqual(
            state["development_review"]["final_review"]["status"],
            "review_pending")
        self.message(state, mf.CHECKPOINT_CONTINUE_ACK)
        with contextlib.redirect_stdout(io.StringIO()):
            mf.cmd_checkpoint_decide(FLOW, state, types.SimpleNamespace(
                choice="continue", ack=mf.CHECKPOINT_CONTINUE_ACK))
        state = mf.load_state()
        self.assertEqual(
            state["development_review"]["last_reviewed_head"], code_head)
        self.assertTrue(mf.ev_final_review_clear({}, state)[0])

        with open("README.md", "w", encoding="utf-8") as f:
            f.write("docs only\n")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-qm", "[REQ1][fix]docs")
        self.assertTrue(mf.ev_final_review_clear({}, mf.load_state())[0])

        self.commit_source("int late = 4;", "[REQ1][fix]late code")
        self.assertFalse(mf.ev_final_review_clear({}, mf.load_state())[0])

    def test_staged_final_review_requires_exact_remote_head_before_acceptance(self):
        state = self.state(
            current="delivery_review", mode="staged", checkpoints=1)
        state["development_review"]["checkpoints"][0].update({
            "status": "accepted", "completed_head": self.base,
        })
        state["development_review"]["current_index"] = 1
        self.save(state)
        code_head = self.commit_source(
            "int final_quality_fix = 5;", "[REQ1][fix]final quality fix")

        with contextlib.redirect_stdout(io.StringIO()):
            mf.cmd_checkpoint_final(mf.load_state())
        state = mf.load_state()
        self.assertEqual(
            state["development_review"]["final_review"]["status"],
            "push_pending")

        remote = os.path.join(self.tmp, "remote.git")
        git(self.tmp, "init", "--bare", "-q", remote)
        git(self.repo, "remote", "add", "origin", remote)
        git(self.repo, "push", "-qu", "origin", "HEAD")
        with contextlib.redirect_stdout(io.StringIO()):
            mf.cmd_checkpoint_final(mf.load_state())
        state = mf.load_state()
        final = state["development_review"]["final_review"]
        self.assertEqual(final["status"], "review_pending")
        self.assertEqual(final["head"], code_head)
        self.assertEqual(final["remote_head"], code_head)
        self.assertTrue(final["remote_ref"])

        self.message(state, mf.CHECKPOINT_CONTINUE_ACK)
        with contextlib.redirect_stdout(io.StringIO()):
            mf.cmd_checkpoint_decide(FLOW, state, types.SimpleNamespace(
                choice="continue", ack=mf.CHECKPOINT_CONTINUE_ACK))
        state = mf.load_state()
        self.assertEqual(
            state["development_review"]["last_reviewed_head"], code_head)
        self.assertTrue(mf.ev_final_review_clear({}, state)[0])

    def test_final_review_rejects_rewritten_reviewed_history(self):
        state = self.state(
            current="delivery_review", mode="continuous", checkpoints=1)
        state["development_review"]["checkpoints"][0].update({
            "status": "completed", "completed_head": self.base,
        })
        state["development_review"]["current_index"] = 1
        reviewed = self.commit_source(
            "int reviewed = 6;", "[REQ1][fix]reviewed code")
        state["development_review"]["last_reviewed_head"] = reviewed
        self.save(state)

        tree = git(self.repo, "rev-parse", "HEAD^{tree}")
        rewritten = git(
            self.repo, "commit-tree", tree, "-m", "rewritten equivalent tree")
        git(self.repo, "update-ref", "HEAD", rewritten)
        ok, why = mf.ev_final_review_clear({}, mf.load_state())
        self.assertFalse(ok)
        self.assertIn("不在当前 HEAD 历史", why)

    def test_final_review_revise_returns_to_normal_quality_chain_not_closed_cp(self):
        state = self.state(
            current="delivery_review", mode="continuous", checkpoints=1)
        state["development_review"]["checkpoints"][0].update({
            "status": "completed", "completed_head": self.base,
        })
        state["development_review"]["current_index"] = 1
        state = self.save(state)
        self.commit_source("int revise_me = 7;", "[REQ1][fix]candidate")
        with contextlib.redirect_stdout(io.StringIO()):
            mf.cmd_checkpoint_final(mf.load_state())
        state = mf.load_state()
        self.message(state, mf.CHECKPOINT_REVISE_ACK)
        with contextlib.redirect_stdout(io.StringIO()):
            mf.cmd_checkpoint_decide(FLOW, state, types.SimpleNamespace(
                choice="revise", ack=mf.CHECKPOINT_REVISE_ACK))
        state = mf.load_state()
        self.assertEqual(state["current"], "tw_change")
        self.assertEqual(
            state["development_review"]["final_rework"]["status"], "coding")
        self.assertIsNone(mf._checkpoint_current(state))

        rendered = io.StringIO()
        with contextlib.redirect_stdout(rendered):
            mf.print_current(FLOW, state)
        self.assertIn("不要再执行 checkpoint ready", rendered.getvalue())

    def test_new_state_skips_legacy_review_while_old_state_keeps_it(self):
        state = self.state(current="tw_compile", mode="continuous", checkpoints=1)
        state["development_review"]["checkpoints"][0]["status"] = "completed"
        state["development_review"]["current_index"] = 1
        self.save(state)
        with contextlib.redirect_stdout(io.StringIO()):
            mf.advance(
                FLOW, state, "tw_compile", FLOW["steps"]["tw_compile"], "done")
        self.assertEqual(mf.load_state()["current"], "tw_codecheck")

        os.remove(mf.STATE_PATH)
        legacy = self.state(current="tw_compile")
        self.save(legacy)
        with contextlib.redirect_stdout(io.StringIO()):
            mf.advance(
                FLOW, legacy, "tw_compile", FLOW["steps"]["tw_compile"], "done")
        self.assertEqual(mf.load_state()["current"], "tw_review")

        os.remove(mf.STATE_PATH)
        legacy_final = self.state(current="tw_verify")
        self.save(legacy_final)
        with contextlib.redirect_stdout(io.StringIO()):
            mf.advance(
                FLOW, legacy_final, "tw_verify",
                FLOW["steps"]["tw_verify"], "done")
        self.assertEqual(mf.load_state()["current"], "archive_confirm")

    def test_old_state_before_pace_keeps_original_route(self):
        legacy = self.state(current="tw_open")
        self.save(legacy)
        with contextlib.redirect_stdout(io.StringIO()):
            mf.advance(
                FLOW, legacy, "tw_open", FLOW["steps"]["tw_open"], "done")
        self.assertEqual(mf.load_state()["current"], "tw_change")

        os.remove(mf.STATE_PATH)
        modern = self.state(current="tw_open")
        modern["protocols"] = {"development_checkpoints": 1}
        self.save(modern)
        with contextlib.redirect_stdout(io.StringIO()):
            mf.advance(
                FLOW, modern, "tw_open", FLOW["steps"]["tw_open"], "done")
        self.assertEqual(mf.load_state()["current"], "tw_pace")

    def test_old_state_already_on_new_pace_node_recovers_without_choice(self):
        legacy = self.save(self.state(current="tw_pace"))
        with contextlib.redirect_stdout(io.StringIO()):
            mf.cmd_done(FLOW, legacy, types.SimpleNamespace(
                ack=None, choice=None, set=[]))
        self.assertEqual(mf.load_state()["current"], "tw_change")

    def test_review_pending_blocks_agent_source_edits_and_moonlight_bypasses(self):
        state = self.state(current="tw_change", mode="staged", checkpoints=1)
        item = state["development_review"]["checkpoints"][0]
        item["status"] = "review_pending"
        item["receipt"] = {
            "base": self.base, "head": self.base,
            "remote_ref": "origin/main", "remote_head": self.base,
        }
        state = self.save(state)
        with self.assertRaises(SystemExit) as blocked:
            with contextlib.redirect_stderr(io.StringIO()):
                mf.cmd_gate(FLOW, state, types.SimpleNamespace(
                    what="edit", arg="src/main.cpp"))
        self.assertEqual(blocked.exception.code, 2)

        state["moonlight"] = {"enabled": True}
        with self.assertRaises(SystemExit) as allowed:
            mf.cmd_gate(FLOW, state, types.SimpleNamespace(
                what="edit", arg="src/main.cpp"))
        self.assertEqual(allowed.exception.code, 0)

    def test_previous_checkpoint_answer_cannot_be_reused_in_same_code_step(self):
        state = self.save(self.state(
            current="tw_change", mode="staged", checkpoints=1))
        self.message(state, mf.CHECKPOINT_CONTINUE_ACK)
        receipt = {"ack_cursor": mf._ack_message_cursor()}
        ok, why = mf._checkpoint_ack(
            state, mf.CHECKPOINT_CONTINUE_ACK,
            mf.CHECKPOINT_CONTINUE_ACK, receipt)
        self.assertFalse(ok)
        self.assertIn("上一批", why)
        with open(mf.STATE_PATH + ".usermsg", "w", encoding="utf-8") as f:
            json.dump([
                {
                    "id": "old", "text": mf.CHECKPOINT_CONTINUE_ACK,
                    "step": "tw_change", "at": "9999-12-31 23:59:59",
                },
                {
                    "id": "new", "text": mf.CHECKPOINT_CONTINUE_ACK,
                    "step": "tw_change", "at": "9999-12-31 23:59:59",
                },
            ], f, ensure_ascii=False)
        ok, _ = mf._checkpoint_ack(
            state, mf.CHECKPOINT_CONTINUE_ACK,
            mf.CHECKPOINT_CONTINUE_ACK, receipt)
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
