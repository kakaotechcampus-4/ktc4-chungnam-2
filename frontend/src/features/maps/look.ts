/**
 * 지도 대표 이미지와 색(#1445). 둘 다 지도 단위이고 방장만 바꾼다(api-spec PATCH /maps/{mapId}, PUT /maps/{mapId}/cover).
 * 색은 카드 바탕과 기본 그림의 하늘이라 글자가 잘 읽히는 밝은 파스텔만 견본으로 둔다. 직접 고른 색은 그대로 쓴다.
 */
export const MAP_COLORS = [
  { value: '#FDE2E4', name: '벚꽃' },
  { value: '#FCE5D4', name: '살구' },
  { value: '#FFF1C9', name: '버터' },
  { value: '#E2ECE9', name: '세이지' },
  { value: '#DCEFE3', name: '민트' },
  { value: '#DDE7FB', name: '하늘' },
  { value: '#EADCF8', name: '라벤더' },
  { value: '#EFE7DD', name: '모래' },
] as const

/** 올리기 전에 긴 변을 이만큼으로 줄인다. 크기 상한은 서버가 COVER_INVALID 의 detail.limit_bytes 로 알려 준다. */
const MAX_SIDE = 1200

/**
 * 고른 사진을 긴 변 1200px WebP 로 줄인다. 상한을 넘으면 화질을 낮춰 다시 굽는다(0.85 → 0.55).
 * 상한(limitBytes)을 모르면 첫 결과를 그대로 보내고, 넘으면 서버가 COVER_INVALID 로 막는다.
 */
export async function shrinkImage(file: Blob, limitBytes?: number): Promise<Blob> {
  const bitmap = await createImageBitmap(file)
  const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height))
  const canvas = document.createElement('canvas')
  canvas.width = Math.round(bitmap.width * scale)
  canvas.height = Math.round(bitmap.height * scale)
  canvas.getContext('2d')!.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
  bitmap.close()
  let blob: Blob | null = null
  for (const quality of [0.85, 0.7, 0.55]) {
    blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/webp', quality))
    if (!blob || !limitBytes || blob.size <= limitBytes) break
  }
  if (!blob) throw new Error('사진을 줄이지 못했어요')
  return blob
}
