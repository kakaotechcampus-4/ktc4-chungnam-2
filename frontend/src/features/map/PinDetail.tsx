import { useId, useRef, useState, type ReactNode } from 'react'
import { ExternalLink } from 'lucide-react'

import { ApiError } from '@/api'
import ErrorText from '@/ErrorText'
import type { MemberView } from '@/features/maps/model'
import { useMeQuery } from '@/features/auth/queries'
import PanelBackLink from '@/features/shell/PanelBackLink'
import { showToast } from '@/features/shell/toast'
import { useAddToShortlistMutation } from '@/features/shortlist/queries'
import ConfirmDialog from '@/ui/ConfirmDialog'
import AgainstMark from '@/ui/AgainstMark'
import { josa } from '@/ui/josa'
import SheetTitle from '@/ui/SheetTitle'
import TextField from '@/ui/TextField'

import { isLive, locationState, useLivePlaceStore } from './livePlaces'
import { asReactionType, FILTER_CATEGORIES, participants, pinEditErrorMessage, toOpinions, type OpinionView, type Pin, type PinCategory, type PinUpdateRequest, type ReactionDto, type ReactionType, type ReasonChip } from './model'
import { useDeletePinMutation, useMyReactionMutation, useReactionsQuery, useReasonChipsQuery, useUpdatePinMutation } from './queries'

/** 반응 색 세트(colors.md 시맨틱 — 배경·선·글자 세 값이 한 세트). 용어·기호는 기획안 9절 고정. */
const R: Record<ReactionType, { mark: ReactNode; label: string; bg: string; line: string; text: string }> = {
  like: { mark: '♥', label: '좋음', bg: 'var(--good-bg)', line: 'var(--good-line)', text: 'var(--good-text)' },
  against: { mark: <AgainstMark />, label: '반대', bg: 'var(--bad-bg)', line: 'var(--bad-line)', text: 'var(--bad-text)' },
}
const TYPES: ReactionType[] = ['like', 'against']
const TEXT_MAX = 140
/** 서버가 같은 이유(EVIDENCE_REQUIRED)로 막을 때도 같은 문구다. */
const MISSING_REASON = '반대 이유를 하나 이상 남겨 주세요'
const MEMO_MAX = 200

const PROMPT: Record<ReactionType, { title: string; placeholder: string }> = {
  like: { title: '무엇이 좋았나요? (선택)', placeholder: '예: 국물이 진하고 양이 많아요' },
  against: { title: '왜 별로인가요? (필수)', placeholder: '예: 지난번 여행 때 가봤어요' },
}

/**
 * 제목 줄(시트 끌기 영역). 「‹ 마킹된 장소」(확정 탭에선 「‹ 확정된 장소」)는 시트 안 이전 화면 — 모바일 좌상단 ‹(내 지도 목록)와 다르다.
 * 넓은 화면은 이 ‹ 가 패널 헤더 ‹ 로 옮겨 간다(PanelBackLink).
 */
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
      <PanelBackLink label={backLabel} onBack={onBack} />
      {/* 자리가 없으면(긴 이름·큰 글자) 확정 버튼이 제목 아래 줄로 내려간다(#406). */}
      <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1.5">
        <SheetTitle>{pin.place_name ?? '이름 없는 장소'}</SheetTitle>
        {confirmed ? (
          <span className="btn-confirm btn-sm">
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
              className="btn-confirm btn-sm"
            >
              ★ 확정 리스트에 넣기
            </button>
          )
        )}
      </div>
    </div>
  )
}

/**
 * 실시간 핀(#382) — 자체 장소 데이터에 없는 곳을 사람이 남긴 핀. 조건 확인·AI 추천·동선에는 쓰이지 않는다.
 * 위치는 지도를 열 때마다 카카오에서 다시 찾는다(못 찾으면 지도에 안 뜬다).
 */
function LiveInfo({ pin }: { pin: Pin }) {
  const places = useLivePlaceStore((s) => s.places)
  const state = locationState(pin, places)
  return (
    <div className="space-y-1.5 rounded-xl bg-ink-50 p-3 text-body">
      <p className="font-semibold text-ink-900">장소 정보가 없는 핀이에요</p>
      <p className="text-ink-600">우리 장소 데이터에 없는 곳이라 조건 확인·AI 추천·동선에는 쓰이지 않아요. 의견은 그대로 남길 수 있어요.</p>
      {state === 'loading' && <p className="text-ink-500">위치를 찾는 중이에요…</p>}
      {state === 'missing' && <p className="font-semibold text-warn-text">카카오에서 이 장소의 위치를 다시 찾지 못했어요. 지도에는 표시되지 않아요.</p>}
    </div>
  )
}

