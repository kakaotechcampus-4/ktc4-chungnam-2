import { PingoMark } from './Pingo'

/**
 * 대표 사진 오른쪽 아래의 핑고 얼굴(#1625, 초대 화면). 사진 위라 흰 원에 얹는다. 장식이라 숨긴다.
 * 부모가 `relative`여야 한다. 링크 미리보기 그림의 워드마크(backend `maps/preview.py`)와 같은 자리다.
 */
export default function CoverPingo() {
  return (
    <span aria-hidden="true" className="keep-light absolute bottom-2 right-2 flex size-8 items-center justify-center rounded-full bg-white/90 shadow-float">
      <PingoMark size={22} />
    </span>
  )
}
