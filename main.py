import ipaddress
import asyncio
import io
import re
import socket
import json
import secrets
import uuid
from datetime import date, datetime, timezone
from html import escape as html_escape
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from xml.sax.saxutils import escape as xml_escape

import httpx
import bleach
from bs4 import BeautifulSoup
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field, HttpUrl
from pypinyin import lazy_pinyin
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from config import settings
from database import get_db
import models


BASE_DIR = Path(__file__).resolve().parent
MEDIA_ROOT = BASE_DIR / "media"
UPLOAD_ROOT = MEDIA_ROOT / "uploads"
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
templates = Jinja2Templates(directory=BASE_DIR / "templates")

app = FastAPI(title="meetseek Community")
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
if settings.allowed_cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
    )
app.mount("/media", StaticFiles(directory=MEDIA_ROOT), name="media")


def csp_value(nonce: str) -> str:
    return "; ".join(
        [
            "default-src 'self'",
            f"script-src 'self' 'nonce-{nonce}' https://cdn.tailwindcss.com https://unpkg.com",
            "style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com",
            "img-src 'self' data: https:",
            "font-src 'self' data:",
            "connect-src 'self'",
            "object-src 'none'",
            "base-uri 'self'",
            "frame-ancestors 'self'",
            "form-action 'self'",
            "upgrade-insecure-requests",
        ]
    )


@app.middleware("http")
async def inject_security_headers(request: Request, call_next):
    request.state.csp_nonce = secrets.token_urlsafe(16)
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = csp_value(request.state.csp_nonce)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    return response