/**
 * 핀을 찍은 사람이 남긴 한마디(#466). 찍은 사람만 쓰고 고친다(`can_edit`) — AI 추천·확정 핀은 고칠 수 없다.
 * 메모가 없고 고칠 수도 없으면 줄을 그리지 않는다.
 */
function PinMemo({ pin, mapId }: { pin: Pin; mapId: string }) {
  const [editing, setEditing] = useState(false)
  const canEdit = pin.permissions.can_edit === true
  if (!pin.memo && !canEdit) return null
  return (
    <div className="flex items-start justify-between gap-2 text-body">
      {pin.memo ? <p className="min-w-0 break-words text-ink-900">“{pin.memo}”</p> : <span />}
      {canEdit && (
        <button type="button" onClick={() => setEditing(true)} className="btn-link shrink-0">
          {pin.memo ? '메모 수정' : '+ 메모 남기기'}
        </button>
      )}
      {editing && <EditPinDialog pin={pin} mapId={mapId} onCancel={() => setEditing(false)} />}
    </div>
  )
}

/**
 * 핀 메모·분류 수정 창(#480). 바뀐 칸만 보낸다. 빈 메모는 지우기다.
 * 분류는 실시간 핀만 바꿀 수 있다 — 자체 DB 핀의 분류는 장소가 정한다. 의견이 달린 핀의 분류는 서버가 422로 막는다.
 * 그 판정은 화면이 따로 하지 않고 서버 문구를 그대로 보여 준다(pinEditErrorMessage).
 */
function EditPinDialog({ pin, mapId, onCancel }: { pin: Pin; mapId: string; onCancel: () => void }) {
  const update = useUpdatePinMutation(mapId, pin.id)
  const [memo, setMemo] = useState(pin.memo ?? '')
  const [category, setCategory] = useState<PinCategory>(pin.category)
  const live = isLive(pin)

  const body: PinUpdateRequest = {}
  if (memo.trim() !== (pin.memo ?? '')) body.memo = memo.trim()
  if (category !== pin.category) body.category = category
  const changed = Object.keys(body).length > 0

  return (
    <ConfirmDialog
      title={live ? '메모·분류 수정' : '메모 수정'}
      body="이 핀을 찍은 사람만 고칠 수 있어요. 비우고 저장하면 메모가 지워져요."
      ok="저장"
      pending={update.isPending || !changed}
      onCancel={onCancel}
      onOk={() =>
        update.mutate(body, {
          onSuccess: () => {
            showToast('핀을 고쳤어요')
            onCancel()
          },
        })
      }
    >
      <div className="pt-2">
        <TextField value={memo} onChange={setMemo} maxLength={MEMO_MAX} label="메모" placeholder="예: 여기 곱창 맛있대" clearLabel="메모 지우기" />
      </div>
      {live && (
        <div role="group" aria-label="분류" className="flex flex-wrap gap-2 pt-1">
          {FILTER_CATEGORIES.map((c) => (
            <button key={c} type="button" aria-pressed={category === c} onClick={() => setCategory(c)} className="chip">
              {c}
            </button>
          ))}
        </div>
      )}
      {update.error && <ErrorText message={pinEditErrorMessage(update.error)} error={update.error} />}
    </ConfirmDialog>
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
  const chips = useReasonChipsQuery(pin.category)
  const memberCount = members.length
  const s = pin.reaction_summary
  const mine = pin.my_reaction?.type ?? null
  const myId = useMeQuery().data?.id

  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <p className="flex flex-wrap items-center gap-x-1 text-body text-ink-600">
          {pin.category}
          <span className="text-ink-500">· {pin.created_by === myId ? '내가 찍은 핀' : `${pin.created_by_display_name ?? '탈퇴한 구성원'}님이 찍은 핀`}</span>
          {/* 사진·주소·전화는 핀 응답에 없다(카카오 응답 저장 금지, #53) — 자세한 정보는 카카오맵 새 창으로. */}
          {pin.place_url && (
            <a href={pin.place_url} target="_blank" rel="noopener noreferrer" className="btn-link ml-auto">
              카카오맵에서 보기 <ExternalLink size={12} aria-hidden="true" />
            </a>
          )}
        </p>
        <PinMemo pin={pin} mapId={mapId} />
        {isLive(pin) && <LiveInfo pin={pin} />}
        {/* 색만으로는 1/4와 2/4가 잘 안 갈려서 숫자로 꼭 적는다(colors.md 3절 한계). */}
        {memberCount > 0 && (
          <p className="text-xs font-bold text-ink-600">
            {participants(pin)}/{memberCount}명이 의견을 남겼어요
          </p>
        )}
        <div className="flex flex-wrap items-center gap-3 border-y border-ink-200 py-2 text-body">
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

      {/* 2단계에서 바로 보이게 「내 의견」을 구성원 의견보다 위에 둔다(#308). */}
      {pin.permissions.can_react ? (
        // 핀마다 새로 그린다. 의견을 취소해도 고른 의견·사유는 남겨 「의견 등록」만 다시 누르면 되돌아간다(#959).
        <MyOpinion key={pin.id} pin={pin} mapId={mapId} chipOptions={chips.data ?? []} chipsError={chips.error} onDone={onDone} />
      ) : (
        // 숙소 핀은 반응을 받지 않는다(#154). v1엔 숙소 핀이 없지만 권한이 꺼져 오면 그린다.
        <p className="text-sm text-ink-500">이 장소에는 의견을 남길 수 없어요</p>
      )}

      <div className="-mx-4 h-1.5 bg-ink-100" />

      {reactions.error ? (
        <ErrorText message="구성원 의견을 불러오지 못했어요" error={reactions.error} />
      ) : (
        reactions.data && <Opinions {...toOpinions(reactions.data, members, chips.data)} />
      )}

      {pin.permissions.can_delete && <DeletePin pin={pin} mapId={mapId} onDone={onDone} />}
    </div>
  )
}

