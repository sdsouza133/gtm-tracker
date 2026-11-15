"""A stand-in for treg in tests: canned answers per tool, and a record of every call. Everything it returns is made
up."""

from collections.abc import Callable
from typing import Any

from app.treg import Answer, TregError

Reply = Callable[[dict[str, Any], dict[str, Any] | None], Any]


class FakeTreg:
    """Answers each tool with a function of the call's query and body, or with a fixed body.

    A tool in `fail` raises TregError (charged nothing unless `fail_spent` says otherwise); every call costs `price`
    unless `prices` names the tool.
    """

    def __init__(
        self,
        answers: dict[str, Reply | Any] | None = None,
        *,
        fail: set[str] | None = None,
        fail_spent: float = 0.0,
        retryable: bool = False,
        price: float = 0.001,
        prices: dict[str, float] | None = None,
    ) -> None:
        self.answers = answers or {}
        self.fail = fail or set()
        self.fail_spent = fail_spent
        self.retryable = retryable
        self.price = price
        self.prices = prices or {}
        self.calls: list[tuple[str, dict[str, Any], dict[str, Any] | None, float]] = []

    def call(
        self, tool: str, *, query: dict[str, Any] | None = None, body: dict[str, Any] | None = None, max_usd: float
    ) -> Answer:
        self.calls.append((tool, dict(query or {}), body, max_usd))
        if tool in self.fail:
            raise TregError(f"{tool} is down", spent=self.fail_spent, retryable=self.retryable)
        reply = self.answers.get(tool, {})
        answer = reply(dict(query or {}), body) if callable(reply) else reply
        return Answer(answer, self.prices.get(tool, self.price))

    def tools(self) -> list[str]:
        return [tool for tool, *_ in self.calls]


def pages(items: list[dict[str, Any]], size: int) -> Reply:
    """A paged list endpoint: page N of `items`, `size` to a page, as HarvestAPI answers."""

    def reply(query: dict[str, Any], _body: dict[str, Any] | None) -> dict[str, Any]:
        page = int(query.get("page") or 1)
        return {"elements": items[(page - 1) * size : page * size], "pagination": {"pageSize": size}}

    return reply
