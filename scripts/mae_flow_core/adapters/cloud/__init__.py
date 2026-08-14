"""云端宿主适配层(详设 docs/superpowers/specs/2026-08-14-cloud-host-adapter-design.md)。

Pi 事件流 → 语义事件 → 内核。Pi 私有对象不越过 pi_event_map.py;
内核面向的工具词汇表、transcript JSONL、状态文件与旧插件完全一致。
"""
