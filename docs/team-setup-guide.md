# 팀원용 설치·실행 설명서 — 내 컴퓨터에서 핀고 켜기

> 개발을 잘 몰라도 **위에서부터 복사해서 붙여 넣으면** 됩니다. 명령어는 모두 **Windows PowerShell** 기준입니다.
> 켠 뒤에 무엇을 눌러 보여 줄지는 `docs/demo-guide.md`(시연 대본)에 있습니다. 이 문서는 **"켜는 데까지"** 입니다.

**걸리는 시간**: 처음 한 번 약 40~60분(설치·데이터 넣기 포함). 그다음부터는 켜는 데 3분.
**꼭 알아 둘 것**: 서버와 데이터베이스는 **각자 내 컴퓨터 안에서만** 돌아갑니다. 다른 사람 컴퓨터와 연결되지 않으니, 같이 보려면 **한 컴퓨터에서** 브라우저 창을 나눠 쓰세요.

---

## 1. 준비물

### 1-1. 프로그램 4개를 설치하세요 (이미 있으면 건너뜁니다)

| 프로그램 | 받는 곳 | 확인하는 명령 (PowerShell) | 이렇게 나오면 OK |
|---|---|---|---|
| **Docker Desktop** | https://www.docker.com/products/docker-desktop | `docker --version` | `Docker version 2x...` |
| **Python 3.12** | https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe (3.12의 마지막 윈도 설치 파일) | `python --version` | `Python 3.12.10` |
| **Node.js 20 이상** | https://nodejs.org (LTS) | `node --version` | `v20` 이상 |
| **Git** | https://git-scm.com | `git --version` | `git version 2...` |

> ❗ **Python 3.13·3.14는 안 됩니다.** 서버 부품 두 개(`psycopg2-binary`, `pyproj`)가 3.12까지만 설치 파일이 있어서 5-1에서 설치가 실패합니다. 3.10·3.11은 됩니다.
> 💡 다른 버전이 이미 깔려 있으면 3.12를 하나 더 설치하고, 이 문서의 `python`을 전부 `py -3.12`로 바꿔 쓰세요(예: `py -3.12 -m pip install -r requirements.txt`).
> 💡 Python을 설치할 때 **"Add python.exe to PATH"** 체크박스를 꼭 켜세요. 안 켜면 `python` 명령이 안 먹습니다.
> 💡 설치한 뒤에는 **PowerShell 창을 새로 열어야** 명령이 인식됩니다.

### 1-2. 키 5개를 팀 리드에게 받으세요

서버가 카카오와 AI에 접속하려면 키가 필요합니다. **팀 리드(백엔드 리더)에게 개인 메시지로** 받으세요.

| 이름 | 무엇에 쓰나 | 어디에 넣나 |
|---|---|---|
| 카카오 **REST API 키** | 카카오 로그인 + 장소 검색 | 3절 `KAKAO_CLIENT_ID` |
| 카카오 **Client Secret** | 카카오 로그인 확인 | 3절 `KAKAO_CLIENT_SECRET` |
| 엘리스 **주소**(BASE URL) | AI 서버 주소 | 3절 `ELICE_ML_API_BASE_URL` |
| 엘리스 **키** | AI가 사람 말을 조건으로 정리 | 3절 `ELICE_ML_API_KEY` |
| 카카오 **JavaScript 키** | 지도 그리기 | 4절 `VITE_KAKAO_MAP_KEY` |

> 🔒 **이 키들은 절대 공개하지 마세요.** 깃허브·디스코드 공개 채널·스크린샷·이슈에 붙이면 안 됩니다. 아래 `.env` 파일은 깃이 자동으로 무시하니 거기에만 적으세요.

### 1-3. 가게 데이터 폴더를 받으세요

