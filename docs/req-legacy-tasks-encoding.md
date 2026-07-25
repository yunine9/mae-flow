# 需求：legacy tasks.md 坏编码时证据链不得崩溃

现象（已定位）：旧布局在途单的 tasks.md 若含非 UTF-8 字节（Windows 记事本 GBK
另存是高频来源），specengine.tasks_source / _count_tasks 的 legacy 分支只捕获
OSError，UnicodeDecodeError 会穿透——spec show / archive 直接 traceback。
v5 路径（change.md）已在上一单收口，本单补齐 legacy 对称面。

期望：与 change.md 同等待遇——引擎收口为带指引的 SpecEngineError（提示 UTF-8），
证据层拒+可重试；archive 的任务计数展示路径保持 CLI 同款宽容语义。
