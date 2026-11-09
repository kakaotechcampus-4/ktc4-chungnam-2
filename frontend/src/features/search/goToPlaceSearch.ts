/**
 * 「장소 검색하기」·「검색해서 직접 찍기」 버튼이 부르는 곳.
 * 검색창에 글자가 있으면 그 글자로 바로 찾고, 비어 있으면 검색창으로 커서를 옮긴다.
 * 커서만 옮기면 글자가 이미 있는 검색창은 달라지는 게 없어 버튼이 안 눌린 것처럼 보였다(PM 점검 #1554).
 */
export function goToPlaceSearch() {
  const input = document.getElementById('place-search')
  if (!(input instanceof HTMLInputElement)) return
  if (input.value.trim()) input.form?.requestSubmit()
  else input.focus()
}
