import asyncio
import json

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import Boolean, Column, DateTime, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Session
from datetime import datetime, timezone

DATABASE_URL = "sqlite:////data/handleliste.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


class Base(DeclarativeBase):
    pass


class Item(Base):
    __tablename__ = "items"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    added_by = Column(String, nullable=False)
    checked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


Base.metadata.create_all(bind=engine)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

subscribers: list[asyncio.Queue] = []


async def broadcast(event: dict):
    for queue in subscribers:
        await queue.put(event)


def item_to_dict(item: Item) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "added_by": item.added_by,
        "checked": item.checked,
        "created_at": item.created_at.isoformat(),
    }


class ItemCreate(BaseModel):
    name: str
    added_by: str


@app.get("/api/items")
def get_items():
    with Session(engine) as session:
        items = session.query(Item).order_by(Item.created_at).all()
        return [item_to_dict(i) for i in items]


@app.post("/api/items", status_code=201)
async def add_item(item: ItemCreate):
    if not item.name.strip() or not item.added_by.strip():
        raise HTTPException(status_code=400, detail="Name and added_by are required")
    with Session(engine) as session:
        db_item = Item(name=item.name.strip(), added_by=item.added_by.strip())
        session.add(db_item)
        session.commit()
        session.refresh(db_item)
        result = item_to_dict(db_item)
    await broadcast({"type": "add", "item": result})
    return result


@app.patch("/api/items/{item_id}")
async def toggle_item(item_id: int):
    with Session(engine) as session:
        item = session.get(Item, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        item.checked = not item.checked
        session.commit()
        result = item_to_dict(item)
    await broadcast({"type": "update", "item": result})
    return result


@app.delete("/api/items/{item_id}")
async def delete_item(item_id: int):
    with Session(engine) as session:
        item = session.get(Item, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        session.delete(item)
        session.commit()
    await broadcast({"type": "delete", "id": item_id})
    return {"ok": True}


@app.delete("/api/items")
async def delete_checked():
    with Session(engine) as session:
        checked = session.query(Item).filter(Item.checked == True).all()
        ids = [i.id for i in checked]
        for item in checked:
            session.delete(item)
        session.commit()
    await broadcast({"type": "delete_checked", "ids": ids})
    return {"deleted": len(ids)}


@app.get("/api/stream")
async def stream(request: Request):
    queue: asyncio.Queue = asyncio.Queue()
    subscribers.append(queue)

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
            if queue in subscribers:
                subscribers.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
