"""디스코드 웹훅 발송. backend와 airflow가 함께 쓰므로 DB·설정 모듈에 기대지 않는다(호출 측이 설정 행을 읽어 넘긴다)."""
import os
import time
from typing import Any, Mapping, Optional, Sequence, Tuple

import httpx

MAX_CONTENT = 2000  # 디스코드 메시지 content 최대 길이
SAFE_CONTENT = 1900  # 한 메시지로 묶을 때 쓰는 길이 — 최대 길이에 여유를 둔다

# discord_settings 행이 없을 때의 값. 비중변화(%p)·신규편입(%p)·일일 리포트 1일 수익률(%) 기준
DEFAULT_SETTINGS = {"enabled": True, "threshold": 3.0, "added_threshold": 2.0, "rise_threshold": 3.0}


def resolve_settings(row: Optional[Mapping[str, Any]], env: Mapping[str, str] = os.environ) -> dict:
    """관리자 페이지에서 저장한 설정이 우선, 저장 전이거나 주소가 비었으면 환경변수 DISCORD_WEBHOOK_URL.

    꺼져 있으면 webhook_url은 None이다 — 보내는 쪽은 webhook_url만 보면 된다.
    """
    settings = {**DEFAULT_SETTINGS, "webhook_url": None}
    if row:
        settings.update({k: row[k] for k in (*DEFAULT_SETTINGS, "webhook_url") if row.get(k) is not None})
    if not settings["webhook_url"]:
        settings["webhook_url"] = env.get("DISCORD_WEBHOOK_URL") or None
    if not settings["enabled"]:
        settings["webhook_url"] = None
    return settings


def clip(text: str, limit: int = MAX_CONTENT) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def post_messages(webhook_url: str, messages: Sequence[str], start: int = 0) -> Tuple[int, Optional[str]]:
    """messages[start:]를 차례로 보낸다. (보낸 데까지의 개수, 실패 설명 — 성공이면 None).

    실패한 뒤 다시 보낼 때 앞의 개수를 start로 넘기면 이미 간 메시지를 되풀이하지 않는다.
    httpx 예외 메시지엔 웹훅 주소(토큰 포함)가 들어가므로 종류·상태코드만 남긴다.
    """
    sent = start
    try:
        with httpx.Client(timeout=10) as client:
            for message in messages[start:]:
                resp = client.post(webhook_url, json={"content": message})
                if resp.status_code == 429:  # rate limit — 안내된 만큼 기다렸다 한 번 재시도
                    time.sleep(float(resp.json().get("retry_after", 1)))
                    resp = client.post(webhook_url, json={"content": message})
                resp.raise_for_status()
                sent += 1
    except httpx.HTTPError as e:
        status = e.response.status_code if isinstance(e, httpx.HTTPStatusError) else None
        return sent, f"{type(e).__name__} status={status}"
    return sent, None
