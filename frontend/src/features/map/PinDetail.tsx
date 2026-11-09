import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router'

import { ApiError } from '@/api'
import ErrorText from '@/ErrorText'
import type { MemberView } from '@/features/maps/model'
import { useMeQuery } from '@/features/auth/queries'
import { AiChecks, AiFulfillment, AiReason } from '@/features/recommend/Evidence'
import { hasReviews } from '@/features/reviews/model'
import PlaceReviews from '@/features/reviews/PlaceReviews'
import PanelBackLink from '@/features/shell/PanelBackLink'
import { showToast } from '@/features/shell/toast'
import { useAddToShortlistMutation, useUnconfirm } from '@/features/shortlist/queries'
import BlogPhotos from '@/ui/BlogPhotos'
import ConfirmDialog from '@/ui/ConfirmDialog'
import Mark from '@/ui/Mark'
import ProgressBar from '@/ui/ProgressBar'
import FieldError from '@/ui/FieldError'
import { josa } from '@/ui/josa'
import MapAppLinks from '@/ui/MapAppLinks'
import SheetTitle from '@/ui/SheetTitle'
import TextField from '@/ui/TextField'
import Sentences from '@/ui/Sentences'
import UnknownName from '@/ui/UnknownName'
import PeopleProof from '@/ui/PeopleProof'
import BusyLabel from '@/ui/BusyLabel'

import { isLive, LOCATE_SLOW_MS, locationState, useLivePlaceStore } from './livePlaces'
import ReactionHelp from './ReactionHelp'
import { asReactionType, authorName, FILTER_CATEGORIES, hasAiEvidence, inputExample, participants, pinEditErrorMessage, toOpinions, type OpinionView, type Pin, type PinCategory, type PinUpdateRequest, type ReactionDto, type ReactionType, type ReasonChip } from './model'
import { useMyReactionMutation, usePinPhotosQuery, usePinTrashQuery, useReactionsQuery, useReasonChipsQuery, useTrashPinMutation, useUpdatePinMutation } from './queries'

/** 반응 색 세트(colors.md 시맨틱 — 배경·선·글자 세 값이 한 세트). 용어·기호는 기획안 9절 고정. */
const R: Record<ReactionType, { mark: ReactNode; label: string; bg: string; line: string; text: string }> = {
  like: { mark: <Mark kind="like" />, label: '좋음', bg: 'var(--good-bg)', line: 'var(--good-line)', text: 'var(--good-text)' },
  against: { mark: <Mark kind="against" />, label: '반대', bg: 'var(--bad-bg)', line: 'var(--bad-line)', text: 'var(--bad-text)' },
}
const TYPES: ReactionType[] = ['like', 'against']
const TEXT_MAX = 140
/** 서버가 같은 이유(EVIDENCE_REQUIRED)로 막을 때도 같은 문구다. */
const MISSING_REASON = '반대 이유를 하나 이상 남겨 주세요'
const MEMO_MAX = 200

/** 입력칸 예시 문장은 카테고리마다 다르다 — `inputExample`(model). */
const PROMPT: Record<ReactionType, { title: string }> = {
  like: { title: '무엇이 좋았나요? (선택)' },
  against: { title: '왜 별로인가요? (필수)' },
}

/**
 * 제목 줄(시트 끌기 영역). 「‹ 핀 찍기」(확정 탭에선 「‹ 장소 확정」)는 시트 안 이전 화면 — 모바일 좌상단 ‹(내 지도 목록)와 다르다.
 * 넓은 화면은 이 ‹ 가 패널 헤더 ‹ 로 옮겨 간다(PanelBackLink).
 */
