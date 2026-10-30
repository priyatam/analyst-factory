"""The model edge builds a real Strands agent with this account's model id.

Not a live call — the suite has no Bedrock. This proves the seam is wired, not faked.
"""
from novamark import model


def test_model_edge_uses_the_configured_model_and_no_tools():
    from strands import Agent

    built = model.agent()

    assert isinstance(built, Agent)
    assert built.tool_names == []
    assert built.model.config["model_id"] == model.MODEL_ID
    assert built.system_prompt


def test_model_id_is_declared_once():
    """AGENTS.md: the id matches the IAM profile. One literal, in model."""
    source = open(model.__file__).read()
    assert source.count("us.anthropic.claude-sonnet-4-6") == 1
