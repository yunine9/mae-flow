**配置确认卡(一卡合一)已收集过本项时:直接 done --choice commit|local|no,禁止重复提问**;
以下仅在预答缺失时执行。
用 AskUserQuestion 询问 STORY 如何交付(给测试的澄清文档,可选;工具不可用才纯文本等回答),三个选项:
- 生成并入库(commit);
- 生成但不入库,仅本地交测(local,团队常规默认);
- 不生成(no)。
拿到按钮选择后直接 done --choice commit|local|no。harness 会把入库选择带进 story 步,
定稿后不再追加一次询问，也不再要求用户输入确认句。
本选择结束后，无论是否生成 STORY，都先进入编码计划检视。
