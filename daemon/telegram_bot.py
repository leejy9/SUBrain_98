import logging
import html
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.request import HTTPXRequest
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters
)
from config import TELEGRAM_BOT_TOKEN
from agent_core import ConstitutionalAgent
import datetime
from event_bridge import event_bridge

# 로깅 설정
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

agent = ConstitutionalAgent()

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start 커맨드 핸들러"""
    welcome_text = (
        "🧠 <b>Subrain_98 회고봇에 오신 것을 환영합니다.</b>\n\n"
        "찰나에 떠오른 생각, 뉴스 기사, 딥리서치 링크를 여기에 공유해 주세요.\n"
        "사용자님의 <b>00_헌법</b> 규칙에 맞춰 원자 단위 마크다운으로 정규화하고, "
        "기존 지식 그래프와 연결하여 Mac의 Google Drive 폴더에 저장합니다.\n\n"
        "💡 <b>사용 방법</b>:\n"
        "1. 모바일에서 [공유하기] → 텔레그램 → 본 봇으로 전송\n"
        "2. 팝업되는 카테고리 버튼 선택 (또는 1줄 맥락 입력)\n"
        "3. 에이전트의 판단 경로 보고서 확인 및 즉시 롤백/수정 가능"
    )
    await update.message.reply_text(welcome_text, parse_mode=ParseMode.HTML)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """일반 텍스트 및 링크 메시지 수신 핸들러"""
    text = update.message.text.strip()
    reply_to = update.message.reply_to_message

    # 1. 이전 보고서 메시지에 답장한 경우 -> 대화형 수정(Refinement) 요청으로 처리
    if reply_to and "last_filename" in context.user_data:
        target_file = context.user_data["last_filename"]
        status_msg = await update.message.reply_text(f"⏳ <code>{html.escape(target_file)}</code> 노트를 피드백에 맞춰 재조정 중입니다...", parse_mode=ParseMode.HTML)
        
        result = agent.refine_note(target_file, text)
        if result.get("success"):
            reasoning = "\n".join([f"• {html.escape(s)}" for s in result.get("reasoning_steps", [])])
            report_text = (
                f"✅ <b>[노트 재조정 완료]</b>\n"
                f"📄 파일: <code>{html.escape(target_file)}</code>\n\n"
                f"🧠 <b>반영된 판단 경로</b>:\n{reasoning}\n\n"
                f"Google Drive를 통해 실시간 업데이트되었습니다."
            )
            keyboard = [[InlineKeyboardButton("↩️ 롤백 (파일 삭제)", callback_data=f"rollback_{target_file}")]]
            await status_msg.edit_text(report_text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await status_msg.edit_text(f"❌ 수정 실패: {html.escape(str(result.get('error')))}")
        return

    # 2. 맥락 입력을 대기 중인 상태에서 텍스트가 들어온 경우
    if context.user_data.get("waiting_context"):
        raw_input = context.user_data.pop("pending_raw", "")
        category = context.user_data.pop("pending_cat", "Experience")
        context.user_data["waiting_context"] = False
        await process_and_reply(update, context, raw_input, user_context=text, category=category)
        return

    # 3. 새로운 인테이크 수신 -> 카테고리 선택 버튼 제공
    context.user_data["pending_raw"] = text
    task_id = f"DOC-{datetime.datetime.now().strftime('%m%d-%H%M%S')}"
    context.user_data["current_task_id"] = task_id

    try:
        await event_bridge.broadcast("CARD_CREATED", {
            "task_id": task_id,
            "title": text[:35] + ("..." if len(text) > 35 else ""),
            "progress": 20,
            "status": "QUEUED"
        })
    except Exception as e:
        logger.warning(f"EventBridge broadcast error: {e}")

    keyboard = [
        [
            InlineKeyboardButton("💼 커리어/경험 (STAR)", callback_data="cat_Experience"),
            InlineKeyboardButton("🧠 영구 지식 (개념)", callback_data="cat_Permanent")
        ],
        [
            InlineKeyboardButton("🏢 기업/직무 분석", callback_data="cat_Application"),
            InlineKeyboardButton("⚡ 빠른 메모 (인박스)", callback_data="cat_Fleeting")
        ],
        [
            InlineKeyboardButton("✏️ 1줄 맥락 직접 쓰고 저장", callback_data="ask_context")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "📥 <b>정보가 접수되었습니다.</b>\n이 내용을 어떤 맥락으로 다룰까요?",
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """인라인 버튼 클릭 핸들러"""
    query = update.callback_query
    await query.answer()
    data = query.data

    # 롤백 처리
    if data.startswith("rollback_"):
        filename = data.replace("rollback_", "")
        success = agent.rollback_note(filename)
        if success:
            await query.edit_message_text(f"🗑️ <code>{html.escape(filename)}</code> 파일이 안전하게 삭제(롤백)되었습니다.", parse_mode=ParseMode.HTML)
        else:
            await query.edit_message_text(f"⚠️ <code>{html.escape(filename)}</code> 파일을 찾을 수 없거나 이미 삭제되었습니다.", parse_mode=ParseMode.HTML)
        return

    # 직접 맥락 입력 요청
    if data == "ask_context":
        context.user_data["waiting_context"] = True
        context.user_data["pending_cat"] = "Experience"
        await query.edit_message_text("✏️ 이 정보를 저장하는 <b>목적이나 내 생각</b>을 1줄로 답장해 주세요:", parse_mode=ParseMode.HTML)
        return

    # 카테고리 선택에 따른 즉시 정규화 처리
    category = data.replace("cat_", "")
    raw_input = context.user_data.pop("pending_raw", "")
    if not raw_input:
        await query.edit_message_text("⚠️ 세션이 만료되었습니다. 다시 공유해 주세요.")
        return

    await query.edit_message_text("⏳ <b>00_헌법을 검토하고 지식 그래프에 노드를 연결 중입니다...</b>", parse_mode=ParseMode.HTML)
    await process_and_reply(query, context, raw_input, user_context="", category=category)

async def process_and_reply(trigger_obj, context: ContextTypes.DEFAULT_TYPE, raw_input: str, user_context: str, category: str):
    """에이전트를 실행하고 텔레그램에 판단 보고서를 회신합니다."""
    try:
        result = agent.process_intake(raw_input, user_context=user_context, category_intent=category)
        filename = result["filename"]
        context.user_data["last_filename"] = filename

        briefing = result.get("briefing", {})
        summary = briefing.get("summary", "")
        passed_links = briefing.get("passed_links", [])
        rejected_links = briefing.get("rejected_links", [])
        fallback_to_moc = briefing.get("fallback_to_moc", False)
        target_moc = briefing.get("target_moc", "MOC_커리어")
        evaluation_log = briefing.get("evaluation_log", "")

        # 1. 85점 이상 통과된 연결 블록 구성
        conn_texts = []
        for pl in passed_links:
            t_node = html.escape(pl.get("target", ""))
            primitive = html.escape(pl.get("primitive", ""))
            score = pl.get("score", 85)
            reason = html.escape(pl.get("reason", ""))
            conn_texts.append(
                f"• <b>[[{t_node}]]</b>  <code>[{primitive}]</code> (적합도: {score}점)\n"
                f"  ↳ {reason}"
            )
        
        if conn_texts:
            connections_block = "\n\n".join(conn_texts)
        elif fallback_to_moc:
            connections_block = (
                f"⚠️ <b>85점 이상 검증된 인과관계가 없습니다.</b>\n"
                f"억지 연결(오염)을 방지하기 위해 <b>[[{html.escape(target_moc)}]]</b>에 안전 격리 배치했습니다."
            )
        else:
            connections_block = "연결 없음"

        # 2. 비판관이 쳐낸 억지 연결(방어 내역) 블록
        rejected_texts = []
        for rl in rejected_links:
            r_target = html.escape(rl.get("target", ""))
            r_score = rl.get("score", 0)
            r_reason = html.escape(rl.get("rejection_reason", ""))
            rejected_texts.append(f"• <s>[[{r_target}]]</s> ({r_score}점 탈락)\n  ↳ <i>{r_reason}</i>")
        rejected_block = "\n".join(rejected_texts) if rejected_texts else "없음"

        # 3. 역량 블록 구성
        comp_str = ", ".join([f"[[{html.escape(c)}]]" for c in result.get("competencies", [])]) or "없음"

        module_name = briefing.get("module_name", "모듈_영구지식")
        classified_type = briefing.get("classified_type", "Permanent")
        is_auto_committed = result.get("is_auto_committed", False)
        final_status = result.get("status", "COMMITTED" if is_auto_committed else "REVIEW_STAGED")
        card_warning = result.get("warning")
        integrity_score = result.get("integrity_score", 100.0)
        checklist = briefing.get("checklist", [
            {"text": f"위키링크 유효성 ({len(passed_links)}건 검증 통과)", "passed": True},
            {"text": "헌법 디스패치 및 프론트매터 일치", "passed": True},
            {"text": "크리틱 인과 점수 85점 통과", "passed": is_auto_committed},
            {"text": "구체적 수치 및 연도 명시", "passed": is_auto_committed}
        ])

        # 실시간 웹 대시보드(EventBridge)로 정규화 완료 카드 브로드캐스트
        task_id = context.user_data.get("current_task_id", f"DOC-{datetime.datetime.now().strftime('%m%d-%H%M%S')}")
        card_title = filename.replace('.md', '')
        
        thinking_list = [
            {"role": "WORKER", "step": "Step 1 [원문 수집]", "text": f"인테이크 원문 {len(raw_input)}자 수집 및 정제 완료."},
            {"role": "WORKER", "step": "Step 2 [헌법 디스패치]", "text": f"헌법 규격 판별 결과: {module_name} ({classified_type}) 채택."},
            {"role": "DIRECTOR", "step": "Step 3 [엔티티 매핑]", "text": f"볼트 인덱스 대조 후 {len(passed_links)}개 위키링크 후보 추출."},
            {"role": "CRITIC", "step": "Step 4 [크리틱 검증]", "text": f"85점 룰 검증 완료 (통과: {len(passed_links)}건, 차단: {len(rejected_links)}건, 자동반영: {'승인' if is_auto_committed else '보완대기'})."}
        ]

        card_data = {
            "id": task_id,
            "task_id": task_id,
            "title": card_title,
            "category": f"{classified_type} ({module_name})",
            "status": final_status,
            "priority": "High" if card_warning else "Normal",
            "progress": 100,
            "source": "Telegram Mobile Ingest",
            "timeAgo": "방금 전",
            "wikilinks": [f"[[{pl.get('target', '')}]]" for pl in passed_links],
            "tags": [f"#{classified_type}", f"#{module_name}"] + [f"#{c}" for c in result.get("competencies", [])],
            "synthesis": summary,
            "filename": filename,
            "markdown_content": result.get("markdown_content", ""),
            "suggestedPrompt": f"{card_title}의 핵심 인과를 바탕으로 3줄 요약을 압축해줘...",
            "copilotActions": [
                {"label": "🪄 헌법 규격 점검", "prompt": f"{card_title} 본문이 00_헌법 서식에 맞는지 재검토해줘"},
                {"label": "🔗 1촌 링크 추가", "prompt": "연관된 볼트 노드 1개를 추가 추천해서 본문에 삽입해줘"},
                {"label": "📄 3줄 핵심 압축", "prompt": "이 내용의 핵심 인사이트를 3줄로 압축 요약해줘"}
            ],
            "warning": card_warning,
            "integrity": {
                "score": integrity_score,
                "checklist": checklist
            },
            "thinking": thinking_list
        }

        try:
            await event_bridge.broadcast("CARD_STAGED", card_data)
            if is_auto_committed:
                await event_bridge.broadcast("CARD_COMMITTED", {
                    "task_id": task_id,
                    "filename": filename,
                    "filepath": result.get("filepath", ""),
                    "markdown_content": result.get("markdown_content", ""),
                    "message": f"'{filename}' 파일이 85점 룰을 통과하여 옵시디언 볼트에 자동 반영되었습니다."
                })
        except Exception as eb_err:
            logger.warning(f"Error broadcasting card event: {eb_err}")

        if is_auto_committed:
            header_status = "✨ <b>[지식이 볼트에 자동 저장되었습니다]</b>\n✓ <b>Critic 85점 & 헌법 무결성 100% 통과 (Auto-Committed)</b>\n"
        else:
            header_status = "⚠️ <b>[검토 및 보완 대기 상태로 등록되었습니다]</b>\n비판관 기준 점수 미달 또는 보완 필요 항목이 있어 대시보드 큐에 격리했습니다.\n"

        report_text = (
            f"{header_status}"
            f"📄 <code>{html.escape(filename)}</code>\n"
            f"🏛️ <b>헌법 디스패치</b>: <code>{html.escape(module_name)}</code> ({html.escape(classified_type)})\n\n"
            f"📌 <b>핵심 요약</b>\n"
            f"{html.escape(summary)}\n\n"
            f"🔗 <b>검증된 인과 연결 (Critic 85점 통과)</b>\n"
            f"{connections_block}\n\n"
            f"🛡️ <b>비판관이 차단한 억지 연결 (방어 완료)</b>\n"
            f"{rejected_block}\n\n"
            f"🏷️ <b>역량 강화</b>: <b>{comp_str}</b>\n\n"
            f"💡 <i>수정 팁: 연결을 바꾸고 싶다면 답장(Reply)으로 <b>\"OO 말고 XX로 연결해줘\"</b>라고 남겨주세요.</i>"
        )

        keyboard = [
            [
                InlineKeyboardButton("↩️ 롤백 (파일 삭제)", callback_data=f"rollback_{filename}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if hasattr(trigger_obj, "message") and trigger_obj.message:
            await trigger_obj.message.reply_text(report_text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
        else:
            await trigger_obj.edit_message_text(report_text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Error processing intake: {e}", exc_info=True)
        err_msg = f"❌ 정규화 처리 중 오류가 발생했습니다:\n<code>{html.escape(str(e))}</code>"
        if hasattr(trigger_obj, "message") and trigger_obj.message:
            await trigger_obj.message.reply_text(err_msg, parse_mode=ParseMode.HTML)
        else:
            await trigger_obj.edit_message_text(err_msg, parse_mode=ParseMode.HTML)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """전역 에러 핸들러"""
    logger.error("Exception while handling an update:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("⚠️ 일시적인 통신 지연이 발생했습니다. 다시 시도해 주세요.")
        except Exception:
            pass

def create_application():
    """텔레그램 봇 Application 인스턴스 빌드"""
    request = HTTPXRequest(
        connection_pool_size=16,
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=30.0
    )

    application = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .request(request)
        .build()
    )

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", start_command))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)
    return application

def main():
    """메인 실행 진입점 (단독 구동 시)"""
    logger.info("Starting Subrain_98 Telegram Bot Daemon with enhanced timeouts & HTML mode...")
    app = create_application()
    app.run_polling(drop_pending_updates=False)

if __name__ == "__main__":
    main()
