import pingo from './pingo.png'

/** 핑고 — AI 쪽 화자(docs/design/colors.md 4절 3층). 그림은 캐릭터 시안(PINGO.pdf) DEFAULT 자세다. */
export default function Pingo({ size = 40 }: { size?: number }) {
  return <img src={pingo} width={size} height={size} alt="" aria-hidden="true" draggable={false} />
}
