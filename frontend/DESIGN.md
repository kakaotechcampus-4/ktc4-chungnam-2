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
    padding: "15px 16px"
  button-outline:
    backgroundColor: "#FFFFFF"
    textColor: "{colors.brand-600}"
    rounded: "{rounded.control}"
  button-confirm:
    backgroundColor: "{colors.confirmed-gold-bg}"
    textColor: "{colors.confirmed-mark}"
    rounded: "{rounded.control}"
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

**Character:** 한 글꼴 가족 하나로 굵기 대비(700 / 500 / 400)만으로 위계를 만든다. 제목도 같은 가족을 쓴다.

### Hierarchy
- **Page title** (700, 24px): 입구 화면 제목(「내 지도」)이다.
- **Sheet title** (700, 20px): 시트 머리(「마킹된 장소」), 모달 제목이다.
- **Card title** (700, 17px): 지도 카드, AI 결과 머리다.
- **Button** (700, 16px): 전폭 CTA다.
- **Item title** (700, 14px): 핀 이름이다.
- **Body** (400, 13px): 검색창, 칩, 이유 문장이다.
- **Caption** (400, 12px): 부가정보, 참여 집계(「2/4명이 의견을 남겼어요」는 700)다.
- **Label** (500, 11px): 탭 라벨, 반응 숫자, 작은 칩이다.

### Named Rules
**Light 금지 규칙.** 300 굵기는 쓰지 않는다. 13px Light 회색 안내문은 읽히지 않는다.

## Layout

