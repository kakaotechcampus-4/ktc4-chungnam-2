import WelcomeScene from '@/features/onboarding/WelcomeScene'
import ModalSheet from '@/features/shell/ModalSheet'
import Accordion from '@/ui/Accordion'
import SheetTitle from '@/ui/SheetTitle'

import { FAQ } from './faq'

/** 자주 묻는 질문(#1538). 질문을 누르면 답이 아래로 펼쳐지고, 답 위에 그 기능을 쓰는 짧은 그림이 돈다. 여기서 풀리지 않으면 아래 버튼으로 버그를 알린다. */
export default function FaqSheet({ onClose, onReport }: { onClose: () => void; onReport?: () => void }) {
  return (
    <ModalSheet label="자주 묻는 질문" onClose={onClose}>
      <SheetTitle>자주 묻는 질문</SheetTitle>
      <p className="mt-1 text-sm text-ink-500">궁금한 내용을 눌러 확인해 보세요</p>
      <div className="mt-3">
        {/* 답을 펼치면 그 기능을 쓰는 짧은 그림이 위에 돈다(온보딩 장면과 같은 모음). 그림은 꾸밈이라 화면 읽기에서 숨는다. */}
        <Accordion
          items={FAQ.map((f) => ({
            id: f.id,
            title: f.q,
            body: (
              <>
                <WelcomeScene kind={f.scene} className="mx-auto mb-3 w-full max-w-[280px]" />
                {f.a}
              </>
            ),
          }))}
        />
      </div>
      {onReport && (
        <button type="button" onClick={onReport} className="btn-neutral btn-lg mt-5 w-full">
          버그 신고하기
        </button>
      )}
    </ModalSheet>
  )
}
