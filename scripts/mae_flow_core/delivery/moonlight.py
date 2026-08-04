"""Pure policy helpers for Moonlight delivery closure."""


def issue_id(existing_count):
    return "ML-%03d" % (existing_count + 1)


def finalize_target(state):
    del state
    return "domain_archive"