/** 핀 삭제 — 구성원 누구나 남의 핀도 지울 수 있다(기획안 #25). 지우면 그 핀의 의견과 확정 리스트 항목도 함께 사라진다. */
function DeletePin({ pin, mapId, onDone }: { pin: Pin; mapId: string; onDone: () => void }) {
  const [asking, setAsking] = useState(false)
  const del = useDeletePinMutation(mapId, pin.id)
  const name = pin.place_name ?? '이 핀'
  return (
    <div className="border-t border-ink-200 pt-3 text-center">
      <button type="button" onClick={() => setAsking(true)} className="btn-text text-body underline">
        핀 삭제
      </button>
      {asking && (
        <ConfirmDialog
          title="이 핀을 삭제할까요?"
          body={`${name} 핀과 거기에 남긴 의견이 모든 구성원에게서 사라져요. 확정 리스트에 있으면 함께 빠져요.`}
          ok="삭제"
          danger
          pending={del.isPending}
          onCancel={() => setAsking(false)}
          onOk={() =>
            del.mutate(undefined, {
              onSuccess: () => {
                setAsking(false)
                showToast(`${name}${josa(name, '을', '를')} 삭제했어요`)
                onDone()
              },
              onError: () => showToast('핀을 삭제하지 못했어요'),
            })
          }
        />
      )}
    </div>
  )
}

