from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest
from pydantic import ValidationError

from app.magnet import brain
from app.magnet.brain import Brain, BrainError, Screen, Verdict
from tests.magnet_fakes import icp


class FakeMessages:
    def __init__(self, answers: list[Any]) -> None:
        self.answers = answers
        self.calls: list[dict[str, Any]] = []

    def parse(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class FakeClient:
    def __init__(self, *answers: Any) -> None:
        self.messages = FakeMessages(list(answers))
        self.beta = SimpleNamespace(messages=self.messages)


def reply(parsed: Any, stop: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(stop_reason=stop, parsed_output=parsed)


def make(client: FakeClient) -> Brain:
    return Brain("", "icp-model", "screen-model", client=client)  # type: ignore[arg-type]


def test_the_icp_comes_from_the_strong_model_with_a_fallback_if_it_declines() -> None:
    many = icp(*(f"rival{i}.example" for i in range(8)))
    client = FakeClient(reply(many))
    found = make(client).icp({"text": "We sell pipeline software."}, ["named.example"])
    call = client.messages.calls[0]
    assert call["model"] == "icp-model"
    assert call["fallbacks"] == "default"
    assert call["betas"] == [brain.FALLBACK_BETA]
    assert "We sell pipeline software." in call["messages"][0]["content"]
    assert "named.example" in call["messages"][0]["content"]
    assert len(found.competitors) == brain.MAX_COMPETITORS


@pytest.mark.parametrize(("stop", "message"), [("refusal", "declined"), ("max_tokens", "cut off")])
def test_a_refused_or_cut_off_answer_is_an_error_not_a_guess(stop: str, message: str) -> None:
    with pytest.raises(BrainError, match=message):
        make(FakeClient(reply(None, stop))).icp({"text": "x"}, [])


def test_api_failures_become_brain_errors() -> None:
    down = anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
    with pytest.raises(BrainError, match="APIConnectionError"):
        make(FakeClient(down)).icp({"text": "x"}, [])


def test_screening_goes_in_batches_to_the_small_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(brain, "SCREEN_BATCH", 2)
    client = FakeClient(
        reply(Screen(people=[Verdict(i=0, fit=True, reason="buyer"), Verdict(i=1, fit=False, reason="student")])),
        reply(Screen(people=[Verdict(i=2, fit=True, reason="buyer"), Verdict(i=7, fit=True, reason="not asked")])),
        reply(Screen(people=[])),
    )
    verdicts = make(client).screen(["VP Sales", "Student", "Head of RevOps", "Designer", "CFO"], icp(), ["RivalCo"])
    assert [c["model"] for c in client.messages.calls] == ["screen-model"] * 3
    assert "2. Head of RevOps" in client.messages.calls[1]["messages"][0]["content"]
    assert "RivalCo" in client.messages.calls[0]["messages"][0]["content"]
    assert {i: v.fit for i, v in verdicts.items()} == {0: True, 1: False, 2: True}  # 7 wasn't in the batch


def test_no_key_and_no_client_is_an_error() -> None:
    with pytest.raises(BrainError, match="ANTHROPIC_API_KEY"):
        Brain("", "a", "b")


def test_a_reply_that_does_not_parse_is_a_brain_error() -> None:
    try:
        Screen.model_validate_json('{"people": [{"i": 0, "fit": tr')  # cut off mid-answer
    except ValidationError as e:
        cut_off = e
    with pytest.raises(BrainError, match="incomplete"):
        make(FakeClient(cut_off)).icp({"text": "x"}, [])
    with pytest.raises(BrainError, match="incomplete"):
        make(FakeClient(cut_off)).screen(["VP Sales"], icp(), [])
