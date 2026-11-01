import { MapPin, MessageSquareText, Sparkles, Star, type LucideIcon } from 'lucide-react'

import type { SceneKind } from './WelcomeScene'

/**
 * 핑고핑고의 기능 소개 — 로그인 화면의 목록과 첫 로그인 온보딩이 이 표 하나를 쓴다.
 * 쓰는 순서대로 — 핀 찍기 → 의견 → AI 추천 → 확정. 아이콘이 각 기능을 가리켜서 같은 체크를 반복하지 않는다.
 * `detail`은 온보딩에서 제목 아래 한 줄이다. 어디서 무엇을 누르는지만 쓰고, 버튼·탭 이름은 화면 글자 그대로다.
 * `scene`은 온보딩에서 핑고가 그 기능을 쓰는 장면이다(WelcomeScene).
 */
export const FEATURES: { Icon: LucideIcon; text: string; detail: string; scene: SceneKind }[] = [
  { Icon: MapPin, text: '가고 싶은 곳을 핀으로 찍어요', detail: '장소를 검색해 「핀 찍기」를 눌러요', scene: 'pin' },
  { Icon: MessageSquareText, text: '좋음·반대로 의견을 남겨요', detail: '반대할 땐 이유를 함께 남겨요', scene: 'reaction' },
  { Icon: Sparkles, text: '모두의 의견을 모아 AI가 장소를 찾아줘요', detail: 'AI 추천 탭에서 「추천받기」를 눌러요', scene: 'ai' },
  { Icon: Star, text: '정한 곳은 확정 리스트에 모아요', detail: '「동선 보기」로 들를 순서도 볼 수 있어요', scene: 'shortlist' },
]