@app.middleware("http")
async def reject_large_json_payload(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        content_type = request.headers.get("content-type", "").lower()
        content_length = request.headers.get("content-length")
        if "application/json" in content_type and content_length:
            try:
                if int(content_length) > settings.max_json_body_bytes:
                    return Response(content="Payload Too Large", status_code=413)
            except ValueError:
                return Response(content="Invalid Content-Length", status_code=400)
    return await call_next(request)

URL_RE = re.compile(r"https?://[^\s<>'\"]+", re.IGNORECASE)
FEED_PAGE_SIZE = 10
SITE_URL = settings.site_url.rstrip("/")
SITE_HOST = urlparse(SITE_URL).hostname or "meetseek.ai"
SITE_ROOT_DOMAIN = SITE_HOST.removeprefix("www.")
MAX_UPLOAD_BYTES = settings.max_upload_bytes
MAX_IMAGE_SIDE = settings.max_image_side
WEBP_QUALITY = settings.webp_quality
AUTH_COOKIE_NAME = settings.auth_cookie_name
AUTH_COOKIE_DOMAIN = settings.auth_cookie_domain
AUTH_COOKIE_MAX_AGE = settings.auth_cookie_max_age
PARSE_URL_TIMEOUT_SECONDS = min(settings.parse_url_timeout_seconds, 3.0)
MAX_PARSE_REDIRECTS = 3
ALLOWED_UPLOAD_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp", "image/tiff"}
ALLOWED_HTML_TAGS = [
    "a", "abbr", "blockquote", "br", "code", "del", "em", "h2", "h3", "h4",
    "hr", "img", "li", "ol", "p", "pre", "strong", "ul",
]
ALLOWED_HTML_ATTRS = {
    "a": ["href", "title", "rel", "target"],
    "abbr": ["title"],
    "img": ["src", "alt", "title", "loading"],
}
ALLOWED_HTML_PROTOCOLS = ["http", "https", "mailto"]
CATEGORY_SEO = {
    "general": {
        "name": "综合讨论",
        "description": "AI 工具、提示词、商业变现和产品实践的综合讨论。",
    },
    "prompts": {
        "name": "提示词",
        "description": "高质量 AI 绘图、视频生成和写作提示词案例，适合 Midjourney、Stable Diffusion、即梦、可灵等模型。",
    },
    "tools": {
        "name": "工具箱",
        "description": "实用 AI 工具、效率工具和自动化工作流分享，帮助个人和团队更快完成内容生产。",
    },
    "business": {
        "name": "商业变现",
        "description": "AI 产品、内容站、工具站和社区增长的商业化经验与复盘。",
    },
}
AUTH_FAILURES: dict[str, int] = {}
ADMIN_FAILURES: dict[str, int] = {}
MAX_FAILURE_DELAY_SECONDS = 8.0


class ParseUrlRequest(BaseModel):
    url: HttpUrl


class LoginRequest(BaseModel):
    username: str | None = Field(default=None, max_length=120)
    password: str | None = Field(default=None, max_length=200)


class PostCreate(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    title: str | None = Field(default=None, max_length=180)
    type: str = Field(default="short", pattern="^(short|article|tool)$")
    category: str = Field(default="general", pattern="^[a-z0-9-]{1,80}$")
    link_preview: dict[str, Any] | None = None


class PostAction(BaseModel):
    post_id: int = Field(gt=0)


class CommentCreate(BaseModel):
    post_id: int = Field(gt=0)
    body: str = Field(min_length=1, max_length=3000)
    parent_id: int | None = Field(default=None, gt=0)


class CommentUpdate(BaseModel):
    body: str = Field(min_length=1, max_length=3000)


class AdminPostAction(BaseModel):
    action: str = Field(pattern="^(delete|pin|unpin|hide)$")


class PostUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=180)
    content: str | None = Field(default=None, min_length=1, max_length=20000)
    summary: str | None = Field(default=None, max_length=320)


def get_current_user() -> dict[str, Any]:
    return {
        "id": settings.mock_user_id,
        "reputation": settings.mock_reputation,
        "is_admin": settings.mock_is_admin,
    }


def client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


async def apply_failure_delay(bucket: dict[str, int], ip: str, base_delay: float) -> None:
    failures = bucket.get(ip, 0)
    if failures <= 0:
        return
    await asyncio.sleep(min(base_delay * failures, MAX_FAILURE_DELAY_SECONDS))


def record_auth_failure(bucket: dict[str, int], ip: str) -> None:
    bucket[ip] = min(bucket.get(ip, 0) + 1, 20)


def clear_auth_failures(bucket: dict[str, int], ip: str) -> None:
    bucket.pop(ip, None)


def contains_external_link(text: str) -> bool:
    return bool(URL_RE.search(text or ""))


def clean_text(value: str | None, limit: int = 320) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    return text[:limit].rstrip()


def is_internal_url(href: str | None) -> bool:
    if not href:
        return True
    parsed = urlparse(href)
    if not parsed.netloc:
        return True
    host = (parsed.hostname or "").lower()
    return host == SITE_ROOT_DOMAIN or host.endswith(f".{SITE_ROOT_DOMAIN}")


def isolate_ugc_external_links(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for link in soup.find_all("a", href=True):
        if is_internal_url(link.get("href")):
            continue
        existing_rel = link.get("rel") or []
        if isinstance(existing_rel, str):
            existing_rel = existing_rel.split()
        rel_values = list(dict.fromkeys([*existing_rel, "nofollow", "ugc"]))
        link["rel"] = " ".join(rel_values)
        link["target"] = "_blank"
    return str(soup)


def sanitize_rich_html(value: str | None) -> str:
    soup = BeautifulSoup(value or "", "html.parser")
    for tag in soup(["script", "style", "template", "iframe", "object", "embed", "svg", "math"]):
        tag.decompose()
    cleaned = bleach.clean(
        str(soup),
        tags=ALLOWED_HTML_TAGS,
        attributes=ALLOWED_HTML_ATTRS,
        protocols=ALLOWED_HTML_PROTOCOLS,
        strip=True,
        strip_comments=True,
    )
    return isolate_ugc_external_links(cleaned)


def html_to_text(value: str | None, limit: int = 20000) -> str:
    soup = BeautifulSoup(value or "", "html.parser")
    return clean_text(soup.get_text(" "), limit)


def text_to_safe_html(value: str | None) -> str:
    escaped = html_escape(value or "")
    return sanitize_rich_html(f"<p>{escaped}</p>")


def set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=token,
        max_age=AUTH_COOKIE_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="lax",
        domain=AUTH_COOKIE_DOMAIN,
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(
        key=AUTH_COOKIE_NAME,
        domain=AUTH_COOKIE_DOMAIN,
        path="/",
        httponly=True,
        secure=True,
        samesite="lax",
    )


def absolute_url(path: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return f"{SITE_URL}{path if path.startswith('/') else '/' + path}"


def enum_value(value: Any) -> str:
    return getattr(value, "value", value)


def dt_iso(value: Any) -> str:
    return value.isoformat() if value else ""


FEED_SORT_OPTIONS = {
    "latest": (
        models.Post.pinned_at.desc().nulls_last(),
        models.Post.published_at.desc().nulls_last(),
        models.Post.created_at.desc(),
    ),
    "popular": (
        models.Post.pinned_at.desc().nulls_last(),
        models.Post.like_count.desc(),
        models.Post.comment_count.desc(),
        models.Post.published_at.desc().nulls_last(),
    ),
    "comments": (
        models.Post.pinned_at.desc().nulls_last(),
        models.Post.comment_count.desc(),
        models.Post.published_at.desc().nulls_last(),
    ),
    "oldest": (
        models.Post.created_at.asc(),
        models.Post.id.asc(),
    ),
}


def feed_order_by(sort_by: str):
    if sort_by not in FEED_SORT_OPTIONS:
        raise HTTPException(status_code=400, detail="不支持的排序字段")
    return FEED_SORT_OPTIONS[sort_by]


def public_posts_stmt(sort_by: str = "latest"):
    return (
        select(models.Post)
        .options(selectinload(models.Post.author))
        .where(
            models.Post.status == models.PostStatus.published,
            models.Post.visibility == models.Visibility.public,
        )
        .order_by(*feed_order_by(sort_by))
    )


def load_feed_posts(db: Session, offset: int, limit: int, sort_by: str = "latest") -> list[models.Post]:
    return list(db.execute(public_posts_stmt(sort_by).offset(offset).limit(limit)).scalars())


def link_preview_for(post: models.Post) -> dict[str, Any] | None:
    if not post.source_url:
        return None
    meta = post.source_meta or {}
    return {
        "url": post.source_url,
        "title": clean_text(meta.get("title") or meta.get("og:title") or post.title, 180),
        "description": clean_text(meta.get("description") or meta.get("og:description") or post.summary, 240),
        "image": meta.get("image") or meta.get("og:image") or "",
        "site_name": clean_text(meta.get("site_name") or meta.get("og:site_name") or urlparse(post.source_url).netloc, 80),
    }


def post_excerpt(post: models.Post) -> str:
    return clean_text(post.summary or post.body_text or post.title, 220)


def serialize_post(post: models.Post, index: int = 0) -> dict[str, Any]:
    cover = post.cover_image_url or post.og_image or ""
    span = "md:col-span-2" if cover and index % 7 == 0 else ""
    return {
        "id": post.id,
        "type": enum_value(post.type),
        "category": post.category_slug,
        "title": post.title,
        "slug": post.slug,
        "summary": post_excerpt(post),
        "url": f"/p/{post.slug}",
        "cover_image_url": cover,
        "author": {
            "id": post.author.id if post.author else None,
            "name": post.author.display_name if post.author else "meetseek",
            "avatar_url": post.author.avatar_url if post.author else "",
        },
        "link_preview": link_preview_for(post),
        "like_count": post.like_count or 0,
        "comment_count": post.comment_count or 0,
        "is_pinned": bool(post.pinned_at),
        "created_at": dt_iso(post.created_at),
        "published_at": dt_iso(post.published_at or post.created_at),
        "card_class": span,
    }


def serialize_ad(ad: models.Advertisement) -> dict[str, Any]:
    return {
        "id": ad.id,
        "location": ad.location,
        "title": ad.title or "",
        "html_content": ad.html_content,
    }


def structured_data_for_post(post: models.Post, meta: dict[str, Any]) -> dict[str, Any]:
    url = meta["canonical_url"]
    image = meta.get("og_image") or post.og_image or post.cover_image_url or ""
    author_name = post.author.display_name if post.author else "meetseek"
    if post.type == models.ContentType.tool:
        return {
            "@context": "https://schema.org",
            "@type": "SoftwareApplication",
            "name": post.title,
            "description": meta["description"],
            "url": url,
            "image": image,
            "applicationCategory": "AIApplication",
            "operatingSystem": "Web",
            "author": {"@type": "Person", "name": author_name},
            "aggregateRating": {
                "@type": "AggregateRating",
                "ratingValue": "4.8",
                "ratingCount": str(max(post.like_count or 1, 1)),
            },
        }
    return {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": post.title,
        "description": meta["description"],
        "url": url,
        "image": image,
        "datePublished": dt_iso(post.published_at or post.created_at),
        "dateModified": dt_iso(post.updated_at),
        "author": {"@type": "Person", "name": author_name},
        "publisher": {"@type": "Organization", "name": "meetseek"},
    }


def category_meta(category_slug: str) -> dict[str, str]:
    fallback_name = category_slug.replace("-", " ").strip().title() or "分类"
    return CATEGORY_SEO.get(
        category_slug,
        {
            "name": fallback_name,
            "description": f"{fallback_name} 分类下的 AI 工具、提示词和社区内容。",
        },
    )


def breadcrumb_items_for_post(post: models.Post) -> list[dict[str, str]]:
    category = category_meta(post.category_slug)
    return [
        {"name": "首页", "url": f"{SITE_URL}/"},
        {"name": category["name"], "url": f"{SITE_URL}/category/{post.category_slug}"},
        {"name": post.title, "url": f"{SITE_URL}/p/{post.slug}"},
    ]


def breadcrumb_structured_data(items: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": index,
                "name": item["name"],
                "item": item["url"],
            }
            for index, item in enumerate(items, start=1)
        ],
    }


def page_structured_data(*items: dict[str, Any]) -> str:
    return json.dumps({"@context": "https://schema.org", "@graph": list(items)}, ensure_ascii=False)


def load_related_posts(db: Session, post: models.Post, limit: int = 3) -> list[models.Post]:
    return list(
        db.execute(
            public_posts_stmt()
            .where(models.Post.category_slug == post.category_slug, models.Post.id != post.id)
            .limit(limit)
        ).scalars()
    )


def compress_image_to_webp(raw: bytes) -> tuple[bytes, int, int]:
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="图片太大，请上传 8MB 以内的图片")
    try:
        probe = Image.open(io.BytesIO(raw))
        mime_type = Image.MIME.get(probe.format or "")
        probe.verify()
        if mime_type not in ALLOWED_UPLOAD_MIME_TYPES:
            raise HTTPException(status_code=400, detail="不支持的图片类型")
        image = Image.open(io.BytesIO(raw))
        image = ImageOps.exif_transpose(image)
    except (UnidentifiedImageError, OSError, ValueError):
        raise HTTPException(status_code=400, detail="无法识别图片格式")

    if image.mode not in {"RGB", "RGBA"}:
        image = image.convert("RGB")
    if image.width > MAX_IMAGE_SIDE or image.height > MAX_IMAGE_SIDE:
        image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), Image.Resampling.LANCZOS)

    output = io.BytesIO()
    save_kwargs = {"format": "WEBP", "quality": WEBP_QUALITY, "method": 6}
    if image.mode == "RGBA":
        save_kwargs["lossless"] = False
    image.save(output, **save_kwargs)
    return output.getvalue(), image.width, image.height


