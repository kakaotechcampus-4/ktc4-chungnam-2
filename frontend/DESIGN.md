---
name: 핑고핑고
description: 친구들이 한 지도에 핀을 찍고 의견을 모아 여행 장소를 정하는 공동 지도
colors:
  brand-50: "#EFF5FE"
  brand-100: "#DBE8FD"
  brand-200: "#B8D0F9"
  brand-300: "#84AFF5"
  brand-500: "#3B72E4"
  brand-600: "#2A57C4"
  brand-700: "#1E4197"
  ink-50: "#F8F9FB"
  ink-100: "#F0F1F5"
  ink-200: "#E2E4EB"
  ink-300: "#C9CCD6"
  ink-400: "#9EA3B2"
  ink-500: "#6B7181"
  ink-600: "#545A6B"
  ink-900: "#14161F"
  good-bg: "#E6F4ED"
  good-line: "#12855A"
  good-text: "#0D6B49"
  warn-bg: "#FBF0DC"
  warn-line: "#C77700"
  warn-text: "#A35F00"
  bad-bg: "#FBEAEA"
  pin-red: "#D02A2A"
  bad-text: "#A32020"
  confirmed-gold: "#F5B301"
  confirmed-gold-bg: "#FFF6DB"
  confirmed-mark: "#6B4500"
  toast: "#3A3F4B"
  kakao-yellow: "#FEE500"
typography:
  page-title:
    fontSize: "24px"
    fontWeight: 700
  sheet-title:
    fontSize: "20px"
    fontWeight: 700
  card-title:
    fontSize: "17px"
    fontWeight: 700
  button:
    fontSize: "16px"
    fontWeight: 700
  item-title:
    fontSize: "16px"
    fontWeight: 700
  section-title:
    fontSize: "14px"
    fontWeight: 700
  body:
    fontSize: "13px"
    fontWeight: 400
  caption:
    fontSize: "12px"
    fontWeight: 400
  label:
    fontSize: "11px"
    fontWeight: 500
rounded:
  tag: "6px"
  control: "8px"
  card: "12px"
  button: "12px"
  sheet: "16px"
  pill: "9999px"
spacing:
  gutter-map: "16px"
  gutter-page: "20px"
  stack: "10px"
  chip-gap: "8px"
  item-pad: "12px"
  card-pad: "16px"
components:
  button-primary:
    backgroundColor: "{colors.brand-600}"
    textColor: "#FFFFFF"
    typography: "{typography.button}"
    rounded: "{rounded.button}"
    height: "52px"
  button-outline:
    backgroundColor: "#FFFFFF"
    textColor: "{colors.brand-600}"
    rounded: "{rounded.button}"
  button-neutral:
    backgroundColor: "#FFFFFF"
    textColor: "{colors.ink-900}"
    rounded: "{rounded.button}"
  button-confirm:
    backgroundColor: "{colors.confirmed-gold-bg}"
    textColor: "{colors.confirmed-mark}"
    rounded: "{rounded.control}"
  tag:
    rounded: "{rounded.tag}"
    typography: "{typography.caption}"
  input:
    backgroundColor: "#FFFFFF"
    rounded: "{rounded.card}"
    height: "48px"
  chip-selected:
    backgroundColor: "{colors.brand-100}"
    textColor: "{colors.brand-700}"
    rounded: "{rounded.pill}"
  chip-default:
    backgroundColor: "#FFFFFF"
    textColor: "{colors.ink-600}"
    rounded: "{rounded.pill}"
  pin-item:
    backgroundColor: "#FFFFFF"
    rounded: "{rounded.card}"
    padding: "{spacing.item-pad}"
  ai-card:
    backgroundColor: "{colors.brand-50}"
    rounded: "{rounded.card}"
  map-control:
    backgroundColor: "#FFFFFF"
    textColor: "{colors.brand-600}"
    rounded: "{rounded.button}"
    size: "44px"
  toast:
    backgroundColor: "{colors.toast}"
    textColor: "#FFFFFF"
    rounded: "{rounded.button}"
