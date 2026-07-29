import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "mae_flow_commit_ownership_test",
    os.path.join(ROOT, "scripts", "mae-flow.py"))
mf = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mf)
with open(
        os.path.join(ROOT, "flow", "flow.json"),
        encoding="utf-8") as flow_stream:
    mf.FLOW = json.load(flow_stream)


def git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, text=True,
        capture_output=True).stdout.strip()


def write(root, relative, text):
    path = os.path.join(root, relative)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
    return path


class CommitOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mae-flow-ownership-")
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.email", "ownership@test.invalid")
        git(self.repo, "config", "user.name", "Ownership Test")
        write(self.repo, "README.md", "base\n")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-qm", "base")
        git(self.repo, "branch", "-M", "main")
        git(self.repo, "checkout", "-qb", "feature")
        self.old_cwd = os.getcwd()
        os.chdir(self.repo)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def state(self, current="build"):
        return {
            "current": current,
            "config": {
                "单号": "REQ123", "单号类型": "fix",
                "CHANGE_NAME": "current-change",
                "基线分支": "main", "分支名": "feature",
            },
            "choices": {"workflow": "full"},
            "history": [], "started": "2026-07-28 10:00:00",
            "initial_dirty": [], "initial_dirty_fingerprints": {},
        }

    def mark_initial(self, state, path):
        state["initial_dirty"].append(path)
        state["initial_dirty_fingerprints"][path] = mf._path_fingerprint(path)

    def test_unchanged_previous_story_is_blocked_before_commit(self):
        old_story = "openspec/changes/old/STORY-REQ122.md"
        write(self.repo, old_story, "# STORY-REQ122\n\n上一单。\n")
        state = self.state()
        self.mark_initial(state, old_story)
        git(self.repo, "add", old_story)

        inherited, foreign, strong, unproven, hints = (
            mf._pending_commit_files("", state))

        self.assertEqual([old_story], inherited)
        self.assertEqual([old_story], foreign)
        self.assertFalse(strong)
        self.assertIn(old_story, unproven)
        self.assertFalse(hints)

    def test_openspec_trust_is_limited_to_current_delivery(self):
        current = "openspec/changes/current-change/change.md"
        foreign = "openspec/changes/another-change/change.md"
        disguised_story = "openspec/changes/current-change/notes.md"
        write(self.repo, current, "# 变更\n")
        write(self.repo, foreign, "# 其他单\n")
        write(self.repo, disguised_story, "# STORY-REQ123\n")

        state = self.state()
        self.assertTrue(mf._trusted_harness_commit_path(current, state))
        self.assertFalse(mf._trusted_harness_commit_path(foreign, state))
        self.assertFalse(mf._trusted_harness_commit_path(disguised_story, state))

        state["spec"] = {
            "archived_to": "2026-07-28-current-change",
            "archive_paths": [
                "openspec/changes/archive/2026-07-28-current-change",
                "openspec/specs/runtime/spec.md",
            ],
        }
        self.assertTrue(mf._trusted_harness_commit_path(
            "openspec/changes/archive/2026-07-28-current-change/change.md",
            state))
        self.assertTrue(mf._trusted_harness_commit_path(
            "openspec/specs/runtime/spec.md", state))
        self.assertFalse(mf._trusted_harness_commit_path(
            "openspec/specs/other/spec.md", state))

    def test_push_backstop_detects_manually_committed_carryover(self):
        old_story = "openspec/changes/old/STORY-REQ122.md"
        write(self.repo, old_story, "# STORY-REQ122\n\n上一单。\n")
        state = self.state(current="push")
        self.mark_initial(state, old_story)
        write(self.repo, "src/current.cpp", "int current = 1;\n")
        git(self.repo, "add", old_story, "src/current.cpp")
        git(self.repo, "commit", "-qm", "[REQ123][fix]current")
        remote = os.path.join(self.tmp, "remote.git")
        git(self.tmp, "init", "--bare", "-q", remote)
        git(self.repo, "remote", "add", "origin", remote)
        git(self.repo, "push", "-qu", "origin", "HEAD")

        ok, why = mf.ev_pushed({}, state)

        self.assertFalse(ok)
        self.assertIn(old_story, why)
        self.assertIn("上一单", why)

    def test_push_backstop_detects_story_disguised_in_current_openspec(self):
        disguised = "openspec/changes/current-change/notes.md"
        state = self.state(current="push")
        write(self.repo, disguised, "# STORY-REQ123\n\n不应入库。\n")
        git(self.repo, "add", disguised)
        git(self.repo, "commit", "-qm", "[REQ123][fix]current")
        remote = os.path.join(self.tmp, "remote.git")
        git(self.tmp, "init", "--bare", "-q", remote)
        git(self.repo, "remote", "add", "origin", remote)
        git(self.repo, "push", "-qu", "origin", "HEAD")

        ok, why = mf.ev_pushed({}, state)

        self.assertFalse(ok)
        self.assertIn(disguised, why)
        self.assertIn("不属于当前", why)

    def test_archive_clean_checks_only_exact_current_outputs(self):
        stale = "openspec/changes/old/change.md"
        archive = (
            "openspec/changes/archive/2026-07-28-current-change/change.md")
        merged = "openspec/specs/runtime/spec.md"
        write(self.repo, stale, "# old\n")
        state = self.state(current="archive")
        self.mark_initial(state, stale)
        write(self.repo, archive, "# current\n")
        write(self.repo, merged, "# spec\n")
        state["spec"] = {
            "phase": "archived",
            "archived_to": "2026-07-28-current-change",
            "archive_paths": [
                "openspec/changes/archive/2026-07-28-current-change",
                merged,
            ],
        }
        ok, why = mf.ev_archive_paths_clean({}, state)
        self.assertFalse(ok)
        self.assertIn("本次定稿产物", why)
        self.assertNotIn(stale, why)

        git(self.repo, "add",
            "openspec/changes/archive/2026-07-28-current-change", merged)
        git(self.repo, "commit", "-qm", "[REQ123][fix]archive")
        ok, why = mf.ev_archive_paths_clean({}, state)
        self.assertTrue(ok, why)
        self.assertTrue(os.path.isfile(stale))

    def test_story_localize_unstages_and_corrects_wrong_directory(self):
        wrong = "openspec/changes/old/story-notes.md"
        write(self.repo, wrong, "# STORY-REQ123\n\n本地交测。\n")
        git(self.repo, "add", wrong)

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            destination = mf._localize_story("REQ123")

        self.assertFalse(os.path.exists(wrong))
        self.assertTrue(os.path.isfile(destination))
        self.assertTrue(destination.startswith(".mae-flow-work/story/"))
        self.assertEqual("", git(
            self.repo, "diff", "--cached", "--name-only", "--", wrong))
        self.assertNotIn(".mae-flow-work", git(
            self.repo, "status", "--short", "--untracked-files=all"))
        exclude = git(self.repo, "rev-parse", "--git-path", "info/exclude")
        with open(os.path.join(self.repo, exclude), encoding="utf-8") as stream:
            self.assertIn("/.mae-flow-work/", stream.read())
        self.assertIn("错误目录", output.getvalue())

    def test_full_flow_can_canonicalize_one_wrong_story_before_evidence(self):
        wrong = "openspec/changes/current-change/notes.md"
        canonical = "docs/story/STORY-REQ123.md"
        write(self.repo, wrong, "# STORY-REQ123\n\n本单内容。\n")
        git(self.repo, "add", wrong)

        with contextlib.redirect_stdout(io.StringIO()):
            result = mf._canonicalize_story_output("REQ123")

        self.assertEqual(canonical, result)
        self.assertFalse(os.path.exists(wrong))
        self.assertTrue(os.path.isfile(canonical))
        self.assertEqual("", git(
            self.repo, "diff", "--cached", "--name-only", "--", wrong))

    def test_full_flow_does_not_adopt_unchanged_previous_story(self):
        wrong = "openspec/changes/old/notes.md"
        write(self.repo, wrong, "# STORY-REQ123\n\n上一单内容。\n")
        state = self.state(current="story")
        self.mark_initial(state, wrong)

        result = mf._canonicalize_story_output("REQ123", state)

        self.assertEqual("", result)
        self.assertTrue(os.path.isfile(wrong))
        self.assertFalse(os.path.exists("docs/story/STORY-REQ123.md"))


if __name__ == "__main__":
    unittest.main()
