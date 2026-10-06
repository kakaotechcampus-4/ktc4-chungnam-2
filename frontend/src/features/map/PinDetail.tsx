import { useState, type ReactNode } from 'react'
import { ExternalLink, ImageOff, X } from 'lucide-react'

import { ApiError } from '@/api'
import ErrorText from '@/ErrorText'
import type { MemberView } from '@/features/maps/model'
import { showToast } from '@/features/shell/toast'
import { useAddToShortlistMutation } from '@/features/shortlist/queries'
import AgainstMark from '@/ui/AgainstMark'
import { josa } from '@/ui/josa'

import { participants, REASON_CHIPS, toOpinions, type OpinionView, type Pin, type ReactionDto, type ReactionType } from './model'
import { useMyReactionMutation, useReactionsQuery } from './queries'

/** 반응 색 세트(colors.md 시맨틱 — 배경·선·글자 세 값이 한 세트). 용어·기호는 기획안 9절 고정. */
const R: Record<ReactionType, { mark: ReactNode; label: string; bg: string; line: string; text: string }> = {
  like: { mark: '♥', label: '좋음', bg: 'var(--good-bg)', line: 'var(--good-line)', text: 'var(--good-text)' },
  neutral: { mark: '△', label: '조율', bg: 'var(--warn-bg)', line: 'var(--warn-line)', text: 'var(--warn-text)' },
  against: { mark: <AgainstMark />, label: '반대', bg: 'var(--bad-bg)', line: 'var(--bad-line)', text: 'var(--bad-text)' },
}
const TYPES: ReactionType[] = ['like', 'neutral', 'against']
const TEXT_MAX = 140

const PROMPT: Record<ReactionType, { title: string; placeholder: string }> = {
  like: { title: '무엇이 좋았나요? (선택)', placeholder: '예: 국물이 진하고 양이 많아요' },
  neutral: { title: '무엇을 조율하면 좋을까요? (선택)', placeholder: '예: 점심보다 저녁이 좋아요' },
  against: { title: '왜 별로인가요? (필수)', placeholder: '예: 지난번 여행 때 가봤어요' },
}

/** 제목 줄(시트 끌기 영역). 「‹ 마킹된 장소」(확정 탭에선 「‹ 확정된 장소」)는 시트 안 이전 화면 — 좌상단 ‹(내 지도 목록)와 다르다. */
export function PinDetailHeader({
  pin,
  mapId,
  backLabel = '마킹된 장소',
  onBack,
}: {
  pin: Pin
  mapId: string
  backLabel?: string
  onBack: () => void
}) {
  const add = useAddToShortlistMutation(mapId)
  const confirmed = pin.kind === '확정'

  return (
    <div>
      <button type="button" onClick={onBack} className="mb-2 text-[13px] font-medium text-ink-500">
        ‹ {backLabel}
      </button>
      <div className="flex items-center justify-between gap-2">
        <h2 className="truncate text-[22px] font-bold text-ink-900">{pin.place_name ?? '이름 없는 장소'}</h2>
        {confirmed ? (
          <span className="shrink-0 rounded-lg border-[1.5px] border-[var(--pin-confirmed)] bg-[var(--confirmed-bg)] px-2.5 py-1.5 text-xs font-bold text-[var(--pin-confirmed-mark)]">
            ✓ 확정됨
          </span>
        ) : (
          pin.permissions.can_add_to_shortlist && (
            // 채움 버튼이 아니다 — 이 화면의 채움 버튼은 「의견 등록」 하나다.
            <button
              type="button"
              disabled={add.isPending}
              onClick={() =>
                add.mutate(pin.id, {
                  onSuccess: () => {
                    const name = pin.place_name ?? '이 장소'
                    showToast(`${name}${josa(name, '을', '를')} 확정 리스트에 넣었어요`)
                  },
                  onError: () => showToast('확정 리스트에 넣지 못했어요'),
                })
              }
              className="shrink-0 rounded-lg border-[1.5px] border-[var(--pin-confirmed)] bg-[var(--confirmed-bg)] px-2.5 py-1.5 text-xs font-bold text-[var(--pin-confirmed-mark)] disabled:opacity-50"
            >
              ★ 확정 리스트에 넣기
            </button>
          )
        )}
      </div>
    </div>
  )
}

