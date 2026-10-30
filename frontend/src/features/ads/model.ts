import type { CandidateDto } from '@/features/recommend/model'
import { distanceM } from '@/features/search/model'

import type { AdDto } from './api'

/**
 * 광고 장소가 추천 후보와 같은 장소인지. 후보에는 자체 DB place_id가 없어서 이름과 좌표로 본다.
 * ponytail: 같은 이름 + 100m 안이면 같은 곳으로 친다. 후보에 place_id가 생기면 그걸로 바꾼다.
 */
export function overlapsCandidate(ad: AdDto, c: CandidateDto): boolean {
  if (c.place_name !== ad.place.name) return false
  if (c.lat === undefined || c.lng === undefined) return true
  return distanceM(ad.place, { lat: c.lat, lng: c.lng }) < 100
}
