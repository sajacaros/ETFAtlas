"""앱에서 디스코드로 보내기. 설정은 비중 변화 알림(Airflow)과 같은 discord_settings 행을 같은 규칙으로 읽는다."""
import asyncio
import logging
from typing import List, Optional

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models.discord_setting import DiscordSetting
from ..utils import discord

logger = logging.getLogger(__name__)


def load_settings(db: Session) -> dict:
    setting = db.get(DiscordSetting, 1)
    row = None if setting is None else {
        "enabled": setting.enabled, "webhook_url": setting.webhook_url, "threshold": setting.threshold,
        "added_threshold": setting.added_threshold, "rise_threshold": setting.rise_threshold,
    }
    return discord.resolve_settings(row)


def webhook_url() -> Optional[str]:
    """보낼 웹훅 주소. 관리자가 디스코드 알림을 꺼 두었거나 주소가 없으면 None."""
    with SessionLocal() as db:
        return load_settings(db)["webhook_url"]


async def send(messages: List[str], purpose: str) -> Optional[str]:
    """보내지 못하면 그 이유. 웹훅이 없거나 꺼져 있으면 보내지 않고 None."""
    url = await asyncio.to_thread(webhook_url)
    if not url:
        logger.info("%s: Discord webhook is off, not sending", purpose)
        return None
    _, error = await asyncio.to_thread(discord.post_messages, url, messages)
    if error:
        logger.warning("%s Discord notification failed: %s", purpose, error)
    return error
