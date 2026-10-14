import asyncio
import http
import json
import logging
import datetime
import re
from pathlib import Path
from typing import Set, Dict, Any, Optional
import websockets

from config import VAULT_DIR, GEMINI_API_KEY
import vault_io
from vault_io import ConflictError
import fact_guard

logger = logging.getLogger(__name__)


CARDS_STORE_PATH = Path(__file__).parent / "cards_store.json"


class EventBridge:
    """백엔드 데몬과 프론트엔드 대시보드를 실시간으로 잇는 WebSocket 양방향 이벤트 브릿지"""

    def __init__(self, host: str = "127.0.0.1", port: int = 8765):
        self.host = host
        self.port = port
        self.clients: Set[Any] = set()
        self.cards: Dict[str, Dict[str, Any]] = {}
        self.critic_enabled: bool = True
        self._server = None
        self.load_cards()

    def load_cards(self):
        """디스크 파일(cards_store.json)에서 카드 상태를 복원하고 볼트 디스크와 SSOT를 동기화합니다."""
        if CARDS_STORE_PATH.exists():
            try:
                data = json.loads(CARDS_STORE_PATH.read_text(encoding="utf-8"))
                from scoring_engine import ScoringEngine
                from vault_indexer import VaultIndexer
                v_indexer = VaultIndexer()
                vault_notes = v_indexer.list_notes()

                for item in data:
                    card_id = item.get("id") or item.get("task_id")
                    if card_id:
                        item["id"] = card_id
                        item["task_id"] = card_id
                        # [SSOT 불변식]: 실제 볼트 파일이 디스크에 존재하면 마크다운 전문과 해시를 디스크 기준으로 갱신
                        filename = item.get("filename")
                        if filename:
                            disk_info = vault_io.read_note(filename)
                            if not disk_info and not filename.startswith("_inbox/"):
                                disk_info = vault_io.read_note(f"_inbox/{filename}")
                            if disk_info:
                                item["markdown_content"] = disk_info["content"]
                                item["base_hash"] = disk_info["hash"]
                                item["filepath"] = str(VAULT_DIR / disk_info["rel_path"])

                        # [Phase 2] 3대 보조 스코어링 메타데이터 주입
                        if "scoring_metadata" not in item or not item["scoring_metadata"]:
                            content_text = item.get("markdown_content") or item.get("raw_content") or item.get("title", "")
                            user_ctx = item.get("user_context") or item.get("raw_intent") or ""
                            score_meta = ScoringEngine.compute_score(content_text, user_ctx, vault_notes)
                            item["scoring_metadata"] = score_meta.model_dump()
                            item["triage_recommendation"] = score_meta.triage_recommendation.value

                        self.cards[card_id] = item
                logger.info(f"[EventBridge] 영구 저장소에서 {len(self.cards)}개 카드 상태 복원 및 볼트 디스크 SSOT 동기화 완료")
            except Exception as e:
                logger.error(f"[EventBridge] 카드 복원 실패: {e}")

        # [SSOT 불변식 2]: 실제 디스크 _inbox/ 디렉터리에 존재하는 파일들을 카드 큐에 자동 등록
        try:
            inbox_dir = VAULT_DIR / "_inbox"
            if inbox_dir.exists():
                for f in sorted(inbox_dir.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True):
                    existing = any(
                        c.get("filename") in [f.name, f"_inbox/{f.name}"]
                        or c.get("title") == f.stem
                        for c in self.cards.values()
                    )
                    if not existing:
                        disk_info = vault_io.read_note(f"_inbox/{f.name}")
                        if disk_info:
                            card_id = f"INBOX-{f.stem[:12]}"
                            created_str = datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                            new_card = {
                                "id": card_id,
                                "task_id": card_id,
                                "title": f.stem,
                                "filename": f"_inbox/{f.name}",
                                "status": "STAGED",
                                "stage": "INBOX_REVIEW",
                                "markdown_content": disk_info["content"],
                                "base_hash": disk_info["hash"],
                                "filepath": str(f),
                                "created_at": created_str,
                                "tags": ["#_inbox", "#SUBrain_98"],
                                "summary": f"인박스 미검토 노트: {f.stem}",
                            }
                            # LIFO: 최신 인박스 노트를 큐 앞단에 배치
                            self.cards = {card_id: new_card, **self.cards}
                            logger.info(f"[EventBridge] 볼트 _inbox 신규 노트 자동 발굴 및 카드 큐 등록: {f.name}")
                self.save_cards()
        except Exception as e:
            logger.error(f"[EventBridge] _inbox 동기화 실패: {e}")

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
                    "critic_enabled": self.critic_enabled,
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
            # [Stage 07 & INV-2] 실제 로컬 옵시디언 볼트에 .md 파일 영구 저장 (단일 관문 vault_io 경유)
            task_id = msg.get("task_id", f"DOC-{datetime.datetime.now().strftime('%m%d-%H%M')}")
            title = msg.get("title", "무제_노트")
            filename = msg.get("filename", "")
            content = msg.get("content", "")
            wikilinks = msg.get("wikilinks", [])
            tags = msg.get("tags", ["#SUBrain_98"])
            markdown_content = msg.get("markdown_content") or (self.cards.get(task_id, {}).get("markdown_content", ""))
            base_hash = msg.get("base_hash")

            if not filename:
                safe_title = re.sub(r'[\\/*?:"<>|]', "", title).strip() or task_id
                filename = f"{safe_title}.md"
            elif not filename.endswith(".md"):
                filename += ".md"

            # 기존 정규화된 마크다운 전문(CCIA/STAR/Frontmatter)이 없으면 기본 템플릿 생성
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

            inbox_note = vault_io.read_note(f"_inbox/{filename}")
            current_note = vault_io.read_note(filename)

            try:
                if inbox_note and not current_note:
                    # _inbox에 격리되어 있던 노드를 검토 확정하여 정식 볼트 루트로 이동
                    vault_io.safe_write(
                        f"_inbox/{filename}",
                        md_text,
                        expected_hash=base_hash,
                        reason="인박스 검토 확정 전 본문 갱신",
                        actor="user"
                    )
                    move_res = vault_io.move_from_inbox(f"_inbox/{filename}")
                    new_hash = move_res["new_hash"]
                    backup_id = move_res["backup_id"]
                    actual_rel_path = move_res["rel_path"]
                else:
                    # 이미 볼트 루트에 있는 파일이거나 신규 파일
                    write_res = vault_io.safe_write(
                        filename,
                        md_text,
                        expected_hash=base_hash,
                        reason="카드 확정 영구 저장",
                        actor="user"
                    )
                    new_hash = write_res["new_hash"]
                    backup_id = write_res["backup_id"]
                    actual_rel_path = write_res["rel_path"]

                target_file = VAULT_DIR / actual_rel_path

                # 상태 갱신
                if task_id in self.cards:
                    self.cards[task_id]["status"] = "COMMITTED"
                    self.cards[task_id]["filename"] = filename
                    self.cards[task_id]["markdown_content"] = md_text
                    self.cards[task_id]["base_hash"] = new_hash
                    self.cards[task_id]["filepath"] = str(target_file)
                    self.cards[task_id]["warning"] = None
                    if "integrity" in self.cards[task_id]:
                        self.cards[task_id]["integrity"]["score"] = 100.0
                    self.save_cards()

                # 성공 이벤트 브로드캐스트
                await self.broadcast("CARD_COMMITTED", {
                    "task_id": task_id,
                    "filename": filename,
                    "filepath": str(target_file),
                    "markdown_content": md_text,
                    "hash": new_hash,
                    "backup_id": backup_id,
                    "message": f"'{filename}' 파일이 옵시디언 볼트에 안전하게 영구 저장되었습니다."
                })

                # 요청 클라이언트에 WRITE_ACK 반환
                await websocket.send(json.dumps({
                    "type": "WRITE_ACK",
                    "data": {
                        "task_id": task_id,
                        "filename": filename,
                        "hash": new_hash,
                        "backup_id": backup_id,
                        "status": "COMMITTED",
                        "message": f"'{filename}' 파일이 영구 저장되었습니다."
                    }
                }, ensure_ascii=False))

            except ConflictError as e:
                logger.warning(f"[EventBridge] 쓰기 충돌 발생: {e}")
                await websocket.send(json.dumps({
                    "type": "WRITE_CONFLICT",
                    "data": {
                        "task_id": task_id,
                        "filename": filename,
                        "current_hash": e.current_hash,
                        "message": "파일이 외부(옵시디언 등)에서 변경되었습니다. 최신 버전을 확인 후 다시 시도하세요."
                    }
                }, ensure_ascii=False))
            except Exception as e:
                logger.error(f"[EventBridge] COMMIT_CARD 저장 실패: {e}", exc_info=True)
                await websocket.send(json.dumps({
                    "type": "WRITE_ERROR",
                    "data": {"task_id": task_id, "error": str(e)}
                }, ensure_ascii=False))

        elif msg_type in ("SAVE_CARD_CONTENT", "SYNC_DISK_FILE"):
            # [Phase 2 & INV-2] 대시보드 인라인 편집기에서 디스크 직접 저장 (⌘S) - 단일 관문 경유
            task_id = msg.get("task_id", "")
            filename = msg.get("filename", "")
            new_content = msg.get("markdown_content", "")
            base_hash = msg.get("base_hash")

            if not filename and task_id in self.cards:
                filename = self.cards[task_id].get("filename", "")
            if not filename:
                filename = f"{task_id}.md"
            elif not filename.endswith(".md"):
                filename += ".md"

            rel_write_path = filename
            if not (VAULT_DIR / filename).exists() and (VAULT_DIR / "_inbox" / filename).exists():
                rel_write_path = f"_inbox/{filename}"

            try:
                write_res = vault_io.safe_write(
                    rel_write_path,
                    new_content,
                    expected_hash=base_hash,
                    reason="인라인 에디터 실시간 동기화",
                    actor="user"
                )
                new_hash = write_res["new_hash"]
                backup_id = write_res["backup_id"]
                target_file = VAULT_DIR / rel_write_path

                if task_id in self.cards:
                    self.cards[task_id]["markdown_content"] = new_content
                    self.cards[task_id]["filename"] = filename
                    self.cards[task_id]["base_hash"] = new_hash
                    self.cards[task_id]["filepath"] = str(target_file)
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
                    "hash": new_hash,
                    "backup_id": backup_id,
                    "message": f"'{filename}' 파일이 Mac 디스크에 즉시 동기화되었습니다."
                })

                await websocket.send(json.dumps({
                    "type": "WRITE_ACK",
                    "data": {
                        "task_id": task_id,
                        "filename": filename,
                        "hash": new_hash,
                        "backup_id": backup_id,
                        "status": "COMMITTED",
                        "message": f"'{filename}' 파일이 동기화되었습니다."
                    }
                }, ensure_ascii=False))

            except ConflictError as e:
                logger.warning(f"[EventBridge] 인라인 저장 충돌: {e}")
                await websocket.send(json.dumps({
                    "type": "WRITE_CONFLICT",
                    "data": {
                        "task_id": task_id,
                        "filename": filename,
                        "current_hash": e.current_hash,
                        "message": "파일이 외부에서 변경되어 저장이 차단되었습니다. 최신 버전을 확인하세요."
                    }
                }, ensure_ascii=False))
            except Exception as e:
                logger.error(f"[EventBridge] 인라인 저장 실패: {e}", exc_info=True)
                await websocket.send(json.dumps({
                    "type": "WRITE_ERROR",
                    "data": {"task_id": task_id, "error": str(e)}
                }, ensure_ascii=False))

        elif msg_type == "EXECUTE_COPILOT":
            # [Stage 04 & INV-1] Gemini를 활용한 지식 실시간 대화 및 수정 제안 생성 (디스크 자동 쓰기 완전 금지)
            task_id = msg.get("task_id", "")
            prompt = msg.get("prompt", "")
            current_synthesis = msg.get("synthesis", "")
            title = msg.get("title", "")
            history = msg.get("history", [])
            filename = msg.get("filename", "")
            markdown_content = msg.get("markdown_content", "")

            # 카드 데이터 및 파일명/마크다운 본문 보강
            if not filename and task_id in self.cards:
                filename = self.cards[task_id].get("filename", "")
            if not filename:
                safe_title = re.sub(r'[\\/*?:"<>|]', "", title).strip() or task_id
                filename = f"{safe_title}.md"
            elif not filename.endswith(".md"):
                filename += ".md"

            disk_note = vault_io.read_note(filename) or vault_io.read_note(f"_inbox/{filename}")
            current_hash = disk_note["hash"] if disk_note else ""
            if not markdown_content and disk_note:
                markdown_content = disk_note["content"]

            try:
                from agent_core import ConstitutionalAgent
                agent = ConstitutionalAgent()

                copilot_result = agent.execute_devil_advocate_copilot(
                    title=title,
                    filename=filename,
                    markdown_content=markdown_content or current_synthesis,
                    prompt=prompt,
                    history=history,
                    synthesis=current_synthesis
                )

                assistant_response = copilot_result.get("assistant_response", "응답이 완료되었습니다.")
                is_modification = copilot_result.get("is_modification", False)
                updated_text = copilot_result.get("updated_synthesis", current_synthesis)
                updated_markdown = copilot_result.get("updated_markdown", "")

                # [INV-1 불변식 준수]: Copilot 실행 도중에는 디스크 파일을 절대 자동 변경하지 않는다.
                # 대신 제안(Proposal) 객체를 클라이언트로 전달하여 사용자가 본문 Diff를 검토하고 수동 승인하도록 유도한다.
                proposal_id = f"PROP-{int(datetime.datetime.now().timestamp())}" if is_modification else None

                # [INV-5 & FactGuard]: AI 수정 제안에 대해 원문 대조 수치 무결성 검증
                fact_report = None
                if is_modification and updated_markdown:
                    raw_quote = fact_guard.extract_raw_source_text(markdown_content)
                    raw_sources = [raw_quote] if raw_quote else [markdown_content]
                    fact_report = fact_guard.verify_figures(updated_markdown, raw_sources)
                    logger.info(f"[EventBridge] FactGuard 감사 완료: {fact_report['total_count']}개 수치 중 미확인 {len(fact_report['unverified'])}건")

                if task_id in self.cards:
                    card = self.cards[task_id]
                    if "chatHistory" not in card:
                        card["chatHistory"] = []
                    card["chatHistory"].append({"role": "user", "content": prompt})
                    card["chatHistory"].append({
                        "role": "assistant",
                        "content": assistant_response,
                        "proposal_id": proposal_id,
                        "is_modification": is_modification,
                        "fact_report": fact_report
                    })
                    if is_modification:
                        card["pending_proposal"] = {
                            "proposal_id": proposal_id,
                            "proposed_markdown": updated_markdown,
                            "updated_synthesis": updated_text,
                            "base_hash": current_hash,
                            "fact_report": fact_report
                        }
                    self.save_cards()

                await websocket.send(json.dumps({
                    "type": "COPILOT_RESULT",
                    "data": {
                        "task_id": task_id,
                        "prompt": prompt,
                        "assistant_response": assistant_response,
                        "is_modification": is_modification,
                        "proposal_id": proposal_id,
                        "updated_synthesis": updated_text,
                        "proposed_markdown": updated_markdown if is_modification else "",
                        "base_hash": current_hash,
                        "filename": filename,
                        "fact_report": fact_report,
                        "message": "AI 본문 수정 제안이 준비되었습니다. 변경 내용을 검토 후 [적용 및 저장]을 누르세요." if is_modification else "AI 답변이 완료되었습니다."
                    }
                }, ensure_ascii=False))

            except Exception as e:
                logger.error(f"[EventBridge] 코파일럿 실행 실패: {e}", exc_info=True)
                await websocket.send(json.dumps({
                    "type": "COPILOT_ERROR",
                    "data": {"task_id": task_id, "error": str(e)}
                }, ensure_ascii=False))

        elif msg_type == "APPLY_PROPOSAL":
            # [Stage 04 & INV-1] 사용자가 Diff를 검토한 후 명시적으로 제안을 수락했을 때만 디스크 단일 관문 쓰기 실행
            task_id = msg.get("task_id", "")
            filename = msg.get("filename", "")
            markdown_content = msg.get("markdown_content", "")
            base_hash = msg.get("base_hash")
            updated_synthesis = msg.get("updated_synthesis", "")

            if not filename and task_id in self.cards:
                filename = self.cards[task_id].get("filename", "")

            try:
                res = vault_io.safe_write(
                    filename,
                    markdown_content,
                    expected_hash=base_hash,
                    reason="AI Copilot 제안 사용자 승인 반영",
                    actor="user"
                )

                if task_id in self.cards:
                    card = self.cards[task_id]
                    card["markdown_content"] = markdown_content
                    if updated_synthesis:
                        card["synthesis"] = updated_synthesis
                    card["status"] = "COMMITTED"
                    card["base_hash"] = res["new_hash"]
                    card.pop("pending_proposal", None)
                    self.save_cards()

                await self.broadcast("CARD_COMMITTED", {
                    "task_id": task_id,
                    "filename": filename,
                    "filepath": str(VAULT_DIR / filename),
                    "markdown_content": markdown_content,
                    "hash": res["new_hash"],
                    "backup_id": res.get("backup_id"),
                    "message": f"'{filename}'에 AI 수정 제안이 성공적으로 반영 및 저장되었습니다."
                })

                await websocket.send(json.dumps({
                    "type": "WRITE_ACK",
                    "data": {
                        "task_id": task_id,
                        "filename": filename,
                        "hash": res["new_hash"],
                        "backup_id": res.get("backup_id"),
                        "status": "COMMITTED",
                        "message": "수정 제안이 디스크에 안전하게 반영되었습니다."
                    }
                }, ensure_ascii=False))

            except ConflictError as e:
                await websocket.send(json.dumps({
                    "type": "WRITE_CONFLICT",
                    "data": {
                        "task_id": task_id,
                        "filename": filename,
                        "current_hash": e.current_hash,
                        "message": "파일이 외부에서 변경되어 제안 적용이 중단되었습니다."
                    }
                }, ensure_ascii=False))
            except Exception as e:
                logger.error(f"[EventBridge] 제안 적용 실패: {e}", exc_info=True)
                await websocket.send(json.dumps({
                    "type": "WRITE_ERROR",
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
                
                filename = card.get("filename", "")
                if filename and card.get("markdown_content"):
                    res = vault_io.safe_write(
                        filename,
                        card["markdown_content"],
                        reason=f"Auto-Fix {code} 적용",
                        actor="user"
                    )
                    card["base_hash"] = res["new_hash"]

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
            # [아침 인사이트 1클릭 승인 -> safe_write 경유]
            insight_id = msg.get("insight_id", "")
            source_node = msg.get("source_node", "")
            target_node = msg.get("target_node", "")
            insight_text = msg.get("transfer_insight", "")

            try:
                src_filename = f"{source_node}.md" if not source_node.endswith(".md") else source_node
                src_note = vault_io.read_note(src_filename)

                now_str = datetime.datetime.now().strftime("%Y-%m-%d")
                if src_note:
                    src_text = src_note["content"]
                    link_entry = f"\n- [[{target_node[:-3] if target_node.endswith('.md') else target_node}]] :: [SERENDIPITY_TRANSFER] (승인: {now_str}) -> {insight_text}"
                    if "## 🔗" in src_text:
                        src_text = src_text.replace("## 🔗", f"## 🔗{link_entry}\n")
                    else:
                        src_text += f"\n\n## 🔗 인지적 연결망\n{link_entry}"

                    vault_io.safe_write(
                        src_filename,
                        src_text,
                        reason="인사이트 전이 위키링크 승인",
                        actor="user"
                    )

                await self.broadcast("INSIGHT_APPROVED", {
                    "insight_id": insight_id,
                    "source_node": source_node,
                    "target_node": target_node,
                    "message": f"'{source_node}'와 '{target_node}' 간의 전이 인사이트 위키링크가 디스크에 확정되었습니다."
                })
            except Exception as e:
                logger.error(f"[EventBridge] 인사이트 승인 처리 실패: {e}")

        elif msg_type == "APPROVE_MOC_MOVE":
            # [MOC 소속 이사 승인 -> moc_service 경유]
            insight_id = msg.get("insight_id", "")
            node_filename = msg.get("node_filename", "")
            target_moc = msg.get("target_moc", "")
            try:
                from moc_service import MOCService
                moc_service = MOCService(str(vault_io.vault_dir))
                res = moc_service.reassign_node_moc(node_filename, target_moc)
                await self.broadcast("MOC_MOVE_APPROVED", {
                    "insight_id": insight_id,
                    "node_filename": node_filename,
                    "target_moc": target_moc,
                    "result": res,
                    "message": f"'{node_filename}' 노드가 '{target_moc}'으로 안전하게 소속 이전되었습니다."
                })
            except Exception as e:
                logger.error(f"[EventBridge] MOC 소속 이사 승인 실패: {e}")

        elif msg_type == "APPROVE_SUB_MOC":
            # [하위 MOC 신설 승인 -> moc_service 경유]
            insight_id = msg.get("insight_id", "")
            parent_moc = msg.get("parent_moc", "")
            sub_moc_name = msg.get("sub_moc_name", "")
            try:
                from moc_service import MOCService
                moc_service = MOCService(str(vault_io.vault_dir))
                res = moc_service.create_sub_moc(parent_moc, sub_moc_name)
                await self.broadcast("SUB_MOC_APPROVED", {
                    "insight_id": insight_id,
                    "parent_moc": parent_moc,
                    "sub_moc_name": sub_moc_name,
                    "result": res,
                    "message": f"'{sub_moc_name}' 2계층 MOC가 신설되었습니다."
                })
            except Exception as e:
                logger.error(f"[EventBridge] 하위 MOC 신설 승인 실패: {e}")

        elif msg_type == "APPROVE_UNLINKED_MENTION":
            # [수평 언링크드 멘션 승인 -> mention_scanner 경유 원자적 치환]
            insight_id = msg.get("insight_id", "")
            source_node = msg.get("source_node", "")
            target_node = msg.get("target_node", "")
            matched_text = msg.get("matched_text", "")
            start_char = msg.get("start_char", -1)
            end_char = msg.get("end_char", -1)
            postposition = msg.get("postposition", "")
            try:
                import mention_scanner
                doc_path = f"{source_node}.md" if not source_node.endswith(".md") else source_node
                success = mention_scanner.apply_unlinked_mention_safely(
                    source_rel_path=doc_path,
                    target_node=target_node,
                    start_char=start_char,
                    end_char=end_char,
                    matched_text=matched_text,
                    postposition=postposition
                )
                if success:
                    await self.broadcast("UNLINKED_MENTION_APPROVED", {
                        "insight_id": insight_id,
                        "source_node": source_node,
                        "target_node": target_node,
                        "matched_text": matched_text,
                        "message": f"'{source_node}' 본문 속 '{matched_text}'가 [[{target_node}]]로 안전하게 수평 결속되었습니다."
                    })
            except Exception as e:
                logger.error(f"[EventBridge] 언링크드 멘션 승인 실패: {e}")

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

        elif msg_type == "SET_CRITIC_ENABLED":
            enabled = bool(msg.get("enabled", True))
            self.critic_enabled = enabled
            logger.info(f"[EventBridge] Critic 비판관 검증 토글 변경: {enabled}")
            try:
                from agent_core import ConstitutionalAgent
                # 싱글톤 에이전트 인스턴스가 있으면 상태 동기화
            except Exception:
                pass
            await self.broadcast("CRITIC_STATUS_CHANGED", {
                "enabled": self.critic_enabled,
                "message": f"Critic 비판관 검증이 {'활성화' if enabled else '비활성화(무료 쿼터 절약)'} 되었습니다."
            })

        elif msg_type == "GET_VAULT_GRAPH":
            # [Phase 3] D3.js Force Graph에 전달할 전체 볼트 노드/엣지 네트워크 인출
            try:
                from vault_indexer import VaultIndexer
                v_indexer = VaultIndexer()
                graph_data = v_indexer.get_graph_data()
                await websocket.send(json.dumps({
                    "type": "VAULT_GRAPH_DATA",
                    "data": graph_data
                }, ensure_ascii=False))
            except Exception as e:
                logger.error(f"[EventBridge] 볼트 그래프 인출 오류: {e}")

        elif msg_type == "GET_VAULT_TREE":
            # [Obsidian File Explorer] 볼트 내 전체 파일 및 카테고리별 트리 인출
            try:
                from vault_indexer import VaultIndexer
                v_indexer = VaultIndexer()
                notes = v_indexer.list_notes()
                categories = {}
                for n in notes:
                    cat = n.get("category", "일반")
                    if cat not in categories:
                        categories[cat] = []
                    categories[cat].append({
                        "name": n["name"],
                        "h1": n["h1"],
                        "path": n["path"],
                        "mtime": n.get("mtime", 0),
                        "outgoing_count": len(n.get("outgoing_links", []))
                    })
                for cat in categories:
                    categories[cat].sort(key=lambda x: x["name"])

                await websocket.send(json.dumps({
                    "type": "VAULT_TREE_RESULT",
                    "data": {
                        "total_count": len(notes),
                        "categories": categories
                    }
                }, ensure_ascii=False))
            except Exception as e:
                logger.error(f"[EventBridge] 볼트 트리 인출 오류: {e}")

        elif msg_type == "GET_NOTE_DETAIL":
            # [Phase 3] 특정 노드 클릭 시 사이드 패널/작업대용 본문 및 메타 인출
            node_name = msg.get("name", "")
            try:
                from vault_indexer import VaultIndexer
                v_indexer = VaultIndexer()
                detail = v_indexer.get_note_detail(node_name)
                await websocket.send(json.dumps({
                    "type": "NOTE_DETAIL_RESULT",
                    "data": detail or {"name": node_name, "error": "Not found"}
                }, ensure_ascii=False))
            except Exception as e:
                logger.error(f"[EventBridge] 노트 상세 인출 오류: {e}")

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

    async def process_http_request(self, connection, request):
        """단일 8765 포트에서 HTTP 대시보드 웹 서빙 및 API 처리 (CORS 프리플라이트 지원)"""
        upgrade = request.headers.get("Upgrade", "").lower()
        if upgrade == "websocket":
            return None  # WebSocket 핸드셰이크는 정상 통과

        # OPTIONS 프리플라이트 요청 즉각 허용
        method = getattr(request, "method", "GET")
        if method == "OPTIONS":
            resp = connection.respond(http.HTTPStatus.NO_CONTENT, "")
            resp.headers["Access-Control-Allow-Origin"] = "*"
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS, PUT, DELETE"
            resp.headers["Access-Control-Allow-Headers"] = "*"
            return resp

        resp = await self._route_http_request(connection, request)
        if resp:
            resp.headers["Access-Control-Allow-Origin"] = "*"
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS, PUT, DELETE"
            resp.headers["Access-Control-Allow-Headers"] = "*"
        return resp

    async def _route_http_request(self, connection, request):
        raw_path = request.path
        path = raw_path.split("?")[0]
        if path in ("/", "/dashboard", "/index.html", "/dashboard_prototype.html"):
            html_path = Path(__file__).parent.parent / "dashboard_prototype.html"
            if not html_path.exists():
                html_path = Path(__file__).parent / "dashboard_prototype.html"

            if html_path.exists():
                html_text = html_path.read_text(encoding="utf-8")
                resp = connection.respond(http.HTTPStatus.OK, html_text)
                resp.headers["Content-Type"] = "text/html; charset=utf-8"
                resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                resp.headers["Pragma"] = "no-cache"
                resp.headers["Expires"] = "0"
                return resp
            return connection.respond(http.HTTPStatus.NOT_FOUND, "Dashboard HTML not found")

        elif path == "/health":
            body = json.dumps({
                "status": "LIVE",
                "clients": len(self.clients),
                "cards": len(self.cards),
                "vault_dir": str(VAULT_DIR)
            }, ensure_ascii=False)
            resp = connection.respond(http.HTTPStatus.OK, body)
            resp.headers["Content-Type"] = "application/json; charset=utf-8"
            return resp

        elif path.startswith("/api/graph"):
            from vault_indexer import VaultIndexer
            v_indexer = VaultIndexer()
            graph_data = v_indexer.get_graph_data()
            body = json.dumps(graph_data, ensure_ascii=False)
            resp = connection.respond(http.HTTPStatus.OK, body)
            resp.headers["Content-Type"] = "application/json; charset=utf-8"
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return resp

        elif path.startswith("/api/vault/tree"):
            from vault_indexer import VaultIndexer
            v_indexer = VaultIndexer()
            notes = v_indexer.list_notes()
            categories = {}
            for n in notes:
                cat = n.get("category", "일반")
                if cat not in categories:
                    categories[cat] = []
                categories[cat].append({
                    "name": n["name"],
                    "h1": n["h1"],
                    "path": n["path"],
                    "mtime": n.get("mtime", 0),
                    "outgoing_count": len(n.get("outgoing_links", []))
                })
            for cat in categories:
                categories[cat].sort(key=lambda x: x["name"])
            body = json.dumps({
                "total_count": len(notes),
                "categories": categories
            }, ensure_ascii=False)
            resp = connection.respond(http.HTTPStatus.OK, body)
            resp.headers["Content-Type"] = "application/json; charset=utf-8"
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return resp

        elif path.startswith("/api/note"):
            from urllib.parse import urlparse, parse_qs
            from vault_indexer import VaultIndexer
            parsed = urlparse(path)
            qs = parse_qs(parsed.query)
            node_name = qs.get("name", [""])[0]
            v_indexer = VaultIndexer()
            detail = v_indexer.get_note_detail(node_name)
            if detail:
                body = json.dumps(detail, ensure_ascii=False)
                resp = connection.respond(http.HTTPStatus.OK, body)
            else:
                body = json.dumps({"error": "Note not found"}, ensure_ascii=False)
                resp = connection.respond(http.HTTPStatus.NOT_FOUND, body)
            resp.headers["Content-Type"] = "application/json; charset=utf-8"
            resp.headers["Cache-Control"] = "no-cache"
            return resp

        elif path.startswith("/api/moc/list"):
            from moc_service import MOCService
            service = MOCService()
            mocs = service.list_mocs()
            body = json.dumps({"mocs": mocs, "total_count": len(mocs)}, ensure_ascii=False)
            resp = connection.respond(http.HTTPStatus.OK, body)
            resp.headers["Content-Type"] = "application/json; charset=utf-8"
            resp.headers["Cache-Control"] = "no-cache"
            return resp

        elif path.startswith("/api/tags/registry"):
            from tag_service import TagRegistry
            reg = TagRegistry()
            data = {
                "canonical_tags": sorted(list(reg.canonical_tags)),
                "tag_categories": reg.tag_categories,
                "tag_definitions": reg.tag_definitions,
                "synonyms_by_tag": reg.synonyms_by_tag,
                "synonym_count": len(reg.synonym_map),
                "vault_file_path": str(reg.tag_dict_path)
            }
            body = json.dumps(data, ensure_ascii=False)
            resp = connection.respond(http.HTTPStatus.OK, body)
            resp.headers["Content-Type"] = "application/json; charset=utf-8"
            resp.headers["Cache-Control"] = "no-cache"
            return resp

        elif path.startswith("/api/tags/add_synonym"):
            from urllib.parse import urlparse, parse_qs
            from tag_service import TagRegistry
            parsed = urlparse(raw_path)
            qs = parse_qs(parsed.query)
            tag = qs.get("tag", [""])[0]
            synonym = qs.get("synonym", [""])[0]
            if not tag or not synonym:
                body = json.dumps({"error": "tag and synonym query params required"}, ensure_ascii=False)
                resp = connection.respond(http.HTTPStatus.BAD_REQUEST, body)
            else:
                reg = TagRegistry()
                success = reg.add_synonym(tag, synonym)
                body = json.dumps({
                    "success": success,
                    "canonical_tag": tag,
                    "new_synonym": synonym,
                    "message": f"동의어 '{synonym}'이(가) '{tag}'에 영구 등록되었습니다." if success else "등록 실패"
                }, ensure_ascii=False)
                resp = connection.respond(http.HTTPStatus.OK, body)
            resp.headers["Content-Type"] = "application/json; charset=utf-8"
            resp.headers["Cache-Control"] = "no-cache"
            return resp

        elif path.startswith("/api/moc/audit"):
            from urllib.parse import urlparse, parse_qs, unquote
            from dreaming_daemon import DreamingDaemon
            parsed = urlparse(raw_path)
            qs = parse_qs(parsed.query)
            raw_moc = qs.get("moc", ["MOC_커리어"])[0]
            moc_name = unquote(raw_moc, errors="replace")
            daemon = DreamingDaemon()
            res = daemon.audit_moc_relevance(moc_name)
            body = json.dumps(res, ensure_ascii=True)
            resp = connection.respond(http.HTTPStatus.OK, body)
            resp.headers["Content-Type"] = "application/json; charset=utf-8"
            resp.headers["Cache-Control"] = "no-cache"
            return resp

        elif path.startswith("/api/moc/diagnose"):
            from urllib.parse import urlparse, parse_qs, unquote
            from dreaming_daemon import DreamingDaemon
            parsed = urlparse(raw_path)
            qs = parse_qs(parsed.query)
            raw_moc = qs.get("moc", ["MOC_커리어"])[0]
            moc_name = unquote(raw_moc, errors="replace")
            daemon = DreamingDaemon()
            res = daemon.diagnose_moc_heterogeneity(moc_name)
            body = json.dumps(res, ensure_ascii=True)
            resp = connection.respond(http.HTTPStatus.OK, body)
            resp.headers["Content-Type"] = "application/json; charset=utf-8"
            resp.headers["Cache-Control"] = "no-cache"
            return resp
        elif path.startswith("/api/moc/reassign"):
            from urllib.parse import urlparse, parse_qs, unquote
            from moc_service import MOCService
            parsed = urlparse(raw_path)
            qs = parse_qs(parsed.query)
            node = unquote(qs.get("node", [""])[0], errors="replace")
            target = unquote(qs.get("target", [""])[0], errors="replace")
            if not node or not target:
                body = json.dumps({"error": "node and target query params required"}, ensure_ascii=True)
                resp = connection.respond(http.HTTPStatus.BAD_REQUEST, body)
            else:
                service = MOCService()
                success = service.reassign_node_moc(node, target)
                body = json.dumps({"success": success, "node": node, "target": target}, ensure_ascii=True)
                resp = connection.respond(http.HTTPStatus.OK, body)
            resp.headers["Content-Type"] = "application/json; charset=utf-8"
            resp.headers["Cache-Control"] = "no-cache"
            return resp

        elif path.startswith("/api/moc/create_sub_moc"):
            from urllib.parse import urlparse, parse_qs, unquote
            from moc_service import MOCService
            parsed = urlparse(raw_path)
            qs = parse_qs(parsed.query)
            name = unquote(qs.get("name", [""])[0], errors="replace")
            parent = unquote(qs.get("parent", [""])[0], errors="replace")
            desc = unquote(qs.get("desc", [""])[0], errors="replace")
            raw_nodes = unquote(qs.get("nodes", [""])[0], errors="replace")
            initial_nodes = [n.strip() for n in raw_nodes.split(",") if n.strip()] if raw_nodes else None

            if not name or not parent:
                body = json.dumps({"error": "name and parent query params required"}, ensure_ascii=True)
                resp = connection.respond(http.HTTPStatus.BAD_REQUEST, body)
            else:
                try:
                    service = MOCService()
                    file_path = service.create_sub_moc(name, parent, desc, initial_nodes)
                    body = json.dumps({
                        "success": True,
                        "file_path": str(file_path),
                        "name": name,
                        "parent": parent,
                        "nodes": initial_nodes
                    }, ensure_ascii=False)
                    resp = connection.respond(http.HTTPStatus.OK, body)
                except Exception as e:
                    body = json.dumps({"error": str(e)}, ensure_ascii=False)
                    resp = connection.respond(http.HTTPStatus.INTERNAL_SERVER_ERROR, body)
            resp.headers["Content-Type"] = "application/json; charset=utf-8"
            resp.headers["Cache-Control"] = "no-cache"
            return resp

        elif path.startswith("/api/moc/merge"):
            from urllib.parse import urlparse, parse_qs
            from moc_service import MOCService
            parsed = urlparse(raw_path)
            qs = parse_qs(parsed.query)
            source = qs.get("source", [""])[0]
            target = qs.get("target", [""])[0]
            if not source or not target:
                body = json.dumps({"error": "source and target query params required"}, ensure_ascii=False)
                resp = connection.respond(http.HTTPStatus.BAD_REQUEST, body)
            else:
                try:
                    service = MOCService()
                    res = service.merge_mocs(source, target)
                    body = json.dumps({"success": True, "result": res}, ensure_ascii=False)
                    resp = connection.respond(http.HTTPStatus.OK, body)
                except Exception as e:
                    body = json.dumps({"error": str(e)}, ensure_ascii=False)
                    resp = connection.respond(http.HTTPStatus.INTERNAL_SERVER_ERROR, body)
            resp.headers["Content-Type"] = "application/json; charset=utf-8"
            resp.headers["Cache-Control"] = "no-cache"
            return resp

        elif path.startswith("/api/subconscious/settings"):
            from urllib.parse import urlparse, parse_qs
            from subconscious_service import SubconsciousArchiveService
            parsed = urlparse(raw_path)
            qs = parse_qs(parsed.query)
            svc = SubconsciousArchiveService()
            if "days" in qs:
                try:
                    new_days = int(qs["days"][0])
                    svc.save_settings({"retention_days": new_days})
                except Exception as e:
                    logger.warning(f"[EventBridge] retention_days 파싱 실패: {e}")
            body = json.dumps(svc.load_settings(), ensure_ascii=False)
            resp = connection.respond(http.HTTPStatus.OK, body)
            resp.headers["Content-Type"] = "application/json; charset=utf-8"
            resp.headers["Cache-Control"] = "no-cache"
            return resp

        elif path.startswith("/api/subconscious/search"):
            from urllib.parse import urlparse, parse_qs
            from subconscious_service import SubconsciousArchiveService
            parsed = urlparse(raw_path)
            qs = parse_qs(parsed.query)
            q = qs.get("q", [""])[0]
            svc = SubconsciousArchiveService()
            matched = svc.search_subconscious_archive(q)
            body = json.dumps({"query": q, "count": len(matched), "results": matched}, ensure_ascii=False)
            resp = connection.respond(http.HTTPStatus.OK, body)
            resp.headers["Content-Type"] = "application/json; charset=utf-8"
            resp.headers["Cache-Control"] = "no-cache"
            return resp

        elif path.startswith("/api/subconscious/archive_now"):
            from subconscious_service import SubconsciousArchiveService
            svc = SubconsciousArchiveService()
            archived = svc.archive_expired_cards(self.cards)
            self.save_cards()
            body = json.dumps({"success": True, "archived_count": len(archived), "items": archived}, ensure_ascii=False)
            resp = connection.respond(http.HTTPStatus.OK, body)
            resp.headers["Content-Type"] = "application/json; charset=utf-8"
            resp.headers["Cache-Control"] = "no-cache"
            return resp

        elif path.startswith("/api/subconscious/list"):
            from subconscious_service import SubconsciousArchiveService
            svc = SubconsciousArchiveService()
            cards_list = svc.list_subconscious_cards(self.cards)
            body = json.dumps({"total_count": len(cards_list), "cards": cards_list}, ensure_ascii=False)
            resp = connection.respond(http.HTTPStatus.OK, body)
            resp.headers["Content-Type"] = "application/json; charset=utf-8"
            resp.headers["Cache-Control"] = "no-cache"
            return resp

        elif path.startswith("/api/subconscious/restore"):
            from urllib.parse import urlparse, parse_qs
            from subconscious_service import SubconsciousArchiveService
            parsed = urlparse(raw_path)
            qs = parse_qs(parsed.query)
            card_id = qs.get("id", [""])[0]
            if not card_id:
                body = json.dumps({"error": "id parameter required"}, ensure_ascii=False)
                resp = connection.respond(http.HTTPStatus.BAD_REQUEST, body)
            else:
                svc = SubconsciousArchiveService()
                success = svc.restore_card_to_inbox(card_id, self.cards)
                self.save_cards()
                body = json.dumps({"success": success, "id": card_id, "restored": True}, ensure_ascii=False)
                resp = connection.respond(http.HTTPStatus.OK, body)
            resp.headers["Content-Type"] = "application/json; charset=utf-8"
            resp.headers["Cache-Control"] = "no-cache"
            return resp

        elif path.startswith("/api/subconscious/delete"):
            from urllib.parse import urlparse, parse_qs
            from subconscious_service import SubconsciousArchiveService
            parsed = urlparse(raw_path)
            qs = parse_qs(parsed.query)
            card_id = qs.get("id", [""])[0]
            if not card_id:
                body = json.dumps({"error": "id parameter required"}, ensure_ascii=False)
                resp = connection.respond(http.HTTPStatus.BAD_REQUEST, body)
            else:
                svc = SubconsciousArchiveService()
                success = svc.delete_subconscious_card(card_id, self.cards)
                self.save_cards()
                body = json.dumps({"success": success, "id": card_id, "deleted": True}, ensure_ascii=False)
                resp = connection.respond(http.HTTPStatus.OK, body)
            resp.headers["Content-Type"] = "application/json; charset=utf-8"
            resp.headers["Cache-Control"] = "no-cache"
            return resp

        return connection.respond(http.HTTPStatus.NOT_FOUND, "Not Found")

    async def start(self):
        self._server = await websockets.serve(
            self.register,
            self.host,
            self.port,
            process_request=self.process_http_request
        )
        logger.info(f"[EventBridge] 단일 포트 HTTP/WebSocket 관제 가동: http://{self.host}:{self.port} & ws://{self.host}:{self.port}")
        return self._server


# 싱글톤 인스턴스
event_bridge = EventBridge()
