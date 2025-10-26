from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.services.options_gateway import OptionGateway, make_option_gateway

router = APIRouter(prefix="/options", tags=["options"])


@router.get("/chain")
async def chain(
    symbol: str = Query(..., min_length=1),
    gw: OptionGateway = Depends(make_option_gateway),
):
    try:
        data = await gw.chain(symbol)
    except ValueError as exc:  # noqa: BLE001 - validation guard
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not data:
        raise HTTPException(status_code=404, detail="Not Found")
    return data


@router.get("/greeks")
async def greeks(
    contract: str = Query(..., min_length=3),
    gw: OptionGateway = Depends(make_option_gateway),
):
    try:
        data = await gw.greeks(contract)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not data:
        raise HTTPException(status_code=404, detail="Not Found")
    return data


__all__ = ["router"]
