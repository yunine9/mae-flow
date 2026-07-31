#!/usr/bin/env python3
"""Regression coverage for compile waiting instructions and packaged Skill."""

import os
import unittest
import zipfile


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def repository_text(relative):
    with open(os.path.join(ROOT, relative), encoding="utf-8") as stream:
        return stream.read()


class CompileWaitInstructionTests(unittest.TestCase):
    def test_compile_agents_use_one_synchronous_build_action(self):
        for relative in (
                "agents/compile-agent.md",
                "agents/codecheck-fix-agent.md",
                "agents/ut-generator-agent.md"):
            with self.subTest(relative=relative):
                content = repository_text(relative)
                self.assertNotRegex(content, r"sleep\s+(?:120|180|后)")
                self.assertNotIn("长间隔轮询", content)
                self.assertIn("单次同步", content)

    def test_packaged_build_fix_uses_command_return_as_completion(self):
        with zipfile.ZipFile(
                os.path.join(ROOT, "build-fix.skill")) as archive:
            self.assertEqual(6, len(archive.infolist()))
            skill = archive.read("build-fix/SKILL.md").decode("utf-8")
            loop = archive.read(
                "build-fix/references/step2_build_loop.md").decode("utf-8")
        self.assertIn("单次同步", skill)
        self.assertIn('cd "$BUILD_DIR" && mcde build -i', loop)
        self.assertIn("源码和构建输入未变化", loop)
        self.assertIn("属于 FAIL，不是 BLOCKED", loop)
        self.assertIn("Windows Git Bash", loop)
        self.assertNotIn("后台执行+轮询", skill)
        self.assertNotIn("/tmp/build_output.txt", loop)
        self.assertNotRegex(loop, r"mcde build -i[^\n]*&")
        self.assertNotRegex(loop, r"\bsleep\s+\d")


if __name__ == "__main__":
    unittest.main()
