用户已在开场选择：人工检视前先进行一次可选 CODE Agent 预检。

执行 `python "{MAEFLOW_PATH}" role-task code-review`，只把生成的任务卡路径交给
craft-reviewer-agent。它只读检查本需求完整未提交增量，不修改文件，也不代替用户人工检视。
记录返回后执行 `done`；无论结论是 CLEAR 还是 ISSUE，都只运行这一轮，不形成自动循环。
