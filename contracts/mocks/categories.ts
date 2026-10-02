import type { components } from "../src/types/api";

type Category = components["schemas"]["Category"];
type RecommendCategory = components["schemas"]["RecommendCategory"];

/**
 * 카테고리별 성질 — backend/common/categories.py와 같은 값이어야 한다(#280).
 * backend/common/tests/test_category_drift.py가 이 표를 글자로 읽어 대조한다 — 한 줄에 카테고리 하나 모양을 지킨다.
 * pinnable: 자체 DB에 있어 핀을 만들 수 있다 · reactable: 반응할 수 있다 · recommendable: AI 추천 대상이다
 */
export const CATEGORY_RULES: Record<Category, { pinnable: boolean; reactable: boolean; recommendable: boolean }> = {
  음식점: { pinnable: true, reactable: true, recommendable: true },
  카페: { pinnable: true, reactable: true, recommendable: true },
  숙소: { pinnable: false, reactable: false, recommendable: false },
  관광지: { pinnable: true, reactable: true, recommendable: true },
  기타: { pinnable: false, reactable: true, recommendable: false },
};

/** 추천 대상 카테고리(스펙 RecommendCategory). */
export const RECOMMEND_CATEGORIES = (Object.keys(CATEGORY_RULES) as Category[]).filter(
  (c): c is RecommendCategory => CATEGORY_RULES[c].recommendable,
);
