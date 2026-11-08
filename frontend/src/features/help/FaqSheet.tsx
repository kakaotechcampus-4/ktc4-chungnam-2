import ModalSheet from '@/features/shell/ModalSheet'
import Accordion from '@/ui/Accordion'
import SheetTitle from '@/ui/SheetTitle'

import { FAQ } from './faq'

/** 자주 묻는 질문(#1538). 질문을 누르면 답이 아래로 펼쳐진다. 여기서 풀리지 않으면 아래 버튼으로 버그를 알린다. */
export default function FaqSheet({ onClose, onReport }: { onClose: () => void; onReport?: () => void }) {
  return (
    <ModalSheet label="자주 묻는 질문" onClose={onClose}>
      <SheetTitle>자주 묻는 질문</SheetTitle>
      <p className="mt-1 text-sm text-ink-500">궁금한 내용을 눌러 확인해 보세요</p>
      <div className="mt-3">
        <Accordion items={FAQ.map((f) => ({ id: f.id, title: f.q, body: f.a }))} />
      </div>
      {onReport && (
        <button type="button" onClick={onReport} className="btn-neutral btn-lg mt-5 w-full">
          버그 신고하기
        </button>
      )}
    </ModalSheet>
  )
}