---

<!-- 화면 디자인 규칙(2026-10-03 /impeccable document로 만들고 #299·#308 점검 결과를 반영, #350에서 팀 공유).
     화면을 만들거나 고치기 전에 읽는다. Impeccable 스킬(/impeccable …)도 이 파일을 읽는다.
     색 값의 정본은 src/styles/tokens.css, 색 결정의 이유는 docs/design/colors.md다. 어긋나면 그쪽이 맞다.
     Figma kYFSIDXYHJ3L1JWRnLDrKH는 참고안이다 — 더 나은 안이 있으면 근거를 붙여 제안하고, 정해지면 여기와 Figma를 같이 고친다. -->

# Design System: 핑고핑고

## Overview

**Creative North Star: "함께 펼친 지도"**

친구 넷이 테이블에 지도 한 장을 펼쳐 놓고, 각자 포스트잇을 붙이고, 갈리는 곳에 동그라미를 친다. 화면의 주인공은 그 지도다. 바텀시트·버튼·칩은 지도 위에 얹은 메모처럼 절제하고, 핀과 의견만 또렷하게 보인다.

- **진행자 원칙:** 지도 위에서 이 체계는 조용한 진행자처럼 행동한다. 의견이 갈린 곳(반대 → 조율)을 먼저 드러내고, 지금 할 일 하나만 브랜드 파랑으로 강조한다.
- **핑고의 자리:** 핑고는 AI가 말하는 자리에만 나온다. 친근함은 핑고와 "~해요" 말투가 맡고, 화면 전체를 귀엽게 만들지 않는다.

밀도는 중간 이상이다. 시트 절반 높이에서 핀 3~4개와 각 반응 집계가 한 번에 읽혀야 한다. 장식보다 상태(의견 필요 / 완료 / 확정 / AI 후보)를 정확히 구분하는 데 힘을 쓴다.

**Key Characteristics:**
- 지도가 항상 떠 있고, UI는 시트 하나와 그 위에 따라붙는 지도 버튼·토스트뿐이다.
- 색은 영역으로 갈린다. UI는 파랑, 지도 위 핀은 빨강, 확정만 골드다.
- AI는 색이 아니라 형태(점선 핀)·톤(brand-50 면)·화자(핑고)로 구분한다.
- 반응은 기호 + 색 + 숫자로 함께 보여 준다. 색만으로 뜻을 전하지 않는다.

## Colors

파랑 217° 하나로 UI를 끌고 가고, 빨강·골드·반응 3색은 정해진 영역 밖으로 나가지 않는다.

### Primary
- **핑고 파랑** (brand-300): 면 전용이다. 핑고 몸통, AI 영역 테두리에 쓴다. 흰 글자 대비가 2.2:1이라 글자 바탕으로 쓰지 않는다.
- **액션 파랑** (brand-600): 채움 버튼, 링크, 활성 탭, 선택 테두리, 지도 버튼 아이콘, 동선 경로선(4px)에 쓴다. 흰 글자 대비는 6.5:1이다.
- **선택 파랑** (brand-100 바탕 + brand-600 선 + brand-700 글자): 켜진 칩과 토글이다. 채우지 않는다.
- **AI 물** (brand-50): AI 후보 카드, 핑고 배너, 「의견 남기기」 칩 바탕이다.

### Tertiary
- **확정 골드** (confirmed-gold, 글자는 confirmed-mark 갈색): 확정 핀, 확정 리스트·동선 순서 번호, 「★ 확정 리스트에 넣기」(연골드 바탕 + 골드 테두리)에만 쓴다.

### Neutral
- **잉크** (ink-900): 본문 글자다.
- **보조 글자** (ink-600 / ink-500): 부가정보와 비활성 탭에 쓴다. ink-500은 흰 바탕 대비 약 5:1이다.
- **희미한 색** (ink-400): 대비가 약 2.5:1이다. 아이콘·비활성 전용이고, 읽어야 하는 글자(집계 숫자·「(나)」·「(선택)」·글자 수)에는 쓰지 않는다. 글자 회색은 900 / 600 / 500 세 단계다.
- **선** (ink-200 hairline / ink-300 control): 카드 테두리와 입력 테두리다.
- **종이** (ink-50): 입구 화면의 페이지 배경이다.

### Semantic
- **좋음** (good-bg / good-line / good-text), **조율·주의** (warn-*), **반대** (bad-bg / pin-red / bad-text): 배경·선·글자가 한 세트다. 선 색을 글자에 쓰지 않는다.

### Named Rules
**영역 분리 규칙.** 빨강은 지도 위 핀과 반응 🚫, 그리고 되돌릴 수 없는 액션에만 쓴다. 입력 오류는 빨강이 아니라 주의색(warn-line 테두리 + warn-text 글자)이다.

**한 화면 한 채움 규칙.** 한 화면에 채운 버튼은 하나다. 나머지는 외곽선이나 글자 버튼으로 둔다.

**파랑은 할 일 규칙.** 초록·노랑·빨강은 반응의 뜻으로 이미 쓰고 있다. 그래서 "아직 의견을 안 남김" 같은 할 일 표시는 브랜드 파랑으로만 한다.

## Typography

**Body Font:** Pretendard Variable(dynamic subset, `src/index.css`). Figma 시안은 아직 Noto Sans KR이라 글자 폭이 조금 다르다.

**글자 크기는 rem으로 쓴다.** `text-[13px]` 같은 px 고정값은 사용자가 글자를 키워도 커지지 않아 위계가 뒤집힌다(150% 확대 점검, #308). 아래 px는 기본 16px 기준 값이다.

**Character:** 한 글꼴 가족 하나로 굵기 대비만으로 위계를 만든다. 제목도 같은 가족을 쓴다. 굵기는 700(제목·버튼) / 600(태그·켜진 칩·짧은 강조) / 500(탭 라벨·글자 버튼) / 400(본문) 네 단계다.

### Hierarchy
단계마다 클래스가 하나다(`src/index.css` `@theme`). 이 여덟 단계 밖의 크기(`text-lg`, `text-[…]`)는 쓰지 않는다.

| 단계 | 크기·굵기 | 클래스 | 쓰는 곳 |
|---|---|---|---|
| Page title | 24 / 700 | `text-2xl` | 입구 화면 제목(「내 지도」·「새 지도」) |
| Sheet title | 20 / 700 | `text-xl` · `ui/SheetTitle` | 시트 머리(「마킹된 장소」), 핀 이름, 검색 결과 머리, 모달 시트 제목 |
| Card title | 17 / 700 | `text-title` | 지도 카드·AI 후보 카드 이름, 확인 창 제목, 전체 화면 머리줄(근거 확인) |
| Button · Item title | 16 / 700 | `text-base` | 전폭 버튼(btn-lg), 목록의 핀 이름 |
| Section title | 14 / 700 | `text-sm font-bold` | 시트 안 구역 제목(「내 의견 선택」·「구성원」·「꼭 지켜야 하는 조건」) |
| Body | 13 / 400 | `text-body` | 칩, 이유 문장, 메타 줄, 시트 안 뒤로가기 |
| Caption | 12 / 400 | `text-xs` | 부가정보, 태그, 참여 집계(「2/4명이 의견을 남겼어요」는 700) |
| Label | 11 / 500 | `text-label` | 탭 라벨, 글자 수, 작은 안내(＊ 줄) |

- **입력칸은 16px다.** 아이폰 Safari는 16px보다 작은 입력칸에 포커스하면 화면을 확대해 지도 화면이 어긋난다. 검색창도 같다. 안내문(placeholder)은 ink-500이다.
- **예외:** 로그인 화면 워드마크 「핑고핑고」(30 / 800, brand-600)만 단계 밖이다. 로고 자리라서다.

### Named Rules
**Light 금지 규칙.** 300 굵기는 쓰지 않는다. 13px Light 회색 안내문은 읽히지 않는다.

## Layout

- **주 화면:** 393px 폭에서 지도 화면 좌우 여백은 16px, 입구 화면은 20px이다.
- **바텀시트:** 3단계다. 1단계는 손잡이 + 제목 줄만 보인다. 2단계는 시트 위끝이 화면 높이의 41%다. 3단계는 상단 39px까지 올라온다. 시트는 하단 탭(74px + 홈 표시줄) 위에서 멈춘다. 탭 막대가 커져도 시트 위끝은 그대로 두고 시트 높이를 줄인다.
- **핀 상세:** 2단계로 열리고, 내용을 끌어 올리면 3단계(의견 쓰기)로 자동 확장한다(#296). 2단계에서 「내 의견」 3버튼이 보이도록 순서는 [이름·참여율·반응 집계] → [내 의견·사유·등록] → [갈린 의견] → [아직 안 남긴 사람 한 줄]이다. 사진 칸은 두지 않는다 — 카카오 응답 저장 금지(#53)라 영원히 비어 있다. 자세한 정보는 메타 줄 끝 「카카오맵」 링크.
- **데스크톱:** 넓은 화면(768px 이상, Tailwind `md`)은 왼쪽 480px + 오른쪽 지도 영역이다(#351·#338). 왼쪽 480px는 맨 왼쪽 세로 탭 줄 72px + 높이 전체 내용 패널 408px다(네이버 지도처럼). 탭 줄은 탭 3개를 세로로 쌓고, 칸마다 아이콘 + 11/500 라벨(라벨 그대로, AI도 같은 모양), 활성은 brand-50 면 + brand-600이다. 내용 패널은 위에서부터 헤더(‹ · 지도 제목 · 구성원) · 검색창 · 탭 내용이고, 탭 내용은 패널 안에서 평범하게 스크롤한다 — 단계·손잡이·끌기·자동 확장이 없다. 탭 줄과 패널은 지도 위에 떠 있지 않아서 그림자 없이 ink-200 오른쪽 선으로 나눈다. 패널 오른쪽 가장자리 세로 가운데의 « 손잡이로 내용 패널만 접고(탭 줄은 남고 나머지는 지도) » 로 편다. 접힌 채 탭·핀·검색 번호를 누르면 패널이 다시 열린다. 지도 영역 왼쪽 위에는 카테고리 칩(좁으면 줄바꿈)과 연결 끊김 띠, 우하단에는 지도 버튼 묶음(16px 여백), 바닥 가운데에는 토스트가 온다. 지도를 옮기는 보정(검색 결과·최근 핀·전체 핀 보기)은 이 지도 영역 기준이다.
- **지도 위:** 위에는 뒤로가기 · 프로필 · 검색창 · 카테고리 칩만 둔다. 오른쪽 아래에는 지도 버튼 묶음이 시트 윗변을 따라 오르내린다. 넓은 화면은 위 데스크톱 줄을 따른다.
- **간격 리듬:** 목록 카드 사이 10px, 칩 사이 8px, 핀 항목 안 12px, 지도 카드 안 16px이다.

**지도 집중 규칙.** 지도를 끄는 동안 검색창과 지도 버튼은 0.15초에 사라진다. 멈추면 0.8초 뒤 0.3초 동안 다시 나타난다.

**지도 버튼 자리 규칙.** 지도 버튼 묶음(44×3)은 시트 윗변 12px 위에 붙어 오르내린다. 상단 UI(검색창·칩·연결 띠) 아래끝 + 4px보다 위로 올라가야 하면 숨긴다 — 3단계·모달·높은 시트·작은 화면(아이폰 SE 2단계). 코드는 실제 공간을 재서 자동으로 숨긴다(#308). 넓은 화면은 지도 영역 우하단에 고정이고 모달일 때만 숨긴다(#338).

## Elevation & Depth

목록과 카드는 평평하다. 테두리만 쓰고 그림자는 없다. 그림자는 지도 위에 떠 있는 것에만 준다. 기준색은 모두 잉크(rgba(20,22,31,α))다.

### Shadow Vocabulary
- **떠 있는 컨트롤** (`shadow-float`, `0 2px 8px rgba(20,22,31,.12)`): 지도 버튼 묶음, 검색창, 상단 원 버튼, 지도 위 카테고리 칩, 하단 AI 원, 패널 손잡이다. Tailwind 기본 `shadow`·`shadow-sm`·`shadow-md`는 순수 검정이라 쓰지 않는다.
- **시트** (`shadow-sheet`, `0 -2px 12px rgba(20,22,31,.08)`): 바텀시트 윗변이다.
- **확정 핀** (`0 2px 4px rgba(0,0,0,.28)`): 흰 테두리 3px와 함께 바다 위 가시성을 맡는다. 빼지 않는다.

**시트 안 그림자 금지 규칙.** 시트 안의 틀에는 그림자를 넣지 않는다. 시트를 올리면 회색 줄로 보인다.

## Shapes

- **반경 단계:** 태그 6(`rounded-sm`) → 컨트롤·작은 버튼 8(`rounded-md`) → 카드·버튼·입력칸·지도 버튼 12(`rounded-xl`) → 시트·확인 창 16(`rounded-2xl`) → 칩 알약(`rounded-full`)이다. 코드는 `--radius-*`를 이 값으로 고정했다(#299). `rounded-lg`도 12지만 이름을 하나로 두려고 `rounded-xl`만 쓴다. 맨 `rounded`(4)는 쓰지 않는다.
- 카드는 핀 항목·AI 카드·지도 카드·핑고 배너·초대 카드 모두 12 하나다(Figma의 10·12·14 혼재를 모음).
- **아이콘을 담는 면:** 원이 아니라 둥근 사각형이다(지도 버튼). 상단 뒤로가기·프로필만 원이다.

## 컴포넌트 목록

**화면은 이 목록의 부품으로만 만든다.** 필요한 모양이 없으면 화면에서 클래스를 새로 짜지 않는다. 먼저 여기와 `src/index.css`(또는 `src/ui/`)에 부품을 만들고, 그 부품으로 화면을 만든다. 버튼 높이·카드 반경·글자 크기가 화면마다 달라지는 것을 막는 장치다(2026-10-17).

| 필요한 것 | 쓰는 부품 | 위치 |
|---|---|---|
| 버튼 | `btn-{primary·outline·neutral·confirm·danger·danger-outline}` + `btn-{lg·md·sm}` | `index.css` |
| 글자 버튼·링크 | `btn-text` · `btn-link` | `index.css` |
| 누르는 알약(필터·선택) | `chip` (+ `chip-against`), 카테고리 줄은 `CategoryChips` | `index.css` · `features/map/PinFilterControls` |
| 짧은 표시 | `tag` + `tag-{neutral·ai·good·warn·bad}` | `index.css` |
| 입력칸 | `TextField`(✕·글자 수 포함) · `ClearButton`, 그 밖의 입력은 `field` 틀 | `ui/TextField` · `index.css` |
| 시트·모달 제목 | `SheetTitle` (20/700) | `ui/SheetTitle` |
| 시트 안 이전 화면 | `BackButton` 「‹ 마킹된 장소」 | `ui/BackButton` |
| 비어 있을 때 | `EmptyState` (회색 면 아이콘 + 제목 + 설명 + 다음 행동) | `ui/EmptyState` |
| 불러오는 중 | `CardSkeleton` (글자 「불러오는 중…」 대신 카드 자리) | `ui/CardSkeleton` |
| 확인 창 | `ConfirmDialog` (`danger`면 마지막 버튼이 빨강) | `ui/ConfirmDialog` |
| 아래에서 올라오는 모달 | `ModalSheet` | `features/shell/ModalSheet` |
| 알림 | `showToast` (+ 「되돌리기」·「다시 시도」 동작) | `features/shell/toast` |
| 사람 | `Avatar` (회색 면 + 첫 글자, 32·44) | `ui/Avatar` |
| AI가 말하는 머리 | `AiHeader` (핑고 + `tag-ai`) | `features/recommend/Readiness` |
| 반대 기호 | `AgainstMark` (lucide Ban) | `ui/AgainstMark` |

- **아이콘:** lucide 선 아이콘만 쓴다. 크기는 12(11~12px 글자 옆) · 14(13px 글자 옆) · 16(14~16px 글자 옆·작은 버튼) · 20(지도 버튼·큰 버튼·단독 아이콘 버튼) · 24(탭) 다섯 단계다. 빈 화면 아이콘만 28이다.
- **핑고(`ui/Pingo`)는 AI 자리에만 둔다.** 빈 화면·로딩·오류에는 넣지 않는다 — `EmptyState`는 회색 면 아이콘이다.

## Components

### Buttons
버튼은 **색 하나 + 크기 하나**다. 높이·글자 크기·반경을 그 자리에서 덧쓰지 않고, 폭(`w-full`·`flex-1`)과 바깥 여백만 준다.

| 색 | 모양 | 쓰는 곳 |
|---|---|---|
| `btn-primary` | 채움 brand-600 + 흰 글자 | 화면당 하나(「의견 등록」·「지도 만들기」·「초대 링크 공유하기」) |
| `btn-outline` | 흰 바탕 + brand-600 테두리·글자 | 두 번째 동작(「지도에 올리기」·「핀 찍기」·「근거 고치기」) |
| `btn-neutral` | 흰 바탕 + ink-300 테두리 + ink-900 글자 | 취소·로그아웃·나가기·선택 안 함 |
| `btn-confirm` | 연골드 + 골드 테두리 + 갈색 글자 + ★ | 「확정 리스트에 넣기」 전용. 「✓ 확정됨」 표시도 같은 모양 |
| `btn-danger` | 채움 빨강 | 되돌릴 수 없는 동작의 확인 창 마지막 버튼(「삭제」·「나가기」) |
| `btn-danger-outline` | 빨강 테두리·글자 | 그 확인 창을 여는 버튼(「지도 삭제」) |

| 크기 | 높이 | 쓰는 곳 |
|---|---|---|
| `btn-lg` | 52 · 16/700 · 반경 12 | 화면·시트 맨 아래 주 버튼 줄(나란히 둘이어도 같다) |
| `btn-md` | 44 · 14/700 · 반경 12 | 확인 창 버튼, 내용 중간 버튼(「의견 등록」), 빈 화면의 다음 행동 |
| `btn-sm` | 32 · 14/700 · 반경 8 · 누르는 곳 44 | 카드·줄 안(「지도에 올리기」·「핀 찍기」·「링크 복사」·「로그아웃」). 12면 알약처럼 보여 칩과 헷갈려서 8이다(#359) |

- **글자 버튼:** `btn-text`(조용한 회색 500 — 「닫기」·「핀 삭제」·「확정 해제」·「나중에 할게요」)와 `btn-link`(brand-600 700 — 「카카오맵에서 보기」·「복사」·「직접 찍기」). 둘 다 누르는 곳 44px이 들어 있다. 크기는 놓인 줄의 글자 크기를 따른다.
- **Kakao:** 카카오 노랑 + 검정 글자, `btn-lg`. 「카카오로 시작하기」 한 곳뿐이다.

### Chips · Tags
- **칩(`chip`)** — 누르는 알약이다(카테고리·지역·사유·「동선 보기」). 13/400, 높이 32, 누르는 곳 44. 켜짐은 `aria-pressed`로 정한다: brand-100 + brand-600 테두리 + brand-700 글자 600. 기본은 흰 바탕 + ink-200 테두리 + ink-700 글자다. 그림자는 지도 위에 떠 있을 때만(`CategoryChips floating`) 준다.
- **사유 칩:** 같은 모양에 `chip-against`를 더한다. 반대 사유를 고르면 반대 세트(bad-bg + pin-red 테두리 + bad-text)다. 파랑으로 켜지 않는다(#299).
- **태그(`tag` + `tag-*`)** — 누를 수 없는 짧은 표시다. 12/600, 반경 6. `tag-neutral`(방장·지역) · `tag-ai`(AI) · `tag-good`/`tag-warn`/`tag-bad`(준비 완료·조건 체크). 흰 글자를 선 색(good-line·warn-line) 위에 얹지 않는다 — warn-line 위 흰 글자는 3.5:1이라 작은 글자 기준(4.5:1)에 못 미친다.

### Cards / Containers
- **핀 항목:** 흰 바탕, ink-200 테두리, 반경 12, 안쪽 12다. 의견을 남긴 핀도 흰 바탕이다. 회색 면은 비활성처럼 읽힌다. 의견이 필요한 핀만 brand-600 1.5px 테두리 + 「의견 남기기」 칩이다(#299).
- **AI 후보 카드:** brand-50 바탕 + brand-300 테두리다. 이유 · 조건 체크 칩 · 구성원 충족 · 출처를 빼지 않는다(가드레일 5).

### Inputs / Fields
- **입력칸(`field` · `ui/TextField`):** 흰 바탕, ink-300 테두리, 반경 12, 높이 48, 글자 16이다. 글자가 있을 때만 오른쪽에 ✕(`ClearButton`)와 글자 수가 보인다. 포커스하면 테두리가 brand-500으로 바뀌고 2px 포커스 링이 붙는다. 날짜·여러 줄 입력도 같은 `field` 틀이다.
- **오류:** `aria-invalid`를 켜면 warn-line 테두리가 되고, 문구는 warn-text다.

### Navigation
- **하단 탭:** 74px + 홈 표시줄이다. 세 탭은 화면을 3등분한 칸의 가운데다. 좌우는 24px 선 아이콘 + 11/500 라벨(활성 brand-600, 비활성 ink-500)이다. 가운데는 AI 원(48px) + 「AI 추천」 라벨이다. 비활성은 흰 바탕 + brand-300 2px 테두리 + 핑고, 활성만 brand-600 채움 + 핑고다(핑고 그림은 그대로). AI는 핑고가 말한다는 규칙과 한 화면 한 채움을 함께 지킨다(#299).
- **검색창:** 글자는 16/400(입력칸 규칙 — 아이폰 확대 방지), 안내문은 ink-500(대비 약 5:1)이다. 지도를 끄는 동안 사라지고, 그동안은 눌리지 않는다.
- **상단:** 좌상단 ‹(흰 원)는 내 지도 목록이다. 우상단은 지도 정보·구성원 버튼으로, 구성원 아이콘 + 인원 수를 보여 준다(이니셜 원은 계정처럼 읽혀서 바꿈, #351). 보이는 원은 32px, 누르는 영역은 44px이다.

### 지도 핀 (Signature)
- **일반:** pin-red 실선 2.5px이다. 속은 참여율만큼 ink-200 → pin-red를 oklch로 섞는다.
- **AI 추천:** pin-red 점선(4 3) + 회색 속 + 핑고 실루엣이다.
- **선택된 핀:** 상세를 연 핀은 1.25배·흰 후광·맨 위로 올리고 아래에 이름 말풍선을 띄운다(#308).
- **누르는 영역:** 보이는 핀은 30×38이지만 누르는 영역은 44×44다.
- **확정:** 골드 채움 + 흰 테두리 3px + 그 바깥 갈색 1px(confirmed-mark) + 그림자(0 2px 6px .35) + 갈색 ♥다. 밝은 땅 위에서 흰 테두리만으로는 1.2:1이라 갈색 선이 가시성을 맡는다(#299).

### 빈 결과 (AI 0곳)
- 「반경 넓히기」가 유일한 채움 버튼이다. 사람이 누르는 버튼이라 가드레일 4와 맞는다. 「근거 고치기」는 외곽선이고, 「직접 찍기」는 brand-600 글자 링크다(#299).

### 연결 상태
- 연결이 끊기면 지도 위에 띄우지 않고 시트 윗변에 붙는 얇은 띠로 알린다. 넓은 화면은 시트 윗변이 없어서 지도 영역 왼쪽 위 칩 아래에 떠 있는 띠(반경 12, 그림자)로 둔다(#338). 띠는 ink-100 바탕 + warn-line 아이콘 + ink-700 글자이고, 문구를 자르지 않는다. 노랑 면은 확정 골드와 겹쳐서 쓰지 않는다(#299).

### 모달
- 딤은 `--scrim` 32% 하나다. 포커스를 시트 안에 가두고, 닫으면 연 버튼으로 돌려준다(#299).

### 토스트
- **모양:** toast 82% + 배경 흐림 12, 흰 글자, 반경 12다.
- **위치:** 시트 윗변 12px 위 가운데, 최대 361px이다. 지도 버튼 묶음과 가로로 겹치면 묶음 위로 올린다. 올리면 상단 UI를 덮게 되면 올리지 않고 폭을 버튼 왼쪽 − 8px까지로 줄여 두 줄로 쓴다(단어 단위 줄바꿈, #308). 넓은 화면은 지도 영역 바닥 16px 위 가운데이고, 버튼 묶음과 겹치면 올리지 않고 줄이기만 한다(#338).
- **동작 글자:** 흰색 굵게 + 밑줄(「되돌리기」·「다시 시도」).
- **시간:** 3초(동작이 있으면 5초)다.

## Do's and Don'ts

### Do:
- **Do** 화면을 만들기 전에 「컴포넌트 목록」을 먼저 본다. 맞는 부품이 없으면 부품부터 만들고 목록에 올린다.
- **Do** 색은 역할 토큰(`--action-fill`, `--text-secondary`…)으로 부른다. 원시 값(`--brand-600`)을 컴포넌트에서 직접 부르지 않는다.
- **Do** 반응은 기호 + 색 + 숫자로 보여 주고, 내 반응은 그 반응 색 칩에 "· 나"를 붙인다.
- **Do** 상단 원형 버튼을 포함한 모든 터치 대상을 최소 44×44px로 잡는다. 보이는 원이 32px이면 히트 영역을 넓힌다.
- **Do** 참여율 핀 아래에 「N/M명이 의견을 남겼어요」를 함께 둔다. 색 단계만으로는 구분이 안 된다.

### Don't:
- **Don't** shadcn 기본 `--primary`(거의 검정)를 버튼·핀에 쓰지 않는다. 브랜드 파랑과 핀 빨강이 정본이다.
- **Don't** 구성원별 색을 쓰지 않는다. 아바타는 회색 면 하나다.
- **Don't** "마킹됨" 배지, "내 선택: ○○" 배지, 범례 한 줄 설명을 넣지 않는다.
- **Don't** 이모지(📅 💬 👥)를 아이콘 대신 쓰지 않는다. lucide(Calendar · MessageSquare · Users)를 쓴다. 🚫는 화면에서 lucide Ban(`ui/AgainstMark`)으로 그리고 뜻은 옆 글자 「반대」가 전한다. ♥ △ ?는 글자로 둔다.
- **Don't** 버튼에 `py-3`·`text-sm`·`rounded-md`를 덧써서 크기를 바꾸지 않는다. 크기는 `btn-lg`/`md`/`sm` 중 하나다.
- **Don't** 확정 해제를 빨강으로 칠하지 않는다. 일상 동작이라 중립 글자 버튼이다. 밀어서 나오는 「빼기」도 ink-600 바탕 + 흰 글자다(#299).