- **주 화면:** 393px 폭에서 지도 화면 좌우 여백은 16px, 입구 화면은 20px이다.
- **바텀시트:** 3단계다. 1단계는 손잡이 + 제목 줄만 보인다. 2단계는 시트 위끝이 화면 높이의 41%다. 3단계는 상단 39px까지 올라온다. 시트는 하단 탭(74px + 홈 표시줄) 위에서 멈춘다. 탭 막대가 커져도 시트 위끝은 그대로 두고 시트 높이를 줄인다.
- **핀 상세:** 2단계로 열리고, 내용을 끌어 올리면 3단계(의견 쓰기)로 자동 확장한다(#296). 2단계에서 「내 의견」 3버튼이 보이도록 순서는 [이름·참여율·반응 집계] → [내 의견·사유·등록] → [갈린 의견] → [아직 안 남긴 사람 한 줄]이다. 사진 칸은 두지 않는다 — 카카오 응답 저장 금지(#53)라 영원히 비어 있다. 자세한 정보는 메타 줄 끝 「카카오맵」 링크.
- **데스크톱:** 넓은 화면에서는 시트·탭 막대·상단 검색을 최대 480px로 왼쪽에 두고 나머지는 지도다(#351).
- **지도 위:** 위에는 뒤로가기 · 프로필 · 검색창 · 카테고리 칩만 둔다. 오른쪽 아래에는 지도 버튼 묶음이 시트 윗변을 따라 오르내린다.
- **간격 리듬:** 목록 카드 사이 10px, 칩 사이 8px, 핀 항목 안 12px, 지도 카드 안 16px이다.

**지도 집중 규칙.** 지도를 끄는 동안 검색창과 지도 버튼은 0.15초에 사라진다. 멈추면 0.8초 뒤 0.3초 동안 다시 나타난다.

**지도 버튼 자리 규칙.** 지도 버튼 묶음(44×3)은 시트 윗변 12px 위에 붙어 오르내린다. 상단 UI(검색창·칩·연결 띠) 아래끝 + 4px보다 위로 올라가야 하면 숨긴다 — 3단계·모달·높은 시트·작은 화면(아이폰 SE 2단계). 코드는 실제 공간을 재서 자동으로 숨긴다(#308).

## Elevation & Depth

목록과 카드는 평평하다. 테두리만 쓰고 그림자는 없다. 그림자는 지도 위에 떠 있는 것에만 준다. 기준색은 모두 잉크(rgba(20,22,31,α))다.

### Shadow Vocabulary
- **떠 있는 컨트롤** (`0 2px 8px rgba(20,22,31,.12)`): 지도 버튼 묶음, 검색창이다.
- **시트** (`0 -2px 12px rgba(20,22,31,.08)`): 바텀시트 윗변이다.
- **확정 핀** (`0 2px 4px rgba(0,0,0,.28)`): 흰 테두리 3px와 함께 바다 위 가시성을 맡는다. 빼지 않는다.

**시트 안 그림자 금지 규칙.** 시트 안의 틀에는 그림자를 넣지 않는다. 시트를 올리면 회색 줄로 보인다.

## Shapes

- **반경 단계:** 태그 6 → 컨트롤 8 → 카드·버튼·지도 버튼 12 → 시트 16 → 칩 알약이다. 코드는 `--radius-*`를 이 값으로 고정했다(#299).
- 카드는 핀 항목·AI 카드·지도 카드 모두 12 하나다(Figma의 10·12·14 혼재를 모음).
- **아이콘을 담는 면:** 원이 아니라 둥근 사각형이다(지도 버튼). 상단 뒤로가기·프로필만 원이다.

## Components

### Buttons
- **Primary:** 채움 brand-600, 흰 글자 16/700, 반경 12. 화면당 하나다(「의견 등록」, 「지도 만들기」, 「초대 링크 공유하기」).
- **Outline:** 흰 바탕 + brand-600 테두리·글자, 반경 8. 「지도에 올리기」 등이다.
- **Confirm:** 연골드 바탕 + 골드 테두리 + 갈색 글자 + ★. 확정 리스트 넣기 전용이다.
- **Kakao:** 카카오 노랑 + 검정 글자. 「카카오로 시작하기」 한 곳뿐이다.

### Chips
- **카테고리 칩:** 알약형이다. 선택하면 brand-100 + brand-600 테두리 + brand-700 글자이고, 기본은 흰 바탕 + ink-200 테두리 + ink-600 글자다.
- **사유 칩:** 같은 모양이다. 반대 사유를 고르면 반대 세트(bad-bg + pin-red 테두리 + bad-text), 조율 사유를 고르면 주의 세트(warn-*)다. 파랑으로 켜지 않는다(#299).

### Cards / Containers
- **핀 항목:** 흰 바탕, ink-200 테두리, 반경 12, 안쪽 12다. 의견을 남긴 핀도 흰 바탕이다. 회색 면은 비활성처럼 읽힌다. 의견이 필요한 핀만 brand-600 1.5px 테두리 + 「의견 남기기」 칩이다(#299).
- **AI 후보 카드:** brand-50 바탕 + brand-300 테두리다. 이유 · 조건 체크 칩 · 구성원 충족 · 출처를 빼지 않는다(가드레일 5).

### Inputs / Fields
- **입력칸:** 흰 바탕, ink-300 테두리, 반경 10, 높이 48이다. 글자가 있을 때만 오른쪽에 ✕가 보인다.
- **오류:** warn-line 테두리 + warn-text 글자다.

### Navigation
- **하단 탭:** 74px + 홈 표시줄이다. 세 탭은 화면을 3등분한 칸의 가운데다. 좌우는 24px 선 아이콘 + 11/500 라벨(활성 brand-600, 비활성 ink-500)이다. 가운데는 AI 원(48px) + 「AI 추천」 라벨이다. 비활성은 흰 바탕 + brand-300 2px 테두리 + 핑고, 활성만 brand-600 채움 + 흰 핑고다. AI는 핑고가 말한다는 규칙과 한 화면 한 채움을 함께 지킨다(#299).
- **검색창:** 안내문은 13/400 ink-500(대비 약 5:1)이다. 지도를 끄는 동안 사라지고, 그동안은 눌리지 않는다.
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
- 연결이 끊기면 지도 위에 띄우지 않고 시트 윗변에 붙는 얇은 띠로 알린다. 띠는 ink-100 바탕 + warn-line 아이콘 + ink-700 글자이고, 문구를 자르지 않는다. 노랑 면은 확정 골드와 겹쳐서 쓰지 않는다(#299).

### 모달
- 딤은 `--scrim` 32% 하나다. 포커스를 시트 안에 가두고, 닫으면 연 버튼으로 돌려준다(#299).

### 토스트
- **모양:** toast 82% + 배경 흐림 12, 흰 글자, 반경 12다.
- **위치:** 시트 윗변 12px 위 가운데, 최대 361px이다. 지도 버튼 묶음과 가로로 겹치면 묶음 위로 올린다. 올리면 상단 UI를 덮게 되면 올리지 않고 폭을 버튼 왼쪽 − 8px까지로 줄여 두 줄로 쓴다(단어 단위 줄바꿈, #308).
- **동작 글자:** 흰색 굵게 + 밑줄(「되돌리기」·「다시 시도」).
- **시간:** 3초(동작이 있으면 5초)다.

## Do's and Don'ts

### Do:
- **Do** 색은 역할 토큰(`--action-fill`, `--text-secondary`…)으로 부른다. 원시 값(`--brand-600`)을 컴포넌트에서 직접 부르지 않는다.
- **Do** 반응은 기호 + 색 + 숫자로 보여 주고, 내 반응은 그 반응 색 칩에 "· 나"를 붙인다.
- **Do** 상단 원형 버튼을 포함한 모든 터치 대상을 최소 44×44px로 잡는다. 보이는 원이 32px이면 히트 영역을 넓힌다.
- **Do** 참여율 핀 아래에 「N/M명이 의견을 남겼어요」를 함께 둔다. 색 단계만으로는 구분이 안 된다.

### Don't:
- **Don't** shadcn 기본 `--primary`(거의 검정)를 버튼·핀에 쓰지 않는다. 브랜드 파랑과 핀 빨강이 정본이다.
- **Don't** 구성원별 색을 쓰지 않는다. 아바타는 회색 면 하나다.
- **Don't** "마킹됨" 배지, "내 선택: ○○" 배지, 범례 한 줄 설명을 넣지 않는다.
- **Don't** 이모지(📅 💬 👥)를 아이콘 대신 쓰지 않는다. lucide(Calendar · MessageSquare · Users)를 쓴다. 🚫는 화면에서 lucide Ban(`ui/AgainstMark`)으로 그리고 뜻은 옆 글자 「반대」가 전한다. ♥ △ ?는 글자로 둔다.
- **Don't** 확정 해제를 빨강으로 칠하지 않는다. 일상 동작이라 중립 글자 버튼이다. 밀어서 나오는 「빼기」도 ink-600 바탕 + 흰 글자다(#299).
