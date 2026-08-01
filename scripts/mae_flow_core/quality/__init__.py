"""Pure quality-contract primitives."""

from .codecheck_advisory import (
    CodeCheckDisposition,
    CodeCheckTarget,
    build_codecheck_target,
    record_dispositions,
    render_codecheck_request,
)

__all__ = [
    "CodeCheckDisposition",
    "CodeCheckTarget",
    "build_codecheck_target",
    "record_dispositions",
    "render_codecheck_request",
]
