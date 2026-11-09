"""
초대 링크 미리보기(#1625) — 카톡 같은 메신저가 링크를 붙일 때 읽어 가는 HTML과 그림. 순수 함수만 둔다.

메신저는 스크립트를 실행하지 않고 화면(frontend/index.html)의 고정 og 태그만 본다. 그래서 미리보기 봇이
`/invites/{token}`을 열 때만 앞단 Caddy가 이 API로 보낸다(deploy/Caddyfile). 사람이 여는 요청은 그대로 화면이다.
"""

from datetime import date
from html import escape
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps

from maps.schemas import InviteSummary

# 메신저 미리보기 권장 크기(1.91:1).
PREVIEW_SIZE = (1200, 630)
# 오른쪽 아래 흰 알약 안 워드마크. 1200×630에 맞춰 그린 그림이라 늘이거나 줄이지 않는다.
# 그림 둘레에 그림자 자리 8px이 있어 보이는 여백은 이 값 + 8이다.
_BADGE_PATH = Path(__file__).parent / "assets" / "preview-badge.png"
_BADGE_MARGIN = 24
# 화면이 API를 부르는 앞자리. deploy/Caddyfile의 handle_path /api/*, frontend/Dockerfile의 VITE_API_BASE_URL과 같다.
API_PREFIX = "/api"
# 사진이 없거나 링크를 더 쓸 수 없을 때 — frontend/index.html의 기본 미리보기와 같은 그림과 글이다.
DEFAULT_IMAGE_PATH = "/og-image.png"
DEFAULT_TITLE = "핑고핑고 — 같이 갈 곳을 한 지도에 모아요"
DEFAULT_DESCRIPTION = "친구들과 한 지도에 가고 싶은 곳을 찍고, 의견을 모아 여행 장소를 정해요"


def _day(d: date) -> str:
    """화면의 날짜 표기(11.2 (월))와 같다."""
    return f"{d.month}.{d.day} ({'월화수목금토일'[d.weekday()]})"


def invite_preview_text(summary: InviteSummary) -> tuple[str, str]:
    """(제목, 설명). 메타 태그에는 조각을 나눠 줄 자리가 없어 사용자 글(이름, 지도 제목)을 문장에 넣는다 —
    화면 응답의 조각 규칙(#717)은 우리 화면이 그릴 때의 규칙이다. 넣을 때 escape는 preview_html이 한다."""
    title = f"{summary.inviter_display_name}님이 {summary.title} 지도에 초대했어요"
    parts = [f"{_day(summary.start_date)} ~ {_day(summary.end_date)}", f"구성원 {summary.member_count}명"]
    if summary.pin_count is not None:
        parts.append(f"핀 {summary.pin_count}개")
    return title, " · ".join(parts)


def preview_html(*, page_url: str, image_url: str, title: str, description: str, image_size: tuple[int, int] | None) -> str:
    """og 태그만 담은 작은 문서. 봇이 아닌데 여기로 왔으면 본문 링크로 화면에 간다."""
    e = {k: escape(v, quote=True) for k, v in
         {"url": page_url, "image": image_url, "title": title, "description": description}.items()}
    size = (
        f'<meta property="og:image:width" content="{image_size[0]}" />\n'
        f'<meta property="og:image:height" content="{image_size[1]}" />\n'
        if image_size else ""
    )
    return (
        '<!doctype html>\n<html lang="ko">\n<head>\n<meta charset="utf-8" />\n'
        f"<title>{e['title']}</title>\n"
        '<meta name="robots" content="noindex" />\n'
        '<meta property="og:type" content="website" />\n'
        '<meta property="og:site_name" content="핑고핑고" />\n'
        '<meta property="og:locale" content="ko_KR" />\n'
        f'<meta property="og:url" content="{e["url"]}" />\n'
        f'<meta property="og:title" content="{e["title"]}" />\n'
        f'<meta property="og:description" content="{e["description"]}" />\n'
        f'<meta name="description" content="{e["description"]}" />\n'
        f'<meta property="og:image" content="{e["image"]}" />\n'
        f"{size}"
        '<meta name="twitter:card" content="summary_large_image" />\n'
        f'</head>\n<body><a href="{e["url"]}">{e["title"]}</a></body>\n</html>\n'
    )


_badge: Image.Image | None = None


def _load_badge() -> Image.Image:
    global _badge
    if _badge is None:
        with Image.open(_BADGE_PATH) as img:
            _badge = img.convert("RGBA")
    return _badge


def compose_preview_image(cover: bytes) -> bytes:
    """대표 사진을 1200×630으로 가운데 맞춰 자르고 오른쪽 아래에 워드마크를 얹은 JPEG.
    사진은 올릴 때 형식과 크기(COVER_MAX_BYTES)를 검사했다. 그래도 열지 못하면 Pillow 예외가 그대로 올라간다."""
    with Image.open(BytesIO(cover)) as img:
        # 휴대폰 사진은 회전을 EXIF로만 적어 두는 일이 있다 — 돌려 놓지 않으면 옆으로 누운 미리보기가 된다.
        photo = ImageOps.fit(ImageOps.exif_transpose(img).convert("RGB"), PREVIEW_SIZE, Image.Resampling.LANCZOS)
    badge = _load_badge()
    width, height = PREVIEW_SIZE
    photo.paste(badge, (width - badge.width - _BADGE_MARGIN, height - badge.height - _BADGE_MARGIN), badge)
    out = BytesIO()
    photo.save(out, "JPEG", quality=85, optimize=True)
    return out.getvalue()
