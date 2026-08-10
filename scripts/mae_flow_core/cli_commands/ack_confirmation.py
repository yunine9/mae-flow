"""配置确认的判定。单独成文件:ack.py 已顶到 500 行红线。"""

import re


def is_full_config_confirmation(value, config=None):
    """用户这句话是不是"整份配置都认了"。

    原来是措辞白名单(只认"确认以上全部配置"/"全部正确"那几句)。可选项文字是
    模型写的,弱模型必然换说法——用户点了「配置无误,开始交付」照样被判不通过。
    用户高于一切:他说可以了就该放行,机器不该嫌措辞不对。

    但当初要防的那件事仍然要防:"确认 master"这种**单项**回答不能给整份配置
    背书。判据换成事实——回答里点了某个配置项的值、又没说"以上/全部/所有",
    那就是在确认单项。
    """
    compact = re.sub(r"[\s，。；;：:、!！]+", "", value or "")
    if not compact or re.search(
            r"不确认|不同意|不是|不要|不能|没有|没法|否认|拒绝|暂不|取消|"
            r"修改|调整|不对|有误|有问题|什么意思|怎么|是否|能否|为什么|[?？]",
            compact):
        return False
    # 肯定的说法不设前缀白名单:模型换个措辞就判不通过,是拿用户当机器。
    if not re.search(r"确认|同意|可以|没问题|无异议|无误|正确|继续|按此|"
                     r"放行|批准|通过|开始|ok|yes|y$", compact, re.I):
        return False
    whole = bool(re.search(r"以上|全部|所有|整份|都对|都正确|无误", compact))
    if whole:
        return True
    named = [
        str(item) for item in (config or {}).values()
        if str(item).strip() and len(str(item).strip()) >= 2
        and str(item).strip() in compact
    ]
    return not named
