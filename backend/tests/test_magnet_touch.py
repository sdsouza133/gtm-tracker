from datetime import date

from app.magnet.touch import Touch, ranked, score

TODAY = date(2026, 11, 1)


def like(person: str, post: str, competitor: str = "rival.example", day: date | None = date(2026, 10, 28)) -> Touch:
    return Touch(person=person, post=post, competitor=competitor, kind="reaction", day=day)


def said(person: str, post: str, text: str, competitor: str = "rival.example") -> Touch:
    return Touch(person=person, post=post, competitor=competitor, kind="comment", day=date(2026, 10, 29), text=text)


def test_a_single_like_is_one_touch_not_intent() -> None:
    s = score([like("a", "p1", day=date(2026, 9, 1))], TODAY)["a"]
    assert (s.touches, s.reactions, s.points, s.tier) == (1, 1, 1, "touch")


def test_the_same_like_seen_twice_counts_once() -> None:
    assert score([like("a", "p1"), like("a", "p1")], TODAY)["a"].touches == 1


def test_a_comment_outweighs_a_like_and_makes_someone_warm() -> None:
    s = score([said("a", "p1", "Great point")], TODAY)["a"]
    assert (s.comments, s.points, s.tier) == (1, 3 + 1, "warm")  # comment, plus recent


def test_two_likes_make_someone_warm() -> None:
    assert score([like("a", "p1"), like("a", "p2")], TODAY)["a"].tier == "warm"


def test_repeated_touches_across_posts_are_hot() -> None:
    s = score([like("a", "p1"), like("a", "p2"), said("a", "p2", "So true")], TODAY)["a"]
    assert s.tier == "hot"
    assert s.points == 1 + 1 + 3 + 1 + 1  # two likes, a comment, a second post, recent


def test_commenting_at_two_competitors_is_hot() -> None:
    s = score([said("a", "p1", "Yes", "one.example"), said("a", "p9", "Agreed", "two.example")], TODAY)["a"]
    assert s.tier == "hot"
    assert s.competitors == {"one.example", "two.example"}


def test_ranking_puts_hot_first_then_points_then_recency() -> None:
    scores = score(
        [
            like("touch", "p1"),
            said("warm", "p1", "Nice"),
            like("hot", "p1"),
            like("hot", "p2"),
            like("hot", "p3"),
            like("old-warm", "p1", day=date(2026, 9, 1)),
            like("old-warm", "p2", day=date(2026, 9, 1)),
        ],
        TODAY,
    )
    assert [s.person for s in ranked(scores)] == ["hot", "warm", "old-warm", "touch"]
