import CourseBody from '@/features/course/CourseBody'
import CourseMapLegend from '@/features/course/CourseMapLegend'
import { PinDetailBody, PinDetailHeader } from '@/features/map/PinDetail'
import { usePinsQuery } from '@/features/map/queries'
import { usePinSelection } from '@/features/map/usePinSelection'
import { useMembersQuery } from '@/features/maps/queries'
import { useShell } from '@/features/shell/shellContext'
import TabSheet from '@/features/shell/TabSheet'
import SheetTitle from '@/ui/SheetTitle'
import Sentences from '@/ui/Sentences'

/**
 * 「AI 코스」 탭(#683, #1130) — 확정 리스트의 장소를 날짜별로 나눠 순서를 짠다. 예전에는 확정 탭의 칩이 여는 시트였다.
 * 결과는 요청한 사람에게만 보이고 지도·확정 리스트를 바꾸지 않는다. 지도에는 확정된 핀과 코스 선(「지도에서 보기」)이 뜬다.
 * 지도에서 핀을 누르면 이 탭 안에서 상세가 열린다 — 확정 탭으로 넘어가면 코스 선이 사라져서다(#1127 리뷰). 보던 코스는 그대로 남는다.
 */
export default function CourseTab() {
  const { mapId } = useShell()
  const { selectedPinId, selectPin } = usePinSelection()
  const pins = usePinsQuery(mapId).data ?? []
  const members = useMembersQuery(mapId).data ?? []
  const openPin = selectedPinId ? pins.find((p) => p.id === selectedPinId) : undefined

  if (openPin) {
    return (
      <TabSheet
        tab="course"
        expandOnScroll
        header={<PinDetailHeader pin={openPin} mapId={mapId} backLabel="AI 코스" onBack={() => selectPin(null)} />}
      >
        <PinDetailBody pin={openPin} mapId={mapId} members={members} onDone={() => selectPin(null)} />
      </TabSheet>
    )
  }

  return (
    <TabSheet
      tab="course"
      header={
        <>
          <SheetTitle>AI 코스 짜기</SheetTitle>
          <p className="mt-1 break-keep text-xs text-ink-500">
            <Sentences text="확정된 장소를 날짜별로 나눠 순서를 짜 줘요. 결과는 나에게만 보여요" />
          </p>
          <CourseMapLegend mapId={mapId} />
        </>
      }
    >
      <CourseBody mapId={mapId} />
    </TabSheet>
  )
}
