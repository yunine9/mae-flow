#!/usr/bin/env python3
"""Protocol adapter tests kept at the Hook process boundary."""

import importlib.util
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
HOOK = os.path.join(ROOT, "hooks", "dispatch.py")
HOOKS_CONFIG = os.path.join(ROOT, "hooks", "hooks.json")
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.application.hooks.models import HookResponse  # noqa: E402
from mae_flow_core.orchestration import (  # noqa: E402
    CommitPace,
    DeliveryPath,
    FlowState,
    Phase,
)


def load_dispatch():
    name = "mae_flow_hook_protocol_test"
    spec = importlib.util.spec_from_file_location(name, HOOK)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class HookProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dispatch = load_dispatch()

    def test_production_registration_preserves_the_codeagent_host_events(self):
        with open(HOOKS_CONFIG, encoding="utf-8") as stream:
            raw = stream.read()
        config = json.loads(raw)["hooks"]

        self.assertEqual(
            {
                "SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
                "SubagentStop", "Stop",
            },
            set(config),
        )

    def test_registration_preserves_codeagent_safety_boundaries(self):
        with open(HOOKS_CONFIG, encoding="utf-8") as stream:
            config = json.load(stream)["hooks"]

        pretool = set(config["PreToolUse"][0]["matcher"].split("|"))
        posttool = set(config["PostToolUse"][0]["matcher"].split("|"))
        self.assertEqual(
            {
                "Edit", "Write", "MultiEdit", "Bash", "WriteStdin",
                "AskUserQuestion", "Task",
            },
            pretool,
        )
        self.assertEqual(
            {"Write", "Edit", "MultiEdit", "AskUserQuestion", "Bash"},
            posttool,
        )

    def test_sessionstart_installs_project_local_launcher_from_hook_root(self):
        with tempfile.TemporaryDirectory() as root:
            plugin = os.path.join(root, "plugin root")
            project = os.path.join(root, "project")
            os.makedirs(os.path.join(plugin, "scripts"))
            os.makedirs(project)
            with open(os.path.join(plugin, "scripts", "mae-flow.py"), "w",
                      encoding="utf-8") as stream:
                stream.write(
                    "import sys\nprint('launcher:' + ','.join(sys.argv[1:]))\n")
            previous = os.getcwd()
            try:
                os.chdir(project)
                with mock.patch.dict(
                        os.environ,
                        {"CODEAGENT3_PLUGIN_ROOT": plugin}, clear=False):
                    self.dispatch._install_project_launcher()
            finally:
                os.chdir(previous)
            launcher = os.path.join(
                project, ".mae-flow-work", "bin", "mae-flow.py")
            with open(launcher, encoding="utf-8") as stream:
                source = stream.read()
            self.assertIn("subprocess.call", source)
            self.assertIn("plugin root/scripts/mae-flow.py", source)
            executed = subprocess.run(
                [sys.executable, launcher, "current"], cwd=project,
                text=True, encoding="utf-8", capture_output=True, check=True)
            self.assertEqual("launcher:current", executed.stdout.strip())

    def test_userprompt_refreshes_project_launcher_after_plugin_update(self):
        with tempfile.TemporaryDirectory() as root:
            plugin = os.path.join(root, "updated plugin")
            project = os.path.join(root, "project")
            os.makedirs(os.path.join(plugin, "scripts"))
            os.makedirs(project)
            with open(os.path.join(plugin, "scripts", "mae-flow.py"), "w",
                      encoding="utf-8") as stream:
                stream.write("print('updated-plugin')\n")
            payload = {"cwd": project, "prompt": "继续"}
            previous = os.getcwd()
            try:
                with mock.patch.dict(
                        os.environ,
                        {"CODEAGENT3_PLUGIN_ROOT": plugin}, clear=False):
                    with mock.patch.object(
                            self.dispatch, "read_input", return_value=payload):
                        with mock.patch.object(self.dispatch, "_arm_watchdog"):
                            with self.assertRaises(SystemExit) as caught:
                                self.dispatch.main(
                                    ["dispatch.py", "userprompt"])
            finally:
                os.chdir(previous)
            self.assertEqual(0, caught.exception.code)
            launcher = os.path.join(
                project, ".mae-flow-work", "bin", "mae-flow.py")
            executed = subprocess.run(
                [sys.executable, launcher], cwd=project,
                text=True, encoding="utf-8", capture_output=True, check=True)
            self.assertEqual("updated-plugin", executed.stdout.strip())

    def test_real_registration_dispatch_blocks_cross_platform_writers(self):
        with open(HOOKS_CONFIG, encoding="utf-8") as stream:
            config = json.load(stream)["hooks"]
        matcher = set(config["PreToolUse"][0]["matcher"].split("|"))
        self.assertIn("Bash", matcher)
        self.assertIn("Edit", matcher)

        with tempfile.TemporaryDirectory() as root:
            os.mkdir(os.path.join(root, ".git"))
            state = FlowState(
                ticket="REQ-HOOK",
                path=DeliveryPath.FULL,
                phase=Phase.STORY,
                commit_pace=CommitPace.CONTINUOUS,
            )
            with open(
                    os.path.join(root, ".mae-flow.json"),
                    "w", encoding="utf-8") as stream:
                json.dump(state.to_dict(), stream, ensure_ascii=False)
            payloads = (
                {
                    "cwd": root,
                    "tool_name": "Bash",
                    "tool_input": {"command": "printf x > src/main.py"},
                },
                {
                    "cwd": root,
                    "tool_name": "Bash",
                    "tool_input": {"command": (
                        "pwsh -Command Set-Content -Path src/main.py -Value x"
                    )},
                },
                {
                    "cwd": root,
                    "tool_name": "apply_patch",
                    "tool_input": {"command": (
                        "*** Begin Patch\n"
                        "*** Add File: src/main.py\n"
                        "+value = 1\n"
                        "*** End Patch\n"
                    )},
                },
                {
                    "cwd": root,
                    "tool_name": "Bash",
                    "tool_input": {"command": "bash"},
                },
                {
                    "cwd": root,
                    "tool_name": "WriteStdin",
                    "tool_input": {"session_id": "active-shell", "chars": "x"},
                },
            )

            previous = os.getcwd()
            try:
                for payload in payloads:
                    with self.subTest(payload=payload):
                        with mock.patch.object(
                                self.dispatch, "read_input",
                                return_value=payload):
                            with mock.patch.object(
                                    self.dispatch, "_arm_watchdog"):
                                stderr = StringIO()
                                with redirect_stderr(stderr):
                                    with self.assertRaises(SystemExit) as caught:
                                        self.dispatch.main(
                                            ["dispatch.py", "PreToolUse"])
                        self.assertEqual(2, caught.exception.code, stderr.getvalue())
            finally:
                os.chdir(previous)

    def test_decodes_utf8_bom_and_gb18030_without_replacement(self):
        payload = {"prompt": "中文确认", "tool_name": "Edit"}
        encoded = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(
            payload,
            self.dispatch._decode_hook_json(
                b"\xef\xbb\xbf" + encoded.encode("utf-8")),
        )
        with mock.patch.object(
                self.dispatch.locale,
                "getpreferredencoding",
                return_value="ascii"):
            self.assertEqual(
                payload,
                self.dispatch._decode_hook_json(encoded.encode("gb18030")),
            )

    def test_invalid_payload_is_rejected_by_decoder(self):
        with self.assertRaises(ValueError):
            self.dispatch._decode_hook_json(b"\xff\xfe\x00not-json")

    def test_unexpected_top_level_exception_fails_open(self):
        with mock.patch.object(
                self.dispatch, "read_input", side_effect=RuntimeError("boom")):
            with mock.patch.object(self.dispatch, "_arm_watchdog"):
                with self.assertRaises(SystemExit) as caught:
                    self.dispatch.main()
        self.assertEqual(0, caught.exception.code)

    def test_main_delegates_decoded_event_to_the_lean_adapter(self):
        response = HookResponse(
            exit_code=2, stdout="lean stdout\n", stderr="lean stderr\n")
        payload = {"cwd": ROOT, "tool_name": "Edit"}

        class ExactAdapter:
            def handle(self, event, value):
                if event != "PreToolUse" or value != payload:
                    raise AssertionError("wrong lean adapter protocol call")
                return response

        adapter = ExactAdapter()

        with mock.patch.object(self.dispatch, "read_input", return_value=payload):
            with mock.patch.object(self.dispatch, "_arm_watchdog"):
                with mock.patch.object(
                        self.dispatch, "_lean_adapter", return_value=adapter):
                    stdout = StringIO()
                    stderr = StringIO()
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        with self.assertRaises(SystemExit) as caught:
                            self.dispatch.main(["dispatch.py", "PreToolUse"])

        self.assertEqual(2, caught.exception.code)
        self.assertEqual("lean stdout\n", stdout.getvalue())
        self.assertEqual("lean stderr\n", stderr.getvalue())

    def test_legacy_stop_events_succeed_without_touching_state(self):
        with tempfile.TemporaryDirectory() as root:
            state_path = os.path.join(root, ".mae-flow.json")
            original = b"state-must-remain-byte-identical"
            with open(state_path, "wb") as stream:
                stream.write(original)
            before = set(os.listdir(root))

            with mock.patch.object(self.dispatch.os, "getcwd", return_value=root):
                adapter = self.dispatch._lean_adapter()
            for event in ("Stop", "SubagentStop"):
                with self.subTest(event=event):
                    response = adapter.handle(event, {"tool_name": "Bash"})
                    self.assertEqual(HookResponse(), response)
                    with open(state_path, "rb") as stream:
                        self.assertEqual(original, stream.read())
                    self.assertEqual(before, set(os.listdir(root)))

    def test_legacy_stop_main_exits_before_all_process_boundary_access(self):
        for event in ("Stop", "SubagentStop", "subagent_stop"):
            with self.subTest(event=event):
                accessed = []
                with mock.patch.object(
                        self.dispatch, "_arm_watchdog",
                        side_effect=lambda: accessed.append("watchdog")):
                    with mock.patch.object(
                            self.dispatch, "_log",
                            side_effect=lambda unused: accessed.append("log")):
                        with mock.patch.object(
                                self.dispatch, "read_input",
                                side_effect=lambda: accessed.append("stdin")):
                            with mock.patch.object(
                                    self.dispatch, "_lean_adapter",
                                    side_effect=lambda: accessed.append(
                                        "adapter")):
                                with self.assertRaises(SystemExit) as caught:
                                    self.dispatch.main(["dispatch.py", event])
                self.assertEqual(0, caught.exception.code)
                self.assertEqual([], accessed)

    def test_staged_push_collects_exact_files_from_every_published_commit(self):
        text_facts = {
            ("rev-parse", "--verify", "HEAD^{commit}"): "cp-2-head",
            ("rev-parse", "--verify",
             "refs/remotes/origin/main^{commit}"): "remote-base",
        }

        def git_text(unused_root, arguments):
            return text_facts.get(tuple(arguments), "")

        def git_paths(unused_root, arguments):
            self.assertEqual(
                ("log", "--format=", "--name-only", "-z",
                 "remote-base..cp-2-head", "--"),
                tuple(arguments),
            )
            return ("src/cp1.py", "src/cp2.py", "src/cp1.py")

        payload = {
            "tool_name": "Bash",
            "tool_input": {
                "command": "git push origin HEAD:refs/heads/main",
            },
        }
        self.assertEqual(
            ("src/cp1.py", "src/cp2.py"),
            self.dispatch._push_commit_files(
                ROOT, payload, git_text=git_text, git_paths=git_paths),
        )

    def test_push_range_includes_unrelated_commits_ahead_of_remote(self):
        def git_text(unused_root, arguments):
            values = {
                ("rev-parse", "--verify", "HEAD^{commit}"): "flow-head",
                ("rev-parse", "--verify",
                 "refs/remotes/origin/main^{commit}"): "remote-base",
            }
            return values.get(tuple(arguments), "")

        def git_paths(unused_root, unused_arguments):
            return ("unrelated/private.txt", "src/delivery.py")

        payload = {
            "tool_name": "Bash",
            "tool_input": {
                "command": "git push origin HEAD:refs/heads/main",
            },
        }
        self.assertEqual(
            ("unrelated/private.txt", "src/delivery.py"),
            self.dispatch._push_commit_files(
                ROOT, payload, git_text=git_text, git_paths=git_paths),
        )

    def test_push_without_refspec_uses_configured_push_tracking_range(self):
        def git_text(unused_root, arguments):
            values = {
                ("rev-parse", "--abbrev-ref", "--symbolic-full-name",
                 "@{push}"): "origin/main",
                ("rev-parse", "--verify", "HEAD^{commit}"): "local-head",
                ("rev-parse", "--verify",
                 "refs/remotes/origin/main^{commit}"): "remote-head",
            }
            return values.get(tuple(arguments), "")

        def git_paths(unused_root, arguments):
            self.assertEqual(
                ("log", "--format=", "--name-only", "-z",
                 "remote-head..local-head", "--"),
                tuple(arguments),
            )
            return ("src/upstream.py",)

        self.assertEqual(
            ("src/upstream.py",),
            self.dispatch._push_commit_files(
                ROOT,
                {"tool_name": "Bash", "tool_input": {"command": "git push"}},
                git_text=git_text,
                git_paths=git_paths,
            ),
        )

    def test_ambiguous_push_refspecs_provide_no_authorization_facts(self):
        payloads = (
            {"tool_name": "Bash", "tool_input": {
                "command": "git push --all origin"}},
            {"tool_name": "Bash", "tool_input": {
                "command": "git push origin main release"}},
            {"tool_name": "Bash", "tool_input": {
                "command": "git push origin :main"}},
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                self.assertEqual(
                    (),
                    self.dispatch._push_commit_files(
                        ROOT, payload,
                        git_text=lambda unused_root, unused_args: "",
                        git_paths=lambda unused_root, unused_args: (),
                    ),
                )

    def test_repository_context_changing_pushes_receive_no_root_facts(self):
        commands = (
            "git push --repo=/tmp/other origin HEAD:refs/heads/main",
            "git -C /tmp/other push origin HEAD:refs/heads/main",
            "git --git-dir=/tmp/other/.git push origin HEAD:refs/heads/main",
            "git --work-tree=/tmp/other push origin HEAD:refs/heads/main",
            "git -c remote.origin.url=/tmp/other push origin "
            "HEAD:refs/heads/main",
            "GIT_DIR=/tmp/other/.git git push origin HEAD:refs/heads/main",
        )

        def git_text(unused_root, arguments):
            values = {
                ("rev-parse", "--verify", "HEAD^{commit}"): "root-head",
                ("rev-parse", "--verify",
                 "refs/remotes/origin/main^{commit}"): "root-remote",
            }
            return values.get(tuple(arguments), "")

        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(
                    (),
                    self.dispatch._push_commit_files(
                        ROOT,
                        {"tool_name": "Bash", "tool_input": {
                            "command": command,
                        }},
                        git_text=git_text,
                        git_paths=lambda unused_root, unused_args: (
                            "root-authorized.py",),
                    ),
                )

    def test_prior_shell_context_and_remote_config_receive_no_root_facts(self):
        commands = (
            "cd /tmp/other && git push origin HEAD:refs/heads/main",
            "export GIT_DIR=/tmp/other/.git; "
            "git push origin HEAD:refs/heads/main",
            "export GIT_WORK_TREE=/tmp/other; "
            "git push origin HEAD:refs/heads/main",
            "export GIT_CONFIG_COUNT=1; "
            "export GIT_CONFIG_KEY_0=remote.origin.pushurl; "
            "export GIT_CONFIG_VALUE_0=/tmp/other; "
            "git push origin HEAD:refs/heads/main",
            "GIT_DIR=/tmp/other/.git "
            "git push origin HEAD:refs/heads/main",
            "env GIT_DIR=/tmp/other/.git "
            "git push origin HEAD:refs/heads/main",
            "git -c remote.origin.pushurl=/tmp/other "
            "push origin HEAD:refs/heads/main",
            "git -c remote.pushDefault=other "
            "push origin HEAD:refs/heads/main",
            "git -c branch.main.remote=other "
            "push origin HEAD:refs/heads/main",
            "git -c branch.main.pushRemote=other "
            "push origin HEAD:refs/heads/main",
            "git -c branch.release.v2.pushRemote=other "
            "push origin HEAD:refs/heads/main",
            "git -c remote.release.mirror.pushurl=/tmp/other "
            "push origin HEAD:refs/heads/main",
            "git -c url./tmp/other.pushInsteadOf=origin "
            "push origin HEAD:refs/heads/main",
            "git -c url./tmp/other.insteadOf=origin "
            "push origin HEAD:refs/heads/main",
            "git -c include.path=/tmp/remote-config "
            "push origin HEAD:refs/heads/main",
            "git -c includeIf.gitdir:/tmp/.path=/tmp/remote-config "
            "push origin HEAD:refs/heads/main",
        )

        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(
                    (),
                    self.dispatch._push_commit_files(
                        ROOT,
                        {"tool_name": "Bash", "tool_input": {
                            "command": command,
                        }},
                        git_text=self._root_push_text,
                        git_paths=lambda unused_root, unused_args: (
                            "root-authorized.py",),
                    ),
                )

    def test_conditional_context_restore_fails_closed_before_fact_reads(self):
        commands = (
            "cd /tmp/other || cd %s; "
            "git push origin HEAD:refs/heads/main" % ROOT,
            "export GIT_DIR=/tmp/other/.git || unset GIT_DIR; "
            "git push origin HEAD:refs/heads/main",
        )

        for command in commands:
            with self.subTest(command=command):
                reads = []

                def git_text(unused_root, arguments):
                    reads.append(("text", tuple(arguments)))
                    return self._root_push_text(unused_root, arguments)

                def git_paths(unused_root, arguments):
                    reads.append(("paths", tuple(arguments)))
                    return ("root-authorized.py",)

                self.assertEqual(
                    (),
                    self.dispatch._push_commit_files(
                        ROOT,
                        {"tool_name": "Bash", "tool_input": {
                            "command": command,
                        }},
                        git_text=git_text,
                        git_paths=git_paths,
                    ),
                )
                self.assertEqual([], reads)

    def test_persistent_shell_context_operations_fail_before_fact_reads(self):
        commands = (
            "pushd /tmp/other; git push origin HEAD:refs/heads/main",
            "popd; git push origin HEAD:refs/heads/main",
            "eval 'cd /tmp/other'; "
            "git push origin HEAD:refs/heads/main",
            "source /tmp/repository-context.sh; "
            "git push origin HEAD:refs/heads/main",
            ". /tmp/repository-context.sh; "
            "git push origin HEAD:refs/heads/main",
            "builtin cd /tmp/other; "
            "git push origin HEAD:refs/heads/main",
            "builtin -- cd /tmp/other; "
            "git push origin HEAD:refs/heads/main",
            "command cd /tmp/other; "
            "git push origin HEAD:refs/heads/main",
            "command -p cd /tmp/other; "
            "git push origin HEAD:refs/heads/main",
            "shopt -s lastpipe; printf value | "
            "export GIT_DIR=/tmp/other/.git; "
            "git push origin HEAD:refs/heads/main",
            "trap 'export GIT_DIR=/tmp/other/.git' DEBUG; "
            "git push origin HEAD:refs/heads/main",
        )

        for command in commands:
            with self.subTest(command=command):
                reads = []

                def git_text(unused_root, arguments):
                    reads.append(("text", tuple(arguments)))
                    return self._root_push_text(unused_root, arguments)

                def git_paths(unused_root, arguments):
                    reads.append(("paths", tuple(arguments)))
                    return ("root-authorized.py",)

                self.assertEqual(
                    (),
                    self.dispatch._push_commit_files(
                        ROOT,
                        {"tool_name": "Bash", "tool_input": {
                            "command": command,
                        }},
                        git_text=git_text,
                        git_paths=git_paths,
                    ),
                )
                self.assertEqual([], reads)

    def test_subshell_and_pipeline_context_does_not_pollute_root_push(self):
        commands = (
            "(cd /tmp/other); "
            "git push origin HEAD:refs/heads/main",
            "(pushd /tmp/other); "
            "git push origin HEAD:refs/heads/main",
            "cd /tmp/other | cat; "
            "git push origin HEAD:refs/heads/main",
            "export GIT_DIR=/tmp/other/.git | cat; "
            "git push origin HEAD:refs/heads/main",
            "pushd /tmp/other | cat; "
            "git push origin HEAD:refs/heads/main",
            "echo ready | git push origin HEAD:refs/heads/main",
        )

        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(
                    ("src/root.py",),
                    self.dispatch._push_commit_files(
                        ROOT,
                        {"tool_name": "Bash", "tool_input": {
                            "command": command,
                        }},
                        git_text=self._root_push_text,
                        git_paths=lambda unused_root, unused_args: (
                            "src/root.py",),
                    ),
                )

    def test_push_inside_unsafe_subshell_fails_before_fact_reads(self):
        commands = (
            "(cd /tmp/other; "
            "git push origin HEAD:refs/heads/main)",
            "(pushd /tmp/other; "
            "git push origin HEAD:refs/heads/main)",
            "(eval 'export GIT_DIR=/tmp/other/.git'; "
            "git push origin HEAD:refs/heads/main)",
        )

        for command in commands:
            with self.subTest(command=command):
                reads = []

                def git_text(unused_root, arguments):
                    reads.append(("text", tuple(arguments)))
                    return self._root_push_text(unused_root, arguments)

                def git_paths(unused_root, arguments):
                    reads.append(("paths", tuple(arguments)))
                    return ("root-authorized.py",)

                self.assertEqual(
                    (),
                    self.dispatch._push_commit_files(
                        ROOT,
                        {"tool_name": "Bash", "tool_input": {
                            "command": command,
                        }},
                        git_text=git_text,
                        git_paths=git_paths,
                    ),
                )
                self.assertEqual([], reads)

    def test_redirection_keeps_repository_context_changes_in_parent_scope(self):
        commands = (
            "cd /tmp/other &>/dev/null; "
            "git push origin HEAD:refs/heads/main",
            "export GIT_DIR=/tmp/other/.git &>/dev/null; "
            "git push origin HEAD:refs/heads/main",
            "cd /tmp/other 2>&1; "
            "git push origin HEAD:refs/heads/main",
            "cd /tmp/other &&>/dev/null; "
            "git push origin HEAD:refs/heads/main",
        )

        for command in commands:
            with self.subTest(command=command):
                reads = []

                def git_text(unused_root, arguments):
                    reads.append(("text", tuple(arguments)))
                    return self._root_push_text(unused_root, arguments)

                def git_paths(unused_root, arguments):
                    reads.append(("paths", tuple(arguments)))
                    return ("root-authorized.py",)

                self.assertEqual(
                    (),
                    self.dispatch._push_commit_files(
                        ROOT,
                        {"tool_name": "Bash", "tool_input": {
                            "command": command,
                        }},
                        git_text=git_text,
                        git_paths=git_paths,
                    ),
                )
                self.assertEqual([], reads)

    def test_unsupported_compound_syntax_fails_before_fact_reads(self):
        commands = (
            "{ cd /tmp/other; "
            "git push origin HEAD:refs/heads/main; }",
            "if true; then cd /tmp/other; fi; "
            "git push origin HEAD:refs/heads/main",
            "for path in /tmp/other; do cd \"$path\"; done; "
            "git push origin HEAD:refs/heads/main",
            "select path in /tmp/other; do cd \"$path\"; done; "
            "git push origin HEAD:refs/heads/main",
            "while false; do cd /tmp/other; done; "
            "git push origin HEAD:refs/heads/main",
            "until true; do cd /tmp/other; done; "
            "git push origin HEAD:refs/heads/main",
            "case value in value) cd /tmp/other;; esac; "
            "git push origin HEAD:refs/heads/main",
            "function change_root { cd /tmp/other; }; change_root; "
            "git push origin HEAD:refs/heads/main",
            "time cd /tmp/other; "
            "git push origin HEAD:refs/heads/main",
            "coproc cd /tmp/other; "
            "git push origin HEAD:refs/heads/main",
            "(( value = 1 )); "
            "git push origin HEAD:refs/heads/main",
            "[[ -d /tmp/other ]] && cd /tmp/other; "
            "git push origin HEAD:refs/heads/main",
        )

        for command in commands:
            with self.subTest(command=command):
                reads = []

                def git_text(unused_root, arguments):
                    reads.append(("text", tuple(arguments)))
                    return self._root_push_text(unused_root, arguments)

                def git_paths(unused_root, arguments):
                    reads.append(("paths", tuple(arguments)))
                    return ("root-authorized.py",)

                self.assertEqual(
                    (),
                    self.dispatch._push_commit_files(
                        ROOT,
                        {"tool_name": "Bash", "tool_input": {
                            "command": command,
                        }},
                        git_text=git_text,
                        git_paths=git_paths,
                    ),
                )
                self.assertEqual([], reads)

    def test_opaque_or_malformed_redirection_fails_before_fact_reads(self):
        commands = (
            "cd /tmp/other >; "
            "git push origin HEAD:refs/heads/main",
            "cd /tmp/other 2>&; "
            "git push origin HEAD:refs/heads/main",
            "cd /tmp/other ><context.log; "
            "git push origin HEAD:refs/heads/main",
            "cd /tmp/other <<EOF\nEOF\n"
            "git push origin HEAD:refs/heads/main",
            "cd /tmp/other <<<context; "
            "git push origin HEAD:refs/heads/main",
            "printf ready <(cd /tmp/other); "
            "git push origin HEAD:refs/heads/main",
            "printf ready >(cd /tmp/other); "
            "git push origin HEAD:refs/heads/main",
        )

        for command in commands:
            with self.subTest(command=command):
                reads = []

                def git_text(unused_root, arguments):
                    reads.append(("text", tuple(arguments)))
                    return self._root_push_text(unused_root, arguments)

                def git_paths(unused_root, arguments):
                    reads.append(("paths", tuple(arguments)))
                    return ("root-authorized.py",)

                self.assertEqual(
                    (),
                    self.dispatch._push_commit_files(
                        ROOT,
                        {"tool_name": "Bash", "tool_input": {
                            "command": command,
                        }},
                        git_text=git_text,
                        git_paths=git_paths,
                    ),
                )
                self.assertEqual([], reads)

    def test_known_simple_redirection_keeps_exact_root_push_facts(self):
        commands = (
            "printf ready >/dev/null; "
            "git push origin HEAD:refs/heads/main",
            "printf ready 2>&1; "
            "git push origin HEAD:refs/heads/main",
            "git push origin HEAD:refs/heads/main >/dev/null",
            "git push origin HEAD:refs/heads/main 2>&1",
            "git push origin HEAD:refs/heads/main &>/dev/null",
            "git push origin HEAD:refs/heads/main >&push.log",
            "</dev/null git push origin HEAD:refs/heads/main 2>/dev/null",
        )

        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(
                    ("src/root.py",),
                    self.dispatch._push_commit_files(
                        ROOT,
                        {"tool_name": "Bash", "tool_input": {
                            "command": command,
                        }},
                        git_text=self._root_push_text,
                        git_paths=lambda unused_root, unused_args: (
                            "src/root.py",),
                    ),
                )

    def test_spaced_numeric_argv_is_not_treated_as_an_io_number(self):
        def git_text(unused_root, arguments):
            values = {
                ("rev-parse", "--verify", "2^{commit}"): "numeric-head",
                ("rev-parse", "--verify",
                 "refs/remotes/origin/2^{commit}"): "numeric-remote",
            }
            return values.get(tuple(arguments), "")

        def git_paths(unused_root, arguments):
            self.assertEqual(
                ("log", "--format=", "--name-only", "-z",
                 "numeric-remote..numeric-head", "--"),
                tuple(arguments),
            )
            return ("src/numeric-ref.py",)

        self.assertEqual(
            ("src/numeric-ref.py",),
            self.dispatch._push_commit_files(
                ROOT,
                {"tool_name": "Bash", "tool_input": {
                    "command": "git push origin 2 >/dev/null",
                }},
                git_text=git_text,
                git_paths=git_paths,
            ),
        )

    def test_reserved_words_as_ordinary_argv_keep_exact_push_facts(self):
        command = (
            "printf '%s' { } if then elif else fi for select while until "
            "do done case in esac function time coproc '[[']; "
            "git push origin HEAD:refs/heads/main"
        )

        self.assertEqual(
            ("src/root.py",),
            self.dispatch._push_commit_files(
                ROOT,
                {"tool_name": "Bash", "tool_input": {"command": command}},
                git_text=self._root_push_text,
                git_paths=lambda unused_root, unused_args: ("src/root.py",),
            ),
        )

    def test_push_ref_selecting_config_fails_before_fact_reads(self):
        commands = (
            "git -c remote.origin.push=refs/heads/main:refs/heads/release "
            "push origin HEAD:refs/heads/main",
            "git -c remote.origin.mirror=true "
            "push origin HEAD:refs/heads/main",
            "git -c branch.main.merge=refs/heads/release "
            "push origin HEAD:refs/heads/main",
            "git -c push.default=matching "
            "push origin HEAD:refs/heads/main",
            "git -c push.followTags=true "
            "push origin HEAD:refs/heads/main",
            "git -c push.recurseSubmodules=on-demand "
            "push origin HEAD:refs/heads/main",
            "git -c remote.origin.futurePushRefs=release "
            "push origin HEAD:refs/heads/main",
            "git -c branch.main.futurePushRefs=release "
            "push origin HEAD:refs/heads/main",
            "git -c push.futureRefSelection=release "
            "push origin HEAD:refs/heads/main",
            "git -c \"remote.release.v2.push="
            "refs/heads/main:refs/heads/release\" "
            "push origin HEAD:refs/heads/main",
            "git --config-env=remote.origin.push=MAE_PUSH_REFS "
            "push origin HEAD:refs/heads/main",
        )

        for command in commands:
            with self.subTest(command=command):
                reads = []

                def git_text(unused_root, arguments):
                    reads.append(("text", tuple(arguments)))
                    return self._root_push_text(unused_root, arguments)

                def git_paths(unused_root, arguments):
                    reads.append(("paths", tuple(arguments)))
                    return ("root-authorized.py",)

                self.assertEqual(
                    (),
                    self.dispatch._push_commit_files(
                        ROOT,
                        {"tool_name": "Bash", "tool_input": {
                            "command": command,
                        }},
                        git_text=git_text,
                        git_paths=git_paths,
                    ),
                )
                self.assertEqual([], reads)

    def test_display_and_transport_config_keeps_exact_push_facts(self):
        commands = (
            "git -c color.ui=false push origin HEAD:refs/heads/main",
            "git -c http.sslVerify=false "
            "push origin HEAD:refs/heads/main",
            "git -c credential.helper= "
            "push origin HEAD:refs/heads/main",
            "git -c core.sshCommand='ssh -i transport-key' "
            "push origin HEAD:refs/heads/main",
            "git -c remote.origin.proxy=http://proxy.invalid "
            "push origin HEAD:refs/heads/main",
            "git -c push.gpgSign=false "
            "push origin HEAD:refs/heads/main",
            "git -c push.negotiate=false "
            "push origin HEAD:refs/heads/main",
        )

        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(
                    ("src/root.py",),
                    self.dispatch._push_commit_files(
                        ROOT,
                        {"tool_name": "Bash", "tool_input": {
                            "command": command,
                        }},
                        git_text=self._root_push_text,
                        git_paths=lambda unused_root, unused_args: (
                            "src/root.py",),
                    ),
                )

    def test_unrelated_control_flow_and_exact_restore_keep_push_facts(self):
        commands = (
            "echo ready && git push origin HEAD:refs/heads/main",
            "printf unavailable || git push origin HEAD:refs/heads/main",
            "(echo ready); git push origin HEAD:refs/heads/main",
            "printf ready | cat; git push origin HEAD:refs/heads/main",
            "FOO=bar; git push origin HEAD:refs/heads/main",
            "export FOO=bar; git push origin HEAD:refs/heads/main",
            "cd /tmp/other; cd '%s'; "
            "git push origin HEAD:refs/heads/main" % ROOT,
            "export GIT_DIR=/tmp/other/.git; unset GIT_DIR; "
            "git push origin HEAD:refs/heads/main",
        )

        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(
                    ("src/root.py",),
                    self.dispatch._push_commit_files(
                        ROOT,
                        {"tool_name": "Bash", "tool_input": {
                            "command": command,
                        }},
                        git_text=self._root_push_text,
                        git_paths=lambda unused_root, unused_args: (
                            "src/root.py",),
                    ),
                )

    def test_quoted_windows_context_fails_before_fact_reads(self):
        commands = (
            '"GIT_DIR=C:\\other repo\\.git" '
            "git push origin HEAD:refs/heads/main",
            'export "GIT_WORK_TREE=C:\\other repo"; '
            "git push origin HEAD:refs/heads/main",
            'set "GIT_DIR=C:\\other repo\\.git" && '
            "git push origin HEAD:refs/heads/main",
            'git -c "remote.origin.pushurl=C:\\other repo" '
            "push origin HEAD:refs/heads/main",
        )

        for command in commands:
            with self.subTest(command=command):
                reads = []

                def git_text(unused_root, arguments):
                    reads.append(("text", tuple(arguments)))
                    return self._root_push_text(unused_root, arguments)

                def git_paths(unused_root, arguments):
                    reads.append(("paths", tuple(arguments)))
                    return ("root-authorized.py",)

                self.assertEqual(
                    (),
                    self.dispatch._push_commit_files(
                        ROOT,
                        {"tool_name": "Bash", "tool_input": {
                            "command": command,
                        }},
                        git_text=git_text,
                        git_paths=git_paths,
                    ),
                )
                self.assertEqual([], reads)

    @staticmethod
    def _root_push_text(unused_root, arguments):
        values = {
            ("rev-parse", "--verify", "HEAD^{commit}"): "root-head",
            ("rev-parse", "--verify",
             "refs/remotes/origin/main^{commit}"): "root-remote",
        }
        return values.get(tuple(arguments), "")

    def test_benign_inline_git_config_keeps_root_push_facts(self):
        self.assertEqual(
            ("src/root.py",),
            self.dispatch._push_commit_files(
                ROOT,
                {"tool_name": "Bash", "tool_input": {
                    "command": (
                        "git -c color.ui=false push origin "
                        "HEAD:refs/heads/main"),
                }},
                git_text=self._root_push_text,
                git_paths=lambda unused_root, unused_args: ("src/root.py",),
            ),
        )


if __name__ == "__main__":
    unittest.main()