def rss_item_for(post: models.Post) -> str:
    url = xml_escape(f"{SITE_URL}/p/{post.slug}")
    title = xml_escape(post.title)
    description = xml_escape(post_excerpt(post))
    pub_date = (post.published_at or post.created_at or datetime.now(timezone.utc)).strftime("%a, %d %b %Y %H:%M:%S %z")
    author = xml_escape(post.author.display_name if post.author else "meetseek")
    return (
        "<item>"
        f"<title>{title}</title>"
        f"<link>{url}</link>"
        f"<guid isPermaLink=\"true\">{url}</guid>"
        f"<description>{description}</description>"
        f"<author>{author}</author>"
        f"<pubDate>{xml_escape(pub_date)}</pubDate>"
        "</item>"
    )


def not_found_response(request: Request, title: str = "内容不存在"):
    return templates.TemplateResponse(
        "404.html",
        {
            "request": request,
            "meta": {
                "title": f"{title} - meetseek",
                "description": "你访问的内容不存在或已被移除。",
                "og_title": f"{title} - meetseek",
                "og_description": "你访问的内容不存在或已被移除。",
                "og_image": "",
                "canonical_url": f"{SITE_URL}/",
            },
        },
        status_code=404,
    )


def require_db_user(db: Session, current_user: dict[str, Any]) -> models.User:
    user = db.get(models.User, current_user["id"])
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="请先登录")
    return user


