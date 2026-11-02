import CourseBody from '@/features/course/CourseBody'
import CourseMapLegend from '@/features/course/CourseMapLegend'
import { useShell } from '@/features/shell/shellContext'
import TabSheet from '@/features/shell/TabSheet'
import SheetTitle from '@/ui/SheetTitle'

/**
 * 「AI 코스」 탭(#683) — 확정 리스트의 장소를 날짜별로 나눠 순서를 짠다. 예전에는 확정 탭의 칩이 여는 시트였다.
 * 결과는 요청한 사람에게만 보이고 지도·확정 리스트를 바꾸지 않는다. 지도에는 확정된 핀과 코스 선(「지도에서 보기」)이 뜬다.
 */
export default function CourseTab() {
  const { mapId } = useShell()
  return (
    <TabSheet
      tab="course"
      header={
        <>
          <SheetTitle>AI 코스 짜기</SheetTitle>
          <p className="mt-1 break-keep text-xs text-ink-500">확정된 장소를 날짜별로 나눠 순서를 짜 줘요. 지도와 확정 리스트는 바뀌지 않고, 결과는 나한테만 보여요</p>
          <CourseMapLegend mapId={mapId} />
        </>
      }
    >
      <CourseBody mapId={mapId} />
    </TabSheet>
  )
}
