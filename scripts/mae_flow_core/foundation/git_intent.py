"""Pure parsing of Git add/commit intent from shell command text."""

import re
import shlex

from .source_paths import normalize_path


COMMIT_VALUE_OPTIONS = {
    "-m", "--message", "-F", "--file", "-C", "--reuse-message",
    "-c", "--reedit-message", "--author", "--date", "--cleanup",
    "-t", "--template", "--fixup", "--squash", "--trailer",
}


def git_subcommand_tokens(command, subcommand):
    results = []
    for segment in re.split(r"&&|\|\||[;\n]", command):
        match = re.search(
            r"(?:^|\s)git\s+" + re.escape(subcommand) + r"\b(.*)$",
            segment,
            re.I,
        )
        if not match:
            continue
        try:
            results.append(shlex.split(match.group(1), posix=True))
        except ValueError:
            continue
    return results


def option_consumes_following(token, value_options):
    option = token.split("=", 1)[0]
    if option in value_options:
        return "=" not in token
    return bool(re.fullmatch(r"-[A-Za-z]*[mFCctS]", token))


class PathspecCollector:
    def __init__(self, value_options):
        self.value_options = value_options
        self.paths = []

    def _consume(self, tokens, index):
        token = tokens[index]
        if not token.startswith("-"):
            self.paths.append(normalize_path(token))
            return index + 1
        return index + (
            2 if option_consumes_following(
                token, self.value_options) else 1)

    def collect(self, tokens):
        index = 0
        while index < len(tokens):
            index = self._consume(tokens, index)
        return self.paths


def command_pathspecs(tokens, value_options=None):
    value_options = value_options or set()
    if "--" in tokens:
        marker = tokens.index("--")
        before, explicit = tokens[:marker], tokens[marker + 1:]
    else:
        before, explicit = tokens, []
    paths = PathspecCollector(value_options).collect(before)
    paths.extend(normalize_path(token) for token in explicit)
    return list(dict.fromkeys(paths))


def git_add_intent(tokens):
    token_set = set(tokens)
    all_mode = bool(
        token_set & {"-A", "--all", "--no-ignore-removal"})
    update = bool(token_set & {"-u", "--update"})
    paths = command_pathspecs(tokens)
    default_paths = ["."] if all_mode or update else []
    return {
        "pathspecs": paths or default_paths,
        "force": bool(token_set & {"-f", "--force"}),
        "tracked_only": update,
        "all": all_mode,
    }


def git_add_intents(command):
    return [
        git_add_intent(tokens)
        for tokens in git_subcommand_tokens(command, "add")
    ]


def short_option_flags(tokens):
    return "".join(
        match.group(1) for token in tokens
        for match in [re.fullmatch(r"-([A-Za-z]+)", token)]
        if match)


def git_commit_intent(command):
    token_sets = git_subcommand_tokens(command, "commit")
    tokens = token_sets[-1] if token_sets else []
    token_set = set(tokens)
    short_flags = short_option_flags(tokens)
    return {
        "pathspecs": command_pathspecs(tokens, COMMIT_VALUE_OPTIONS),
        "all": "a" in short_flags or "--all" in token_set,
        "include": "i" in short_flags or "--include" in token_set,
    }
