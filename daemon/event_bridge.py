import asyncio
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
                        self.cards[card_id] = item
                logger.info(f"[EventBridge] 영구 저장소에서 {len(self.cards)}개 카드 상태 복원 및 볼트 디스크 SSOT 동기화 완료")
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
                from google import genai
                client = genai.Client(api_key=GEMINI_API_KEY)

                history_text = ""
                if history:
                    recent = history[-6:]
                    h_lines = []
                    for h in recent:
                        r = "사용자" if h.get("role") == "user" else "AI 코파일럿"
                        h_lines.append(f"- {r}: {h.get('content', '')}")
                    history_text = "\n[이전 대화 기록]:\n" + "\n".join(h_lines)

                system_prompt = f"""당신은 사용자의 옵시디언 지식 베이스 문서를 함께 읽고 대화하며 교정하는 AI 어시스턴트(SUBrain Copilot)입니다.

[문서 제목]: {title}
[저장 파일명]: {filename}

[현재 문서 마크다운 전문]:
```markdown
{markdown_content or current_synthesis}
```
{history_text}

[사용자의 이번 메시지]:
{prompt}

당신은 Antigravity Agent나 ChatGPT, Claude처럼 자연스럽고 뛰어난 성능의 대화형 어시스턴트입니다.
1. 사용자가 질문/탐색을 하거나 단순 대화를 나누는 경우 (문서 수정 불필요):
   - 문서 내용을 바탕으로 친절하고 명쾌하게 질문에 답변하세요.
   - is_modification: false
   - updated_markdown: "" (빈 문자열)
   - updated_synthesis: 현재 요약 본문 유지

2. 사용자가 문서 내용 수정, 보강, 재작성, 특정 섹션 변경, 가이드 추가 등을 요청하는 경우:
   - [사실 무결성 불변식]: 사용자의 입력이나 현재 문서에 명시되지 않은 정량적 수치(%, 명, 금액 등)나 고유명사를 절대로 지어내지 마세요.
   - 사용자의 의도에 맞추어 [현재 문서 마크다운 전문]의 해당 섹션을 직접 지능적으로 수정·보강하세요.
   - 인위적인 '> [!NOTE] 교정 내역' 같은 잡다한 로그 블록을 덧붙이지 마세요.
   - 문서 본문 그 자체를 완성도 높은 옵시디언 마크다운(Frontmatter 포함 전문)으로 깔끔하게 업데이트하세요.
   - is_modification: true
   - updated_markdown: 수정된 문서의 완성된 전체 마크다운 문자열
   - updated_synthesis: 수정된 핵심 내용을 반영한 1~2문장 요약
   - assistant_response: 사용자의 요청을 어떻게 반영했는지 친절하고 자연스러운 대화체로 답변하세요.

출력 형식은 마크다운 코드블록(```json) 없이 순수 JSON만 출력하세요:
{{
  "assistant_response": "자연스러운 대화형 답변 (마크다운 지원)",
  "is_modification": true,
  "updated_synthesis": "핵심 1~2문장 요약",
  "updated_markdown": "수정된 문서 마크다운 전문 (Frontmatter 포함, 수정 없을 시 빈 문자열)"
}}"""

                resp = client.models.generate_content(
                    model="gemini-3.1-flash-lite",
                    contents=[system_prompt]
                )
                raw_text = resp.text.strip()
                if raw_text.startswith("```"):
                    lines = raw_text.splitlines()
                    if lines[0].startswith("```"): lines = lines[1:]
                    if lines and lines[-1].startswith("```"): lines = lines[:-1]
                    raw_text = "\n".join(lines).strip()

                try:
                    parsed = json.loads(raw_text)
                    assistant_response = parsed.get("assistant_response", "응답이 완료되었습니다.")
                    is_modification = parsed.get("is_modification", False)
                    updated_text = parsed.get("updated_synthesis", current_synthesis)
                    updated_markdown = parsed.get("updated_markdown", "")
                except Exception:
                    assistant_response = raw_text
                    is_modification = False
                    updated_text = current_synthesis
                    updated_markdown = ""

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