async def require_admin(request: Request, current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    ip = client_ip(request)
    if not current_user.get("is_admin"):
        await apply_failure_delay(ADMIN_FAILURES, ip, settings.admin_failure_delay_seconds)
        record_auth_failure(ADMIN_FAILURES, ip)
        raise HTTPException(status_code=403, detail="需要管理员权限")
    clear_auth_failures(ADMIN_FAILURES, ip)
    return current_user


def load_owned_post_for_update(db: Session, post_id: int, current_user: dict[str, Any]) -> models.Post:
    post = db.execute(select(models.Post).where(models.Post.id == post_id).with_for_update()).scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="帖子不存在")
    if not current_user.get("is_admin") and post.author_id != current_user["id"]:
        raise HTTPException(status_code=403, detail="无权修改这个资源")
    return post


def load_owned_comment_for_update(db: Session, comment_id: int, current_user: dict[str, Any]) -> models.Comment:
    comment = db.execute(select(models.Comment).where(models.Comment.id == comment_id).with_for_update()).scalar_one_or_none()
    if not comment:
        raise HTTPException(status_code=404, detail="评论不存在")
    if not current_user.get("is_admin") and comment.author_id != current_user["id"]:
        raise HTTPException(status_code=403, detail="无权修改这个资源")
    return comment


