from runtime.action_protocol import action_error
from runtime.action_protocol import action_ok
from runtime.action_protocol import normalize_action_result


def test_normalize_action_result_keeps_protocol_metadata() -> None:
    result = normalize_action_result(
        {
            "_ok": False,
            "_error": "failed",
            "_warnings": ["check input"],
            "_metadata": {"cost": 1},
            "task": "demo",
        }
    )

    assert result.ok is False
    assert result.error == "failed"
    assert result.warnings == ("check input",)
    assert result.metadata == {"cost": 1}
    assert result.data == {"task": "demo"}


def test_action_helpers_create_result() -> None:
    assert action_ok({"task": "demo"}).ok is True
    assert action_error("boom").ok is False
