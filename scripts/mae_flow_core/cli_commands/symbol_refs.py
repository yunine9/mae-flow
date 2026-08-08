"""全仓符号引用清单——改动收口的递工具。

这是工具不是门禁:只读、不写状态、不拦任何东西、任何模式可用。
它服务的是最贵的那类事故:动了共享符号(签名/枚举/常量/配置键/协议字段),
十三处引用改了十二处,漏的那处在 MyBatis XML 里——编译全绿,基本功能坏。
靠提示词要求 Agent 自觉 grep 会漏;一条确定性命令把清单打出来,漏项一目了然。
"""

import os
import subprocess

# 编译器看得见的扩展名;其余一律归入"编译器看不见",漏改就是运行期事故。
_CODE_EXTENSIONS = frozenset((
    ".java", ".kt", ".scala", ".groovy",
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp",
    ".cs", ".go", ".rs", ".swift",
    ".py", ".js", ".jsx", ".ts", ".tsx",
))


def _git_lines(arguments):
    """git 输出行;无命中/无仓库返回空列表,绝不抛错——工具失败不能变成新卡点。"""
    try:
        completed = subprocess.run(
            ["git", "-c", "core.quotepath=false"] + list(arguments),
            shell=False, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=60)
    except Exception:
        return []
    if completed.returncode not in (0, 1):
        return []
    return [line for line in completed.stdout.splitlines() if line.strip()]


def _is_code_file(path):
    return os.path.splitext(path)[1].lower() in _CODE_EXTENSIONS


def symbol_hits(symbol):
    """(编译可见命中, 编译器看不见命中, 文件名命中);词边界精确匹配,含未跟踪文件。"""
    grep = _git_lines([
        "grep", "-nwIF", "--untracked", "-e", symbol, "--", ".",
        ":(exclude).mae-flow-work", ":(exclude)*.min.js",
    ])
    code, opaque = [], []
    for line in grep:
        path = line.split(":", 1)[0]
        (code if _is_code_file(path) else opaque).append(line)
    names = [
        path for path in _git_lines(
            ["ls-files", "--cached", "--others", "--exclude-standard"])
        if symbol in os.path.basename(path)
    ]
    return code, opaque, names


def cmd_symbol_refs(args):
    for symbol in args.symbols:
        code, opaque, names = symbol_hits(symbol)
        total = len(code) + len(opaque)
        if total == 0 and not names:
            print("[mae-flow] %s: 0 处引用(词边界精确匹配,含未跟踪文件)。"
                  % symbol)
            print("  若该符号由反射/字符串拼接产生,再用模糊搜索复核: "
                  "git grep --untracked <部分名>")
            continue
        print("[mae-flow] 符号引用清单: %s(共 %d 处,其中编译器看不见 %d 处)"
              % (symbol, total, len(opaque)))
        index = 0
        if opaque:
            print("── 编译器看不见的文件(XML/YAML/SQL/配置/脚本——"
                  "漏改这里=编译全绿功能坏)──")
            for line in opaque:
                index += 1
                print("[ ] %d. %s" % (index, line[:300]))
        if code:
            print("── 代码文件 ──")
            for line in code:
                index += 1
                print("[ ] %d. %s" % (index, line[:300]))
        if names:
            print("── 文件名命中 ──")
            for path in names:
                index += 1
                print("[ ] %d. %s" % (index, path))
        print("每一处要么适配、要么写明为何不需要;清单逐项对钩后这个符号才算收口。")