function Opinions({ split: all, likes, unknown }: ReturnType<typeof toOpinions>) {
  // 내 의견은 위 「내 의견」에 이미 있어서 갈린 의견에선 뺀다.
  const split = all.filter((o) => !o.isMe)
  const [showLikes, setShowLikes] = useState(false)
  const nameOf = (o: { name: string; isMe: boolean }) => `${o.name}${o.isMe ? ' (나)' : ''}`

  return (
    <section className="space-y-2.5">
      {split.length > 0 && (
        <>
          <h3 className="text-sm font-bold text-ink-900">갈린 의견 {split.length}</h3>
          <ul className="divide-y divide-ink-200 overflow-hidden rounded-xl bg-ink-50">
            {split.map((o) => (
              <OpinionRow key={o.userId} o={o} name={nameOf(o)} />
            ))}
          </ul>
        </>
      )}
      {likes.length > 0 && (
        <div>
          <div className="flex items-center justify-between text-body">
            <p className="font-medium text-ink-900">
              <span style={{ color: R.like.line }}>♥</span> {likes.map(nameOf).join(' · ')} 좋아해요
            </p>
            {likes.some((l) => l.chips.length || l.text) && (
              <button type="button" onClick={() => setShowLikes((v) => !v)} className="btn-text text-xs">
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
      {unknown.some((m) => !m.isMe) && (
        <p className="text-body text-ink-500">
          ? 아직 안 남겼어요 · {unknown.filter((m) => !m.isMe).map((m) => m.name).join(' · ')}
        </p>
      )}
    </section>
  )
}

function OpinionRow({ o, name }: { o: OpinionView; name: string }) {
  return (
    <li className="space-y-1 px-3 py-2.5">
      <p className="flex flex-wrap items-center gap-1.5 text-body">
        <span className="tag" style={{ background: R[o.type].bg, color: R[o.type].text }}>
          {R[o.type].mark} {R[o.type].label}
        </span>
        <span className="font-medium text-ink-900">{name}</span>
        {o.chips.length > 0 && <span className="font-bold text-ink-900">· {o.chips.join(' · ')}</span>}
      </p>
      {o.text && <p className="text-body text-ink-600">“{o.text}”</p>}
    </li>
  )
}

/**
 * 「내 의견 선택」. 고르면 아래에 사유 입력이 펼쳐진다. 등록 전까지 위 집계는 바뀌지 않는다.
 * 반대는 칩이나 글 중 하나가 있어야 등록된다(가드레일 3). 이 화면의 채움 버튼은 「의견 등록」 하나다.
 */
function MyOpinion({
  pin,
  mapId,
  chipOptions,
  chipsError,
  onDone,
}: {
  pin: Pin
  mapId: string
  /** 화면엔 label, 요청엔 id 를 보낸다 — 이름을 보내면 서버가 422 로 막는다. */
  chipOptions: ReasonChip[]
  chipsError: Error | null
  onDone: () => void
}) {
  const saved = pin.my_reaction
  const [type, setType] = useState<ReactionType | null>(asReactionType(saved?.type))
  const [chips, setChips] = useState<string[]>(saved?.reason_chip_ids ?? [])
  const [text, setText] = useState(saved?.reason_text ?? '')
  const react = useMyReactionMutation(mapId, pin)
  const missingReason = type === 'against' && chips.length === 0 && text.trim() === ''
  // 사유 없이 반대를 누르면 버튼을 끄지 않고 이유를 입력칸 아래에 알린다 — 꺼진 버튼은 왜 막혔는지 읽히지 않는다(#959).
  const [triedEmpty, setTriedEmpty] = useState(false)
  const reasonRef = useRef<HTMLInputElement>(null)
  const reasonErrorId = useId()
  const showMissing = triedEmpty && missingReason

  function submit() {
    if (!type) return
    if (missingReason) {
      setTriedEmpty(true)
      reasonRef.current?.focus()
      return
    }
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
          err instanceof ApiError && err.code === 'EVIDENCE_REQUIRED' ? MISSING_REASON : '의견을 등록하지 못했어요',
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
    <section className="space-y-2.5">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-bold text-ink-900">내 의견 선택</h3>
        {saved && (
          <button type="button" onClick={cancel} disabled={react.isPending} className="btn-text text-body underline">
            의견 취소
          </button>
        )}
      </div>
      <div role="radiogroup" aria-label="내 의견" className="grid grid-cols-2 gap-1.5">
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
              style={on ? { background: R[t].bg, borderColor: R[t].line } : { background: 'var(--surface-card)', borderColor: 'var(--ink-200)' }}
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
          <p className="text-body font-bold text-ink-900">{PROMPT[type].title}</p>
          {type === 'against' && chipOptions.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {chipOptions.map((chip) => {
                const on = chips.includes(chip.id)
                return (
                  <button
                    key={chip.id}
                    type="button"
                    aria-pressed={on}
                    onClick={() => setChips((cs) => (on ? cs.filter((c) => c !== chip.id) : [...cs, chip.id]))}
                    className="chip chip-against"
                  >
                    {chip.label}
                  </button>
                )
              })}
            </div>
          )}
          {type === 'against' && chipsError && <ErrorText message="사유 칩을 불러오지 못했어요 — 글로 적어 주세요" error={chipsError} />}
          <TextField
            value={text}
            onChange={setText}
            maxLength={TEXT_MAX}
            placeholder={PROMPT[type].placeholder}
            label={PROMPT[type].title}
            clearLabel="사유 지우기"
            inputRef={reasonRef}
            describedBy={showMissing ? reasonErrorId : undefined}
          />
          {showMissing && (
            <p id={reasonErrorId} className="text-xs font-semibold text-warn-text">
              {MISSING_REASON}
            </p>
          )}
          {type === 'against' && <p className="text-label text-ink-500">자세히 적을수록 더 정확한 추천을 받을 수 있어요</p>}
        </div>
      )}

      <button
        type="button"
        onClick={submit}
        disabled={!type || react.isPending}
        className="btn-primary btn-md w-full"
      >
        {react.isPending ? '등록하는 중…' : '의견 등록'}
      </button>
    </section>
  )
}
