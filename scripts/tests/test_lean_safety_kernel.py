#!/usr/bin/env python3
"""Public behavior contract for the lean workflow safety kernel."""

import json
import os
import shlex
import sys
import tempfile
import unittest
from dataclasses import replace


SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.guard.manifest import DeliveryManifest  # noqa: E402
from mae_flow_core.guard.safety_kernel import (  # noqa: E402
    SafetyContext,
    SafetyDecision,
    decide_pretool,
    decide_stateless_pretool,
)
from mae_flow_core.orchestration import (  # noqa: E402
    CapabilityAttempt,
    CommitPace,
    DeliveryPath,
    FlowState,
    Phase,
    StartupConfig,
)
from mae_flow_core.orchestration.delivery import (  # noqa: E402
    DELIVERY_RECEIPT_KEY,
    checkpoint_receipt_key,
    issue_delivery_receipt,
)


FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), "fixtures", "lean_git_cases.json"
)


def _command(argv):
    """Adapt fixture argv to the command-string parser boundary."""
    return " ".join(shlex.quote(str(token)) for token in argv)


def _paths(paths, repository_root):
    return DeliveryManifest.from_paths(
        paths, repository_root=repository_root).files


def _state(
        path=DeliveryPath.FULL,
        phase=Phase.CONSTRUCTION,
        decisions=(),
        delivery_files=(),
        initial_dirty=(),
        capabilities=(),
        commit_pace=CommitPace.STAGED):
    return FlowState(
        ticket="REQ-7",
        path=path,
        phase=phase,
        commit_pace=commit_pace,
        decisions=decisions,
        delivery_files=delivery_files,
        initial_dirty=initial_dirty,
        capabilities=capabilities,
    )


def _context(state, repository_root="/repo", **overrides):
    values = {
        "state": state,
        "repository_root": repository_root,
        "staged_files": (),
        "commit_files": (),
        "initial_dirty": (),
        "current_dirty_fingerprints": (),
        "current_branch": "",
    }
    values.update(overrides)
    return SafetyContext(**values)


def _with_final_receipt(state):
    decisions = state.decisions + (
        ("delivery.commit_message", "[REQ-7][fix]修复查询映射"),
        ("delivery.plan.remote", "origin"),
        ("delivery.plan.destination_ref", "refs/heads/main"),
        ("delivery.plan.expected_destination_sha", "a" * 40),
        ("delivery.plan.new_branch", "false"),
        ("delivery.plan.source_sha", "a" * 40),
    )
    planned = replace(
        state,
        phase=Phase.DELIVERY,
        commit_pace=CommitPace.CONTINUOUS,
        decisions=decisions,
    )
    receipt = issue_delivery_receipt(
        planned, "User confirmed the exact Git delivery plan.")
    return replace(
        planned,
        decisions=planned.decisions + ((DELIVERY_RECEIPT_KEY, receipt),),
    )


class LeanSafetyKernelFixtureTests(unittest.TestCase):
    def setUp(self):
        with open(FIXTURE_PATH, "r", encoding="utf-8") as fixture_file:
            self.fixture = json.load(fixture_file)

    def public_call(self, item):
        raw = item["context"]
        root = raw["working_directory"]
        manifest_input = raw["authorized_manifest"]
        candidate = _paths(manifest_input["files"], root)
        authorized = candidate if manifest_input["authorized"] else ()
        dirty = _paths(raw["preexisting_dirty_files"], root)
        phase = (
            Phase.CONSTRUCTION
            if raw["source_edit_confirmed"]
            else Phase.STORY
        )
        state = _state(
            phase=phase,
            delivery_files=authorized,
            initial_dirty=dirty,
        )
        if authorized and item["operation_family"].startswith("git_"):
            state = _with_final_receipt(state)
        context = _context(
            state,
            repository_root=root,
            staged_files=candidate,
            commit_files=candidate,
            initial_dirty=dirty,
            current_dirty_fingerprints=tuple(
                (path, "startup") for path in dirty),
        )

        argv = item["command"]["argv"]
        tool = "Bash"
        tool_input = {"command": _command(argv)}
        if argv[0] == "apply_patch":
            tool = "ApplyPatch"
            tool_input = {"targets": _paths([argv[1]], root)}
        elif item["operation_family"] == "protected_control":
            tool_input["targets"] = _paths([argv[-1]], root)
        elif item["operation_family"] == "filesystem":
            # A shell adapter owns argv parsing.  The pure kernel consumes the
            # already-parsed destructive targets that guard.bash recognizes.
            tool_input["recursive_delete_targets"] = (argv[-1],)
        return decide_pretool(context, tool, tool_input)

    def test_every_versioned_fixture_case_runs_through_the_public_api(self):
        self.assertEqual(1, self.fixture["schema_version"])
        decisions = {
            item["case"]: self.public_call(item)
            for item in self.fixture["cases"]
        }

        self.assertEqual(
            {
                item["case"]: item["expected"]["allowed"]
                for item in self.fixture["cases"]
            },
            {
                case: decision.allow
                for case, decision in decisions.items()
            },
        )
        self.assertTrue(all(
            isinstance(decision, SafetyDecision)
            for decision in decisions.values()
        ))
        for item in self.fixture["cases"]:
            if not item["expected"]["allowed"]:
                self.assertEqual(
                    item["operation_family"],
                    decisions[item["case"]].rule,
                    item["case"],
                )

    def test_windows_argv_is_adapted_without_losing_drive_or_backslashes(self):
        item = next(
            case for case in self.fixture["cases"]
            if case["case"] == "allowed_windows_exact_file_git_add"
        )

        decision = self.public_call(item)

        self.assertTrue(decision.allow)


