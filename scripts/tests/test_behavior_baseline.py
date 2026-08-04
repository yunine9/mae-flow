#!/usr/bin/env python3
"""Relevant-only domain documentation selection."""

import importlib
import importlib.util
import os
import sys
import tempfile
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)


class BehaviorBaselineTests(unittest.TestCase):
    def _module(self):
        name = "mae_flow_core.orchestration.behavior_baseline"
        self.assertIsNotNone(importlib.util.find_spec(name))
        return importlib.import_module(name)

    def test_only_relevant_indexed_domain_documents_are_loaded(self):
        module = self._module()
        with tempfile.TemporaryDirectory() as root:
            specs = os.path.join(root, "docs", "specs")
            os.makedirs(specs)
            self._write(os.path.join(specs, "index.md"), """
| 领域 | 关键词 | 文档 |
| --- | --- | --- |
| radio-access | NRPRACH, SUL, PRACH | docs/specs/radio-access.md |
| billing | invoice, account | docs/specs/billing.md |
""")
            self._write(os.path.join(specs, "radio-access.md"), "radio truth")
            self._write(os.path.join(specs, "billing.md"), "billing truth")
            context = module.load_relevant_domain_context(
                root, ("NRPRACH支持SUL模式",))
            self.assertEqual(("docs/specs/radio-access.md",), tuple(
                document.path for document in context.documents))
            self.assertEqual("radio truth", context.documents[0].content)

    @staticmethod
    def _write(path, content):
        with open(path, "w", encoding="utf-8") as stream:
            stream.write(content)


if __name__ == "__main__":
    unittest.main()
