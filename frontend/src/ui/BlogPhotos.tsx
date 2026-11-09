import { useState } from 'react'
import { ImageOff } from 'lucide-react'

export type BlogPhoto = { thumbnail_url: string; link_url: string; site_name: string }

const TILE = 'size-18 shrink-0 overflow-hidden rounded-xl bg-ink-100'

/** 사진 한 칸. 미리보기 주소가 만료돼 못 그리면 빈 회색 칸으로 둔다(링크는 그대로 원문으로 간다). */
function Tile({ photo, n }: { photo: BlogPhoto; n: number }) {
  const [broken, setBroken] = useState(false)
  const site = photo.site_name || '출처'
  return (
    <a
      href={photo.link_url}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={`블로그 사진 ${n}, ${site}, 새 창`}
      className={`${TILE} press block`}
    >
      {!broken && (
        <img src={photo.thumbnail_url} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setBroken(true)} className="size-full object-cover" />
      )}
    </a>
  )
}

/**
 * 핀 상세 블로그 사진 줄(#1157) — 그 가게를 다룬 블로그 사진 미리보기 최대 3장을 72px 한 줄로 둔다.
 * 2단계 시트에서 "내 의견" 버튼이 밀리지 않게 낮게 둔다. 공식 사진이 아니라서 "블로그 사진"이라고 밝히고 출처 사이트 이름을 적는다.
 * 누르면 원문 글을 새 창으로 연다.
 * 높이는 상태와 상관없이 72px 한 줄이다(불러오는 중 빈 칸 3개, 사진, 실패 글, 없음 글). 불러오는 칸이 오류 글로 줄어들면
 * 아래 버튼이 위로 당겨져, 누르려던 자리에 지도가 와 핀 상세가 닫혔다(e2e, 2026-11-10). 누를 것이 움직이지 않게 한다.
 */
export default function BlogPhotos({ photos, loading = false, failed = false }: { photos?: BlogPhoto[]; loading?: boolean; failed?: boolean }) {
  if (failed) return <Notice text="사진을 불러오지 못했어요" />
  if (loading) {
    return (
      <div className="flex gap-2" aria-hidden="true">
        {[0, 1, 2].map((i) => (
          <div key={i} className={`${TILE} animate-pulse motion-reduce:animate-none`} />
        ))}
      </div>
    )
  }
  if (!photos?.length) return <Notice text="블로그 사진을 찾지 못했어요" />
  const sites = [...new Set(photos.map((p) => p.site_name).filter(Boolean))]
  return (
    <section aria-label="블로그 사진" className="flex items-center gap-2">
      {photos.map((p, i) => (
        <Tile key={p.link_url + i} photo={p} n={i + 1} />
      ))}
      <div className="min-w-0 pl-1">
        <p className="text-xs font-semibold text-ink-700">블로그 사진</p>
        {sites.length > 0 && <p className="truncate text-label text-ink-500">{sites.join(', ')}</p>}
      </div>
    </section>
  )
}

/** 실패나 없음 — 사진 줄과 같은 높이의 빈 칸 하나와 짧은 글. */
function Notice({ text }: { text: string }) {
  return (
    <div className="flex items-center gap-2">
      <span aria-hidden="true" className={`${TILE} flex items-center justify-center text-ink-400`}>
        <ImageOff size={20} />
      </span>
      <p className="pl-1 text-xs text-ink-500">{text}</p>
    </div>
  )
}
