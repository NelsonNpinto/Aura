from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.session import get_db

DB = Annotated[Session, Depends(get_db)]


def serialize(record):
    return {column.name: getattr(record, column.name) for column in record.__table__.columns}


def require(db, model, ident):
    record = db.get(model, ident)
    if not record:
        raise HTTPException(404, f"{model.__name__} not found")
    return record


def recent(db, model):
    return [
        serialize(r)
        for r in db.scalars(select(model).order_by(model.created_at.desc(), model.id).limit(100))
    ]


def save(db, record):
    db.add(record)
    db.commit()
    db.refresh(record)
    return serialize(record)