export function PinDetailHeader({
  pin,
  mapId,
  backLabel = '핀 찍기',
  onBack,
}: {
  pin: Pin
  mapId: string
  backLabel?: string
  onBack: () => void
}) {
  const add = useAddToShortlistMutation(mapId)
  const remove = useUnconfirm(mapId)
  const confirmed = pin.kind === '확정'
  const canToggle = confirmed ? pin.permissions.can_remove_from_shortlist : pin.permissions.can_add_to_shortlist
  const busy = add.isPending || remove.isPending
  const navigate = useNavigate()
  const name = pin.place_name ?? '이 장소'
  // 넣으면 확정 리스트로 가는 길을(#1030), 빼면 「되돌리기」를 토스트로 준다 — 핀 모양만으로는 뺐다는 걸 놓친다(#1576).
  const toggle = () =>
    confirmed
      ? remove.unconfirm(pin)
      : add.mutate(pin.id, {
          onSuccess: () =>
            showToast(`${name}${josa(name, '을', '를')} 확정 리스트에 넣었어요`, {
              label: '확정 리스트 보기',
              onClick: () => navigate(`/maps/${mapId}/shortlist`),
            }),
          onError: () => showToast('확정 리스트에 넣지 못했어요'),
        })

  return (
    <div>
      <PanelBackLink label={backLabel} onBack={onBack} />
      {/* 자리가 없으면(긴 이름·큰 글자) 확정 버튼이 제목 아래 줄로 내려간다(#406). */}
      <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1.5">
        <span className="flex min-w-0 items-center gap-1.5">
          <SheetTitle>{pin.place_name ?? '이름 없는 장소'}</SheetTitle>
          {/* AI 추천에서 올린 핀은 모두의 핀이 된 뒤에도 AI가 고른 곳임을 알린다(DESIGN.md 「지도 핀」, #1032). */}
          {hasAiEvidence(pin) && <span className="tag tag-ai">AI</span>}
        </span>
        {canToggle ? (
          // 켜고 끄는 버튼 하나다. 한 버튼이라 눌러도 포커스가 그대로다. 채움 버튼이 아니다 — 이 화면의 채움 버튼은 「의견 등록」 하나다.
          <button type="button" aria-pressed={confirmed} disabled={busy} onClick={toggle} className="btn-confirm btn-sm">
            {confirmed ? (
              <><Mark kind="check" size={14} /> 확정됨</>
            ) : (
              <>
                <Mark kind="star" size={14} /> 확정 리스트에 넣기
              </>
            )}
          </button>
        ) : (
          confirmed && <span className="btn-confirm btn-sm"><><Mark kind="check" size={14} /> 확정됨</></span>
        )}
      </div>
    </div>
  )
}

/**
 * 실시간 핀(#382) — 자체 장소 데이터에 없는 곳을 사람이 남긴 핀. 조건 확인·AI 추천·동선에는 쓰이지 않는다.
 * 위치는 지도를 열 때마다 카카오에서 다시 찾는다(못 찾으면 지도에 안 뜬다).
 */
export function LiveInfo({ pin }: { pin: Pin }) {
  const places = useLivePlaceStore((s) => s.places)
  const since = useLivePlaceStore((s) => s.since[pin.id])
  const retry = useLivePlaceStore((s) => s.retry)
  const state = locationState(pin, places)
  // 찾기 시작한 지 1분이 넘으면(검색 실패로 멈춘 경우 포함) 기다리게 두지 않고 다시 찾을지 묻는다.
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (state !== 'loading' || since === undefined) return
    const wait = since + LOCATE_SLOW_MS - Date.now()
    if (wait <= 0) return
    const t = setTimeout(() => setNow(Date.now()), wait)
    return () => clearTimeout(t)
  }, [state, since])
  const slow = state === 'loading' && since !== undefined && now >= since + LOCATE_SLOW_MS
  return (
    <div className="space-y-1.5 rounded-xl bg-ink-50 p-3 text-body">
      <p className="font-semibold text-ink-900">상세 정보가 등록되지 않은 장소예요</p>
      <p className="text-ink-600"><Sentences text="AI 추천이나 동선에는 반영되지 않지만, 구성원 간 의견은 자유롭게 나눌 수 있어요." /></p>
      {state === 'loading' && !slow && <p className="text-ink-500">장소 위치를 확인하는 중이에요…</p>}
      {slow && (
        <div className="flex items-center justify-between gap-2">
          <p className="text-ink-600">
            <Sentences text="위치를 아직 찾지 못했어요. 다시 시도할까요?" />
          </p>
          <button type="button" onClick={retry} className="btn-outline btn-sm shrink-0">
            다시 시도
          </button>
        </div>
      )}
      {state === 'missing' && <p className="font-semibold text-warn-text"><Sentences text="위치 정보를 확인할 수 없어 지도에 표시되지 않아요." /></p>}
    </div>
  )
}

