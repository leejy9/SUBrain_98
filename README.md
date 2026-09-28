# Subrain_98 (서브레인 98)

> **From Flash of Thought to Structured Knowledge Graph**  
> 찰나의 생각에서 구조화된 지식 그래프까지

---

## 📌 프로젝트 소개 (Overview)
**Subrain_98**은 이동 중이거나 일상에서 떠오른 아이디어, 웹 리서치 결과를 '맥락 손실 제로(Zero-Loss Context)'로 캡처하여 엄격한 지식 헌법에 따라 구조화된 로컬 마크다운(Obsidian) 지식 베이스로 자동 편입시키는 **지능형 세컨드 브레인 에이전트 시스템**입니다.

- **모바일 원클릭 인테이크**: 텔레그램 봇을 통한 신속한 원문 및 착상 캡처
- **헌법 최우선 디스패처(Constitutional Dispatcher)**: 입력된 정보의 유형을 분석하여 영구지식(CCIA), 경험정리(3C4P/멀티렌즈/STAR), 단순기록 모듈로 자동 라우팅
- **2-Pass Critic 검증 시스템**: 85점 이상의 기준 미달 시 자동 교정 및 재작성
- **투명한 의사결정 브리핑 & 롤백**: AI의 연결 의사결정 인과관계를 스토리텔링 형태로 브리핑하고 인라인 버튼으로 즉시 롤백/재조정 지원

---

## 📂 디렉토리 구조 (Directory Structure)
```text
Subrain_98/
├── 00_PROJECT_LOG.md            # 전체 프로젝트 토의 및 실행 기록 일지
├── 01_PRD_PRODUCT_REQUIREMENTS.md # 제품 요구사항 정의서
├── 02_SYSTEM_ARCHITECTURE.md    # 시스템 아키텍처 및 데이터 흐름도
├── 03_BACKEND_PRD.md            # 백엔드/에이전트 데몬 상세 스펙
├── daemon/                      # 백엔드 에이전트 데몬 소스 코드
│   ├── agent_core.py            # 헌법 디스패처 및 파이프라인 코어
│   ├── critic_validator.py      # 2-Pass Critic 검증 모듈
│   ├── telegram_bot.py          # 텔레그램 인터페이스 및 의사결정 카드
│   ├── vault_indexer.py         # 로컬 볼트 인덱싱 및 관계 분석
│   ├── models.py                # Pydantic 데이터 모델
│   ├── config.py                # 환경 설정 로더
│   └── .env.example             # 환경 변수 설정 템플릿
└── README.md
```

---

## 🚀 빠른 시작 (Quick Start)

### 1. 환경 설정
`daemon` 디렉토리로 이동하여 가상환경을 구성하고 환경변수를 설정합니다.

```bash
cd daemon
cp .env.example .env
# .env 파일에 TELEGRAM_BOT_TOKEN, GEMINI_API_KEY, VAULT_DIR 입력
```

### 2. 패키지 설치 및 실행
```bash
uv sync
uv run python main.py
```
