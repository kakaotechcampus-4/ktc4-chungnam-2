# frontend

루트 문서를 먼저 읽는다: `/CLAUDE.md`(가드레일·용어·스코프), `docs/api-spec.yaml`(계약 정본),
`docs/events.md`(SSE), `docs/errors.md`(에러 코드 ↔ 화면 매핑), `contracts/README.md`(타입·목서버 사용법).

## 스택

Vite + React + TypeScript · TanStack Query(서버 상태) · Zustand(UI 상태) ·
Tailwind CSS + shadcn/ui · 카카오맵 JS SDK

카카오맵은 명령형 SDK고 공식 React 래퍼가 없다. 마커 상태는 React 바깥에서 독립 관리하고,
React는 UI 상태(선택된 핀, 필터 값 등)만 갖는다.

## 화면 구조 (최종기획안 4절 — 확정)

탭 3개: 지도(기본) / AI 추천 / 리스트(확정). 지도 탭 위에 검색·핀목록·핀상세가 바텀시트로 뜬다
(GitHub #16~21). 핀 모양 3종(확정=채운 핀/일반=실선/AI 추천=점선)은 색과 별개 — 색은 "누가
찍었는지"고, 확정·AI 추천 핀은 고정색을 쓴다(팔레트·배정 방식은 결정 이슈 #26 미결).

## 계약 — 백엔드를 기다리지 않는다

- 타입·목 서버는 `contracts/`에서 가져온다. `contracts/mocks`로 BE 없이 전 화면 개발 가능
  (시나리오 전환은 `contracts/README.md` 참고).
- `docs/api-spec.yaml`이 스펙 정본이다. 여기서 스펙을 바꾸지 않는다 — 부족/틀렸다고 판단되면
  루트에 보고한다 (백엔드 모듈과 동일 원칙).
- 실시간은 SSE 2채널(전체/개인, `docs/events.md`) — 본인의 비공개 AI 후보는 개인 채널로만 온다.

## 디렉토리 — 기능(피처) 단위

코드 설계보다 디렉토리 단위로 끝난다는 전제로 간다. 화면(지도/AI추천/리스트) 기준으로 나누고,
여러 피처에서 같은 함수가 반복되면 그때 공통 모듈로 뽑는다 — 처음부터 공통 레이어를 설계하지 않는다.
지금은 프론트 담당이 한 명이라 이 문서 하나로 충분하다. 인원이 늘면 backend처럼
`frontend/<feature>/CLAUDE.md`로 쪼갠다.

## 코드 품질

`docs/code-quality.md` 참고. 이 쪽은 "요청받은 범위만 건드렸는가"·"에러를 조용히 삼키지 않는가"가
특히 중요하다 — SSE 재연결 실패, mutation 실패를 토스트 없이 무시하지 않는다.