/**
 * 핀을 찍은 사람이 남긴 한마디(#466). 찍은 사람만 쓰고 고친다(`can_edit`) — AI 추천·확정 핀은 고칠 수 없다.
 * 메모가 없고 고칠 수도 없으면 줄을 그리지 않는다.
 */
/**
 * AI 추천에서 올린 핀의 근거(가드레일 5). 올리기 전 후보 카드와 같은 부품으로 같은 값을 그린다 — 올린 뒤에도 그대로 보인다(#1032).
 */
function AiPinEvidence({ pin, members }: { pin: Pin; members: MemberView[] }) {
  return (
    <section aria-label="AI 추천 근거" className="mt-2 space-y-2 rounded-xl border-[1.5px] border-brand-300 bg-[var(--pingo-bg)] p-3">
      <p className="text-xs font-bold text-selected">AI가 추천한 이유</p>
      {pin.reason && <AiReason text={pin.reason} />}
      <AiChecks evidence={pin} />
      <AiFulfillment evidence={pin} members={members} />
    </section>
  )
}

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
      title={live ? '메모와 분류 수정' : '메모 수정'}
      body="비우고 저장하면 메모가 지워져요."
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
        <TextField value={memo} onChange={setMemo} maxLength={MEMO_MAX} label="메모" placeholder={inputExample(category, 'memo')} clearLabel="메모 지우기" />
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

/** 블로그 사진 줄(#1157). 실시간 핀은 부르지 않고 그리지 않는다. */
function PinPhotos({ pin }: { pin: Pin }) {
  const photos = usePinPhotosQuery(pin)
  if (pin.source === 'live') return null
  return (
    <div className="py-1">
      <BlogPhotos photos={photos.data} loading={photos.isPending} failed={photos.isError} />
    </div>
  )
}

/** 핀 상세 본문(Figma 5절 '마킹된 장소 상세', 지금 탭 이름은 핀 찍기). */
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
          {/* 동네는 서버가 자체 DB 주소에서 뽑는다. 실시간 핀과 주소 없는 장소는 없어서 비운다(#1564). */}
          {pin.neighborhood && <span>· {pin.neighborhood}</span>}
          <span className="text-ink-500">· {pin.created_by === myId ? '내가 찍은 핀' : <UnknownName text={`${authorName(pin)}님이 찍은 핀`} />}</span>
        </p>
        <PinPhotos pin={pin} />
        {/* 주소, 영업시간은 원본 장소 페이지에서 본다(카카오 응답 저장 금지, #53). 바로 눈에 띄게 버튼 줄로 둔다. 사진은 위 블로그 사진 줄(#1157). */}
        <div className="py-1">
          <MapAppLinks kakao={pin.place_url} naver={pin.naver_url} />
        </div>
        <PinMemo pin={pin} mapId={mapId} />
        {isLive(pin) && <LiveInfo pin={pin} />}
        {hasAiEvidence(pin) && <AiPinEvidence pin={pin} members={members} />}
        {/* 색만으로는 1/4와 2/4가 잘 안 갈려서 숫자로 꼭 적는다(colors.md 3절 한계). */}
        {memberCount > 0 && (
          <PinParticipants pin={pin} memberCount={memberCount} names={reactions.data?.map((r) => members.find((m) => m.userId === r.user_id)?.name ?? r.display_name ?? '구성원')} />
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
              <span style={mine === t ? undefined : { color: R[t].text }}>{s[t]}명</span>
              {mine === t && '· 나'}
            </span>
          ))}
          <span className="flex items-center gap-1 font-bold">
            <span className="text-ink-500"><Mark kind="unknown" /></span> <span className="text-ink-900">미확인</span>
            <span className="text-ink-600">{Math.max(0, memberCount - participants(pin))}명</span>
          </span>
          {/* 「미확인」이 장소 정보가 확인 안 됐다는 말로 읽히지 않게 뜻을 그 자리에서 연다(#1030). */}
          <span className="ml-auto">
            <ReactionHelp />
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

      {/* 장소 후기는 자체 DB 장소 핀에만(#953). 실시간 핀은 장소 정보가 없어 후기를 붙일 수 없다. */}
      {hasReviews(pin) && (
        <>
          <div className="-mx-4 h-1.5 bg-ink-100" />
          <PlaceReviews pin={pin} />
        </>
      )}

      {pin.permissions.can_delete && <DeletePin pin={pin} mapId={mapId} onDone={onDone} />}
    </div>
  )
}

