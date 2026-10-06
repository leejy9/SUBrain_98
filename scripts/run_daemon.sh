#!/bin/bash
# ==============================================================================
# SUBrain_98 — 24/7 Headless Daemon Runner with macOS caffeinate
# ==============================================================================
# - 맥북 덮개를 닫아도 시스템/디스플레이/디스크가 잠자지 않도록 caffeinate 적용
# - Telegram 봇 폴링 및 WebSocket 이벤트 브릿지(port 8765) 동시 구동
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DAEMON_DIR="$SCRIPT_DIR/../daemon"

cd "$DAEMON_DIR" || exit 1

echo "============================================================"
echo "🧠 Subrain_98 Headless Daemon Starting (Anti-Sleep: ON)"
echo "📍 Working Directory: $DAEMON_DIR"
echo "📡 WebSocket: ws://127.0.0.1:8765"
echo "💡 Dashboard: Open dashboard_prototype.html in standard browser"
echo "============================================================"

# caffeinate 옵션:
# -d: display idle sleep 방지
# -i: system idle sleep 방지
# -s: system sleep 방지 (AC 전원 시)
# -u: user active 상태 유지
caffeinate -disu "$DAEMON_DIR/.venv/bin/python" "$DAEMON_DIR/main.py"
