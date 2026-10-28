# 화면 이미지(#168). 빌드 맥락은 저장소 루트다(frontend가 ../contracts의 타입을 경로로 불러온다):
#   docker build -f frontend/Dockerfile --build-arg VITE_KAKAO_MAP_KEY=... -t pingo-web .
# API는 같은 주소의 /api 아래에 있다(앞단 Caddy가 나눠 보낸다) — 그래서 VITE_API_BASE_URL은 /api로 고정이다.
FROM node:22-alpine AS build
WORKDIR /src

COPY contracts/package.json contracts/package-lock.json contracts/
RUN cd contracts && npm ci
COPY frontend/package.json frontend/package-lock.json frontend/
RUN cd frontend && npm ci

COPY contracts contracts
COPY frontend frontend

# 카카오 지도 JS 키는 브라우저에 그대로 나가는 값이다(카카오 콘솔에서 사이트 도메인으로 제한한다). 비밀값이 아니다.
ARG VITE_KAKAO_MAP_KEY
ENV VITE_API_BASE_URL=/api \
    VITE_KAKAO_MAP_KEY=${VITE_KAKAO_MAP_KEY}
RUN cd frontend && npm run build

FROM caddy:2.8-alpine
COPY frontend/deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /src/frontend/dist /srv
