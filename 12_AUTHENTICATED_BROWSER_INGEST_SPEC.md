# 12_AUTHENTICATED_BROWSER_INGEST_SPEC.md
## 전용 브라우저 프로필 기반 인테이크 & 인스타 카드뉴스 추출 스펙

> **문서 상태**: 설계 완료 (Plan Mode 확정)  
> **관련 문서**: [11_UNIVERSAL_INGEST_EXTRACTOR_SPEC.md](file:///Users/grasshop/Desktop/Antigravity/Subrain_98/11_UNIVERSAL_INGEST_EXTRACTOR_SPEC.md), [00_PROJECT_LOG.md](file:///Users/grasshop/Desktop/Antigravity/Subrain_98/00_PROJECT_LOG.md)

---

### 1. 배경 및 사용자 문제의식

1. **로그인 방어벽 및 폐쇄형 SNS 인테이크 한계**:
   - 인스타그램 카드뉴스, 구글 독스, 로그인 전용 비공개 아티클 등은 일반 크롤러나 Jina Reader로 접근 시 403 Forbidden 또는 로그인 창으로 차단됨.
   - 특히 인스타그램은 본문이 텍스트가 아니라 다수의 이미지(슬라이드 1~10장) 안에 텍스트가 박혀 있어 텍스트 추출이 불가능했음.
2. **사용자 해결 방안 채택**:
   - 사용자가 **수집/크롤링 전용 독립 브라우저 프로필(부계정)**을 생성하여 Subrain 엔진에 연결.
   - 메인 개인 크롬과 완벽히 격리된 샌드박스 환경에서 로그인 세션을 재활용하여 차단을 무력화.

---

### 2. 4대 엔지니어링 불변식 (Invariants)

- **INV-B1 (독립 샌드박스 프로필 불변식 - Isolated Profile)**:
  - 사용자의 일상 메인 크롬과 완전히 분리된 전용 디렉터리(`~/.subrain_browser_profile`)를 사용한다.
  - 사용자가 맥북에서 크롬을 켜두고 웹서핑 중이어도 '프로필 잠금(Profile in use)' 충돌이 0%로 완벽히 방지된다.
- **INV-B2 (온디맨드 스위칭 불변식 - On-Demand Switching)**:
  - 모든 링크에 무거운 브라우저를 띄우지 않는다. 유튜브 영상, 일반 텍스트, 공개 웹페이지는 기존의 0.3초 가벼운 `universal_extractor`로 초고속 처리한다.
  - **인스타그램 링크(`instagram.com`) 또는 403 차단 사이트 감지 시에만 2차 무기로 브라우저 세션을 기동**하여 속도와 리소스를 보존한다.
- **INV-B3 (멀티모달 카드뉴스 순차 복원 불변식 - Multimodal OCR)**:
  - 인스타그램 카드뉴스 인입 시, 브라우저가 게시물의 슬라이드 이미지(1~10장)를 고화질로 일괄 수집한 뒤 Gemini Vision 멀티모달에 주입한다.
  - 슬라이드 1번부터 끝번까지 순서대로 헤드라인과 본문을 100% 온전한 마크다운으로 복원한다.
- **INV-B4 (정직한 세션 만료 알림 불변식 - Graceful Expiration)**:
  - 인스타나 구글 쿠키가 만료되어 로그인 창으로 튕길 경우 시스템이 비정상 종료되지 않고, 텔레그램으로 `"🔑 전용 프로필의 세션이 만료되었습니다. 1회 재로그인이 필요합니다"`를 정직하게 알린다.

---

### 3. 컴포넌트 아키텍처

```
[인스타 링크 / 403 차단 사이트 인입]
                │
                ▼
┌──────────────────────────────────────────────┐
│  daemon/authenticated_extractor.py           │
│  ├─ 1. 전용 프로필(~/.subrain_browser_profile) │
│  │     세션으로 백그라운드 Chromium 실행       │
│  ├─ 2. 인스타 슬라이드 이미지 1~10장 일괄 수집  │
│  └─ 3. Gemini Vision OCR 독해                │
│         ➔ 카드뉴스 속 글자 100% 텍스트화     │
└──────────────────────────────────────────────┘
                │ (추출된 고화질 마크다운 본문)
                ▼
┌──────────────────────────────────────────────┐
│  daemon/agent_core.py                        │
│  └─ 헌법 자동 분류 ➔ CCIA/STAR 요약 ➔ 볼트 저장 │
└──────────────────────────────────────────────┘
```

---

### 4. 단계별 구현 계획 (PIV Tasks)

#### Task 1: 전용 프로필 세션 관리자 (`daemon/browser_session_manager.py`)
- **목표**: 메인 크롬과 충돌 없는 전용 프로필 생성 및 1회성 로그인 도구.
- **기능**:
  - `python daemon/browser_session_manager.py --setup` 실행 시 전용 창이 뜨고, 사용자가 수집용 부계정으로 1회 로그인하면 세션 쿠키가 `~/.subrain_browser_profile`에 영구 보관됨.

#### Task 2: 인스타그램 카드뉴스 & 로그인 사이트 전용 추출기 (`daemon/authenticated_extractor.py`)
- **목표**: 200줄 이내 슬림 모듈.
- **기능**:
  - 인스타 단일 포스트 및 캐러셀(슬라이드) 이미지 URL 일괄 파싱.
  - Gemini Vision API 호출: 이미지들을 전달하여 슬라이드별 본문 텍스트 완벽 추출.

#### Task 3: 만능 추출기(`universal_extractor.py`) 자동 연동
- **수정**:
  - `_is_instagram_url(url)` 감지 시 `authenticated_extractor`로 즉시 연결.
  - 일반 웹페이지 403 차단 발생 시 2차 폴백으로 투입.

#### Task 4: 통합 E2E 검증 (`scripts/test_authenticated_extractor_e2e.py`)
- **검증**:
  - 전용 프로필 세션 로드 검증
  - 인스타그램 카드뉴스 텍스트 변환 및 요약 생성 검증

---

### 5. 수용 기준 (Acceptance Criteria)
1. 메인 크롬이 맥북에서 켜져 있는 상태에서도 프로필 충돌 없이 백그라운드 브라우저가 정상 기동한다.
2. 인스타그램 링크를 텔레그램에 넣었을 때 로그인 창에 막히지 않고 슬라이드 텍스트가 추출되어 요약 카드가 도착한다.
3. 일반 유튜브/웹 링크는 기존처럼 1초 이내 초고속으로 처리되고, 인스타 링크에만 브라우저가 동작한다.
