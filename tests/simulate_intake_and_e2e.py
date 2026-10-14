import asyncio
import os
import sys

# daemon 경로 추가
daemon_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "daemon"))
if daemon_path not in sys.path:
    sys.path.insert(0, daemon_path)

from agent_core import ConstitutionalAgent
from event_bridge import event_bridge
import websockets
import json

async def trigger_intake():
    print("🚀 [E2E] 1. 신규 인테이크 투입 시작...")
    raw_text = (
        "2026년 차세대 에이전트 분산 아키텍처에서 단일 장애점(SPOF)을 제거하기 위한 "
        "멀티 리전 세션 페일오버 및 분산 락 하네스 설계 원칙."
    )
    user_intent = "향후 대규모 동시성 인프라 운영 시 핵심 가이드라인으로 활용할 것"

    agent = ConstitutionalAgent()
    result = agent.process_intake(raw_text, user_context=user_intent, category_intent="Permanent")
    
    filename = result["filename"]
    print(f"✓ 인테이크 완료: 파일명 = {filename}, 상태 = {result.get('status')}")
    print(f"✓ 생성 파일 경로: {result.get('filepath')}")

    # WebSocket을 통해 브로드캐스트 상태 알림
    uri = "ws://127.0.0.1:8765"
    async with websockets.connect(uri) as ws:
        # 카드 목록 새로고침 요청
        await ws.send(json.dumps({"action": "GET_ALL_CARDS"}))
        resp = await ws.recv()
        data = json.loads(resp)
        print(f"✓ 대시보드 WebSocket 응답 수신: 총 {len(data.get('cards', []))}개 카드 확인.")

if __name__ == "__main__":
    asyncio.run(trigger_intake())
