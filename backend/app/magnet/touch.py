"""Touchpoints, not intent. A like is one touch; what makes someone worth a message is repeated, varied engagement.

Each engagement is a touch. A person's score counts comments above likes, then rewards engaging on more than one post,
with more than one competitor, and recently. The tier says how much it means:

- hot: comments at two or more competitors, or three or more touches across two or more posts
- warm: two or more touches, or one comment
- touch: a single like. It's listed, never sold as intent.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Literal

Kind = Literal["comment", "reaction"]
Tier = Literal["hot", "warm", "touch"]

COMMENT_POINTS = 3
REACTION_POINTS = 1
EXTRA_POST_POINTS = 1
EXTRA_COMPETITOR_POINTS = 2
RECENT_POINTS = 1
RECENT_DAYS = 14
HOT_TOUCHES = 3
TIER_ORDER: dict[Tier, int] = {"hot": 0, "warm": 1, "touch": 2}


@dataclass(frozen=True)
class Touch:
    """One engagement: who, on which post at which competitor, how, and when."""

    person: str  # the person's LinkedIn key (member ID or profile URL)
    post: str
    competitor: str
    kind: Kind
    day: date | None = None
    text: str = ""  # the comment, when it is one


@dataclass
class Score:
    person: str
    touches: int = 0
    comments: int = 0
    reactions: int = 0
    posts: set[str] = field(default_factory=set)
    competitors: set[str] = field(default_factory=set)
    commented_at: set[str] = field(default_factory=set)
    last: date | None = None
    points: int = 0
    tier: Tier = "touch"


def score(touches: list[Touch], today: date) -> dict[str, Score]:
    """Each person's touch count, points and tier. The same reaction counted twice (a retry) counts once."""
    seen: set[tuple[str, str, str, str]] = set()
    out: dict[str, Score] = {}
    for t in touches:
        key = (t.person, t.post, t.kind, t.text)
        if key in seen:
            continue
        seen.add(key)
        s = out.setdefault(t.person, Score(person=t.person))
        s.touches += 1
        s.posts.add(t.post)
        s.competitors.add(t.competitor)
        if t.kind == "comment":
            s.comments += 1
            s.commented_at.add(t.competitor)
        else:
            s.reactions += 1
        if t.day and (s.last is None or t.day > s.last):
            s.last = t.day
    for s in out.values():
        s.points = (
            COMMENT_POINTS * s.comments
            + REACTION_POINTS * s.reactions
            + EXTRA_POST_POINTS * (len(s.posts) - 1)
            + EXTRA_COMPETITOR_POINTS * (len(s.competitors) - 1)
            + (RECENT_POINTS if s.last and s.last >= today - timedelta(days=RECENT_DAYS) else 0)
        )
        s.tier = tier_of(s)
    return out


def tier_of(s: Score) -> Tier:
    if len(s.commented_at) >= 2 or (s.touches >= HOT_TOUCHES and len(s.posts) >= 2):  # noqa: PLR2004
        return "hot"
    if s.touches >= 2 or s.comments >= 1:  # noqa: PLR2004
        return "warm"
    return "touch"


def ranked(scores: dict[str, Score]) -> list[Score]:
    """Hot first, then by points, then by most recent touch."""
    return sorted(
        scores.values(),
        key=lambda s: (TIER_ORDER[s.tier], -s.points, -(s.last.toordinal() if s.last else 0), s.person),
    )
