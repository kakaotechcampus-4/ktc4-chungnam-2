# frontend

pin-go-pin-go 웹 클라이언트입니다.
컨벤션과 화면 구조는 `CLAUDE.md`에, 계약은 루트 `docs/api-spec.yaml`에 있습니다(정본).

## 실행

```bash
npm install
npm run dev     # http://localhost:5173
```

`npm run dev`는 DEV에서 `contracts/`의 msw 목 서버를 자동으로 띄웁니다.
그래서 백엔드 없이도 전 화면을 개발할 수 있습니다. 시나리오 전환은 `contracts/README.md`를 보세요.

## 스크립트

| 명령 | 용도 |
|---|---|
| `npm run dev` | 개발 서버 (목 서버 포함) |
| `npm run build` | `tsc -b` + 프로덕션 빌드 |
| `npm run lint` | oxlint |
| `npm run preview` | 빌드 산출물 미리보기 |

## contracts 연결 방식

`contracts/`는 빌드 산출물 없이 소스만 있는 패키지입니다.
`file:` 의존성으로 붙이면 Vite가 `node_modules` 안의 `.ts`를 변환하지 않아서 깨집니다.
그래서 `node_modules` 밖 절대경로 alias로 소스를 직접 가리킵니다.

- 런타임 해석은 `vite.config.ts`의 `resolve.alias`가 `@pingo/contracts/*` 전체를 맡습니다.
- 타입 해석은 `tsconfig.app.json`의 `paths`가 맡는데, 생성된 `.d.ts`만 매핑합니다.

`paths`를 `@pingo/contracts/*`로 넓히면 안 됩니다.
tsc가 import를 따라가 `contracts/mocks/*.ts`까지 이쪽 strict 설정으로 검사해서, 남의 패키지 소스 때문에 이 빌드가 깨집니다. contracts 수정은 루트 소관이라 우리가 고칠 수도 없습니다.
목 서버 쪽 타입은 `src/contracts-mocks.d.ts`의 앰비언트 선언이 받습니다.

루트 `tsconfig.json`에도 같은 `paths`가 있지만 컴파일에는 쓰이지 않습니다.
shadcn CLI가 루트 tsconfig에서 alias를 찾기 때문에 둔 것입니다.

## 스택

Vite, React 19, TypeScript, TanStack Query(서버 상태), Zustand(UI 상태),
Tailwind CSS v4 + shadcn/ui, 카카오맵 JS SDK
