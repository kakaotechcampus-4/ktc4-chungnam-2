# frontend

pin-go-pin-go 웹 클라이언트.
컨벤션·화면 구조는 `CLAUDE.md`, 계약은 루트 `docs/api-spec.yaml`이 정본.

## 실행

```bash
npm install
npm run dev     # http://localhost:5173
```

`npm run dev`는 DEV에서 `contracts/`의 msw 목 서버를 자동으로 띄운다.
백엔드 없이 전 화면 개발 가능 — 시나리오 전환은 `contracts/README.md` 참고.

## 스크립트

| 명령 | 용도 |
|---|---|
| `npm run dev` | 개발 서버 (목 서버 포함) |
| `npm run build` | `tsc -b` + 프로덕션 빌드 |
| `npm run lint` | oxlint |
| `npm run preview` | 빌드 산출물 미리보기 |

## contracts 배선

`contracts/`는 빌드 산출물 없는 **소스 전용** 패키지다.
`file:` 의존성으로 붙이면 Vite가 `node_modules` 안의 `.ts`를 변환하지 않아 깨진다.
그래서 `node_modules` 밖 절대경로 alias로 소스를 직접 가리킨다.

- 런타임 해석 — `vite.config.ts`의 `resolve.alias`
- 타입 해석 — `tsconfig.app.json`의 `paths`
- 둘 중 하나만 있으면 한쪽만 깨진다

루트 `tsconfig.json`에도 같은 `paths`가 있는데 컴파일에는 쓰이지 않는다.
shadcn CLI가 루트 tsconfig에서 alias를 찾기 때문.

## 스택

Vite · React 19 · TypeScript · TanStack Query(서버 상태) · Zustand(UI 상태) ·
Tailwind CSS v4 + shadcn/ui · 카카오맵 JS SDK
