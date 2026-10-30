"""Stand-in tasks for the eval CLI. They do not call a model."""


def spoil(case):
    """One ticker returns a wrong figure. The rest match the label."""
    if case.metadata["ticker"] == "NMB":
        return {"output": {"revenue": 1}}
    return {"output": dict(case.expected_output)}
