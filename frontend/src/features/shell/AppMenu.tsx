import { useState, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router'
import { Dialog } from 'radix-ui'
import { Bug, CircleHelp, Map as MapIcon, Menu, MessageSquare, X } from 'lucide-react'

import LogoutConfirm from '@/features/auth/LogoutConfirm'
import { TERMS } from '@/features/auth/terms'
import WithdrawConfirm from '@/features/auth/WithdrawConfirm'
import FeedbackSheet from '@/features/feedback/FeedbackSheet'
import FaqSheet from '@/features/help/FaqSheet'
import Accordion from '@/ui/Accordion'
import Wordmark from '@/ui/Wordmark'

type Sheet = 'faq' | 'bug' | 'other' | 'withdraw' | 'logout' | null

/**
 * PC 지도 패널 머리의 ☰와 왼쪽에서 나오는 메뉴(#1538, 카카오맵 왼쪽 메뉴 모양).
 * 위에서부터 워드마크 + ✕ → 아이콘 줄(내 지도로 돌아가기) → 글자 줄(자주 묻는 질문 · 버그 신고하기 · 의견 보내기 · 설정 ⌄) → 선 → 작은 글자(로그아웃).
 * 줄을 누르면 메뉴를 닫고 그 창을 연다. 바깥이나 Esc로 닫고, 닫으면 ☰로 초점이 돌아온다(Radix Dialog).
 */
export default function AppMenu({ mapId }: { mapId: string }) {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [sheet, setSheet] = useState<Sheet>(null)
  const show = (next: Sheet) => {
    setOpen(false)
    setSheet(next)
  }
  const close = () => setSheet(null)

  return (
    <>
      <Dialog.Root open={open} onOpenChange={setOpen}>
        <Dialog.Trigger
          aria-label="메뉴"
          className="hit-44 flex size-8 shrink-0 items-center justify-center rounded-lg text-white transition-colors hover:bg-white/15 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
        >
          <Menu size={24} aria-hidden="true" />
        </Dialog.Trigger>
        <Dialog.Portal>
          <Dialog.Overlay className="enter-fade fixed inset-0 z-50 bg-scrim" />
          <Dialog.Content
            aria-describedby={undefined}
            className="fixed inset-y-3 left-3 z-50 flex w-[22rem] flex-col overflow-y-auto rounded-2xl bg-white shadow-float outline-none data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:slide-in-from-left-4 motion-reduce:animate-none"
          >
            <Dialog.Title className="sr-only">메뉴</Dialog.Title>
            <div className="flex items-center justify-between px-6 pb-4 pt-6">
              <Wordmark className="h-6 w-auto" />
              <Dialog.Close aria-label="메뉴 닫기" className="hit-44 flex size-8 items-center justify-center rounded-lg text-ink-900 press">
                <X size={24} aria-hidden="true" />
              </Dialog.Close>
            </div>

            <nav aria-label="메뉴" className="flex flex-1 flex-col px-6">
              <ul>
                <li>
                  <MenuRow icon={<MapIcon size={20} aria-hidden="true" />} onClick={() => navigate('/')}>
                    내 지도로 돌아가기
                  </MenuRow>
                </li>
              </ul>

              <ul className="mt-5">
                <li>
                  <MenuRow icon={<CircleHelp size={20} aria-hidden="true" />} onClick={() => show('faq')}>
                    자주 묻는 질문
                  </MenuRow>
                </li>
                <li>
                  <MenuRow icon={<Bug size={20} aria-hidden="true" />} onClick={() => show('bug')}>
                    버그 신고하기
                  </MenuRow>
                </li>
                <li>
                  <MenuRow icon={<MessageSquare size={20} aria-hidden="true" />} onClick={() => show('other')}>
                    의견 보내기
                  </MenuRow>
                </li>
                <li className="pl-8">
                  <Accordion
                    variant="menu"
                    items={[
                      {
                        id: 'settings',
                        title: '설정',
                        body: (
                          <ul className="space-y-0.5">
                            {TERMS.map((t) => (
                              <li key={t.to}>
                                <Link to={t.to} className="flex min-h-9 items-center text-sm text-ink-500 hover:text-ink-900 hover:underline">
                                  {t.title}
                                </Link>
                              </li>
                            ))}
                            <li>
                              <button type="button" onClick={() => show('withdraw')} className="flex min-h-9 items-center text-sm text-ink-500 hover:text-ink-900 hover:underline">
                                회원 탈퇴
                              </button>
                            </li>
                          </ul>
                        ),
                      },
                    ]}
                  />
                </li>
              </ul>

              <div className="mt-auto border-t border-ink-200 py-4">
                <button type="button" onClick={() => show('logout')} className="btn-text text-sm">
                  로그아웃
                </button>
              </div>
            </nav>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>

      {sheet === 'faq' && <FaqSheet onClose={close} onReport={() => setSheet('bug')} />}
      {(sheet === 'bug' || sheet === 'other') && <FeedbackSheet key={sheet} mapId={mapId} initialCategory={sheet} onClose={close} />}
      {sheet === 'withdraw' && <WithdrawConfirm onCancel={close} />}
      {sheet === 'logout' && <LogoutConfirm onCancel={close} />}
    </>
  )
}

/** 메뉴 글자 줄 — 20 선 아이콘 + 16/500 글자, 높이 44. */
function MenuRow({ icon, onClick, children }: { icon: ReactNode; onClick: () => void; children: ReactNode }) {
  return (
    <button type="button" onClick={onClick} className="flex min-h-11 w-full items-center gap-3 text-left text-base font-medium text-ink-900 hover:text-brand-600">
      <span className="text-ink-600">{icon}</span>
      {children}
    </button>
  )
}
