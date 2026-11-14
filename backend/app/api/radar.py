"""The job radar: its inbox, hiring posts, settings, and a run on demand."""

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.auth import AppSettings, DbSession, SignedIn
from app.clock import Today
from app.config import Settings
from app.db import session_factory
from app.models import RadarItem
from app.radar import run as radar
from app.radar.fit import RadarConfig
from app.schemas import HiringPost, RadarAdded, RadarConfigOut, RadarConfigPatch, RadarItemOut, RadarOut

router = APIRouter(prefix="/api/radar", tags=["radar"], dependencies=[SignedIn])

INBOX_LIMIT = 200


@dataclass
class Runtime:
    """How the API starts radar work: in a background thread, with the real network. Tests run it inline."""

    settings: Settings
    tools: Callable[[], radar.Tools]
    spawn: Callable[[Callable[[], None]], None]
    factory: sessionmaker[Session]

    def start(self, work: Callable[[], None]) -> None:
        self.spawn(work)


def _thread(work: Callable[[], None]) -> None:
    threading.Thread(target=work, daemon=True).start()


def get_runtime(request: Request, settings: AppSettings) -> Runtime:
    runtime = getattr(request.app.state, "radar_runtime", None)
    return runtime or Runtime(
        settings=settings, tools=lambda: radar.default_tools(settings), spawn=_thread, factory=session_factory()
    )


RadarRuntime = Annotated[Runtime, Depends(get_runtime)]


def _item(r: RadarItem) -> RadarItemOut:
    d = r.data or {}
    return RadarItemOut(
        id=r.id,
        company=r.company,
        title=r.title,
        url=r.url,
        posted=r.posted,
        fit=r.fit,
        state=r.state,
        company_id=r.company_id,
        location=d.get("location", ""),
        salary=d.get("salary", ""),
        flags=list(d.get("flags") or []),
        source=d.get("source", "LinkedIn"),
        snippet=d.get("snippet", ""),
        on_bench=bool(d.get("on_bench")),
    )


@router.get("")
def state(session: DbSession, settings: AppSettings) -> RadarOut:
    """The radar's last run, its settings, the inbox (newest first, best fit first within a day) and hiring posts."""
    items = session.scalars(
        select(RadarItem)
        .where(RadarItem.state == "new")
        .order_by(RadarItem.posted.desc().nulls_last(), RadarItem.fit.desc(), RadarItem.id)
        .limit(INBOX_LIMIT)
    ).all()
    posts = [HiringPost.model_validate(p) for p in radar.get_setting(session, "radar_posts", []) if isinstance(p, dict)]
    status_now = dict(radar.get_setting(session, "radar_status", {}))
    status_now["running"] = radar.is_running(session, status_now)
    return RadarOut(
        status=status_now,
        config=RadarConfigOut(**radar.config(session).__dict__),
        items=[_item(r) for r in items],
        posts=posts,
        treg=bool(settings.treg_token and settings.treg_token.get_secret_value().strip()),
    )


@router.patch("/config")
def update_config(body: RadarConfigPatch, session: DbSession) -> RadarConfigOut:
    stored = dict(radar.get_setting(session, "radar_config", {}))
    stored.update(body.model_dump(exclude_unset=True, exclude_none=True))
    cfg = RadarConfig.from_setting(stored)
    radar.put_setting(session, "radar_config", stored)
    session.commit()
    return RadarConfigOut(**cfg.__dict__)


@router.post("/run", status_code=status.HTTP_202_ACCEPTED)
def run_now(session: DbSession, runtime: RadarRuntime) -> dict[str, str]:
    """Check now, in the background. The status shows progress; a second press while it runs is refused."""
    current = dict(radar.get_setting(session, "radar_status", {}))
    if radar.is_running(session, current):
        raise HTTPException(status.HTTP_409_CONFLICT, "The radar is already running.")

    def work() -> None:
        radar.run_once(runtime.factory, runtime.settings, runtime.tools(), "manual")

    # marked before the thread starts, so the page's first refresh already sees it running and keeps polling
    current.update(running=True, step="starting", error="", started_at=datetime.now(UTC).isoformat())
    radar.put_setting(session, "radar_status", current)
    session.commit()
    runtime.start(work)
    return {"status": "started"}


def _get_item(session: DbSession, item_id: str) -> RadarItem:
    item = session.get(RadarItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That role isn't in the radar.")
    return item


@router.post("/items/{item_id}/add")
def add(item_id: str, session: DbSession, today: Today, runtime: RadarRuntime) -> RadarAdded:
    """Put a radar role into the tracker: the company (if it's new), an Apply move, and a move to find the hiring
    manager, both for today."""
    item = _get_item(session, item_id)
    if item.state == "added":
        raise HTTPException(status.HTTP_409_CONFLICT, "Already added.")
    added = radar.add_to_board(session, item, today)
    session.commit()
    company = added.company
    if not (company.research.get("jobs") or {}).get("board"):
        cid, title, move_id = company.id, item.title, added.apply_move.id
        runtime.start(lambda: radar.find_board_for(runtime.factory, runtime.tools().web, cid, title, move_id, today))
    return RadarAdded(company_id=company.id, move_id=added.apply_move.id)


@router.post("/items/{item_id}/dismiss")
def dismiss(item_id: str, session: DbSession) -> RadarItemOut:
    item = _get_item(session, item_id)
    item.state = "dismissed"
    item.data = {**item.data, "dismissed_at": datetime.now(UTC).isoformat()}
    session.commit()
    return _item(item)