class SourceEditAuthorizationTests(unittest.TestCase):
    def decision(self, state, target, **context_facts):
        return decide_pretool(
            _context(state, **context_facts),
            "Edit",
            {"targets": (target,)},
        )

    def test_full_source_edits_require_explicit_construction_phase(self):
        construction = self.decision(
            _state(phase=Phase.CONSTRUCTION), "src/main.py")
        story = self.decision(
            _state(phase=Phase.STORY), "src/main.py")
        quality = self.decision(
            _state(phase=Phase.QUALITY), "src/main.py")
        approved_quality = self.decision(
            _state(
                phase=Phase.QUALITY,
                decisions=((
                    "quality.source_fix_approved",
                    "The user approved the diagnosed source fix.",
                ),),
            ),
            "src/main.py",
        )

        self.assertTrue(construction.allow)
        self.assertEqual((False, "source_edit"), (story.allow, story.rule))
        self.assertEqual((False, "source_edit"), (quality.allow, quality.rule))
        self.assertEqual(
            (False, "source_edit"),
            (approved_quality.allow, approved_quality.rule),
        )

    def test_staged_checkpoint_confirmation_freezes_source_until_commit(self):
        planned = _state(
            phase=Phase.CONSTRUCTION,
            decisions=(
                ("construction.cp.CP1.ready", "true"),
                ("construction.cp.CP1.confirmation", "用户确认 CP1。"),
                ("delivery.cp.CP1.file", "src/main.py"),
                ("delivery.cp.CP1.message", "[REQ-7][fix]完成 CP1"),
                ("delivery.cp.CP1.source_sha", "a" * 40),
            ),
        )
        receipt = issue_delivery_receipt(
            planned, "用户确认 CP1。", checkpoint="CP1")
        confirmed = replace(
            planned,
            current_cp="CP1",
            decisions=planned.decisions + ((
                checkpoint_receipt_key("CP1"), receipt),),
        )

        decision = self.decision(confirmed, "src/main.py")

        self.assertEqual(
            (False, "source_edit"), (decision.allow, decision.rule))
        self.assertIn("CP1", decision.message)

    def test_non_bash_command_text_is_never_treated_as_shell_execution(self):
        decision = decide_pretool(
            _context(_state(phase=Phase.CONSTRUCTION)),
            "apply_patch",
            {
                "command": "git reset --hard HEAD",
                "targets": ("src/help_text.py",),
            },
        )
        self.assertTrue(decision.allow)

    def test_focused_source_edits_require_scope_approval(self):
        unapproved = self.decision(
            _state(path=DeliveryPath.FOCUSED), "src/main.py")
        approved = self.decision(
            _state(
                path=DeliveryPath.FOCUSED,
                decisions=((
                    "focused.scope_approved",
                    "The user approved the focused change scope.",
                ),),
            ),
            "src/main.py",
        )

        self.assertEqual((False, "source_edit"), (
            unapproved.allow, unapproved.rule))
        self.assertTrue(approved.allow)

    def test_documentation_and_work_packages_are_allowed_outside_coding(self):
        startup = _state(phase=Phase.STARTUP)

        documentation = self.decision(startup, "docs/decision.md")
        work_package = self.decision(
            startup, ".mae-flow-work/REQ-7/plan.md")

        self.assertTrue(documentation.allow)
        self.assertTrue(work_package.allow)

    def test_unknown_repository_writes_are_scope_controlled(self):
        targets = (
            "web/index.html",
            "web/site.css",
            "LICENSE",
            "config/application.yaml",
            "tests/page.snapshot",
        )
        full_before = _state(phase=Phase.STORY)
        full_after = _state(phase=Phase.CONSTRUCTION)
        focused_before = _state(path=DeliveryPath.FOCUSED)
        focused_after = _state(
            path=DeliveryPath.FOCUSED,
            decisions=((
                "focused.scope_approved",
                "The user approved the focused change scope.",
            ),),
        )

        for target in targets:
            with self.subTest(target=target):
                full_blocked = self.decision(full_before, target)
                focused_blocked = self.decision(focused_before, target)
                self.assertEqual(
                    (False, "source_edit"),
                    (full_blocked.allow, full_blocked.rule),
                )
                self.assertTrue(self.decision(full_after, target).allow)
                self.assertEqual(
                    (False, "source_edit"),
                    (focused_blocked.allow, focused_blocked.rule),
                )
                self.assertTrue(self.decision(focused_after, target).allow)

    def test_adapter_can_explicitly_classify_a_non_source_target_as_safe(self):
        safe = self.decision(
            _state(phase=Phase.STARTUP),
            "generated/cache.bin",
            safe_write_targets=("generated/cache.bin",),
        )
        protected = self.decision(
            _state(phase=Phase.CONSTRUCTION),
            ".mae-flow.yml",
            safe_write_targets=(".mae-flow.yml",),
        )

        self.assertTrue(safe.allow)
        self.assertEqual(
            (False, "protected_control"),
            (protected.allow, protected.rule),
        )

    def test_safe_write_identity_follows_repository_path_style(self):
        startup = _state(phase=Phase.STARTUP)

        posix_case_mismatch = self.decision(
            startup,
            "Generated/Cache.bin",
            safe_write_targets=("generated/cache.bin",),
        )
        windows_drive_match = self.decision(
            startup,
            r"C:\WORK\REPO\Generated\Cache.bin",
            repository_root=r"c:\work\repo",
            safe_write_targets=("generated/cache.bin",),
        )
        windows_unc_match = self.decision(
            startup,
            r"\\SERVER\SHARE\REPO\Generated\Cache.bin",
            repository_root=r"\\server\share\repo",
            safe_write_targets=(r"generated\cache.bin",),
        )

        self.assertEqual(
            (False, "source_edit"),
            (posix_case_mismatch.allow, posix_case_mismatch.rule),
        )
        self.assertTrue(windows_drive_match.allow)
        self.assertTrue(windows_unc_match.allow)

    def test_protected_controls_precede_source_authorization(self):
        approved = _state(
            phase=Phase.CONSTRUCTION,
            delivery_files=(".mae-flow.yml",),
        )

        decision = self.decision(approved, ".mae-flow.yml")

        self.assertEqual(
            (False, "protected_control"),
            (decision.allow, decision.rule),
        )

    def test_protected_control_aliases_are_normalized_before_classification(self):
        aliases = (
            "work/../.mae-flow.yml",
            "../repo/.mae-flow.yml",
            "/repo/work/../.mae-flow.yml",
            r"work\..\.MAE-FLOW.YML",
            ".MAE-FLOW.YML",
        )
        state = _state(phase=Phase.CONSTRUCTION)

        for target in aliases:
            with self.subTest(target=target):
                decision = self.decision(
                    state,
                    target,
                    safe_write_targets=(target,),
                )
                self.assertEqual(
                    (False, "protected_control"),
                    (decision.allow, decision.rule),
                )

        windows = self.decision(
            state,
            r"C:\work\repo\work\..\.MaE-Flow.YmL",
            repository_root=r"c:\work\repo",
            safe_write_targets=(r"work\..\.MaE-Flow.YmL",),
        )
        self.assertEqual(
            (False, "protected_control"),
            (windows.allow, windows.rule),
        )

        rooted_current_drive = self.decision(
            state,
            r"\work\repo\.mae-flow.yml",
            repository_root=r"C:\work\repo",
            safe_write_targets=(r"\work\repo\.mae-flow.yml",),
        )
        safe_alias = self.decision(
            state,
            "../repo/.mae-flow.yml",
            safe_write_targets=("../repo/.mae-flow.yml",),
        )
        drive_relative = self.decision(
            state,
            r"C:.mae-flow.yml",
            repository_root=r"C:\work\repo",
            safe_write_targets=(r"C:.mae-flow.yml",),
        )

        self.assertEqual(
            (False, "protected_control"),
            (rooted_current_drive.allow, rooted_current_drive.rule),
        )
        self.assertEqual(
            (False, "protected_control"),
            (safe_alias.allow, safe_alias.rule),
        )
        self.assertEqual(
            (False, "source_edit"),
            (drive_relative.allow, drive_relative.rule),
        )

    def test_shell_writers_use_the_same_phase_source_authorization(self):
        before = _state(phase=Phase.STORY)
        during = _state(phase=Phase.CONSTRUCTION)
        commands = (
            "sed -i 's/old/new/' src/main.py",
            "printf changed > src/main.py",
            "printf changed | tee src/main.py",
            "cp generated/main.py src/main.py",
            "mv generated/main.py src/main.py",
            "touch src/main.py",
            "rm src/main.py",
            (
                "python -c \"open('src/main.py', 'w').write('changed')\""
            ),
            "pwsh -NoProfile -Command Set-Content -Path src/main.py -Value x",
            r"cmd.exe /d /c echo changed ^> src\main.py",
        )

        for command in commands:
            with self.subTest(command=command):
                blocked = decide_pretool(
                    _context(before), "Bash", {"command": command})
                allowed = decide_pretool(
                    _context(during), "Bash", {"command": command})
                self.assertEqual(
                    (False, "source_edit"),
                    (blocked.allow, blocked.rule),
                )
                self.assertTrue(allowed.allow, command)

    def test_common_codeagent_writers_share_phase_authorization(self):
        before = _state(phase=Phase.STORY)
        during = _state(phase=Phase.CONSTRUCTION)
        commands = (
            ("truncate -s 0 src/main.py", True),
            ("dd if=/dev/null of=src/main.py", True),
            ("perl -pi -e 's/old/new/' src/main.py", True),
            ("ruby -pi -e 'gsub(/old/, \'new\')' src/main.py", True),
            ("patch -p0 < change.patch", False),
            ("git apply change.patch", False),
        )

        for command, allowed_during_construction in commands:
            with self.subTest(command=command):
                blocked = decide_pretool(
                    _context(before), "Bash", {"command": command})
                allowed = decide_pretool(
                    _context(during), "Bash", {"command": command})
                self.assertEqual(
                    (False, "source_edit"),
                    (blocked.allow, blocked.rule),
                )
                self.assertEqual(
                    allowed_during_construction,
                    allowed.allow,
                    command,
                )

    def test_corrupt_state_still_protects_literal_flow_control_writes(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, ".mae-flow.json"), "wb") as stream:
                stream.write(b"corrupt")

            blocked = decide_stateless_pretool(
                root,
                "Bash",
                {"command": "printf x > .mae-flow.json"},
            )
            allowed = decide_stateless_pretool(
                root,
                "Bash",
                {"command": "printf x > src/recovery-note.txt"},
            )

        self.assertEqual(
            (False, "protected_control"),
            (blocked.allow, blocked.rule),
        )
        self.assertTrue(allowed.allow)

    def test_shell_writers_never_mutate_flow_control_aliases(self):
        state = _state(phase=Phase.CONSTRUCTION)
        cases = (
            ("printf x > .MAE-FLOW.JSON", "/repo"),
            (
                "printf x > .mae-flow-work/lean-hook-user-events.json",
                "/repo",
            ),
            ("tee .CODECHECKCLI/result.json", "/repo"),
            (
                r"pwsh -Command Set-Content -Path C:\REPO\.Mae-Flow.Json -Value x",
                r"c:\repo",
            ),
            (
                r"cmd.exe /d /c copy source C:\REPO\.CODECHECKCLI\state.json",
                r"c:\repo",
            ),
            (
                "python -c \"open('.mae-flow.json.tokens', 'w').write('x')\"",
                "/repo",
            ),
        )

        for command, root in cases:
            with self.subTest(command=command):
                decision = decide_pretool(
                    _context(state, repository_root=root),
                    "Bash",
                    {"command": command},
                )
                self.assertEqual(
                    (False, "protected_control"),
                    (decision.allow, decision.rule),
                )

    def test_active_flow_rejects_interactive_background_and_reused_shells(self):
        state = _state(phase=Phase.CONSTRUCTION)
        calls = (
            ("Bash", {"command": "bash"}),
            ("Bash", {"command": "pwsh -NoProfile"}),
            ("Bash", {"command": "cmd.exe /k"}),
            ("Bash", {"command": "build-wrapper", "run_in_background": True}),
            ("Bash", {"command": "build-wrapper", "tty": True}),
            ("write_stdin", {"session_id": "shell-1", "chars": "rm src/a.py"}),
        )

        for tool, tool_input in calls:
            with self.subTest(tool=tool, tool_input=tool_input):
                decision = decide_pretool(
                    _context(state), tool, tool_input)
                self.assertEqual(
                    (False, "interactive_shell"),
                    (decision.allow, decision.rule),
                )

    def test_ordinary_private_build_wrappers_still_fail_open(self):
        state = _state(phase=Phase.STORY)

        decision = decide_pretool(
            _context(state),
            "Bash",
            {"command": "private-build-wrapper --configuration Debug"},
        )

        self.assertTrue(decision.allow)

    def test_recognized_writers_with_dynamic_targets_fail_closed(self):
        state = _state(phase=Phase.CONSTRUCTION)
        commands = (
            "printf changed > \"$TARGET\"",
            "python -c \"open(target, 'w').write('changed')\"",
        )

        for command in commands:
            with self.subTest(command=command):
                decision = decide_pretool(
                    _context(state), "Bash", {"command": command})
                self.assertEqual(
                    (False, "source_edit"),
                    (decision.allow, decision.rule),
                )