/**
 * 핀 삭제 — 찍은 사람과 방장만(`can_delete`). 휴지통으로 옮겨져 보관 기간 안에 되살릴 수 있다(#864).
 * 끌어서 버리기(TrashDropZone)의 키보드·스크린리더 대안이라 확인 창을 남긴다. 되돌릴 수 있어서 빨간 버튼은 쓰지 않는다(DESIGN 영역 분리 규칙).
 */
function DeletePin({ pin, mapId, onDone }: { pin: Pin; mapId: string; onDone: () => void }) {
  const [asking, setAsking] = useState(false)
  const del = useTrashPinMutation(mapId)
  // 보관 일수는 서버 값으로 적는다(화면에 숫자를 두지 않는다). 확인 창을 열 때만 받는다.
  const days = usePinTrashQuery(mapId, asking).data?.retention_days
  return (
    <div className="border-t border-ink-200 pt-3 text-center">
      <button type="button" onClick={() => setAsking(true)} className="btn-text text-body underline">
        핀 삭제
      </button>
      {asking && (
        <ConfirmDialog
          title="이 핀을 삭제할까요?"
          body={days ? `삭제해요. ${days}일 안에 되돌릴 수 있어요` : '삭제해요. 지도 정보의 「삭제한 핀」에서 되돌릴 수 있어요'}
          ok="삭제"
          pending={del.isPending}
          onCancel={() => setAsking(false)}
          onOk={() =>
            // 알림·되돌리기·실패 알림은 훅이 띄운다.
            del.mutate(pin, {
              onSuccess: () => {
                setAsking(false)
                onDone()
              },
            })
          }
        />
      )}
    </div>
  )
}

/** 의견 요약 줄의 주어 — 「현성님, 지우님이」, 나도 있으면 「나와 현성님이」, 나뿐이면 「내가」. */
function subjectOf(people: { name: string; isMe: boolean }[]) {
  const others = people.filter((p) => !p.isMe).map((p) => `${p.name}님`).join(', ')
  if (!others) return '내가'
  return people.some((p) => p.isMe) ? `나와 ${others}이` : `${others}이`
}

