import asyncio
import json
import logging
import datetime
import re
from pathlib import Path
from typing import Set, Dict, Any, Optional
import websockets

from config import VAULT_DIR, GEMINI_API_KEY

logger = logging.getLogger(__name__)


CARDS_STORE_PATH = Path(__file__).parent / "cards_store.json"


class EventBridge:
    """백엔드 데몬과 프론트엔드 대시보드를 실시간으로 잇는 WebSocket 양방향 이벤트 브릿지"""

    def __init__(self, host: str = "127.0.0.1", port: int = 8765):
        self.host = host
        self.port = port
        self.clients: Set[Any] = set()
        self.cards: Dict[str, Dict[str, Any]] = {}
        self._server = None
        self.load_cards()

    def load_cards(self):
        """디스크 파일(cards_store.json)에서 카드 상태를 복원합니다."""
        if CARDS_STORE_PATH.exists():
            try:
                data = json.loads(CARDS_STORE_PATH.read_text(encoding="utf-8"))
                for item in data:
                    card_id = item.get("id") or item.get("task_id")
                    if card_id:
                        item["id"] = card_id
                        item["task_id"] = card_id
                        self.cards[card_id] = item
                logger.info(f"[EventBridge] 영구 저장소에서 {len(self.cards)}개 카드 상태 복원 완료")
            except Exception as e:
                logger.error(f"[EventBridge] 카드 복원 실패: {e}")

    def save_cards(self):
        """현재 인메모리 카드 상태를 디스크 파일(cards_store.json)에 영구 저장합니다."""
        try:
            CARDS_STORE_PATH.write_text(
                json.dumps(list(self.cards.values()), ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            logger.debug(f"[EventBridge] {len(self.cards)}개 카드 영구 저장 완료")
        except Exception as e:
            logger.error(f"[EventBridge] 카드 저장 실패: {e}")

    async def register(self, websocket):
        self.clients.add(websocket)
        client_addr = getattr(websocket, "remote_address", "client")
        logger.info(f"[EventBridge] 대시보드 클라이언트 연결됨: {client_addr}")
        try:
            # 1. 연결 즉시 환영 및 상태 확인 이벤트 전송 (최신순 LIFO 정렬)
            welcome_event = {
                "type": "SYSTEM_CONNECTED",
                "data": {
                    "status": "LIVE",
                    "clients": len(self.clients),
                    "vault_dir": str(VAULT_DIR),
                    "active_cards": list(self.cards.values())
                }
            }
            await websocket.send(json.dumps(welcome_event, ensure_ascii=False))

            # 2. 클라이언트로부터 수신되는 실시간 메시지 양방향 루프
            async for raw_message in websocket:
                try:
                    msg = json.loads(raw_message)
                    await self.handle_client_message(websocket, msg)
                except Exception as e:
                    logger.error(f"[EventBridge] 메시지 처리 오류: {e}", exc_info=True)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.clients.remove(websocket)
            logger.info("[EventBridge] 대시보드 클라이언트 연결 해제됨")

    async def handle_client_message(self, websocket, msg: Dict[str, Any]):
        msg_type = msg.get("type")
        logger.info(f"[EventBridge] 📩 클라이언트 요청 수신: {msg_type}")

        if msg_type == "COMMIT_CARD":
            # [Stage 07] 실제 로컬 옵시디언 볼트에 .md 파일 영구 저장 (Two-Way Sync)
            task_id = msg.get("task_id", f"DOC-{datetime.datetime.now().strftime('%m%d-%H%M')}")
            title = msg.get("title", "무제_노트")
            filename = msg.get("filename", "")
            content = msg.get("content", "")
            wikilinks = msg.get("wikilinks", [])
            tags = msg.get("tags", ["#SUBrain_98"])
            markdown_content = msg.get("markdown_content") or (self.cards.get(task_id, {}).get("markdown_content", ""))

            if not filename:
                safe_title = re.sub(r'[\\/*?:"<>|]', "", title).strip() or task_id
                filename = f"{safe_title}.md"
            elif not filename.endswith(".md"):
                filename += ".md"

            target_file = VAULT_DIR / filename

            # 기존 정규화된 마크다운 전문(CCIA/STAR/Frontmatter)이 있으면 그대로 보존하여 디스크에 기록
            if markdown_content:
                md_text = markdown_content
            else:
                now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                md_text = f"""---
aliases: [{title}]
tags: {json.dumps(tags, ensure_ascii=False)}
created: {now_str}
status: 완료
type: Permanent
task_id: {task_id}
---

# {title}

## 📌 핵심 요약 & 컨텍스트
{content}

## 🔗 연관 지식 노드
{chr(10).join([f'- {wl}' for wl in wikilinks]) if wikilinks else "- [[MOC_지식원리]]"}

---
*Generated & Committed via SUBrain_98 Virtual AI Company Workstation*
"""

            # 실제 Mac 디스크 파일 쓰기
            target_file.write_text(md_text, encoding="utf-8")
            logger.info(f"[EventBridge] ✅ 로컬 옵시디언 볼트에 파일 영구 저장 성공 (Two-Way Sync): {target_file}")

            # 상태 갱신
            if task_id in self.cards:
                self.cards[task_id]["status"] = "COMMITTED"
                self.cards[task_id]["filename"] = filename
                self.cards[task_id]["markdown_content"] = md_text
                self.save_cards()

            # 성공 이벤트 브로드캐스트
            await self.broadcast("CARD_COMMITTED", {
                "task_id": task_id,
                "filename": filename,
                "filepath": str(target_file),
                "markdown_content": md_text,
                "message": f"'{filename}' 파일이 옵시디언 볼트에 안전하게 영구 저장되었습니다."
            })

        elif msg_type in ("SAVE_CARD_CONTENT", "SYNC_DISK_FILE"):
            # [Phase 2] 대시보드 인라인 편집기에서 디스크 직접 저장 (⌘S)
            task_id = msg.get("task_id", "")
            filename = msg.get("filename", "")
            new_content = msg.get("markdown_content", "")

            if not filename and task_id in self.cards:
                filename = self.cards[task_id].get("filename", "")
            if not filename:
                filename = f"{task_id}.md"
            elif not filename.endswith(".md"):
                filename += ".md"

            target_file = VAULT_DIR / filename
            target_file.write_text(new_content, encoding="utf-8")
            logger.info(f"[EventBridge] 💾 인라인 에디터 디스크 파일 실시간 동기화 완료: {target_file}")

            if task_id in self.cards:
                self.cards[task_id]["markdown_content"] = new_content
                self.cards[task_id]["filename"] = filename
                self.cards[task_id]["status"] = "COMMITTED"
                self.cards[task_id]["warning"] = None
                if "integrity" in self.cards[task_id]:
                    self.cards[task_id]["integrity"]["score"] = 100.0
                self.save_cards()

            await self.broadcast("CARD_COMMITTED", {
                "task_id": task_id,
                "filename": filename,
                "filepath": str(target_file),
                "markdown_content": new_content,
                "message": f"'{filename}' 파일이 Mac 디스크에 즉시 동기화되었습니다."
            })

        elif msg_type == "EXECUTE_COPILOT":
            # [Stage 04 & 07] Gemini를 활용한 지식 실시간 교정 및 디스크 즉각 반영
            task_id = msg.get("task_id", "")
            prompt = msg.get("prompt", "")
            current_synthesis = msg.get("synthesis", "")
            title = msg.get("title", "")

            try:
                from google import genai
                client = genai.Client(api_key=GEMINI_API_KEY)
                system_prompt = f"""당신은 사용자의 옵시디언 지식 베이스를 관리하는 AI 코파일럿입니다.
[현재 카드 제목]: {title}
[현재 요약 본문]:
{current_synthesis}

[사용자 수정 지시사항]:
{prompt}

지시사항을 명확히 반영하여 한 차원 더 높은 완성도로 교정된 본문 요약을 작성하세요.
부연 설명이나 인사말 없이 오직 교정된 최종 본문 텍스트만 출력하세요."""

                resp = client.models.generate_content(
                    model="gemini-3.1-flash-lite",
                    contents=[system_prompt]
                )
                updated_text = resp.text.strip()
                if updated_text.startswith("```"):
                    lines = updated_text.splitlines()
                    if lines[0].startswith("```"): lines = lines[1:]
                    if lines and lines[-1].startswith("```"): lines = lines[:-1]
                    updated_text = "\n".join(lines).strip()

                updated_md = None
                if task_id in self.cards:
                    card = self.cards[task_id]
                    card["synthesis"] = updated_text
                    filename = card.get("filename", f"{title}.md")
                    if not filename.endswith(".md"): filename += ".md"

                    # 마크다운 본문에 Copilot 교정 노트 적층
                    if "markdown_content" in card and card["markdown_content"]:
                        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                        card["markdown_content"] += f"\n\n> [!NOTE] 🤖 AI Copilot 교정 ({now_str})\n> 지시사항: {prompt}\n> {updated_text}\n"
                        updated_md = card["markdown_content"]
                        # 디스크 파일 실시간 동기화
                        target_file = VAULT_DIR / filename
                        target_file.write_text(card["markdown_content"], encoding="utf-8")
                        logger.info(f"[EventBridge] 💾 Copilot 디스크 파일 동기화 완료: {target_file}")
                    self.save_cards()

                await websocket.send(json.dumps({
                    "type": "COPILOT_RESULT",
                    "data": {
                        "task_id": task_id,
                        "updated_synthesis": updated_text,
                        "updated_markdown_content": updated_md,
                        "prompt": prompt,
                        "message": "AI 지시사항이 반영되어 본문 및 디스크 파일이 교정되었습니다."
                    }
                }, ensure_ascii=False))
            except Exception as e:
                logger.error(f"[EventBridge] 코파일럿 실행 실패: {e}")
                await websocket.send(json.dumps({
                    "type": "COPILOT_ERROR",
                    "data": {"task_id": task_id, "error": str(e)}
                }, ensure_ascii=False))

        elif msg_type == "APPLY_AUTO_FIX":
            task_id = msg.get("task_id", "")
            code = msg.get("code", "")
            updated_md = msg.get("markdown_content", "")
            
            if task_id in self.cards:
                card = self.cards[task_id]
                card["warning"] = None
                card["status"] = "COMMITTED"
                if "integrity" in card:
                    card["integrity"]["score"] = 100.0
                    for check in card["integrity"].get("checklist", []):
                        check["passed"] = True

                if updated_md:
                    card["markdown_content"] = updated_md
                
                # 디스크 파일 실시간 동기화
                filename = card.get("filename", "")
                if filename and card.get("markdown_content"):
                    target_file = VAULT_DIR / filename
                    target_file.write_text(card["markdown_content"], encoding="utf-8")
                    logger.info(f"[EventBridge] 💾 Auto-Fix 디스크 파일 실시간 동기화 완료: {target_file}")

                self.save_cards()

            await self.broadcast("AUTO_FIX_APPLIED", {
                "task_id": task_id,
                "code": code,
                "message": f"규칙 {code} 교정안이 적용되어 디스크 파일과 100% 동기화되었습니다."
            })
            await self.broadcast("CARD_COMMITTED", {
                "task_id": task_id,
                "filename": self.cards.get(task_id, {}).get("filename", ""),
                "message": "규칙 교정 완료 후 볼트에 영구 저장되었습니다."
            })

        elif msg_type in ("DISCARD_NODE", "TOMBSTONE_NODE"):
            # [Tombstone 소프트 삭제 핸들러]
            task_id = msg.get("task_id", "")
            filename = msg.get("filename", "")
            reason = msg.get("reason", "신규 사실로 인한 반증 및 전제 무효화")
            content = msg.get("content", "")

            if task_id in self.cards:
                if not filename:
                    filename = self.cards[task_id].get("filename", "")
                if not content:
                    content = self.cards[task_id].get("markdown_content") or self.cards[task_id].get("content", "")

            if not filename:
                filename = f"{task_id}.md"

            try:
                from agent_core import ConstitutionalAgent
                agent = ConstitutionalAgent()
                res = agent.discard_node_tombstone(filename, reason, content=content)
                if res.get("success"):
                    if task_id in self.cards:
                        self.cards[task_id]["status"] = "TOMBSTONE"
                        self.cards[task_id]["discard_reason"] = reason
                        self.cards[task_id]["discarded_at"] = res.get("discarded_at")
                        self.save_cards()
                    await self.broadcast("NODE_DISCARDED", {
                        "task_id": task_id,
                        "filename": filename,
                        "reason": reason,
                        "discarded_at": res.get("discarded_at"),
                        "message": f"'{filename}'이 _archive/tombstones/로 안전 격리 보존되었습니다."
                    })
                else:
                    await websocket.send(json.dumps({"type": "DISCARD_ERROR", "data": res}, ensure_ascii=False))
            except Exception as e:
                logger.error(f"[EventBridge] 묘비 폐기 처리 오류: {e}")

        elif msg_type == "FETCH_MORNING_INSIGHTS":
            # [아침 인사이트 큐 요청]
            try:
                from agent_core import ConstitutionalAgent
                agent = ConstitutionalAgent()
                insights = agent.generate_morning_insights()
                await websocket.send(json.dumps({
                    "type": "MORNING_INSIGHTS_RESULT",
                    "data": insights
                }, ensure_ascii=False))
            except Exception as e:
                logger.error(f"[EventBridge] 아침 인사이트 생성 오류: {e}")

        elif msg_type == "APPROVE_INSIGHT":
            # [아침 인사이트 1클릭 승인 -> 디스크 파일 양방향 링크 주입]
            insight_id = msg.get("insight_id", "")
            source_node = msg.get("source_node", "")
            target_node = msg.get("target_node", "")
            insight_text = msg.get("transfer_insight", "")

            try:
                src_path = VAULT_DIR / f"{source_node}.md" if not source_node.endswith(".md") else VAULT_DIR / source_node
                tgt_path = VAULT_DIR / f"{target_node}.md" if not target_node.endswith(".md") else VAULT_DIR / target_node

                now_str = datetime.datetime.now().strftime("%Y-%m-%d")
                if src_path.exists():
                    src_text = src_path.read_text(encoding="utf-8")
                    link_entry = f"\n- [[{target_node[:-3] if target_node.endswith('.md') else target_node}]] :: [SERENDIPITY_TRANSFER] (승인: {now_str}) -> {insight_text}"
                    if "## 🔗" in src_text:
                        src_text = src_text.replace("## 🔗", f"## 🔗{link_entry}\n")
                    else:
                        src_text += f"\n\n## 🔗 인지적 연결망\n{link_entry}"
                    src_path.write_text(src_text, encoding="utf-8")

                await self.broadcast("INSIGHT_APPROVED", {
                    "insight_id": insight_id,
                    "source_node": source_node,
                    "target_node": target_node,
                    "message": f"'{source_node}'와 '{target_node}' 간의 전이 인사이트 위키링크가 디스크에 확정되었습니다."
                })
            except Exception as e:
                logger.error(f"[EventBridge] 인사이트 승인 처리 실패: {e}")

        elif msg_type == "ENRICH_CARD_EXECUTIVE":
            # [직급별 심층 검토 요청]
            task_id = msg.get("task_id", "")
            title = msg.get("title", "")
            content = msg.get("content", "")
            source_date = msg.get("source_date", "")

            try:
                from agent_core import ConstitutionalAgent
                agent = ConstitutionalAgent()
                rev = agent.perform_executive_review(title, content, source_date)
                if task_id in self.cards:
                    self.cards[task_id]["executive_review"] = rev
                    self.save_cards()
                await websocket.send(json.dumps({
                    "type": "EXECUTIVE_REVIEW_RESULT",
                    "data": {"task_id": task_id, "executive_review": rev}
                }, ensure_ascii=False))
            except Exception as e:
                logger.error(f"[EventBridge] 직급 심사 오류: {e}")

    async def broadcast(self, event_type: str, data: Dict[str, Any]):
        """모든 연결된 대시보드 화면에 실시간 이벤트 브로드캐스팅"""
        card_id = data.get("id") or data.get("task_id")
        if card_id:
            data["id"] = card_id
            data["task_id"] = card_id
            if event_type in ("CARD_CREATED", "CARD_STAGED"):
                new_cards = {card_id: data}
                for k, v in self.cards.items():
                    if k != card_id:
                        new_cards[k] = v
                self.cards = new_cards
                self.save_cards()

        if not self.clients:
            return
        message = json.dumps({"type": event_type, "data": data}, ensure_ascii=False)
        await asyncio.gather(
            *[client.send(message) for client in self.clients],
            return_exceptions=True
        )
        logger.debug(f"[EventBridge] 브로드캐스트 전송 완료: {event_type} (수신 클라이언트: {len(self.clients)}개)")

    async def start(self):
        self._server = await websockets.serve(self.register, self.host, self.port)
        logger.info(f"[EventBridge] WebSocket 실시간 서버 가동 완료: ws://{self.host}:{self.port}")
        return self._server


# 싱글톤 인스턴스
event_bridge = EventBridge()
