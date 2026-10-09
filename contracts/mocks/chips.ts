/**
 * 반대 사유 칩 — docs/constraints.md「반대 사유 칩 (v1)」표와 같아야 한다(#60).
 * 목 서버가 그 표를 그대로 흉내 낸다. 칩을 바꾸면 문서 표, 구현의 목록, 이 파일을 함께 고친다.
 */
import type { components } from "../src/types/api";

export type ReasonChip = components["schemas"]["ReasonChip"];

const BY_CATEGORY: Record<string, ReasonChip[]> = {
  음식점: [
    { id: "food_spicy", label: "매워요", fact_key: "spicy_focused" },
    { id: "food_oily", label: "느끼해요", fact_key: "oily_focused" },
    { id: "food_expensive", label: "비싸요" }, // 가격 라벨은 뺐다(#423)
    { id: "food_wait", label: "웨이팅이 길어요", fact_key: "wait_short" },
    { id: "food_cramped", label: "좁아요", fact_key: "spacious" },
  ],
  카페: [
    { id: "cafe_crowded", label: "너무 붐벼요", fact_key: "is_crowded_large" },
    { id: "cafe_noisy", label: "시끄러워요", fact_key: "quiet" },
    { id: "cafe_seat", label: "자리가 불편해요", fact_key: "comfortable_seat" },
    { id: "cafe_expensive", label: "비싸요" },
  ],
  관광지: [
    { id: "sight_inaccessible", label: "휠체어·유모차로 가기 힘들어요", fact_key: "accessible" },
    { id: "sight_expensive", label: "입장료가 비싸요" },
    { id: "sight_noisy", label: "시끄러워요", fact_key: "quiet" },
  ],
};

const COMMON: ReasonChip[] = [
  { id: "common_not_my_taste", label: "취향이 아니에요" },
  { id: "common_far", label: "너무 멀어요" },
];

/** 반응할 수 없는 카테고리(숙소·기타)는 빈 배열. 그 외는 카테고리 칩 다음에 공통 칩. */
export function chipsFor(category: string): ReasonChip[] {
  const own = BY_CATEGORY[category];
  return own ? [...own, ...COMMON] : [];
}
