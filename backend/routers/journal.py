import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from datetime import date

import database as db
from backend.auth_middleware import get_current_user

router = APIRouter(prefix="/journal", tags=["journal"])


class TradeCreate(BaseModel):
    ticker: str
    direction: str = "long"
    entry_date: date
    exit_date: Optional[date] = None
    entry_price: float
    exit_price: Optional[float] = None
    shares: float
    setup: str = ""
    notes: str = ""
    outcome: Optional[str] = None


class TradeUpdate(TradeCreate):
    pass


@router.get("")
async def list_trades(current_user: dict = Depends(get_current_user)):
    return db.get_trade_journal(current_user["id"])


@router.post("")
async def create_trade_route(body: TradeCreate, current_user: dict = Depends(get_current_user)):
    return db.create_trade(current_user["id"], body.model_dump())


@router.put("/{trade_id}")
async def update_trade_route(trade_id: int, body: TradeUpdate, current_user: dict = Depends(get_current_user)):
    result = db.update_trade(current_user["id"], trade_id, body.model_dump())
    if not result:
        raise HTTPException(status_code=404, detail="Trade not found")
    return result


@router.delete("/{trade_id}")
async def delete_trade_route(trade_id: int, current_user: dict = Depends(get_current_user)):
    deleted = db.delete_trade(current_user["id"], trade_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Trade not found")
    return {"deleted": trade_id}