def load_public_post_for_update(db: Session, post_id: int) -> models.Post:
    post = db.execute(
        select(models.Post)
        .where(
            models.Post.id == post_id,
            models.Post.status == models.PostStatus.published,
            models.Post.visibility == models.Visibility.public,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="帖子不存在")
    return post


async def toggle_like(payload: PostAction, db: Session, current_user: dict[str, Any]) -> dict[str, Any]:
    actor = require_db_user(db, current_user)
    try:
        post = load_public_post_for_update(db, payload.post_id)
        author = db.execute(select(models.User).where(models.User.id == post.author_id).with_for_update()).scalar_one_or_none()
        existing = db.execute(
            select(models.Interaction)
            .where(
                models.Interaction.user_id == actor.id,
                models.Interaction.post_id == post.id,
                models.Interaction.type == models.InteractionType.like,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if existing:
            db.delete(existing)
            post.like_count = max((post.like_count or 0) - 1, 0)
            if author:
                author.reputation = (author.reputation or 0) - 1
            liked = False
        else:
            db.add(models.Interaction(user_id=actor.id, post_id=post.id, type=models.InteractionType.like))
            post.like_count = (post.like_count or 0) + 1
            if author:
                author.reputation = (author.reputation or 0) + 1
            liked = True
        db.commit()
        return {
            "post_id": post.id,
            "liked": liked,
            "like_count": post.like_count,
            "author_reputation": author.reputation if author else 0,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="点赞处理失败")


def meta_content(soup: BeautifulSoup, *keys: str) -> str:
    for key in keys:
        tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
        if tag and tag.get("content"):
            return clean_text(tag["content"], 700)
    return ""


def assert_public_url(raw_url: str) -> None:
    parsed = urlparse(raw_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=400, detail="只支持 http/https 外链")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror:
        raise HTTPException(status_code=400, detail="无法解析这个域名")
    for item in addresses:
        ip = ipaddress.ip_address(item[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise HTTPException(status_code=400, detail="不允许解析内网或本机地址")


async def enforce_post_permission(
    payload: PostCreate,
    current_user: dict[str, int] = Depends(get_current_user),
) -> dict[str, Any]:
    if current_user["reputation"] < 50 and contains_external_link(payload.content):
        raise HTTPException(status_code=403, detail="积分低于 50，暂时不能发布外链内容")
    return {"payload": payload, "user": current_user}


@app.post("/api/parse-url")
@limiter.limit("12/minute")
async def parse_url(request: Request, payload: ParseUrlRequest):
    raw_url = str(payload.url)
    assert_public_url(raw_url)
    headers = {
        "User-Agent": "Mozilla/5.0 meetseekbot/0.1 (+https://meetseek.ai)",
        "Accept": "text/html,application/xhtml+xml",
    }
    try:
        current_url = raw_url
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(PARSE_URL_TIMEOUT_SECONDS),
            follow_redirects=False,
            headers=headers,
        ) as client:
            for _ in range(MAX_PARSE_REDIRECTS + 1):
                assert_public_url(current_url)
                response = await client.get(current_url)
                if response.status_code not in {301, 302, 303, 307, 308}:
                    break
                location = response.headers.get("location")
                if not location:
                    break
                current_url = urljoin(str(response.url), location)
            else:
                raise HTTPException(status_code=400, detail="重定向次数过多")
            assert_public_url(str(response.url))
            response.raise_for_status()
    except httpx.TimeoutException:
        raise HTTPException(status_code=408, detail="解析超时，请稍后再试")
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=400, detail=f"目标网站返回 {exc.response.status_code}")
    except httpx.HTTPError:
        raise HTTPException(status_code=400, detail="无法抓取这个链接")

    content_type = response.headers.get("content-type", "")
    if "html" not in content_type.lower():
        raise HTTPException(status_code=400, detail="这个链接不是网页内容")

    soup = BeautifulSoup(response.text[:800_000], "html.parser")
    page_title = soup.title.string if soup.title and soup.title.string else ""
    title = clean_text(meta_content(soup, "og:title", "twitter:title") or page_title or urlparse(str(response.url)).netloc, 180)
    description = clean_text(meta_content(soup, "og:description", "twitter:description", "description"), 320)
    image = meta_content(soup, "og:image", "og:image:url", "twitter:image")
    site_name = clean_text(meta_content(soup, "og:site_name") or urlparse(str(response.url)).netloc, 120)

    return {
        "url": str(response.url),
        "title": title,
        "description": description,
        "image": urljoin(str(response.url), image) if image else "",
        "site_name": site_name,
    }


@app.post("/api/auth/mock-login")
@limiter.limit("3/minute")
async def mock_login(request: Request, response: Response, payload: LoginRequest | None = None):
    ip = client_ip(request)
    await apply_failure_delay(AUTH_FAILURES, ip, settings.login_failure_delay_seconds)
    expected_password = settings.mock_login_password.get_secret_value() if settings.mock_login_password else ""
    if expected_password and (not payload or payload.password != expected_password):
        record_auth_failure(AUTH_FAILURES, ip)
        await asyncio.sleep(settings.login_failure_delay_seconds)
        raise HTTPException(status_code=401, detail="用户名或密码不正确")
    token = secrets.token_urlsafe(32)
    set_auth_cookie(response, token)
    clear_auth_failures(AUTH_FAILURES, ip)
    return {"ok": True}


@app.post("/api/auth/logout")
@limiter.limit("10/minute")
async def logout(request: Request, response: Response):
    clear_auth_cookie(response)
    return {"ok": True}


@app.post("/api/posts")
@limiter.limit("2/minute")
async def create_post(request: Request, context: dict[str, Any] = Depends(enforce_post_permission)):
    payload: PostCreate = context["payload"]
    user = context["user"]
    safe_html = sanitize_rich_html(payload.content)
    text_content = html_to_text(safe_html)
    title = clean_text(payload.title or text_content, 80)
    now = datetime.now(timezone.utc)
    post_id = int(now.timestamp() * 1000)
    post = {
        "id": post_id,
        "author_id": user["id"],
        "type": payload.type,
        "category": payload.category,
        "title": title,
        "summary": clean_text(text_content, 220),
        "content": text_content,
        "body_html": safe_html,
        "link_preview": payload.link_preview,
        "cover_image_url": "",
        "url": "#",
        "status": "published",
        "like_count": 0,
        "comment_count": 0,
        "is_pinned": False,
        "created_at": dt_iso(now),
        "published_at": dt_iso(now),
        "author": {
            "id": user["id"],
            "name": "我",
            "avatar_url": "",
        },
    }
    return {
        "ok": True,
        "post": post,
    }


@app.patch("/api/posts/{post_id}")
@limiter.limit("6/minute")
async def update_post(
    request: Request,
    post_id: int,
    payload: PostUpdate,
    db: Session = Depends(get_db),
    current_user: dict[str, Any] = Depends(get_current_user),
):
    try:
        post = load_owned_post_for_update(db, post_id, current_user)
        if payload.title is not None:
            post.title = clean_text(payload.title, 180)
        if payload.summary is not None:
            post.summary = clean_text(payload.summary, 320)
        if payload.content is not None:
            safe_html = sanitize_rich_html(payload.content)
            post.body_html = safe_html
            post.body_text = html_to_text(safe_html)
        db.commit()
        db.refresh(post)
        return {"post": serialize_post(post)}
    except HTTPException:
        db.rollback()
        raise


@app.delete("/api/posts/{post_id}")
@limiter.limit("4/minute")
async def delete_post(
    request: Request,
    post_id: int,
    db: Session = Depends(get_db),
    current_user: dict[str, Any] = Depends(get_current_user),
):
    try:
        post = load_owned_post_for_update(db, post_id, current_user)
        post.status = models.PostStatus.deleted
        post.visibility = models.Visibility.private
        db.commit()
        return {"post_id": post.id, "deleted": True}
    except HTTPException:
        db.rollback()
        raise


@app.get("/api/ads")
@limiter.limit("60/minute")
async def ads(request: Request, location: str = Query(..., min_length=1, max_length=80), db: Session = Depends(get_db)):
    rows = list(
        db.execute(
            select(models.Advertisement)
            .where(
                models.Advertisement.location == location,
                models.Advertisement.status == "active",
            )
            .order_by(models.Advertisement.sort_order.asc(), models.Advertisement.id.asc())
            .limit(8)
        ).scalars()
    )
    return {"location": location, "ads": [serialize_ad(row) for row in rows]}


@app.get("/api/feed")
@limiter.limit("60/minute")
async def feed(
    request: Request,
    page: int = Query(2, ge=1),
    sort_by: str = Query("latest", min_length=1, max_length=32),
    db: Session = Depends(get_db),
):
    offset = (page - 1) * FEED_PAGE_SIZE
    rows = load_feed_posts(db, offset, FEED_PAGE_SIZE + 1, sort_by)
    items = rows[:FEED_PAGE_SIZE]
    return {
        "page": page,
        "sort_by": sort_by,
        "has_more": len(rows) > FEED_PAGE_SIZE,
        "items": [serialize_post(post, offset + index) for index, post in enumerate(items)],
    }


@app.post("/api/admin/posts/{post_id}/action")
@limiter.limit("10/minute")
async def admin_post_action(
    request: Request,
    post_id: int,
    payload: AdminPostAction,
    db: Session = Depends(get_db),
    current_user: dict[str, Any] = Depends(require_admin),
):
    post = db.execute(select(models.Post).where(models.Post.id == post_id).with_for_update()).scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="帖子不存在")

    if payload.action == "delete":
        post.status = models.PostStatus.deleted
        post.visibility = models.Visibility.private
    elif payload.action == "hide":
        post.status = models.PostStatus.hidden
    elif payload.action == "pin":
        post.pinned_at = datetime.now(timezone.utc)
    elif payload.action == "unpin":
        post.pinned_at = None

    db.commit()
    return {
        "post_id": post.id,
        "action": payload.action,
        "status": enum_value(post.status),
        "visibility": enum_value(post.visibility),
        "is_pinned": bool(post.pinned_at),
    }


@app.post("/api/like")
@limiter.limit("10/minute")
async def like(request: Request, payload: PostAction, db: Session = Depends(get_db), current_user: dict[str, int] = Depends(get_current_user)):
    return await toggle_like(payload, db, current_user)


@app.post("/api/posts/{post_id}/like")
@limiter.limit("10/minute")
async def like_post(request: Request, post_id: int, db: Session = Depends(get_db), current_user: dict[str, int] = Depends(get_current_user)):
    return await toggle_like(PostAction(post_id=post_id), db, current_user)


@app.post("/api/bookmark")
@limiter.limit("20/minute")
async def bookmark(request: Request, payload: PostAction, db: Session = Depends(get_db), current_user: dict[str, int] = Depends(get_current_user)):
    actor = require_db_user(db, current_user)
    try:
        post = load_public_post_for_update(db, payload.post_id)
        existing = db.execute(
            select(models.Interaction)
            .where(
                models.Interaction.user_id == actor.id,
                models.Interaction.post_id == post.id,
                models.Interaction.type == models.InteractionType.bookmark,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if existing:
            db.delete(existing)
            post.bookmark_count = max((post.bookmark_count or 0) - 1, 0)
            bookmarked = False
        else:
            db.add(models.Interaction(user_id=actor.id, post_id=post.id, type=models.InteractionType.bookmark))
            post.bookmark_count = (post.bookmark_count or 0) + 1
            bookmarked = True
        db.commit()
        return {"post_id": post.id, "bookmarked": bookmarked, "bookmark_count": post.bookmark_count}
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="收藏处理失败")


@app.post("/api/comments")
@limiter.limit("6/minute")
async def comments(request: Request, payload: CommentCreate, db: Session = Depends(get_db), current_user: dict[str, Any] = Depends(get_current_user)):
    actor = require_db_user(db, current_user)
    try:
        post = load_public_post_for_update(db, payload.post_id)
        parent = None
        if payload.parent_id:
            parent = db.get(models.Comment, payload.parent_id)
            if not parent or parent.post_id != post.id:
                raise HTTPException(status_code=400, detail="回复目标不存在")
        body = clean_text(payload.body, 3000)
        safe_html = text_to_safe_html(body)
        comment = models.Comment(
            post_id=post.id,
            author_id=actor.id,
            parent_id=parent.id if parent else None,
            body_text=body,
            body_html=safe_html,
            status=models.PostStatus.published,
        )
        db.add(comment)
        post.comment_count = (post.comment_count or 0) + 1
        db.commit()
        db.refresh(comment)
        return {
            "id": comment.id,
            "post_id": post.id,
            "author": {"id": actor.id, "name": actor.display_name, "avatar_url": actor.avatar_url or ""},
            "body": comment.body_text,
            "created_at": dt_iso(comment.created_at),
            "comment_count": post.comment_count,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="评论发布失败")


@app.patch("/api/comments/{comment_id}")
@limiter.limit("8/minute")
async def update_comment(
    request: Request,
    comment_id: int,
    payload: CommentUpdate,
    db: Session = Depends(get_db),
    current_user: dict[str, Any] = Depends(get_current_user),
):
    try:
        comment = load_owned_comment_for_update(db, comment_id, current_user)
        body = clean_text(payload.body, 3000)
        comment.body_text = body
        comment.body_html = text_to_safe_html(body)
        db.commit()
        db.refresh(comment)
        return {
            "id": comment.id,
            "post_id": comment.post_id,
            "body": comment.body_text,
            "updated_at": dt_iso(comment.updated_at),
        }
    except HTTPException:
        db.rollback()
        raise


@app.delete("/api/comments/{comment_id}")
@limiter.limit("6/minute")
async def delete_comment(
    request: Request,
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: dict[str, Any] = Depends(get_current_user),
):
    try:
        comment = load_owned_comment_for_update(db, comment_id, current_user)
        post = db.execute(select(models.Post).where(models.Post.id == comment.post_id).with_for_update()).scalar_one_or_none()
        comment.status = models.PostStatus.deleted
        if post:
            post.comment_count = max((post.comment_count or 0) - 1, 0)
        db.commit()
        return {
            "id": comment.id,
            "post_id": comment.post_id,
            "deleted": True,
            "comment_count": post.comment_count if post else None,
        }
    except HTTPException:
        db.rollback()
        raise


@app.post("/api/images/upload")
@limiter.limit("10/minute")
async def upload_image(request: Request, file: UploadFile = File(...)):
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    webp_bytes, width, height = compress_image_to_webp(raw)
    today = date.today()
    folder = UPLOAD_ROOT / f"{today:%Y}" / f"{today:%m}"
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.webp"
    path = folder / filename
    path.write_bytes(webp_bytes)
    url = f"/media/uploads/{today:%Y}/{today:%m}/{filename}"
    return {
        "url": url,
        "absolute_url": absolute_url(url),
        "width": width,
        "height": height,
        "size": len(webp_bytes),
        "format": "webp",
    }


@app.get("/", response_class=HTMLResponse)
async def home(request: Request, db: Session = Depends(get_db), current_user: dict[str, Any] = Depends(get_current_user)):
    meta = {
        "title": "meetseek - AI 技术与商业变现社区",
        "description": "meetseek 是一个融合 AI 工具箱、提示词库和轻量社区的内容站。",
        "og_title": "meetseek - AI 技术与商业变现社区",
        "og_description": "AI 工具、提示词案例、商业变现经验和社区讨论。",
        "og_image": "https://meetseek.ai/static/og-cover.png",
        "og_type": "website",
        "site_name": "meetseek",
        "canonical_url": f"{SITE_URL}/",
    }
    rows = load_feed_posts(db, 0, FEED_PAGE_SIZE)
    posts = [serialize_post(post, index) for index, post in enumerate(rows)]
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "meta": meta,
            "posts": posts,
            "next_page": 2,
            "has_more": len(posts) == FEED_PAGE_SIZE,
            "current_user": current_user,
        },
    )


@app.get("/u/{username}", response_class=HTMLResponse)
async def profile(username: str, request: Request, db: Session = Depends(get_db)):
    user = db.execute(select(models.User).where(models.User.username == username, models.User.is_active.is_(True))).scalar_one_or_none()
    if not user:
        return not_found_response(request, "用户不存在")

    posts = list(
        db.execute(
            select(models.Post)
            .options(selectinload(models.Post.author))
            .where(
                models.Post.author_id == user.id,
                models.Post.status == models.PostStatus.published,
                models.Post.visibility == models.Visibility.public,
            )
            .order_by(models.Post.pinned_at.desc().nulls_last(), models.Post.published_at.desc().nulls_last(), models.Post.created_at.desc())
            .limit(24)
        ).scalars()
    )
    bookmarked = list(
        db.execute(
            select(models.Post)
            .join(models.Interaction, models.Interaction.post_id == models.Post.id)
            .options(selectinload(models.Post.author))
            .where(
                models.Interaction.user_id == user.id,
                models.Interaction.type == models.InteractionType.bookmark,
                models.Post.status == models.PostStatus.published,
                models.Post.visibility == models.Visibility.public,
            )
            .order_by(models.Interaction.created_at.desc())
            .limit(24)
        ).scalars()
    )
    liked_total = db.execute(
        select(func.coalesce(func.sum(models.Post.like_count), 0)).where(
            models.Post.author_id == user.id,
            models.Post.status == models.PostStatus.published,
            models.Post.visibility == models.Visibility.public,
        )
    ).scalar_one()
    post_total = db.execute(
        select(func.count(models.Post.id)).where(
            models.Post.author_id == user.id,
            models.Post.status == models.PostStatus.published,
            models.Post.visibility == models.Visibility.public,
        )
    ).scalar_one()
    meta = {
        "title": f"{user.display_name} 的主页 - meetseek",
        "description": clean_text(user.bio or f"{user.display_name} 在 meetseek 发布的内容、收藏和社区积分。", 160),
        "og_title": f"{user.display_name} 的主页 - meetseek",
        "og_description": clean_text(user.bio or f"{user.display_name} 在 meetseek 发布的内容、收藏和社区积分。", 160),
        "og_image": user.avatar_url or "",
        "og_type": "profile",
        "site_name": "meetseek",
        "canonical_url": f"{SITE_URL}/u/{user.username}",
    }
    return templates.TemplateResponse(
        "profile.html",
        {
            "request": request,
            "meta": meta,
            "user": user,
            "stats": {
                "reputation": user.reputation or 0,
                "liked_total": int(liked_total or 0),
                "post_total": int(post_total or 0),
                "bookmark_total": len(bookmarked),
            },
            "posts": [serialize_post(post, index) for index, post in enumerate(posts)],
            "bookmarks": [serialize_post(post, index) for index, post in enumerate(bookmarked)],
        },
    )


@app.get("/sitemap.xml")
async def sitemap_xml(db: Session = Depends(get_db)):
    rows = db.execute(
        select(models.Post.slug, models.Post.updated_at)
        .where(
            models.Post.status == models.PostStatus.published,
            models.Post.visibility == models.Visibility.public,
        )
        .order_by(models.Post.updated_at.desc())
    ).all()
    home_lastmod = dt_iso(rows[0].updated_at)[:10] if rows else date.today().isoformat()
    items = [
        f"<url><loc>{xml_escape(SITE_URL + '/')}</loc><lastmod>{xml_escape(home_lastmod)}</lastmod><changefreq>daily</changefreq><priority>1.0</priority></url>"
    ]
    for row in rows:
        lastmod = dt_iso(row.updated_at)[:10]
        loc = xml_escape(f"{SITE_URL}/p/{row.slug}")
        items.append(f"<url><loc>{loc}</loc><lastmod>{xml_escape(lastmod)}</lastmod><changefreq>weekly</changefreq><priority>0.7</priority></url>")
    category_rows = db.execute(
        select(models.Post.category_slug, func.max(models.Post.updated_at).label("updated_at"))
        .where(
            models.Post.status == models.PostStatus.published,
            models.Post.visibility == models.Visibility.public,
        )
        .group_by(models.Post.category_slug)
    ).all()
    for row in category_rows:
        lastmod = dt_iso(row.updated_at)[:10]
        loc = xml_escape(f"{SITE_URL}/category/{row.category_slug}")
        items.append(f"<url><loc>{loc}</loc><lastmod>{xml_escape(lastmod)}</lastmod><changefreq>daily</changefreq><priority>0.8</priority></url>")
    xml = '<?xml version="1.0" encoding="UTF-8"?>' + '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(items) + "</urlset>"
    return Response(content=xml, media_type="application/xml")


@app.get("/robots.txt")
async def robots_txt():
    content = "\n".join(
        [
            "User-agent: *",
            "Allow: /",
            "Disallow: /api/",
            "Disallow: /admin",
            "Disallow: /admin/",
            "Disallow: /login",
            "Disallow: /register",
            "Disallow: /reset-password",
            "Disallow: /settings",
            "Disallow: /account",
            "",
            f"Sitemap: {SITE_URL}/sitemap.xml",
            "",
        ]
    )
    return Response(content=content, media_type="text/plain; charset=utf-8")


@app.get("/feed.xml")
async def rss_feed(db: Session = Depends(get_db)):
    posts = list(
        db.execute(
            public_posts_stmt()
            .options(selectinload(models.Post.author))
            .limit(50)
        ).scalars()
    )
    items = "".join(rss_item_for(post) for post in posts)
    last_build = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0">'
        "<channel>"
        "<title>meetseek 社区更新</title>"
        f"<link>{xml_escape(SITE_URL + '/')}</link>"
        "<description>AI 工具、提示词和商业变现经验更新。</description>"
        "<language>zh-CN</language>"
        f"<lastBuildDate>{xml_escape(last_build)}</lastBuildDate>"
        f"{items}"
        "</channel>"
        "</rss>"
    )
    return Response(content=xml, media_type="application/rss+xml")