아래 폴더를 팀 리드(또는 데이터 담당)에게 받아 **저장소 밖**(예: `C:\Users\내이름\Downloads\`)에 두세요. 저장소는 공개라서 이 파일은 깃에 올리지 않습니다.

| 폴더 | 들어 있는 것 |
|---|---|
| `식당카페_라벨_2026-10-02` | 음식점·카페 목록과 라벨(10/2 납품) |
| `음식점_1013`, `카페_1013`, `관광지_1013` | 음식점·카페·관광지 목록과 라벨(10/13 납품) |

한쪽만 받았으면 받은 것만 넣으면 됩니다(5-4).

---

## 2. 코드 받기

```powershell
cd $HOME\Desktop
git clone https://github.com/kakaotechcampus-4/ktc4-chungnam-2.git pingo
cd pingo
git checkout develop
git pull
```

> ✅ `Already up to date.` 또는 받아 오는 글이 나오면 성공입니다. 이제 `pingo` 폴더 안에 `backend`, `frontend`, `docs` 폴더가 있습니다.
> ❓ 로그인 창이 뜨면 깃허브 계정으로 로그인하세요. 권한 오류가 나면 팀 리드에게 저장소 초대를 요청하세요.

---

## 3. 백엔드(서버) 설정 — `.env` 파일 만들기

```powershell
cd backend
Copy-Item env.demo.example .env
notepad .env
```

메모장에 파일이 열립니다. 아래 **4줄**의 `=` **바로 뒤에** 받은 값을 붙여 넣고 저장하세요. 나머지 줄은 그대로 둡니다.

```
KAKAO_CLIENT_ID=여기에_REST_API_키
KAKAO_CLIENT_SECRET=여기에_Client_Secret
ELICE_ML_API_BASE_URL=여기에_엘리스_주소
ELICE_ML_API_KEY=여기에_엘리스_키
```

(`.env`에서 채울 곳은 이 4줄뿐입니다. 지도 키는 4절 프론트에서 넣습니다.)

**이것만 지키세요**
- `=` 앞뒤에 **공백을 넣지 마세요.** (`KAKAO_CLIENT_ID= abc` ✗ → `KAKAO_CLIENT_ID=abc` ✓)
- 값에 **따옴표를 붙이지 마세요.**
- 값 뒤에 `# 설명` 같은 **주석을 붙이지 마세요.** 주석은 항상 별도의 줄에 쓰세요.
- 키를 **채팅창에 붙인 채로 복사**하면 앞뒤에 공백이 따라오기도 합니다. 붙여 넣은 뒤 `=` 바로 뒤에 글자가 붙어 있는지 눈으로 확인하세요.
- `.env`를 고치면 **서버를 껐다 다시 켜야** 적용됩니다.

---

## 4. 프론트(화면) 설정 — `.env.local` 파일 만들기

```powershell
cd ..\frontend
Copy-Item env.demo.example .env.local
notepad .env.local
```

`VITE_KAKAO_MAP_KEY=` 뒤에 받은 **카카오 JavaScript 키**를 붙여 넣고 저장하세요. `VITE_API_BASE_URL=http://localhost:8000` 줄은 그대로 둡니다.

> ⚠️ **백엔드 `.env`를 프론트에 복사하지 마세요.** 프론트가 읽는 값은 위 두 개뿐이고(`VITE_`로 시작), 백엔드 `.env`에는 데이터베이스 주소·시크릿 같은 비밀이 들어 있어서 복사하면 위험만 늘어납니다.

---

## 5. 처음 한 번만 하는 준비

### 5-1. 파이썬 부품 설치 (약 2~3분)

```powershell
cd ..\backend
python -m pip install -r requirements.txt
```

### 5-2. 데이터베이스 켜기

**먼저 Docker Desktop 프로그램을 실행해 두세요**(고래 아이콘이 초록색이 될 때까지). 그다음:

```powershell
docker compose up -d
```

> ✅ `Container backend-db-1 Started` 같은 줄이 나오면 성공입니다. 처음엔 이미지를 받느라 1~2분 걸립니다.

### 5-3. 표(테이블) 만들기

```powershell
python -m alembic upgrade head
```

> ✅ 빨간 `Error`나 `Traceback` 없이 끝나면 성공입니다. 마지막 `Running upgrade ...` 줄의 번호는 코드가 바뀔 때마다 늘어납니다.

### 5-4. 가게 데이터 넣기 (약 5분)

아래 `C:\경로` 부분을 **1-3에서 받은 폴더가 있는 실제 경로**로 바꾸세요(경로에 한글/공백이 있으면 따옴표로 감싼 그대로 두세요). **위에서부터 순서대로** 넣고, 받지 않은 폴더의 줄은 건너뜁니다. 파일이 다른 폴더에 들어 있으면 파일 이름으로 찾아 경로를 바꾸세요.

```powershell
$env:PYTHONUTF8=1
# 10/2 납품본
python -m places.load restaurants --file "C:\경로\식당카페_라벨_2026-10-02\restaurant_seoul_curated.csv" --labels "C:\경로\식당카페_라벨_2026-10-02\restaurant_seoul_curated_labels.json" --authoritative
python -m places.load cafes --file "C:\경로\식당카페_라벨_2026-10-02\cafe_seoul_curated.csv" --labels "C:\경로\식당카페_라벨_2026-10-02\cafe_seoul_curated_labels.csv" --authoritative
# 10/13 납품본 (음식점 → 카페 → 관광지 순서)
python -m places.load restaurants --file "C:\경로\음식점_1013\final_restaurant_places_hotspot.csv" --labels "C:\경로\음식점_1013\seoul_restaurant_labels_hotspot.json" --authoritative
python -m places.load cafes --file "C:\경로\카페_1013\cafe_seoul_curated.csv" --labels "C:\경로\카페_1013\cafe_seoul_curated_labels.json" --authoritative
python -m places.load tourapi --file "C:\경로\관광지_1013\tourist_seoul_places.json" --labels "C:\경로\관광지_1013\tourist_seoul_curated_labels.csv" --authoritative
```

> ✅ 명령마다 `DB: 신규 ...` 줄이 나오고, 끝에 `[curated] 분류별 정예 / 정예 아님` 표가 나오면 성공입니다. 좌표가 없는 가게는 자동으로 건너뛰니 파일 행 수보다 조금 적은 게 정상입니다.
> ❗ **`--authoritative`를 빼지 마세요.** 빼면 사람이 조사한 가게로 표시되지 않아서, 라벨이 적은 가게가 AI 추천 후보에서 빠집니다.
> ❗ 관광지 라벨은 `.json`이 아니라 **`.csv`** 파일을 넣습니다. json을 넣으면 라벨이 전부 건너뛰어집니다.
> 💡 먼저 연습해 보고 싶으면 명령 맨 끝에 `--dry-run`을 붙이세요. 실제로는 넣지 않고 결과만 보여 줍니다.
> 💡 다시 넣을 때는 **위 순서 전체를 처음부터** 하세요. 중복은 생기지 않지만, 한 줄만 다시 하면 나중 납품본의 값을 예전 값으로 덮어씁니다.
> 💡 인허가 데이터(서울 음식점·카페 약 10만 곳)는 선택입니다. 넣으면 검색 결과 중 핀으로 찍히는 가게가 늘지만 오래 걸리고 메모리를 많이 씁니다. 넣는 법은 `docs/openapi-workflow.md` 5-1에 있습니다.

### 5-5. 프론트 부품 설치 (약 1~2분)

```powershell
cd ..\frontend
npm install
```

---

## 6. 켜기 — 터미널 2개

시연할 때마다 이 두 개를 켭니다. **PowerShell 창을 2개** 여세요.

**터미널 ① 서버** (`backend` 폴더에서!)

```powershell
cd $HOME\Desktop\pingo\backend
docker compose up -d
python -m uvicorn main:asgi_app --port 8000
```

> ✅ `Application startup complete.`가 나오면 켜진 것입니다. **이 창은 닫지 마세요.**
> ❗ 폴더가 `pingo`가 아니라 **`pingo\backend`** 여야 합니다. 아니면 `Could not import module "main"` 오류가 납니다.

**터미널 ② 화면**

```powershell
cd $HOME\Desktop\pingo\frontend
npm run dev
```

> ✅ `Local: http://localhost:5173/`가 나오면 켜진 것입니다.

---

## 7. 잘 켜졌는지 확인

1. 브라우저에서 `http://localhost:8000/health` → `{"status":"ok"}`가 보이면 서버 OK.
2. 브라우저에서 **`http://localhost:5173`** (꼭 `localhost`로!) → **핑고핑고** 화면과 노란 **「카카오로 시작하기」** 버튼이 보이면 화면 OK.
3. 버튼을 눌러 **내 카카오 계정으로 로그인** → 동의 화면에서 **동의** → **내 지도** 목록이 나오면 전부 성공입니다. 🎉

> ⚠️ 주소를 `127.0.0.1`로 열면 로그인이 풀려 버립니다. 항상 **`localhost`**로 여세요.

이제 `docs/demo-guide.md`의 **장면 1~6**을 따라 시연해 보세요.

---

## 8. 막혔을 때

| 이런 일이 생겼다 | 왜 그럴까 | 이렇게 해 보세요 |
|---|---|---|
| `Could not import module "main"` | `backend` 폴더가 아닌 곳에서 서버를 켰다 | `cd backend`로 들어가서 다시 켠다 |
| `failed to connect to the docker API` | Docker Desktop이 꺼져 있다 | Docker Desktop을 실행하고 초록색이 될 때까지 기다린 뒤 다시 |
| 서버가 안 켜지고 `ConfigError` | `backend\.env`가 없거나 `PINGO_ENV=dev`가 없다 | 3절을 다시 한다(`.env`가 `backend` 폴더 안에 있어야 한다) |
| `relation "..." does not exist` | 표를 아직 안 만들었다 | `python -m alembic upgrade head` |
| 5-1에서 `pg_config executable not found`나 `proj executable not found` | Python이 3.13 이상이다 | 1-1대로 3.12를 깔고 `py -3.12 -m pip install -r requirements.txt` |
| `address already in use` | 8000(또는 5173) 포트를 다른 프로그램이 쓴다 | 이전에 켠 서버 창을 닫거나, `netstat -ano \| findstr :8000`으로 찾아 종료 |
| 로그인 버튼을 누르면 카카오 오류 `KOE010` | `KAKAO_CLIENT_SECRET`이 비었거나 틀렸다(앞뒤 공백 포함) | `.env`의 시크릿을 다시 확인하고 서버를 껐다 켠다 |
| 카카오 오류 `KOE101`·`KOE004` | `KAKAO_CLIENT_ID`가 틀렸거나 앱의 카카오 로그인이 꺼져 있다 | 키를 다시 확인하고, 계속되면 팀 리드에게 알린다 |
| 로그인 후 「로그인하지 못했어요」 | 위 카카오 오류 중 하나이거나 내 계정 문제 | 서버 창의 `kakao login failed: reason=...` 한 줄을 팀 리드에게 보여 준다 |
| 지도가 회색이거나 「지도를 불러오지 못했어요」 | 지도 키가 없다 | `frontend\.env.local`의 `VITE_KAKAO_MAP_KEY`를 확인하고 **`npm run dev`를 껐다 켠다** |
| 장소 검색이 「쓸 수 없어요」 | `KAKAO_CLIENT_ID`가 비었거나 틀렸다 | `.env`를 확인하고 서버를 껐다 켠다 |
| 추천이 실패하거나 AI가 안 읽는다 | 엘리스 키가 틀렸거나 만료됐다(서버 창에 `401`) | 팀 리드에게 새 키를 받는다 |
| 핀이 안 찍히고 「아직 지원하지 않는 장소예요」 | 우리 데이터에 없는 가게다 | 정상입니다. `docs/demo-guide.md` 장면 3의 가게를 **이름 그대로** 검색한다 |
| 아무것도 없는데 `.env` 수정이 안 먹는다 | 서버가 옛 설정으로 돌고 있다 | 서버 창에서 `Ctrl + C`로 끄고 다시 켠다 |

---

## 9. 코드를 새로 받을 때 (업데이트)

팀이 코드를 고치면 시연 전에 한 번씩 받아 오세요.

```powershell
cd $HOME\Desktop\pingo
git checkout develop
git pull
cd frontend
npm install
cd ..\backend
python -m pip install -r requirements.txt
python -m alembic upgrade head
```

그다음 6절처럼 서버와 화면을 껐다 다시 켜면 됩니다.

---

## 10. 끝낼 때 / 지켜야 할 것

- 터미널 ①, ②에서 `Ctrl + C`로 서버와 화면을 끕니다.
- 데이터베이스를 끄려면 `backend` 폴더에서 `docker compose stop`(데이터는 남습니다).
- ⚠️ **`docker compose down -v`는 쓰지 마세요.** 데이터가 전부 지워져서 5-4를 다시 해야 합니다.
- **`.env`와 `.env.local`은 절대 깃에 올리지 마세요.** 올리기 전에 `git status`를 눌러서 이 두 파일이 목록에 **없는지** 확인하세요(깃이 무시하도록 설정돼 있어 정상이면 안 보입니다).
- 키가 새어 나갔다고 의심되면 바로 팀 리드에게 알려서 키를 새로 발급받으세요.
