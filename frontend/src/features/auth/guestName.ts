/**
 * 게스트 이름 칸에 미리 넣어 두는 아무 이름(「신나는 수달」). 버튼만 눌러도 들어갈 수 있고, 지우고 자기 이름을 적어도 된다.
 * 다른 서비스의 캐릭터 이름은 쓰지 않는다. 형용사 12 × 동물 12 = 144가지라 한 지도의 게스트(최대 10명)끼리 겹칠 수 있다 —
 * 서버에 이름 겹침 검사가 없어 겹쳐도 들어가진다. 겹치면 본인이 바꾼다.
 */
const ADJECTIVES = ['신나는', '느긋한', '배고픈', '설레는', '용감한', '졸린', '꼼꼼한', '씩씩한', '수줍은', '궁금한', '부지런한', '상냥한']
const ANIMALS = ['수달', '펭귄', '다람쥐', '고래', '너구리', '판다', '부엉이', '해달', '알파카', '고슴도치', '미어캣', '거북이']

const pick = (list: string[], r: number) => list[Math.floor(r * list.length) % list.length]

export function randomGuestName(random: () => number = Math.random): string {
  return `${pick(ADJECTIVES, random())} ${pick(ANIMALS, random())}`
}
