import { MapPin, MessageSquareText, Sparkles, Star, type LucideIcon } from 'lucide-react'

import type { SceneKind } from './WelcomeScene'

/**
 * 핑고핑고의 기능 소개 — 로그인 화면의 목록과 첫 로그인 온보딩이 이 표 하나를 쓴다.
 * 쓰는 순서대로 — 핀 찍기 → 의견 → AI 추천 → 확정. 아이콘이 각 기능을 가리켜서 같은 체크를 반복하지 않는다.
 * `detail`은 온보딩에서 제목 아래 한 줄이다. 어디서 무엇을 누르는지만 쓰고, 버튼·탭 이름은 화면 글자 그대로다.
 * `scene`은 온보딩에서 핑고가 그 기능을 쓰는 장면이다(WelcomeScene).
 */
export const FEATURES: { Icon: LucideIcon; text: string; detail: string; scene: SceneKind }[] = [
  { Icon: MapPin, text: '가고 싶은 곳을 핀으로 남겨요', detail: '장소를 검색하고 핀 찍기를 눌러 보세요', scene: 'pin' },
  { Icon: MessageSquareText, text: '좋음과 반대로 솔직한 의견을 나눠요', detail: '반대할 때는 이유를 남겨 다른 대안을 찾을 수 있어요', scene: 'reaction' },
  { Icon: Sparkles, text: '모두의 취향을 모아 AI가 대안을 찾아줘요', detail: '의견이 갈릴 때 AI 추천 탭에서 추천받기를 눌러 보세요', scene: 'ai' },
  { Icon: Star, text: '마음에 드는 장소는 확정해 모아 둬요', detail: '날짜에 넣고 동선 보기를 누르면 들를 순서가 보여요', scene: 'shortlist' },
]
