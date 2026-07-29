"""Pure source/build path classification shared by Mae-Flow adapters."""

import os
import re


SOURCE_EXTENSIONS = (
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx",
    ".inl", ".ipp", ".tpp", ".java", ".kt", ".kts", ".groovy",
    ".scala", ".py", ".pyi", ".go", ".rs", ".cs", ".js", ".jsx",
    ".cjs", ".mjs", ".ts", ".tsx", ".cts", ".mts", ".vue", ".swift",
    ".m", ".mm", ".proto", ".sql", ".s", ".asm", ".cmake", ".gradle",
    ".sln", ".vcxproj", ".props", ".targets", ".sh", ".bash", ".bat",
    ".cmd", ".ps1", ".mk", ".gn", ".gni", ".bzl",
)
SOURCE_FILENAMES = {
    "cmakelists.txt", "makefile", "gnumakefile", "pom.xml",
    "build.gradle", "settings.gradle", "gradle.properties", "package.json",
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "cargo.toml",
    "cargo.lock", "go.mod", "go.sum", "meson.build", "build.ninja",
    "cmakepresets.json", "cmakeuserpresets.json", "vcpkg.json",
    "conanfile.py", "conanfile.txt", "pyproject.toml", "setup.py",
    "setup.cfg", "tox.ini", "pipfile", "pipfile.lock", "poetry.lock",
    "requirements.txt", "workspace", "workspace.bazel", "module.bazel",
    "build", "build.bazel", "gemfile", "rakefile", "composer.json",
    "composer.lock",
}
BUILD_DESCRIPTOR_EXTENSIONS = (
    ".cmake", ".gradle", ".sln", ".vcxproj", ".props", ".targets",
    ".mk", ".gn", ".gni", ".bzl",
)
BUILD_SCRIPT_EXTENSIONS = (".sh", ".bash", ".bat", ".cmd", ".ps1")
DOCUMENT_EXTENSIONS = (".md", ".rst", ".adoc", ".txt")


def normalize_path(path):
    return (path or "").replace("\\", "/")


def is_absolute_path(path):
    normalized = normalize_path(path)
    return normalized.startswith("/") or bool(
        re.match(r"^[A-Za-z]:/", normalized))


def repo_relative_for_match(path, project_root):
    """Return a normalized root-relative path without cross-drive relpath."""
    normalized = normalize_path(path).strip().strip("\"'")
    if not normalized:
        return normalized
    if not is_absolute_path(normalized):
        return re.sub(r"^(?:\./)+", "", normalized)

    root = normalize_path(project_root).rstrip("/")
    roots = []
    for candidate in (root, _native_realpath(root)):
        if (candidate
                and candidate.lower() not in {
                    item.lower() for item in roots}):
            roots.append(candidate)
    candidates = [normalized]
    real = _native_realpath(normalized)
    if real and real.lower() != normalized.lower():
        candidates.append(real)
    for candidate in candidates:
        lowered = candidate.lower()
        for item in roots:
            root_lowered = item.lower()
            if lowered == root_lowered:
                return ""
            if lowered.startswith(root_lowered + "/"):
                return candidate[len(item) + 1:]
    return None


def _native_realpath(path):
    if not os.path.isabs(path):
        return ""
    try:
        return normalize_path(os.path.realpath(path)).rstrip("/")
    except OSError:
        return ""


def matches_pattern(path, pattern):
    try:
        return bool(re.search(pattern, path, re.I))
    except re.error:
        return False


def is_build_path(path):
    normalized = normalize_path(path).strip().strip("\"'").lower()
    base = normalized.rsplit("/", 1)[-1]
    return bool(
        base in SOURCE_FILENAMES
        or (base.startswith("requirements") and base.endswith(".txt"))
        or normalized.endswith(
            BUILD_DESCRIPTOR_EXTENSIONS + BUILD_SCRIPT_EXTENSIONS)
    )


def known_source_classification(
        path, project_root=None, require_membership=False):
    """Return True/False for known cases and None for pattern candidates."""
    normalized = normalize_path(path).strip().strip("\"'")
    if normalized.endswith("(未提交)"):
        normalized = normalized[:-len("(未提交)")]
    relative = (
        repo_relative_for_match(normalized, project_root)
        if project_root is not None
        else re.sub(r"^(?:\./)+", "", normalized)
    )
    if (require_membership and is_absolute_path(normalized)
            and relative is None):
        return False
    lowered = normalized.lower()
    if is_build_path(normalized) or lowered.endswith(SOURCE_EXTENSIONS):
        return True
    if lowered.endswith(DOCUMENT_EXTENSIONS):
        return False
    if relative is None:
        return False
    return None


def is_source_path(
        path, patterns, project_root=None, require_membership=False):
    known = known_source_classification(
        path,
        project_root=project_root,
        require_membership=require_membership,
    )
    if known is not None:
        return known
    normalized = normalize_path(path).strip().strip("\"'")
    if normalized.endswith("(未提交)"):
        normalized = normalized[:-len("(未提交)")]
    relative = (
        repo_relative_for_match(normalized, project_root)
        if project_root is not None
        else re.sub(r"^(?:\./)+", "", normalized)
    )
    return any(
        matches_pattern(relative, pattern)
        for pattern in patterns
    )
