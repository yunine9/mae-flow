"""Pure policy helpers for Moonlight delivery closure."""


def issue_id(existing_count):
    return "ML-%03d" % (existing_count + 1)


def finalize_target(state):
    del state
    return "domain_archive"


def repeat_count(issues, step, reason):
    """这一步、这个原因,连同本次一共登记过几回。

    实测:月光在 branch_create 上一字不差地登记了 7 次。每次都把上一条标成
    superseded,记录上看不出在重复;模型收不到"别再试了"的信号,就一直重试。
    """
    said = str(reason or "").strip()
    return 1 + sum(
        1 for old in (issues or ())
        if old.get("step") == step and str(old.get("reason", "")).strip() == said
    )


BLOCK_SAVED = ("[mae-flow] 月光宝盒已记录无法自动解决的硬阻塞并保存现场。"
               "本轮允许正常停止；早晨执行 moonlight report 查看，"
               "条件补齐后执行 moonlight repair 继续当前步骤。")


def block_notice(repeats):
    if repeats < 2:
        return BLOCK_SAVED
    return BLOCK_SAVED + (
        "\n[mae-flow] ⚠ 本步同一原因已登记 %d 次——换个说法再试也不会有不同"
        "结果。停止重试本步,直接结束回复等人工处理;重复登记只会把晨间报告"
        "刷满。" % repeats)

