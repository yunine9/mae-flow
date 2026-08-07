"""Install a stable project-local bridge to the CodeAgent plugin entry."""

import os

from ..runtime import ACTION_FILE, EXIT_FILE, FLOW_FILE


def project_has_runtime_state(project_root=None):
    """Whether this project ever enabled Mae-Flow.

    A global plugin install only offers capability; it must not leave files in
    repositories that never started a delivery. Without this check the bridge
    reappears in ``git status`` of every project on the first message, and
    comes back immediately after the user deletes it.
    """
    root = os.path.abspath(project_root or os.getcwd())
    return any(
        os.path.isfile(os.path.join(root, marker))
        for marker in (FLOW_FILE, EXIT_FILE, ACTION_FILE)
    )


def install_project_launcher(project_root=None, plugin_root=None):
    project_root = os.path.abspath(project_root or os.getcwd())
    plugin_root = (
        str(plugin_root or "").strip()
        or os.environ.get("CODEAGENT3_PLUGIN_ROOT", "").strip()
        or os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", "..", ".."))
    )
    entry = os.path.join(plugin_root, "scripts", "mae-flow.py")
    target = os.path.join(
        project_root, ".mae-flow-work", "bin", "mae-flow.py")
    temporary = target + ".tmp-%s" % os.getpid()
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(temporary, "w", encoding="utf-8", newline="\n") as stream:
            stream.write("import subprocess\nimport sys\n\n")
            stream.write("ENTRY = %r\n" % entry)
            stream.write(
                "raise SystemExit(subprocess.call("
                "[sys.executable, ENTRY] + sys.argv[1:]))\n")
        os.replace(temporary, target)
        try:
            os.chmod(target, 0o755)
        except OSError:
            pass
        return target
    except (OSError, UnicodeError):
        try:
            if os.path.exists(temporary):
                os.unlink(temporary)
        except OSError:
            pass
        return ""


def install_launcher_when_active(project_root=None, plugin_root=None):
    """Materialize the bridge only for projects that already use Mae-Flow."""
    if not project_has_runtime_state(project_root):
        return ""
    return install_project_launcher(project_root, plugin_root)


def install_launcher_for_event(event):
    normalized = "".join(
        character for character in str(event).casefold()
        if character.isalnum())
    if normalized in {"sessionstart", "userprompt", "userpromptsubmit"}:
        return install_launcher_when_active()
    return ""