function Opinions({ split: all, likes, unknown }: ReturnType<typeof toOpinions>) {
  // 내 의견은 위 「내 의견」에 이미 있어서 갈린 의견에선 뺀다.
  const split = all.filter((o) => !o.isMe)
  const waiting = unknown.filter((m) => !m.isMe)
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
              <span style={{ color: R.like.line }}>{R.like.mark}</span> {subjectOf(likes)} 좋아해요
            </p>
            {likes.some((l) => l.chips.length || l.text) && (
              <button type="button" onClick={() => setShowLikes((v) => !v)} className="btn-text inline-flex items-center gap-0.5 text-xs">
                {showLikes ? '접기' : '펼치기'}
                {showLikes ? <Mark kind="chevronUp" size={14} /> : <Mark kind="chevronDown" size={14} />}
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
      {waiting.length > 0 && (
        // 의견을 기다리는 사람은 눈에 띄게 둔다 — 여럿이면 「○○님 외 N명」으로 줄인다(#1576).
        <p className="flex items-center gap-1.5 rounded-xl border border-brand-200 bg-brand-100 px-3 py-2.5 text-body font-semibold text-[var(--selected-text)]">
          <Mark kind="unknown" /> {waiting.length > 1 ? `${waiting[0].name}님 외 ${waiting.length - 1}명이` : `${waiting[0].name}님이`} 아직 의견을
          남기지 않았어요
        </p>
      )}
    </section>
  )
}

function OpinionRow({ o, name }: { o: OpinionView; name: string }) {
  const reasons = o.text ? [...o.chips, `“${o.text}”`] : o.chips
  return (
    <li className="space-y-1 px-3 py-2.5">
      <p className="flex flex-wrap items-center gap-1.5 text-body">
        <span className="tag" style={{ background: R[o.type].bg, color: R[o.type].text }}>
          {R[o.type].mark} {R[o.type].label}
        </span>
        <span className="font-medium text-ink-900">{name}</span>
      </p>
      {/* 고른 칩과 쓴 글은 같은 줄·같은 글자로 둔다 — 칩만 굵게 이름 옆에 붙어 있어 사람마다 모양이 달랐다(#1576). 쓴 글만 따옴표다. */}
      {reasons.length > 0 && <p className="text-body text-ink-700">{reasons.join(' · ')}</p>}
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
        showToast('의견을 취소했어요', {
          label: '되돌리기',
          onClick: () =>
            previous &&
            react.mutate(
              { type: previous.type, reason_text: previous.reason_text, reason_chip_ids: previous.reason_chip_ids },
              { onError: () => showToast('의견을 되돌리지 못했어요') },
            ),
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
              className="press flex flex-col items-center gap-0.5 rounded-xl border py-2"
              style={on ? { backgroundColor: R[t].bg, borderColor: R[t].line } : { backgroundColor: 'var(--surface-card)', borderColor: 'var(--ink-200)' }}
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
          {type === 'against' && chipsError && <ErrorText message="사유 칩을 불러오지 못했어요. 이유를 직접 적어 주세요" error={chipsError} />}
          <TextField
            value={text}
            onChange={setText}
            maxLength={TEXT_MAX}
            placeholder={inputExample(pin.category, type)}
            label={PROMPT[type].title}
            clearLabel="사유 지우기"
            inputRef={reasonRef}
            describedBy={showMissing ? reasonErrorId : undefined}
          />
          {showMissing && (
            <FieldError id={reasonErrorId}>
              {MISSING_REASON}
            </FieldError>
          )}
          {type === 'against' && <p className="text-label text-ink-500">자세히 적을수록 추천이 정확해져요</p>}
        </div>
      )}

      <button
        aria-busy={react.isPending}
        type="button"
        onClick={submit}
        disabled={!type || react.isPending}
        className="btn-primary btn-md w-full"
      >
        <BusyLabel busy={react.isPending} busyText="등록하는 중…">의견 등록</BusyLabel>
      </button>
    </section>
  )
}

/**
 * 이 핀에 의견을 남긴 사람 — 누가 남겼는지 얼굴로(#1547, 사회적 증거). 의견 목록을 받기 전에는 막대로 비율만 보인다.
 * 색만으로는 1/4와 2/4가 잘 안 갈려서 숫자는 글로 꼭 적는다(colors.md 3절 한계).
 */
function PinParticipants({ pin, memberCount, names }: { pin: Pin; memberCount: number; names?: string[] }) {
  if (names) return <PeopleProof names={names} total={memberCount} verb="이 의견을 남겼어요" />
  return <ProgressBar label={`${participants(pin)}/${memberCount}명이 의견을 남겼어요`} value={participants(pin)} max={memberCount} className="pb-1" />
}
