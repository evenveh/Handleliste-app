import asyncio
import json
import os
import re
import secrets
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Session

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:////data/handleliste.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

# Koder lages fra et alfabet uten tegn som er lette å forveksle (0/O, 1/I/L).
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8


class Base(DeclarativeBase):
    pass


class Household(Base):
    __tablename__ = "households"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    code = Column(String, nullable=False, unique=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Item(Base):
    __tablename__ = "items"
    id = Column(Integer, primary_key=True, index=True)
    household_id = Column(Integer, ForeignKey("households.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    added_by = Column(String, nullable=False)
    checked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


def generate_code(session: Session) -> str:
    while True:
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        if not session.query(Household).filter(Household.code == code).first():
            return code


def normalize_code(code: str) -> str:
    """Godta koder med små bokstaver, bindestrek eller mellomrom ("abcd-efgh")."""
    return re.sub(r"[^A-Z0-9]", "", code.upper())


def format_code(code: str) -> str:
    return f"{code[:4]}-{code[4:]}"


def migrate():
    """Oppgrader databaser fra før husstander fantes.

    Eksisterende varer flyttes inn i én husstand, og koden skrives til loggen
    slik at familien som allerede bruker appen kan bli med i den.
    """
    with engine.begin() as conn:
        cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(items)")]
        if "household_id" not in cols:
            conn.exec_driver_sql(
                "ALTER TABLE items ADD COLUMN household_id INTEGER REFERENCES households(id)"
            )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_items_household_id ON items (household_id)"
            )

    with Session(engine) as session:
        orphans = session.query(Item).filter(Item.household_id.is_(None)).all()
        if not orphans:
            return
        household = Household(name="Vår husstand", code=generate_code(session))
        session.add(household)
        session.flush()
        for item in orphans:
            item.household_id = household.id
        session.commit()
        print(
            f"[migrering] {len(orphans)} eksisterende varer er flyttet til husstanden "
            f"'{household.name}'. Bli med med koden: {format_code(household.code)}",
            flush=True,
        )


Base.metadata.create_all(bind=engine)
migrate()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Én liste med SSE-abonnenter per husstand, slik at endringer bare når
# klientene som ser på den samme lista.
subscribers: dict[int, list[asyncio.Queue]] = defaultdict(list)


async def broadcast(household_id: int, event: dict):
    for queue in subscribers.get(household_id, []):
        await queue.put(event)


def household_to_dict(household: Household) -> dict:
    return {"name": household.name, "code": format_code(household.code)}


def item_to_dict(item: Item) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "added_by": item.added_by,
        "checked": item.checked,
        "created_at": item.created_at.isoformat(),
    }


def get_household(session: Session, code: str) -> Household:
    household = (
        session.query(Household).filter(Household.code == normalize_code(code)).first()
    )
    if not household:
        raise HTTPException(status_code=404, detail="Household not found")
    return household


def get_item(session: Session, household: Household, item_id: int) -> Item:
    item = (
        session.query(Item)
        .filter(Item.id == item_id, Item.household_id == household.id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


class HouseholdCreate(BaseModel):
    name: str


class HouseholdUpdate(BaseModel):
    name: str


class ItemCreate(BaseModel):
    name: str
    added_by: str


# ── Husstander ──


@app.post("/api/households", status_code=201)
def create_household(data: HouseholdCreate):
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    with Session(engine) as session:
        household = Household(name=name[:60], code=generate_code(session))
        session.add(household)
        session.commit()
        return household_to_dict(household)


@app.get("/api/households/{code}")
def read_household(code: str):
    with Session(engine) as session:
        return household_to_dict(get_household(session, code))


@app.patch("/api/households/{code}")
async def rename_household(code: str, data: HouseholdUpdate):
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    with Session(engine) as session:
        household = get_household(session, code)
        household.name = name[:60]
        session.commit()
        household_id = household.id
        result = household_to_dict(household)
    await broadcast(household_id, {"type": "household", "household": result})
    return result


# ── Varer (alltid innenfor én husstand) ──


@app.get("/api/households/{code}/items")
def get_items(code: str):
    with Session(engine) as session:
        household = get_household(session, code)
        items = (
            session.query(Item)
            .filter(Item.household_id == household.id)
            .order_by(Item.created_at)
            .all()
        )
        return [item_to_dict(i) for i in items]


@app.post("/api/households/{code}/items", status_code=201)
async def add_item(code: str, item: ItemCreate):
    if not item.name.strip() or not item.added_by.strip():
        raise HTTPException(status_code=400, detail="Name and added_by are required")
    with Session(engine) as session:
        household = get_household(session, code)
        db_item = Item(
            household_id=household.id,
            name=item.name.strip(),
            added_by=item.added_by.strip(),
        )
        session.add(db_item)
        session.commit()
        session.refresh(db_item)
        household_id = household.id
        result = item_to_dict(db_item)
    await broadcast(household_id, {"type": "add", "item": result})
    return result


@app.patch("/api/households/{code}/items/{item_id}")
async def toggle_item(code: str, item_id: int):
    with Session(engine) as session:
        household = get_household(session, code)
        item = get_item(session, household, item_id)
        item.checked = not item.checked
        session.commit()
        household_id = household.id
        result = item_to_dict(item)
    await broadcast(household_id, {"type": "update", "item": result})
    return result


@app.delete("/api/households/{code}/items/{item_id}")
async def delete_item(code: str, item_id: int):
    with Session(engine) as session:
        household = get_household(session, code)
        item = get_item(session, household, item_id)
        session.delete(item)
        session.commit()
        household_id = household.id
    await broadcast(household_id, {"type": "delete", "id": item_id})
    return {"ok": True}


@app.delete("/api/households/{code}/items")
async def delete_checked(code: str):
    with Session(engine) as session:
        household = get_household(session, code)
        checked = (
            session.query(Item)
            .filter(Item.household_id == household.id, Item.checked == True)
            .all()
        )
        ids = [i.id for i in checked]
        for item in checked:
            session.delete(item)
        session.commit()
        household_id = household.id
    await broadcast(household_id, {"type": "delete_checked", "ids": ids})
    return {"deleted": len(ids)}


@app.get("/api/households/{code}/stream")
async def stream(code: str, request: Request):
    with Session(engine) as session:
        household_id = get_household(session, code).id

    queue: asyncio.Queue = asyncio.Queue()
    subscribers[household_id].append(queue)

    async def event_generator():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    if await request.is_disconnected():
                        break
        except asyncio.CancelledError:
            pass
        finally:
            queues = subscribers.get(household_id)
            if queues is not None:
                if queue in queues:
                    queues.remove(queue)
                if not queues:
                    subscribers.pop(household_id, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
