import { ExternalLink, MapPin } from 'lucide-react'

type Service = 'kakao' | 'naver'

const SERVICE: Record<Service, { name: string; bg: string; fg: string }> = {
  kakao: { name: '카카오맵', bg: 'var(--kakao-yellow)', fg: 'var(--ink-900)' },
  naver: { name: '네이버 지도', bg: 'var(--naver-green)', fg: '#fff' },
}

/**
 * 서비스 표시 — 그 서비스 색 사각형 안에 핀. 남의 로고를 옮겨 그리지 않고 색과 이름으로 알아보게 한다(상표).
 * 이름은 옆 글자가 읽으므로 장식이다.
 */
function ServiceMark({ service, size }: { service: Service; size: number }) {
  const s = SERVICE[service]
  return (
    <span aria-hidden="true" className="inline-flex shrink-0 items-center justify-center rounded-[5px]" style={{ width: size, height: size, background: s.bg, color: s.fg }}>
      <MapPin size={Math.round(size * 0.66)} strokeWidth={2.5} />
    </span>
  )
}

/**
 * 카카오맵, 네이버 지도의 원본 장소 페이지로 가는 링크 한 쌍. 주소, 사진, 영업시간 같은 자세한 정보는 그쪽에서 본다
 * (카카오 응답 저장 금지, #53). 새 창으로 연다. 앱 안 WebView 는 카카오 약관이 막는다.
 * 링크는 서버가 만든다(`place_url`, `naver_url`). 없는 쪽은 그리지 않는다.
 * - row: 핀 상세 — 같은 너비 두 버튼을 한 줄에 둔다. 바로 눈에 띄게 하려는 자리다
 * - inline: 후보, 광고 카드 — 카드 안이 좁아 작은 글자 링크로 둔다
 * onOpen: 연 것을 세는 곳(광고 클릭 집계)이 있으면 넘긴다.
 */
export default function MapAppLinks({
  kakao,
  naver,
  variant = 'row',
  onOpen,
}: {
  kakao?: string | null
  naver?: string | null
  variant?: 'row' | 'inline'
  onOpen?: () => void
}) {
  const links = (
    [
      ['kakao', kakao],
      ['naver', naver],
    ] as const
  ).filter((l): l is readonly [Service, string] => Boolean(l[1]))
  if (links.length === 0) return null

  if (variant === 'inline') {
    return (
      <span className="flex flex-wrap justify-end gap-x-3">
        {links.map(([service, url]) => (
          <a key={service} href={url} target="_blank" rel="noopener noreferrer" onClick={onOpen} className="btn-link inline-flex items-center gap-1 text-xs">
            <ServiceMark service={service} size={14} />
            {SERVICE[service].name}에서 보기 <ExternalLink size={12} aria-hidden="true" />
          </a>
        ))}
      </span>
    )
  }
  return (
    <div className="grid grid-cols-2 gap-2">
      {links.map(([service, url]) => (
        <a
          key={service}
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          onClick={onOpen}
          aria-label={`${SERVICE[service].name}에서 보기, 새 창`}
          className="btn-outline btn-sm justify-center gap-1.5"
        >
          <ServiceMark service={service} size={18} />
          {SERVICE[service].name}
          <ExternalLink size={14} aria-hidden="true" className="text-ink-500" />
        </a>
      ))}
    </div>
  )
}
