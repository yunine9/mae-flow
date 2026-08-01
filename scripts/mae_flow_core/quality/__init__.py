"""Pure quality-contract primitives."""

from .codecheck_advisory import (
    CodeCheckDisposition,
    CodeCheckTarget,
    build_codecheck_target,
    record_dispositions,
    render_codecheck_request,
)
from .selection import QualityRecommendation, recommend_quality
from .ut_handoff import append_ut_handoff, render_ut_context

__all__ = [
    "CodeCheckDisposition",
    "CodeCheckTarget",
    "QualityRecommendation",
    "append_ut_handoff",
    "build_codecheck_target",
    "recommend_quality",
    "record_dispositions",
    "render_codecheck_request",
    "render_ut_context",
]
