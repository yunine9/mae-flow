"""Pure policy helpers for Moonlight delivery closure."""


def issue_id(existing_count):
    return "ML-%03d" % (existing_count + 1)


def finalize_target(state):
    workflow = (
        (state.get("choices") or {}).get("workflow", "")
    )
    change_name = (
        (state.get("config") or {}).get("CHANGE_NAME")
    )
    return (
        "end"
        if workflow == "review" or not change_name
        else "archive_confirm"
    )
