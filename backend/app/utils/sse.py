"""SSE(Server-Sent Events) 스트림 조각: 이벤트 한 건의 포맷과, 오래 조용할 때 끼우는 heartbeat."""
import asyncio
import json
from typing import Any, AsyncIterator

# 모델이 오래 생각하는 동안에도 프록시(nginx 기본 60초)가 유휴 연결을 끊지 않도록 보내는 주기
HEARTBEAT_INTERVAL = 15.0
DONE = "data: [DONE]\n\n"  # 스트림 끝 표시 (프런트가 이걸 보고 읽기를 멈춘다)


def sse_event(data: Any) -> str:
    """JSON으로 직렬화한 이벤트 한 건 (`data: ...` + 빈 줄)."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def with_heartbeat(chunks: AsyncIterator[str], interval: float = HEARTBEAT_INTERVAL) -> AsyncIterator[str]:
    """chunks를 그대로 흘려보내되, interval 동안 아무것도 없으면 SSE 주석(`: ping`)을 끼워 넣는다.

    에이전트 스트림은 진입한 task 안에서만 닫을 수 있어서, 한 task가 끝까지 돌리고 큐로 넘겨받는다.
    """
    queue: asyncio.Queue = asyncio.Queue()
    done = object()

    async def produce():
        try:
            async for chunk in chunks:
                await queue.put(chunk)
        finally:
            await queue.put(done)

    producer = asyncio.create_task(produce())
    try:
        while True:
            try:
                chunk = await asyncio.wait_for(queue.get(), timeout=interval)
            except asyncio.TimeoutError:
                yield ": ping\n\n"
                continue
            if chunk is done:
                break
            yield chunk
        await producer  # 생산 중 예외가 있었으면 여기서 드러난다
    finally:
        producer.cancel()  # 클라이언트가 끊으면 에이전트 실행도 멈춘다
