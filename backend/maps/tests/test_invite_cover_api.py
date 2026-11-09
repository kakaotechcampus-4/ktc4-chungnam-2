"""
초대 화면 대표 이미지와 링크 미리보기(#1625) 통합 테스트(conftest.py 참고 — 실제 PostgreSQL 필요).
GET /invites/{token}의 region·cover_url, GET /invites/{token}/cover·preview·preview-image.
"""

from io import BytesIO

from PIL import Image

from common.settings import settings
from maps import preview
from maps.tests.test_delete_leave_api import _auth
from maps.tests.test_map_cover_api import WEBP, _put

BUSAN = {"label": "부산", "lat": 35.1796, "lng": 129.0756}


def _photo(size=(800, 1000), color=(30, 120, 200)) -> bytes:
    out = BytesIO()
    Image.new("RGB", size, color).save(out, "JPEG")
    return out.getvalue()


def _map_and_token(app_client, *, title="부산 여행", region=BUSAN):
    body = {"title": title, "start_date": "2026-11-02", "end_date": "2026-11-12"}
    if region:
        body["region"] = region
    map_id = app_client.post("/maps", json=body, cookies=_auth("user_1")).json()["id"]
    token = app_client.post(f"/maps/{map_id}/invite", cookies=_auth("user_1")).json()["token"]
    return map_id, token


def test_summary_has_region_and_no_cover_until_uploaded(app_client):
    map_id, token = _map_and_token(app_client)
    summary = app_client.get(f"/invites/{token}").json()
    assert summary["region"] == BUSAN
    assert "cover_url" not in summary
    assert app_client.get(f"/invites/{token}/cover").status_code == 404

    assert _put(app_client, map_id, WEBP).status_code == 200
    url = app_client.get(f"/invites/{token}").json()["cover_url"]
    # 지도 응답과 같은 v — 사진을 바꾸면 두 주소가 함께 바뀐다
    map_v = app_client.get(f"/maps/{map_id}", cookies=_auth("user_1")).json()["cover_url"].split("?v=")[1]
    assert url == f"/invites/{token}/cover?v={map_v}"


def test_invite_cover_opens_without_login_while_link_lives(app_client):
    map_id, token = _map_and_token(app_client)
    _put(app_client, map_id, WEBP)
    got = app_client.get(f"/invites/{token}/cover")   # 쿠키 없음
    assert got.status_code == 200
    assert got.content == WEBP
    assert got.headers["content-type"] == "image/webp"
    assert got.headers["x-content-type-options"] == "nosniff"

    assert app_client.delete(f"/invites/{token}", cookies=_auth("user_1")).status_code == 204
    gone = app_client.get(f"/invites/{token}/cover")
    assert gone.status_code == 410
    assert gone.json()["code"] == "INVITE_REVOKED"
    assert app_client.get("/invites/nope/cover").status_code == 404


def test_preview_html_uses_photo_and_escapes_user_text(app_client):
    map_id, token = _map_and_token(app_client, title='<b>"부산"</b> & 바다')
    _put(app_client, map_id, _photo(), "image/jpeg")
    resp = app_client.get(f"/invites/{token}/preview")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    html = resp.text
    base = settings.frontend_base_url
    v = app_client.get(f"/invites/{token}").json()["cover_url"].split("?")[1]
    assert f'<meta property="og:image" content="{base}/api/invites/{token}/preview-image?{v}" />' in html
    assert f'<meta property="og:url" content="{base}/invites/{token}" />' in html
    assert '<meta property="og:image:width" content="1200" />' in html
    assert "&lt;b&gt;&quot;부산&quot;&lt;/b&gt; &amp; 바다 지도에 초대했어요" in html
    assert "<b>" not in html
    assert "11.2 (월) ~ 11.12 (목) · 구성원 1명 · 핀 0개" in html


def test_preview_without_photo_or_with_dead_link_is_default(app_client):
    _map_id, token = _map_and_token(app_client, region=None)
    html = app_client.get(f"/invites/{token}/preview").text
    assert f'content="{settings.frontend_base_url}/og-image.png"' in html
    assert "부산 여행 지도에 초대했어요" in html            # 사진이 없어도 글은 그 지도 것
    assert "og:image:width" not in html

    dead = app_client.get("/invites/nope/preview")
    assert dead.status_code == 200                          # 봇에게 오류 화면을 보이지 않는다
    assert preview.DEFAULT_TITLE in dead.text


def test_preview_image_is_cropped_jpeg_with_badge(app_client):
    map_id, token = _map_and_token(app_client)
    _put(app_client, map_id, _photo(), "image/jpeg")
    resp = app_client.get(f"/invites/{token}/preview-image")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    img = Image.open(BytesIO(resp.content))
    assert img.size == preview.PREVIEW_SIZE
    # 오른쪽 아래 흰 알약의 왼쪽 안쪽 여백(글자가 없는 곳)은 사진(파랑)보다 밝다
    width, height = preview.PREVIEW_SIZE
    badge_w, badge_h = Image.open(preview._BADGE_PATH).size
    left, top = width - badge_w - preview._BADGE_MARGIN, height - badge_h - preview._BADGE_MARGIN
    assert min(img.getpixel((left + 25, top + badge_h // 2))) > 220
    assert img.getpixel((40, 40))[2] > 150                 # 사진 자리는 그대로 파랑


def test_preview_image_404_when_no_photo_or_unreadable(app_client):
    map_id, token = _map_and_token(app_client)
    assert app_client.get(f"/invites/{token}/preview-image").status_code == 404
    _put(app_client, map_id, WEBP)                         # 앞 바이트만 WebP인 가짜 — Pillow가 못 연다
    assert app_client.get(f"/invites/{token}/preview-image").status_code == 404