class GitManifestSafetyTests(unittest.TestCase):
    def test_commit_requires_the_confirmed_ticket_type_and_working_branch(self):
        configured = replace(
            _state(
                phase=Phase.DELIVERY,
                delivery_files=("src/a.cpp", "tests/a_test.cpp"),
                commit_pace=CommitPace.CONTINUOUS,
            ),
            startup_config=StartupConfig(
                worker="zhangsan",
                ticket_type="fix",
                base_branch="main",
                working_branch="main_zhangsan_REQ-7",
            ),
        )
        state = _with_final_receipt(configured)
        exact = ("src/a.cpp", "tests/a_test.cpp")

        wrong_type = self.bash(
            state, "git commit -m '[REQ-7][feat]修复查询映射'",
            staged_files=exact,
            current_branch="main_zhangsan_REQ-7",
        )
        wrong_branch = self.bash(
            state, "git commit -m '[REQ-7][fix]修复查询映射'",
            staged_files=exact,
            current_branch="main",
        )
        exact_commit = self.bash(
            state, "git commit -m '[REQ-7][fix]修复查询映射'",
            staged_files=exact,
            current_branch="main_zhangsan_REQ-7",
        )

        self.assertEqual((False, "git_commit"),
                         (wrong_type.allow, wrong_type.rule))
        self.assertIn("[REQ-7][fix]", wrong_type.message)
        self.assertEqual((False, "git_commit"),
                         (wrong_branch.allow, wrong_branch.rule))
        self.assertIn("main_zhangsan_REQ-7", wrong_branch.message)
        self.assertTrue(exact_commit.allow, exact_commit.message)

    def manifest_state(self, **overrides):
        values = {
            "phase": Phase.DELIVERY,
            "delivery_files": ("src/a.cpp", "tests/a_test.cpp"),
        }
        values.update(overrides)
        return _with_final_receipt(_state(**values))

    def bash(self, state, command, **facts):
        return decide_pretool(
            _context(state, **facts),
            "Bash",
            {"command": command},
        )

    def test_git_effects_require_current_receipt_and_exact_bound_fields(self):
        bare = _state(
            phase=Phase.DELIVERY,
            delivery_files=("src/a.cpp", "tests/a_test.cpp"),
            commit_pace=CommitPace.CONTINUOUS,
        )
        exact = ("src/a.cpp", "tests/a_test.cpp")
        self.assertFalse(self.bash(
            bare, "git add src/a.cpp tests/a_test.cpp").allow)

        state = self.manifest_state()
        allowed_add = self.bash(
            state, "git add src/a.cpp tests/a_test.cpp")
        wrong_message = self.bash(
            state, "git commit -m '[REQ-7][fix]其他信息'",
            staged_files=exact)
        exact_message = self.bash(
            state, "git commit -m '[REQ-7][fix]修复查询映射'",
            staged_files=exact)
        implicit_push = self.bash(
            state, "git push origin HEAD", commit_files=exact)
        canonical_push = self.bash(
            state,
            "git push --force-with-lease=refs/heads/main:%s "
            "origin HEAD:refs/heads/main" % ("a" * 40),
            commit_files=exact,
        )

        self.assertTrue(allowed_add.allow)
        self.assertFalse(wrong_message.allow)
        self.assertTrue(exact_message.allow)
        self.assertFalse(implicit_push.allow)
        self.assertFalse(canonical_push.allow)
        self.assertIn("observed", canonical_push.message.lower())

    def test_broad_staging_and_commit_options_block_before_manifest_checks(self):
        state = self.manifest_state()

        add = self.bash(state, "git add -A")
        commit = self.bash(state, "git commit -a -m update")

        self.assertEqual((False, "git_staging"), (add.allow, add.rule))
        self.assertEqual((False, "git_commit"), (
            commit.allow, commit.rule))

    def test_opaque_add_and_commit_pathspecs_block_before_manifest_checks(self):
        state = self.manifest_state()

        add = self.bash(
            state,
            "git add --pathspec-from-file=paths.txt",
            staged_files=("src/a.cpp", "tests/a_test.cpp"),
        )
        commit = self.bash(
            state,
            "git commit --pathspec-from-file paths.txt -m update",
            staged_files=("src/a.cpp", "tests/a_test.cpp"),
        )

        self.assertEqual((False, "git_staging"), (add.allow, add.rule))
        self.assertEqual((False, "git_commit"), (
            commit.allow, commit.rule))

    def test_git_pathspec_magic_cannot_be_authorized_as_an_exact_file(self):
        state = _state(
            phase=Phase.DELIVERY,
            delivery_files=(":(exclude)README.md",))

        add = self.bash(state, "git add -- ':(exclude)README.md'")

        self.assertEqual((False, "git_staging"), (add.allow, add.rule))
        self.assertIn("exact", add.message.lower())

    def test_every_commit_invocation_is_checked_in_shell_order(self):
        state = self.manifest_state()
        commands = (
            "git commit -a -m first && git commit -m second",
            "git commit -m first && git commit -a -m second",
            (
                "git commit --include src/a.cpp -m first && "
                "git commit -m second"
            ),
            (
                "git commit -m first && "
                "git commit --include src/a.cpp -m second"
            ),
        )

        for command in commands:
            with self.subTest(command=command):
                decision = self.bash(
                    state,
                    command,
                    staged_files=("src/a.cpp", "tests/a_test.cpp"),
                )
                self.assertEqual((False, "git_commit"), (
                    decision.allow, decision.rule))

    def test_heterogeneous_git_blocks_follow_shell_source_order(self):
        state = self.manifest_state()
        exact = ("src/a.cpp", "tests/a_test.cpp")
        cases = (
            (
                "git commit -a -m first && "
                "git add --pathspec-from-file=paths.txt",
                {"staged_files": exact},
                "git_commit",
            ),
            (
                "git add --pathspec-from-file=paths.txt && "
                "git commit -a -m second",
                {"staged_files": exact},
                "git_staging",
            ),
            (
                "git add src/a.cpp && "
                "git commit --pathspec-from-file=paths.txt -m second && "
                "git push origin main",
                {"staged_files": exact, "commit_files": exact},
                "git_staging",
            ),
            (
                "git push origin main && "
                "git add --pathspec-from-file=paths.txt",
                {"commit_files": ("src/a.cpp",)},
                "git_publish",
            ),
            (
                "git add -A && "
                "git commit --pathspec-from-file=paths.txt -m second && "
                "git push origin main",
                {"staged_files": exact, "commit_files": exact},
                "git_staging",
            ),
        )

        for command, facts, expected_rule in cases:
            with self.subTest(command=command):
                decision = self.bash(state, command, **facts)
                self.assertEqual(
                    (False, expected_rule),
                    (decision.allow, decision.rule),
                )

    def test_commit_requires_exact_actual_staged_manifest(self):
        state = self.manifest_state(capabilities=(CapabilityAttempt(
            "tests", "stale-source", "stale-env", "failed", "ignored"),))

        exact = self.bash(
            state,
            "git commit -m '[REQ-7][fix]修复查询映射'",
            staged_files=("tests/a_test.cpp", "src/a.cpp"),
        )
        missing = self.bash(
            state,
            "git commit -m update",
            staged_files=("src/a.cpp",),
        )
        extra = self.bash(
            state,
            "git commit -m update",
            staged_files=("src/a.cpp", "tests/a_test.cpp", "README.md"),
        )

        self.assertTrue(exact.allow)
        self.assertEqual((False, "git_commit"), (
            missing.allow, missing.rule))
        self.assertEqual((False, "git_commit"), (extra.allow, extra.rule))

    def test_commit_message_uses_ticket_and_actual_wrapper_arguments(self):
        state = self.manifest_state()
        exact = ("tests/a_test.cpp", "src/a.cpp")
        cases = (
            ("git commit -m update", False),
            ("git commit -m '[REQ-8][fix]错误单号'", False),
            ("git commit -m '[REQ-7][fix]修复查询映射'", True),
            ("git commit -m '[REQ-7][feat]实现查询条件'", False),
            ("git commit -m '[REQ-7][feat]保留尾部空格 '", False),
            ("git commit -m '[REQ-7][feat]摘要\n正文'", False),
            ("git commit -m '[REQ-7][feat] 描述前有空格'", False),
            (
                'cmd.exe /d /c git commit -m "[REQ-7][fix]修复结果映射"',
                False,
            ),
        )
        for command, expected_allow in cases:
            with self.subTest(command=command):
                decision = self.bash(
                    state, command, staged_files=exact)
                self.assertIs(expected_allow, decision.allow)
                if not expected_allow:
                    self.assertEqual("git_commit", decision.rule)
        missing_ticket = self.bash(
            replace(state, ticket=""),
            "git commit -m '[][fix]缺少单号'",
            staged_files=exact,
        )
        self.assertEqual((False, "git_commit"), (
            missing_ticket.allow, missing_ticket.rule))

        bracket_ticket = self.bash(
            replace(state, ticket="REQ[7]"),
            "git commit -m '[REQ[7]][feat]ambiguous ticket'",
            staged_files=exact,
        )
        self.assertEqual((False, "git_commit"), (
            bracket_ticket.allow, bracket_ticket.rule))

    def test_push_requires_exact_recorded_commit_manifest(self):
        state = self.manifest_state()

        exact = self.bash(
            state,
            "git push origin main",
            commit_files=("tests/a_test.cpp", "src/a.cpp"),
        )
        mismatch = self.bash(
            state,
            "git push origin main",
            commit_files=("src/a.cpp", "README.md"),
        )

        self.assertFalse(exact.allow)
        self.assertEqual((False, "git_publish"), (
            mismatch.allow, mismatch.rule))

    def test_allowed_earlier_git_action_does_not_skip_later_manifest_check(self):
        state = self.manifest_state()

        commit_after_add = self.bash(
            state,
            "git add src/a.cpp && "
            "git commit -m '[REQ-7][fix]提交部分文件'",
            staged_files=("src/a.cpp",),
        )
        push_after_commit = self.bash(
            state,
            "git commit -m '[REQ-7][fix]提交并推送' && git push origin main",
            staged_files=("src/a.cpp", "tests/a_test.cpp"),
            commit_files=("src/a.cpp",),
        )

        self.assertEqual((False, "git_staging"), (
            commit_after_add.allow, commit_after_add.rule))
        self.assertEqual((False, "git_commit"), (
            push_after_commit.allow, push_after_commit.rule))

    def test_startup_dirty_path_requires_explicit_manifest_adoption(self):
        unadopted = self.manifest_state(
            delivery_files=("src/existing.cpp",),
            initial_dirty=("src/existing.cpp",),
        )
        adopted = self.manifest_state(
            delivery_files=("src/existing.cpp",),
            initial_dirty=("src/existing.cpp",),
            decisions=(("delivery.adopted_dirty", "src/existing.cpp"),),
        )
        context_snapshot = self.manifest_state(
            delivery_files=("src/existing.cpp",),
            decisions=(("delivery.adopted_dirty", "src/existing.cpp"),),
        )

        blocked = self.bash(unadopted, "git add src/existing.cpp")
        allowed = self.bash(adopted, "git add src/existing.cpp")
        context_allowed = self.bash(
            context_snapshot,
            "git add src/existing.cpp",
            initial_dirty=(("src/existing.cpp", "startup-fingerprint"),),
        )

        self.assertEqual((False, "git_staging"), (
            blocked.allow, blocked.rule))
        self.assertTrue(allowed.allow)
        self.assertTrue(context_allowed.allow)

    def test_recursive_delete_blocks_outside_and_allows_task_owned_temp(self):
        state = self.manifest_state()
        facts = {"task_owned_temp_dir": "/repo/.tmp/task-7"}

        outside = self.bash(state, "rm -rf build", **facts)
        inside = self.bash(state, "rm -rf /repo/.tmp/task-7", **facts)
        displayed = self.bash(state, "echo rm -rf build", **facts)

        self.assertEqual((False, "filesystem"), (
            outside.allow, outside.rule))
        self.assertTrue(inside.allow)
        self.assertTrue(displayed.allow)

    def test_destructive_recognition_precedes_read_only_fail_open(self):
        state = self.manifest_state()

        destructive = self.bash(state, "git reset --hard HEAD")
        read_only = self.bash(state, "git status --definitely-not-an-option")

        self.assertEqual((False, "git_destructive"), (
            destructive.allow, destructive.rule))
        self.assertTrue(read_only.allow)

    def test_destructive_git_uses_actual_execution_positions(self):
        state = self.manifest_state()
        cases = (
            ("git reset --hard HEAD", False),
            ("git status && git reset --hard HEAD", False),
            ("sh -c 'git reset --hard HEAD'", False),
            ("sudo -u root git reset --hard HEAD", False),
            ("pwsh -NoProfile -Command git reset --hard HEAD", False),
            ("cmd.exe /d /c git reset --hard HEAD", False),
            ("git clean -fd", False),
            ("git checkout -f main", False),
            ("echo git reset --hard HEAD", True),
            ("printf 'git reset --hard HEAD'", True),
            ("git status && echo git reset --hard HEAD", True),
            ("bash -n -c 'git reset --hard HEAD'", True),
            ("bash --help -c 'git reset --hard HEAD'", True),
        )
        for command, expected_allow in cases:
            with self.subTest(command=command):
                decision = self.bash(state, command)
                self.assertIs(expected_allow, decision.allow)
                if not expected_allow:
                    self.assertEqual("git_destructive", decision.rule)

    def test_powershell_recursive_delete_is_a_filesystem_risk(self):
        decision = self.bash(
            self.manifest_state(),
            "pwsh -Command Remove-Item -Recurse src",
        )

        self.assertEqual(
            (False, "filesystem"),
            (decision.allow, decision.rule),
        )

    def test_actual_substitution_positions_drive_destructive_git_gate(self):
        state = self.manifest_state()
        cases = (
            ('echo "$(git reset --hard HEAD)"', False),
            ("echo `git clean -dfx`", False),
            ("echo '$(git reset --hard HEAD)'", True),
            ('echo "\\$(git reset --hard HEAD)"', True),
            ("bash -n -c 'echo \"$(git reset --hard HEAD)\"'", True),
        )
        for command, expected_allow in cases:
            with self.subTest(command=command):
                decision = self.bash(state, command)
                self.assertIs(expected_allow, decision.allow)
                if not expected_allow:
                    self.assertEqual("git_destructive", decision.rule)

    def test_high_confidence_wrappers_and_inline_aliases_are_opaque_delivery(self):
        state = self.manifest_state()
        cases = (
            (
                'python -c "import subprocess; '
                "subprocess.run(['git','add','src/a.cpp'])\"",
                "git_staging",
            ),
            (
                'python -c "import subprocess; '
                "subprocess.run(['git','commit','-m','wrapped'])\"",
                "git_commit",
            ),
            (
                'python -c "import os; '
                "os.system('git push origin HEAD')\"",
                "git_publish",
            ),
            (
                "git -c alias.ship='!git push origin HEAD' ship",
                "git_publish",
            ),
        )
        for command, expected_rule in cases:
            with self.subTest(command=command):
                decision = self.bash(
                    state,
                    command,
                    staged_files=("src/a.cpp", "tests/a_test.cpp"),
                    commit_files=("src/a.cpp", "tests/a_test.cpp"),
                )
                self.assertEqual(
                    (False, expected_rule),
                    (decision.allow, decision.rule),
                )

    def test_print_and_read_only_alias_text_remain_fail_open(self):
        state = self.manifest_state()
        commands = (
            'python -c "print(\'git push origin HEAD\')"',
            "git -c alias.lg='log --oneline' lg",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(self.bash(state, command).allow)

    def test_hidden_repository_or_global_git_aliases_fail_closed(self):
        state = self.manifest_state()

        hidden = self.bash(state, "git ship")
        known = self.bash(state, "git status --short")

        self.assertEqual((False, "git_alias"), (hidden.allow, hidden.rule))
        self.assertTrue(known.allow)


class PublicValueTests(unittest.TestCase):
    def test_guard_package_exports_the_immutable_public_values(self):
        from mae_flow_core import guard

        state = _state()
        context = guard.SafetyContext(state, "/repo")
        decision = guard.SafetyDecision(True)

        self.assertIsInstance(context, SafetyContext)
        self.assertIsInstance(decision, SafetyDecision)
        with self.assertRaises((AttributeError, TypeError)):
            decision.allow = False


if __name__ == "__main__":
    unittest.main()
