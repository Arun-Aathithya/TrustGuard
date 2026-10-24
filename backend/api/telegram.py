"""
Telegram bot endpoints.

  GET  /api/telegram/status   bot state for the Hardware page (no secrets: never the token or chat ids)
  POST /api/telegram/test     (admin) send a test message to every authorised chat
"""
from fastapi import APIRouter, Depends

from api.security import require_admin
from services import telegram_bot

router = APIRouter(prefix="/api/telegram", tags=["telegram"])


@router.get("/status")
def get_status():
    return telegram_bot.telegram_status()


@router.post("/test", dependencies=[Depends(require_admin)])
def send_test():
    return telegram_bot.send_test_message()
