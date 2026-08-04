"""Relevant domain context and durable reconciliation commands."""

from .shared import os, read_text
from .wiring import api
from mae_flow_core.orchestration.behavior_baseline import (
    apply_domain_reconciliation,
    load_relevant_domain_context,
    plan_domain_reconciliation,
)


def cmd_domain_docs(state, args):
    del state
    root = os.getcwd()
    if args.domain_docs_action == "context":
        context = load_relevant_domain_context(root, args.term)
        print("[mae-flow] 相关领域文档: %d" % len(context.documents))
        for document in context.documents:
            print("- " + document.path)
        return context
    if args.domain_docs_action == "show":
        context = load_relevant_domain_context(root, ("",))
        print("[mae-flow] 领域文档索引: " + context.index_path)
        return context
    try:
        candidate = read_text(args.candidate, encoding="utf-8")
        result = plan_domain_reconciliation(root, args.domain, candidate)
        apply_domain_reconciliation(result, args.keyword)
    except (OSError, TypeError, ValueError) as exc:
        api.die("领域文档协调失败: %s" % exc, 2)
    print("[mae-flow] 领域文档 %s: %s" % (result.action, result.path))
    return result