/** 핀 상세 본문(Figma 5절 '마킹된 장소 상세'). */
export function PinDetailBody({
  pin,
  mapId,
  members,
  onDone,
}: {
  pin: Pin
  mapId: string
  members: MemberView[]
  /** 의견을 등록하면 목록으로 돌아간다(Figma '의견 등록 후'). */
  onDone: () => void
}) {
  const reactions = useReactionsQuery(pin.id)
  const memberCount = members.length
  const s = pin.reaction_summary
  const mine = pin.my_reaction?.type ?? null

  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <p className="text-[13px] text-ink-600">
          {pin.category}
          {pin.created_by_display_name && <span className="text-ink-500"> · {pin.created_by_display_name}님이 찍은 핀</span>}
        </p>
        {/* 색만으로는 1/4와 2/4가 잘 안 갈려서 숫자로 꼭 적는다(colors.md 3절 한계). */}
        {memberCount > 0 && (
          <p className="text-xs font-bold text-ink-600">
            {participants(pin)}/{memberCount}명이 의견을 남겼어요
          </p>
        )}
        <div className="flex flex-wrap items-center gap-3 border-y border-ink-200 py-2 text-[13px]">
          {TYPES.map((t) => (
            <span
              key={t}
              className="flex items-center gap-1 font-bold"
              style={mine === t ? { background: R[t].bg, border: `1px solid ${R[t].line}`, color: R[t].text, padding: '2px 8px', borderRadius: 8 } : undefined}
            >
              <span style={{ color: R[t].line }}>{R[t].mark}</span>
              <span className={mine === t ? '' : 'text-ink-900'}>{R[t].label}</span>
              <span style={mine === t ? undefined : { color: R[t].text }}>{s[t]}</span>
              {mine === t && '· 나'}
            </span>
          ))}
          <span className="flex items-center gap-1 font-bold">
            <span className="text-ink-500">?</span> <span className="text-ink-900">미확인</span>
            <span className="text-ink-600">{Math.max(0, memberCount - participants(pin))}</span>
          </span>
        </div>
      </div>

      <PlaceInfo pin={pin} />

      {reactions.error ? (
        <ErrorText message="구성원 의견을 불러오지 못했어요" error={reactions.error} />
      ) : (
        reactions.data && <Opinions {...toOpinions(reactions.data, members)} />
      )}

      <div className="-mx-4 h-1.5 bg-ink-100" />

      {pin.permissions.can_react ? (
        <MyOpinion key={pin.my_reaction?.type ?? 'none'} pin={pin} mapId={mapId} onDone={onDone} />
      ) : (
        // 숙소 핀은 반응을 받지 않는다(#154). v1엔 숙소 핀이 없지만 권한이 꺼져 오면 그린다.
        <p className="text-sm text-ink-500">이 장소에는 의견을 남길 수 없어요</p>
      )}
    </div>
  )
}

/**
 * 장소 사진·주소·전화는 핀 응답에 없다(카카오 응답은 저장 금지, #53). 그래서 사진 자리엔 Figma 의
 * '사진이 없어요' 표시를 두고, 자세한 정보는 카카오맵으로 보낸다. 앱 안 WebView 금지 — 새 창으로 연다.
 */
