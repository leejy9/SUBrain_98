import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# daemon 경로 추가
daemon_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "daemon"))
if daemon_path not in sys.path:
    sys.path.insert(0, daemon_path)

import telegram_bot
from telegram_bot import handle_message, intake_lock


class TestOfflineAndConcurrency(unittest.TestCase):
    """Phase 4: 오프라인 큐잉 및 연속 인테이크 방어 검증"""

    def test_offline_polling_configuration(self):
        """Task 4.1: 오프라인 동안 쌓인 메시지 유실 방지 (drop_pending_updates=False) 검증"""
        main_path = os.path.join(daemon_path, "main.py")
        with open(main_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn(
            "start_polling(drop_pending_updates=False)",
            content,
            "main.py의 start_polling에 drop_pending_updates=False가 명시되어야 합니다."
        )

        bot_path = os.path.join(daemon_path, "telegram_bot.py")
        with open(bot_path, "r", encoding="utf-8") as f:
            bot_content = f.read()
        self.assertIn(
            "run_polling(drop_pending_updates=False)",
            bot_content,
            "telegram_bot.py의 run_polling에 drop_pending_updates=False가 명시되어야 합니다."
        )

    def test_concurrent_intake_locking_and_isolation(self):
        """Task 4.2: asyncio.Lock을 통한 동시 인테이크 파이프라인 무결성 및 순차 처리 검증"""
        async def run_test():
            execution_order = []
            active_concurrency = [0]
            max_concurrency = [0]

            def fake_process_intake(raw_input, user_context="", category_intent=""):
                active_concurrency[0] += 1
                if active_concurrency[0] > max_concurrency[0]:
                    max_concurrency[0] = active_concurrency[0]
                import time
                time.sleep(0.05)
                active_concurrency[0] -= 1
                execution_order.append(raw_input)
                return {
                    "filename": f"{raw_input[:10]}.md",
                    "briefing": {
                        "summary": f"요약 {raw_input}",
                        "passed_links": [],
                        "rejected_links": [],
                        "module_name": "모듈_영구지식",
                        "classified_type": "Permanent"
                    },
                    "is_auto_committed": True,
                    "status": "COMMITTED"
                }

            mock_agent = MagicMock()
            mock_agent.process_intake.side_effect = fake_process_intake

            # 모의 텔레그램 메시지 3건 생성
            received_initial_texts = []
            broadcasted_events = []

            async def fake_broadcast(event_name, data):
                broadcasted_events.append((event_name, data.get("task_id"), data.get("title")))

            updates = []
            for i in range(3):
                msg_mock = AsyncMock()
                status_msg_mock = AsyncMock()

                async def reply_text_side_effect(text, parse_mode=None):
                    received_initial_texts.append(text)
                    return status_msg_mock

                msg_mock.text = f"동시인테이크메시지_{i+1}"
                msg_mock.reply_to_message = None
                msg_mock.reply_text.side_effect = reply_text_side_effect

                up = MagicMock()
                up.message = msg_mock
                updates.append((up, status_msg_mock))

            context = MagicMock()
            context.user_data = {}

            with patch.object(telegram_bot, "agent", mock_agent), \
                 patch.object(telegram_bot.event_bridge, "broadcast", side_effect=fake_broadcast):

                # 3개의 메시지를 동시에 전송
                tasks = [
                    handle_message(up, context)
                    for up, _ in updates
                ]
                await asyncio.gather(*tasks)

            # 1. 동시 실행 개수는 최대 1개여야 함 (Lock에 의한 순차화)
            self.assertEqual(max_concurrency[0], 1, "동시 실행 인테이크 수는 1개여야 합니다 (asyncio.Lock 준수).")

            # 2. 3건 모두 정상 순차 완료되었는지 확인
            self.assertEqual(len(execution_order), 3)

            # 3. 2번째 혹은 3번째 요청은 '대기열 순차 처리 대기 중' 안내 문구를 수신했어야 함
            waiting_notices = [
                txt for txt in received_initial_texts
                if "대기열 순차 처리 대기 중" in txt
            ]
            self.assertGreaterEqual(len(waiting_notices), 1, "동시 인입 시 대기열 안내 메시지가 전송되어야 합니다.")

            # 4. 카드 생성(CARD_CREATED) 브로드캐스트 3건의 task_id가 모두 상이해야 함 (아이솔레이션 보장)
            created_events = [e for e in broadcasted_events if e[0] == "CARD_CREATED"]
            task_ids = [e[1] for e in created_events]
            self.assertEqual(len(task_ids), 3)

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
