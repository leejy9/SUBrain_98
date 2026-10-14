import os
import sys
import json
from pathlib import Path

# daemon 경로 추가
daemon_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "daemon"))
if daemon_path not in sys.path:
    sys.path.insert(0, daemon_path)

from dreaming_daemon import DreamingDaemon

def main():
    print("🌙 [The Dreaming Daemon] 실제 볼트 MOC_커리어 감사 및 이질성 진단 착수...")
    daemon = DreamingDaemon()

    # 1. 소속 적합성 감사
    print("\n🔍 1. MOC_커리어 소속 적합성 감사 (Semantic Drift Audit) 실행 중...")
    audit = daemon.audit_moc_relevance("MOC_커리어")
    print(f"✓ 감사 완료 (노드 수: {audit.get('total_nodes')}개)")
    print(f"✓ 이사 권고 감지 여부: {audit.get('drift_detected')}")
    print(f"✓ 자연어 총평: {audit.get('natural_briefing')}")
    if audit.get("recommendations"):
        print("✓ 권고 항목:")
        for r in audit["recommendations"]:
            print(f"   - [[{r.get('node')}]] ➔ {r.get('suggested_moc')}: {r.get('reasoning')}")

    # 2. 이질성 분할 진단
    print("\n🌌 2. MOC_커리어 이질성 분할 진단 (Heterogeneity Split Diagnosis) 실행 중...")
    split = daemon.diagnose_moc_heterogeneity("MOC_커리어")
    print(f"✓ 진단 완료 (노드 수: {split.get('total_nodes')}개)")
    print(f"✓ 분할 추천 여부: {split.get('split_recommended')} (이질성 수준: {split.get('heterogeneity_level')})")
    print(f"✓ 자연어 총평: {split.get('natural_briefing')}")
    if split.get("suggested_sub_mocs"):
        print("✓ 하위 MOC 신설 추천:")
        for s in split["suggested_sub_mocs"]:
            print(f"   - 🪐 {s.get('name')}: {s.get('rationale')}")
            print(f"     후보 노드: {s.get('candidate_nodes')}")

if __name__ == "__main__":
    main()