@app.get("/category/{category_slug}", response_class=HTMLResponse)
async def category_page(category_slug: str, request: Request, db: Session = Depends(get_db), current_user: dict[str, Any] = Depends(get_current_user)):
    category = category_meta(category_slug)
    posts = list(
        db.execute(
            public_posts_stmt()
            .where(models.Post.category_slug == category_slug)
            .limit(24)
        ).scalars()
    )
    meta = {
        "title": f"{category['name']} - meetseek",
        "description": category["description"],
        "og_title": f"{category['name']} - meetseek",
        "og_description": category["description"],
        "og_image": "https://meetseek.ai/static/og-cover.png",
        "og_type": "website",
        "site_name": "meetseek",
        "canonical_url": f"{SITE_URL}/category/{category_slug}",
    }
    return templates.TemplateResponse(
        "category.html",
        {
            "request": request,
            "meta": meta,
            "category": {"slug": category_slug, **category},
            "posts": [serialize_post(post, index) for index, post in enumerate(posts)],
            "current_user": current_user,
        },
    )


@app.get("/p/{slug}", response_class=HTMLResponse)
async def post_detail(slug: str, request: Request, db: Session = Depends(get_db), current_user: dict[str, Any] = Depends(get_current_user)):
    post = db.execute(
        select(models.Post)
        .options(selectinload(models.Post.author))
        .where(
            models.Post.slug == slug,
            models.Post.status == models.PostStatus.published,
            models.Post.visibility == models.Visibility.public,
        )
        .limit(1)
    ).scalar_one_or_none()
    if not post:
        return not_found_response(request)

    post.view_count = (post.view_count or 0) + 1
    db.commit()
    db.refresh(post)

    description = clean_text(post.meta_description or post.summary or post.body_text or post.title, 320)
    image = post.og_image or post.cover_image_url or ""
    meta = {
        "title": post.meta_title or f"{post.title} - meetseek",
        "description": description,
        "og_title": post.meta_title or post.title,
        "og_description": description,
        "og_image": absolute_url(image) if image else "",
        "og_type": "article",
        "site_name": "meetseek",
        "canonical_url": post.canonical_url or f"{SITE_URL}/p/{post.slug}",
    }
    breadcrumbs = breadcrumb_items_for_post(post)
    article_schema = structured_data_for_post(post, meta)
    article_schema.pop("@context", None)
    related_posts = load_related_posts(db, post)
    return templates.TemplateResponse(
        "detail.html",
        {
            "request": request,
            "meta": meta,
            "post": post,
            "post_card": serialize_post(post),
            "breadcrumbs": breadcrumbs,
            "related_posts": [serialize_post(item, index) for index, item in enumerate(related_posts)],
            "current_user": current_user,
            "structured_data": page_structured_data(article_schema, breadcrumb_structured_data(breadcrumbs)),
        },
    )
