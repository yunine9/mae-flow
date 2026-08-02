# Mae-Flow 干净环境验收

高效率、高质量；在需要人介入时聪明地让人介入。

目标：从一个没有 Mae-Flow 状态、没有公司私有质量工具、没有旧会话的干净 checkout，证明当前 Full/Focused 工作流和 Intake → Spec → Design → Construction → Quality → Delivery 六阶段模型可安装、可恢复、可退出、可发布。

## 环境矩阵

至少覆盖：

- [ ] GitHub Actions `windows-latest`，真实 NT 路径与文件锁语义；
- [ ] GitHub Actions `ubuntu-latest`，独立的通用 Python 回归；
- [ ] 一台公司 Windows 主机，仅做 [FIELD-TEST.md](FIELD-TEST.md) 的 Host 集成金丝雀。

CI 不安装或调用真实内部 Build、UT、CodeCheck。两套发布场景使用 fake Host payload 和 opaque outcome，因此公开 runner 可维护且不需要私有凭据。

## 1. 干净 checkout

```text
git clone <repository> mae-flow-clean
cd mae-flow-clean
git status --short
python --version
```

- [ ] `git status --short` 为空。
- [ ] `python` 可发现并启动；流程、文档和 CI 不要求其他解释器命令名。
- [ ] 仓库中不存在活动 `.mae-flow.json` 时，四个生产 Hooks 全部 fail-open。

## 2. 模型烟测

- [ ] 启动卡只提供 Full 与 Focused。
- [ ] Full 用户卡只出现在 Startup、Spec、Story、每个 CP、Delivery 和真实条件风险。
- [ ] Focused 用户卡只出现在 Startup、Delivery；语义风险可以升级 Full/Spec。
- [ ] 文档和 UI 都显示唯一六阶段序列 Intake → Spec → Design → Construction → Quality → Delivery。
- [ ] Build、UT、CodeCheck、Grill、Story、Reviewer 被描述为一次性 opaque capabilities。
- [ ] Host Hook 是唯一写者；生产只有 `SessionStart`、`UserPromptSubmit`、`PreToolUse`、`PostToolUse`。

## 3. 文件与交付烟测

- [ ] 需求文档按单号分组。
- [ ] Story 与条件文档默认保留在本地，用户明确选择才加入 exact manifest。
- [ ] 初始脏文件不被默认采用。
- [ ] manifest 只包含逐文件路径，Windows alias 不重复。
- [ ] 提交说明为 `[ticket][feat|fix]description`。
- [ ] Moonlight 精确授权不隐藏 Delivery 卡。

## 4. 平台边界烟测

- [ ] UTF-8 BOM JSON、GB18030 Hook input 和 CRLF resource 通过。
- [ ] drive、UNC、反斜杠与大小写 identity 通过。
- [ ] locked replace/delete 在固定 attempt 内成功或明确失败；验收过程不实际等待。
- [ ] fake Host capability 同步返回；timeout 使用短 subprocess 边界，不依赖 POSIX signal。
- [ ] 输入未变时复用 capability result，不后台轮询或自动再次调用。

## 5. 发布门

在 checkout 中依次运行一次：

```text
python scripts/tests/test_lean_semantic_scenarios.py
python scripts/tests/test_windows_lean_runtime.py
python -m unittest discover -s scripts/tests -p 'test_*.py'
python scripts/selftest.py
git diff --check
```

验收标准：

- [ ] 两套 targeted release suites 均 PASS；
- [ ] discover PASS；
- [ ] selftest PASS，并报告已注册的全部 suite；
- [ ] Windows 与 Ubuntu CI jobs 均 PASS；
- [ ] `git diff --check` 无输出；
- [ ] 运行测试后 `git status --short` 没有意外文件；
- [ ] 没有访问公司私有工具、网络服务或真实 Delivery remote。