function PlaceInfo({ pin }: { pin: Pin }) {
  return (
    <div className="space-y-2">
      <div className="relative flex h-[100px] flex-col items-center justify-center gap-1 rounded-xl bg-ink-100 text-ink-500">
        <span className="absolute left-3 top-3 rounded-xl bg-ink-900/80 px-2.5 py-1 text-[11px] font-bold text-white">{pin.category}</span>
        <ImageOff size={20} aria-hidden="true" />
        <p className="text-xs">사진이 없어요</p>
      </div>
      {pin.place_url && (
        <a
          href={pin.place_url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2 rounded-xl bg-ink-50 p-3.5 text-[13px] font-bold text-brand-600"
        >
          카카오맵에서 자세히 보기 <ExternalLink size={14} aria-hidden="true" />
        </a>
      )}
    </div>
  )
}

function Opinions({ split, likes, unknown }: ReturnType<typeof toOpinions>) {
  const [showLikes, setShowLikes] = useState(false)
  const nameOf = (o: { name: string; isMe: boolean }) => `${o.name}${o.isMe ? ' (나)' : ''}`

  return (
    <section className="space-y-2.5">
      {split.length > 0 && (
        <>
          <h3 className="text-[15px] font-bold text-ink-900">갈린 의견 {split.length}</h3>
          <ul className="divide-y divide-ink-200 overflow-hidden rounded-xl bg-ink-50">
            {split.map((o) => (
              <OpinionRow key={o.userId} o={o} name={nameOf(o)} />
            ))}
          </ul>
        </>
      )}
      {likes.length > 0 && (
        <div>
          <div className="flex items-center justify-between text-[13px]">
            <p className="font-medium text-ink-900">
              <span style={{ color: R.like.line }}>♥</span> {likes.map(nameOf).join(' · ')} 좋아해요
            </p>
            {likes.some((l) => l.chips.length || l.text) && (
              <button type="button" onClick={() => setShowLikes((v) => !v)} className="text-xs font-medium text-ink-500">
                {showLikes ? '접기 ▴' : '펼치기 ▾'}
              </button>
            )}
          </div>
          {showLikes && (
            <ul className="mt-2 divide-y divide-ink-200 overflow-hidden rounded-xl bg-ink-50">
              {likes.map((o) => (
                <OpinionRow key={o.userId} o={o} name={nameOf(o)} />
              ))}
            </ul>
          )}
        </div>
      )}
      {unknown.map((m) => (
        <p key={m.userId} className="text-[13px] text-ink-500">
          ? {m.isMe ? '나는 아직 의견을 안 남겼어요' : `${m.name}님이 아직 의견을 안 남겼어요`}
        </p>
      ))}
    </section>
  )
}

function OpinionRow({ o, name }: { o: OpinionView; name: string }) {
  return (
    <li className="space-y-1 px-3 py-2.5">
      <p className="flex flex-wrap items-center gap-1.5 text-[13px]">
        <span className="rounded-lg px-1.5 py-px text-xs font-bold" style={{ background: R[o.type].bg, color: R[o.type].text }}>
          {R[o.type].mark} {R[o.type].label}
        </span>
        <span className="font-medium text-ink-900">{name}</span>
        {o.chips.length > 0 && <span className="font-bold text-ink-900">· {o.chips.join(' · ')}</span>}
      </p>
      {o.text && <p className="text-[13px] text-ink-600">“{o.text}”</p>}
    </li>
  )
}

/**
 * 「내 의견 선택」. 조율·반대는 아래에 사유 입력이 펼쳐진다. 등록 전까지 위 집계는 바뀌지 않는다.
 * 반대는 칩이나 글 중 하나가 있어야 등록된다(가드레일 3). 이 화면의 채움 버튼은 「의견 등록」 하나다.
 */
function MyOpinion({ pin, mapId, onDone }: { pin: Pin; mapId: string; onDone: () => void }) {
  const saved = pin.my_reaction
  const [type, setType] = useState<ReactionType | null>(saved?.type ?? null)
  const [chips, setChips] = useState<string[]>(saved?.reason_chip_ids ?? [])
  const [text, setText] = useState(saved?.reason_text ?? '')
  const react = useMyReactionMutation(mapId, pin)
  const chipOptions = REASON_CHIPS[pin.category] ?? []
  const missingReason = type === 'against' && chips.length === 0 && text.trim() === ''

  function submit() {
    if (!type || missingReason) return
    const body = {
      type,
      ...(text.trim() ? { reason_text: text.trim() } : {}),
      ...(type === 'against' && chips.length ? { reason_chip_ids: chips } : {}),
    }
    react.mutate(body, {
      onSuccess: () => {
        showToast('의견을 남겼어요')
        onDone()
      },
      onError: (err) =>
        showToast(
          err instanceof ApiError && err.code === 'EVIDENCE_REQUIRED' ? '반대 이유를 하나 이상 남겨 주세요' : '의견을 등록하지 못했어요',
          { label: '다시 시도', onClick: submit },
        ),
    })
  }

  function cancel() {
    const previous: ReactionDto | null | undefined = saved
    react.mutate(null, {
      onSuccess: () =>
        showToast('의견을 거뒀어요', {
          label: '되돌리기',
          onClick: () =>
            previous &&
            react.mutate({ type: previous.type, reason_text: previous.reason_text, reason_chip_ids: previous.reason_chip_ids }),
        }),
      onError: () => showToast('의견을 취소하지 못했어요'),
    })
  }

  return (
    <section className="space-y-2.5 pb-4">
      <div className="flex items-center justify-between">
        <h3 className="text-[15px] font-bold text-ink-900">내 의견 선택</h3>
        {saved && (
          <button type="button" onClick={cancel} disabled={react.isPending} className="text-[13px] font-medium text-ink-500 underline">
            의견 취소
          </button>
        )}
      </div>
      <div role="radiogroup" aria-label="내 의견" className="grid grid-cols-3 gap-1.5">
        {TYPES.map((t) => {
          const on = type === t
          return (
            <button
              key={t}
              type="button"
              role="radio"
              aria-checked={on}
              onClick={() => setType(t)}
              className="flex flex-col items-center gap-0.5 rounded-xl border py-2"
              style={on ? { background: R[t].bg, borderColor: R[t].line } : { background: '#fff', borderColor: 'var(--ink-200)' }}
            >
              <span style={{ color: R[t].line }}>{R[t].mark}</span>
              <span className="text-xs font-bold" style={{ color: on ? R[t].text : 'var(--ink-600)' }}>
                {R[t].label}
              </span>
            </button>
          )
        })}
      </div>

      {type && (
        <div className="space-y-2">
          <p className="text-[13px] font-bold text-ink-900">{PROMPT[type].title}</p>
          {type === 'against' && chipOptions.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {chipOptions.map((chip) => {
                const on = chips.includes(chip)
                return (
                  <button
                    key={chip}
                    type="button"
                    aria-pressed={on}
                    onClick={() => setChips((cs) => (on ? cs.filter((c) => c !== chip) : [...cs, chip]))}
                    className={`rounded-full border px-3 py-1.5 text-[13px] ${
                      on ? 'border-[var(--bad-line)] bg-[var(--bad-bg)] font-bold text-[var(--bad-text)]' : 'border-ink-300 bg-white font-medium text-ink-700'
                    }`}
                  >
                    {chip}
                  </button>
                )
              })}
            </div>
          )}
          <div className="flex items-center gap-2 rounded-xl border-[1.5px] border-ink-300 bg-white py-3 pl-3.5 pr-3 focus-within:border-[var(--line-focus)]">
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              maxLength={TEXT_MAX}
              placeholder={PROMPT[type].placeholder}
              aria-label={PROMPT[type].title}
              className="min-w-0 flex-1 bg-transparent text-[13px] outline-none"
            />
            {text && (
              <button type="button" aria-label="사유 지우기" onClick={() => setText('')} className="flex size-[18px] items-center justify-center rounded-full bg-ink-300 text-white">
                <X size={10} />
              </button>
            )}
            <span className="text-[11px] text-ink-500">
              {text.length}/{TEXT_MAX}
            </span>
          </div>
          {type === 'against' && <p className="text-[11px] text-ink-500">자세히 적을수록 더 정확한 추천을 받을 수 있어요</p>}
        </div>
      )}

      <button
        type="button"
        onClick={submit}
        disabled={!type || missingReason || react.isPending}
        className="w-full rounded-xl bg-brand-600 py-2.5 text-sm font-bold text-white disabled:bg-ink-100 disabled:text-ink-400"
      >
        {react.isPending ? '등록하는 중…' : '의견 등록'}
      </button>
    </section>
  )
}
