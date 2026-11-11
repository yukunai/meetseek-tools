import asyncio
import base64
import html
import hmac
import hashlib
import ipaddress
import json
import os
import re
import secrets
import shutil
import sqlite3
import socket
import smtplib
import time
import unicodedata
import uuid
from collections import defaultdict, deque
from contextvars import ContextVar
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from difflib import SequenceMatcher
from email.message import EmailMessage
from io import BytesIO
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote, urlparse

import bleach
import httpx
import yt_dlp
from bs4 import BeautifulSoup
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from app.admin_panel import setup_sqladmin
from app.auth import create_access_token, decode_access_token, hash_password_bcrypt, verify_password_bcrypt
from app.utils.editorjs import parse_editorjs_blocks
from app.utils.plagiarism_detector import ENTITY_TOKEN, PlagiarismDetector

try:
    from pypinyin import lazy_pinyin
except ImportError:  # pragma: no cover - production image installs pypinyin.
    lazy_pinyin = None


APP_ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
DOWNLOAD_DIR = DATA_DIR / "downloads"
IMAGE_DIR = DATA_DIR / "images"
TMP_DIR = DATA_DIR / "tmp"
COMPRESS_DIR = DATA_DIR / "compressed"
OFFICE_DIR = DATA_DIR / "office"
PAYMENT_DIR = DATA_DIR / "payments"
PROMPT_IMAGE_DIR = DATA_DIR / "prompt_images"
SHOP_IMAGE_DIR = DATA_DIR / "shop_images"
PLUGIN_IMAGE_DIR = DATA_DIR / "plugin_images"
AVATAR_DIR = DATA_DIR / "avatars"
POST_MEDIA_DIR = DATA_DIR / "post_media"
SETTINGS_FILE = DATA_DIR / "settings.json"
VISITOR_STATS_FILE = DATA_DIR / "visitor_stats.json"
PROMPT_GALLERY_FILE = DATA_DIR / "prompt_gallery.json"
IP_INTEL_FILE = DATA_DIR / "ip_intel.json"
CUSTOM_PROMPT_GALLERY_KEY = "_custom"
APP_DB_FILE = DATA_DIR / "app.db"
IOPAINT_URL = os.getenv("IOPAINT_URL", "http://localhost:8081").rstrip("/")
MAX_VIDEO_JOBS = int(os.getenv("MAX_VIDEO_JOBS", "1"))
MAX_IMAGE_MB = int(os.getenv("MAX_IMAGE_MB", "20"))
MAX_VIDEO_FILE_MB = int(os.getenv("MAX_VIDEO_FILE_MB", "2048"))
MAX_VIDEO_QUALITY = os.getenv("MAX_VIDEO_QUALITY", "4k").strip().lower()
MAX_OFFICE_FILE_MB = int(os.getenv("MAX_OFFICE_FILE_MB", "100"))
RETENTION_SECONDS = int(os.getenv("RETENTION_SECONDS", str(60 * 60)))
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "20"))
YTDLP_COOKIES_FILE = os.getenv("YTDLP_COOKIES_FILE", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN", ".meetseek.ai")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://tools.meetseek.ai").rstrip("/")
MAIN_BASE_URL = os.getenv("MAIN_BASE_URL", "https://meetseek.ai").rstrip("/")
PASSWORD_RESET_SECONDS = int(os.getenv("PASSWORD_RESET_SECONDS", str(60 * 15)))
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").strip()
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER).strip()
SMTP_TLS = os.getenv("SMTP_TLS", "true").lower() not in {"0", "false", "no"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^\+?[0-9][0-9\s-]{5,18}[0-9]$")
DEFAULT_PROMPT_SKILL = (
    "你是一个专业 AI 绘图提示词反推助手。请根据用户上传的图片，反推出可用于 Midjourney、Stable Diffusion、"
    "DALL-E 或其他图像模型的提示词。必须输出严格 JSON，字段为 zh 和 en。zh 使用中文，en 使用英文。"
    "两种提示词都要包含主体、场景、构图、镜头/视角、光线、色彩、材质、风格、细节、画质关键词。"
    "不要添加 Markdown，不要输出 JSON 之外的任何内容。"
)
default_prompt_config = {
    "provider": "openai",
    "api_base": OPENAI_BASE_URL,
    "model": OPENAI_MODEL,
    "api_key": "",
    "skill": DEFAULT_PROMPT_SKILL,
}
DEFAULT_TRANSLATE_SKILL = (
    "你是一个专业 AI 绘图提示词翻译助手。根据目标语言翻译并适度补全提示词，保留原意，"
    "补充主体、场景、构图、镜头、光线、色彩、材质、风格和画质关键词。只输出最终提示词。"
)
DEFAULT_REWRITE_SKILL = (
    "你是一个擅长中文社交媒体表达的文案编辑。请保留核心事实，不编造数据，"
    "把原文改写成用户要求的中文风格。不要解释过程，只输出成稿。"
)
DEFAULT_VIDEO_SUMMARY_SKILL = (
    "你是一个视频内容总结助手。请根据视频标题、字幕或转写文本，输出摘要、重点、金句和可发布文案。"
)
default_ai_configs = {
    "image_prompt_reverse": {
        "label": "图片反推提示词",
        "description": "上传图片后反推出中文和英文绘图提示词，必须选择支持视觉输入的模型。",
        "kind": "vision",
        "provider": "openai",
        "api_base": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "api_key": "",
        "skill": DEFAULT_PROMPT_SKILL,
    },
    "prompt_translate": {
        "label": "提示词中英互转",
        "description": "提示词详情页里中文转英文、英文转中文，文本模型即可。",
        "kind": "text",
        "provider": "deepseek",
        "api_base": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "api_key": "",
        "skill": DEFAULT_TRANSLATE_SKILL,
    },
    "copy_rewrite": {
        "label": "博主风格文案转换",
        "description": "把说明书或草稿改写成小红书体、知乎体等文案。",
        "kind": "text",
        "provider": "deepseek",
        "api_base": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "api_key": "",
        "skill": DEFAULT_REWRITE_SKILL,
    },
    "video_summary": {
        "label": "视频总结预留",
        "description": "后续用于 YouTube/B站视频总结、字幕总结和爆款摘要。",
        "kind": "text",
        "provider": "deepseek",
        "api_base": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "api_key": "",
        "skill": DEFAULT_VIDEO_SUMMARY_SKILL,
    },
}
prompt_provider_presets = {
    "ark": {"label": "火山方舟 Ark", "api_base": "https://ark.cn-beijing.volces.com/api/v3", "model": "doubao-seed-2-0-lite-260428", "text_model": "doubao-seed-2-0-lite-260428", "vision_model": "doubao-seed-2-0-lite-260428", "mode": "openai", "supports_vision": True, "note": "Seed 2.0 lite 是多模态理解模型，当前推荐模型名为 doubao-seed-2-0-lite-260428，并确认已在火山方舟开通。"},
    "ernie": {"label": "文心 ERNIE / 百度千帆", "api_base": "https://qianfan.baidubce.com/v2", "model": "ernie-4.5-turbo-128k", "text_model": "ernie-4.5-turbo-128k", "vision_model": "ernie-4.5-turbo-vl", "mode": "openai", "supports_vision": True, "note": "图片反推请使用 VL/多模态模型。"},
    "qwen": {"label": "通义千问 Qwen", "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus", "text_model": "qwen-plus", "vision_model": "qwen-vl-plus", "mode": "openai", "supports_vision": True, "note": "文本用 qwen-plus，图片用 qwen-vl-plus 或视觉模型。"},
    "deepseek": {"label": "DeepSeek", "api_base": "https://api.deepseek.com/v1", "model": "deepseek-chat", "text_model": "deepseek-chat", "vision_model": "", "mode": "openai", "supports_vision": False, "note": "deepseek-chat 是文本模型，不能用于图片反推。"},
    "kimi": {"label": "Kimi / Moonshot", "api_base": "https://api.moonshot.cn/v1", "model": "moonshot-v1-8k", "text_model": "moonshot-v1-8k", "vision_model": "", "mode": "openai", "supports_vision": False, "note": "当前预设为文本模型，图片反推请改用视觉模型。"},
    "glm": {"label": "智谱 GLM", "api_base": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4-flash", "text_model": "glm-4-flash", "vision_model": "glm-4v-flash", "mode": "openai", "supports_vision": True, "note": "图片反推请使用 GLM-4V 视觉模型。"},
    "doubao": {"label": "豆包 Doubao / Seed", "api_base": "https://ark.cn-beijing.volces.com/api/v3", "model": "doubao-seed-2-0-lite-260428", "text_model": "doubao-seed-2-0-lite-260428", "vision_model": "doubao-seed-2-0-lite-260428", "mode": "openai", "supports_vision": True, "note": "Seed 2.0 lite 是多模态理解模型，当前推荐模型名为 doubao-seed-2-0-lite-260428，并确认已在火山方舟开通。"},
    "hunyuan": {"label": "腾讯混元 Hunyuan", "api_base": "https://api.hunyuan.cloud.tencent.com/v1", "model": "hunyuan-turbos-latest", "text_model": "hunyuan-turbos-latest", "vision_model": "hunyuan-vision", "mode": "openai", "supports_vision": True, "note": "图片反推请使用混元视觉模型。"},
    "mimo": {"label": "小米 MiMo", "api_base": "https://api.xiaomimimo.com/v1", "model": "mimo-v2-pro", "text_model": "mimo-v2-pro", "vision_model": "", "mode": "openai", "supports_vision": False, "note": "当前预设为文本模型。"},
    "minimax": {"label": "MiniMax", "api_base": "https://api.minimax.io/v1", "model": "MiniMax-M2.5-highspeed", "text_model": "MiniMax-M2.5-highspeed", "vision_model": "", "mode": "openai", "supports_vision": False, "note": "当前预设为文本模型。"},
    "openai": {"label": "ChatGPT / OpenAI", "api_base": "https://api.openai.com/v1", "model": "gpt-4o-mini", "text_model": "gpt-4o-mini", "vision_model": "gpt-4o-mini", "mode": "openai", "supports_vision": True, "note": "图片反推可用 gpt-4o-mini / gpt-4.1-mini 等视觉模型。"},
    "claude": {"label": "Claude / Anthropic", "api_base": "https://api.anthropic.com/v1", "model": "claude-sonnet-4-5", "text_model": "claude-sonnet-4-5", "vision_model": "claude-sonnet-4-5", "mode": "anthropic", "supports_vision": True, "note": "Claude 支持图片输入。"},
    "google": {"label": "Gemini / Google", "api_base": "https://generativelanguage.googleapis.com/v1beta", "model": "gemini-2.5-flash", "text_model": "gemini-2.5-flash", "vision_model": "gemini-2.5-flash", "mode": "gemini", "supports_vision": True, "note": "Gemini Flash 可用于图片反推和文本翻译。"},
}
prompt_image_models = ["Nano banana", "gpt-image", "可灵", "即梦", "Flux", "Midjourney", "Stable Diffusion", "文心一言", "通义万相"]
default_prompt_gallery = [
    {
        "title": "未来城市雨夜",
        "category": "赛博朋克",
        "tags": ["城市", "夜景", "电影感"],
        "models": [],
        "gradient": "from-slate-950 via-violet-700 to-orange-500",
        "zh": "未来城市雨夜，霓虹灯反射在湿润街道上，远处高楼与全息广告牌，孤独行人撑伞穿过街口，电影级构图，低角度镜头，强烈明暗对比，超高细节，真实质感，8K。",
        "en": "futuristic rainy city night, neon reflections on wet streets, distant skyscrapers and holographic billboards, a lonely pedestrian crossing with an umbrella, cinematic composition, low angle shot, dramatic contrast, ultra detailed, realistic texture, 8k",
    },
    {
        "title": "东方庭院茶室",
        "category": "东方美学",
        "tags": ["庭院", "静物", "自然光"],
        "models": [],
        "gradient": "from-emerald-900 via-lime-700 to-amber-300",
        "zh": "安静的东方庭院茶室，木质窗棂，青苔石板，茶具置于低矮木桌上，晨光穿过竹影，空气中有细微尘埃，温润色调，极简构图，写实摄影，高级生活方式杂志风。",
        "en": "quiet oriental courtyard tea room, wooden lattice windows, mossy stone floor, tea set on a low wooden table, morning light through bamboo shadows, subtle dust in the air, warm tones, minimal composition, realistic photography, premium lifestyle magazine style",
    },
    {
        "title": "太空歌剧角色",
        "category": "角色设计",
        "tags": ["科幻", "人物", "盔甲"],
        "models": [],
        "gradient": "from-indigo-950 via-blue-700 to-cyan-400",
        "zh": "太空歌剧女指挥官角色设定，银白色轻型装甲，肩部发光徽章，背后是巨型星舰舷窗和星云，坚定眼神，半身像，细腻皮肤纹理，概念艺术，电影海报级光影。",
        "en": "space opera female commander character design, silver white lightweight armor, glowing shoulder emblem, giant starship window and nebula in the background, determined eyes, half body portrait, detailed skin texture, concept art, cinematic poster lighting",
    },
    {
        "title": "极简产品海报",
        "category": "商业视觉",
        "tags": ["产品", "海报", "极简"],
        "models": [],
        "gradient": "from-zinc-900 via-zinc-600 to-zinc-200",
        "zh": "极简高端产品海报，一只磨砂黑智能设备悬浮在柔和灰色背景中，边缘有精确高光，干净留白，工作室布光，商业广告摄影，奢侈科技品牌质感。",
        "en": "minimal premium product poster, a matte black smart device floating on a soft gray background, precise rim highlights, clean negative space, studio lighting, commercial advertising photography, luxury tech brand texture",
    },
    {
        "title": "童话森林小屋",
        "category": "插画",
        "tags": ["森林", "治愈", "童话"],
        "models": [],
        "gradient": "from-green-800 via-emerald-500 to-yellow-200",
        "zh": "童话森林里的温暖小屋，蘑菇、萤火虫和蜿蜒小路，窗户透出暖黄色灯光，柔软圆润的造型，细腻手绘质感，治愈系儿童绘本插画，高饱和但舒适。",
        "en": "warm cottage in a fairytale forest, mushrooms, fireflies and a winding path, warm yellow light from windows, soft rounded shapes, delicate hand drawn texture, healing children's picture book illustration, saturated yet comfortable colors",
    },
    {
        "title": "复古胶片街拍",
        "category": "摄影",
        "tags": ["街拍", "胶片", "复古"],
        "models": [],
        "gradient": "from-stone-800 via-orange-700 to-amber-200",
        "zh": "复古胶片街拍，一位穿风衣的人站在老街咖啡馆门口，午后阳光斜照，颗粒感胶片质感，浅景深，真实自然姿态，1970 年代杂志摄影风。",
        "en": "vintage film street photography, a person in a trench coat standing outside an old street cafe, afternoon sunlight slanting in, grainy film texture, shallow depth of field, natural pose, 1970s magazine photography style",
    },
]

for folder in (DOWNLOAD_DIR, IMAGE_DIR, TMP_DIR, COMPRESS_DIR, OFFICE_DIR, PAYMENT_DIR, PROMPT_IMAGE_DIR, SHOP_IMAGE_DIR, PLUGIN_IMAGE_DIR, AVATAR_DIR, POST_MEDIA_DIR):
    folder.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="meetseek AI Tools")
app.mount("/static", StaticFiles(directory=APP_ROOT / "static"), name="static")
templates = Jinja2Templates(directory=APP_ROOT / "templates")
setup_sqladmin(app, APP_DB_FILE)

tasks: dict[str, dict[str, Any]] = {}
reward_sessions: dict[str, dict[str, Any]] = {}
current_request_var: ContextVar[Request | None] = ContextVar("current_request", default=None)
video_semaphore = asyncio.Semaphore(MAX_VIDEO_JOBS)
prompt_gallery_lock = asyncio.Lock()
rate_buckets: dict[str, deque[float]] = defaultdict(deque)
event_logs: deque[dict[str, Any]] = deque(maxlen=200)
feature_flags = {
    "video": True,
    "image": True,
    "metadata": True,
    "compress": True,
    "office": True,
    "cover": True,
    "copy": True,
    "prompt": True,
}


@app.middleware("http")
async def store_current_request(request: Request, call_next):
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
    if forwarded_proto == "https" or request.headers.get("host", "").endswith("meetseek.ai"):
        request.scope["scheme"] = "https"
    token = current_request_var.set(request)
    try:
        return await call_next(request)
    finally:
        current_request_var.reset(token)


def default_content_security_policy() -> str:
    """Browser CSP for static HTML + Tailwind/Alpine CDNs + optional AdSense. Override with SECURITY_CSP."""
    custom = os.getenv("SECURITY_CSP", "").strip()
    if custom:
        return custom
    return "; ".join(
        [
            "default-src 'self'",
            "base-uri 'self'",
            "object-src 'none'",
            "frame-ancestors 'self'",
            "frame-src https://www.youtube.com https://www.youtube-nocookie.com https://googleads.g.doubleclick.net https://td.doubleclick.net",
            "img-src 'self' data: blob: https: http:",
            "font-src 'self' data: https:",
            "style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com",
            "connect-src 'self' https: wss:",
            "media-src 'self' blob: https: data:",
            "worker-src 'self' blob:",
            "manifest-src 'self'",
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.tailwindcss.com https://cdn.jsdelivr.net https://unpkg.com "
            "https://pagead2.googlesyndication.com https://www.googletagservices.com https://www.googletagmanager.com "
            "https://googleads.g.doubleclick.net https://securepubads.g.doubleclick.net "
            "https://ep1.adtrafficquality.google https://ep2.adtrafficquality.google",
            "upgrade-insecure-requests",
        ]
    )


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy",
        "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()",
    )
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    if (request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip() == "https"):
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if not request.url.path.startswith("/admin"):
        response.headers.setdefault("Content-Security-Policy", default_content_security_policy())
    return response


# Third-party ad embeds only (strip attacker-controlled <script> / <iframe> / event handlers).
ALLOWED_AD_SCRIPT_SRC_PREFIXES: tuple[str, ...] = (
    "https://pagead2.googlesyndication.com/",
    "https://www.googletagservices.com/",
    "https://www.googletagmanager.com/",
    "https://googleads.g.doubleclick.net/",
    "https://securepubads.g.doubleclick.net/",
    "https://ep1.adtrafficquality.google/",
    "https://ep2.adtrafficquality.google/",
)
ALLOWED_AD_IFRAME_SRC_PREFIXES: tuple[str, ...] = ALLOWED_AD_SCRIPT_SRC_PREFIXES + (
    "https://www.youtube.com/embed/",
    "https://www.youtube-nocookie.com/embed/",
)

ALLOWED_AD_HTML_TAGS = frozenset(
    {
        "a", "abbr", "b", "br", "div", "em", "i", "iframe", "img", "ins", "li", "noscript",
        "ol", "p", "script", "small", "span", "strong", "style", "sub", "sup", "table",
        "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
    }
)
ALLOWED_AD_HTML_ATTRS: dict[str, list[str]] = {
    "*": ["class", "id", "title", "style", "role", "align", "dir"],
    "a": ["href", "target", "rel"],
    "img": ["src", "alt", "width", "height", "loading", "srcset", "sizes", "decoding", "referrerpolicy"],
    "iframe": ["src", "width", "height", "frameborder", "allow", "allowfullscreen", "loading", "referrerpolicy", "title"],
    "ins": ["class", "style", "data-ad-client", "data-ad-slot", "data-ad-format", "data-ad-format-auto", "data-full-width-responsive", "data-adtest", "data-ad-channel"],
    "script": ["src", "async", "defer", "type", "crossorigin", "referrerpolicy", "charset", "nomodule"],
    "noscript": [],
}


def sanitize_ad_html_fragment(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    for tag in list(soup.find_all("script")):
        src = (tag.get("src") or "").strip()
        if not src or not any(src.startswith(p) for p in ALLOWED_AD_SCRIPT_SRC_PREFIXES):
            tag.decompose()
        elif tag.string and tag.string.strip():
            tag.clear()
    for tag in list(soup.find_all("iframe")):
        src = (tag.get("src") or "").strip()
        if not src or not any(src.startswith(p) for p in ALLOWED_AD_IFRAME_SRC_PREFIXES):
            tag.decompose()
    for el in soup.find_all(True):
        for name in list(el.attrs):
            if isinstance(name, str) and name.lower().startswith("on"):
                del el.attrs[name]
    fragment = soup.body.decode_contents() if soup.body else str(soup)
    return bleach.clean(
        fragment,
        tags=sorted(ALLOWED_AD_HTML_TAGS),
        attributes=ALLOWED_AD_HTML_ATTRS,
        protocols=["http", "https", "data"],
        strip=True,
    )[:50000]


default_ad_slots = {
    "top_banner": {"label": "顶部横幅", "enabled": False, "html": "", "note": "适合 Google 横幅广告或自建品牌横幅"},
    "after_cards": {"label": "工具卡片下方", "enabled": False, "html": "", "note": "适合工具入口下面的原生广告"},
    "after_video": {"label": "视频工具下方", "enabled": False, "html": "", "note": "适合视频下载结果附近"},
    "after_image": {"label": "图片工具下方", "enabled": False, "html": "", "note": "适合图片工具结果附近"},
    "ip_banner": {"label": "IP 检测页横幅", "enabled": False, "layout": "banner", "html": "", "note": "IP 分流检测页面顶部横幅广告位"},
    "ip_block_1": {"label": "IP 检测页豆腐块 1", "enabled": False, "layout": "banner", "html": "", "note": "IP 分流检测页面四宫格广告位第 1 个"},
    "ip_block_2": {"label": "IP 检测页豆腐块 2", "enabled": False, "layout": "banner", "html": "", "note": "IP 分流检测页面四宫格广告位第 2 个"},
    "ip_block_3": {"label": "IP 检测页豆腐块 3", "enabled": False, "layout": "banner", "html": "", "note": "IP 分流检测页面四宫格广告位第 3 个"},
    "ip_block_4": {"label": "IP 检测页豆腐块 4", "enabled": False, "layout": "banner", "html": "", "note": "IP 分流检测页面四宫格广告位第 4 个"},
    "footer": {"label": "底部广告位", "enabled": False, "html": "", "note": "适合低干扰广告"},
}
ad_layouts = {
    "banner": {"label": "1 个横幅", "count": 1},
    "split": {"label": "2 个小横幅", "count": 2},
    "grid4": {"label": "4 个豆腐块", "count": 4},
}


def normalize_ad_slot(slot: dict[str, Any]) -> dict[str, Any]:
    layout = slot.get("layout") if slot.get("layout") in ad_layouts else "banner"
    count = ad_layouts[layout]["count"]
    raw_items = slot.get("items") if isinstance(slot.get("items"), list) else []
    if not raw_items and slot.get("html"):
        raw_items = [{"html": slot.get("html", "")}]
    items = []
    for index in range(count):
        raw = raw_items[index] if index < len(raw_items) and isinstance(raw_items[index], dict) else {}
        items.append({"html": sanitize_ad_html_fragment(str(raw.get("html") or ""))})
    return {
        "label": slot.get("label", ""),
        "enabled": bool(slot.get("enabled")),
        "layout": layout,
        "items": items,
        "html": items[0]["html"] if items else "",
        "note": slot.get("note", ""),
    }


default_credit_rules = {
    "video_download": {"label": "万能视频下载", "type": "视频工具", "enabled": True, "cost": 5, "tiers": ["free", "pro", "vip"]},
    "video_batch": {"label": "批量视频下载（每条链接）", "type": "视频工具", "enabled": True, "cost": 5, "tiers": ["free", "pro", "vip"]},
    "cover_download": {"label": "短视频封面提取", "type": "视频工具", "enabled": True, "cost": 1, "tiers": ["free", "pro", "vip"]},
    "image_cleanup": {"label": "AI 图片去水印/修复", "type": "图片工具", "enabled": True, "cost": 8, "tiers": ["free", "pro", "vip"]},
    "image_prompt_reverse": {"label": "图片反推提示词", "type": "提示词", "enabled": True, "cost": 3, "tiers": ["free", "pro", "vip"]},
    "prompt_translate": {"label": "提示词中英互转", "type": "提示词", "enabled": True, "cost": 1, "tiers": ["free", "pro", "vip"]},
    "media_compress": {"label": "万能文件压缩", "type": "媒体处理", "enabled": True, "cost": 2, "tiers": ["free", "pro", "vip"]},
    "office_convert": {"label": "PDF/Office 万能转换", "type": "办公急救", "enabled": True, "cost": 3, "tiers": ["free", "pro", "vip"]},
    "copy_rewrite": {"label": "博主风格文案转换", "type": "文案工具", "enabled": True, "cost": 2, "tiers": ["free", "pro", "vip"]},
    "metadata_strip": {"label": "图片剥壳机", "type": "图片工具", "enabled": True, "cost": 1, "tiers": ["free", "pro", "vip"]},
    "social_card": {"label": "美化分享卡片", "type": "文案工具", "enabled": True, "cost": 1, "tiers": ["free", "pro", "vip"]},
    "nano_banana": {"label": "Nano banana", "type": "图像模型标签", "enabled": True, "cost": 8, "tiers": ["free", "pro", "vip"]},
    "gpt_image": {"label": "gpt-image", "type": "图像模型标签", "enabled": True, "cost": 12, "tiers": ["pro", "vip"]},
    "kling": {"label": "可灵", "type": "图像模型标签", "enabled": True, "cost": 10, "tiers": ["pro", "vip"]},
    "jimeng": {"label": "即梦", "type": "图像模型标签", "enabled": True, "cost": 10, "tiers": ["pro", "vip"]},
    "flux": {"label": "Flux", "type": "图像模型标签", "enabled": True, "cost": 8, "tiers": ["free", "pro", "vip"]},
    "midjourney": {"label": "Midjourney", "type": "图像模型标签", "enabled": True, "cost": 8, "tiers": ["free", "pro", "vip"]},
    "stable_diffusion": {"label": "Stable Diffusion", "type": "图像模型标签", "enabled": True, "cost": 6, "tiers": ["free", "pro", "vip"]},
    "ernie_image": {"label": "文心一言", "type": "图像模型标签", "enabled": True, "cost": 8, "tiers": ["free", "pro", "vip"]},
    "wanxiang": {"label": "通义万相", "type": "图像模型标签", "enabled": True, "cost": 8, "tiers": ["free", "pro", "vip"]},
}
default_usage_rules = {
    "video_info": {"label": "视频解析", "enabled": True, "guest_limit": 5, "free_limit": 30, "pro_limit": 300, "vip_limit": 1000},
    "video_download": {"label": "万能视频下载", "enabled": True, "guest_limit": 0, "free_limit": 10, "pro_limit": 80, "vip_limit": 300},
    "video_batch": {"label": "批量视频下载", "enabled": True, "guest_limit": 0, "free_limit": 5, "pro_limit": 30, "vip_limit": 100},
    "cover_info": {"label": "封面解析", "enabled": True, "guest_limit": 5, "free_limit": 30, "pro_limit": 300, "vip_limit": 1000},
    "cover_download": {"label": "短视频封面提取", "enabled": True, "guest_limit": 0, "free_limit": 20, "pro_limit": 200, "vip_limit": 600},
    "image_cleanup": {"label": "AI 图片去水印/修复", "enabled": True, "guest_limit": 0, "free_limit": 5, "pro_limit": 50, "vip_limit": 200},
    "image_prompt_reverse": {"label": "图片反推提示词", "enabled": True, "guest_limit": 0, "free_limit": 10, "pro_limit": 80, "vip_limit": 300},
    "prompt_translate": {"label": "提示词中英互转", "enabled": True, "guest_limit": 0, "free_limit": 30, "pro_limit": 300, "vip_limit": 1000},
    "media_compress": {"label": "万能文件压缩", "enabled": True, "guest_limit": 0, "free_limit": 20, "pro_limit": 120, "vip_limit": 500},
    "office_convert": {"label": "PDF/Office 万能转换", "enabled": True, "guest_limit": 0, "free_limit": 10, "pro_limit": 80, "vip_limit": 300},
    "copy_rewrite": {"label": "博主风格文案转换", "enabled": True, "guest_limit": 0, "free_limit": 15, "pro_limit": 200, "vip_limit": 600},
    "metadata_strip": {"label": "图片剥壳机", "enabled": True, "guest_limit": 0, "free_limit": 50, "pro_limit": 500, "vip_limit": 2000},
    "social_card": {"label": "美化分享卡片", "enabled": True, "guest_limit": 0, "free_limit": 30, "pro_limit": 300, "vip_limit": 1000},
}
default_payment_config = {
    "manual_enabled": True,
    "stripe_enabled": False,
    "stripe_secret_key": "",
    "stripe_webhook_secret": "",
    "stripe_currency": "usd",
    "stripe_success_url": "",
    "stripe_cancel_url": "",
    "xunhu_enabled": False,
    "xunhu_appid": "",
    "xunhu_appsecret": "",
    "xunhu_gateway": "https://api.xunhupay.com/payment/do.html",
    "xunhu_notify_url": "",
    "xunhu_return_url": "",
    "xunhu_callback_url": "",
    "wechat_qr": "",
    "alipay_qr": "",
    "instructions": "付款后提交订单号或截图，管理员审核后自动加积分。",
    "packages": [
        {"id": "points_100", "name": "100 积分", "points": 100, "amount": 9.9},
        {"id": "points_300", "name": "300 积分", "points": 300, "amount": 29.9},
        {"id": "points_1000", "name": "1000 积分", "points": 1000, "amount": 88.0},
    ],
}
default_reward_config = {
    "enabled": True,
    "seconds": 30,
    "points": 1,
    "daily_limit": 5,
    "title": "看广告赚积分",
    "description": "完整停留指定秒数后可以领取积分。接入广告代码后，这里会展示广告位。",
}
default_checkin_config = {
    "enabled": True,
    "points": 2,
    "streak_days": 7,
    "streak_bonus": 10,
    "title": "每日签到",
    "description": "每天签到可领取积分，连续签到满周期还有额外奖励。",
}
video_quality_options = {
    "4k": {"label": "4K", "height": 2160, "rank": 4},
    "2k": {"label": "2K", "height": 1440, "rank": 3},
    "1080p": {"label": "1080P", "height": 1080, "rank": 2},
    "720p": {"label": "720P", "height": 720, "rank": 1},
    "audio": {"label": "仅音频 MP3", "height": 0, "rank": 0},
}
default_video_config = {
    "max_quality": MAX_VIDEO_QUALITY if MAX_VIDEO_QUALITY in video_quality_options else "4k",
}
default_prompt_admin_emails = [email.strip().lower() for email in os.getenv("PROMPT_ADMIN_EMAILS", "").split(",") if email.strip()]
TOOLS_BASE_URL = "https://tools.meetseek.ai"
PROMPTS_BASE_URL = "https://prompts.meetseek.ai"
SHOP_BASE_URL = "https://shop.meetseek.ai"
default_link_card_config = {
    "whitelist": [
        "youtube.com",
        "www.youtube.com",
        "youtu.be",
        "mp.weixin.qq.com",
        "kanjianle.com",
        "www.kanjianle.com",
        "gainbrief.com",
        "www.gainbrief.com",
    ],
    "blacklist": [],
}


def normalize_domain_list(value: Any) -> list[str]:
    if isinstance(value, str):
        items = re.split(r"[\s,，]+", value)
    elif isinstance(value, list):
        items = value
    else:
        items = []
    domains = []
    for item in items:
        domain = str(item or "").strip().lower()
        domain = re.sub(r"^https?://", "", domain).split("/")[0].strip()
        if domain and re.match(r"^[a-z0-9.-]+$", domain) and domain not in domains:
            domains.append(domain)
    return domains


def load_settings() -> dict[str, Any]:
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    else:
        data = {}
    saved_ads = data.get("ads", {})
    ads = {
        key: normalize_ad_slot(default | saved_ads.get(key, {}))
        for key, default in default_ad_slots.items()
    }
    legacy_prompt_config = default_prompt_config | data.get("prompt_config", {})
    saved_ai_configs = data.get("ai_configs", {})
    ai_configs = {
        key: default | saved_ai_configs.get(key, {})
        for key, default in default_ai_configs.items()
    }
    if data.get("prompt_config") and not saved_ai_configs:
        legacy_provider = legacy_prompt_config.get("provider", "openai")
        legacy_preset = prompt_provider_presets.get(legacy_provider, prompt_provider_presets["openai"])
        migrated = {
            "provider": legacy_provider,
            "api_base": legacy_prompt_config.get("api_base", legacy_preset["api_base"]),
            "model": legacy_prompt_config.get("model", legacy_preset.get("text_model") or legacy_preset["model"]),
            "api_key": legacy_prompt_config.get("api_key", ""),
        }
        if legacy_preset.get("supports_vision"):
            ai_configs["image_prompt_reverse"] = ai_configs["image_prompt_reverse"] | migrated | {"skill": legacy_prompt_config.get("skill") or DEFAULT_PROMPT_SKILL}
        else:
            for key in ("prompt_translate", "copy_rewrite", "video_summary"):
                ai_configs[key] = ai_configs[key] | migrated
    saved_credit_rules = data.get("credit_rules", {})
    credit_rules = {
        key: default | saved_credit_rules.get(key, {})
        for key, default in default_credit_rules.items()
    }
    saved_usage_rules = data.get("usage_rules", {})
    usage_rules = {
        key: default | saved_usage_rules.get(key, {})
        for key, default in default_usage_rules.items()
    }
    payment_config = default_payment_config | data.get("payment_config", {})
    reward_config = default_reward_config | data.get("reward_config", {})
    checkin_config = default_checkin_config | data.get("checkin_config", {})
    video_config = default_video_config | data.get("video_config", {})
    if video_config.get("max_quality") not in video_quality_options:
        video_config["max_quality"] = default_video_config["max_quality"]
    prompt_admin_emails = data.get("prompt_admin_emails", default_prompt_admin_emails)
    saved_link_card_config = data.get("link_card_config", {})
    link_card_config = {
        "whitelist": normalize_domain_list(saved_link_card_config.get("whitelist", default_link_card_config["whitelist"])),
        "blacklist": normalize_domain_list(saved_link_card_config.get("blacklist", default_link_card_config["blacklist"])),
    }
    return {
        "ads": ads,
        "prompt_config": legacy_prompt_config,
        "ai_configs": ai_configs,
        "credit_rules": credit_rules,
        "usage_rules": usage_rules,
        "payment_config": payment_config,
        "reward_config": reward_config,
        "checkin_config": checkin_config,
        "video_config": video_config,
        "prompt_admin_emails": prompt_admin_emails,
        "link_card_config": link_card_config,
    }


def save_settings(settings: dict[str, Any]) -> None:
    SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


settings = load_settings()
CN_TZ = timezone(timedelta(hours=8))
SESSION_SECONDS = 60 * 60 * 24 * 30
ADMIN_SESSION_SECONDS = 60 * 60 * 12


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(APP_DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def ad_slot_to_config(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    keys = row.keys()
    raw_items: list[dict[str, Any]] = []
    items_json = str(row["items_json"] if "items_json" in keys else "")
    if items_json.strip():
        try:
            parsed = json.loads(items_json)
            if isinstance(parsed, list):
                raw_items = [item for item in parsed if isinstance(item, dict)]
        except json.JSONDecodeError:
            raw_items = []
    slot = {
        "label": str(row["label"] if "label" in keys else ""),
        "note": str(row["note"] if "note" in keys else ""),
        "enabled": bool(row["enabled"] if "enabled" in keys else False),
        "layout": str(row["layout"] if "layout" in keys else "banner"),
        "html": str(row["html"] if "html" in keys else ""),
        "items": raw_items,
    }
    return normalize_ad_slot(slot)


def ads_from_db(public_only: bool = False) -> dict[str, dict[str, Any]]:
    try:
        with db() as conn:
            rows = conn.execute("SELECT * FROM ad_slots ORDER BY slot").fetchall()
    except sqlite3.Error:
        rows = []
    ads = {
        key: normalize_ad_slot(default | ((settings.get("ads", {}) or {}).get(key, {}) if "settings" in globals() else {}))
        for key, default in default_ad_slots.items()
    }
    for row in rows:
        slot = str(row["slot"] or "")
        if not slot:
            continue
        ads[slot] = ad_slot_to_config(row)
        if not ads[slot].get("label"):
            ads[slot]["label"] = default_ad_slots.get(slot, {}).get("label", slot)
    if public_only:
        return {
            key: value
            for key, value in ads.items()
            if value.get("enabled") and any(item.get("html") for item in value.get("items", []))
        }
    return ads


def sync_default_ad_slots(conn: sqlite3.Connection) -> None:
    timestamp = int(now())
    saved_ads = settings.get("ads", {}) if "settings" in globals() else {}
    for slot, default in default_ad_slots.items():
        existing = conn.execute("SELECT slot FROM ad_slots WHERE slot = ?", (slot,)).fetchone()
        if existing:
            continue
        config = normalize_ad_slot(default | saved_ads.get(slot, {}))
        conn.execute(
            """
            INSERT INTO ad_slots(slot, label, note, enabled, layout, html, items_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                slot,
                config.get("label", default.get("label", slot)),
                config.get("note", default.get("note", "")),
                1 if config.get("enabled") else 0,
                config.get("layout", "banner"),
                config.get("html", ""),
                json.dumps(config.get("items", []), ensure_ascii=False),
                timestamp,
            ),
        )


def init_db() -> None:
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                tier TEXT NOT NULL DEFAULT 'free',
                points INTEGER NOT NULL DEFAULT 0,
                disabled INTEGER NOT NULL DEFAULT 0,
                posting_disabled INTEGER NOT NULL DEFAULT 0,
                muted_until INTEGER NOT NULL DEFAULT 0,
                deleted_at INTEGER NOT NULL DEFAULT 0,
                bio TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL
            )
            """
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "points" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN points INTEGER NOT NULL DEFAULT 0")
        if "disabled" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN disabled INTEGER NOT NULL DEFAULT 0")
        if "posting_disabled" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN posting_disabled INTEGER NOT NULL DEFAULT 0")
        if "muted_until" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN muted_until INTEGER NOT NULL DEFAULT 0")
        if "deleted_at" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN deleted_at INTEGER NOT NULL DEFAULT 0")
        if "avatar_url" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN avatar_url TEXT NOT NULL DEFAULT ''")
        if "nickname" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN nickname TEXT NOT NULL DEFAULT ''")
        if "hashed_password" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN hashed_password TEXT NOT NULL DEFAULT ''")
        if "bio" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN bio TEXT NOT NULL DEFAULT ''")
        if "phone" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN phone TEXT NOT NULL DEFAULT ''")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique ON users(email)")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_phone_unique ON users(phone) WHERE phone != ''")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS password_resets (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                used_at INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS usage_counts (
                day TEXT NOT NULL,
                identity TEXT NOT NULL,
                tool TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY(day, identity, tool)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS credit_orders (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                package_id TEXT NOT NULL,
                package_name TEXT NOT NULL,
                points INTEGER NOT NULL,
                amount REAL NOT NULL,
                method TEXT NOT NULL,
                transaction_no TEXT NOT NULL DEFAULT '',
                screenshot TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        order_columns = {row["name"] for row in conn.execute("PRAGMA table_info(credit_orders)").fetchall()}
        if "stripe_session_id" not in order_columns:
            conn.execute("ALTER TABLE credit_orders ADD COLUMN stripe_session_id TEXT NOT NULL DEFAULT ''")
        if "stripe_payment_intent_id" not in order_columns:
            conn.execute("ALTER TABLE credit_orders ADD COLUMN stripe_payment_intent_id TEXT NOT NULL DEFAULT ''")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stripe_events (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_checkins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                day TEXT NOT NULL,
                points INTEGER NOT NULL,
                streak INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                UNIQUE(user_id, day),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ad_slots (
                slot TEXT PRIMARY KEY,
                label TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 0,
                layout TEXT NOT NULL DEFAULT 'banner',
                html TEXT NOT NULL DEFAULT '',
                items_json TEXT NOT NULL DEFAULT '[]',
                updated_at INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        sync_default_ad_slots(conn)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                slug TEXT UNIQUE NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                seo_title TEXT NOT NULL DEFAULT '',
                seo_description TEXT NOT NULL DEFAULT '',
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                author_id INTEGER NOT NULL,
                type TEXT NOT NULL DEFAULT 'short',
                title TEXT NOT NULL,
                slug TEXT NOT NULL,
                category_slug TEXT NOT NULL DEFAULT 'ai',
                summary TEXT NOT NULL DEFAULT '',
                content_html TEXT NOT NULL DEFAULT '',
                content_json TEXT NOT NULL DEFAULT '',
                cover_image TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL DEFAULT '',
                link_previews_json TEXT NOT NULL DEFAULT '',
                visibility TEXT NOT NULL DEFAULT 'public',
                status TEXT NOT NULL DEFAULT 'draft',
                meta_title TEXT NOT NULL DEFAULT '',
                meta_description TEXT NOT NULL DEFAULT '',
                og_image TEXT NOT NULL DEFAULT '',
                canonical_url TEXT NOT NULL DEFAULT '',
                view_count INTEGER NOT NULL DEFAULT 0,
                comment_count INTEGER NOT NULL DEFAULT 0,
                like_count INTEGER NOT NULL DEFAULT 0,
                bookmark_count INTEGER NOT NULL DEFAULT 0,
                pinned_at INTEGER NOT NULL DEFAULT 0,
                recommended_at INTEGER NOT NULL DEFAULT 0,
                published_at INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                UNIQUE(category_slug, slug),
                FOREIGN KEY(author_id) REFERENCES users(id)
            )
            """
        )
        post_columns = {row["name"] for row in conn.execute("PRAGMA table_info(posts)").fetchall()}
        for column, definition in {
            "summary": "TEXT NOT NULL DEFAULT ''",
            "cover_image": "TEXT NOT NULL DEFAULT ''",
            "meta_title": "TEXT NOT NULL DEFAULT ''",
            "meta_description": "TEXT NOT NULL DEFAULT ''",
            "og_image": "TEXT NOT NULL DEFAULT ''",
            "canonical_url": "TEXT NOT NULL DEFAULT ''",
            "source_url": "TEXT NOT NULL DEFAULT ''",
            "link_previews_json": "TEXT NOT NULL DEFAULT ''",
            "content_json": "TEXT NOT NULL DEFAULT ''",
            "view_count": "INTEGER NOT NULL DEFAULT 0",
            "comment_count": "INTEGER NOT NULL DEFAULT 0",
            "like_count": "INTEGER NOT NULL DEFAULT 0",
            "bookmark_count": "INTEGER NOT NULL DEFAULT 0",
            "pinned_at": "INTEGER NOT NULL DEFAULT 0",
            "recommended_at": "INTEGER NOT NULL DEFAULT 0",
            "published_at": "INTEGER NOT NULL DEFAULT 0",
            "updated_at": "INTEGER NOT NULL DEFAULT 0",
        }.items():
            if column not in post_columns:
                conn.execute(f"ALTER TABLE posts ADD COLUMN {column} {definition}")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_public_slug ON posts(category_slug, slug, status, visibility)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_sitemap ON posts(status, visibility, updated_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_recommended ON posts(recommended_at, status, visibility)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS post_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                post_id INTEGER NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL,
                UNIQUE(user_id, post_id),
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(post_id) REFERENCES posts(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_post_preferences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                post_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                UNIQUE(user_id, post_id, kind),
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(post_id) REFERENCES posts(id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_user_post_preferences_user_kind ON user_post_preferences(user_id, kind)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_follows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                follower_id INTEGER NOT NULL,
                author_id INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                UNIQUE(follower_id, author_id),
                FOREIGN KEY(follower_id) REFERENCES users(id),
                FOREIGN KEY(author_id) REFERENCES users(id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_user_follows_follower ON user_follows(follower_id)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_blocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                author_id INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                UNIQUE(user_id, author_id),
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(author_id) REFERENCES users(id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_user_blocks_user ON user_blocks(user_id)")
        now_ts = int(now())
        for name, slug, description in [
            ("AI 工具", "ai-tools", "AI 工具、效率工具和自动化工作流。"),
            ("提示词", "prompts", "AI 绘图提示词、图片反推和创作案例。"),
            ("商业变现", "business", "AI 商业化、流量和产品增长。"),
            ("建站与 SEO", "build", "轻量社区、SEO 和产品架构。"),
        ]:
            conn.execute(
                "INSERT OR IGNORE INTO categories(name, slug, description, created_at) VALUES (?, ?, ?, ?)",
                (name, slug, description, now_ts),
            )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS prompts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_key TEXT UNIQUE NOT NULL,
                kind TEXT NOT NULL DEFAULT 'prompt',
                title TEXT NOT NULL,
                cover_image TEXT NOT NULL DEFAULT '',
                model_engine TEXT NOT NULL DEFAULT '',
                prompt_text TEXT NOT NULL DEFAULT '',
                negative_prompt TEXT NOT NULL DEFAULT '',
                author_id INTEGER,
                category_id INTEGER,
                category TEXT NOT NULL DEFAULT '未分类',
                tags TEXT NOT NULL DEFAULT '[]',
                models TEXT NOT NULL DEFAULT '[]',
                gradient TEXT NOT NULL DEFAULT 'from-slate-950 via-slate-700 to-orange-500',
                zh TEXT NOT NULL DEFAULT '',
                en TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                cta TEXT NOT NULL DEFAULT '查看详情',
                sort_order INTEGER NOT NULL DEFAULT 0,
                hidden INTEGER NOT NULL DEFAULT 0,
                is_featured INTEGER NOT NULL DEFAULT 0,
                client_nonce TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(author_id) REFERENCES users(id),
                FOREIGN KEY(category_id) REFERENCES categories(id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_prompts_visible_sort ON prompts(hidden, sort_order, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_prompts_title ON prompts(title)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_prompts_model_engine ON prompts(model_engine)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS favorites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                prompt_id INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                UNIQUE(user_id, prompt_id),
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(prompt_id) REFERENCES prompts(id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_favorites_user_created ON favorites(user_id, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_favorites_prompt ON favorites(prompt_id)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                target_id INTEGER NOT NULL,
                target_type TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_comments_target_created ON comments(target_type, target_id, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_comments_user_created ON comments(user_id, created_at)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS contact_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                inquiry_type TEXT NOT NULL DEFAULT 'contact',
                name TEXT NOT NULL DEFAULT '',
                company TEXT NOT NULL DEFAULT '',
                contact TEXT NOT NULL DEFAULT '',
                budget TEXT NOT NULL DEFAULT '',
                placement TEXT NOT NULL DEFAULT '',
                message TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'new',
                source_path TEXT NOT NULL DEFAULT '',
                ip_address TEXT NOT NULL DEFAULT '',
                user_agent TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_contact_submissions_type_created ON contact_submissions(inquiry_type, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_contact_submissions_status_created ON contact_submissions(status, created_at)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wechat_geo_articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL DEFAULT '',
                source_text TEXT NOT NULL DEFAULT '',
                context_note TEXT NOT NULL DEFAULT '',
                wechat_html TEXT NOT NULL DEFAULT '',
                ai_html TEXT NOT NULL DEFAULT '',
                clean_markdown TEXT NOT NULL DEFAULT '',
                chunk_json TEXT NOT NULL DEFAULT '[]',
                suggestions_json TEXT NOT NULL DEFAULT '[]',
                geo_score INTEGER NOT NULL DEFAULT 0,
                semantic_density INTEGER NOT NULL DEFAULT 0,
                noise_score INTEGER NOT NULL DEFAULT 0,
                token_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'draft',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_wechat_geo_articles_status ON wechat_geo_articles(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_wechat_geo_articles_created ON wechat_geo_articles(created_at)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS post_reactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                post_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                UNIQUE(user_id, post_id, kind),
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(post_id) REFERENCES posts(id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_post_reactions_post_kind ON post_reactions(post_id, kind)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_post_reactions_user_created ON post_reactions(user_id, created_at)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS shop_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                slug TEXT UNIQUE NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_shop_categories_enabled_sort ON shop_categories(enabled, sort_order, id)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS shop_products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER,
                title TEXT NOT NULL,
                slug TEXT UNIQUE NOT NULL,
                subtitle TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                cover_image TEXT NOT NULL DEFAULT '',
                gallery_images TEXT NOT NULL DEFAULT '',
                product_type TEXT NOT NULL DEFAULT 'physical',
                price_cents INTEGER NOT NULL DEFAULT 0,
                points_price INTEGER NOT NULL DEFAULT 0,
                stock INTEGER NOT NULL DEFAULT -1,
                status TEXT NOT NULL DEFAULT 'draft',
                fulfillment_note TEXT NOT NULL DEFAULT '',
                auto_delivery INTEGER NOT NULL DEFAULT 0,
                delivery_subject TEXT NOT NULL DEFAULT '',
                delivery_body TEXT NOT NULL DEFAULT '',
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                FOREIGN KEY(category_id) REFERENCES shop_categories(id)
            )
            """
        )
        shop_product_columns = {row["name"] for row in conn.execute("PRAGMA table_info(shop_products)").fetchall()}
        if "auto_delivery" not in shop_product_columns:
            conn.execute("ALTER TABLE shop_products ADD COLUMN auto_delivery INTEGER NOT NULL DEFAULT 0")
        if "gallery_images" not in shop_product_columns:
            conn.execute("ALTER TABLE shop_products ADD COLUMN gallery_images TEXT NOT NULL DEFAULT ''")
        if "delivery_subject" not in shop_product_columns:
            conn.execute("ALTER TABLE shop_products ADD COLUMN delivery_subject TEXT NOT NULL DEFAULT ''")
        if "delivery_body" not in shop_product_columns:
            conn.execute("ALTER TABLE shop_products ADD COLUMN delivery_body TEXT NOT NULL DEFAULT ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_shop_products_public_sort ON shop_products(status, sort_order, id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_shop_products_category ON shop_products(category_id, status)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS shop_orders (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                amount_cents INTEGER NOT NULL DEFAULT 0,
                points_amount INTEGER NOT NULL DEFAULT 0,
                payment_method TEXT NOT NULL DEFAULT 'manual',
                status TEXT NOT NULL DEFAULT 'pending',
                customer_note TEXT NOT NULL DEFAULT '',
                admin_note TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(product_id) REFERENCES shop_products(id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_shop_orders_user_created ON shop_orders(user_id, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_shop_orders_status_created ON shop_orders(status, created_at)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS plugins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT 'AI & ChatGPT',
                rating TEXT NOT NULL DEFAULT '4.7',
                users TEXT NOT NULL DEFAULT '',
                icon TEXT NOT NULL DEFAULT '◆',
                accent TEXT NOT NULL DEFAULT 'from-violet-600 to-blue-500',
                short_description TEXT NOT NULL DEFAULT '',
                long_description TEXT NOT NULL DEFAULT '',
                version TEXT NOT NULL DEFAULT '1.0.0',
                install_url TEXT NOT NULL DEFAULT '',
                chrome_store_url TEXT NOT NULL DEFAULT '',
                edge_store_url TEXT NOT NULL DEFAULT '',
                direct_url TEXT NOT NULL DEFAULT '',
                icon_url TEXT NOT NULL DEFAULT '',
                tags TEXT NOT NULL DEFAULT '',
                developer_name TEXT NOT NULL DEFAULT '',
                developer_email TEXT NOT NULL DEFAULT '',
                submitter_id INTEGER NOT NULL DEFAULT 0,
                review_note TEXT NOT NULL DEFAULT '',
                website_url TEXT NOT NULL DEFAULT '',
                support_url TEXT NOT NULL DEFAULT '',
                cover_image TEXT NOT NULL DEFAULT '',
                gallery_images TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'published',
                is_featured INTEGER NOT NULL DEFAULT 0,
                is_trending INTEGER NOT NULL DEFAULT 0,
                is_new INTEGER NOT NULL DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        plugin_columns = {row["name"] for row in conn.execute("PRAGMA table_info(plugins)").fetchall()}
        for column, definition in {
            "website_url": "TEXT NOT NULL DEFAULT ''",
            "support_url": "TEXT NOT NULL DEFAULT ''",
            "cover_image": "TEXT NOT NULL DEFAULT ''",
            "gallery_images": "TEXT NOT NULL DEFAULT ''",
            "short_description": "TEXT NOT NULL DEFAULT ''",
            "long_description": "TEXT NOT NULL DEFAULT ''",
            "version": "TEXT NOT NULL DEFAULT '1.0.0'",
            "install_url": "TEXT NOT NULL DEFAULT ''",
            "chrome_store_url": "TEXT NOT NULL DEFAULT ''",
            "edge_store_url": "TEXT NOT NULL DEFAULT ''",
            "direct_url": "TEXT NOT NULL DEFAULT ''",
            "icon_url": "TEXT NOT NULL DEFAULT ''",
            "tags": "TEXT NOT NULL DEFAULT ''",
            "developer_name": "TEXT NOT NULL DEFAULT ''",
            "developer_email": "TEXT NOT NULL DEFAULT ''",
            "submitter_id": "INTEGER NOT NULL DEFAULT 0",
            "review_note": "TEXT NOT NULL DEFAULT ''",
            "status": "TEXT NOT NULL DEFAULT 'published'",
            "is_featured": "INTEGER NOT NULL DEFAULT 0",
            "is_trending": "INTEGER NOT NULL DEFAULT 0",
            "is_new": "INTEGER NOT NULL DEFAULT 0",
            "sort_order": "INTEGER NOT NULL DEFAULT 0",
            "created_at": "INTEGER NOT NULL DEFAULT 0",
            "updated_at": "INTEGER NOT NULL DEFAULT 0",
        }.items():
            if column not in plugin_columns:
                conn.execute(f"ALTER TABLE plugins ADD COLUMN {column} {definition}")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_plugins_status_sort ON plugins(status, sort_order, id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_plugins_category ON plugins(category, status)")
        seed_default_plugins(conn)


def hash_password(password: str, salt: str | None = None) -> str:
    return hash_password_bcrypt(password)


def hash_password_legacy(password: str, salt: str) -> str:
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    if stored.startswith("$2"):
        return verify_password_bcrypt(password, stored)
    try:
        salt, expected = stored.split("$", 1)
    except ValueError:
        return False
    actual = hash_password_legacy(password, salt).split("$", 1)[1]
    return hmac.compare_digest(actual, expected)


def user_password_hash(row: sqlite3.Row | dict[str, Any]) -> str:
    keys = row.keys()
    hashed = str(row["hashed_password"] if "hashed_password" in keys else "")
    legacy = str(row["password_hash"] if "password_hash" in keys else "")
    return hashed or legacy


class MemberUserOut(BaseModel):
    email: str = Field(default="")
    name: str = Field(default="")
    tier: str = Field(default="free")
    points: int = Field(default=0)
    avatar_url: str = Field(default="")
    bio: str = Field(default="")
    phone: str = Field(default="")
    followers_count: int = Field(default=0)
    following_count: int = Field(default=0)
    total_likes: int = Field(default=0)
    is_prompt_admin: bool = Field(default=False)
    created_at: int = Field(default=0)


class PostActionPayload(BaseModel):
    action: str = Field(default="")


class ContactSubmissionPayload(BaseModel):
    inquiry_type: str = Field(default="contact", max_length=32)
    name: str = Field(default="", max_length=120)
    company: str = Field(default="", max_length=160)
    contact: str = Field(default="", max_length=180)
    budget: str = Field(default="", max_length=120)
    placement: str = Field(default="", max_length=160)
    message: str = Field(default="", max_length=3000)


class WechatGeoPayload(BaseModel):
    title: str = Field(default="", max_length=160)
    content: str = Field(default="", max_length=80_000)
    context_note: str = Field(default="", max_length=2000)


def api_public_user(user: dict[str, Any] | sqlite3.Row | None) -> dict[str, Any] | None:
    if not user:
        return None
    keys = user.keys() if isinstance(user, sqlite3.Row) else user.keys()
    email = str(user["email"] if "email" in keys else "")
    payload = MemberUserOut(
        email=email,
        name=str((user["nickname"] if "nickname" in keys and user["nickname"] else "") or (user["name"] if "name" in keys else "")),
        tier=str(user["tier"] if "tier" in keys else "free"),
        points=int(user["points"] if "points" in keys else 0),
        avatar_url=str(user["avatar_url"] if "avatar_url" in keys else ""),
        bio=str(user["bio"] if "bio" in keys else ""),
        phone=str(user["phone"] if "phone" in keys else ""),
        followers_count=int(user["followers_count"] if "followers_count" in keys else 0),
        following_count=int(user["following_count"] if "following_count" in keys else 0),
        total_likes=int(user["total_likes"] if "total_likes" in keys else 0),
        is_prompt_admin=email.lower() in {item.lower() for item in settings.get("prompt_admin_emails", [])},
        created_at=int(user["created_at"] if "created_at" in keys else 0),
    )
    return payload.model_dump()


def user_social_stats(conn: sqlite3.Connection, user_id: int) -> dict[str, int]:
    followers = conn.execute(
        "SELECT COUNT(*) AS count FROM user_follows WHERE author_id = ?",
        (user_id,),
    ).fetchone()
    following = conn.execute(
        "SELECT COUNT(*) AS count FROM user_follows WHERE follower_id = ?",
        (user_id,),
    ).fetchone()
    likes = conn.execute(
        """
        SELECT COUNT(post_reactions.id) AS count
        FROM post_reactions
        JOIN posts ON posts.id = post_reactions.post_id
        WHERE posts.author_id = ? AND post_reactions.kind = 'like'
        """,
        (user_id,),
    ).fetchone()
    return {
        "followers_count": int(followers["count"] or 0),
        "following_count": int(following["count"] or 0),
        "total_likes": int(likes["count"] or 0),
    }


def public_user_with_stats(row: sqlite3.Row | None, conn: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    user = public_user(row)
    if not user:
        return None
    if conn:
        user.update(user_social_stats(conn, int(user["id"])))
    else:
        with db() as stats_conn:
            user.update(user_social_stats(stats_conn, int(user["id"])))
    return user


def api_public_user_with_stats(row: sqlite3.Row | None, conn: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    user = public_user_with_stats(row, conn)
    return api_public_user(user)


def public_user(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if not row:
        return None
    email = row["email"]
    display_name = (row["nickname"] if "nickname" in row.keys() and row["nickname"] else "") or row["name"]
    is_prompt_admin = email.lower() in {item.lower() for item in settings.get("prompt_admin_emails", [])}
    return {
        "id": row["id"],
        "email": email,
        "name": display_name,
        "nickname": display_name,
        "tier": row["tier"],
        "points": row["points"] if "points" in row.keys() else 0,
        "avatar_url": row["avatar_url"] if "avatar_url" in row.keys() else "",
        "bio": row["bio"] if "bio" in row.keys() else "",
        "phone": row["phone"] if "phone" in row.keys() else "",
        "disabled": bool(row["disabled"]) if "disabled" in row.keys() else False,
        "posting_disabled": bool(row["posting_disabled"]) if "posting_disabled" in row.keys() else False,
        "muted_until": int(row["muted_until"]) if "muted_until" in row.keys() else 0,
        "deleted_at": row["deleted_at"] if "deleted_at" in row.keys() else 0,
        "is_prompt_admin": is_prompt_admin,
        "is_admin": is_prompt_admin,
        "created_at": row["created_at"],
    }


def is_site_admin(request: Request | None = None, user: dict[str, Any] | None = None) -> bool:
    return bool((user and user.get("is_admin")) or valid_admin_session(request))


def user_from_request(request: Request) -> dict[str, Any] | None:
    token = request.cookies.get("meetseek_session")
    if not token:
        return None
    jwt_payload = decode_access_token(token)
    if jwt_payload and str(jwt_payload.get("sub") or "").isdigit():
        with db() as conn:
            row = conn.execute(
                """
                SELECT * FROM users
                WHERE id = ? AND disabled = 0 AND deleted_at = 0
                """,
                (int(jwt_payload["sub"]),),
            ).fetchone()
        return public_user(row)
    with db() as conn:
        row = conn.execute(
            """
            SELECT users.* FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token = ? AND sessions.expires_at > ? AND users.disabled = 0 AND users.deleted_at = 0
            """,
            (token, int(now())),
        ).fetchone()
    return public_user(row)


def require_user(request: Request) -> dict[str, Any]:
    user = user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录后再使用")
    return user


def ensure_user_can_post(user: dict[str, Any]) -> None:
    if user.get("posting_disabled"):
        raise HTTPException(status_code=403, detail="该账号已被禁止发文")
    muted_until = int(user.get("muted_until") or 0)
    if muted_until and muted_until > int(now()):
        until = datetime.fromtimestamp(muted_until, CN_TZ).strftime("%Y-%m-%d %H:%M")
        raise HTTPException(status_code=403, detail=f"该账号已被禁言至 {until}")


def ensure_user_can_comment(user: dict[str, Any]) -> None:
    muted_until = int(user.get("muted_until") or 0)
    if muted_until and muted_until > int(now()):
        until = datetime.fromtimestamp(muted_until, CN_TZ).strftime("%Y-%m-%d %H:%M")
        raise HTTPException(status_code=403, detail=f"该账号已被禁言至 {until}")


def get_current_user(request: Request) -> dict[str, Any]:
    return require_user(request)


def require_prompt_admin(request: Request) -> dict[str, Any]:
    user = require_user(request)
    if not user.get("is_prompt_admin"):
        raise HTTPException(status_code=403, detail="只有提示词管理员可以修改图库")
    return user


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        "meetseek_session",
        token,
        max_age=SESSION_SECONDS,
        httponly=True,
        secure=True,
        samesite="lax",
        domain=COOKIE_DOMAIN,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie("meetseek_session", domain=COOKIE_DOMAIN)


def password_reset_link(token: str, request: Request | None = None) -> str:
    if request:
        scheme = request.headers.get("x-forwarded-proto") or request.url.scheme or "https"
        host = request.headers.get("host") or urlparse(PUBLIC_BASE_URL).netloc
        return f"{scheme}://{host}/reset-password?token={token}"
    return f"{PUBLIC_BASE_URL}/reset-password?token={token}"


def send_password_reset_email(email: str, link: str) -> bool:
    if not SMTP_HOST or not SMTP_FROM:
        return False
    message = EmailMessage()
    message["Subject"] = "meetseek 账号密码重置"
    message["From"] = SMTP_FROM
    message["To"] = email
    message.set_content(
        "\n".join(
            [
                "你正在重置 meetseek 会员账号密码。",
                "",
                f"请在 {PASSWORD_RESET_SECONDS // 60} 分钟内打开这个链接：",
                link,
                "",
                "如果不是你本人操作，可以忽略这封邮件。",
            ]
        )
    )
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
        if SMTP_TLS:
            server.starttls()
        if SMTP_USER:
            server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(message)
    return True


def send_plain_email(to_email: str, subject: str, body: str) -> bool:
    if not SMTP_HOST or not SMTP_FROM or not to_email:
        return False
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = SMTP_FROM
    message["To"] = to_email
    message.set_content(body)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
        if SMTP_TLS:
            server.starttls()
        if SMTP_USER:
            server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(message)
    return True


def send_shop_delivery_email(user: Mapping[str, Any], product: sqlite3.Row | Mapping[str, Any], order_id: str) -> bool:
    if str(product["product_type"] or "").lower() != "virtual":
        return False
    if int(product["auto_delivery"] or 0) != 1:
        return False
    delivery_body = str(product["delivery_body"] or "").strip()
    if not delivery_body:
        return False
    subject = str(product["delivery_subject"] or "").strip() or f"MeetSeek 商品交付：{product['title']}"
    body = "\n".join(
        [
            f"你好，{user.get('name') or 'MeetSeek 用户'}：",
            "",
            f"你的订单 {order_id} 已完成，以下是虚拟商品交付内容：",
            "",
            delivery_body,
            "",
            "如果你对订单有疑问，请联系 MeetSeek 管理员。",
        ]
    )
    return send_plain_email(str(user.get("email") or ""), subject, body)


def make_admin_session_token() -> str:
    timestamp = str(int(now()))
    signature = hmac.new(ADMIN_TOKEN.encode("utf-8"), timestamp.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{timestamp}.{signature}"


def valid_admin_session(request: Request | None) -> bool:
    if not request or not ADMIN_TOKEN:
        return False
    token = request.cookies.get("meetseek_admin")
    if not token or "." not in token:
        return False
    timestamp, signature = token.split(".", 1)
    if not timestamp.isdigit() or int(now()) - int(timestamp) > ADMIN_SESSION_SECONDS:
        return False
    expected = hmac.new(ADMIN_TOKEN.encode("utf-8"), timestamp.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def valid_sqladmin_session(request: Request | None) -> bool:
    if not request:
        return False
    try:
        return bool(request.session.get("sqladmin_authenticated"))
    except AssertionError:
        return False


def valid_any_admin_session(request: Request | None) -> bool:
    return valid_admin_session(request) or valid_sqladmin_session(request)


def set_admin_cookie(response: Response) -> None:
    response.set_cookie(
        "meetseek_admin",
        make_admin_session_token(),
        max_age=ADMIN_SESSION_SECONDS,
        httponly=True,
        secure=True,
        samesite="lax",
        domain=COOKIE_DOMAIN,
    )


def clear_admin_cookie(response: Response) -> None:
    response.delete_cookie("meetseek_admin", domain=COOKIE_DOMAIN)


def now() -> float:
    return time.time()


def today_key() -> str:
    return datetime.now(CN_TZ).strftime("%Y-%m-%d")


def yesterday_key() -> str:
    return (datetime.now(CN_TZ).date() - timedelta(days=1)).strftime("%Y-%m-%d")


def month_key() -> str:
    return datetime.now(CN_TZ).strftime("%Y-%m")


def load_visitor_stats() -> dict[str, Any]:
    if VISITOR_STATS_FILE.exists():
        try:
            return json.loads(VISITOR_STATS_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"total": 0, "days": {}, "months": {}, "recent": []}


def save_visitor_stats(stats: dict[str, Any]) -> None:
    VISITOR_STATS_FILE.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")


def visitor_id(request: Request) -> str:
    raw = f"{client_ip(request)}|{request.headers.get('user-agent', '')}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def track_visit(request: Request) -> None:
    stats = load_visitor_stats()
    day = today_key()
    month = month_key()
    visitor = visitor_id(request)
    stats["total"] = int(stats.get("total", 0)) + 1
    stats.setdefault("days", {}).setdefault(day, {"views": 0, "visitors": []})
    stats.setdefault("months", {}).setdefault(month, {"views": 0, "visitors": []})
    stats["days"][day]["views"] += 1
    stats["months"][month]["views"] += 1
    if visitor not in stats["days"][day]["visitors"]:
        stats["days"][day]["visitors"].append(visitor)
    if visitor not in stats["months"][month]["visitors"]:
        stats["months"][month]["visitors"].append(visitor)
    stats["recent"] = ([{"time": int(now()), "ip": client_ip(request), "path": str(request.url.path)}] + stats.get("recent", []))[:100]
    save_visitor_stats(stats)


def visitor_summary() -> dict[str, Any]:
    stats = load_visitor_stats()
    day = today_key()
    month = month_key()
    day_data = stats.get("days", {}).get(day, {"views": 0, "visitors": []})
    month_data = stats.get("months", {}).get(month, {"views": 0, "visitors": []})
    return {
        "today": {"views": day_data.get("views", 0), "visitors": len(day_data.get("visitors", []))},
        "month": {"key": month, "views": month_data.get("views", 0), "visitors": len(month_data.get("visitors", []))},
        "total": stats.get("total", 0),
        "recent": stats.get("recent", [])[:30],
    }


def public_task(task_id: str) -> dict[str, Any]:
    task = tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    return {
        "id": task_id,
        "type": task.get("type"),
        "status": task.get("status"),
        "title": task.get("title"),
        "thumbnail": task.get("thumbnail"),
        "message": task.get("message", ""),
        "progress": task.get("progress", 0),
        "speed": task.get("speed"),
        "eta": task.get("eta"),
        "size": task.get("size"),
        "quality": task.get("quality"),
        "attempt": task.get("attempt", 0),
        "credit_cost": task.get("credit_cost", 0),
        "credit_label": task.get("credit_label"),
        "download_url": task.get("download_url"),
        "created_at": task.get("created_at"),
    }


def log_event(level: str, message: str, **extra: Any) -> None:
    event_logs.appendleft({"time": int(now()), "level": level, "message": message, **extra})


def recent_password_resets() -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT password_resets.*, users.email, users.name
            FROM password_resets
            JOIN users ON users.id = password_resets.user_id
            ORDER BY password_resets.created_at DESC
            LIMIT 20
            """
        ).fetchall()
    return [
        {
            "email": row["email"],
            "name": row["name"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "used_at": row["used_at"],
            "reset_link": password_reset_link(row["token"]),
        }
        for row in rows
    ]


def credit_rule_for(key: str) -> dict[str, Any]:
    if key not in default_credit_rules:
        raise HTTPException(status_code=500, detail="积分规则未配置")
    return default_credit_rules[key] | settings.get("credit_rules", {}).get(key, {})


def usage_rule_for(key: str) -> dict[str, Any]:
    return default_usage_rules.get(key, {"label": key, "enabled": True, "guest_limit": 5, "free_limit": 20, "pro_limit": 200, "vip_limit": 1000}) | settings.get("usage_rules", {}).get(key, {})


def check_usage_limit(request: Request, key: str, units: int = 1) -> None:
    rule = usage_rule_for(key)
    if not rule.get("enabled", True):
        return
    user = user_from_request(request)
    tier = user["tier"] if user else "guest"
    limit = int(rule.get(f"{tier}_limit", rule.get("guest_limit", 5)))
    if limit < 0:
        return
    unit_count = max(1, int(units or 1))
    identity = f"user:{user['id']}" if user else f"guest:{client_ip(request)}"
    day = today_key()
    with db() as conn:
        row = conn.execute(
            "SELECT count FROM usage_counts WHERE day = ? AND identity = ? AND tool = ?",
            (day, identity, key),
        ).fetchone()
        current = row["count"] if row else 0
        if current + unit_count > limit:
            raise HTTPException(status_code=429, detail=f"{rule.get('label', key)} 今日次数已用完：上限 {limit} 次")
        conn.execute(
            """
            INSERT INTO usage_counts(day, identity, tool, count, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(day, identity, tool)
            DO UPDATE SET count = count + excluded.count, updated_at = excluded.updated_at
            """,
            (day, identity, key, unit_count, int(now())),
        )


def charge_points(request: Request, key: str, units: int = 1) -> dict[str, Any]:
    rule = credit_rule_for(key)
    label = rule.get("label", key)
    if not rule.get("enabled", True):
        raise HTTPException(status_code=403, detail=f"{label} 当前未开放")
    user = require_user(request)
    tiers = rule.get("tiers") or ["free", "pro", "vip"]
    if user.get("tier", "free") not in tiers:
        raise HTTPException(status_code=403, detail=f"{label} 仅限 {', '.join(tiers)} 会员使用")

    unit_count = max(1, int(units or 1))
    unit_cost = max(0, int(rule.get("cost", 0)))
    total_cost = unit_cost * unit_count
    if total_cost <= 0:
        return {"user": user, "cost": 0, "unit_cost": unit_cost, "rule": rule}

    with db() as conn:
        row = conn.execute("SELECT id, email, name, nickname, tier, points, avatar_url, bio, created_at FROM users WHERE id = ?", (user["id"],)).fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="请重新登录")
        if row["points"] < total_cost:
            raise HTTPException(status_code=402, detail=f"积分不足：{label} 需要 {total_cost} 分，当前只有 {row['points']} 分")
        conn.execute("UPDATE users SET points = points - ? WHERE id = ?", (total_cost, row["id"]))
        updated = conn.execute("SELECT id, email, name, nickname, tier, points, avatar_url, bio, created_at FROM users WHERE id = ?", (row["id"],)).fetchone()

    log_event("info", "积分扣除", user=user["email"], item=label, cost=total_cost, left=updated["points"])
    return {"user": public_user(updated), "cost": total_cost, "unit_cost": unit_cost, "rule": rule}


def refund_points(user_id: int | None, points: int, reason: str = "") -> None:
    if not user_id or points <= 0:
        return
    with db() as conn:
        conn.execute("UPDATE users SET points = points + ? WHERE id = ?", (points, user_id))
        row = conn.execute("SELECT email, points FROM users WHERE id = ?", (user_id,)).fetchone()
    log_event("info", "积分退回", user=row["email"] if row else user_id, points=points, reason=reason)


def refund_task_credit(task_id: str, reason: str) -> None:
    task = tasks.get(task_id)
    if not task or task.get("credit_refunded"):
        return
    points = int(task.get("credit_cost") or 0)
    if points <= 0:
        return
    refund_points(task.get("credit_user_id"), points, reason)
    task["credit_refunded"] = True
    task["message"] = f"{task.get('message', '任务失败')}，已退回 {points} 积分"


def raw_payment_config() -> dict[str, Any]:
    return default_payment_config | settings.get("payment_config", {})


def public_payment_config(admin: bool = False) -> dict[str, Any]:
    config = raw_payment_config()
    stripe_secret = str(config.get("stripe_secret_key") or "").strip()
    stripe_webhook_secret = str(config.get("stripe_webhook_secret") or "").strip()
    xunhu_appid = str(config.get("xunhu_appid") or "").strip()
    xunhu_appsecret = str(config.get("xunhu_appsecret") or "").strip()
    payload = {
        "manual_enabled": config.get("manual_enabled", True),
        "stripe_enabled": bool(config.get("stripe_enabled", False) and stripe_secret),
        "stripe_currency": str(config.get("stripe_currency") or "usd").lower(),
        "stripe_webhook_url": f"{PUBLIC_BASE_URL}/api/payment/stripe/webhook",
        "stripe_success_url": config.get("stripe_success_url") or "",
        "stripe_cancel_url": config.get("stripe_cancel_url") or "",
        "stripe_secret_configured": bool(stripe_secret),
        "stripe_webhook_secret_configured": bool(stripe_webhook_secret),
        "xunhu_enabled": bool(config.get("xunhu_enabled", False) and xunhu_appid and xunhu_appsecret),
        "xunhu_gateway": str(config.get("xunhu_gateway") or default_payment_config["xunhu_gateway"]),
        "xunhu_notify_url": config.get("xunhu_notify_url") or f"{PUBLIC_BASE_URL}/api/payment/xunhu/notify",
        "xunhu_return_url": config.get("xunhu_return_url") or stripe_default_success_url(),
        "xunhu_callback_url": config.get("xunhu_callback_url") or stripe_default_cancel_url(),
        "xunhu_appid": xunhu_appid,
        "xunhu_appid_configured": bool(xunhu_appid),
        "xunhu_appsecret_configured": bool(xunhu_appsecret),
        "wechat_qr": config.get("wechat_qr") or "",
        "alipay_qr": config.get("alipay_qr") or "",
        "instructions": config.get("instructions", default_payment_config["instructions"]),
        "packages": config.get("packages", default_payment_config["packages"]),
    }
    if admin:
        return payload
    secret_keys = {"stripe_secret_configured", "stripe_webhook_secret_configured", "xunhu_appid", "xunhu_appid_configured", "xunhu_appsecret_configured"}
    return {key: value for key, value in payload.items() if key not in secret_keys}


def public_reward_config() -> dict[str, Any]:
    config = default_reward_config | settings.get("reward_config", {})
    return {
        "enabled": bool(config.get("enabled", True)),
        "seconds": max(1, int(config.get("seconds", 30))),
        "points": max(0, int(config.get("points", 1))),
        "daily_limit": max(0, int(config.get("daily_limit", 5))),
        "title": config.get("title", default_reward_config["title"]),
        "description": config.get("description", default_reward_config["description"]),
    }


def public_checkin_config() -> dict[str, Any]:
    config = default_checkin_config | settings.get("checkin_config", {})
    return {
        "enabled": bool(config.get("enabled", True)),
        "points": max(0, int(config.get("points", default_checkin_config["points"]))),
        "streak_days": max(1, int(config.get("streak_days", default_checkin_config["streak_days"]))),
        "streak_bonus": max(0, int(config.get("streak_bonus", default_checkin_config["streak_bonus"]))),
        "title": config.get("title", default_checkin_config["title"]),
        "description": config.get("description", default_checkin_config["description"]),
    }


def load_prompt_gallery_overrides() -> dict[str, Any]:
    if not PROMPT_GALLERY_FILE.exists():
        return {}
    try:
        data = json.loads(PROMPT_GALLERY_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save_prompt_gallery_overrides(overrides: dict[str, Any]) -> None:
    PROMPT_GALLERY_FILE.write_text(json.dumps(overrides, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_prompt_tag_text(value: str) -> list[str]:
    for separator in ("，", "、", "/", "\n", "\t"):
        value = value.replace(separator, ",")
    return [tag.strip()[:24] for tag in value.split(",") if tag.strip()][:12]


def clean_prompt_models(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip() in prompt_image_models]


def clean_prompt_sort_order(value: Any) -> int:
    try:
        return max(0, min(999999, int(str(value or "0").strip() or 0)))
    except ValueError:
        return 0


def clean_prompt_timestamp(value: Any) -> int:
    try:
        return max(0, int(str(value or "0").strip() or 0))
    except ValueError:
        return 0


def clean_prompt_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def clean_prompt_client_nonce(value: Any) -> str:
    raw = str(value or "").strip()[:100]
    return "".join(char for char in raw if char.isalnum() or char in {"-", "_"})[:80]


def clean_prompt_item_id(value: Any) -> str:
    raw = str(value or "").strip()[:140]
    return "".join(char for char in raw if char.isalnum() or char in {"-", "_"})[:120]


def default_prompt_item_id(index: int) -> str:
    return f"default-{index}"


def new_custom_prompt_item_id() -> str:
    return f"custom-{uuid.uuid4().hex}"


def ensure_prompt_gallery_ids(overrides: dict[str, Any]) -> bool:
    changed = False
    custom_items = overrides.get(CUSTOM_PROMPT_GALLERY_KEY, [])
    if not isinstance(custom_items, list):
        return changed
    seen = {default_prompt_item_id(index) for index in range(len(default_prompt_gallery))}
    for item in custom_items:
        if not isinstance(item, dict):
            continue
        item_id = clean_prompt_item_id(item.get("id"))
        if not item_id or item_id in seen:
            item_id = new_custom_prompt_item_id()
            item["id"] = item_id
            changed = True
        elif item.get("id") != item_id:
            item["id"] = item_id
            changed = True
        seen.add(item_id)
    return changed


def clean_prompt_ad_url(value: str) -> str:
    clean = value.strip()[:2000]
    if not clean:
        return ""
    parsed = urlparse(clean)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="广告链接只支持 http 或 https")
    return clean


def clean_prompt_gallery_item(item: dict[str, Any], fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    fallback = fallback or {}
    kind = str(item.get("kind") or fallback.get("kind") or "prompt").strip().lower()
    if kind not in {"prompt", "ad"}:
        kind = "prompt"
    url = str(item.get("url") or fallback.get("url") or "").strip()[:2000]
    if url:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            url = ""
    cleaned = {
        "id": clean_prompt_item_id(item.get("id", fallback.get("id", ""))),
        "kind": kind,
        "title": str(item.get("title") or fallback.get("title") or "未命名提示词").strip()[:120] or "未命名提示词",
        "category": str(item.get("category") or fallback.get("category") or "未分类").strip()[:40] or "未分类",
        "tags": [str(tag).strip()[:24] for tag in item.get("tags", fallback.get("tags", [])) if str(tag).strip()][:12],
        "models": [model for model in item.get("models", fallback.get("models", [])) if model in prompt_image_models],
        "gradient": str(item.get("gradient") or fallback.get("gradient") or "from-slate-950 via-slate-700 to-orange-500"),
        "zh": str(item.get("zh") or fallback.get("zh") or "").strip()[:5000],
        "en": str(item.get("en") or fallback.get("en") or "").strip()[:5000],
        "description": str(item.get("description") or fallback.get("description") or "").strip()[:1000],
        "url": url,
        "cta": str(item.get("cta") or fallback.get("cta") or "查看详情").strip()[:24] or "查看详情",
        "sort_order": clean_prompt_sort_order(item.get("sort_order", fallback.get("sort_order", 0))),
        "created_at": clean_prompt_timestamp(item.get("created_at", fallback.get("created_at", 0))),
        "hidden": clean_prompt_bool(item.get("hidden", fallback.get("hidden", False))),
        "client_nonce": clean_prompt_client_nonce(item.get("client_nonce", fallback.get("client_nonce", ""))),
    }
    if item.get("image"):
        cleaned["image"] = str(item["image"])
    elif fallback.get("image"):
        cleaned["image"] = str(fallback["image"])
    return cleaned


def prompt_json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        parsed = []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def prompt_db_row_to_item(row: sqlite3.Row) -> dict[str, Any]:
    models = prompt_json_list(row["models"])
    tags = prompt_json_list(row["tags"])
    image = str(row["cover_image"] or "")
    item = {
        "id": str(row["item_key"] or row["id"]),
        "_index": int(row["id"]),
        "kind": str(row["kind"] or "prompt"),
        "title": str(row["title"] or "未命名提示词"),
        "category": str(row["category"] or "未分类"),
        "tags": tags,
        "models": models,
        "gradient": str(row["gradient"] or "from-slate-950 via-slate-700 to-orange-500"),
        "zh": str(row["zh"] or row["prompt_text"] or ""),
        "en": str(row["en"] or ""),
        "description": str(row["description"] or ""),
        "url": str(row["url"] or ""),
        "cta": str(row["cta"] or "查看详情"),
        "sort_order": int(row["sort_order"] or 0),
        "created_at": str(row["created_at"] or ""),
        "hidden": bool(row["hidden"]),
        "is_featured": bool(row["is_featured"]),
        "model_engine": str(row["model_engine"] or ", ".join(models)),
        "prompt_text": str(row["prompt_text"] or ""),
        "negative_prompt": str(row["negative_prompt"] or ""),
        "client_nonce": str(row["client_nonce"] or ""),
    }
    if image:
        item["image"] = image
    return item


def sql_like_pattern(value: str) -> str:
    escaped = value.replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def prompt_gallery_items(
    overrides: dict[str, Any] | None = None,
    save_missing_ids: bool = False,
    search: str = "",
    category: str = "",
    model_engine: str = "",
) -> list[dict[str, Any]]:
    clauses = ["hidden = 0"]
    params: list[Any] = []
    clean_search = search.strip()[:80]
    clean_category = category.strip()[:40]
    clean_model = model_engine.strip()[:80]
    if clean_search:
        pattern = sql_like_pattern(clean_search)
        clauses.append(
            """
            (
                title LIKE ? ESCAPE '\\'
                OR prompt_text LIKE ? ESCAPE '\\'
                OR zh LIKE ? ESCAPE '\\'
                OR en LIKE ? ESCAPE '\\'
                OR description LIKE ? ESCAPE '\\'
                OR tags LIKE ? ESCAPE '\\'
            )
            """
        )
        params.extend([pattern] * 6)
    if clean_category and clean_category != "全部":
        pattern = sql_like_pattern(clean_category)
        clauses.append("(category = ? OR tags LIKE ? ESCAPE '\\')")
        params.extend([clean_category, pattern])
    if clean_model and clean_model != "全部模型":
        clauses.append("(model_engine = ? OR models LIKE ? ESCAPE '\\')")
        params.extend([clean_model, sql_like_pattern(f'"{clean_model}"')])
    with db() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM prompts
            WHERE {" AND ".join(clauses)}
            ORDER BY sort_order DESC, created_at DESC, id DESC
            """,
            params,
        ).fetchall()
    return [prompt_db_row_to_item(row) for row in rows]


def prompt_gallery_item_at_index(index: int, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    if index < 0:
        raise HTTPException(status_code=404, detail="提示词不存在")
    with db() as conn:
        row = conn.execute("SELECT * FROM prompts WHERE id = ? AND hidden = 0", (index,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="提示词不存在")
    return prompt_db_row_to_item(row)


def prompt_gallery_index_for_id(item_id: str, overrides: dict[str, Any] | None = None) -> int:
    clean_id = clean_prompt_item_id(item_id)
    if not clean_id:
        raise HTTPException(status_code=404, detail="提示词不存在")
    with db() as conn:
        row = conn.execute(
            "SELECT id FROM prompts WHERE item_key = ? AND hidden = 0",
            (clean_id,),
        ).fetchone()
        if not row and clean_id.isdigit():
            row = conn.execute(
                "SELECT id FROM prompts WHERE id = ? AND hidden = 0",
                (int(clean_id),),
            ).fetchone()
    if row:
        return int(row["id"])
    raise HTTPException(status_code=404, detail="提示词不存在")


def delete_prompt_gallery_image_ref(image_url: str | None) -> None:
    if not image_url or not image_url.startswith("/api/prompts/images/"):
        return
    filename = Path(image_url).name
    (PROMPT_IMAGE_DIR / filename).unlink(missing_ok=True)


def public_host(request: Request) -> str:
    return request.headers.get("host", "").split(":", 1)[0].lower()


def public_base_for_host(host: str) -> str:
    if host == "prompts.meetseek.ai":
        return PROMPTS_BASE_URL
    if host == "tools.meetseek.ai":
        return TOOLS_BASE_URL
    if host == "shop.meetseek.ai":
        return SHOP_BASE_URL
    return MAIN_BASE_URL


def absolute_public_url(path_or_url: str, base_url: str) -> str:
    value = str(path_or_url or "").strip()
    if value.startswith(("http://", "https://")):
        return value
    if not value.startswith("/"):
        value = f"/{value}"
    return f"{base_url}{value}"


def html_escape(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def clean_plain_text(value: Any, limit: int = 1000) -> str:
    text = bleach.clean(str(value or ""), tags=[], attributes={}, strip=True)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def safe_json_ld(data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return f'<script type="application/ld+json">{payload}</script>'


ALLOWED_CONTENT_TAGS = [
    "a", "b", "blockquote", "br", "code", "em", "figcaption", "figure", "h2", "h3",
    "i", "img", "li", "ol", "p", "pre", "source", "strong", "ul", "video",
]
ALLOWED_CONTENT_ATTRS = {
    "*": ["class"],
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "loading", "width", "height"],
    "source": ["src", "type"],
    "video": ["src", "controls", "preload", "playsinline"],
}


def apply_ugc_link_attrs(content: str) -> str:
    soup = BeautifulSoup(content or "", "html.parser")
    policy = link_card_policy()
    for tag in soup.find_all("a"):
        href = str(tag.get("href") or "")
        host = urlparse(href).hostname or ""
        if host and domain_matches(host, policy["blacklist"]):
            tag.replace_with(tag.get_text(" ", strip=True) or href)
            continue
        if host and not host.endswith("meetseek.ai"):
            tag["rel"] = "nofollow ugc"
            tag["target"] = "_blank"
    for tag in soup.find_all("img"):
        tag["loading"] = "lazy"
        if not tag.get("alt"):
            tag["alt"] = ""
    for tag in soup.find_all("video"):
        tag["controls"] = ""
        tag["preload"] = "metadata"
        tag["playsinline"] = ""
    return str(soup)


def clean_user_html(content: str) -> str:
    cleaned = bleach.clean(
        content or "",
        tags=ALLOWED_CONTENT_TAGS,
        attributes=ALLOWED_CONTENT_ATTRS,
        protocols=["http", "https", "mailto"],
        strip=True,
    )
    return apply_ugc_link_attrs(cleaned)


YOUTUBE_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:youtube\.com/watch\?(?:[^\s<>'\"]*&)?v=|youtu\.be/)([A-Za-z0-9_-]{6,20})(?:[^\s<>'\"]*)?",
    re.IGNORECASE,
)
URL_RE = re.compile(r"https?://[^\s<>'\"]+", re.IGNORECASE)
LINK_CARD_DOMAINS = {
    "mp.weixin.qq.com": ("mp.weixin.qq.com", "微信文章"),
    "kanjianle.com": ("kanjianle.com", "kanjianle.com"),
    "www.kanjianle.com": ("kanjianle.com", "kanjianle.com"),
    "gainbrief.com": ("gainbrief.com", "gainbrief.com"),
    "www.gainbrief.com": ("gainbrief.com", "gainbrief.com"),
}
LINK_PREVIEW_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}


def domain_matches(host: str, domains: list[str]) -> bool:
    clean_host = (host or "").lower().strip(".")
    return any(clean_host == domain or clean_host.endswith(f".{domain}") for domain in domains)


def link_card_policy() -> dict[str, list[str]]:
    config = settings.get("link_card_config", default_link_card_config) if "settings" in globals() else default_link_card_config
    return {
        "whitelist": normalize_domain_list(config.get("whitelist", default_link_card_config["whitelist"])),
        "blacklist": normalize_domain_list(config.get("blacklist", [])),
    }


def is_link_card_allowed(host: str) -> bool:
    policy = link_card_policy()
    if domain_matches(host, policy["blacklist"]):
        return False
    return domain_matches(host, policy["whitelist"])


def trim_url_for_card(url: str, limit: int = 96) -> str:
    clean = re.sub(r"[?#].*$", "", url).rstrip("/")
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1] + "…"


def normalize_preview_image(image: str, page_url: str) -> str:
    clean = str(image or "").strip()
    if not clean:
        return ""
    if clean.startswith("//"):
        return f"{urlparse(page_url).scheme}:{clean}"
    if clean.startswith("/"):
        parsed = urlparse(page_url)
        return f"{parsed.scheme}://{parsed.netloc}{clean}"
    return clean if clean.startswith(("http://", "https://")) else ""


def is_low_value_preview_image(image: str) -> bool:
    clean = str(image or "").lower()
    return (
        not clean
        or "static.ghost.org" in clean and "publication-cover" in clean
        or clean.endswith("/favicon.ico")
    )


def image_from_srcset(srcset: str) -> str:
    candidates = [part.strip().split(" ", 1)[0] for part in str(srcset or "").split(",") if part.strip()]
    return candidates[-1] if candidates else ""


def image_from_tag(tag: Any, page_url: str) -> str:
    if not tag:
        return ""
    raw = str(tag.get("src") or "").strip() or image_from_srcset(str(tag.get("srcset") or ""))
    return normalize_preview_image(raw, page_url)


def image_from_jsonld(soup: BeautifulSoup, page_url: str) -> str:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or script.get_text() or "")
        except json.JSONDecodeError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop(0)
            if isinstance(item, list):
                stack.extend(item)
                continue
            if not isinstance(item, dict):
                continue
            image = item.get("image")
            if isinstance(image, str):
                normalized = normalize_preview_image(image, page_url)
                if normalized and not is_low_value_preview_image(normalized):
                    return normalized
            if isinstance(image, dict):
                normalized = normalize_preview_image(str(image.get("url") or ""), page_url)
                if normalized and not is_low_value_preview_image(normalized):
                    return normalized
            if isinstance(image, list):
                stack.extend(image)
            graph = item.get("@graph")
            if isinstance(graph, list):
                stack.extend(graph)
    return ""


def article_image_from_html(soup: BeautifulSoup, page_url: str) -> str:
    selectors = [
        "figure.kg-image-card img",
        "article figure img",
        "article img.kg-image",
        "article img",
        "main figure img",
        "main img",
    ]
    for selector in selectors:
        for tag in soup.select(selector):
            image = image_from_tag(tag, page_url)
            width = int(str(tag.get("width") or "0").split(".", 1)[0] or 0)
            height = int(str(tag.get("height") or "0").split(".", 1)[0] or 0)
            if image and not is_low_value_preview_image(image) and not (width and width < 240) and not (height and height < 160):
                return image
    return ""


def parse_link_preview_html(html_text: str, page_url: str) -> dict[str, str]:
    parsed = urlparse(page_url)
    host = (parsed.hostname or parsed.netloc or "").lower()
    domain = host.removeprefix("www.")
    soup = BeautifulSoup((html_text or "")[:500_000], "lxml")

    def meta_value(*names: str) -> str:
        for name in names:
            tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
            if tag and tag.get("content"):
                value = str(tag["content"]).strip()
                if value:
                    return value
        return ""

    title = meta_value("og:title", "twitter:title")
    if not title and soup.title and soup.title.string:
        title = str(soup.title.string).strip()
    if not title:
        title = domain or page_url
    description = meta_value("og:description", "description", "twitter:description")
    image = normalize_preview_image(meta_value("og:image", "twitter:image"), page_url)
    if is_low_value_preview_image(image):
        image = image_from_jsonld(soup, page_url) or article_image_from_html(soup, page_url)
    result = {
        "url": page_url,
        "domain": domain,
        "title": re.sub(r"\s+", " ", title).strip()[:180],
        "description": re.sub(r"\s+", " ", description).strip()[:280],
        "image": image,
    }
    print("[link_preview]", json.dumps(result, ensure_ascii=False), flush=True)
    return result


def extract_article_text_from_html(html_text: str, page_url: str) -> dict[str, str]:
    soup = BeautifulSoup((html_text or "")[:1_200_000], "lxml")
    for tag in soup(["script", "style", "noscript", "iframe", "svg", "form", "nav", "footer", "header", "aside"]):
        tag.decompose()
    for selector in [
        ".advertisement", ".ad", ".ads", ".share", ".social", ".related", ".recommend",
        ".sidebar", ".comments", ".comment", ".newsletter", ".subscribe", ".breadcrumb",
    ]:
        for tag in soup.select(selector):
            tag.decompose()

    def meta_value(*names: str) -> str:
        for name in names:
            tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
            if tag and tag.get("content"):
                value = str(tag["content"]).strip()
                if value:
                    return value
        return ""

    title = meta_value("og:title", "twitter:title")
    if not title and soup.title and soup.title.string:
        title = str(soup.title.string).strip()
    title = re.sub(r"\s+", " ", title or "").strip()

    candidates: list[Any] = []
    for selector in [
        "article", "main", "[role='main']", ".post-content", ".entry-content", ".article-content",
        ".article__content", ".article-body", ".post-body", ".story-body", ".gh-content",
        ".kg-card-markdown", ".content", ".main-content", "#content", "#main",
    ]:
        candidates.extend(soup.select(selector))
    if not candidates and soup.body:
        candidates = [soup.body]

    best_text = ""
    for node in candidates:
        text = node.get_text("\n", strip=True)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text).strip()
        paragraph_count = len([line for line in text.splitlines() if len(line.strip()) >= 20])
        score = len(text) + paragraph_count * 240
        best_score = len(best_text) + len([line for line in best_text.splitlines() if len(line.strip()) >= 20]) * 240
        if score > best_score:
            best_text = text
    paragraph_texts = [
        re.sub(r"\s+", " ", tag.get_text(" ", strip=True)).strip()
        for tag in soup.find_all(["p", "h2", "h3", "li"])
    ]
    paragraph_texts = [line for line in paragraph_texts if len(line) >= 24]
    paragraph_text = "\n\n".join(paragraph_texts)
    if len(paragraph_text) > max(len(best_text) * 0.7, 800):
        best_text = paragraph_text
    if not best_text:
        best_text = soup.get_text("\n", strip=True)
        best_text = re.sub(r"\n{3,}", "\n\n", best_text)
    return {
        "url": page_url,
        "title": title[:180],
        "content": best_text[:80_000],
    }


def extract_renderable_urls(text: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for match in URL_RE.finditer(text or ""):
        raw_url = match.group(0).rstrip(").,，。；;")
        host = (urlparse(raw_url).hostname or "").lower()
        if not host or raw_url in seen:
            continue
        if YOUTUBE_URL_RE.fullmatch(raw_url):
            continue
        if is_link_card_allowed(host):
            seen.add(raw_url)
            urls.append(raw_url)
    return urls


def fetch_link_preview_sync(url: str) -> dict[str, str] | None:
    try:
        clean = legal_url(url)
    except HTTPException as exc:
        log_event("error", "链接预览地址被拦截", url=str(url)[:180], error=str(exc.detail)[:160])
        return None
    host = (urlparse(clean).hostname or "").lower()
    if not is_link_card_allowed(host):
        return None
    try:
        with httpx.Client(timeout=5.0, follow_redirects=True, headers=LINK_PREVIEW_HEADERS) as client:
            response = client.get(clean)
            response.raise_for_status()
    except Exception as exc:
        log_event("error", "链接预览抓取失败", url=clean[:180], error=str(exc)[:160])
        return None
    return parse_link_preview_html(response.text, clean)


def build_link_previews_for_post(content: str, source_url: str = "") -> list[dict[str, str]]:
    raw_text = BeautifulSoup(content or "", "html.parser").get_text("\n")
    candidates = extract_renderable_urls(f"{raw_text}\n{source_url or ''}")
    previews: list[dict[str, str]] = []
    seen: set[str] = set()
    for url in candidates[:4]:
        if url in seen:
            continue
        seen.add(url)
        preview = fetch_link_preview_sync(url)
        if preview:
            previews.append(preview)
    return previews


def safe_link_previews(raw: str | None) -> list[dict[str, str]]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    previews: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        host = (urlparse(url).hostname or "").lower()
        if not url.startswith(("http://", "https://")) or not is_link_card_allowed(host):
            continue
        if YOUTUBE_URL_RE.fullmatch(url):
            continue
        previews.append({
            "url": url,
            "domain": str(item.get("domain") or host.removeprefix("www."))[:120],
            "title": str(item.get("title") or trim_url_for_card(url, 120))[:180],
            "description": str(item.get("description") or "")[:280],
            "image": str(item.get("image") or ""),
        })
    return previews[:4]


def render_rich_link_cards(previews: list[dict[str, str]]) -> str:
    cards: list[str] = []
    for preview in previews:
        url = html_escape(preview.get("url", ""))
        if not url:
            continue
        title = html_escape(preview.get("title") or preview.get("domain") or "链接预览")
        description = html_escape(preview.get("description", ""))
        domain = html_escape(preview.get("domain", ""))
        image = html_escape(preview.get("image", ""))
        image_html = (
            '<div class="h-32 w-full flex-shrink-0 overflow-hidden border-b border-slate-100 bg-slate-100 sm:h-40 sm:w-1/3 sm:border-b-0 sm:border-r">'
            f'<img src="{image}" alt="{title}" loading="lazy" class="h-full w-full object-cover object-top group-hover:scale-105 transition-transform duration-500">'
            '</div>'
            if image else ""
        )
        description_html = (
            f'<p class="mt-1 text-sm text-slate-500 line-clamp-2">{description}</p>'
            if description else ""
        )
        cards.append(
            f'<a href="{url}" target="_blank" rel="nofollow ugc" '
            'class="flex flex-col sm:flex-row overflow-hidden border border-slate-200 rounded-2xl hover:bg-slate-50 transition-colors mt-4 group bg-white">'
            f'{image_html}'
            '<div class="p-4 flex-1 flex flex-col justify-center">'
            f'<h3 class="font-bold text-slate-900 line-clamp-2 text-base">{title}</h3>'
            f'{description_html}'
            '<div class="mt-3 text-xs font-medium text-slate-400 uppercase flex items-center gap-1">'
            f'<span>{domain}</span>'
            '<svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M7 17 17 7"/><path d="M8 7h9v9"/></svg>'
            '</div></div></a>'
        )
    return "".join(cards)


def render_known_link_cards(text: str, previews: list[dict[str, str]] | None = None) -> str:
    seen: set[str] = set()
    cards: list[str] = []
    cards.append(render_rich_link_cards(previews or []))
    for preview in previews or []:
        if preview.get("url"):
            seen.add(str(preview["url"]))
    for match in YOUTUBE_URL_RE.finditer(text or ""):
        video_id = match.group(1)
        host = (urlparse(match.group(0)).hostname or "").lower()
        if not is_link_card_allowed(host):
            continue
        if video_id in seen:
            continue
        seen.add(video_id)
        embed_url = f"https://www.youtube.com/embed/{video_id}"
        cards.append(
            '<div class="mt-3 max-w-2xl overflow-hidden rounded-2xl border border-slate-100 bg-black shadow-sm">'
            f'<iframe src="{html_escape(embed_url)}" class="aspect-video w-full border-0" '
            'allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>'
            '</div>'
        )
    for match in URL_RE.finditer(text or ""):
        raw_url = match.group(0).rstrip(").,，。；;")
        host = (urlparse(raw_url).hostname or "").lower()
        if raw_url in seen:
            continue
        if not is_link_card_allowed(host) or host not in LINK_CARD_DOMAINS:
            continue
        seen.add(raw_url)
        title, label = LINK_CARD_DOMAINS[host]
        cards.append(
            f'<a href="{html_escape(raw_url)}" target="_blank" rel="nofollow ugc" '
            'class="my-3 block rounded-2xl border border-slate-100 bg-slate-50 p-4 shadow-sm transition hover:-translate-y-0.5 hover:border-slate-200 hover:bg-white hover:shadow-md">'
            '<div class="flex items-start justify-between gap-4">'
            '<div class="min-w-0">'
            f'<p class="text-xs font-black uppercase tracking-wide text-slate-400">{html_escape(label)}</p>'
            f'<h4 class="mt-2 text-base font-black leading-snug text-slate-950">{html_escape(title)}</h4>'
            f'<p class="mt-2 text-sm font-bold leading-6 text-slate-500">{html_escape((urlparse(raw_url).hostname or label).removeprefix("www."))}</p>'
            '</div>'
            '<span class="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-white text-lg shadow-sm">↗</span>'
            '</div>'
            '</a>'
        )
    return "".join(cards)


def url_should_be_hidden_after_card(url: str, preview_urls: set[str]) -> bool:
    clean = url.rstrip(").,，。；;")
    if clean in preview_urls:
        return True
    host = (urlparse(clean).hostname or "").lower()
    return is_link_card_allowed(host) and host in LINK_CARD_DOMAINS


def strip_rendered_link_urls(text: str, previews: list[dict[str, str]] | None = None) -> str:
    preview_urls = {str(item.get("url") or "") for item in previews or [] if item.get("url")}
    clean_text = YOUTUBE_URL_RE.sub("", text or "")
    clean_text = URL_RE.sub(
        lambda match: "" if url_should_be_hidden_after_card(match.group(0), preview_urls) else match.group(0),
        clean_text,
    )
    return re.sub(r"\n{3,}", "\n\n", html.unescape(clean_text)).strip()


def render_short_detail_content(content: str, previews: list[dict[str, str]] | None = None) -> str:
    raw_text = BeautifulSoup(content or "", "html.parser").get_text("\n")
    raw_text = html.unescape(raw_text)
    cards_html = render_known_link_cards(raw_text, previews)
    clean_text = strip_rendered_link_urls(raw_text, previews)
    text_html = (
        '<div class="content-box line-clamp-4 whitespace-pre-wrap text-slate-700 transition-all duration-300">'
        f"{html_escape(clean_text)}"
        "</div>"
        '<button class="expand-toggle-btn hidden text-orange-600 hover:text-orange-700 text-sm font-medium mt-2 transition-colors" type="button">展开全文</button>'
        if clean_text
        else ""
    )
    return f'<div class="space-y-5">{text_html}{cards_html}</div>'


def should_hide_card_summary(title: str, summary: str, item_type: str = "") -> bool:
    clean_title = re.sub(r"\s+", " ", (title or "")).strip()
    clean_summary = re.sub(r"\s+", " ", (summary or "")).strip()
    return not clean_summary or item_type == "short" or clean_title == clean_summary


def post_card_summary_html(row: sqlite3.Row) -> str:
    title = str(row["title"] or "")
    summary = str(row["summary"] or post_excerpt(row["content_html"], 120) or "")
    item_type = str(row["type"] or "")
    if should_hide_card_summary(title, summary, item_type):
        return ""
    return f'<p class="mt-2 line-clamp-2 text-sm leading-relaxed text-slate-500">{html_escape(summary)}</p>'


def account_post_card_html(row: sqlite3.Row) -> str:
    post = public_post(row)
    url = f'/{html_escape(str(post["category_slug"]))}/{html_escape(str(post["slug"]))}'
    title = html_escape(str(post["title"] or "未命名内容"))
    category = html_escape(str(post["category_slug"] or "ai-tools"))
    title_html = (
        f'<a class="text-lg font-black text-slate-950 hover:text-orange-600" href="{url}">{title}</a>'
        if str(post.get("type") or "") != "short"
        else ""
    )
    display_text = str(post.get("display_summary") or "")
    summary_html = (
        f'<p class="account-content-box {"mt-3 " if title_html else ""}line-clamp-4 whitespace-pre-wrap text-sm leading-relaxed text-slate-500 transition-all duration-300">{html_escape(display_text)}</p>'
        if display_text else ""
    )
    expand_button_html = (
        '<button class="account-expand-toggle hidden text-orange-600 hover:text-orange-700 text-sm font-medium mt-2 transition-colors" type="button">展开全文</button>'
        if display_text else ""
    )
    link_cards_html = str(post.get("link_cards_html") or "")
    return f"""
    <article class="rounded-3xl border border-slate-100 bg-white p-5 shadow-sm">
      {title_html}
      {summary_html}
      {expand_button_html}
      {link_cards_html}
      <div class="mt-4 flex items-center gap-4 text-xs font-bold text-slate-400">
        <span>{category}</span><span>{int(post["like_count"])} 赞</span><span>{int(post["comment_count"])} 评论</span>
      </div>
    </article>
    """


def editor_json_to_html(raw: str, title: str) -> str | None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    blocks = data.get("blocks")
    if not isinstance(blocks, list):
        return None
    return clean_user_html(parse_editorjs_blocks(blocks)["html"])


def parse_editorjs_raw(raw: str) -> dict[str, str] | None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    blocks = data.get("blocks")
    if not isinstance(blocks, list):
        return None
    parsed = parse_editorjs_blocks(blocks)
    parsed["html"] = clean_user_html(parsed.get("html", ""))
    return parsed


def title_to_slug(title: str, fallback: str = "post") -> str:
    text = unicodedata.normalize("NFKC", str(title or "").strip().lower())
    pieces: list[str] = []
    for char in text:
        if char.isascii() and char.isalnum():
            pieces.append(char)
        elif "\u4e00" <= char <= "\u9fff" and lazy_pinyin:
            pieces.append(f"-{lazy_pinyin(char, errors='ignore')[0]}-")
        elif char in {" ", "-", "_", "/", "·", "，", "。", "、", "：", "；", "！", "？", ".", ","}:
            pieces.append("-")
        else:
            pieces.append("-")
    slug = re.sub(r"[^a-z0-9]+", "-", "".join(pieces)).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return (slug or fallback)[:96].strip("-") or fallback


def unique_post_slug(conn: sqlite3.Connection, title: str, category_slug: str, post_id: int | None = None) -> str:
    base = title_to_slug(title)
    slug = base
    suffix = 2
    while True:
        if post_id:
            row = conn.execute(
                "SELECT id FROM posts WHERE category_slug = ? AND slug = ? AND id != ?",
                (category_slug, slug, post_id),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id FROM posts WHERE category_slug = ? AND slug = ?",
                (category_slug, slug),
            ).fetchone()
        if not row:
            return slug
        slug = f"{base}-{suffix}"
        suffix += 1


def post_excerpt(content: str, limit: int = 160) -> str:
    clean = re.sub(r"<[^>]+>", " ", str(content or ""))
    clean = re.sub(r"\s+", " ", html.unescape(clean)).strip()
    return clean[:limit]


def post_plain_text(content: str) -> str:
    soup = BeautifulSoup(content or "", "html.parser")
    text = soup.get_text("\n")
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def post_card_display_text(row: sqlite3.Row, link_previews: list[dict[str, str]]) -> str:
    if str(row["type"] or "") == "short":
        source_text = post_plain_text(row["content_html"] or row["summary"] or "")
    else:
        source_text = row["summary"] or post_excerpt(row["content_html"])
    return strip_rendered_link_urls(source_text, link_previews)


def public_post(row: sqlite3.Row) -> dict[str, Any]:
    canonical = row["canonical_url"] or f"{MAIN_BASE_URL}/{row['category_slug']}/{row['slug']}"
    parsed_editor = parse_editorjs_raw(row["content_html"] or "") if str(row["content_html"] or "").lstrip().startswith("{") else None
    rendered_content = parsed_editor["html"] if parsed_editor else apply_ugc_link_attrs(row["content_html"])
    image_url = row["og_image"] or row["cover_image"] or (parsed_editor or {}).get("seo_image", "")
    if image_url and not image_url.startswith(("http://", "https://")):
        image_url = absolute_public_url(image_url, MAIN_BASE_URL)
    published_at = row["published_at"] or row["created_at"]
    updated_at = row["updated_at"] or published_at
    link_previews = safe_link_previews(row["link_previews_json"] if "link_previews_json" in row.keys() else "")
    source_for_cards = row["content_html"] or row["summary"] or row["source_url"] or ""
    display_summary = post_card_display_text(row, link_previews)
    return {
        "id": row["id"],
        "author_id": row["author_id"],
        "type": row["type"],
        "title": row["title"],
        "slug": row["slug"],
        "category_slug": row["category_slug"],
        "summary": row["summary"],
        "display_summary": display_summary,
        "content_html": rendered_content,
        "link_previews": link_previews,
        "link_cards_html": "" if row["type"] not in {"short", "link", "tool"} else render_known_link_cards(source_for_cards, link_previews),
        "cover_image": row["cover_image"],
        "source_url": row["source_url"],
        "visibility": row["visibility"],
        "status": row["status"],
        "meta_title": row["meta_title"] or row["title"],
        "meta_description": (parsed_editor or {}).get("seo_description") or row["meta_description"] or row["summary"] or post_excerpt(row["content_html"]),
        "og_image": image_url,
        "canonical_url": canonical,
        "comment_count": int(row["comment_count"] if "comment_count" in row.keys() else 0),
        "like_count": int(row["like_count"] if "like_count" in row.keys() else 0),
        "bookmark_count": int(row["bookmark_count"] if "bookmark_count" in row.keys() else 0),
        "recommended_at": int(row["recommended_at"] if "recommended_at" in row.keys() else 0),
        "pinned_at": int(row["pinned_at"] if "pinned_at" in row.keys() else 0),
        "published_at": published_at,
        "updated_at": updated_at,
        "published_at_iso": datetime.fromtimestamp(published_at, timezone.utc).isoformat(),
        "updated_at_iso": datetime.fromtimestamp(updated_at, timezone.utc).isoformat(),
    }


MORE_MENU_ITEM_CLASS = "block w-full rounded-lg px-3 py-2 text-left text-sm font-bold text-slate-700 transition hover:bg-slate-50"
MORE_MENU_DANGER_CLASS = "block w-full rounded-lg px-3 py-2 text-left text-sm font-bold text-rose-600 transition hover:bg-rose-50"


def is_following_author(conn: sqlite3.Connection, follower_id: int | None, author_id: int | None) -> bool:
    if not follower_id or not author_id or follower_id == author_id:
        return False
    return bool(conn.execute(
        "SELECT id FROM user_follows WHERE follower_id = ? AND author_id = ?",
        (follower_id, author_id),
    ).fetchone())


def post_more_menu_html(
    *,
    post_id: int | None,
    author_id: int | None,
    post_url: str,
    current_user: dict[str, Any] | None,
    is_admin: bool,
    is_following: bool = False,
    is_recommended: bool = False,
) -> str:
    post_id_attr = int(post_id or 0)
    author_id_attr = int(author_id or 0)
    if not post_id:
        items = (
            f'<button class="{MORE_MENU_ITEM_CLASS} more-menu-action" type="button" data-menu-action="copy" data-url="{html_escape(post_url)}">复制链接</button>'
        )
    else:
        current_user_id = int(current_user.get("id") or 0) if current_user else 0
        is_author = bool(current_user_id and author_id_attr and current_user_id == author_id_attr)
        if is_admin:
            recommend_label = "取消推荐" if is_recommended else "推荐到首页"
            recommend_action = "unrecommend" if is_recommended else "recommend"
            items = "".join([
                f'<button class="{MORE_MENU_ITEM_CLASS} more-menu-action" type="button" data-menu-action="{recommend_action}" data-post-id="{post_id_attr}">{recommend_label}</button>',
                f'<button class="{MORE_MENU_ITEM_CLASS} more-menu-action" type="button" data-menu-action="pin" data-post-id="{post_id_attr}">置顶</button>',
                f'<button class="{MORE_MENU_ITEM_CLASS} more-menu-action" type="button" data-menu-action="hide" data-post-id="{post_id_attr}">隐藏内容</button>',
                f'<button class="{MORE_MENU_ITEM_CLASS} more-menu-action" type="button" data-menu-action="violation" data-post-id="{post_id_attr}">标记为违规</button>',
                f'<button class="{MORE_MENU_DANGER_CLASS} more-menu-action" type="button" data-menu-action="delete" data-post-id="{post_id_attr}">删除内容</button>',
                f'<button class="{MORE_MENU_DANGER_CLASS} more-menu-action" type="button" data-menu-action="ban_author" data-post-id="{post_id_attr}" data-author-id="{author_id_attr}">封禁作者</button>',
                f'<button class="{MORE_MENU_ITEM_CLASS} more-menu-action" type="button" data-menu-action="copy" data-url="{html_escape(post_url)}">复制链接</button>',
            ])
        elif is_author:
            items = "".join([
                f'<a class="{MORE_MENU_ITEM_CLASS}" href="/editor/posts/{post_id_attr}">编辑</a>',
                f'<button class="{MORE_MENU_ITEM_CLASS} more-menu-action" type="button" data-menu-action="pin" data-post-id="{post_id_attr}">置顶到个人主页</button>',
                f'<button class="{MORE_MENU_ITEM_CLASS} more-menu-action" type="button" data-menu-action="private" data-post-id="{post_id_attr}">设为仅自己可见</button>',
                f'<button class="{MORE_MENU_DANGER_CLASS} more-menu-action" type="button" data-menu-action="delete" data-post-id="{post_id_attr}">删除</button>',
                f'<button class="{MORE_MENU_ITEM_CLASS} more-menu-action" type="button" data-menu-action="copy" data-url="{html_escape(post_url)}">复制链接</button>',
            ])
        else:
            follow_label = "取消关注" if is_following else "关注"
            follow_attr = "true" if is_following else "false"
            items = "".join([
                f'<button class="{MORE_MENU_ITEM_CLASS} more-menu-action" type="button" data-menu-action="not_interested" data-post-id="{post_id_attr}">不感兴趣</button>',
                f'<button class="{MORE_MENU_ITEM_CLASS} more-menu-action" type="button" data-menu-action="hide" data-post-id="{post_id_attr}">隐藏这条内容</button>',
                f'<button class="{MORE_MENU_ITEM_CLASS} more-menu-action" type="button" data-menu-action="block_author" data-post-id="{post_id_attr}" data-author-id="{author_id_attr}">屏蔽该作者</button>',
                f'<button class="{MORE_MENU_ITEM_CLASS} more-menu-action" type="button" data-menu-action="report" data-post-id="{post_id_attr}">举报</button>',
                f'<button class="{MORE_MENU_ITEM_CLASS} more-menu-action" type="button" data-menu-action="bookmark" data-post-id="{post_id_attr}">收藏</button>',
                f'<button class="{MORE_MENU_ITEM_CLASS} more-menu-action" type="button" data-menu-action="follow" data-author-id="{author_id_attr}" data-following="{follow_attr}">{follow_label}</button>',
                f'<button class="{MORE_MENU_ITEM_CLASS} more-menu-action" type="button" data-menu-action="copy" data-url="{html_escape(post_url)}">复制链接</button>',
            ])
    return (
        '<div class="relative shrink-0">'
        '<button class="more-menu-toggle grid h-9 w-9 place-items-center rounded-full text-slate-400 transition hover:bg-slate-100 hover:text-slate-700" type="button" aria-label="更多操作">'
        '<svg class="h-5 w-5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="1.7"/><circle cx="12" cy="12" r="1.7"/><circle cx="19" cy="12" r="1.7"/></svg>'
        '</button>'
        '<div class="more-menu absolute right-0 top-10 z-50 hidden w-52 rounded-xl border border-slate-100 bg-white/90 p-2 shadow-lg backdrop-blur">'
        f'{items}'
        '</div>'
        '</div>'
    )


def home_feed_item_from_post(
    post: dict[str, Any],
    *,
    author_name: str,
    author_avatar_url: str = "",
    current_user: dict[str, Any] | None = None,
    is_admin: bool = False,
    is_following: bool = False,
) -> dict[str, Any]:
    item_type = {"short": "短文", "article": "长文", "tool": "工具", "prompt": "提示词", "link": "链接"}.get(str(post.get("type") or ""), "内容")
    read_source = str(post.get("summary") or post.get("content_html") or "")
    read_minutes = max(1, round(len(read_source) / 260))
    canonical_url = str(post.get("canonical_url") or "#")
    author_id = int(post.get("author_id") or 0)
    return {
        "id": int(post.get("id") or 0),
        "author_id": author_id,
        "post_type": post.get("type") or "",
        "type": item_type,
        "title": post.get("title") or "",
        "summary": post.get("display_summary") or post.get("summary") or post_excerpt(str(post.get("content_html") or "")),
        "href": canonical_url,
        "tag": post.get("category_slug") or "ai-tools",
        "meta": f"刚刚 · {read_minutes} 分钟阅读",
        "author": author_name or "meetseek",
        "author_avatar_url": author_avatar_url,
        "image": post.get("og_image") or "",
        "like_count": int(post.get("like_count") or 0),
        "comment_count": int(post.get("comment_count") or 0),
        "bookmark_count": int(post.get("bookmark_count") or 0),
        "link_cards_html": post.get("link_cards_html") or "",
        "link_previews": post.get("link_previews") or [],
        "more_menu_html": post_more_menu_html(
            post_id=int(post.get("id") or 0),
            author_id=author_id,
            post_url=canonical_url,
            current_user=current_user,
            is_admin=is_admin,
            is_following=is_following,
            is_recommended=bool(post.get("recommended_at")),
        ),
    }


def render_home_feed_card(
    item: dict[str, Any],
    *,
    current_user: dict[str, Any] | None = None,
    is_admin: bool = False,
) -> str:
    author = str(item.get("author") or "meetseek")
    avatar_letter = html_escape(author)[:1] or "M"
    author_avatar_url = str(item.get("author_avatar_url") or "").strip()
    author_avatar_html = (
        f'<img class="h-10 w-10 shrink-0 rounded-full object-cover ring-1 ring-slate-200" src="{html_escape(author_avatar_url)}" alt="{html_escape(author)}" loading="lazy">'
        if author_avatar_url else
        f'<span class="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-slate-950 text-sm font-black text-white">{avatar_letter}</span>'
    )
    image = str(item.get("image") or "").strip()
    raw_href = str(item.get("href") or "#")
    href = html_escape(raw_href)
    share_url = html_escape(raw_href)
    title = str(item.get("title") or "")
    summary = str(item.get("summary") or "")
    like_count = int(item.get("like_count") or 0)
    comment_count = int(item.get("comment_count") or 0)
    bookmark_count = int(item.get("bookmark_count") or 0)
    post_id = int(item.get("id") or 0)
    author_id = int(item.get("author_id") or 0)
    category_slug = str(item.get("tag") or "ai-tools")
    more_menu_html = str(item.get("more_menu_html") or post_more_menu_html(
        post_id=post_id or None,
        author_id=author_id or None,
        post_url=raw_href,
        current_user=current_user,
        is_admin=is_admin,
    ))
    link_cards_html = str(item.get("link_cards_html") or render_known_link_cards(summary))
    grid_class = "grid gap-4 sm:grid-cols-[minmax(0,1fr)_auto]" if image else "grid gap-4"
    title_html = ""
    if item.get("type") != "短文":
        title_html = (
            f'<a href="{href}">'
            f'<h3 class="mt-3 text-xl font-black leading-snug text-slate-950 hover:text-orange-600">{html_escape(title)}</h3>'
            "</a>"
        )
    image_html = (
        f'<a class="block overflow-hidden rounded-xl bg-slate-100" href="{href}">'
        f'<img class="h-32 w-32 rounded-xl object-cover" src="{html_escape(image)}" alt="{html_escape(title)}" loading="lazy">'
        "</a>"
        if image else ""
    )
    return (
        '<article class="rounded-2xl border border-slate-100 bg-white p-5 shadow-sm transition-shadow hover:shadow-md">'
        f'<div class="{grid_class}">'
        '<div class="min-w-0">'
        '<div class="flex items-start justify-between gap-3">'
        '<div class="flex min-w-0 items-center gap-3">'
        f'<a href="/account" class="block shrink-0">{author_avatar_html}</a>'
        '<div class="min-w-0">'
        f'<a class="block truncate text-sm font-black text-slate-950 hover:text-orange-600" href="/account">{html_escape(author)}</a>'
        f'<p class="mt-0.5 truncate text-xs font-bold text-slate-400">{html_escape(str(item.get("meta") or ""))}</p>'
        "</div>"
        "</div>"
        f"{more_menu_html}"
        "</div>"
        f"{title_html}"
        f'<p class="post-content-text content-box mt-3 line-clamp-4 max-w-3xl whitespace-pre-wrap text-[15px] leading-7 text-slate-600 transition-all duration-300">{html_escape(summary)}</p>'
        '<button class="expand-toggle-btn hidden text-orange-600 hover:text-orange-700 text-sm font-medium mt-2 transition-colors" type="button">展开全文</button>'
        f"{link_cards_html}"
        '<div class="mt-4 flex items-center justify-between border-t border-slate-100 pt-4 text-sm text-slate-500">'
        '<div class="flex items-center gap-6">'
        f'<button class="btn-inline-comment flex items-center gap-1.5 transition-colors hover:text-emerald-600 disabled:cursor-not-allowed disabled:opacity-50" type="button" data-post-id="{post_id}" aria-label="评论" {"disabled" if not post_id else ""}>'
        '<svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M21 12a8.5 8.5 0 0 1-8.5 8.5H5l-2 2v-7.5A8.5 8.5 0 1 1 21 12Z"/></svg>'
        f'<span>评论 <span data-comment-count-label="{post_id}">{comment_count}</span></span>'
        "</button>"
        f'<button class="btn-like flex items-center gap-1.5 transition-colors hover:text-emerald-600 disabled:cursor-not-allowed disabled:opacity-50" type="button" aria-label="点赞" data-post-id="{post_id}" data-count="{like_count}" {"disabled" if not post_id else ""}>'
        '<svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.6l-1-1a5.5 5.5 0 1 0-7.8 7.8l1 1L12 21l7.8-7.6 1-1a5.5 5.5 0 0 0 0-7.8Z"/></svg>'
        f'<span>点赞 <span data-count-label>{like_count}</span></span>'
        "</button>"
        f'<button class="btn-bookmark flex items-center gap-1.5 transition-colors hover:text-orange-500 disabled:cursor-not-allowed disabled:opacity-50" type="button" aria-label="收藏" data-post-id="{post_id}" data-count="{bookmark_count}" {"disabled" if not post_id else ""}>'
        '<svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M6 3h12a1 1 0 0 1 1 1v17l-7-4-7 4V4a1 1 0 0 1 1-1Z"/></svg>'
        f'<span>收藏 <span data-count-label>{bookmark_count}</span></span>'
        "</button>"
        f'<button class="btn-share flex items-center gap-1.5 transition-colors hover:text-emerald-600" type="button" aria-label="分享" data-url="{share_url}">'
        '<svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M4 12v7a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-7"/><path d="M12 16V3"/><path d="m7 8 5-5 5 5"/></svg>'
        '<span>分享</span>'
        "</button>"
        "</div>"
        f'<a class="rounded-md bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-200" href="/?category={quote(category_slug)}">{html_escape(category_slug)}</a>'
        "</div>"
        f'<div class="mt-4 hidden rounded-2xl border border-slate-100 bg-white/80 p-4" data-inline-comments="{post_id}">'
        f'<form class="grid gap-3" data-inline-comment-form data-post-id="{post_id}">'
        '<textarea class="min-h-20 w-full resize-y rounded-2xl border border-slate-200 bg-slate-50 p-3 text-sm leading-6 text-slate-700 outline-none transition focus:border-orange-300 focus:bg-white focus:ring-4 focus:ring-orange-50" placeholder="写下你的评论..."></textarea>'
        '<div class="flex items-center justify-between">'
        '<span class="text-xs font-bold text-slate-400" data-inline-comment-status></span>'
        '<button class="rounded-xl bg-slate-950 px-4 py-2 text-sm font-black text-white transition hover:bg-orange-600" type="submit" data-inline-comment-submit>发送</button>'
        "</div>"
        "</form>"
        '<div class="mt-4 grid gap-3" data-inline-comment-list></div>'
        "</div>"
        "</div>"
        f"{image_html}"
        "</div>"
        "</article>"
    )


def save_post_record(
    conn: sqlite3.Connection,
    *,
    author_id: int,
    title: str,
    content_html: str,
    post_type: str = "short",
    category_slug: str = "ai-tools",
    summary: str = "",
    cover_image: str = "",
    source_url: str = "",
    status: str = "published",
    visibility: str = "public",
    post_id: int | None = None,
) -> sqlite3.Row:
    clean_title = title.strip()[:180]
    if len(clean_title) < 2:
        raise HTTPException(status_code=400, detail="标题至少 2 个字")
    if post_type not in {"short", "article", "tool", "prompt", "link"}:
        raise HTTPException(status_code=400, detail="未知内容类型")
    if visibility not in {"public", "members", "private"}:
        raise HTTPException(status_code=400, detail="未知可见范围")
    if status not in {"draft", "published", "pending", "hidden"}:
        raise HTTPException(status_code=400, detail="未知发布状态")
    category = conn.execute("SELECT slug FROM categories WHERE slug = ?", (category_slug,)).fetchone()
    if not category:
        category_slug = "ai-tools"
    slug = unique_post_slug(conn, clean_title, category_slug, post_id)
    raw_content = content_html.strip()
    editor_data = parse_editorjs_raw(raw_content) if raw_content.startswith("{") else None
    if editor_data is not None:
        clean_content = raw_content
    elif "<" in raw_content and ">" in raw_content:
        clean_content = clean_user_html(raw_content)
    else:
        clean_content = clean_user_html(html.escape(raw_content).replace("\n", "<br>"))
    clean_summary = (summary.strip() or (editor_data or {}).get("seo_description", "") or post_excerpt(clean_content))[:240]
    meta_title = clean_title[:70]
    meta_description = clean_summary[:160]
    og_image = cover_image.strip() or (editor_data or {}).get("seo_image", "")
    link_previews = build_link_previews_for_post(clean_content, source_url) if post_type in {"short", "link", "tool"} else []
    link_previews_json = json.dumps(link_previews, ensure_ascii=False, separators=(",", ":")) if link_previews else ""
    timestamp = int(now())
    published_at = timestamp if status == "published" else 0
    canonical_url = f"{MAIN_BASE_URL}/{category_slug}/{slug}" if status == "published" and visibility == "public" else ""
    if post_id:
        conn.execute(
            """
            UPDATE posts
            SET type = ?, title = ?, slug = ?, category_slug = ?, summary = ?, content_html = ?,
                cover_image = ?, source_url = ?, visibility = ?, status = ?, meta_title = ?,
                meta_description = ?, og_image = ?, canonical_url = ?, published_at = CASE WHEN ? = 'published' AND published_at = 0 THEN ? ELSE published_at END,
                link_previews_json = ?, updated_at = ?
            WHERE id = ? AND author_id = ?
            """,
            (
                post_type,
                clean_title,
                slug,
                category_slug,
                clean_summary,
                clean_content,
                cover_image.strip(),
                source_url.strip(),
                visibility,
                status,
                meta_title,
                meta_description,
                og_image,
                canonical_url,
                status,
                published_at,
                link_previews_json,
                timestamp,
                post_id,
                author_id,
            ),
        )
        row = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    else:
        cur = conn.execute(
            """
            INSERT INTO posts(
                author_id, type, title, slug, category_slug, summary, content_html, cover_image,
                source_url, visibility, status, meta_title, meta_description, og_image,
                canonical_url, link_previews_json, published_at, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                author_id,
                post_type,
                clean_title,
                slug,
                category_slug,
                clean_summary,
                clean_content,
                cover_image.strip(),
                source_url.strip(),
                visibility,
                status,
                meta_title,
                meta_description,
                og_image,
                canonical_url,
                link_previews_json,
                published_at,
                timestamp,
                timestamp,
            ),
        )
        row = conn.execute("SELECT * FROM posts WHERE id = ?", (cur.lastrowid,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="帖子不存在")
    return row


def main_sitemap_urls(today: str) -> list[str]:
    urls = [
        sitemap_url(f"{MAIN_BASE_URL}/", today, "daily", "1.0"),
        sitemap_url(f"{MAIN_BASE_URL}/account", today, "weekly", "0.5"),
        sitemap_url(TOOLS_BASE_URL + "/", today, "weekly", "0.8"),
        sitemap_url(PROMPTS_BASE_URL + "/", today, "daily", "0.8"),
        sitemap_url(PROMPTS_BASE_URL + "/reverse", today, "weekly", "0.7"),
        sitemap_url(SHOP_BASE_URL + "/", today, "weekly", "0.6"),
    ]
    with db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM posts
            WHERE status = 'published' AND visibility = 'public'
            ORDER BY updated_at DESC
            LIMIT 5000
            """
        ).fetchall()
    for row in rows:
        post = public_post(row)
        lastmod = datetime.fromtimestamp(post["updated_at"] or post["published_at"] or int(now()), timezone.utc).date().isoformat()
        urls.append(
            sitemap_url(
                post["canonical_url"],
                lastmod,
                "weekly",
                "0.7",
                image=post["og_image"],
                image_title=post["title"],
            )
        )
    return urls


def spotlight_search_markup() -> str:
    return """
  <button type="button" data-search-trigger onclick="openSearch()" class="fixed bottom-5 right-5 z-40 inline-flex items-center gap-2 rounded-full bg-slate-950 px-4 py-3 text-sm font-black text-white shadow-xl transition hover:bg-orange-600 md:hidden">
    <span>🔍</span><span>搜索</span>
  </button>
  <div id="global-search-modal" class="fixed inset-0 z-50 hidden items-start justify-center bg-slate-900/40 px-4 pt-24 backdrop-blur-sm">
    <div class="w-full max-w-2xl overflow-hidden rounded-2xl bg-white shadow-2xl">
      <div class="flex items-center gap-3 border-b border-slate-100 px-5 py-4">
        <span class="text-xl text-slate-400">🔍</span>
        <input id="searchInput" type="search" autocomplete="off" placeholder="搜索内容与工具..." class="w-full border-none bg-transparent text-lg font-bold text-slate-900 placeholder:text-slate-300 outline-none focus:ring-0">
        <button type="button" onclick="closeSearch()" class="rounded-lg px-2 py-1 text-xs font-black text-slate-400 transition hover:bg-slate-100 hover:text-slate-700">ESC</button>
      </div>
      <ul id="searchResults" class="max-h-[26rem] overflow-y-auto divide-y divide-slate-100"></ul>
    </div>
  </div>
  <script>
    (function () {
      const modal = document.getElementById("global-search-modal");
      const input = document.getElementById("searchInput");
      const results = document.getElementById("searchResults");
      let timer = null;
      let controller = null;

      function escapeHtml(value) {
        return String(value || "").replace(/[&<>"']/g, function (char) {
          return {"&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#039;"}[char];
        });
      }

      function renderIdle() {
        if (!results) return;
        results.innerHTML = '<li class="px-5 py-8 text-center text-sm font-bold text-slate-400">输入关键词搜索沉淀内容</li>';
      }

      function renderResults(items) {
        if (!results) return;
        if (!items.length) {
          results.innerHTML = '<li class="px-5 py-8 text-center text-sm font-bold text-slate-400">未找到相关内容</li>';
          return;
        }
        results.innerHTML = items.map(function (item) {
          const title = escapeHtml(item.title || "未命名内容");
          const snippet = escapeHtml(item.snippet || "");
          const type = escapeHtml(item.type_label || item.type || "内容");
          const url = escapeHtml(item.url || "#");
          return '<li><a class="block px-5 py-4 transition hover:bg-slate-50" href="' + url + '">' +
            '<div class="flex items-center justify-between gap-4">' +
              '<span class="line-clamp-1 text-sm font-black text-slate-900">' + title + '</span>' +
              '<span class="shrink-0 rounded-full bg-orange-50 px-2 py-1 text-[11px] font-black text-orange-600">' + type + '</span>' +
            '</div>' +
            (snippet ? '<p class="mt-1 line-clamp-2 text-sm leading-6 text-slate-500">' + snippet + '</p>' : '') +
          '</a></li>';
        }).join("");
      }

      window.openSearch = function () {
        if (!modal || !input) return;
        modal.classList.remove("hidden");
        modal.classList.add("flex");
        window.setTimeout(function () { input.focus(); }, 0);
      };

      window.closeSearch = function () {
        if (!modal || !input) return;
        modal.classList.add("hidden");
        modal.classList.remove("flex");
        input.value = "";
        renderIdle();
      };

      document.addEventListener("click", function (event) {
        const trigger = event.target.closest("[data-search-trigger]");
        if (!trigger) return;
        event.preventDefault();
        window.openSearch();
      });

      document.addEventListener("keydown", function (event) {
        const key = String(event.key || "").toLowerCase();
        if ((event.metaKey || event.ctrlKey) && key === "k") {
          event.preventDefault();
          window.openSearch();
        }
        if (event.key === "Escape" && modal && !modal.classList.contains("hidden")) {
          window.closeSearch();
        }
      });

      if (modal) {
        modal.addEventListener("click", function (event) {
          if (event.target === modal) window.closeSearch();
        });
      }

      if (input) {
        input.addEventListener("input", function () {
          const query = input.value.trim();
          window.clearTimeout(timer);
          if (!query) {
            renderIdle();
            return;
          }
          timer = window.setTimeout(async function () {
            if (controller) controller.abort();
            controller = new AbortController();
            if (results) {
              results.innerHTML = '<li class="px-5 py-8 text-center text-sm font-bold text-slate-400">搜索中...</li>';
            }
            try {
              const response = await fetch("/api/search?q=" + encodeURIComponent(query), { signal: controller.signal });
              if (!response.ok) throw new Error("search failed");
              const payload = await response.json();
              renderResults(Array.isArray(payload) ? payload : (payload.results || []));
            } catch (error) {
              if (error.name === "AbortError") return;
              if (results) {
                results.innerHTML = '<li class="px-5 py-8 text-center text-sm font-bold text-rose-500">搜索暂时不可用</li>';
              }
            }
          }, 300);
        });
      }

      renderIdle();
    })();
  </script>"""


def render_main_home_html(request: Request) -> str:
    user = user_from_request(request)
    current_user_is_admin = is_site_admin(request, user)
    current_user_id = int(user["id"]) if user else 0
    current_user_admin_attr = "true" if current_user_is_admin else "false"
    stats = visitor_summary()
    today = datetime.now(CN_TZ).strftime("%Y年%m月%d日")
    user_name = html_escape(user["name"]) if user else ""
    raw_user_name = str(user.get("name") or "") if user else ""
    raw_user_avatar_url = str(user.get("avatar_url") or "").strip() if user else ""
    user_badge = f'{html_escape(user["tier"]).upper()} · {int(user.get("points") or 0)} 积分' if user else "登录后同步工具箱和提示词库积分"
    current_user_avatar_button = (
        f'<img id="home-author-avatar" class="h-11 w-11 shrink-0 rounded-full object-cover ring-1 ring-slate-200" src="{html_escape(raw_user_avatar_url)}" alt="{html_escape(raw_user_name or "头像")}" loading="lazy">'
        if raw_user_avatar_url else
        f'<button id="home-author-avatar" class="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-slate-950 text-sm font-black text-white" type="button">{html_escape((raw_user_name or "M")[:1] or "M")}</button>'
    )
    sidebar_user_avatar = (
        f'<img class="h-11 w-11 shrink-0 rounded-full object-cover ring-1 ring-slate-200" src="{html_escape(raw_user_avatar_url)}" alt="{html_escape(raw_user_name or "头像")}" loading="lazy">'
        if raw_user_avatar_url else
        f'<span class="grid h-11 w-11 place-items-center rounded-full bg-slate-950 text-sm font-black text-white">{html_escape((raw_user_name or "M")[:1] or "M")}</span>'
    )
    sidebar_account_href = "/account" if user else "/login"
    sidebar_account_label = "进入会员中心" if user else "登录 / 注册"
    json_ld = safe_json_ld({
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": "meetseek",
        "url": MAIN_BASE_URL,
        "inLanguage": "zh-CN",
        "description": "meetseek 是面向 AI 技术、商业变现、工具效率和提示词创作的轻量社区与工具入口。",
        "potentialAction": {
            "@type": "SearchAction",
            "target": f"{MAIN_BASE_URL}/search?q={{search_term_string}}",
            "query-input": "required name=search_term_string",
        },
    })
    feed_items = [
        {
            "type": "长文",
            "title": "AI 工具如何从玩具变成真正的生产力",
            "summary": "从提示词库、视频下载、图片处理到积分会员，meetseek 会把可复用的 AI 工作流沉淀成工具和内容。",
            "href": "https://prompts.meetseek.ai/",
            "tag": "提示词库",
            "meta": "置顶 · 4 分钟阅读",
        },
        {
            "type": "短文",
            "title": "主站正在融合工具箱和提示词库",
            "summary": "同一个账号、同一套积分、同一个会员中心。工具用于解决问题，社区用于沉淀经验。",
            "href": "https://tools.meetseek.ai/",
            "tag": "工具箱",
            "meta": f"{today} · 1 分钟阅读",
        },
        {
            "type": "链接",
            "title": "图片反推提示词已经接入火山方舟 Seed 2.0",
            "summary": "上传图片后生成中文和英文 Prompt，后续会继续补充适用模型、案例图库和会员积分规则。",
            "href": "https://prompts.meetseek.ai/reverse",
            "tag": "AI 工具",
            "meta": "更新 · 2 分钟阅读",
        },
    ]
    with db() as conn:
        if current_user_id:
            saved_rows = conn.execute(
                """
                SELECT posts.*, users.name AS author_name, users.avatar_url AS author_avatar_url
                FROM posts
                JOIN users ON users.id = posts.author_id
                WHERE posts.status = 'published'
                  AND posts.visibility = 'public'
                  AND NOT EXISTS (
                    SELECT 1
                    FROM user_post_preferences
                    WHERE user_post_preferences.user_id = ?
                      AND user_post_preferences.post_id = posts.id
                      AND user_post_preferences.kind IN ('hidden', 'not_interested')
                  )
                  AND NOT EXISTS (
                    SELECT 1
                    FROM user_blocks
                    WHERE user_blocks.user_id = ?
                      AND user_blocks.author_id = posts.author_id
                  )
                ORDER BY posts.pinned_at DESC, posts.published_at DESC, posts.created_at DESC
                LIMIT 8
                """,
                (current_user_id, current_user_id),
            ).fetchall()
        else:
            saved_rows = conn.execute(
                """
                SELECT posts.*, users.name AS author_name, users.avatar_url AS author_avatar_url
                FROM posts
                JOIN users ON users.id = posts.author_id
                WHERE posts.status = 'published' AND posts.visibility = 'public'
                ORDER BY posts.pinned_at DESC, posts.published_at DESC, posts.created_at DESC
                LIMIT 8
                """
            ).fetchall()
        following_author_ids = {
            int(row["author_id"])
            for row in conn.execute(
                "SELECT author_id FROM user_follows WHERE follower_id = ?",
                (current_user_id,),
            ).fetchall()
        } if user else set()
    saved_items = []
    for row in saved_rows:
        post = public_post(row)
        item_type = {"short": "短文", "article": "长文", "tool": "工具", "prompt": "提示词", "link": "链接"}.get(post["type"], "内容")
        read_minutes = max(1, round(len(post["summary"] or post["content_html"]) / 260))
        saved_items.append(
            {
                "id": post["id"],
                "author_id": post["author_id"],
                "post_type": post["type"],
                "type": item_type,
                "title": post["title"],
                "summary": post.get("display_summary") or post["summary"] or post_excerpt(post["content_html"]),
                "href": post["canonical_url"],
                "tag": post["category_slug"],
                "meta": f"{datetime.fromtimestamp(post['published_at'] or post['created_at'], CN_TZ).strftime('%Y年%m月%d日')} · {read_minutes} 分钟阅读",
                "author": row["author_name"] or "meetseek",
                "author_avatar_url": row["author_avatar_url"] if "author_avatar_url" in row.keys() else "",
                "image": post["og_image"],
                "like_count": post["like_count"],
                "comment_count": post["comment_count"],
                "bookmark_count": post["bookmark_count"],
                "link_cards_html": post.get("link_cards_html", ""),
                "link_previews": post.get("link_previews", []),
                "more_menu_html": post_more_menu_html(
                    post_id=post["id"],
                    author_id=post["author_id"],
                    post_url=post["canonical_url"],
                    current_user=user,
                    is_admin=current_user_is_admin,
                    is_following=post["author_id"] in following_author_ids,
                    is_recommended=bool(post.get("recommended_at")),
                ),
            }
        )
    feed_items = saved_items + feed_items
    tool_cards = [
        {"title": "AI 工具箱", "desc": "视频下载、图片修复、文件压缩、PDF 转换和文案卡片。", "href": TOOLS_BASE_URL, "mark": "工"},
        {"title": "提示词库", "desc": "瀑布流提示词案例、图片反推、中英文 Prompt 和模型标签。", "href": PROMPTS_BASE_URL, "mark": "提"},
        {"title": "MeetSeek 商店", "desc": "会员、积分包、AI 服务和后台自定义商品统一放在这里。", "href": SHOP_BASE_URL, "mark": "店"},
        {"title": "会员中心", "desc": "积分、签到、订单和工具使用权限会在三个站点共用。", "href": "/account", "mark": "会"},
    ]
    nav_items = [
        ("首页", "/"),
        ("工具箱", TOOLS_BASE_URL),
        ("提示词", PROMPTS_BASE_URL),
        ("商店", SHOP_BASE_URL),
        ("会员", "/account"),
    ]
    composer_html = """
      <section id="home-compose" class="mb-6 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm transition-shadow focus-within:shadow-md">
        <form id="home-post-form" class="grid gap-5">
          <div class="flex items-start gap-4">
            <button id="home-author-avatar" class="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-slate-950 text-sm font-black text-white" type="button">M</button>
            <div class="min-w-0 flex-1">
              <textarea id="home-post-content" class="min-h-[120px] w-full resize-none border-none bg-transparent px-0 text-base leading-7 text-slate-800 outline-none placeholder:text-slate-400 focus:ring-0" placeholder="分享你的想法、经验或发现..."></textarea>
              <input id="home-post-title" class="hidden h-11 w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 text-sm font-black outline-none transition focus:border-orange-300" placeholder="工具链接标题">
              <input id="home-post-source" class="mt-3 hidden h-11 w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 text-sm font-bold outline-none transition focus:border-orange-300" placeholder="可选：粘贴工具或文章链接">
            </div>
          </div>
          <div class="flex flex-wrap items-center justify-between gap-3">
            <input id="home-post-category" type="hidden" value="ai-tools">
            <div class="flex items-center gap-2 rounded-xl border border-slate-100 bg-slate-50 p-1.5">
              <button id="home-image-button" class="grid h-9 w-9 place-items-center rounded-lg text-slate-600 transition-colors hover:bg-white hover:text-slate-900 hover:shadow-sm" type="button" aria-label="上传图片" title="图片">
                <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="m2.25 15.75 5.159-5.159a2.25 2.25 0 0 1 3.182 0l5.159 5.159m-1.5-1.5 1.409-1.409a2.25 2.25 0 0 1 3.182 0l2.909 2.909M3.75 19.5h16.5a1.5 1.5 0 0 0 1.5-1.5V6a1.5 1.5 0 0 0-1.5-1.5H3.75A1.5 1.5 0 0 0 2.25 6v12a1.5 1.5 0 0 0 1.5 1.5Zm10.5-11.25h.008v.008h-.008V8.25Z"/></svg>
              </button>
              <button id="home-video-button" class="grid h-9 w-9 place-items-center rounded-lg text-slate-600 transition-colors hover:bg-white hover:text-slate-900 hover:shadow-sm" type="button" aria-label="上传视频" title="视频">
                <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="m15.75 10.5 4.72-4.72a.75.75 0 0 1 1.28.53v11.38a.75.75 0 0 1-1.28.53l-4.72-4.72M4.5 18.75h9a2.25 2.25 0 0 0 2.25-2.25v-9A2.25 2.25 0 0 0 13.5 5.25h-9A2.25 2.25 0 0 0 2.25 7.5v9a2.25 2.25 0 0 0 2.25 2.25Z"/></svg>
              </button>
              <button id="home-gif-button" class="grid h-9 w-9 place-items-center rounded-lg text-slate-600 transition-colors hover:bg-white hover:text-slate-900 hover:shadow-sm" type="button" aria-label="插入 GIF" title="GIF">
                <svg class="h-6 w-6" viewBox="0 0 28 20" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><rect x="1.5" y="2.5" width="25" height="15" rx="4"/><path stroke-linecap="round" stroke-linejoin="round" d="M9.2 8.2H7.5a2 2 0 1 0 0 4h1.7v-1.7H8.1M12.4 8.2v4M16 12.2v-4h4.2M16 10.2h3.2"/></svg>
              </button>
              <button id="home-emoji-button" class="grid h-9 w-9 place-items-center rounded-lg text-slate-600 transition-colors hover:bg-white hover:text-slate-900 hover:shadow-sm" type="button" aria-label="插入表情" title="表情">
                <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M15.182 15.182a4.5 4.5 0 0 1-6.364 0M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0ZM9.75 9.75h.008v.008H9.75V9.75Zm4.5 0h.008v.008h-.008V9.75Z"/></svg>
              </button>
              <button id="home-tool-post" class="grid h-9 w-9 place-items-center rounded-lg text-slate-600 transition-colors hover:bg-white hover:text-slate-900 hover:shadow-sm" type="button" aria-label="工具链接" title="工具链接">
                <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M13.19 8.688a4.5 4.5 0 0 1 6.364 6.364l-1.768 1.768a4.5 4.5 0 0 1-6.364-6.364l.884-.884m-1.768 5.303a4.5 4.5 0 0 1-6.364-6.364l1.768-1.768a4.5 4.5 0 0 1 6.364 6.364l-.884.884"/></svg>
              </button>
              <button id="home-long-post" class="inline-flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm text-slate-600 transition-colors hover:bg-white hover:text-slate-900 hover:shadow-sm" type="button">
                <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M16.862 4.487 18.55 2.8a1.875 1.875 0 1 1 2.652 2.652L10.582 16.07a4.5 4.5 0 0 1-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 0 1 1.13-1.897l8.932-8.931Zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0 1 15.75 21H5.25A2.25 2.25 0 0 1 3 18.75V8.25A2.25 2.25 0 0 1 5.25 6H10"/></svg>
                文章
              </button>
            </div>
            <button id="home-post-submit" class="rounded-full bg-orange-600 px-7 py-3 text-sm font-black text-white transition hover:bg-orange-700 disabled:bg-slate-300" type="submit">发布</button>
          </div>
          <input id="home-image-input" class="hidden" type="file" accept="image/png,image/jpeg,image/webp">
          <input id="home-video-input" class="hidden" type="file" accept="video/mp4,video/quicktime,video/webm">
          <input id="home-gif-input" class="hidden" type="file" accept="image/gif">
          <div id="home-emoji-panel" class="hidden flex flex-wrap gap-2 rounded-2xl bg-slate-50 p-3 text-xl"></div>
          <div id="home-media-preview" class="hidden grid gap-3 rounded-2xl bg-slate-50 p-3 sm:grid-cols-3"></div>
          <p id="home-post-message" class="hidden rounded-2xl bg-slate-50 px-4 py-3 text-sm font-black"></p>
        </form>
      </section>
      <div id="home-article-modal" class="fixed inset-0 z-50 hidden place-items-center bg-slate-950/45 px-4 py-6 backdrop-blur-sm">
        <div class="mx-auto flex h-[90vh] w-full max-w-5xl flex-col overflow-hidden rounded-3xl bg-white shadow-2xl">
          <div class="flex shrink-0 justify-end px-6 pt-4">
            <button id="home-article-close" class="grid h-10 w-10 place-items-center rounded-full bg-slate-100 text-xl font-black text-slate-600" type="button">×</button>
          </div>
          <div class="flex-1 overflow-y-auto p-8">
            <input id="home-article-title" class="w-full border-none bg-transparent px-0 text-3xl font-bold leading-tight text-slate-950 outline-none placeholder:text-slate-300 focus:ring-0" placeholder="输入标题...">
            <div class="mt-4 flex items-center gap-2 rounded-xl border border-slate-100 bg-slate-50 p-1.5">
              <span class="rounded-lg px-3 py-1.5 text-sm text-slate-600 transition-colors hover:bg-white hover:text-slate-900 hover:shadow-sm">H2/H3</span>
              <span class="rounded-lg px-3 py-1.5 text-sm text-slate-600 transition-colors hover:bg-white hover:text-slate-900 hover:shadow-sm">图片</span>
              <span class="rounded-lg px-3 py-1.5 text-sm text-slate-600 transition-colors hover:bg-white hover:text-slate-900 hover:shadow-sm">列表</span>
              <span class="rounded-lg px-3 py-1.5 text-sm text-slate-600 transition-colors hover:bg-white hover:text-slate-900 hover:shadow-sm">引用</span>
              <span class="rounded-lg px-3 py-1.5 text-sm text-slate-600 transition-colors hover:bg-white hover:text-slate-900 hover:shadow-sm">链接预览</span>
            </div>
            <div id="home-article-editor" class="mt-6 min-h-[50vh] rounded-2xl bg-white px-1 py-4 text-slate-800"></div>
          </div>
          <div class="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-slate-100 bg-white px-6 py-4">
            <span id="home-article-draft-state" class="text-sm font-bold text-slate-400">草稿自动保存</span>
            <div class="flex gap-2">
              <button id="home-article-clear" class="rounded-full bg-slate-100 px-5 py-3 text-sm font-black text-slate-600" type="button">清空草稿</button>
              <button id="home-article-submit" class="rounded-full bg-orange-600 px-7 py-3 text-sm font-black text-white" type="button">发布</button>
            </div>
          </div>
        </div>
      </div>
    """
    composer_html = composer_html.replace(
        '<button id="home-author-avatar" class="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-slate-950 text-sm font-black text-white" type="button">M</button>',
        current_user_avatar_button,
    )
    if not user:
        composer_html = """
      <a id="home-compose" href="/login" class="mb-6 flex cursor-pointer items-center justify-between rounded-3xl border border-slate-200 bg-white p-6 shadow-sm transition-shadow hover:shadow-md">
        <div class="flex min-w-0 items-center gap-4">
          <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-slate-100 text-slate-400">M</div>
          <span class="truncate text-lg text-slate-400">登录后分享你的想法与经验...</span>
        </div>
        <span class="shrink-0 rounded-full bg-slate-900 px-5 py-2 text-sm font-medium text-white">登录 / 注册</span>
      </a>
        """
    composer_script = """
  <script>
    (function () {
      const form = document.getElementById("home-post-form");
      if (!form) return;
      const title = document.getElementById("home-post-title");
      const content = document.getElementById("home-post-content");
      const category = document.getElementById("home-post-category");
      const source = document.getElementById("home-post-source");
      const message = document.getElementById("home-post-message");
      const submit = document.getElementById("home-post-submit");
      const imageButton = document.getElementById("home-image-button");
      const videoButton = document.getElementById("home-video-button");
      const gifButton = document.getElementById("home-gif-button");
      const emojiButton = document.getElementById("home-emoji-button");
      const imageInput = document.getElementById("home-image-input");
      const videoInput = document.getElementById("home-video-input");
      const gifInput = document.getElementById("home-gif-input");
      const emojiPanel = document.getElementById("home-emoji-panel");
      const mediaPreview = document.getElementById("home-media-preview");
      const toolButton = document.getElementById("home-tool-post");
      const longButton = document.getElementById("home-long-post");
      const articleModal = document.getElementById("home-article-modal");
      const articleClose = document.getElementById("home-article-close");
      const articleTitle = document.getElementById("home-article-title");
      const articleEditorHolder = document.getElementById("home-article-editor");
      const articleSubmit = document.getElementById("home-article-submit");
      const articleClear = document.getElementById("home-article-clear");
      const articleDraftState = document.getElementById("home-article-draft-state");
      let postType = "short";
      const draftKey = "meetseek:article-draft";
      const emojiList = ["😀","😂","😍","👍","🔥","✨","🚀","💡","📌","👏","🤔","😎","🥹","✅","❤️","🎯"];
      const uploadedMedia = [];
      let editor = null;
      let draftTimer = null;

      function setMessage(text, isError) {
        message.textContent = text;
        message.className = "rounded-2xl px-4 py-3 text-sm font-black " + (isError ? "bg-rose-50 text-rose-600" : "bg-emerald-50 text-emerald-700");
      }

      function escapeHtml(value) {
        return String(value || "")
          .replaceAll("&", "&amp;")
          .replaceAll("<", "&lt;")
          .replaceAll(">", "&gt;")
          .replaceAll('"', "&quot;")
          .replaceAll("'", "&#39;");
      }

      function renderMediaPreview() {
        if (!uploadedMedia.length) {
          mediaPreview.classList.add("hidden");
          mediaPreview.innerHTML = "";
          return;
        }
        mediaPreview.classList.remove("hidden");
        mediaPreview.innerHTML = uploadedMedia.map((item, index) => {
          const remove = `<button class="absolute right-2 top-2 grid h-7 w-7 place-items-center rounded-full bg-white/90 text-sm font-black text-slate-600 shadow" type="button" data-remove-media="${index}">×</button>`;
          if (item.kind === "video") {
            return `<div class="relative overflow-hidden rounded-2xl bg-white"><video class="h-36 w-full object-cover" src="${escapeHtml(item.url)}" controls preload="metadata"></video>${remove}</div>`;
          }
          return `<div class="relative overflow-hidden rounded-2xl bg-white"><img class="h-36 w-full object-cover" src="${escapeHtml(item.url)}" alt="上传媒体" loading="lazy">${remove}</div>`;
        }).join("");
        mediaPreview.querySelectorAll("[data-remove-media]").forEach((button) => {
          button.addEventListener("click", () => {
            uploadedMedia.splice(Number(button.dataset.removeMedia), 1);
            renderMediaPreview();
          });
        });
      }

      function mediaToHtml() {
        return uploadedMedia.map((item) => {
          if (item.kind === "video") return `<figure><video src="${escapeHtml(item.url)}" controls preload="metadata" playsinline></video></figure>`;
          return `<figure><img src="${escapeHtml(item.url)}" alt="帖子图片" loading="lazy"></figure>`;
        }).join("");
      }

      async function uploadMedia(kind, file) {
        if (!file) return;
        setMessage("正在上传...", false);
        const data = new FormData();
        data.append("kind", kind);
        data.append("file", file);
        const response = await fetch("/api/posts/media", { method: "POST", body: data });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) {
          setMessage(result.detail || "上传失败", true);
          return;
        }
        uploadedMedia.push(result.media);
        renderMediaPreview();
        setMessage("上传完成", false);
      }

      function insertEmoji(emoji) {
        const start = content.selectionStart || 0;
        const end = content.selectionEnd || 0;
        content.value = content.value.slice(0, start) + emoji + content.value.slice(end);
        content.focus();
        content.selectionStart = content.selectionEnd = start + emoji.length;
      }

      function setPostType(nextType) {
        postType = nextType;
        toolButton.className = postType === "tool"
          ? "grid h-9 w-9 place-items-center rounded-lg bg-white text-slate-900 shadow-sm transition-colors"
          : "grid h-9 w-9 place-items-center rounded-lg text-slate-600 transition-colors hover:bg-white hover:text-slate-900 hover:shadow-sm";
        title.classList.toggle("hidden", postType !== "tool");
        source.classList.toggle("hidden", postType !== "tool");
        if (postType === "tool") title.focus();
        else content.focus();
      }

      function openArticleModal() {
        articleModal.classList.remove("hidden");
        articleModal.classList.add("grid");
        articleTitle.focus();
      }

      function closeArticleModal() {
        articleModal.classList.add("hidden");
        articleModal.classList.remove("grid");
      }

      function blocksToText(data) {
        return (data?.blocks || []).map((block) => {
          const item = block.data || {};
          if (typeof item.text === "string") return item.text.replace(/<[^>]*>/g, "");
          if (Array.isArray(item.items)) return item.items.join(" ");
          if (typeof item.caption === "string") return item.caption.replace(/<[^>]*>/g, "");
          if (item.meta?.title) return item.meta.title;
          return "";
        }).filter(Boolean).join("\\n\\n").trim();
      }

      async function getEditorData() {
        if (!editor) return { time: Date.now(), blocks: [], version: "2" };
        return await editor.save();
      }

      async function saveArticleDraft() {
        const draft = { title: articleTitle.value, content: await getEditorData() };
        localStorage.setItem(draftKey, JSON.stringify(draft));
        articleDraftState.textContent = "草稿已保存";
      }

      function queueArticleDraftSave() {
        clearTimeout(draftTimer);
        draftTimer = setTimeout(() => {
          saveArticleDraft().catch(() => {
            articleDraftState.textContent = "草稿保存失败";
          });
        }, 450);
      }

      function loadArticleDraft() {
        try {
          const raw = localStorage.getItem(draftKey);
          if (!raw) return null;
          const draft = JSON.parse(raw);
          articleTitle.value = draft.title || "";
          return draft.content || null;
        } catch (error) {}
        return null;
      }

      function initArticleEditor() {
        if (editor || !articleEditorHolder || !window.EditorJS) return;
        const savedBlocks = loadArticleDraft();
        editor = new EditorJS({
          holder: "home-article-editor",
          placeholder: "输入 / 选择块，开始写作...",
          data: savedBlocks || { blocks: [] },
          autofocus: false,
          tools: {
            header: {
              class: Header,
              inlineToolbar: true,
              config: { levels: [2, 3], defaultLevel: 2 }
            },
            image: {
              class: ImageTool,
              config: {
                endpoints: { byFile: "/api/posts/editor-image" },
                field: "image"
              }
            },
            list: { class: EditorjsList, inlineToolbar: true },
            quote: { class: Quote, inlineToolbar: true, config: { quotePlaceholder: "引用内容", captionPlaceholder: "出处" } },
            linkTool: { class: LinkTool, config: { endpoint: "/api/posts/link-preview" } }
          },
          onChange: queueArticleDraftSave
        });
      }

      async function submitArticle() {
        const editorData = await getEditorData();
        const articleBody = blocksToText(editorData);
        const articleHeading = articleTitle.value.trim();
        if (!articleHeading || articleHeading.length < 2) {
          articleDraftState.textContent = "标题至少 2 个字";
          return;
        }
        if (!articleBody || articleBody.length < 10) {
          articleDraftState.textContent = "正文至少写 10 个字";
          return;
        }
        const data = new FormData();
        data.append("title", articleHeading);
        data.append("content_html", JSON.stringify(editorData));
        data.append("summary", articleBody.replace(/\\s+/g, " ").slice(0, 180));
        data.append("post_type", "article");
        data.append("category_slug", category.value);
        data.append("source_url", "");
        data.append("status", "published");
        data.append("visibility", "public");
        articleSubmit.disabled = true;
        articleSubmit.textContent = "发布中...";
        try {
          const response = await fetch("/api/posts", { method: "POST", body: data });
          const payload = await response.json();
          if (!response.ok) throw new Error(payload.detail || "发布失败");
          if (payload.html) {
            document.getElementById("home-feed-list")?.insertAdjacentHTML("afterbegin", payload.html);
          }
          initExpandablePosts();
          localStorage.removeItem(draftKey);
          articleTitle.value = "";
          if (editor) await editor.clear();
          closeArticleModal();
          setMessage("内容已发布到信息流顶部。", false);
        } catch (error) {
          articleDraftState.textContent = error.message || "发布失败";
        } finally {
          articleSubmit.disabled = false;
          articleSubmit.textContent = "发布";
        }
      }

      toolButton?.addEventListener("click", () => setPostType(postType === "tool" ? "short" : "tool"));
      longButton?.addEventListener("click", () => {
        initArticleEditor();
        openArticleModal();
      });
      articleClose?.addEventListener("click", closeArticleModal);
      articleModal?.addEventListener("click", (event) => {
        if (event.target === articleModal) closeArticleModal();
      });
      articleTitle?.addEventListener("input", saveArticleDraft);
      articleSubmit?.addEventListener("click", submitArticle);
      articleClear?.addEventListener("click", () => {
        articleTitle.value = "";
        if (editor) editor.clear();
        localStorage.removeItem(draftKey);
        articleDraftState.textContent = "草稿已清空";
      });
      imageButton?.addEventListener("click", () => imageInput?.click());
      videoButton?.addEventListener("click", () => videoInput?.click());
      gifButton?.addEventListener("click", () => gifInput?.click());
      imageInput?.addEventListener("change", () => {
        uploadMedia("image", imageInput.files?.[0]).finally(() => {
          imageInput.value = "";
        });
      });
      videoInput?.addEventListener("change", () => {
        uploadMedia("video", videoInput.files?.[0]).finally(() => {
          videoInput.value = "";
        });
      });
      gifInput?.addEventListener("change", () => {
        uploadMedia("gif", gifInput.files?.[0]).finally(() => {
          gifInput.value = "";
        });
      });
      emojiPanel.innerHTML = emojiList.map((emoji) => `<button class="grid h-9 w-9 place-items-center rounded-full bg-white text-lg shadow-sm transition hover:bg-slate-100" type="button" data-emoji="${emoji}">${emoji}</button>`).join("");
      emojiButton?.addEventListener("click", () => {
        emojiPanel.classList.toggle("hidden");
      });
      emojiPanel.querySelectorAll("[data-emoji]").forEach((button) => {
        button.addEventListener("click", () => {
          insertEmoji(button.dataset.emoji || "");
          emojiPanel.classList.add("hidden");
        });
      });
      loadArticleDraft();

      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const body = content.value.trim();
        const mediaBlock = mediaToHtml();
        if (!body && !uploadedMedia.length) {
          setMessage("先写一点内容再发布。", true);
          return;
        }
        const derivedTitle = body.replace(/\\s+/g, " ").slice(0, 60);
        const fallbackTitle = uploadedMedia.length ? "分享了媒体内容" : "";
        const finalTitle = postType === "short" ? derivedTitle : title.value.trim();
        if (!(finalTitle || fallbackTitle) || (finalTitle || fallbackTitle).length < 2) {
          setMessage(postType === "tool" ? "工具链接标题至少 2 个字。" : "先多写一点内容再发布。", true);
          return;
        }
        const finalContent = [body, mediaBlock].filter(Boolean).join("\\n\\n");
        const finalSummary = body
          ? body.replace(/\\s+/g, " ").slice(0, 160)
          : uploadedMedia.map((item) => item.kind === "video" ? "视频" : item.kind === "gif" ? "动图" : "图片").join("、");
        const data = new FormData();
        data.append("title", finalTitle || fallbackTitle);
        data.append("content_html", finalContent);
        data.append("summary", finalSummary);
        data.append("post_type", postType);
        data.append("category_slug", category.value);
        data.append("source_url", source.value.trim());
        data.append("status", "published");
        data.append("visibility", "public");
        submit.disabled = true;
        submit.textContent = "发布中...";
        try {
          const response = await fetch("/api/posts", { method: "POST", body: data });
          const payload = await response.json();
          if (!response.ok) throw new Error(payload.detail || "发布失败");
          if (payload.html) {
            document.getElementById("home-feed-list")?.insertAdjacentHTML("afterbegin", payload.html);
          }
          initExpandablePosts();
          title.value = "";
          content.value = "";
          source.value = "";
          uploadedMedia.splice(0, uploadedMedia.length);
          renderMediaPreview();
          setPostType("short");
          setMessage("已发布到最新动态顶部。", false);
        } catch (error) {
          setMessage(error.message || "发布失败，请先确认已登录。", true);
        } finally {
          submit.disabled = false;
          submit.textContent = "发布";
        }
      });
      function initExpandablePosts(root = document) {
        root.querySelectorAll(".content-box").forEach((text) => {
          const button = text.nextElementSibling?.classList?.contains("expand-toggle-btn") ? text.nextElementSibling : null;
          if (!button || text.dataset.expandReady === "true") return;
          text.dataset.expandReady = "true";
          requestAnimationFrame(() => {
            if (text.scrollHeight > text.clientHeight + 2) {
              button.classList.remove("hidden");
            }
          });
          button.addEventListener("click", () => {
            const expanded = text.dataset.expanded === "true";
            text.dataset.expanded = expanded ? "false" : "true";
            text.classList.toggle("line-clamp-4", expanded);
            button.textContent = expanded ? "展开全文" : "收起";
          });
        });
      }
      function setReactionState(button, active, count) {
        const label = button.querySelector("[data-count-label]");
        button.dataset.active = active ? "true" : "false";
        button.dataset.count = String(Math.max(0, count));
        button.classList.toggle("text-emerald-600", button.classList.contains("btn-like") && active);
        button.classList.toggle("text-orange-500", button.classList.contains("btn-bookmark") && active);
        if (label) label.textContent = String(Math.max(0, count));
      }
      async function toggleReaction(button, endpoint) {
        const postId = Number(button.dataset.postId || 0);
        if (!postId) return;
        if (button.dataset.busy === "true") return;
        button.dataset.busy = "true";
        const wasActive = button.dataset.active === "true";
        const previousCount = Number(button.dataset.count || 0);
        const optimisticCount = Math.max(0, previousCount + (wasActive ? -1 : 1));
        setReactionState(button, !wasActive, optimisticCount);
        try {
          const response = await fetch(endpoint.replace(":id", String(postId)), { method: "POST" });
          if (response.status === 401) {
            window.location.href = "/account";
            return;
          }
          const payload = await response.json();
          if (!response.ok) throw new Error(payload.detail || "操作失败");
          setReactionState(button, Boolean(payload.active), Number(payload.count || 0));
        } catch (error) {
          setReactionState(button, wasActive, previousCount);
          alert(error.message || "操作失败");
        } finally {
          button.dataset.busy = "false";
        }
      }
      function showToast(text) {
        let toast = document.getElementById("home-toast");
        if (!toast) {
          toast = document.createElement("div");
          toast.id = "home-toast";
          toast.className = "fixed bottom-6 left-1/2 z-[80] -translate-x-1/2 rounded-full bg-slate-950 px-5 py-3 text-sm font-black text-white shadow-lg transition";
          document.body.appendChild(toast);
        }
        toast.textContent = text;
        toast.style.opacity = "1";
        clearTimeout(window.__homeToastTimer);
        window.__homeToastTimer = setTimeout(() => { toast.style.opacity = "0"; }, 1800);
      }
      function relativeTime(ts) {
        const diff = Math.max(1, Math.floor(Date.now() / 1000) - Number(ts || 0));
        if (diff < 60) return "刚刚";
        if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
        if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
        return `${Math.floor(diff / 86400)} 天前`;
      }
      function renderInlineComment(comment) {
        const name = comment.author?.name || "用户";
        const avatar = comment.author?.avatar_url
          ? `<img class="h-8 w-8 rounded-full object-cover ring-1 ring-slate-200" src="${escapeHtml(comment.author.avatar_url)}" alt="${escapeHtml(name)}" loading="lazy">`
          : `<div class="grid h-8 w-8 place-items-center rounded-full bg-slate-900 text-xs font-black text-white">${escapeHtml(name.slice(0, 1) || "用")}</div>`;
        return `
          <div class="flex gap-3 rounded-2xl bg-slate-50 p-3">
            <div class="shrink-0">${avatar}</div>
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2">
                <b class="text-sm text-slate-900">${escapeHtml(name)}</b>
                <span class="text-xs font-bold text-slate-400">${relativeTime(comment.created_at)}</span>
              </div>
              <p class="mt-1 whitespace-pre-wrap text-sm leading-6 text-slate-600">${escapeHtml(comment.content)}</p>
            </div>
          </div>`;
      }
      async function loadInlineComments(panel, postId) {
        const list = panel.querySelector("[data-inline-comment-list]");
        if (!list || panel.dataset.loaded === "true") return;
        list.innerHTML = '<div class="rounded-2xl bg-slate-50 p-4 text-sm font-bold text-slate-400">正在加载评论...</div>';
        const response = await fetch(`/api/comments/post/${postId}`);
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.detail || "评论加载失败");
        const comments = payload.comments || [];
        list.innerHTML = comments.length
          ? comments.map(renderInlineComment).join("")
          : '<div class="rounded-2xl border border-dashed border-slate-200 bg-slate-50 p-4 text-center text-sm font-bold text-slate-400">暂无评论，来写第一条。</div>';
        panel.dataset.loaded = "true";
      }
      async function toggleInlineComments(button) {
        const postId = Number(button.dataset.postId || 0);
        const article = button.closest("article");
        const panel = article?.querySelector(`[data-inline-comments="${postId}"]`);
        if (!postId || !panel) return;
        const willOpen = panel.classList.contains("hidden");
        panel.classList.toggle("hidden", !willOpen);
        if (willOpen) await loadInlineComments(panel, postId);
      }
      async function submitInlineComment(form) {
        const postId = Number(form.dataset.postId || 0);
        const textarea = form.querySelector("textarea");
        const status = form.querySelector("[data-inline-comment-status]");
        const text = (textarea?.value || "").trim();
        if (!postId || !text) return;
        if (status) status.textContent = "正在发送...";
        const payload = new FormData();
        payload.append("target_type", "post");
        payload.append("target_id", String(postId));
        payload.append("content", text);
        const response = await fetch("/api/comments", { method: "POST", body: payload });
        if (response.status === 401) { window.location.href = "/account"; return; }
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          if (status) status.textContent = data.detail || "发送失败";
          return;
        }
        textarea.value = "";
        if (status) status.textContent = "已发送";
        const panel = form.closest("[data-inline-comments]");
        const list = panel?.querySelector("[data-inline-comment-list]");
        if (list) {
          if (list.querySelector(".border-dashed")) list.innerHTML = "";
          list.insertAdjacentHTML("afterbegin", renderInlineComment(data.comment));
        }
        const countLabel = document.querySelector(`[data-comment-count-label="${postId}"]`);
        if (countLabel) countLabel.textContent = String(Number(countLabel.textContent || 0) + 1);
        setTimeout(() => { if (status) status.textContent = ""; }, 1500);
      }
      function closeMoreMenus(exceptMenu) {
        document.querySelectorAll(".more-menu").forEach((menu) => {
          if (menu !== exceptMenu) menu.classList.add("hidden");
        });
      }
      async function runPostMenuAction(button) {
        const action = button.dataset.menuAction;
        const article = button.closest("article");
        if (action === "copy") {
          const url = new URL(button.dataset.url || window.location.href, window.location.origin).toString();
          await navigator.clipboard.writeText(url);
          showToast("已复制");
          return;
        }
        if (action === "follow") {
          const authorId = Number(button.dataset.authorId || 0);
          if (!authorId) return;
          const wasFollowing = button.dataset.following === "true";
          button.dataset.following = wasFollowing ? "false" : "true";
          button.textContent = wasFollowing ? "关注" : "取消关注";
          const response = await fetch(`/api/users/${authorId}/toggle_follow`, { method: "POST" });
          if (response.status === 401) { window.location.href = "/account"; return; }
          const payload = await response.json().catch(() => ({}));
          if (!response.ok) throw new Error(payload.detail || "操作失败");
          button.dataset.following = payload.following ? "true" : "false";
          button.textContent = payload.following ? "取消关注" : "关注";
          showToast(payload.message || "已更新");
          return;
        }
        if (action === "bookmark") {
          const postId = Number(button.dataset.postId || 0);
          const response = await fetch(`/api/posts/${postId}/toggle_bookmark`, { method: "POST" });
          if (response.status === 401) { window.location.href = "/account"; return; }
          const payload = await response.json().catch(() => ({}));
          if (!response.ok) throw new Error(payload.detail || "操作失败");
          showToast(payload.active ? "已收藏" : "已取消收藏");
          return;
        }
        const postId = Number(button.dataset.postId || 0);
        if (!postId) return;
        const destructive = ["hide", "delete", "private", "not_interested", "block_author", "violation", "ban_author"].includes(action);
        if (destructive && article) {
          article.style.transition = "opacity .18s ease, transform .18s ease";
          article.style.opacity = "0";
          article.style.transform = "translateY(6px)";
          setTimeout(() => article.remove(), 180);
        }
        const response = await fetch(`/api/posts/${postId}/action`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action })
        });
        if (response.status === 401) { window.location.href = "/account"; return; }
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.detail || "操作失败");
        if (["pin", "private", "recommend", "unrecommend", "report", "violation", "ban_author"].includes(action)) {
          showToast(payload.message || "已更新");
        }
      }
      document.addEventListener("click", async (event) => {
        const toggle = event.target.closest(".more-menu-toggle");
        if (toggle) {
          event.preventDefault();
          const menu = toggle.parentElement?.querySelector(".more-menu");
          if (!menu) return;
          const willOpen = menu.classList.contains("hidden");
          closeMoreMenus(menu);
          menu.classList.toggle("hidden", !willOpen);
          return;
        }
        const menuAction = event.target.closest(".more-menu-action");
        if (menuAction) {
          event.preventDefault();
          closeMoreMenus();
          try {
            await runPostMenuAction(menuAction);
          } catch (error) {
            showToast(error.message || "操作失败");
          }
          return;
        }
        if (!event.target.closest(".more-menu")) closeMoreMenus();
        const commentButton = event.target.closest(".btn-inline-comment");
        if (commentButton) {
          event.preventDefault();
          await toggleInlineComments(commentButton);
          return;
        }
        const inlineCommentForm = event.target.closest("[data-inline-comment-form]");
        if (inlineCommentForm && event.target.closest("[data-inline-comment-submit]")) {
          event.preventDefault();
          await submitInlineComment(inlineCommentForm);
          return;
        }
        const likeButton = event.target.closest(".btn-like");
        if (likeButton) {
          event.preventDefault();
          await toggleReaction(likeButton, "/api/posts/:id/toggle_like");
          return;
        }
        const bookmarkButton = event.target.closest(".btn-bookmark");
        if (bookmarkButton) {
          event.preventDefault();
          await toggleReaction(bookmarkButton, "/api/posts/:id/toggle_bookmark");
          return;
        }
        const shareButton = event.target.closest(".btn-share");
        if (shareButton) {
          event.preventDefault();
          const label = shareButton.querySelector("span");
          const oldText = label?.textContent || "分享";
          const url = new URL(shareButton.dataset.url || window.location.href, window.location.origin).toString();
          await navigator.clipboard.writeText(url);
          if (label) label.textContent = "✅ 已复制";
          setTimeout(() => {
            if (label) label.textContent = oldText;
          }, 2000);
        }
      });
      initExpandablePosts();
    })();
  </script>
    """
    if not user:
        composer_script = ""
    feed_html_parts = []
    for item in feed_items:
        feed_html_parts.append(render_home_feed_card(item, current_user=user, is_admin=current_user_is_admin))
    feed_html = "".join(feed_html_parts)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>meetseek - AI 技术与商业变现社区</title>
  <meta name="description" content="meetseek 是面向 AI 技术、商业变现、工具效率和提示词创作的轻量社区与工具入口，整合 AI 工具箱、提示词库和会员积分体系。">
  <meta name="robots" content="index,follow,max-image-preview:large">
  <link rel="canonical" href="{MAIN_BASE_URL}/">
  <meta property="og:locale" content="zh_CN">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="meetseek">
  <meta property="og:title" content="meetseek - AI 技术与商业变现社区">
  <meta property="og:description" content="整合 AI 工具箱、提示词库、会员积分和轻量社区的信息流入口。">
  <meta property="og:url" content="{MAIN_BASE_URL}/">
  <meta name="twitter:card" content="summary">
  {json_ld}
  <script src="https://cdn.tailwindcss.com"></script>
  <script defer src="https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/@editorjs/editorjs@latest"></script>
  <script src="https://cdn.jsdelivr.net/npm/@editorjs/header@latest"></script>
  <script src="https://cdn.jsdelivr.net/npm/@editorjs/list@latest"></script>
  <script src="https://cdn.jsdelivr.net/npm/@editorjs/quote@latest"></script>
  <script src="https://cdn.jsdelivr.net/npm/@editorjs/image@latest"></script>
  <script src="https://cdn.jsdelivr.net/npm/@editorjs/link@latest"></script>
  <style>
    body {{ letter-spacing: 0; }}
    .glass {{ background: rgba(255,255,255,.72); backdrop-filter: blur(18px); border: 1px solid rgba(226,232,240,.74); }}
    .soft {{ box-shadow: 0 22px 80px rgba(15, 23, 42, .07); }}
    #home-article-editor .codex-editor__redactor {{ padding-bottom: 120px !important; }}
    #home-article-editor .ce-block__content,
    #home-article-editor .ce-toolbar__content {{ max-width: 100%; }}
    #home-article-editor .ce-paragraph {{ line-height: 1.9; font-size: 16px; }}
  </style>
</head>
<body class="min-h-screen bg-[#f8fafc] text-slate-950" data-current-user-id="{current_user_id}" data-current-user-admin="{current_user_admin_attr}">
  <main class="mx-auto flex min-h-screen max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6 md:flex-row">
    <aside class="hidden w-64 shrink-0 md:block">
      <div class="sticky top-4 flex h-[calc(100vh-2rem)] flex-col rounded-2xl border border-white/40 bg-white/60 p-4 shadow-sm backdrop-blur-md">
        <section>
          <a href="/" class="mb-6 flex items-center gap-3 rounded-2xl bg-white/55 p-3">
            <span class="grid h-11 w-11 place-items-center rounded-xl bg-orange-600 text-lg font-black text-white">M</span>
            <span>
              <span class="block text-xl font-black">meetseek</span>
              <span class="block text-xs font-bold text-slate-400">AI 社区入口</span>
            </span>
          </a>
          <nav class="grid gap-1">
            <button type="button" data-search-trigger onclick="openSearch()" class="mb-3 flex w-full items-center justify-between rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-500 transition-colors hover:bg-slate-100"><span>🔍 搜索内容与工具...</span><kbd class="rounded border border-slate-200 bg-white px-1.5 py-0.5 font-mono text-[10px] text-slate-400">⌘ K</kbd></button>
            <a class="rounded-lg bg-orange-50 px-4 py-3 text-sm font-black text-orange-600 transition-colors hover:bg-slate-100/50" href="/">🏠 探索大厅</a>
            <a class="rounded-lg px-4 py-3 text-sm font-black text-slate-600 transition-colors hover:bg-slate-100/50 hover:text-slate-950" href="#home-compose">✍️ 发文</a>
            <a class="rounded-lg px-4 py-3 text-sm font-black text-slate-600 transition-colors hover:bg-slate-100/50 hover:text-slate-950" href="{PROMPTS_BASE_URL}">✨ 提示词库</a>
            <a class="rounded-lg px-4 py-3 text-sm font-black text-slate-600 transition-colors hover:bg-slate-100/50 hover:text-slate-950" href="{TOOLS_BASE_URL}">🧰 AI 工具箱</a>
            <a class="rounded-lg px-4 py-3 text-sm font-black text-slate-600 transition-colors hover:bg-slate-100/50 hover:text-slate-950" href="/tools/identity-builder">🧬 JSON 身份锁</a>
            <a class="rounded-lg px-4 py-3 text-sm font-black text-slate-600 transition-colors hover:bg-slate-100/50 hover:text-slate-950" href="/business">💼 商业变现</a>
            <a class="rounded-lg px-4 py-3 text-sm font-black text-slate-600 transition-colors hover:bg-slate-100/50 hover:text-slate-950" href="/account">📝 我的帖子</a>
          </nav>
        </section>
        <section class="mt-6 rounded-2xl border border-white/50 bg-white/45 p-5">
          <p class="text-xs font-black uppercase tracking-wide text-slate-400">频道</p>
          <div class="mt-4 grid gap-3 text-sm font-black text-slate-600">
            <a class="flex items-center justify-between" href="/ai-tools"><span>AI 工具</span><span class="h-2 w-2 rounded-full bg-blue-400"></span></a>
            <a class="flex items-center justify-between" href="{PROMPTS_BASE_URL}"><span>提示词</span><span class="h-2 w-2 rounded-full bg-emerald-400"></span></a>
            <a class="flex items-center justify-between" href="/business"><span>商业变现</span><span class="h-2 w-2 rounded-full bg-orange-400"></span></a>
            <a class="flex items-center justify-between" href="/build"><span>建站与 SEO</span><span class="h-2 w-2 rounded-full bg-violet-400"></span></a>
          </div>
        </section>
        <section class="mt-auto rounded-2xl border border-white/50 bg-white/65 p-4">
          <p class="text-xs font-black uppercase tracking-wide text-slate-400">当前账号</p>
          <div class="mt-3 flex items-center gap-3">
            {sidebar_user_avatar}
            <div class="min-w-0">
              <p class="truncate text-sm font-black text-slate-950">{user_name or "未登录"}</p>
              <p class="truncate text-xs font-bold text-slate-400">{html_escape(user_badge)}</p>
            </div>
          </div>
          <a class="mt-4 block rounded-2xl bg-slate-950 px-4 py-3 text-center text-sm font-black text-white transition hover:bg-orange-600" href="{sidebar_account_href}">{sidebar_account_label}</a>
        </section>
      </div>
    </aside>
    <section class="min-w-0 flex-1">
      {composer_html}
      <section class="mt-5 rounded-2xl border border-slate-100 bg-white p-2 shadow-sm">
        <div class="flex items-center gap-2 overflow-x-auto text-sm font-black text-slate-600">
          <a class="rounded-2xl bg-orange-50 px-4 py-3 text-orange-600" href="/">为你推荐</a>
          <a class="rounded-2xl px-4 py-3 transition hover:bg-slate-50" href="/ai-tools">AI 工具</a>
          <a class="rounded-2xl px-4 py-3 transition hover:bg-slate-50" href="{PROMPTS_BASE_URL}">提示词</a>
          <a class="rounded-2xl px-4 py-3 transition hover:bg-slate-50" href="/business">商业变现</a>
        </div>
      </section>
      <section class="mt-5">
        <div class="rounded-2xl border border-slate-100 bg-white px-5 py-4 shadow-sm">
          <h1 class="text-xl font-black">社区动态</h1>
          <p class="mt-1 text-sm leading-relaxed text-slate-500">AI 工具、提示词、商业变现和建站经验的单列信息流。</p>
        </div>
        <div id="home-feed-list" class="mt-4 grid gap-4">
          {feed_html}
        </div>
      </section>
    </section>
  </main>
  {spotlight_search_markup()}
  {composer_script}
</body>
</html>"""


PLUGIN_LANGS: dict[str, dict[str, str]] = {
    "zh": {"name": "中文", "hero": "让你的浏览器更强大", "sub": "发现 AI、效率、开发、隐私和创作插件，也可以直达 MeetSeek 工具箱、提示词库和社区。", "search": "搜索插件、工具、AI 助手...", "featured": "精选插件", "trending": "本周趋势", "new": "新鲜上架", "tools": "AI 工具箱", "prompts": "提示词库", "community": "社区动态", "signin": "登录", "add": "添加到浏览器", "overview": "概览", "features": "功能", "reviews": "评价", "details": "详情", "verified": "已验证发布者"},
    "en": {"name": "English", "hero": "Make your browser more powerful", "sub": "Discover AI, productivity, developer, privacy and creative extensions, plus quick access to MeetSeek tools and prompts.", "search": "Search extensions, tools, AI agents...", "featured": "Featured Extensions", "trending": "Trending This Week", "new": "New & Noteworthy", "tools": "AI Toolbox", "prompts": "Prompt Library", "community": "Community Feed", "signin": "Sign in", "add": "Add to Browser", "overview": "Overview", "features": "Features", "reviews": "Reviews", "details": "Details", "verified": "Verified publisher"},
    "fr": {"name": "Français", "hero": "Rendez votre navigateur plus puissant", "sub": "Découvrez des extensions IA, productivité, développement, confidentialité et création.", "search": "Rechercher extensions, outils, agents IA...", "featured": "Extensions sélectionnées", "trending": "Tendances de la semaine", "new": "Nouveautés", "tools": "Boîte à outils IA", "prompts": "Bibliothèque de prompts", "community": "Communauté", "signin": "Connexion", "add": "Ajouter au navigateur", "overview": "Aperçu", "features": "Fonctions", "reviews": "Avis", "details": "Détails", "verified": "Éditeur vérifié"},
    "de": {"name": "Deutsch", "hero": "Mach deinen Browser stärker", "sub": "Entdecke KI-, Produktivitäts-, Entwickler-, Datenschutz- und Kreativ-Erweiterungen.", "search": "Erweiterungen, Tools, KI-Agenten suchen...", "featured": "Empfohlene Erweiterungen", "trending": "Trends der Woche", "new": "Neu & bemerkenswert", "tools": "KI-Toolbox", "prompts": "Prompt-Bibliothek", "community": "Community", "signin": "Anmelden", "add": "Zum Browser hinzufügen", "overview": "Übersicht", "features": "Funktionen", "reviews": "Bewertungen", "details": "Details", "verified": "Verifizierter Anbieter"},
    "pt": {"name": "Português", "hero": "Deixe seu navegador mais poderoso", "sub": "Descubra extensões de IA, produtividade, desenvolvimento, privacidade e criação.", "search": "Buscar extensões, ferramentas, agentes de IA...", "featured": "Extensões em destaque", "trending": "Tendências da semana", "new": "Novidades", "tools": "Caixa de ferramentas IA", "prompts": "Biblioteca de prompts", "community": "Comunidade", "signin": "Entrar", "add": "Adicionar ao navegador", "overview": "Visão geral", "features": "Recursos", "reviews": "Avaliações", "details": "Detalhes", "verified": "Editor verificado"},
    "es": {"name": "Español", "hero": "Haz tu navegador más potente", "sub": "Descubre extensiones de IA, productividad, desarrollo, privacidad y creatividad.", "search": "Buscar extensiones, herramientas, agentes IA...", "featured": "Extensiones destacadas", "trending": "Tendencias de la semana", "new": "Novedades", "tools": "Caja de herramientas IA", "prompts": "Biblioteca de prompts", "community": "Comunidad", "signin": "Iniciar sesión", "add": "Añadir al navegador", "overview": "Resumen", "features": "Funciones", "reviews": "Reseñas", "details": "Detalles", "verified": "Editor verificado"},
    "ja": {"name": "日本語", "hero": "ブラウザをもっと強力に", "sub": "AI、生産性、開発、プライバシー、クリエイティブ拡張を見つけましょう。", "search": "拡張機能、ツール、AI エージェントを検索...", "featured": "注目の拡張機能", "trending": "今週のトレンド", "new": "新着", "tools": "AI ツール箱", "prompts": "プロンプト庫", "community": "コミュニティ", "signin": "ログイン", "add": "ブラウザに追加", "overview": "概要", "features": "機能", "reviews": "レビュー", "details": "詳細", "verified": "認証済み発行者"},
    "ko": {"name": "한국어", "hero": "브라우저를 더 강력하게", "sub": "AI, 생산성, 개발, 개인정보, 창작 확장 프로그램을 발견하세요.", "search": "확장 프로그램, 도구, AI 에이전트 검색...", "featured": "추천 확장 프로그램", "trending": "이번 주 인기", "new": "새로운 도구", "tools": "AI 도구함", "prompts": "프롬프트 라이브러리", "community": "커뮤니티", "signin": "로그인", "add": "브라우저에 추가", "overview": "개요", "features": "기능", "reviews": "리뷰", "details": "상세", "verified": "인증된 게시자"},
    "ar": {"name": "العربية", "hero": "اجعل متصفحك أكثر قوة", "sub": "اكتشف إضافات الذكاء الاصطناعي والإنتاجية والتطوير والخصوصية والإبداع.", "search": "ابحث عن الإضافات والأدوات ووكلاء الذكاء الاصطناعي...", "featured": "إضافات مميزة", "trending": "الأكثر رواجًا هذا الأسبوع", "new": "جديد ومميز", "tools": "صندوق أدوات الذكاء الاصطناعي", "prompts": "مكتبة الأوامر", "community": "المجتمع", "signin": "تسجيل الدخول", "add": "أضف إلى المتصفح", "overview": "نظرة عامة", "features": "الميزات", "reviews": "المراجعات", "details": "التفاصيل", "verified": "ناشر موثوق"},
}

PLUGIN_CATEGORIES = [("AI & ChatGPT", "ai"), ("Productivity", "productivity"), ("Ad Blocker", "privacy"), ("Developer Tools", "developer"), ("Privacy", "privacy"), ("Shopping", "shopping")]
PLUGIN_ITEMS = [
    {"slug": "meetseek-prompt-copilot", "title": "MeetSeek Prompt Copilot", "desc": "Capture pages, rewrite prompts, and save reusable AI workflows.", "category": "AI & ChatGPT", "rating": "4.9", "users": "82K", "icon": "M", "accent": "from-violet-600 to-blue-500"},
    {"slug": "adguard-adblocker", "title": "AdGuard AdBlocker", "desc": "Unmatched ad blocking against advertising and pop-ups.", "category": "Privacy", "rating": "4.7", "users": "1.5M", "icon": "✓", "accent": "from-emerald-500 to-green-700"},
    {"slug": "dark-reader", "title": "Dark Reader", "desc": "Dark mode for every website with flexible brightness controls.", "category": "Accessibility", "rating": "4.7", "users": "5M", "icon": "◐", "accent": "from-slate-900 to-blue-950"},
    {"slug": "clip-to-notion", "title": "Clip to Notion", "desc": "Save pages, articles and highlights to your knowledge base.", "category": "Productivity", "rating": "4.6", "users": "683K", "icon": "N", "accent": "from-slate-700 to-slate-950"},
    {"slug": "google-translate", "title": "Google Translate", "desc": "Translate pages and selected text with one click.", "category": "Productivity", "rating": "4.6", "users": "452K", "icon": "G", "accent": "from-blue-500 to-cyan-400"},
    {"slug": "monica-ai", "title": "Monica AI Assistant", "desc": "All-in-one AI assistant on any web page.", "category": "AI & ChatGPT", "rating": "4.7", "users": "21K", "icon": "✦", "accent": "from-fuchsia-500 to-violet-600"},
]

PLUGIN_CATALOG_ITEMS = PLUGIN_ITEMS + [
    {"slug": "grammarly", "title": "Grammarly", "desc": "AI writing assistant for clearer, stronger everyday writing.", "category": "AI & ChatGPT", "rating": "4.8", "users": "987K", "icon": "G", "accent": "from-emerald-500 to-teal-500"},
    {"slug": "tampermonkey", "title": "Tampermonkey", "desc": "Run userscripts and customize the web to match your workflow.", "category": "Developer Tools", "rating": "4.8", "users": "912K", "icon": "●", "accent": "from-slate-900 to-slate-700"},
    {"slug": "web-developer", "title": "Web Developer", "desc": "Add a toolbar packed with practical developer utilities.", "category": "Developer Tools", "rating": "4.7", "users": "433K", "icon": "⚙", "accent": "from-slate-700 to-slate-950"},
    {"slug": "honey", "title": "Honey", "desc": "Automatically find and apply coupon codes while shopping.", "category": "Shopping", "rating": "4.6", "users": "345K", "icon": "h", "accent": "from-orange-500 to-amber-500"},
    {"slug": "save-to-pocket", "title": "Save to Pocket", "desc": "Save articles and videos to view later on any device.", "category": "Productivity", "rating": "4.7", "users": "321K", "icon": "♥", "accent": "from-rose-500 to-red-500"},
    {"slug": "ublock-origin", "title": "uBlock Origin", "desc": "Efficient, powerful ad blocker with flexible filters.", "category": "Privacy", "rating": "4.8", "users": "1.6M", "icon": "u", "accent": "from-red-700 to-red-900"},
    {"slug": "lastpass", "title": "LastPass", "desc": "Password manager and form filler for everyday browsing.", "category": "Productivity", "rating": "4.4", "users": "280K", "icon": "•••", "accent": "from-red-500 to-orange-500"},
    {"slug": "awesome-screenshot", "title": "Awesome Screenshot", "desc": "Screenshot, annotate and share pages with ease.", "category": "Productivity", "rating": "4.7", "users": "567K", "icon": "◎", "accent": "from-pink-500 to-violet-500"},
    {"slug": "momentum", "title": "Momentum", "desc": "Replace the new tab page with a calm personal dashboard.", "category": "Productivity", "rating": "4.6", "users": "235K", "icon": "m", "accent": "from-teal-500 to-cyan-500"},
    {"slug": "page-assist", "title": "Page Assist", "desc": "Summarize, rewrite and translate any page with AI.", "category": "AI & ChatGPT", "rating": "4.7", "users": "186K", "icon": "✣", "accent": "from-purple-500 to-indigo-500"},
    {"slug": "onetab", "title": "OneTab", "desc": "Save up to 95% memory and reduce tab clutter.", "category": "Productivity", "rating": "4.6", "users": "1.1M", "icon": "◆", "accent": "from-blue-500 to-sky-500"},
    {"slug": "bitwarden", "title": "Bitwarden", "desc": "Free password manager for all your devices.", "category": "Privacy", "rating": "4.7", "users": "412K", "icon": "◈", "accent": "from-blue-700 to-indigo-700"},
]


def seed_default_plugins(conn: sqlite3.Connection) -> None:
    timestamp = int(now())
    featured_slugs = {item["slug"] for item in PLUGIN_ITEMS[:3]}
    trending_slugs = {item["slug"] for item in PLUGIN_ITEMS[:5]}
    new_slugs = {item["slug"] for item in PLUGIN_ITEMS[3:6]}
    for index, item in enumerate(PLUGIN_CATALOG_ITEMS):
        conn.execute(
            """
            INSERT OR IGNORE INTO plugins(
                slug, title, description, category, rating, users, icon, accent,
                short_description, long_description, version, install_url,
                chrome_store_url, edge_store_url, direct_url, icon_url, tags,
                developer_name, developer_email, submitter_id, review_note,
                website_url, support_url, cover_image, gallery_images, status,
                is_featured, is_trending, is_new, sort_order, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["slug"],
                item["title"],
                item["desc"],
                item["category"],
                item.get("rating", "4.7"),
                item.get("users", ""),
                item.get("icon", "◆"),
                item.get("accent", "from-violet-600 to-blue-500"),
                item["desc"],
                item["desc"],
                "1.0.0",
                "",
                "",
                "",
                "",
                "",
                "",
                "MeetSeek",
                "",
                0,
                "",
                "",
                "",
                "",
                "",
                "published",
                1 if item["slug"] in featured_slugs else 0,
                1 if item["slug"] in trending_slugs else 0,
                1 if item["slug"] in new_slugs else 0,
                index,
                timestamp,
                timestamp,
            ),
        )


def plugin_row_to_item(row: sqlite3.Row) -> dict[str, Any]:
    keys = set(row.keys())
    short_description = str(row["short_description"] or "") if "short_description" in keys else ""
    long_description = str(row["long_description"] or "") if "long_description" in keys else ""
    description = str(row["description"] or "")
    gallery_raw = str(row["gallery_images"] or "")
    try:
        gallery_images = json.loads(gallery_raw) if gallery_raw.strip().startswith("[") else []
    except json.JSONDecodeError:
        gallery_images = []
    if not gallery_images:
        gallery_images = [part.strip() for part in re.split(r"[\n,]+", gallery_raw) if part.strip()]
    return {
        "id": int(row["id"]),
        "slug": str(row["slug"]),
        "title": str(row["title"]),
        "desc": short_description or description,
        "description": description,
        "short_description": short_description,
        "long_description": long_description or description,
        "category": str(row["category"] or "AI & ChatGPT"),
        "rating": str(row["rating"] or "4.7"),
        "users": str(row["users"] or ""),
        "icon": str(row["icon"] or "◆"),
        "accent": str(row["accent"] or "from-violet-600 to-blue-500"),
        "version": str(row["version"] or "1.0.0") if "version" in keys else "1.0.0",
        "install_url": str(row["install_url"] or "") if "install_url" in keys else "",
        "chrome_store_url": str(row["chrome_store_url"] or "") if "chrome_store_url" in keys else "",
        "edge_store_url": str(row["edge_store_url"] or "") if "edge_store_url" in keys else "",
        "direct_url": str(row["direct_url"] or "") if "direct_url" in keys else "",
        "icon_url": str(row["icon_url"] or "") if "icon_url" in keys else "",
        "tags": str(row["tags"] or "") if "tags" in keys else "",
        "developer_name": str(row["developer_name"] or "") if "developer_name" in keys else "",
        "developer_email": str(row["developer_email"] or "") if "developer_email" in keys else "",
        "submitter_id": int(row["submitter_id"] or 0) if "submitter_id" in keys else 0,
        "review_note": str(row["review_note"] or "") if "review_note" in keys else "",
        "website_url": str(row["website_url"] or ""),
        "support_url": str(row["support_url"] or ""),
        "cover_image": str(row["cover_image"] or ""),
        "gallery_images": gallery_images,
        "status": str(row["status"] or "published"),
        "is_featured": int(row["is_featured"] or 0),
        "is_trending": int(row["is_trending"] or 0),
        "is_new": int(row["is_new"] or 0),
        "sort_order": int(row["sort_order"] or 0),
    }


def plugin_items_from_db(include_hidden: bool = False) -> list[dict[str, Any]]:
    try:
        with db() as conn:
            where = "" if include_hidden else "WHERE status = 'published'"
            rows = conn.execute(
                f"""
                SELECT * FROM plugins
                {where}
                ORDER BY sort_order ASC, id ASC
                """
            ).fetchall()
            if rows:
                return [plugin_row_to_item(row) for row in rows]
    except sqlite3.Error:
        pass
    return [dict(item) for item in PLUGIN_CATALOG_ITEMS]


def plugin_pick(items: list[dict[str, Any]], flag: str, fallback_slice: slice) -> list[dict[str, Any]]:
    picked = [item for item in items if int(item.get(flag, 0) or 0)]
    return picked or items[fallback_slice]

PLUGIN_UI: dict[str, dict[str, str]] = {
    "zh": {
        "home": "首页", "discover": "发现", "top_charts": "排行榜", "categories": "分类", "all_extensions": "全部插件", "new_noteworthy": "新品推荐",
        "search_button": "搜索", "view_all": "查看全部", "other_languages": "其他语言",
        "creator_label": "给创作者", "creator_title": "发布插件、提示词和 AI 工作流。", "submit": "提交插件",
        "editor_picks": "编辑精选", "workflow_title": "MeetSeek 工作流捷径",
        "workflow_desc": "把浏览器插件、提示词、AI 工具、文章检测和创作者工作流连接起来。",
        "about": "关于", "share": "分享", "related": "相关插件", "latest": "最新公告",
        "latest_desc": "已优化与 MeetSeek 工具箱、提示词库和创作者工作流的连接体验。",
        "trust": "信任与安全", "verified_practices": "已验证发布者", "privacy": "隐私实践透明", "offline": "支持离线能力",
        "version": "版本", "category": "分类", "languages": "语言", "users": "用户",
    },
    "en": {
        "home": "Home", "discover": "Discover", "top_charts": "Top Charts", "categories": "Categories", "all_extensions": "All Extensions", "new_noteworthy": "New & Noteworthy",
        "search_button": "Search", "view_all": "View all", "other_languages": "Other languages",
        "creator_label": "For creators", "creator_title": "Publish plugins, prompts and AI workflows.", "submit": "Submit Extension",
        "editor_picks": "Editor's Picks", "workflow_title": "MeetSeek workflow shortcuts",
        "workflow_desc": "Connect browser extensions with prompts, AI tools, article checks and creator workflows.",
        "about": "About", "share": "Share", "related": "Related", "latest": "Latest Announcement",
        "latest_desc": "Improved integration with MeetSeek tools, prompt library and creator workflows.",
        "trust": "Trust & Safety", "verified_practices": "Verified publisher", "privacy": "Privacy practices", "offline": "Works offline where possible",
        "version": "Version", "category": "Category", "languages": "Languages", "users": "users",
    },
}

PLUGIN_UI.update({
    "fr": {"home": "Accueil", "top_charts": "Classements", "categories": "Catégories", "new_noteworthy": "Nouveautés", "discover": "Découvrir", "search_button": "Rechercher", "view_all": "Tout voir", "other_languages": "Autres langues", "creator_label": "Pour les créateurs", "creator_title": "Publiez plugins, prompts et workflows IA.", "submit": "Soumettre", "editor_picks": "Choix de la rédaction", "workflow_title": "Raccourcis MeetSeek", "workflow_desc": "Reliez extensions, prompts, outils IA et workflows.", "about": "À propos de ", "share": "Partager", "related": "Extensions liées", "latest": "Annonce récente", "latest_desc": "Intégration améliorée avec les outils MeetSeek.", "trust": "Confiance et sécurité", "verified_practices": "Éditeur vérifié", "privacy": "Pratiques de confidentialité", "offline": "Fonctionne hors ligne si possible", "version": "Version", "category": "Catégorie", "languages": "Langues", "users": "utilisateurs"},
    "de": {"home": "Startseite", "top_charts": "Charts", "categories": "Kategorien", "new_noteworthy": "Neuheiten", "discover": "Entdecken", "search_button": "Suchen", "view_all": "Alle ansehen", "other_languages": "Weitere Sprachen", "creator_label": "Für Creator", "creator_title": "Veröffentliche Plugins, Prompts und KI-Workflows.", "submit": "Einreichen", "editor_picks": "Empfehlungen", "workflow_title": "MeetSeek Schnellzugriffe", "workflow_desc": "Verbinde Erweiterungen, Prompts, KI-Tools und Workflows.", "about": "Über ", "share": "Teilen", "related": "Ähnliche Plugins", "latest": "Neueste Meldung", "latest_desc": "Verbesserte Integration mit MeetSeek Tools.", "trust": "Vertrauen & Sicherheit", "verified_practices": "Verifizierter Anbieter", "privacy": "Datenschutzpraktiken", "offline": "Offlinefähig, wenn möglich", "version": "Version", "category": "Kategorie", "languages": "Sprachen", "users": "Nutzer"},
    "pt": {"home": "Início", "top_charts": "Mais populares", "categories": "Categorias", "new_noteworthy": "Novidades", "discover": "Descobrir", "search_button": "Buscar", "view_all": "Ver tudo", "other_languages": "Outros idiomas", "creator_label": "Para criadores", "creator_title": "Publique plugins, prompts e fluxos de IA.", "submit": "Enviar", "editor_picks": "Escolhas do editor", "workflow_title": "Atalhos MeetSeek", "workflow_desc": "Conecte extensões, prompts, ferramentas de IA e fluxos.", "about": "Sobre ", "share": "Compartilhar", "related": "Plugins relacionados", "latest": "Último anúncio", "latest_desc": "Integração melhorada com as ferramentas MeetSeek.", "trust": "Confiança e segurança", "verified_practices": "Editor verificado", "privacy": "Práticas de privacidade", "offline": "Funciona offline quando possível", "version": "Versão", "category": "Categoria", "languages": "Idiomas", "users": "usuários"},
    "es": {"home": "Inicio", "top_charts": "Listas", "categories": "Categorías", "new_noteworthy": "Novedades", "discover": "Descubrir", "search_button": "Buscar", "view_all": "Ver todo", "other_languages": "Otros idiomas", "creator_label": "Para creadores", "creator_title": "Publica plugins, prompts y flujos de IA.", "submit": "Enviar", "editor_picks": "Selección editorial", "workflow_title": "Accesos MeetSeek", "workflow_desc": "Conecta extensiones, prompts, herramientas IA y flujos.", "about": "Acerca de ", "share": "Compartir", "related": "Plugins relacionados", "latest": "Último anuncio", "latest_desc": "Integración mejorada con herramientas MeetSeek.", "trust": "Confianza y seguridad", "verified_practices": "Editor verificado", "privacy": "Prácticas de privacidad", "offline": "Funciona sin conexión cuando es posible", "version": "Versión", "category": "Categoría", "languages": "Idiomas", "users": "usuarios"},
    "ja": {"home": "ホーム", "top_charts": "ランキング", "categories": "カテゴリ", "new_noteworthy": "新着注目", "discover": "見つける", "search_button": "検索", "view_all": "すべて見る", "other_languages": "その他の言語", "creator_label": "クリエイター向け", "creator_title": "プラグイン、プロンプト、AI ワークフローを公開。", "submit": "送信", "editor_picks": "編集部おすすめ", "workflow_title": "MeetSeek ショートカット", "workflow_desc": "拡張機能、プロンプト、AI ツール、ワークフローを接続。", "about": "概要：", "share": "共有", "related": "関連プラグイン", "latest": "最新のお知らせ", "latest_desc": "MeetSeek ツールとの連携を改善しました。", "trust": "信頼と安全", "verified_practices": "認証済み発行者", "privacy": "プライバシー対応", "offline": "可能な範囲でオフライン対応", "version": "バージョン", "category": "カテゴリ", "languages": "言語", "users": "ユーザー"},
    "ko": {"home": "홈", "top_charts": "순위", "categories": "카테고리", "new_noteworthy": "신규 추천", "discover": "탐색", "search_button": "검색", "view_all": "전체 보기", "other_languages": "다른 언어", "creator_label": "크리에이터용", "creator_title": "플러그인, 프롬프트, AI 워크플로를 게시하세요.", "submit": "제출", "editor_picks": "에디터 추천", "workflow_title": "MeetSeek 바로가기", "workflow_desc": "확장 프로그램, 프롬프트, AI 도구와 워크플로를 연결합니다.", "about": "소개 ", "share": "공유", "related": "관련 플러그인", "latest": "최근 소식", "latest_desc": "MeetSeek 도구와의 연결이 개선되었습니다.", "trust": "신뢰와 안전", "verified_practices": "인증된 게시자", "privacy": "개인정보 처리", "offline": "가능한 경우 오프라인 지원", "version": "버전", "category": "카테고리", "languages": "언어", "users": "사용자"},
    "ar": {"home": "الرئيسية", "top_charts": "الأعلى", "categories": "الفئات", "new_noteworthy": "الجديد", "discover": "اكتشف", "search_button": "بحث", "view_all": "عرض الكل", "other_languages": "لغات أخرى", "creator_label": "للمبدعين", "creator_title": "انشر الإضافات والأوامر وسير عمل الذكاء الاصطناعي.", "submit": "إرسال إضافة", "editor_picks": "اختيارات التحرير", "workflow_title": "اختصارات MeetSeek", "workflow_desc": "اربط الإضافات بالأوامر وأدوات الذكاء الاصطناعي وسير العمل.", "about": "حول ", "share": "مشاركة", "related": "إضافات ذات صلة", "latest": "آخر إعلان", "latest_desc": "تم تحسين التكامل مع أدوات MeetSeek.", "trust": "الثقة والأمان", "verified_practices": "ناشر موثوق", "privacy": "ممارسات الخصوصية", "offline": "يعمل دون اتصال عند الإمكان", "version": "الإصدار", "category": "الفئة", "languages": "اللغات", "users": "مستخدم"},
})

PLUGIN_CATEGORY_TEXT: dict[str, dict[str, str]] = {
    "zh": {
        "AI & ChatGPT": "AI 与 ChatGPT",
        "Productivity": "效率工具",
        "Ad Blocker": "广告拦截",
        "Developer Tools": "开发工具",
        "Privacy": "隐私安全",
        "Shopping": "购物",
        "Accessibility": "辅助功能",
    }
}

PLUGIN_ITEM_TEXT: dict[str, dict[str, dict[str, str]]] = {
    "zh": {
        "meetseek-prompt-copilot": {"title": "MeetSeek 提示词助手", "desc": "采集网页、改写提示词，并保存可复用的 AI 工作流。"},
        "adguard-adblocker": {"title": "AdGuard 广告拦截器", "desc": "拦截网页广告、弹窗和干扰内容，让浏览更清爽。"},
        "dark-reader": {"title": "Dark Reader 深色模式", "desc": "为任意网站开启深色模式，并支持亮度与对比度调节。"},
        "clip-to-notion": {"title": "Notion 剪藏助手", "desc": "把网页、文章和高亮内容保存到你的知识库。"},
        "google-translate": {"title": "Google 翻译", "desc": "一键翻译网页和选中文本。"},
        "monica-ai": {"title": "Monica AI 助手", "desc": "在任意网页使用的一体化 AI 助手。"},
        "grammarly": {"title": "Grammarly 写作助手", "desc": "帮你写出更清晰、更自然的英文内容。"},
        "tampermonkey": {"title": "Tampermonkey 脚本管理", "desc": "运行用户脚本，自定义你的网页工作流。"},
        "web-developer": {"title": "Web Developer 工具栏", "desc": "为开发者提供常用网页调试工具。"},
        "honey": {"title": "Honey 优惠助手", "desc": "购物时自动查找并应用优惠码。"},
        "save-to-pocket": {"title": "Pocket 稍后读", "desc": "保存文章和视频，稍后在任意设备阅读。"},
        "ublock-origin": {"title": "uBlock Origin", "desc": "高效、强大的广告拦截器。"},
        "lastpass": {"title": "LastPass 密码管理", "desc": "保存密码并自动填写常用表单。"},
        "awesome-screenshot": {"title": "Awesome Screenshot", "desc": "截图、标注并快速分享网页内容。"},
        "momentum": {"title": "Momentum 新标签页", "desc": "把新标签页变成安静的个人仪表盘。"},
        "page-assist": {"title": "Page Assist AI", "desc": "用 AI 总结、改写和翻译网页。"},
        "onetab": {"title": "OneTab 标签整理", "desc": "节省内存并减少浏览器标签混乱。"},
        "bitwarden": {"title": "Bitwarden 密码库", "desc": "免费开源的跨设备密码管理器。"},
    }
}

PLUGIN_LIST_UI = {
    "zh": {
        "all_extensions": "全部插件",
        "subtitle": "发现 3,245 个插件，增强你的浏览器体验。",
        "total_extensions": "插件总数",
        "new_this_week": "本周新增",
        "active_users": "活跃用户",
        "average_rating": "平均评分",
        "filters": "筛选",
        "most_popular": "最受欢迎",
        "highest_rated": "评分最高",
        "newest": "最新上架",
        "collections": "合集",
        "hub": "插件中心",
        "hub_desc": "提升浏览体验所需的插件、工具和工作流。",
        "extension_marketplace": "插件市场",
        "search_extensions": "搜索插件...",
        "extensions": "个插件",
        "all": "全部",
        "more": "更多",
    },
    "en": {
        "all_extensions": "All Extensions",
        "subtitle": "Discover 3,245 extensions to supercharge your browsing experience.",
        "total_extensions": "Total Extensions",
        "new_this_week": "New This Week",
        "active_users": "Active Users",
        "average_rating": "Average Rating",
        "filters": "Filters",
        "most_popular": "Most Popular",
        "highest_rated": "Highest Rated",
        "newest": "Newest",
        "collections": "Collections",
        "hub": "Extensions Hub",
        "hub_desc": "Everything you need to enhance your browsing experience.",
        "extension_marketplace": "Extension Marketplace",
        "search_extensions": "Search extensions...",
        "extensions": "extensions",
        "all": "All",
        "more": "More",
    },
}

PLUGIN_UI["fr"]["all_extensions"] = "Toutes les extensions"
PLUGIN_UI["de"]["all_extensions"] = "Alle Erweiterungen"
PLUGIN_UI["pt"]["all_extensions"] = "Todas as extensões"
PLUGIN_UI["es"]["all_extensions"] = "Todas las extensiones"
PLUGIN_UI["ja"]["all_extensions"] = "すべての拡張機能"
PLUGIN_UI["ko"]["all_extensions"] = "전체 확장 프로그램"
PLUGIN_UI["ar"]["all_extensions"] = "كل الإضافات"

PLUGIN_LIST_UI.update({
    "fr": {**PLUGIN_LIST_UI["en"], "all_extensions": "Toutes les extensions", "subtitle": "Découvrez 3 245 extensions pour améliorer votre navigation.", "total_extensions": "Extensions", "new_this_week": "Nouvelles cette semaine", "active_users": "Utilisateurs actifs", "average_rating": "Note moyenne", "filters": "Filtres", "most_popular": "Les plus populaires", "highest_rated": "Les mieux notées", "newest": "Nouvelles", "collections": "Collections", "hub": "Hub extensions", "hub_desc": "Tout pour améliorer votre expérience de navigation.", "extension_marketplace": "Marché des extensions", "search_extensions": "Rechercher des extensions...", "extensions": "extensions", "all": "Tout", "more": "Plus"},
    "de": {**PLUGIN_LIST_UI["en"], "all_extensions": "Alle Erweiterungen", "subtitle": "Entdecke 3.245 Erweiterungen für ein besseres Browser-Erlebnis.", "total_extensions": "Erweiterungen", "new_this_week": "Neu diese Woche", "active_users": "Aktive Nutzer", "average_rating": "Durchschnittsbewertung", "filters": "Filter", "most_popular": "Am beliebtesten", "highest_rated": "Bestbewertet", "newest": "Neueste", "collections": "Sammlungen", "hub": "Erweiterungs-Hub", "hub_desc": "Alles für ein besseres Browser-Erlebnis.", "extension_marketplace": "Erweiterungsmarktplatz", "search_extensions": "Erweiterungen suchen...", "extensions": "Erweiterungen", "all": "Alle", "more": "Mehr"},
    "pt": {**PLUGIN_LIST_UI["en"], "all_extensions": "Todas as extensões", "subtitle": "Descubra 3.245 extensões para melhorar sua navegação.", "total_extensions": "Extensões", "new_this_week": "Novas nesta semana", "active_users": "Usuários ativos", "average_rating": "Nota média", "filters": "Filtros", "most_popular": "Mais populares", "highest_rated": "Melhor avaliadas", "newest": "Mais recentes", "collections": "Coleções", "hub": "Hub de extensões", "hub_desc": "Tudo para aprimorar sua experiência no navegador.", "extension_marketplace": "Mercado de extensões", "search_extensions": "Pesquisar extensões...", "extensions": "extensões", "all": "Tudo", "more": "Mais"},
    "es": {**PLUGIN_LIST_UI["en"], "all_extensions": "Todas las extensiones", "subtitle": "Descubre 3.245 extensiones para mejorar tu navegación.", "total_extensions": "Extensiones", "new_this_week": "Nuevas esta semana", "active_users": "Usuarios activos", "average_rating": "Valoración media", "filters": "Filtros", "most_popular": "Más populares", "highest_rated": "Mejor valoradas", "newest": "Más recientes", "collections": "Colecciones", "hub": "Hub de extensiones", "hub_desc": "Todo lo que necesitas para mejorar tu navegación.", "extension_marketplace": "Mercado de extensiones", "search_extensions": "Buscar extensiones...", "extensions": "extensiones", "all": "Todo", "more": "Más"},
    "ja": {**PLUGIN_LIST_UI["en"], "all_extensions": "すべての拡張機能", "subtitle": "3,245 個の拡張機能でブラウザ体験を強化。", "total_extensions": "拡張機能数", "new_this_week": "今週の新着", "active_users": "アクティブユーザー", "average_rating": "平均評価", "filters": "フィルター", "most_popular": "人気順", "highest_rated": "高評価", "newest": "新着順", "collections": "コレクション", "hub": "拡張機能ハブ", "hub_desc": "ブラウザ体験を高めるすべてをここに。", "extension_marketplace": "拡張機能マーケット", "search_extensions": "拡張機能を検索...", "extensions": "件", "all": "すべて", "more": "もっと見る"},
    "ko": {**PLUGIN_LIST_UI["en"], "all_extensions": "전체 확장 프로그램", "subtitle": "3,245개의 확장 프로그램으로 브라우징 경험을 강화하세요.", "total_extensions": "확장 프로그램", "new_this_week": "이번 주 신규", "active_users": "활성 사용자", "average_rating": "평균 평점", "filters": "필터", "most_popular": "인기순", "highest_rated": "평점순", "newest": "최신순", "collections": "컬렉션", "hub": "확장 프로그램 허브", "hub_desc": "브라우징 경험을 높이는 모든 것.", "extension_marketplace": "확장 프로그램 마켓", "search_extensions": "확장 프로그램 검색...", "extensions": "개", "all": "전체", "more": "더 보기"},
    "ar": {**PLUGIN_LIST_UI["en"], "all_extensions": "كل الإضافات", "subtitle": "اكتشف 3,245 إضافة لتحسين تجربة التصفح.", "total_extensions": "عدد الإضافات", "new_this_week": "الجديد هذا الأسبوع", "active_users": "مستخدمون نشطون", "average_rating": "متوسط التقييم", "filters": "تصفية", "most_popular": "الأكثر شعبية", "highest_rated": "الأعلى تقييما", "newest": "الأحدث", "collections": "مجموعات", "hub": "مركز الإضافات", "hub_desc": "كل ما تحتاجه لتحسين تجربة التصفح.", "extension_marketplace": "سوق الإضافات", "search_extensions": "ابحث عن إضافات...", "extensions": "إضافة", "all": "الكل", "more": "المزيد"},
})

PLUGIN_DETAIL_UI = {
    "zh": {
        "share": "分享",
        "add_collection": "加入收藏",
        "compatible": "与你的浏览器兼容",
        "website": "官网",
        "updated": "更新日期",
        "size": "大小",
        "permissions": "权限",
        "support": "支持",
        "changelog": "更新日志",
        "read_more": "阅读更多",
        "full_changelog": "查看完整更新日志",
        "latest_announcement": "最新公告",
        "whats_new": "最新版本变化",
        "ratings_reviews": "评分与评价",
        "no_data_collection": "不收集数据",
        "modify_data": "修改你复制粘贴的内容",
        "display_notifications": "显示通知",
        "read_site_data": "读取并更改网站数据",
    },
    "en": {
        "share": "Share",
        "add_collection": "Add to collection",
        "compatible": "Compatible with your browser",
        "website": "Website",
        "updated": "Updated",
        "size": "Size",
        "permissions": "Permissions",
        "support": "Support",
        "changelog": "Changelog",
        "read_more": "Read more",
        "full_changelog": "View full changelog",
        "latest_announcement": "Latest Announcement",
        "whats_new": "What's New",
        "ratings_reviews": "Ratings & Reviews",
        "no_data_collection": "No data collection",
        "modify_data": "Modify data you copy and paste",
        "display_notifications": "Display notifications",
        "read_site_data": "Read and change all your data on websites",
    },
}

PLUGIN_DETAIL_UI.update({
    "fr": {**PLUGIN_DETAIL_UI["en"], "share": "Partager", "add_collection": "Ajouter à la collection", "compatible": "Compatible avec votre navigateur", "permissions": "Autorisations", "support": "Support", "ratings_reviews": "Notes et avis"},
    "de": {**PLUGIN_DETAIL_UI["en"], "share": "Teilen", "add_collection": "Zur Sammlung hinzufügen", "compatible": "Mit deinem Browser kompatibel", "permissions": "Berechtigungen", "support": "Support", "ratings_reviews": "Bewertungen"},
    "pt": {**PLUGIN_DETAIL_UI["en"], "share": "Compartilhar", "add_collection": "Adicionar à coleção", "compatible": "Compatível com seu navegador", "permissions": "Permissões", "support": "Suporte", "ratings_reviews": "Avaliações"},
    "es": {**PLUGIN_DETAIL_UI["en"], "share": "Compartir", "add_collection": "Añadir a colección", "compatible": "Compatible con tu navegador", "permissions": "Permisos", "support": "Soporte", "ratings_reviews": "Valoraciones"},
    "ja": {**PLUGIN_DETAIL_UI["en"], "share": "共有", "add_collection": "コレクションに追加", "compatible": "お使いのブラウザに対応", "permissions": "権限", "support": "サポート", "ratings_reviews": "評価とレビュー"},
    "ko": {**PLUGIN_DETAIL_UI["en"], "share": "공유", "add_collection": "컬렉션에 추가", "compatible": "브라우저와 호환", "permissions": "권한", "support": "지원", "ratings_reviews": "평점 및 리뷰"},
    "ar": {**PLUGIN_DETAIL_UI["en"], "share": "مشاركة", "add_collection": "إضافة إلى مجموعة", "compatible": "متوافق مع متصفحك", "permissions": "الأذونات", "support": "الدعم", "ratings_reviews": "التقييمات والمراجعات"},
})


def plugin_ui(lang: str, key: str, default: str = "") -> str:
    return PLUGIN_UI.get(lang, PLUGIN_UI["en"]).get(key, PLUGIN_UI["en"].get(key, default))


def plugin_category_text(category: str, lang: str) -> str:
    return PLUGIN_CATEGORY_TEXT.get(lang, {}).get(category, category)


def plugin_item_text(item: dict[str, Any], lang: str, field: str) -> str:
    value = str(item[field])
    translation = PLUGIN_ITEM_TEXT.get(lang, {}).get(item["slug"], {}).get(field)
    if not translation:
        return value
    default_item = next((default for default in PLUGIN_CATALOG_ITEMS if default["slug"] == item["slug"]), None)
    if default_item and value == str(default_item.get(field, "")):
        return translation
    return value


def plugin_language_switcher(lang: str) -> str:
    other_options = "".join(
        f'<option value="{code}" {"selected" if code == lang else ""}>{html_escape(data["name"])}</option>'
        for code, data in PLUGIN_LANGS.items()
        if code not in {"zh", "en"}
    )
    return f"""
      <div class="grid gap-2">
        <div class="grid grid-cols-2 gap-2">
          <a class="rounded-full px-3 py-2 text-center text-xs font-black transition {'bg-slate-950 text-white' if lang == 'zh' else 'bg-white text-slate-500 hover:bg-slate-100'}" href="/">中文</a>
          <a class="rounded-full px-3 py-2 text-center text-xs font-black transition {'bg-slate-950 text-white' if lang == 'en' else 'bg-white text-slate-500 hover:bg-slate-100'}" href="/?lang=en">English</a>
        </div>
        <label class="sr-only" for="plugin-lang-select">{html_escape(plugin_ui(lang, 'other_languages'))}</label>
        <select id="plugin-lang-select" class="w-full rounded-full border-0 bg-white px-3 py-2 text-xs font-black text-slate-500 outline-none ring-1 ring-slate-100 transition hover:bg-slate-100" onchange="if(this.value) window.location.href='/?lang='+this.value">
          <option value="">{html_escape(plugin_ui(lang, 'other_languages'))}</option>
          {other_options}
        </select>
      </div>"""


def plugin_lang(request: Request) -> tuple[str, dict[str, str]]:
    code = str(request.query_params.get("lang") or "zh").lower()
    if code not in PLUGIN_LANGS:
        code = "zh"
    return code, PLUGIN_LANGS[code]


def plugin_url(path: str, lang: str) -> str:
    suffix = f"?lang={quote(lang)}" if lang != "zh" else ""
    return f"{path}{suffix}"


def plugin_category_href(category: str, lang: str) -> str:
    params = [f"category={quote(category)}"]
    if lang != "zh":
        params.append(f"lang={quote(lang)}")
    return f"/plugins?{'&'.join(params)}"


def plugin_accent_class(item: dict[str, Any]) -> str:
    return {
        "meetseek-prompt-copilot": "from-violet-600 to-blue-500",
        "adguard-adblocker": "from-emerald-500 to-green-700",
        "dark-reader": "from-slate-900 to-blue-950",
        "clip-to-notion": "from-slate-700 to-slate-950",
        "google-translate": "from-blue-500 to-cyan-400",
        "monica-ai": "from-fuchsia-500 to-violet-600",
    }.get(item["slug"], item.get("accent", "from-violet-600 to-blue-500"))


def plugin_display_item(item: dict[str, Any], lang: str) -> dict[str, Any]:
    return {
        **item,
        "title": plugin_item_text(item, lang, "title"),
        "desc": plugin_item_text(item, lang, "desc"),
        "version": item.get("version", "1.0.0"),
        "install_url": item.get("install_url", ""),
        "icon_url": item.get("icon_url", ""),
        "cover_image": item.get("cover_image", ""),
        "gallery_images": item.get("gallery_images", []) if isinstance(item.get("gallery_images", []), list) else [],
        "category_label": plugin_category_text(item["category"], lang),
        "href": plugin_url(f"/plugins/{item['slug']}", lang),
        "accent_class": plugin_accent_class(item),
    }


def plugin_template_context(request: Request, lang: str, t: dict[str, str]) -> dict[str, Any]:
    user = user_from_request(request)
    catalog_items = plugin_items_from_db()
    featured_items = plugin_pick(catalog_items, "is_featured", slice(0, 3))
    trending_items = plugin_pick(catalog_items, "is_trending", slice(0, 5))
    new_items = plugin_pick(catalog_items, "is_new", slice(3, 6))
    category_values = []
    seen_category_values = set()
    for item in catalog_items:
        category = str(item.get("category") or "")
        if not category or category in seen_category_values:
            continue
        seen_category_values.add(category)
        category_values.append(category)
    return {
        "request": request,
        "lang": lang,
        "dir": "rtl" if lang == "ar" else "ltr",
        "t": t,
        "ui": PLUGIN_UI.get(lang, PLUGIN_UI["en"]),
        "current_user": user,
        "main_base_url": MAIN_BASE_URL,
        "tools_base_url": TOOLS_BASE_URL,
        "prompts_base_url": PROMPTS_BASE_URL,
        "signin_label": html_escape(t["signin"]) if not user else html_escape(str(user.get("name") or "Account")),
        "zh_url": plugin_url("/", "zh"),
        "en_url": plugin_url("/", "en"),
        "other_language_options": [
            {"code": code, "name": data["name"], "selected": code == lang}
            for code, data in PLUGIN_LANGS.items()
            if code not in {"zh", "en"}
        ],
        "nav_items": [
            {"icon": "⌂", "label": plugin_ui(lang, "home"), "href": plugin_url("/", lang), "active": True},
            {"icon": "↗", "label": plugin_ui(lang, "top_charts"), "href": "#trending", "active": False},
            {"icon": "▦", "label": plugin_ui(lang, "categories"), "href": plugin_url("/plugins", lang) + "#categories", "active": False},
            {"icon": "✦", "label": plugin_ui(lang, "new_noteworthy"), "href": "#new", "active": False},
            {"icon": "⚙", "label": t["tools"], "href": TOOLS_BASE_URL, "active": False},
            {"icon": "✨", "label": t["prompts"], "href": PROMPTS_BASE_URL, "active": False},
            {"icon": "●", "label": t["community"], "href": plugin_url("/community", lang), "active": False},
        ],
        "category_chips": [
            {"label": plugin_category_text(label, lang), "href": plugin_category_href(label, lang)}
            for label in category_values
        ],
        "featured_items": [plugin_display_item(item, lang) for item in featured_items],
        "trending_items": [plugin_display_item(item, lang) for item in trending_items],
        "new_items": [plugin_display_item(item, lang) for item in new_items],
    }


def plugin_list_context(request: Request, lang: str, t: dict[str, str]) -> dict[str, Any]:
    context = plugin_template_context(request, lang, t)
    list_ui = PLUGIN_LIST_UI.get(lang, PLUGIN_LIST_UI["en"])
    catalog_items = plugin_items_from_db()
    selected_category = str(request.query_params.get("category") or "").strip()
    if selected_category and selected_category not in {str(item.get("category") or "") for item in catalog_items}:
        selected_category = ""
    filtered_items = [
        item for item in catalog_items
        if not selected_category or str(item.get("category") or "") == selected_category
    ]
    all_items = [plugin_display_item(item, lang) for item in filtered_items]
    category_filters = []
    seen_categories = set()
    for item in catalog_items:
        category = item["category"]
        if category in seen_categories:
            continue
        seen_categories.add(category)
        category_filters.append(
            {
                "raw": category,
                "label": plugin_category_text(category, lang),
                "href": plugin_category_href(category, lang),
                "active": category == selected_category,
            }
        )
    category_label = plugin_category_text(selected_category, lang) if selected_category else ""
    page_title = f"{category_label} - {list_ui['all_extensions']} - MeetSeek" if selected_category else f"{list_ui['all_extensions']} - MeetSeek"
    page_desc = f"{category_label} 分类插件列表。" if selected_category and lang == "zh" else list_ui["subtitle"]
    canonical = f"{MAIN_BASE_URL}/plugins"
    if selected_category:
        canonical = f"{canonical}?category={quote(selected_category)}"
    context.update(
        {
            "meta": {
                "title": page_title,
                "description": page_desc,
                "canonical_url": canonical,
            },
            "list_ui": list_ui,
            "all_items": all_items,
            "category_labels": [item["label"] for item in category_filters],
            "category_filters": category_filters,
            "selected_category": selected_category,
            "selected_category_label": category_label,
            "total_extensions": "3,245",
            "new_this_week": "124",
            "active_users": "1.2M+",
            "average_rating": "4.8",
        }
    )
    return context


def plugin_submit_context(request: Request, lang: str, t: dict[str, str]) -> dict[str, Any]:
    context = plugin_template_context(request, lang, t)
    category_values = []
    seen = set()
    for item in plugin_items_from_db():
        category = str(item.get("category") or "").strip()
        if category and category not in seen:
            seen.add(category)
            category_values.append(category)
    if not category_values:
        category_values = ["AI & ChatGPT", "Productivity", "Developer Tools", "Privacy", "Design", "Shopping"]
    context.update(
        {
            "meta": {
                "title": "提交插件 - MeetSeek",
                "description": "向 MeetSeek 提交浏览器插件、AI 工具和生产力工作流。",
                "canonical_url": f"{MAIN_BASE_URL}/plugins/submit",
            },
            "category_values": category_values,
            "accent_presets": [
                "from-violet-500 to-blue-500",
                "from-emerald-500 to-teal-500",
                "from-orange-500 to-amber-400",
                "from-sky-500 to-cyan-400",
                "from-fuchsia-500 to-rose-500",
                "from-slate-800 to-slate-950",
            ],
        }
    )
    return context


def plugin_card_html(item: dict[str, str], lang: str) -> str:
    href = plugin_url(f"/plugins/{item['slug']}", lang)
    title = plugin_item_text(item, lang, "title")
    desc = plugin_item_text(item, lang, "desc")
    return f"""
      <a href="{href}" class="group block overflow-hidden rounded-2xl border border-slate-100 bg-white p-4 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md">
        <div class="rounded-xl bg-gradient-to-br {html_escape(item['accent'])} p-4 text-white">
          <div class="grid h-12 w-12 place-items-center rounded-2xl bg-white/20 text-xl font-black backdrop-blur">{html_escape(item['icon'])}</div>
          <h3 class="mt-5 text-lg font-black leading-tight">{html_escape(title)}</h3>
          <p class="mt-2 line-clamp-2 text-xs font-bold leading-5 text-white/75">{html_escape(desc)}</p>
        </div>
        <div class="mt-3 flex items-center justify-between gap-3 text-xs font-black text-slate-500">
          <span class="rounded-full bg-slate-50 px-2 py-1">⭐ {html_escape(item['rating'])}</span><span>{html_escape(item['users'])} {html_escape(plugin_ui(lang, 'users'))}</span>
        </div>
      </a>"""


def render_plugin_marketplace_html(request: Request) -> Response:
    lang, t = plugin_lang(request)
    context = plugin_template_context(request, lang, t)
    context["meta"] = {
        "title": "MeetSeek Extensions - AI Browser Plugins",
        "description": t["sub"],
        "canonical_url": MAIN_BASE_URL,
    }
    return templates.TemplateResponse("plugin_market.html", context)

    is_rtl = lang == "ar"
    user = user_from_request(request)
    lang_links = plugin_language_switcher(lang)
    nav_items = [("⌂", plugin_ui(lang, "home"), plugin_url("/", lang)), ("↗", plugin_ui(lang, "top_charts"), "#trending"), ("▦", plugin_ui(lang, "categories"), "#categories"), ("✦", plugin_ui(lang, "new_noteworthy"), "#new"), ("⚙", t["tools"], TOOLS_BASE_URL), ("✨", t["prompts"], PROMPTS_BASE_URL), ("●", t["community"], plugin_url("/community", lang))]
    nav_html = "".join(f'<a class="flex items-center gap-3 rounded-2xl px-4 py-3 text-sm font-black {"bg-violet-50 text-violet-700" if i == 0 else "text-slate-500 hover:bg-slate-50 hover:text-slate-900"}" href="{href}"><span>{icon}</span><span>{html_escape(label)}</span></a>' for i, (icon, label, href) in enumerate(nav_items))
    featured_html = "".join(plugin_card_html(item, lang) for item in PLUGIN_ITEMS[:3])
    new_html = "".join(plugin_card_html(item, lang) for item in PLUGIN_ITEMS[3:6])
    trending_rows = ""
    for idx, item in enumerate(PLUGIN_ITEMS[:5], 1):
        href = plugin_url(f"/plugins/{item['slug']}", lang)
        title = plugin_item_text(item, lang, "title")
        desc = plugin_item_text(item, lang, "desc")
        category = plugin_category_text(item["category"], lang)
        trending_rows += f"""<a href="{href}" class="grid grid-cols-[2rem_1fr_auto_auto] items-center gap-3 rounded-2xl px-3 py-3 transition hover:bg-slate-50"><span class="text-sm font-black text-slate-400">{idx}</span><span class="flex min-w-0 items-center gap-3"><span class="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br {html_escape(item['accent'])} text-sm font-black text-white">{html_escape(item['icon'])}</span><span class="min-w-0"><b class="block truncate text-sm text-slate-950">{html_escape(title)}</b><small class="block truncate text-xs font-bold text-slate-400">{html_escape(desc)}</small></span></span><span class="hidden rounded-full bg-slate-50 px-3 py-1 text-xs font-black text-slate-500 sm:block">{html_escape(category)}</span><span class="text-xs font-black text-orange-500">★ {html_escape(item['rating'])}</span></a>"""
    cat_chips = "".join(f'<a href="#" class="rounded-full bg-white px-4 py-2 text-xs font-black text-slate-500 shadow-sm transition hover:bg-violet-50 hover:text-violet-700">{html_escape(plugin_category_text(label, lang))}</a>' for label, _ in PLUGIN_CATEGORIES)
    hero = html_escape(t['hero']).replace('powerful', '<span class="text-blue-600">powerful</span>').replace('强大', '<span class="text-blue-600">强大</span>')
    return f"""<!doctype html><html lang="{html_escape(lang)}" dir="{'rtl' if is_rtl else 'ltr'}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>MeetSeek Extensions - AI Browser Plugins</title><meta name="description" content="{html_escape(t['sub'])}"><link rel="canonical" href="{MAIN_BASE_URL}/"><script src="https://cdn.tailwindcss.com"></script><style>body{{letter-spacing:0}}.hero-glow{{background:radial-gradient(circle at 72% 22%,rgba(99,102,241,.20),transparent 32%),radial-gradient(circle at 88% 8%,rgba(20,184,166,.12),transparent 24%)}}</style></head><body class="min-h-screen bg-[#f7f8fe] text-slate-950"><div class="mx-auto grid min-h-screen max-w-[1500px] grid-cols-1 lg:grid-cols-[17rem_1fr]"><aside class="hidden border-r border-slate-200/70 bg-white/70 p-6 backdrop-blur-xl lg:block"><a href="{MAIN_BASE_URL}/" class="flex items-center gap-3"><span class="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-violet-600 to-blue-500 text-lg font-black text-white">M</span><b class="text-xl">MEETSEEK</b></a><nav class="mt-9 grid gap-1">{nav_html}</nav><div class="mt-8 border-t border-slate-100 pt-6 text-xs font-black text-slate-400">{lang_links}</div><div class="mt-8 rounded-3xl bg-slate-950 p-5 text-white"><p class="text-xs font-black uppercase text-emerald-300">{html_escape(plugin_ui(lang, 'creator_label'))}</p><p class="mt-3 text-lg font-black">{html_escape(plugin_ui(lang, 'creator_title'))}</p><a class="mt-5 inline-flex rounded-full bg-white px-4 py-2 text-xs font-black text-slate-950" href="/community">{html_escape(plugin_ui(lang, 'submit'))}</a></div></aside><main class="min-w-0"><header class="sticky top-0 z-30 flex items-center justify-between border-b border-slate-200/70 bg-white/70 px-5 py-4 backdrop-blur-xl lg:px-10"><div class="flex items-center gap-3 lg:hidden"><span class="grid h-9 w-9 place-items-center rounded-xl bg-violet-600 font-black text-white">M</span><b>MEETSEEK</b></div><nav class="hidden items-center gap-8 text-sm font-black text-slate-500 md:flex"><a class="text-slate-950" href="/">{html_escape(plugin_ui(lang, 'discover'))}</a><a href="#categories">{html_escape(plugin_ui(lang, 'categories'))}</a><a href="#trending">{html_escape(plugin_ui(lang, 'top_charts'))}</a><a href="/community">{html_escape(t['community'])}</a><a href="{TOOLS_BASE_URL}">{html_escape(t['tools'])}</a></nav><div class="flex items-center gap-3"><a class="grid h-10 w-10 place-items-center rounded-full bg-white shadow-sm" href="#search">⌕</a><a class="rounded-full bg-slate-950 px-5 py-3 text-sm font-black text-white" href="/account">{html_escape(t['signin']) if not user else html_escape(str(user.get('name') or 'Account'))}</a></div></header><section class="hero-glow border-b border-slate-200/70 px-5 py-12 lg:px-10 lg:py-16"><div class="grid gap-10 xl:grid-cols-[1fr_23rem]"><div><h1 class="max-w-3xl text-5xl font-black leading-[1.08] tracking-tight md:text-7xl">{hero}</h1><p class="mt-6 max-w-2xl text-base font-bold leading-8 text-slate-500">{html_escape(t['sub'])}</p><div id="search" class="mt-9 flex max-w-3xl items-center overflow-hidden rounded-2xl bg-white p-2 shadow-xl shadow-slate-200/70"><span class="px-4 text-slate-400">⌕</span><input class="h-12 min-w-0 flex-1 border-none bg-transparent text-sm font-bold outline-none" placeholder="{html_escape(t['search'])}"><button class="rounded-xl bg-violet-600 px-6 py-3 text-sm font-black text-white">{html_escape(plugin_ui(lang, 'search_button'))}</button></div><div id="categories" class="mt-5 flex flex-wrap gap-2">{cat_chips}<a class="rounded-full bg-white px-4 py-2 text-xs font-black text-slate-500 shadow-sm" href="{TOOLS_BASE_URL}">{html_escape(t['tools'])}</a><a class="rounded-full bg-white px-4 py-2 text-xs font-black text-slate-500 shadow-sm" href="{PROMPTS_BASE_URL}">{html_escape(t['prompts'])}</a></div></div><div class="relative hidden xl:block"><div class="absolute right-12 top-2 grid h-28 w-28 rotate-12 place-items-center rounded-[2rem] bg-white text-5xl shadow-xl">🧩</div><div class="absolute bottom-4 right-2 grid h-20 w-20 -rotate-6 place-items-center rounded-3xl bg-white text-3xl shadow-xl">🛡️</div><div class="absolute left-6 top-28 grid h-16 w-16 rotate-6 place-items-center rounded-2xl bg-white text-2xl shadow-xl">⚡</div></div></div></section><section class="space-y-10 px-5 py-10 lg:px-10"><section><div class="mb-5 flex items-center justify-between"><h2 class="text-2xl font-black">{html_escape(t['featured'])}</h2><a class="text-sm font-black text-slate-400" href="#">{html_escape(plugin_ui(lang, 'view_all'))}</a></div><div class="grid gap-5 md:grid-cols-3">{featured_html}</div></section><section id="trending" class="rounded-3xl border border-slate-100 bg-white p-5 shadow-sm"><div class="mb-3 flex items-center justify-between"><h2 class="text-2xl font-black">{html_escape(t['trending'])}</h2><a class="text-sm font-black text-slate-400" href="#">{html_escape(plugin_ui(lang, 'view_all'))}</a></div><div class="divide-y divide-slate-100">{trending_rows}</div></section><section id="new"><div class="mb-5 flex items-center justify-between"><h2 class="text-2xl font-black">{html_escape(t['new'])}</h2><a class="text-sm font-black text-slate-400" href="#">{html_escape(plugin_ui(lang, 'view_all'))}</a></div><div class="grid gap-5 md:grid-cols-3">{new_html}</div></section><section class="overflow-hidden rounded-3xl bg-slate-950 p-8 text-white"><p class="text-sm font-black text-emerald-300">{html_escape(plugin_ui(lang, 'editor_picks'))}</p><h2 class="mt-3 text-3xl font-black">{html_escape(plugin_ui(lang, 'workflow_title'))}</h2><p class="mt-3 max-w-2xl text-sm font-bold leading-7 text-white/60">{html_escape(plugin_ui(lang, 'workflow_desc'))}</p><div class="mt-6 flex flex-wrap gap-3"><a class="rounded-full bg-white px-5 py-3 text-sm font-black text-slate-950" href="{TOOLS_BASE_URL}">{html_escape(t['tools'])}</a><a class="rounded-full bg-white/10 px-5 py-3 text-sm font-black text-white" href="{PROMPTS_BASE_URL}">{html_escape(t['prompts'])}</a><a class="rounded-full bg-white/10 px-5 py-3 text-sm font-black text-white" href="/community">{html_escape(t['community'])}</a></div></section></section></main></div></body></html>"""


def render_plugin_list_html(request: Request) -> Response:
    lang, t = plugin_lang(request)
    return templates.TemplateResponse("plugin_list.html", plugin_list_context(request, lang, t))


def plugin_by_slug(slug: str) -> dict[str, str] | None:
    try:
        with db() as conn:
            row = conn.execute(
                "SELECT * FROM plugins WHERE slug = ? AND status = 'published' LIMIT 1",
                (slug,),
            ).fetchone()
            if row:
                return plugin_row_to_item(row)
    except sqlite3.Error:
        pass
    return next((item for item in PLUGIN_CATALOG_ITEMS if item["slug"] == slug), None)


def render_plugin_detail_html(request: Request, plugin_slug: str) -> Response:
    lang, t = plugin_lang(request)
    item = plugin_by_slug(plugin_slug)
    if not item:
        raise HTTPException(status_code=404, detail="插件不存在")
    title = plugin_item_text(item, lang, "title")
    desc = plugin_item_text(item, lang, "desc")
    category = plugin_category_text(item["category"], lang)
    feature_lines = [
        "屏蔽干扰内容并提升浏览效率",
        "可连接 MeetSeek 工具箱和提示词库",
        "隐私优先，发布者已验证",
        "轻量、快速、容易使用",
    ] if lang == "zh" else [
        "Blocks noisy pages and speeds up workflows",
        "Works with MeetSeek tools and prompt library",
        "Privacy-first design with verified publisher",
        "Lightweight, fast and easy to use",
    ]
    about_title = f"{plugin_ui(lang, 'about')} {title}" if lang != "zh" else f"{plugin_ui(lang, 'about')}{title}"
    long_desc = str(item.get("long_description") or "").strip()
    about_desc = long_desc or (
        f"{desc} 这款插件适合创作者、运营者和开发者，用来提升浏览器里的 AI 工作流效率。"
        if lang == "zh"
        else f"{desc} It is designed for creators, operators and builders who want a faster browser workflow."
    )
    context = plugin_template_context(request, lang, t)
    context.update(
        {
            "meta": {
                "title": f"{title} - MeetSeek Extensions",
                "description": desc,
                "canonical_url": f"{MAIN_BASE_URL}/plugins/{plugin_slug}",
            },
            "plugin": plugin_display_item(item, lang),
            "category": category,
            "detail_ui": PLUGIN_DETAIL_UI.get(lang, PLUGIN_DETAIL_UI["en"]),
            "feature_lines": feature_lines,
            "about_title": about_title,
            "about_desc": about_desc,
            "related_items": [
                plugin_display_item(other, lang)
                for other in plugin_items_from_db()
                if other["slug"] != plugin_slug
            ][:3],
        }
    )
    return templates.TemplateResponse("plugin_detail.html", context)

    related_items = [other for other in PLUGIN_ITEMS if other["slug"] != plugin_slug][:3]
    related = "".join(plugin_card_html(other, lang) for other in related_items)
    feature_lines = [
        "屏蔽干扰内容并提升浏览效率",
        "可连接 MeetSeek 工具箱和提示词库",
        "隐私优先，发布者已验证",
        "轻量、快速、容易使用",
    ] if lang == "zh" else [
        "Blocks noisy pages and speeds up workflows",
        "Works with MeetSeek tools and prompt library",
        "Privacy-first design with verified publisher",
        "Lightweight, fast and easy to use",
    ]
    features = "".join(f'<li class="flex gap-2"><span class="text-emerald-500">✓</span><span>{html_escape(line)}</span></li>' for line in feature_lines)
    about_title = f"{plugin_ui(lang, 'about')} {title}" if lang != "zh" else f"{plugin_ui(lang, 'about')}{title}"
    about_desc = f"{desc} 这款插件适合创作者、运营者和开发者，用来提升浏览器里的 AI 工作流效率。" if lang == "zh" else f"{desc} It is designed for creators, operators and builders who want a faster browser workflow."
    return f"""<!doctype html><html lang="{html_escape(lang)}" dir="{'rtl' if lang == 'ar' else 'ltr'}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{html_escape(title)} - MeetSeek Extensions</title><meta name="description" content="{html_escape(desc)}"><link rel="canonical" href="{MAIN_BASE_URL}/plugins/{html_escape(plugin_slug)}"><script src="https://cdn.tailwindcss.com"></script></head><body class="min-h-screen bg-[#f7f8fe] text-slate-950"><main class="mx-auto max-w-7xl px-5 py-6"><nav class="mb-7 flex items-center justify-between text-sm font-black text-slate-500"><a href="{plugin_url('/', lang)}" class="hover:text-slate-950">{html_escape(plugin_ui(lang, 'home'))}</a><div class="flex gap-3"><a href="{TOOLS_BASE_URL}">{html_escape(t['tools'])}</a><a href="{PROMPTS_BASE_URL}">{html_escape(t['prompts'])}</a><a href="/community">{html_escape(t['community'])}</a></div></nav><section class="rounded-[2rem] border border-slate-100 bg-white p-6 shadow-sm lg:p-10"><div class="grid gap-8 lg:grid-cols-[1fr_18rem]"><div class="flex gap-6"><div class="grid h-28 w-28 shrink-0 place-items-center rounded-[2rem] bg-gradient-to-br {html_escape(item['accent'])} text-5xl font-black text-white">{html_escape(item['icon'])}</div><div><div class="flex flex-wrap items-center gap-3"><h1 class="text-4xl font-black tracking-tight">{html_escape(title)}</h1><span class="rounded-full bg-violet-50 px-3 py-1 text-xs font-black text-violet-600">{html_escape(t['verified'])}</span></div><p class="mt-3 text-sm font-bold leading-7 text-slate-500">{html_escape(desc)}</p><div class="mt-4 flex flex-wrap gap-5 text-sm font-black text-slate-500"><span>⭐ {html_escape(item['rating'])}</span><span>{html_escape(item['users'])} {html_escape(plugin_ui(lang, 'users'))}</span><span class="text-emerald-600">● {html_escape(t['verified'])}</span></div></div></div><aside class="grid gap-3"><a class="rounded-2xl bg-violet-600 px-6 py-4 text-center text-sm font-black text-white shadow-lg shadow-violet-200" href="{TOOLS_BASE_URL}">{html_escape(t['add'])}</a><a class="rounded-2xl border border-slate-200 px-6 py-4 text-center text-sm font-black text-slate-600" href="/community">{html_escape(plugin_ui(lang, 'share'))}</a></aside></div><div class="mt-8 grid gap-4 lg:grid-cols-[1fr_12rem]"><div class="overflow-hidden rounded-3xl bg-gradient-to-br {html_escape(item['accent'])} p-8 text-white"><h2 class="text-4xl font-black">{html_escape(title)}</h2><p class="mt-4 max-w-xl text-lg font-bold leading-8 text-white/75">{html_escape(desc)}</p><div class="mt-16 rounded-3xl bg-white/20 p-5 backdrop-blur"><div class="h-44 rounded-2xl bg-white/85"></div></div></div><div class="grid gap-4"><div class="rounded-3xl bg-slate-100 p-4"><div class="h-28 rounded-2xl bg-white"></div></div><div class="rounded-3xl bg-slate-100 p-4"><div class="h-28 rounded-2xl bg-white"></div></div><div class="grid place-items-center rounded-3xl bg-slate-900 p-4 text-sm font-black text-white">+3 more</div></div></div></section><section class="mt-6 grid gap-6 lg:grid-cols-[1fr_20rem]"><article class="rounded-[2rem] border border-slate-100 bg-white p-8 shadow-sm"><div class="flex gap-8 border-b border-slate-100 pb-5 text-sm font-black text-slate-500"><span class="text-violet-600">{html_escape(t['overview'])}</span><span>{html_escape(t['features'])}</span><span>{html_escape(t['reviews'])}</span></div><h2 class="mt-7 text-2xl font-black">{html_escape(about_title)}</h2><p class="mt-4 text-sm font-bold leading-8 text-slate-600">{html_escape(about_desc)}</p><ul class="mt-5 grid gap-2 text-sm font-bold text-slate-600">{features}</ul><div class="mt-8 rounded-3xl bg-violet-50 p-5"><b>{html_escape(plugin_ui(lang, 'latest'))}</b><p class="mt-2 text-sm font-bold leading-7 text-slate-500">{html_escape(plugin_ui(lang, 'latest_desc'))}</p></div></article><aside class="space-y-5"><section class="rounded-3xl border border-slate-100 bg-white p-6 shadow-sm"><h3 class="font-black">{html_escape(t['details'])}</h3><dl class="mt-4 grid gap-3 text-sm font-bold text-slate-500"><div class="flex justify-between"><dt>{html_escape(plugin_ui(lang, 'version'))}</dt><dd>1.0.0</dd></div><div class="flex justify-between"><dt>{html_escape(plugin_ui(lang, 'category'))}</dt><dd>{html_escape(category)}</dd></div><div class="flex justify-between"><dt>{html_escape(plugin_ui(lang, 'languages'))}</dt><dd>9</dd></div></dl></section><section class="rounded-3xl border border-slate-100 bg-white p-6 shadow-sm"><h3 class="font-black">{html_escape(plugin_ui(lang, 'trust'))}</h3><ul class="mt-4 grid gap-2 text-sm font-bold text-slate-500"><li>✅ {html_escape(plugin_ui(lang, 'verified_practices'))}</li><li>✅ {html_escape(plugin_ui(lang, 'privacy'))}</li><li>✅ {html_escape(plugin_ui(lang, 'offline'))}</li></ul></section></aside></section><section class="mt-8"><h2 class="mb-4 text-2xl font-black">{html_escape(plugin_ui(lang, 'related'))}</h2><div class="grid gap-5 md:grid-cols-3">{related}</div></section></main></body></html>"""


def render_shop_page(request: Request) -> Response:
    user = user_from_request(request)
    categories = [public_shop_category(row) for row in shop_category_rows()]
    products = [public_shop_product(row) for row in shop_product_rows(public_only=True)]
    orders: list[dict[str, Any]] = []
    if user:
        with db() as conn:
            rows = conn.execute(
                """
                SELECT
                    shop_orders.*,
                    shop_products.title AS product_title,
                    shop_products.slug AS product_slug
                FROM shop_orders
                JOIN shop_products ON shop_products.id = shop_orders.product_id
                WHERE shop_orders.user_id = ?
                ORDER BY shop_orders.created_at DESC
                LIMIT 10
                """,
                (user["id"],),
            ).fetchall()
        orders = [public_shop_order(row) for row in rows]
    return templates.TemplateResponse(
        "shop.html",
        {
            "request": request,
            "meta": {
                "title": "MeetSeek 商店 - 会员、积分与 AI 服务",
                "description": "购买 MeetSeek 会员、积分包、AI 工具套餐和定制服务。",
                "canonical_url": SHOP_BASE_URL,
                "image_url": "",
                "type": "website",
            },
            "site_name": "meetseek",
            "main_base_url": MAIN_BASE_URL,
            "tools_base_url": TOOLS_BASE_URL,
            "prompts_base_url": PROMPTS_BASE_URL,
            "shop_base_url": SHOP_BASE_URL,
            "current_user": user,
            "categories": categories,
            "products": products,
            "orders": orders,
        },
    )


def shop_product_row_by_slug(slug: str, public_only: bool = True) -> sqlite3.Row | None:
    status_filter = "AND shop_products.status = 'published'" if public_only else ""
    with db() as conn:
        return conn.execute(
            f"""
            SELECT
                shop_products.*,
                shop_categories.name AS category_name,
                shop_categories.slug AS category_slug
            FROM shop_products
            LEFT JOIN shop_categories ON shop_categories.id = shop_products.category_id
            WHERE shop_products.slug = ?
            {status_filter}
            LIMIT 1
            """,
            (slug,),
        ).fetchone()


def shop_order_row_for_user(order_id: str, user_id: int) -> sqlite3.Row | None:
    with db() as conn:
        return conn.execute(
            """
            SELECT
                shop_orders.*,
                shop_products.title AS product_title,
                shop_products.slug AS product_slug,
                shop_products.product_type AS product_type,
                shop_products.cover_image AS product_cover_image,
                shop_products.gallery_images AS product_gallery_images
            FROM shop_orders
            JOIN shop_products ON shop_products.id = shop_orders.product_id
            WHERE shop_orders.id = ? AND shop_orders.user_id = ?
            LIMIT 1
            """,
            (order_id, user_id),
        ).fetchone()


def render_shop_product_page(request: Request, slug: str) -> Response:
    user = user_from_request(request)
    row = shop_product_row_by_slug(slug)
    if not row:
        raise HTTPException(status_code=404, detail="商品不存在或未上架")
    product = public_shop_product(row)
    title = f"{product['title']} - MeetSeek 商城"
    description = product.get("description") or product.get("subtitle") or "MeetSeek 商城商品详情。"
    return templates.TemplateResponse(
        "shop_product.html",
        {
            "request": request,
            "meta": {
                "title": title,
                "description": description[:150],
                "canonical_url": f"{SHOP_BASE_URL}/products/{product['slug']}",
                "image_url": product.get("cover_image") or "",
                "type": "product",
            },
            "site_name": "meetseek",
            "main_base_url": MAIN_BASE_URL,
            "tools_base_url": TOOLS_BASE_URL,
            "prompts_base_url": PROMPTS_BASE_URL,
            "shop_base_url": SHOP_BASE_URL,
            "current_user": user,
            "product": product,
        },
    )


def render_shop_pay_page(request: Request, order_id: str) -> Response:
    user = user_from_request(request)
    if not user:
        return RedirectResponse(f"{MAIN_BASE_URL}/login", status_code=302)
    row = shop_order_row_for_user(order_id, int(user["id"]))
    if not row:
        raise HTTPException(status_code=404, detail="订单不存在")
    order = public_shop_order(row)
    gallery_images = [
        item.strip()
        for item in re.split(r"[\n,]+", str(row["product_gallery_images"] if "product_gallery_images" in row.keys() else ""))
        if item.strip()
    ][:12]
    product_image = str(row["product_cover_image"] or "").strip() or (gallery_images[0] if gallery_images else "")
    payment = public_payment_config()
    return templates.TemplateResponse(
        "shop_pay.html",
        {
            "request": request,
            "meta": {
                "title": f"订单支付 - {order['product_title']}",
                "description": "MeetSeek 商城订单支付页面。",
                "canonical_url": f"{SHOP_BASE_URL}/shop/pay/{order_id}",
                "image_url": product_image,
                "type": "website",
            },
            "site_name": "meetseek",
            "main_base_url": MAIN_BASE_URL,
            "tools_base_url": TOOLS_BASE_URL,
            "prompts_base_url": PROMPTS_BASE_URL,
            "shop_base_url": SHOP_BASE_URL,
            "current_user": user,
            "order": order,
            "product_image": product_image,
            "payment": payment,
        },
    )


def render_account_html(request: Request) -> str:
    user = user_from_request(request)
    if user:
        with db() as conn:
            stats_row = conn.execute(
"""
                SELECT COUNT(*) AS post_count,
                       COALESCE(SUM(like_count), 0) AS like_count
                FROM posts
                WHERE author_id = ? AND status = 'published' AND visibility = 'public'
                """,
                (user["id"],),
            ).fetchone()
            posts = conn.execute(
                """
                SELECT * FROM posts
                WHERE author_id = ? AND status = 'published'
                ORDER BY pinned_at DESC, published_at DESC, created_at DESC
                LIMIT 20
                """,
                (user["id"],),
            ).fetchall()
            orders = conn.execute(
                "SELECT credit_orders.*, users.email, users.name FROM credit_orders JOIN users ON users.id = credit_orders.user_id WHERE user_id = ? ORDER BY created_at DESC LIMIT 5",
                (user["id"],),
            ).fetchall()
            social_stats = user_social_stats(conn, int(user["id"]))
        checkin = checkin_state(user["id"])
        avatar_url = html_escape(user.get("avatar_url") or "")
        bio = str(user.get("bio") or "").strip()
        bio_html = html_escape(bio)
        avatar_html = (
            f'<img class="h-20 w-20 rounded-3xl object-cover" src="{avatar_url}" alt="{html_escape(user["name"])}" loading="lazy">'
            if avatar_url
            else f'<div class="grid h-20 w-20 place-items-center rounded-3xl bg-slate-950 text-2xl font-black text-white">{html_escape(user["name"][:1] or "M")}</div>'
        )
        modal_avatar_html = (
            f'<img id="avatar-preview" class="h-full w-full rounded-full object-cover" src="{avatar_url}" alt="{html_escape(user["name"])}" loading="lazy">'
            if avatar_url
            else f'<div id="avatar-preview" class="grid h-full w-full place-items-center rounded-full bg-slate-950 text-2xl font-black text-white">{html_escape(user["name"][:1] or "M")}</div>'
        )
        posts_html = "".join(account_post_card_html(row) for row in posts) or '<div class="rounded-3xl border border-dashed border-slate-200 bg-white p-8 text-center text-sm font-bold text-slate-400">暂无发布内容</div>'
        orders_html = "".join(
            f'<li class="rounded-2xl bg-slate-50 px-4 py-3"><strong>{html_escape(order["package_name"])}</strong><span class="ml-2 text-slate-500">{html_escape(order["status"])} · {int(order["points"])} 积分</span></li>'
            for order in orders
        ) or '<li class="rounded-2xl border border-dashed border-slate-200 py-6 text-center text-sm font-bold text-slate-400">暂无积分订单</li>'
        post_count = int(stats_row["post_count"] or 0)
        like_count = int(social_stats["total_likes"])
        following_count = int(social_stats["following_count"])
        followers_count = int(social_stats["followers_count"])
        checked_today = bool(checkin.get("checked_today"))
        checkin_button = (
            '<button disabled class="mt-4 w-full cursor-not-allowed rounded-2xl bg-slate-100 px-5 py-3 text-sm font-black text-slate-400" type="button">今日已签到</button>'
            if checked_today
            else '<button class="mt-4 w-full rounded-2xl bg-slate-950 px-5 py-3 text-sm font-black text-white transition hover:bg-orange-600" type="button" x-on:click="checkin()">签到领积分</button>'
        )
        body = f"""
        <section class="grid gap-6 lg:grid-cols-[1fr_340px]">
          <div class="space-y-6">
            <div class="glass soft rounded-3xl p-7">
              <div class="flex flex-wrap items-center justify-between gap-5">
                <div class="flex items-center gap-5">
                  <div id="account-avatar-shell">{avatar_html}</div>
                  <div>
                    <p class="text-sm font-black text-orange-600">统一会员中心</p>
                    <h1 id="account-display-name" class="mt-2 text-4xl font-black">{html_escape(user["name"])}</h1>
                    <p id="account-bio" class="mt-2 max-w-2xl text-sm leading-6 text-slate-500">{bio_html or "这个人还没有写简介。"}</p>
                    <div class="mt-4 flex items-center gap-6 text-sm">
                      <div class="flex flex-col"><span id="account-following-count" class="text-lg font-bold text-slate-900">{following_count}</span><span class="text-slate-500">关注</span></div>
                      <div class="flex flex-col"><span id="account-followers-count" class="text-lg font-bold text-slate-900">{followers_count}</span><span class="text-slate-500">粉丝</span></div>
                      <div class="flex flex-col"><span id="account-total-likes" class="text-lg font-bold text-slate-900">{like_count}</span><span class="text-slate-500">获赞</span></div>
                    </div>
                    <p class="mt-2 text-sm text-slate-500">{html_escape(user["tier"]).upper()} · 主站、工具箱和提示词库共用账号</p>
                  </div>
                </div>
                <button class="grid h-11 w-11 place-items-center rounded-2xl bg-slate-950 text-white" type="button" x-on:click="settingsOpen = true" aria-label="资料设置">⚙</button>
              </div>
            </div>
            <div class="grid gap-4 sm:grid-cols-3">
              <div class="rounded-3xl border border-slate-100 bg-white p-6 shadow-sm"><p class="text-sm font-bold text-slate-400">积分</p><p class="mt-3 text-4xl font-black text-orange-600">{int(user.get("points") or 0)}</p></div>
              <div class="rounded-3xl border border-slate-100 bg-white p-6 shadow-sm"><p class="text-sm font-bold text-slate-400">获赞</p><p class="mt-3 text-4xl font-black text-orange-600">{like_count}</p></div>
              <div class="rounded-3xl border border-slate-100 bg-white p-6 shadow-sm"><p class="text-sm font-bold text-slate-400">发布数</p><p class="mt-3 text-4xl font-black text-orange-600">{post_count}</p></div>
            </div>
            <div class="rounded-3xl border border-slate-100 bg-white p-3 shadow-sm">
              <div class="flex gap-2">
                <button class="rounded-2xl px-5 py-3 text-sm font-black" :class="tab === 'posts' ? 'bg-orange-50 text-orange-600' : 'text-slate-500 hover:bg-slate-50'" type="button" x-on:click="tab = 'posts'">我的发布</button>
                <button class="rounded-2xl px-5 py-3 text-sm font-black" :class="tab === 'bookmarks' ? 'bg-orange-50 text-orange-600' : 'text-slate-500 hover:bg-slate-50'" type="button" x-on:click="tab = 'bookmarks'">我的收藏</button>
              </div>
              <div class="mt-4 grid gap-4 p-2" x-show="tab === 'posts'">{posts_html}</div>
              <div class="mt-4 rounded-3xl border border-dashed border-slate-200 bg-slate-50 p-8 text-center text-sm font-bold text-slate-400" x-show="tab === 'bookmarks'" x-cloak>收藏列表接口已预留，后续接入收藏表后自动展示。</div>
            </div>
          </div>
          <aside class="grid gap-5">
            <section class="rounded-3xl border border-slate-100 bg-white p-6 shadow-sm">
              <h2 class="text-xl font-black">签到</h2>
              <p class="mt-3 text-sm leading-relaxed text-slate-500">{'今天已经签到。' if checkin.get("checked_today") else '今天还没有签到，可领取积分。'}</p>
              {checkin_button}
            </section>
            <section class="rounded-3xl border border-slate-100 bg-white p-6 shadow-sm">
              <h2 class="text-xl font-black">最近订单</h2>
              <ul class="mt-4 grid gap-3 text-sm">{orders_html}</ul>
            </section>
            <section class="rounded-3xl border border-slate-100 bg-white p-6 shadow-sm">
              <h2 class="text-xl font-black">快捷入口</h2>
              <div class="mt-4 grid gap-3 text-sm font-black">
                <a class="rounded-2xl bg-slate-50 px-4 py-3 transition hover:bg-slate-100" href="https://tools.meetseek.ai/">🧰 使用工具箱</a>
                <a class="rounded-2xl bg-slate-50 px-4 py-3 transition hover:bg-slate-100" href="https://prompts.meetseek.ai/">✨ 浏览提示词库</a>
                <button class="rounded-2xl bg-slate-950 px-4 py-3 text-white" type="button" x-on:click="logout()">退出登录</button>
              </div>
            </section>
          </aside>
        </section>
        <div class="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-5 backdrop-blur-sm" x-show="settingsOpen" x-cloak>
          <section class="w-full max-w-2xl rounded-3xl border border-white/20 bg-white/90 p-6 shadow-2xl backdrop-blur-xl">
            <div class="flex items-center justify-between">
              <h2 class="text-2xl font-black">资料设置</h2>
              <button class="grid h-10 w-10 place-items-center rounded-full bg-slate-100 font-black" type="button" x-on:click="settingsOpen = false">×</button>
            </div>
            <form id="profile-settings-form" class="mt-6 grid gap-4" x-on:submit.prevent="saveProfile">
              <label class="text-sm font-black text-slate-500">昵称</label>
              <input id="profile-nickname" name="nickname" class="h-12 rounded-2xl border border-slate-200 bg-white px-4 outline-none transition focus:border-transparent focus:ring-2 focus:ring-orange-500" x-model="profileName">
              <label class="text-sm font-black text-slate-500">邮箱地址</label>
              <input id="profile-email" name="email" type="email" class="h-12 rounded-2xl border border-slate-200 bg-white px-4 outline-none transition focus:border-transparent focus:ring-2 focus:ring-orange-500" x-model="profileEmail" placeholder="用于登录和找回密码">
              <label class="text-sm font-black text-slate-500">手机号</label>
              <input id="profile-phone" name="phone" inputmode="tel" class="h-12 rounded-2xl border border-slate-200 bg-white px-4 outline-none transition focus:border-transparent focus:ring-2 focus:ring-orange-500" x-model="profilePhone" placeholder="可选，用于账号安全绑定">
              <label class="text-sm font-black text-slate-500">个人简介</label>
              <textarea id="profile-bio" name="bio" maxlength="150" class="min-h-24 resize-none rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm leading-6 outline-none transition focus:border-transparent focus:ring-2 focus:ring-orange-500" x-model="profileBio" placeholder="用 150 字以内介绍你正在关注的方向"></textarea>
              <div>
                <p class="text-sm font-black text-slate-500">头像</p>
                <label class="group relative mt-3 block h-20 w-20 cursor-pointer overflow-hidden rounded-full ring-4 ring-slate-100 transition hover:ring-orange-100">
                  {modal_avatar_html}
                  <span class="absolute inset-0 grid place-items-center bg-black/0 text-xs font-black text-white opacity-0 transition group-hover:bg-black/50 group-hover:opacity-100">更换</span>
                  <input id="avatar-input" class="hidden" type="file" accept="image/*" x-ref="avatarInput">
                </label>
              </div>
              <button class="rounded-2xl bg-orange-600 px-5 py-3 font-black text-white" type="submit">保存资料</button>
            </form>
            <div class="my-8 h-px w-full bg-slate-100"></div>
            <form class="grid gap-4" x-on:submit.prevent="changePassword">
              <h3 class="text-lg font-black">修改密码</h3>
              <input class="h-12 rounded-2xl border border-slate-200 bg-white px-4 outline-none transition focus:border-transparent focus:ring-2 focus:ring-slate-900" type="password" x-model="oldPassword" placeholder="旧密码">
              <input class="h-12 rounded-2xl border border-slate-200 bg-white px-4 outline-none transition focus:border-transparent focus:ring-2 focus:ring-slate-900" type="password" x-model="newPassword" placeholder="新密码，至少 8 位">
              <input class="h-12 rounded-2xl border border-slate-200 bg-white px-4 outline-none transition focus:border-transparent focus:ring-2 focus:ring-slate-900" type="password" x-model="confirmPassword" placeholder="确认新密码">
              <button class="rounded-2xl bg-slate-950 px-5 py-3 font-black text-white" type="submit">修改密码</button>
            </form>
            <p id="settings-message" class="mt-4 min-h-5 text-sm font-bold" :class="settingsMessage.includes('成功') ? 'text-emerald-600' : 'text-red-600'" x-text="settingsMessage"></p>
          </section>
        </div>
        """
    else:
        body = """
        <section class="grid gap-6 lg:grid-cols-[1fr_420px]">
          <div class="glass soft rounded-3xl p-8">
            <p class="text-sm font-black text-orange-600">一个账号，三个站点</p>
            <h1 class="mt-3 text-4xl font-black md:text-6xl">登录 meetseek 会员中心</h1>
            <p class="mt-5 max-w-2xl text-base leading-relaxed text-slate-500">登录后可同步使用工具箱、提示词库、积分、签到和后续社区发布权限。</p>
            <div class="mt-8 grid gap-4 sm:grid-cols-3">
              <a class="rounded-3xl bg-white/70 p-5 font-black" href="https://tools.meetseek.ai/">工具箱</a>
              <a class="rounded-3xl bg-white/70 p-5 font-black" href="https://prompts.meetseek.ai/">提示词库</a>
              <div class="rounded-3xl bg-white/70 p-5 font-black">社区信息流</div>
            </div>
          </div>
          <form class="glass soft rounded-3xl p-6" x-on:submit.prevent="submitAuth">
            <h2 class="text-2xl font-black" x-text="mode === 'login' ? '登录' : '注册'"></h2>
            <label class="mt-5 block text-sm font-bold text-slate-600">邮箱</label>
            <input class="mt-2 h-12 w-full rounded-2xl border border-slate-200 px-4 outline-none focus:border-orange-500" type="email" x-model="email" required>
            <label class="mt-4 block text-sm font-bold text-slate-600">密码</label>
            <input class="mt-2 h-12 w-full rounded-2xl border border-slate-200 px-4 outline-none focus:border-orange-500" type="password" x-model="password" required>
            <template x-if="mode === 'register'">
              <div>
                <label class="mt-4 block text-sm font-bold text-slate-600">显示姓名</label>
                <input class="mt-2 h-12 w-full rounded-2xl border border-slate-200 px-4 outline-none focus:border-orange-500" x-model="name">
              </div>
            </template>
            <p class="mt-4 min-h-5 text-sm text-red-600" x-text="message"></p>
            <button class="mt-3 w-full rounded-2xl bg-slate-950 px-5 py-3 font-black text-white" type="submit" x-text="mode === 'login' ? '登录' : '注册'"></button>
            <button class="mt-3 w-full rounded-2xl bg-slate-100 px-5 py-3 font-black text-slate-700" type="button" x-on:click="mode = mode === 'login' ? 'register' : 'login'; message = ''" x-text="mode === 'login' ? '没有账号？去注册' : '已有账号？去登录'"></button>
            <a class="mt-4 block text-center text-sm font-bold text-slate-500 hover:text-orange-600" href="/forgot-password">忘记密码？</a>
          </form>
        </section>
        """
    initial_profile_name = json.dumps(user["name"] if user else "", ensure_ascii=False)
    initial_profile_bio = json.dumps(user.get("bio") if user else "", ensure_ascii=False)
    initial_profile_email = json.dumps(user.get("email") if user else "", ensure_ascii=False)
    initial_profile_phone = json.dumps(user.get("phone") if user else "", ensure_ascii=False)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>会员中心 - meetseek</title>
  <meta name="description" content="meetseek 统一会员中心，同步工具箱、提示词库、积分、签到和会员权限。">
  <meta name="robots" content="noindex,follow">
  <link rel="canonical" href="{MAIN_BASE_URL}/account">
  <script src="https://cdn.tailwindcss.com"></script>
  <script defer src="https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js"></script>
  <style>body {{ letter-spacing: 0; }} [x-cloak] {{ display: none !important; }} .glass {{ background: rgba(255,255,255,.74); backdrop-filter: blur(18px); border: 1px solid rgba(226,232,240,.74); }} .soft {{ box-shadow: 0 22px 80px rgba(15,23,42,.07); }}</style>
</head>
<body class="min-h-screen bg-[#f6f7fb] text-slate-950" x-data="accountPage()">
  <header class="border-b border-slate-200/70 bg-white/80 backdrop-blur-xl">
    <div class="mx-auto flex max-w-6xl items-center justify-between px-5 py-4">
      <a href="/" class="flex items-center gap-3"><span class="grid h-10 w-10 place-items-center rounded-xl bg-orange-600 text-lg font-black text-white">M</span><span class="text-2xl font-black">meetseek</span></a>
      <a class="rounded-full bg-slate-100 px-4 py-2 text-sm font-black text-slate-700" href="/">返回首页</a>
    </div>
  </header>
  <main class="mx-auto max-w-6xl px-5 py-8">{body}</main>
  <script>
    document.addEventListener("alpine:init", () => {{
      Alpine.data("accountPage", () => ({{
        mode: "login",
        tab: "posts",
        settingsOpen: false,
        email: "",
        password: "",
        name: "",
        profileName: {initial_profile_name},
        profileEmail: {initial_profile_email},
        profilePhone: {initial_profile_phone},
        profileBio: {initial_profile_bio},
        oldPassword: "",
        newPassword: "",
        confirmPassword: "",
        message: "",
        settingsMessage: "",
        async submitAuth() {{
          this.message = "正在处理...";
          const form = new FormData();
          form.append("email", this.email);
          form.append("password", this.password);
          if (this.mode === "register") form.append("name", this.name);
          const res = await fetch(`/api/auth/${{this.mode}}`, {{ method: "POST", body: form }});
          const data = await res.json().catch(() => ({{}}));
          if (!res.ok) {{
            this.message = data.detail || "操作失败";
            return;
          }}
          location.href = "/account";
        }},
        async saveProfile() {{
          this.settingsMessage = "正在保存...";
          const form = new FormData();
          form.append("nickname", this.profileName);
          form.append("email", this.profileEmail);
          form.append("phone", this.profilePhone);
          form.append("bio", this.profileBio);
          if (this.$refs.avatarInput && this.$refs.avatarInput.files[0]) form.append("avatar", this.$refs.avatarInput.files[0]);
          const res = await fetch("/api/user/profile", {{ method: "POST", body: form }});
          const data = await res.json().catch(() => ({{}}));
          if (!res.ok) {{
            this.settingsMessage = data.detail || "保存失败";
            return;
          }}
          window.dispatchEvent(new CustomEvent("profile-updated", {{ detail: data.user || {{}} }}));
          this.profileName = data.user?.name || data.user?.nickname || this.profileName;
          this.profileEmail = data.user?.email || this.profileEmail;
          this.profilePhone = data.user?.phone || "";
          this.profileBio = data.user?.bio || "";
          if (this.$refs.avatarInput) this.$refs.avatarInput.value = "";
          this.settingsMessage = "资料保存成功";
        }},
        async changePassword() {{
          if (this.newPassword !== this.confirmPassword) {{
            this.settingsMessage = "两次输入的新密码不一致";
            return;
          }}
          this.settingsMessage = "正在修改密码...";
          const form = new FormData();
          form.append("old_password", this.oldPassword);
          form.append("new_password", this.newPassword);
          form.append("confirm_password", this.confirmPassword);
          const res = await fetch("/api/member/password", {{ method: "POST", body: form }});
          const data = await res.json().catch(() => ({{}}));
          if (!res.ok) {{
            this.settingsMessage = data.detail || "修改失败";
            return;
          }}
          this.oldPassword = "";
          this.newPassword = "";
          this.confirmPassword = "";
          this.settingsMessage = "密码修改成功";
        }},
        async checkin() {{
          const res = await fetch("/api/member/checkin", {{ method: "POST" }});
          const data = await res.json().catch(() => ({{}}));
          if (!res.ok) {{
            this.settingsMessage = data.detail || "签到失败";
            this.settingsOpen = true;
            return;
          }}
          location.reload();
        }},
        async logout() {{
          await fetch("/api/auth/logout", {{ method: "POST" }});
          location.href = "/account";
        }},
      }}));
    }});
    document.addEventListener("DOMContentLoaded", () => {{
      const avatarInput = document.getElementById("avatar-input");
      const nicknameInput = document.getElementById("profile-nickname");
      const emailInput = document.getElementById("profile-email");
      const phoneInput = document.getElementById("profile-phone");
      const bioInput = document.getElementById("profile-bio");

      function avatarMarkup(user, sizeClass, fallbackTextClass) {{
        const name = user?.name || user?.nickname || "M";
        if (user?.avatar_url) {{
          return `<img class="${{sizeClass}} object-cover" src="${{user.avatar_url}}" alt="${{name}}" loading="lazy">`;
        }}
        return `<div class="grid ${{sizeClass}} place-items-center bg-slate-950 ${{fallbackTextClass}} font-black text-white">${{name.slice(0, 1) || "M"}}</div>`;
      }}

      function applyProfileUpdate(user) {{
        const name = user?.name || user?.nickname || "";
        const bio = user?.bio || "";
        const displayName = document.getElementById("account-display-name");
        const displayBio = document.getElementById("account-bio");
        const followingCount = document.getElementById("account-following-count");
        const followersCount = document.getElementById("account-followers-count");
        const totalLikes = document.getElementById("account-total-likes");
        const avatarShell = document.getElementById("account-avatar-shell");
        const preview = document.getElementById("avatar-preview");
        if (displayName && name) displayName.textContent = name;
        if (displayBio) displayBio.textContent = bio || "这个人还没有写简介。";
        if (followingCount && user?.following_count !== undefined) followingCount.textContent = user.following_count;
        if (followersCount && user?.followers_count !== undefined) followersCount.textContent = user.followers_count;
        if (totalLikes && user?.total_likes !== undefined) totalLikes.textContent = user.total_likes;
        if (nicknameInput && name) nicknameInput.value = name;
        if (emailInput) emailInput.value = user?.email || "";
        if (phoneInput) phoneInput.value = user?.phone || "";
        if (bioInput) bioInput.value = bio;
        if (avatarShell) {{
          avatarShell.innerHTML = avatarMarkup(user, "h-20 w-20 rounded-3xl", "text-2xl");
        }}
        if (preview) {{
          const previewHtml = avatarMarkup(user, "h-full w-full rounded-full", "text-2xl");
          if (preview.tagName === "IMG" && user?.avatar_url) {{
            preview.src = user.avatar_url;
            preview.alt = name || "头像";
          }} else {{
            preview.outerHTML = previewHtml.replace("<img ", '<img id="avatar-preview" ').replace("<div ", '<div id="avatar-preview" ');
          }}
        }}
      }}

      window.addEventListener("profile-updated", (event) => {{
        applyProfileUpdate(event.detail || {{}});
      }});

      function initAccountExpandableContent(root = document) {{
        root.querySelectorAll(".account-content-box").forEach((box) => {{
          const button = box.nextElementSibling?.classList?.contains("account-expand-toggle") ? box.nextElementSibling : null;
          if (!button || box.dataset.expandReady === "true") return;
          box.dataset.expandReady = "true";
          requestAnimationFrame(() => {{
            if (box.scrollHeight > box.clientHeight + 2) {{
              button.classList.remove("hidden");
            }}
          }});
          button.addEventListener("click", () => {{
            const expanded = box.dataset.expanded === "true";
            box.dataset.expanded = expanded ? "false" : "true";
            box.classList.toggle("line-clamp-4", expanded);
            button.textContent = expanded ? "展开全文" : "收起";
          }});
        }});
      }}

      initAccountExpandableContent();

      if (avatarInput) {{
        avatarInput.addEventListener("change", () => {{
          const file = avatarInput.files && avatarInput.files[0];
          if (!file) return;
          const preview = document.getElementById("avatar-preview");
          const url = URL.createObjectURL(file);
          if (preview && preview.tagName === "IMG") {{
            preview.src = url;
          }} else if (preview) {{
            preview.innerHTML = "";
            const img = document.createElement("img");
            img.src = url;
            img.alt = "头像预览";
            img.className = "h-full w-full rounded-full object-cover";
            preview.appendChild(img);
          }}
        }});
      }}
    }});
  </script>
</body>
</html>"""


def prompt_profile_card(row: sqlite3.Row) -> str:
    title = html_escape(str(row["title"] or "未命名提示词"))
    image = html_escape(str(row["cover_image"] or ""))
    category = html_escape(str(row["category"] if "category" in row.keys() else "提示词"))
    models = prompt_json_list(row["models"] if "models" in row.keys() else row["model_engine"])
    model_text = html_escape(" / ".join(models[:2]) if models else str(row["model_engine"] or "AI 模型"))
    item_id = html_escape(str(row["item_key"] if "item_key" in row.keys() and row["item_key"] else row["id"]))
    image_html = (
        f'<img class="h-40 w-full rounded-2xl object-cover" src="{image}" alt="{title}" loading="lazy">'
        if image
        else '<div class="grid h-40 w-full place-items-center rounded-2xl bg-slate-100 text-2xl font-black text-slate-300">Prompt</div>'
    )
    prompt_text = str(row["prompt_text"] or row["zh"] or row["description"] or "")
    text = html_escape(prompt_text[:120])
    copy_text = html_escape(prompt_text)
    return f"""
    <article class="rounded-3xl border border-slate-100 bg-white p-4 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md">
      <a href="{PROMPTS_BASE_URL}/prompt/{item_id}" class="block">{image_html}</a>
      <div class="mt-4">
        <div class="flex flex-wrap gap-2 text-xs font-black text-slate-400">
          <span class="rounded-full bg-orange-50 px-2.5 py-1 text-orange-600">{category}</span>
          <span class="rounded-full bg-slate-100 px-2.5 py-1">{model_text}</span>
        </div>
        <a href="{PROMPTS_BASE_URL}/prompt/{item_id}" class="mt-3 block text-lg font-black leading-snug text-slate-950 hover:text-orange-600">{title}</a>
        <p class="mt-2 line-clamp-3 text-sm leading-6 text-slate-500">{text}</p>
        <button class="mt-4 rounded-full bg-slate-950 px-4 py-2 text-xs font-black text-white transition hover:bg-orange-600" type="button" data-copy-prompt="{copy_text}">复制 Prompt</button>
      </div>
    </article>
    """


def empty_profile_state(text: str) -> str:
    return f"""
    <div class="rounded-3xl border border-dashed border-slate-200 bg-white p-10 text-center">
      <svg class="mx-auto h-14 w-14 text-slate-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
        <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5A3.375 3.375 0 0 0 10.125 2.25H8.25m0 12.75h7.5m-7.5-3h7.5m-7.5-3h3M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z"/>
      </svg>
      <p class="mt-4 text-base font-black text-slate-500">{html_escape(text)}</p>
      <a class="mt-3 inline-flex text-sm font-black text-orange-600" href="{PROMPTS_BASE_URL}/">去提示词库看看</a>
    </div>
    """


def render_user_profile_html(request: Request, user: dict[str, Any]) -> str:
    with db() as conn:
        authored = conn.execute(
            """
            SELECT * FROM prompts
            WHERE author_id = ? AND hidden = 0
            ORDER BY sort_order DESC, created_at DESC, id DESC
            LIMIT 60
            """,
            (user["id"],),
        ).fetchall()
        favorites = conn.execute(
            """
            SELECT prompts.* FROM favorites
            JOIN prompts ON prompts.id = favorites.prompt_id
            WHERE favorites.user_id = ? AND prompts.hidden = 0
            ORDER BY favorites.created_at DESC
            LIMIT 60
            """,
            (user["id"],),
        ).fetchall()
    avatar = html_escape(str(user.get("avatar_url") or ""))
    name = html_escape(str(user.get("name") or "meetseek"))
    created = datetime.fromtimestamp(int(user.get("created_at") or now()), CN_TZ).strftime("%Y年%m月%d日")
    avatar_html = (
        f'<img class="h-24 w-24 rounded-3xl object-cover ring-4 ring-white" src="{avatar}" alt="{name}" loading="lazy">'
        if avatar
        else f'<div class="grid h-24 w-24 place-items-center rounded-3xl bg-slate-950 text-3xl font-black text-white ring-4 ring-white">{name[:1]}</div>'
    )
    authored_html = "".join(prompt_profile_card(row) for row in authored) or empty_profile_state("这里空空如也，还没有发布提示词。")
    favorites_html = "".join(prompt_profile_card(row) for row in favorites) or empty_profile_state("这里空空如也，还没有收藏提示词。")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>个人主页 - meetseek</title>
  <meta name="robots" content="noindex,follow">
  <script src="https://cdn.tailwindcss.com"></script>
  <script defer src="https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js"></script>
  <style>[x-cloak] { display: none !important; }</style>
</head>
<body class="min-h-screen bg-slate-50 text-slate-950" x-data="{{ tab: 'posts' }}">
  <header class="border-b border-slate-200/70 bg-white/80 backdrop-blur-xl">
    <div class="mx-auto flex max-w-6xl items-center justify-between px-5 py-4">
      <a href="/" class="flex items-center gap-3"><span class="grid h-10 w-10 place-items-center rounded-xl bg-orange-600 text-lg font-black text-white">M</span><span class="text-2xl font-black">meetseek</span></a>
      <a class="rounded-full bg-slate-100 px-4 py-2 text-sm font-black text-slate-700" href="/">返回首页</a>
    </div>
  </header>
  <main class="mx-auto max-w-6xl px-5 py-8">
    <section class="overflow-hidden rounded-3xl border border-slate-100 bg-white shadow-sm">
      <div class="h-32 bg-gradient-to-r from-slate-100 to-orange-50"></div>
      <div class="-mt-12 flex flex-wrap items-end justify-between gap-5 px-7 pb-7">
        <div class="flex items-end gap-5">
          {avatar_html}
          <div class="pb-2">
            <h1 class="text-4xl font-black">{name}</h1>
            <p class="mt-2 text-sm font-bold text-slate-400">加入于 {created} · {html_escape(str(user.get("tier") or "free")).upper()} · {int(user.get("points") or 0)} 积分</p>
          </div>
        </div>
        <a class="rounded-2xl bg-slate-950 px-5 py-3 text-sm font-black text-white transition hover:bg-orange-600" href="/account">资料设置</a>
      </div>
    </section>
    <section class="mt-6 rounded-3xl border border-slate-100 bg-white p-3 shadow-sm">
      <div class="flex gap-2">
        <button class="rounded-2xl px-5 py-3 text-sm font-black transition" :class="tab === 'posts' ? 'bg-orange-50 text-orange-600' : 'text-slate-500 hover:bg-slate-50'" type="button" @click="tab = 'posts'">我的发布</button>
        <button class="rounded-2xl px-5 py-3 text-sm font-black transition" :class="tab === 'favorites' ? 'bg-orange-50 text-orange-600' : 'text-slate-500 hover:bg-slate-50'" type="button" @click="tab = 'favorites'">我的收藏</button>
      </div>
      <div class="mt-4 grid gap-4 p-2 sm:grid-cols-2 lg:grid-cols-3" x-show="tab === 'posts'">{authored_html}</div>
      <div class="mt-4 grid gap-4 p-2 sm:grid-cols-2 lg:grid-cols-3" x-show="tab === 'favorites'" x-cloak>{favorites_html}</div>
    </section>
  </main>
  <script>
    document.addEventListener("click", async (event) => {{
      const button = event.target.closest("[data-copy-prompt]");
      if (!button) return;
      const label = button.textContent;
      await navigator.clipboard.writeText(button.dataset.copyPrompt || "");
      button.textContent = "已复制";
      button.classList.add("bg-orange-600");
      setTimeout(() => {{
        button.textContent = label;
        button.classList.remove("bg-orange-600");
      }}, 1500);
    }});
  </script>
</body>
</html>"""


def prompt_seo_json_ld(items: list[dict[str, Any]]) -> str:
    data = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": "meetseek 提示词库",
        "url": f"{PROMPTS_BASE_URL}/",
        "inLanguage": "zh-CN",
        "description": "可直接复制使用的 AI 绘图提示词图库，包含中文 Prompt、English Prompt、风格标签和适用模型标签。",
        "mainEntity": {
            "@type": "ItemList",
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": index + 1,
                    "url": f"{PROMPTS_BASE_URL}/prompt/{item.get('id')}",
                    "item": {
                        "@type": "CreativeWork",
                        "name": item.get("title", ""),
                        "description": (item.get("zh") or item.get("description") or item.get("en") or "")[:300],
                        "keywords": ", ".join([*(item.get("tags") or []), *(item.get("models") or []), item.get("category", "")]).strip(", "),
                    },
                }
                for index, item in enumerate(items[:50])
                if item.get("id") and item.get("kind") != "ad"
            ],
        },
    }
    return safe_json_ld(data)


def prompt_seo_fallback(items: list[dict[str, Any]]) -> str:
    articles = []
    for item in items[:24]:
        if item.get("kind") == "ad":
            continue
        tags = " / ".join([*(item.get("tags") or []), *(item.get("models") or [])])
        image = absolute_public_url(item.get("image", ""), PROMPTS_BASE_URL) if item.get("image") else ""
        image_html = f'<img src="{html_escape(image)}" alt="{html_escape(item.get("title"))}" loading="lazy">' if image else ""
        articles.append(
            "\n".join(
                [
                    '<article class="prompt-seo-item">',
                    f'<h3><a href="/prompt/{html_escape(item.get("id"))}">{html_escape(item.get("title"))}</a></h3>',
                    f"<p>{html_escape(item.get('category'))}{' · ' if tags else ''}{html_escape(tags)}</p>",
                    image_html,
                    f"<p>{html_escape(item.get('zh'))}</p>",
                    f"<p>{html_escape(item.get('en'))}</p>",
                    "</article>",
                ]
            )
        )
    return (
        '<noscript><section class="mt-8 grid gap-5 rounded-2xl border border-slate-200 bg-white p-5">'
        '<h2 class="text-2xl font-black">提示词内容</h2>'
        + "".join(articles)
        + "</section></noscript>"
    )


def render_prompt_index_html(items: list[dict[str, Any]]) -> str:
    content = (APP_ROOT / "static" / "prompt.html").read_text(encoding="utf-8")
    return (
        content
        .replace("<!--PROMPT_SEO_JSON_LD-->", prompt_seo_json_ld(items))
        .replace("<!--PROMPT_SEO_FALLBACK-->", prompt_seo_fallback(items))
    )


def render_prompt_detail_html(item: dict[str, Any], favorited: bool = False) -> str:
    title = item.get("title") or "AI 绘图提示词"
    description = (item.get("zh") or item.get("description") or item.get("en") or "")[:160]
    canonical = f"{PROMPTS_BASE_URL}/prompt/{item.get('id')}"
    image_url = absolute_public_url(item.get("image", ""), PROMPTS_BASE_URL) if item.get("image") else ""
    prompt_id = int(item.get("_index") or item.get("prompt_id") or 0)
    heart_path = (
        '<path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.08C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>'
        if favorited
        else '<path stroke-linecap="round" stroke-linejoin="round" d="M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12Z"/>'
    )
    tags = [item.get("category", ""), *(item.get("tags") or []), *(item.get("models") or [])]
    json_ld = {
        "@context": "https://schema.org",
        "@type": "CreativeWork",
        "name": title,
        "url": canonical,
        "inLanguage": "zh-CN",
        "description": description,
        "keywords": ", ".join([tag for tag in tags if tag]),
        "text": item.get("zh") or item.get("en") or "",
    }
    if image_url:
        json_ld["image"] = image_url
    image_block = f'<img class="hero-image" src="{html_escape(image_url)}" alt="{html_escape(title)}">' if image_url else ""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html_escape(title)} - meetseek 提示词库</title>
  <meta name="description" content="{html_escape(description)}">
  <meta name="robots" content="index,follow,max-image-preview:large">
  <link rel="canonical" href="{html_escape(canonical)}">
  <meta property="og:locale" content="zh_CN">
  <meta property="og:type" content="article">
  <meta property="og:site_name" content="meetseek 提示词库">
  <meta property="og:title" content="{html_escape(title)}">
  <meta property="og:description" content="{html_escape(description)}">
  <meta property="og:url" content="{html_escape(canonical)}">
  {f'<meta property="og:image" content="{html_escape(image_url)}">' if image_url else ''}
  <meta name="twitter:card" content="summary_large_image">
  {safe_json_ld(json_ld)}
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f6f7fb; color: #0f172a; letter-spacing: 0; }}
    header, main {{ max-width: 1040px; margin: 0 auto; padding: 24px; }}
    a {{ color: #ea580c; text-decoration: none; font-weight: 800; }}
    .logo {{ display: inline-flex; align-items: center; gap: 12px; color: #0f172a; }}
    .mark {{ display: grid; width: 36px; height: 36px; place-items: center; border-radius: 10px; background: #ea580c; color: white; font-weight: 900; }}
    article {{ overflow: hidden; border: 1px solid #e2e8f0; border-radius: 24px; background: white; box-shadow: 0 16px 40px rgba(15, 23, 42, .06); }}
    .content {{ padding: 28px; }}
    h1 {{ margin: 10px 0 12px; font-size: clamp(32px, 5vw, 56px); line-height: 1.05; }}
    .meta, .chips {{ display: flex; flex-wrap: wrap; gap: 8px; color: #64748b; }}
    .chip {{ border-radius: 999px; background: #eef2f7; padding: 6px 10px; font-size: 13px; font-weight: 800; }}
    .model {{ background: #dcfce7; color: #047857; }}
    .hero-image {{ display: block; width: 100%; height: auto; max-height: 84vh; object-fit: contain; background: #0f172a; }}
    .prompt {{ margin-top: 20px; border-radius: 18px; background: #f8fafc; padding: 20px; white-space: pre-wrap; line-height: 1.8; }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 20px; }}
    .favorite {{ display: inline-flex; align-items: center; gap: 8px; border: 1px solid #e2e8f0; border-radius: 999px; background: white; padding: 10px 14px; color: #94a3b8; font-weight: 900; cursor: pointer; transition: transform .15s ease, color .15s ease, background .15s ease; }}
    .favorite:hover {{ transform: scale(1.04); color: #ef4444; background: #fff1f2; }}
    .favorite.is-favorited {{ color: #ef4444; }}
    .favorite svg {{ width: 20px; height: 20px; }}
    footer {{ margin-top: 28px; color: #64748b; }}
  </style>
</head>
<body>
  <header>
    <a class="logo" href="/">
      <span class="mark">M</span>
      <span>meetseek 提示词库</span>
    </a>
  </header>
  <main>
    <article>
      {image_block}
      <div class="content">
        <div class="meta">{html_escape(item.get("category"))}</div>
        <h1>{html_escape(title)}</h1>
        <div class="chips">
          {"".join(f'<span class="chip">{html_escape(tag)}</span>' for tag in (item.get("tags") or []))}
          {"".join(f'<span class="chip model">{html_escape(model)}</span>' for model in (item.get("models") or []))}
        </div>
        <section class="prompt"><h2>中文 Prompt</h2>{html_escape(item.get("zh"))}</section>
        <section class="prompt"><h2>English Prompt</h2>{html_escape(item.get("en"))}</section>
        <div class="actions">
          <button id="favorite-button" class="favorite {'is-favorited' if favorited else ''}" type="button" data-prompt-id="{prompt_id}" data-favorited="{'true' if favorited else 'false'}">
            <svg viewBox="0 0 24 24" fill="{'currentColor' if favorited else 'none'}" stroke="currentColor" stroke-width="1.8" aria-hidden="true">{heart_path}</svg>
            <span>{'已收藏' if favorited else '收藏'}</span>
          </button>
        </div>
      </div>
    </article>
    <footer><a href="/">返回提示词图库</a> · <a href="/reverse">图片反推</a> · <a href="https://tools.meetseek.ai/">工具箱</a></footer>
  </main>
  <script>
    const favoriteButton = document.getElementById("favorite-button");
    function renderFavoriteButton(favorited) {{
      favoriteButton.dataset.favorited = favorited ? "true" : "false";
      favoriteButton.classList.toggle("is-favorited", favorited);
      favoriteButton.querySelector("span").textContent = favorited ? "已收藏" : "收藏";
      favoriteButton.querySelector("svg").setAttribute("fill", favorited ? "currentColor" : "none");
      favoriteButton.querySelector("svg").innerHTML = favorited
        ? '<path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.08C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>'
        : '<path stroke-linecap="round" stroke-linejoin="round" d="M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12Z"/>';
    }}
    favoriteButton?.addEventListener("click", async () => {{
      const previous = favoriteButton.dataset.favorited === "true";
      renderFavoriteButton(!previous);
      const response = await fetch(`/api/prompts/${{favoriteButton.dataset.promptId}}/favorite`, {{ method: "POST" }});
      const data = await response.json().catch(() => ({{}}));
      if (response.status === 401) {{
        location.href = "/login";
        return;
      }}
      if (!response.ok) {{
        renderFavoriteButton(previous);
        return;
      }}
      renderFavoriteButton(Boolean(data.favorited));
    }});
  </script>
</body>
</html>"""


def sitemap_url(loc: str, lastmod: str, changefreq: str = "weekly", priority: str = "0.7", image: str = "", image_title: str = "") -> str:
    image_part = ""
    if image:
        image_part = (
            "<image:image>"
            f"<image:loc>{html_escape(image)}</image:loc>"
            f"<image:title>{html_escape(image_title)}</image:title>"
            "</image:image>"
        )
    return (
        "<url>"
        f"<loc>{html_escape(loc)}</loc>"
        f"<lastmod>{html_escape(lastmod)}</lastmod>"
        f"<changefreq>{html_escape(changefreq)}</changefreq>"
        f"<priority>{html_escape(priority)}</priority>"
        f"{image_part}"
        "</url>"
    )


async def save_uploaded_image_webp(
    image: UploadFile,
    folder: Path,
    prefix: str,
    max_side: int = 1800,
    quality: int = 86,
    max_mb: int | None = MAX_IMAGE_MB,
) -> str:
    if not (image.content_type or "").startswith("image/"):
        raise HTTPException(status_code=400, detail="请上传图片文件")
    content = await image.read()
    if not content:
        raise HTTPException(status_code=400, detail="图片不能为空")
    if max_mb is not None and len(content) > max_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"图片不能超过 {max_mb}MB")
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log_event("error", "上传目录不可写", folder=str(folder), error=str(exc))
        raise HTTPException(status_code=500, detail="上传目录不可写，请检查服务器存储权限")
    try:
        from PIL import Image, UnidentifiedImageError

        if max_mb is None:
            Image.MAX_IMAGE_PIXELS = None
        source = Image.open(BytesIO(content))
        source.verify()
        source = Image.open(BytesIO(content))
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise HTTPException(status_code=400, detail="无法识别真实图片类型")
    try:
        source.thumbnail((max_side, max_side))
        if source.mode not in {"RGB", "RGBA"}:
            source = source.convert("RGB")
    except (OSError, SyntaxError, ValueError):
        raise HTTPException(status_code=400, detail="图片文件已损坏，无法处理")
    filename = f"{prefix}-{uuid.uuid4().hex}.webp"
    output = folder / filename
    try:
        source.save(output, "WEBP", quality=quality, method=6)
    except OSError as exc:
        log_event("error", "图片保存失败", folder=str(folder), error=str(exc))
        raise HTTPException(status_code=500, detail="图片保存失败，请检查服务器存储权限")
    return filename


async def save_prompt_gallery_image(image: UploadFile, prefix: str) -> str:
    filename = await save_uploaded_image_webp(image, PROMPT_IMAGE_DIR, prefix, max_side=2200, quality=88)
    return f"/api/prompts/images/{filename}"


async def save_avatar_image(image: UploadFile) -> str:
    filename = await save_uploaded_image_webp(image, AVATAR_DIR, "avatar", max_side=512, quality=84, max_mb=None)
    return f"/api/avatars/{filename}"


def clean_plugin_url(value: str, label: str = "链接") -> str:
    clean = (value or "").strip()[:2000]
    if not clean:
        return ""
    parsed = urlparse(clean)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail=f"{label}只支持 http 或 https")
    return clean


def clean_plugin_slug_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "").strip().lower()
    ascii_text = text.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    if not slug and lazy_pinyin:
        slug = "-".join(part for part in lazy_pinyin(value or "") if part)
        slug = re.sub(r"[^a-z0-9]+", "-", slug.lower()).strip("-")
    return slug[:72].strip("-") or f"plugin-{uuid.uuid4().hex[:8]}"


def unique_plugin_slug(conn: sqlite3.Connection, title: str) -> str:
    base = clean_plugin_slug_text(title)
    candidate = base
    counter = 2
    while conn.execute("SELECT 1 FROM plugins WHERE slug = ? LIMIT 1", (candidate,)).fetchone():
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


async def save_plugin_icon(icon: UploadFile | None) -> str:
    if not icon or not icon.filename:
        return ""
    suffix = Path(icon.filename).suffix.lower()
    content_type = (icon.content_type or "").lower()
    if suffix == ".svg" or content_type in {"image/svg+xml", "text/xml"}:
        content = await icon.read()
        if not content:
            raise HTTPException(status_code=400, detail="图标不能为空")
        if len(content) > 512 * 1024:
            raise HTTPException(status_code=413, detail="SVG 图标不能超过 512KB")
        text = content.decode("utf-8", errors="ignore")
        if re.search(r"<\s*script|on[a-z]+\s*=", text, re.I):
            raise HTTPException(status_code=400, detail="SVG 图标包含不安全脚本")
        PLUGIN_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"plugin-icon-{uuid.uuid4().hex}.svg"
        (PLUGIN_IMAGE_DIR / filename).write_bytes(content)
        return f"/api/plugins/images/{filename}"
    filename = await save_uploaded_image_webp(icon, PLUGIN_IMAGE_DIR, "plugin-icon", max_side=512, quality=88, max_mb=2)
    return f"/api/plugins/images/{filename}"


async def save_plugin_image(image: UploadFile | None, prefix: str, max_side: int = 1800) -> str:
    if not image or not image.filename:
        return ""
    filename = await save_uploaded_image_webp(image, PLUGIN_IMAGE_DIR, prefix, max_side=max_side, quality=88, max_mb=5)
    return f"/api/plugins/images/{filename}"


async def save_post_media_file(file: UploadFile, kind: str) -> dict[str, str]:
    content_type = (file.content_type or "").lower()
    if kind not in {"image", "video", "gif"}:
        raise HTTPException(status_code=400, detail="未知媒体类型")
    if kind == "image":
        filename = await save_uploaded_image_webp(file, POST_MEDIA_DIR, "post-image", max_side=2200, quality=88)
        return {"kind": "image", "url": f"/api/post-media/{filename}", "mime": "image/webp"}
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件不能为空")
    if kind == "gif":
        if content_type not in {"image/gif"}:
            raise HTTPException(status_code=400, detail="请选择 GIF 文件")
        if len(content) > MAX_IMAGE_MB * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"GIF 不能超过 {MAX_IMAGE_MB}MB")
        try:
            from PIL import Image, UnidentifiedImageError

            source = Image.open(BytesIO(content))
            source.verify()
            if (source.format or "").upper() != "GIF":
                raise HTTPException(status_code=400, detail="请选择真实 GIF 文件")
        except HTTPException:
            raise
        except (UnidentifiedImageError, OSError):
            raise HTTPException(status_code=400, detail="无法识别真实 GIF 类型")
        filename = f"post-gif-{uuid.uuid4().hex}.gif"
        (POST_MEDIA_DIR / filename).write_bytes(content)
        return {"kind": "gif", "url": f"/api/post-media/{filename}", "mime": "image/gif"}
    if not content_type.startswith("video/"):
        raise HTTPException(status_code=400, detail="请选择视频文件")
    if len(content) > min(MAX_VIDEO_FILE_MB, 200) * 1024 * 1024:
        raise HTTPException(status_code=413, detail="视频不能超过 200MB")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".mp4", ".mov", ".webm", ".m4v"}:
        suffix = ".mp4"
    filename = f"post-video-{uuid.uuid4().hex}{suffix}"
    (POST_MEDIA_DIR / filename).write_bytes(content)
    return {"kind": "video", "url": f"/api/post-media/{filename}", "mime": content_type or "video/mp4"}


def public_checkin(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "day": row["day"],
        "points": row["points"],
        "streak": row["streak"],
        "created_at": row["created_at"],
    }


def checkin_state(user_id: int) -> dict[str, Any]:
    today = today_key()
    yesterday = yesterday_key()
    with db() as conn:
        today_row = conn.execute(
            "SELECT * FROM daily_checkins WHERE user_id = ? AND day = ?",
            (user_id, today),
        ).fetchone()
        latest = conn.execute(
            "SELECT * FROM daily_checkins WHERE user_id = ? ORDER BY day DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        total = conn.execute("SELECT COUNT(*) AS count FROM daily_checkins WHERE user_id = ?", (user_id,)).fetchone()["count"]
        recent = conn.execute(
            "SELECT * FROM daily_checkins WHERE user_id = ? ORDER BY day DESC LIMIT 10",
            (user_id,),
        ).fetchall()
    active_streak = latest["streak"] if latest and latest["day"] in {today, yesterday} else 0
    return {
        "today": today,
        "checked_today": bool(today_row),
        "current_streak": active_streak,
        "total_checkins": total,
        "today_checkin": public_checkin(today_row) if today_row else None,
        "recent": [public_checkin(row) for row in recent],
    }


def recent_admin_checkins() -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT daily_checkins.*, users.email, users.name
            FROM daily_checkins
            JOIN users ON users.id = daily_checkins.user_id
            ORDER BY daily_checkins.created_at DESC
            LIMIT 30
            """
        ).fetchall()
    return [
        {
            "email": row["email"],
            "name": row["name"],
            "day": row["day"],
            "points": row["points"],
            "streak": row["streak"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def package_by_id(package_id: str) -> dict[str, Any]:
    for package in public_payment_config().get("packages", []):
        if str(package.get("id")) == package_id:
            return package
    raise HTTPException(status_code=400, detail="未知积分套餐")


def currency_minor_units(currency: str) -> int:
    zero_decimal = {
        "bif", "clp", "djf", "gnf", "jpy", "kmf", "krw", "mga", "pyg", "rwf",
        "ugx", "vnd", "vuv", "xaf", "xof", "xpf",
    }
    return 0 if currency.lower() in zero_decimal else 2


def stripe_amount_minor(amount: float, currency: str) -> int:
    exponent = currency_minor_units(currency)
    decimal_amount = Decimal(str(amount))
    multiplier = Decimal(10) ** exponent
    minor = (decimal_amount * multiplier).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return max(1, int(minor))


def stripe_default_success_url() -> str:
    return f"{PUBLIC_BASE_URL}/?stripe=success"


def stripe_default_cancel_url() -> str:
    return f"{PUBLIC_BASE_URL}/?stripe=cancel"


def verify_stripe_signature(payload: bytes, signature_header: str, webhook_secret: str, tolerance: int = 300) -> None:
    parts: dict[str, list[str]] = defaultdict(list)
    for item in signature_header.split(","):
        if "=" in item:
            key, value = item.split("=", 1)
            parts[key].append(value)
    timestamp_values = parts.get("t", [])
    signatures = parts.get("v1", [])
    if not timestamp_values or not signatures:
        raise HTTPException(status_code=400, detail="Stripe 签名头不完整")
    try:
        timestamp = int(timestamp_values[0])
    except ValueError:
        raise HTTPException(status_code=400, detail="Stripe 签名时间戳无效")
    if abs(int(now()) - timestamp) > tolerance:
        raise HTTPException(status_code=400, detail="Stripe 签名已过期")
    signed_payload = f"{timestamp}.".encode("utf-8") + payload
    expected = hmac.new(webhook_secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, signature) for signature in signatures):
        raise HTTPException(status_code=400, detail="Stripe 签名校验失败")


def xunhu_sign(params: dict[str, Any], appsecret: str) -> str:
    sign_params = {
        key: str(value)
        for key, value in params.items()
        if key != "hash" and value is not None and str(value) != ""
    }
    sign_source = "&".join(f"{key}={sign_params[key]}" for key in sorted(sign_params))
    return hashlib.md5(f"{sign_source}{appsecret}".encode("utf-8")).hexdigest()


def verify_xunhu_hash(params: dict[str, Any], appsecret: str) -> bool:
    provided = str(params.get("hash") or "").lower()
    if not provided:
        return False
    return hmac.compare_digest(provided, xunhu_sign(params, appsecret).lower())


def format_yuan_amount(amount: float) -> str:
    return str(Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def save_optional_image(upload: UploadFile | None, folder: Path, prefix: str, max_mb: int = 5) -> str:
    if not upload or not upload.filename:
        return ""
    if not (upload.content_type or "").startswith("image/"):
        raise HTTPException(status_code=400, detail="请上传图片文件")
    suffix = Path(upload.filename).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        suffix = ".png"
    filename = f"{prefix}-{uuid.uuid4().hex}{suffix}"
    path = folder / filename
    size = 0
    with path.open("wb") as handle:
        while chunk := upload.file.read(1024 * 1024):
            size += len(chunk)
            if size > max_mb * 1024 * 1024:
                path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail=f"图片不能超过 {max_mb}MB")
            handle.write(chunk)
    return filename


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    return (forwarded.split(",")[0] or request.client.host or "unknown").strip()


def check_rate_limit(request: Request) -> None:
    ip = client_ip(request)
    bucket = rate_buckets[ip]
    cutoff = now() - 60
    while bucket and bucket[0] < cutoff:
        bucket.popleft()
    if len(bucket) >= RATE_LIMIT_PER_MINUTE:
        raise HTTPException(status_code=429, detail="请求太频繁，请稍后再试")
    bucket.append(now())


def require_feature(name: str) -> None:
    if not feature_flags.get(name, True):
        raise HTTPException(status_code=403, detail="该工具暂时关闭")


def public_video_config() -> dict[str, Any]:
    qualities = {
        key: {
            "label": value["label"],
            "height": value["height"],
            "enabled": True,
        }
        for key, value in video_quality_options.items()
    }
    return {
        "qualities": qualities,
        "max_file_mb": MAX_VIDEO_FILE_MB,
        "download_limits": {
            "single": usage_rule_for("video_download"),
            "batch": usage_rule_for("video_batch"),
        },
    }


def validate_video_quality(quality: str) -> str:
    if quality not in video_quality_options:
        raise HTTPException(status_code=400, detail="不支持的清晰度")
    return quality


URL_IN_TEXT_RE = re.compile(r"https?://[^\s<>\"]+", re.IGNORECASE)


def extract_first_url(value: str) -> str:
    clean = (value or "").strip()
    match = URL_IN_TEXT_RE.search(clean)
    if match:
        clean = match.group(0)
    return clean.rstrip("，。；、!！?？)）]】'\"")


def legal_url(url: str) -> str:
    clean = extract_first_url(url)
    if not clean.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="请输入有效链接")
    parsed = urlparse(clean)
    host = parsed.hostname
    if not host:
        raise HTTPException(status_code=400, detail="请输入有效链接")
    try:
        resolved = {item[4][0] for item in socket.getaddrinfo(host, None)}
    except socket.gaierror:
        raise HTTPException(status_code=400, detail="无法解析该域名")
    for address in resolved:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            raise HTTPException(status_code=400, detail="不支持内网、localhost 或保留地址链接")
    return clean


def format_selector(quality: str) -> str:
    if quality == "audio":
        return "bestaudio/best"
    height = video_quality_options.get(quality, video_quality_options["1080p"])["height"]
    return f"bestvideo[height<={height}]+bestaudio/best[height<={height}]/best"


def postprocessors_for_quality(quality: str) -> list[dict[str, str]]:
    if quality == "audio":
        return [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
    return [{"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}]


def readable_size(bytes_value: int | None) -> str | None:
    if not bytes_value:
        return None
    units = ["B", "KB", "MB", "GB"]
    size = float(bytes_value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return None


def safe_file_part(name: str, fallback: str = "file") -> str:
    cleaned = "".join(char if char.isascii() and (char.isalnum() or char in "._-") else "-" for char in name).strip(".-")
    return (cleaned or fallback)[:80]


def remove_directory(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def remove_file(path: str | Path) -> None:
    Path(path).unlink(missing_ok=True)


def compression_profile(mode: str) -> dict[str, Any]:
    profiles = {
        "clear": {"label": "高清压缩", "image_quality": 90, "webp_quality": 88, "crf": "20", "preset": "slow"},
        "balanced": {"label": "均衡压缩", "image_quality": 82, "webp_quality": 80, "crf": "24", "preset": "medium"},
        "small": {"label": "极限压缩", "image_quality": 68, "webp_quality": 68, "crf": "29", "preset": "medium"},
    }
    return profiles.get(mode, profiles["balanced"])


def compress_image_file(input_path: Path, output_path: Path, mode: str) -> None:
    from PIL import Image, ImageOps

    profile = compression_profile(mode)
    with Image.open(input_path) as opened:
        image = ImageOps.exif_transpose(opened)
        suffix = output_path.suffix.lower()
        if suffix in {".jpg", ".jpeg"}:
            if image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
            image.save(output_path, "JPEG", quality=profile["image_quality"], optimize=True, progressive=True)
        elif suffix == ".webp":
            image.save(output_path, "WEBP", quality=profile["webp_quality"], method=6)
        else:
            if image.mode not in {"RGB", "RGBA", "P", "L"}:
                image = image.convert("RGBA")
            image.save(output_path, "PNG", optimize=True, compress_level=9)


async def compress_video_file(input_path: Path, output_path: Path, mode: str) -> None:
    profile = compression_profile(mode)
    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-map",
        "0:v:0?",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        profile["preset"],
        "-crf",
        profile["crf"],
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(output_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="ignore")[-500:] or "FFmpeg 压缩失败"
        raise RuntimeError(detail)


async def save_upload(upload: UploadFile, output_path: Path, limit_mb: int) -> int:
    total = 0
    with output_path.open("wb") as handle:
        while chunk := await upload.read(1024 * 1024):
            total += len(chunk)
            if total > limit_mb * 1024 * 1024:
                raise HTTPException(status_code=413, detail=f"文件不能超过 {limit_mb}MB")
            handle.write(chunk)
    return total


def pdf_to_docx(input_path: Path, output_path: Path) -> None:
    import fitz
    from docx import Document

    document = Document()
    pdf = fitz.open(input_path)
    try:
        for index, page in enumerate(pdf, start=1):
            if index > 1:
                document.add_page_break()
            document.add_heading(f"第 {index} 页", level=2)
            text = page.get_text("text").strip()
            if text:
                for paragraph in text.splitlines():
                    if paragraph.strip():
                        document.add_paragraph(paragraph.strip())
            else:
                document.add_paragraph("这一页未识别到可提取文本，可能是扫描件或图片型 PDF。")
    finally:
        pdf.close()
    document.save(output_path)


def pdf_to_long_image(input_path: Path, output_path: Path) -> None:
    import fitz
    from PIL import Image

    pdf = fitz.open(input_path)
    try:
        if len(pdf) > 30:
            raise RuntimeError("PDF 页数超过 30 页，长图会过大，请先拆分后再转换")
        images = []
        for page in pdf:
            pixmap = page.get_pixmap(matrix=fitz.Matrix(1.8, 1.8), alpha=False)
            image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
            images.append(image)
        if not images:
            raise RuntimeError("PDF 没有可转换页面")
        width = max(image.width for image in images)
        height = sum(image.height for image in images)
        long_image = Image.new("RGB", (width, height), "white")
        y = 0
        for image in images:
            x = (width - image.width) // 2
            long_image.paste(image, (x, y))
            y += image.height
        long_image.save(output_path, "PNG", optimize=True)
    finally:
        pdf.close()


def images_to_pdf(input_paths: list[Path], output_path: Path) -> None:
    from PIL import Image, ImageOps

    pages = []
    for input_path in input_paths:
        with Image.open(input_path) as opened:
            image = ImageOps.exif_transpose(opened)
            if image.mode != "RGB":
                image = image.convert("RGB")
            pages.append(image.copy())
    if not pages:
        raise RuntimeError("请至少上传一张图片")
    first, rest = pages[0], pages[1:]
    first.save(output_path, "PDF", save_all=True, append_images=rest, resolution=150)


def fallback_rewrite(text: str, style: str) -> str:
    clean = " ".join(text.strip().split())
    if not clean:
        raise HTTPException(status_code=400, detail="请输入要转换的文案")
    if style == "zhihu":
        return (
            f"先说结论：{clean}\n\n"
            "这件事真正值得注意的，不是表面上的功能点，而是它解决了一个很具体的使用场景。\n\n"
            "如果拆开来看，可以分成三层：第一，用户为什么会需要它；第二，它是否足够简单；第三，它能不能稳定复用。"
            "只要这三点成立，它就不是一个花哨的小功能，而是一个有真实价值的工具。"
        )
    return (
        f"真的被这个小功能香到了！✨\n\n{clean}\n\n"
        "以前这种事总是要来回折腾，现在一步就能搞定，省时间也省心。\n\n"
        "适合：\n"
        "1. 想快速出内容的人\n"
        "2. 不想被复杂工具劝退的人\n"
        "3. 需要马上交付结果的人\n\n"
        "属于是用过就回不去的程度～"
    )


async def ai_rewrite(text: str, style: str) -> dict[str, str]:
    style_name = "小红书体" if style == "xiaohongshu" else "知乎体"
    engine = prompt_engine_config("copy_rewrite")
    if not engine.get("api_key"):
        return {"text": fallback_rewrite(text, style), "provider": "local-fallback"}

    prompt = (
        f"请把下面这段说明改写成{style_name}中文内容。"
        "要求：保留核心事实，不编造数据；表达自然、有传播感；不要解释改写过程，只输出成稿。\n\n"
        f"原文：{text.strip()[:3000]}"
    )
    try:
        output = await prompt_chat_completion(engine, [
            {"role": "system", "content": engine.get("skill") or DEFAULT_REWRITE_SKILL},
            {"role": "user", "content": prompt},
        ])
        return {"text": output, "provider": engine["provider"]}
    except Exception as exc:
        log_event("error", "AI 文案转换失败，已使用本地兜底", provider=engine["provider"], model=engine["model"], error=str(exc)[:180])
        return {"text": fallback_rewrite(text, style), "provider": "local-fallback"}


def fallback_image_prompt(filename: str, provider: str = "local-fallback", model: str = "") -> dict[str, str]:
    base = safe_file_part(Path(filename).stem, "uploaded-image").replace("-", " ")
    cn = (
        f"一张以“{base}”为主题的高质量图片，主体清晰，构图干净，光线自然，细节丰富，"
        "背景简洁但有层次，整体画面具有高级感和真实质感，适合社交媒体封面或视觉海报。"
    )
    en = (
        f"A high-quality image inspired by \"{base}\", clear main subject, clean composition, natural lighting, "
        "rich details, a simple yet layered background, premium realistic texture, suitable for a social media cover or visual poster."
    )
    return {"zh": cn, "en": en, "provider": provider, "model": model}


def env_api_key_for_provider(provider: str) -> str:
    return OPENAI_API_KEY if provider == "openai" else ""


def clean_api_key(value: str | None) -> str:
    key = str(value or "").strip().strip('"').strip("'")
    if key.lower().startswith("bearer "):
        key = key[7:].strip()
    return key


def default_model_for_preset(preset: dict[str, Any], kind: str) -> str:
    if kind == "vision":
        return preset.get("vision_model") or preset.get("model") or OPENAI_MODEL
    return preset.get("text_model") or preset.get("model") or OPENAI_MODEL


def prompt_task_defaults(config_key: str) -> dict[str, Any]:
    return default_ai_configs.get(config_key, default_ai_configs["image_prompt_reverse"])


def prompt_engine_config(config_key: str = "image_prompt_reverse", mask_secret: bool = False) -> dict[str, Any]:
    default = prompt_task_defaults(config_key)
    config = default | settings.get("ai_configs", {}).get(config_key, {})
    provider = config.get("provider") or default.get("provider") or "openai"
    preset = prompt_provider_presets.get(provider, prompt_provider_presets["openai"])
    kind = config.get("kind") or default.get("kind") or "text"
    api_key = clean_api_key(config.get("api_key") or env_api_key_for_provider(provider))
    result = {
        "config_key": config_key,
        "label": default.get("label", config_key),
        "description": default.get("description", ""),
        "kind": kind,
        "provider": provider,
        "provider_label": preset["label"],
        "provider_mode": preset["mode"],
        "supports_vision": bool(preset.get("supports_vision")),
        "provider_note": preset.get("note", ""),
        "api_base": (config.get("api_base") or preset["api_base"] or OPENAI_BASE_URL).rstrip("/"),
        "model": config.get("model") or default_model_for_preset(preset, kind),
        "skill": config.get("skill") or default.get("skill") or DEFAULT_PROMPT_SKILL,
    }
    if mask_secret:
        result["api_key_set"] = bool(api_key)
        result["api_key_source"] = "后台保存" if config.get("api_key") else "环境变量" if env_api_key_for_provider(provider) else "未配置"
    else:
        result["api_key"] = api_key
    result["vision_ready"] = engine_supports_vision(result)
    return result


def prompt_engine_from_values(config_key: str, provider: str, api_base: str, model: str, api_key: str, skill: str) -> dict[str, Any]:
    if provider not in prompt_provider_presets:
        provider = "openai"
    saved = prompt_engine_config(config_key)
    default = prompt_task_defaults(config_key)
    preset = prompt_provider_presets[provider]
    kind = default.get("kind") or saved.get("kind") or "text"
    result = {
        "config_key": config_key,
        "label": default.get("label", config_key),
        "description": default.get("description", ""),
        "kind": kind,
        "provider": provider,
        "provider_label": preset["label"],
        "provider_mode": preset["mode"],
        "supports_vision": bool(preset.get("supports_vision")),
        "provider_note": preset.get("note", ""),
        "api_base": (api_base.strip() or preset["api_base"] or saved["api_base"]).rstrip("/"),
        "model": model.strip() or default_model_for_preset(preset, kind) or saved["model"],
        "api_key": clean_api_key(api_key) or clean_api_key(saved.get("api_key", "")) or clean_api_key(env_api_key_for_provider(provider)),
        "skill": skill.strip() or saved.get("skill") or default.get("skill") or DEFAULT_PROMPT_SKILL,
    }
    result["vision_ready"] = engine_supports_vision(result)
    return result


def public_ai_configs() -> dict[str, Any]:
    return {key: prompt_engine_config(key, mask_secret=True) for key in default_ai_configs}


def engine_supports_vision(engine: dict[str, Any]) -> bool:
    if engine.get("kind") != "vision":
        return True
    if not engine.get("supports_vision"):
        return False
    model = (engine.get("model") or "").lower()
    text_only = ("deepseek-chat", "deepseek-reasoner", "qwen-plus", "qwen-max", "moonshot-v1", "mimo", "minimax")
    if any(marker in model for marker in text_only):
        return False
    vision_markers = ("vision", "vl", "4v", "seed-2", "gpt-4o", "gpt-4.1", "gemini", "claude")
    return any(marker in model for marker in vision_markers) or bool(engine.get("supports_vision"))


def fallback_translate_prompt(text: str, target: str) -> str:
    clean = " ".join(text.strip().split())
    if target == "en":
        return (
            "High-quality image prompt, "
            f"{clean}, clear subject, rich details, balanced composition, cinematic lighting, refined texture, high resolution"
        )
    return f"高质量图片提示词，{clean}，主体清晰，细节丰富，构图平衡，电影感光影，质感细腻，高分辨率。"


def readable_api_error(engine: dict[str, Any], exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        body = exc.response.text[:500]
        provider = engine.get("provider", "")
        model = engine.get("model", "")
        if status == 401:
            if provider in {"ark", "doubao"}:
                return (
                    "火山方舟返回 401 未授权：请确认后台填写的是“方舟 API Key”，不是 AccessKey/SecretKey、"
                    "不是模型名称，也不要包含多余空格；如果粘贴了 Bearer 前缀，系统会自动清理。"
                    f"同时确认该 Key 所属账号/项目已开通模型 {model}。原始响应：{body}"
                )
            return f"API 返回 401 未授权：请检查 API Key 是否正确、是否过期、是否有该模型权限。原始响应：{body}"
        if status == 403:
            return f"API 返回 403 无权限：通常是模型未开通、账号无权限或项目额度限制。模型：{model}。原始响应：{body}"
        if status == 404:
            if provider in {"ark", "doubao"}:
                return (
                    f"火山方舟返回 404：请检查模型名称是否正确，并确认账号/项目已开通模型 {model}。"
                    "如果响应里出现 ModelNotOpen，就需要先在火山方舟控制台开通该模型。"
                    f"原始响应：{body}"
                )
            return f"API 返回 404：请检查 API Base 或模型名称是否正确。模型：{model}。原始响应：{body}"
        if status == 429:
            return f"API 返回 429：额度或频率超限。原始响应：{body}"
        return f"API 返回 HTTP {status}：{body}"
    if isinstance(exc, httpx.HTTPError):
        return f"连接 API 失败：{exc}"
    return str(exc)


async def prompt_chat_completion(engine: dict[str, Any], messages: list[dict[str, Any]]) -> str:
    api_key = clean_api_key(engine.get("api_key", ""))
    if not api_key:
        raise RuntimeError("未配置 API Key")
    provider_mode = engine.get("provider_mode")
    if provider_mode == "gemini":
        text_parts = []
        for message in messages:
            content = message.get("content")
            if isinstance(content, str):
                text_parts.append(content)
            elif isinstance(content, list):
                for item in content:
                    if item.get("type") == "text":
                        text_parts.append(item.get("text", ""))
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                f"{engine['api_base']}/models/{engine['model']}:generateContent?key={api_key}",
                json={"contents": [{"parts": [{"text": "\n\n".join(text_parts)}]}]},
            )
            response.raise_for_status()
            data = response.json()
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    if provider_mode == "anthropic":
        system = ""
        anthropic_messages = []
        for message in messages:
            role = message.get("role", "user")
            content = message.get("content", "")
            if role == "system":
                if isinstance(content, str):
                    system = content
                continue
            parts = []
            if isinstance(content, str):
                parts.append({"type": "text", "text": content})
            elif isinstance(content, list):
                for item in content:
                    if item.get("type") == "text":
                        parts.append({"type": "text", "text": item.get("text", "")})
                    elif item.get("type") == "image_url":
                        image_url = (item.get("image_url") or {}).get("url", "")
                        if image_url.startswith("data:") and ";base64," in image_url:
                            media_type = image_url.split(";", 1)[0].removeprefix("data:")
                            data = image_url.split(";base64,", 1)[1]
                            parts.append({
                                "type": "image",
                                "source": {"type": "base64", "media_type": media_type, "data": data},
                            })
            if parts:
                anthropic_messages.append({"role": "assistant" if role == "assistant" else "user", "content": parts})
        payload = {
            "model": engine["model"],
            "max_tokens": 1600,
            "temperature": 0.35,
            "messages": anthropic_messages,
        }
        if system:
            payload["system"] = system
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                f"{engine['api_base']}/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return "\n".join(part.get("text", "") for part in data.get("content", []) if part.get("type") == "text").strip()
    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.post(
            f"{engine['api_base']}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": engine["model"], "messages": messages, "temperature": 0.35},
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()


async def ai_image_prompt(image: UploadFile, content: bytes) -> dict[str, str]:
    engine = prompt_engine_config("image_prompt_reverse")
    api_key = engine.get("api_key", "")
    if not api_key:
        return fallback_image_prompt(image.filename or "image")
    if not engine_supports_vision(engine):
        log_event("error", "图片提示词生成未调用：当前配置不是视觉模型", provider=engine["provider"], model=engine["model"])
        return fallback_image_prompt(image.filename or "image", provider="local-fallback", model=engine["model"])

    content_type = image.content_type or "image/png"
    encoded = base64.b64encode(content).decode("ascii")
    try:
        if engine.get("provider_mode") == "gemini":
            async with httpx.AsyncClient(timeout=90) as client:
                response = await client.post(
                    f"{engine['api_base']}/models/{engine['model']}:generateContent?key={api_key}",
                    json={
                        "contents": [{
                            "parts": [
                                {"text": engine["skill"]},
                                {"inline_data": {"mime_type": content_type, "data": encoded}},
                            ]
                        }]
                    },
                )
                response.raise_for_status()
                data = response.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        else:
            text = await prompt_chat_completion(engine, [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": engine["skill"]},
                        {"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{encoded}"}},
                    ],
                }
            ])
        if text.startswith("```"):
            text = text.strip("`")
            text = text.removeprefix("json").strip()
        parsed = json.loads(text)
        zh = str(parsed.get("zh", "")).strip()
        en = str(parsed.get("en", "")).strip()
        if not zh or not en:
            raise ValueError("模型返回内容不完整")
        return {"zh": zh, "en": en, "provider": engine["provider"], "model": engine["model"]}
    except Exception as exc:
        log_event("error", "图片提示词生成失败，已使用兜底结果", provider=engine["provider"], model=engine["model"], error=str(exc)[:240])
        return fallback_image_prompt(image.filename or "image", provider="local-fallback", model=engine["model"])


def best_size_for_quality(info: dict[str, Any], quality: str) -> int | None:
    formats = info.get("formats") or []
    if quality == "audio":
        audio = [f for f in formats if f.get("acodec") != "none" and f.get("vcodec") == "none"]
        chosen = max(audio, key=lambda f: f.get("abr") or 0, default={})
        return chosen.get("filesize") or chosen.get("filesize_approx")
    max_height = video_quality_options.get(quality, video_quality_options["1080p"])["height"]
    videos = [f for f in formats if f.get("vcodec") != "none" and (f.get("height") or 0) <= max_height]
    audios = [f for f in formats if f.get("acodec") != "none" and f.get("vcodec") == "none"]
    video = max(videos, key=lambda f: ((f.get("height") or 0), f.get("tbr") or 0), default={})
    audio = max(audios, key=lambda f: f.get("abr") or 0, default={})
    total = (video.get("filesize") or video.get("filesize_approx") or 0) + (audio.get("filesize") or audio.get("filesize_approx") or 0)
    return total or None


def ydl_info(url: str, download: bool = False, outtmpl: str | None = None, hook=None, quality: str = "1080p") -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "concurrent_fragment_downloads": 8,
        "socket_timeout": 30,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    }
    if YTDLP_COOKIES_FILE and Path(YTDLP_COOKIES_FILE).exists():
        opts["cookiefile"] = YTDLP_COOKIES_FILE

    if download:
        opts.update({
            "format": format_selector(quality),
            "outtmpl": outtmpl,
            "merge_output_format": "mp4",
            "progress_hooks": [hook] if hook else [],
            "postprocessors": postprocessors_for_quality(quality),
        })
    else:
        opts["skip_download"] = True

    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=download)


def video_duration_label(seconds: Any) -> str:
    try:
        total = int(seconds or 0)
    except (TypeError, ValueError):
        return ""
    if total <= 0:
        return ""
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def public_direct_video_formats(info: dict[str, Any]) -> dict[str, Any]:
    formats = info.get("formats") or []
    videos: list[dict[str, Any]] = []
    audios: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in formats:
        url = item.get("url")
        format_id = str(item.get("format_id") or "")
        if not url or not format_id or format_id in seen:
            continue
        seen.add(format_id)
        width = item.get("width")
        height = item.get("height")
        filesize = item.get("filesize") or item.get("filesize_approx")
        row = {
            "format_id": format_id,
            "url": url,
            "ext": item.get("ext") or "",
            "resolution": item.get("resolution") or (f"{width}x{height}" if width and height else ""),
            "height": height,
            "fps": item.get("fps"),
            "size": readable_size(filesize),
            "note": item.get("format_note") or "",
            "has_audio": item.get("acodec") not in {None, "none"},
            "has_video": item.get("vcodec") not in {None, "none"},
        }
        if row["has_video"]:
            if (height or 0) > 1440:
                row["download_quality"] = "4k"
            elif (height or 0) > 1080:
                row["download_quality"] = "2k"
            elif (height or 0) > 720:
                row["download_quality"] = "1080p"
            else:
                row["download_quality"] = "720p"
            videos.append(row)
        elif row["has_audio"]:
            row["abr"] = item.get("abr")
            row["download_quality"] = "audio"
            audios.append(row)

    videos.sort(key=lambda f: ((f.get("height") or 0), f.get("fps") or 0), reverse=True)
    audios.sort(key=lambda f: (f.get("abr") or 0), reverse=True)
    progressive = [item for item in videos if item["has_audio"]]
    return {
        "video": (progressive + [item for item in videos if not item["has_audio"]])[:16],
        "audio": audios[:8],
    }


def readable_video_parse_error(url: str, exc: Exception) -> str:
    message = str(exc)
    host = (urlparse(url).hostname or "").lower()
    if "Fresh cookies" in message or "cookies are needed" in message:
        if "douyin.com" in host or "iesdouyin.com" in host:
            return "抖音需要后台配置新鲜 cookies 才能解析媒体流。当前已识别链接，但服务器没有可用抖音 cookies。"
        return "该平台需要后台配置新鲜 cookies 才能解析媒体流。"
    if "Unsupported URL" in message:
        return "暂不支持这个链接，请换公开视频页面链接再试。"
    if "HTTP Error 403" in message or "Forbidden" in message:
        return "目标平台拒绝服务器访问，可能需要 cookies 或该内容不允许公开解析。"
    return f"解析失败：{message[:180]}"


def cleanup_old_files(max_age_seconds: int = RETENTION_SECONDS) -> dict[str, int]:
    cutoff = now() - max_age_seconds
    removed = 0
    for folder in (DOWNLOAD_DIR, IMAGE_DIR, TMP_DIR, COMPRESS_DIR, OFFICE_DIR, PAYMENT_DIR):
        for path in folder.glob("**/*"):
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
                removed += 1
    for task_id, task in list(tasks.items()):
        if task.get("created_at", 0) < cutoff:
            tasks.pop(task_id, None)
    return {"removed": removed}


def remove_download_task(task_id: str, file_path: Path) -> None:
    task_dir = DOWNLOAD_DIR / task_id
    if task_dir.exists():
        shutil.rmtree(task_dir, ignore_errors=True)
    elif file_path.exists():
        file_path.unlink(missing_ok=True)
    tasks.pop(task_id, None)


async def run_video_download(task_id: str, url: str) -> None:
    async with video_semaphore:
        task = tasks[task_id]
        task["status"] = "running"
        task["message"] = "正在下载和合并音视频..."
        task_dir = DOWNLOAD_DIR / task_id
        task_dir.mkdir(parents=True, exist_ok=True)

        def hook(data: dict[str, Any]) -> None:
            if data.get("status") == "downloading":
                total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
                done = data.get("downloaded_bytes") or 0
                if total > MAX_VIDEO_FILE_MB * 1024 * 1024:
                    raise RuntimeError(f"文件预计超过 {MAX_VIDEO_FILE_MB}MB，已停止下载")
                if total:
                    task["progress"] = min(95, int(done * 90 / total))
                    task["size"] = readable_size(total)
                task["speed"] = readable_size(data.get("speed"))
                task["eta"] = data.get("eta")
                task["message"] = "正在下载片段"
            elif data.get("status") == "finished":
                task["progress"] = 96
                task["message"] = "正在用 FFmpeg 合并..."

        for attempt in range(1, 3):
            task["attempt"] = attempt
            try:
                info = await asyncio.to_thread(
                    ydl_info,
                    url,
                    True,
                    str(task_dir / "%(title).120s.%(ext)s"),
                    hook,
                    task.get("quality", "1080p"),
                )
                task["title"] = info.get("title") or task.get("title") or "视频"
                files = sorted(task_dir.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
                final = next((p for p in files if p.is_file() and p.suffix.lower() in {".mp4", ".webm", ".mkv", ".mov", ".mp3", ".m4a"}), None)
                if not final:
                    raise RuntimeError("下载完成但未找到输出文件")
                if final.stat().st_size > MAX_VIDEO_FILE_MB * 1024 * 1024:
                    raise RuntimeError(f"文件超过 {MAX_VIDEO_FILE_MB}MB，已删除")

                task["file"] = str(final)
                task["size"] = readable_size(final.stat().st_size)
                task["download_url"] = f"/api/files/{task_id}"
                task["progress"] = 100
                task["status"] = "done"
                task["message"] = "处理完成"
                return
            except Exception as exc:
                if attempt < 2:
                    task["message"] = f"下载失败，正在重试：{str(exc)[:120]}"
                    shutil.rmtree(task_dir, ignore_errors=True)
                    task_dir.mkdir(parents=True, exist_ok=True)
                    await asyncio.sleep(2)
                    continue
                task["status"] = "error"
                task["message"] = str(exc)[:300]
                refund_task_credit(task_id, "视频下载失败")
                log_event("error", "视频下载失败", task_id=task_id, error=task["message"])


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> str:
    track_visit(request)
    host = public_host(request)
    if host == "www.meetseek.ai":
        return RedirectResponse(f"{MAIN_BASE_URL}/", status_code=301)
    if host in {"meetseek.ai", "localhost", "127.0.0.1"}:
        return render_plugin_marketplace_html(request)
    if host == "shop.meetseek.ai":
        return render_shop_page(request)
    if host == "prompts.meetseek.ai":
        async with prompt_gallery_lock:
            items = prompt_gallery_items(save_missing_ids=True)
        return render_prompt_index_html(items)
    return (APP_ROOT / "static" / "index.html").read_text(encoding="utf-8")


@app.head("/")
async def index_head() -> Response:
    return Response(status_code=200)


@app.get("/community", response_class=HTMLResponse)
async def community_home(request: Request) -> str:
    track_visit(request)
    host = public_host(request)
    if host == "www.meetseek.ai":
        return RedirectResponse(f"{MAIN_BASE_URL}/community", status_code=301)
    if host not in {"meetseek.ai", "localhost", "127.0.0.1"}:
        raise HTTPException(status_code=404, detail="页面不存在")
    return render_main_home_html(request)


@app.get("/plugins", response_class=HTMLResponse)
async def plugin_list_page(request: Request) -> Response:
    track_visit(request)
    host = public_host(request)
    if host == "www.meetseek.ai":
        return RedirectResponse(f"{MAIN_BASE_URL}/plugins", status_code=301)
    if host not in {"meetseek.ai", "localhost", "127.0.0.1"}:
        raise HTTPException(status_code=404, detail="页面不存在")
    return render_plugin_list_html(request)


@app.get("/plugins/submit", response_class=HTMLResponse)
async def plugin_submit_page(request: Request) -> HTMLResponse:
    track_visit(request)
    host = public_host(request)
    if host == "www.meetseek.ai":
        return RedirectResponse(f"{MAIN_BASE_URL}/plugins/submit", status_code=301)
    if host not in {"meetseek.ai", "localhost", "127.0.0.1"}:
        raise HTTPException(status_code=404, detail="页面不存在")
    lang, t = plugin_lang(request)
    return templates.TemplateResponse("plugin_submit.html", plugin_submit_context(request, lang, t))


@app.get("/plugins/{plugin_slug}", response_class=HTMLResponse)
async def plugin_detail_page(plugin_slug: str, request: Request) -> str:
    track_visit(request)
    host = public_host(request)
    if host == "www.meetseek.ai":
        return RedirectResponse(f"{MAIN_BASE_URL}/plugins/{plugin_slug}", status_code=301)
    if host not in {"meetseek.ai", "localhost", "127.0.0.1"}:
        raise HTTPException(status_code=404, detail="页面不存在")
    return render_plugin_detail_html(request, plugin_slug)


@app.get("/robots.txt")
async def robots_txt(request: Request) -> Response:
    host = public_host(request)
    base_url = public_base_for_host(host)
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin",
        "Disallow: /forgot-password",
        "Disallow: /reset-password",
        "Disallow: /api/",
        "Disallow: /api/admin/",
        "Disallow: /api/auth/",
        "Disallow: /api/payment/",
        "Disallow: /api/tasks/",
        "Disallow: /api/files/",
    ]
    if host == "prompts.meetseek.ai":
        lines.append("Allow: /api/prompts/images/")
    lines.append(f"Sitemap: {base_url}/sitemap.xml")
    return Response("\n".join(lines) + "\n", media_type="text/plain; charset=utf-8")


@app.get("/sitemap.xml")
async def sitemap_xml(request: Request) -> Response:
    host = public_host(request)
    today = datetime.now(timezone.utc).date().isoformat()
    if host == "prompts.meetseek.ai":
        async with prompt_gallery_lock:
            items = prompt_gallery_items(save_missing_ids=True)
        urls = [
            sitemap_url(f"{PROMPTS_BASE_URL}/", today, "daily", "1.0"),
            sitemap_url(f"{PROMPTS_BASE_URL}/reverse", today, "weekly", "0.8"),
        ]
        for item in items:
            if item.get("kind") == "ad" or not item.get("id"):
                continue
            image = absolute_public_url(item.get("image", ""), PROMPTS_BASE_URL) if item.get("image") else ""
            urls.append(
                sitemap_url(
                    f"{PROMPTS_BASE_URL}/prompt/{item.get('id')}",
                    today,
                    "weekly",
                    "0.7",
                    image=image,
                    image_title=item.get("title", ""),
                )
            )
    elif host == "tools.meetseek.ai":
        urls = [
            sitemap_url(f"{TOOLS_BASE_URL}/", today, "weekly", "1.0"),
            sitemap_url(f"{TOOLS_BASE_URL}/tools/video-downloader", today, "weekly", "0.9"),
            sitemap_url(f"{TOOLS_BASE_URL}/tools/green-video", today, "weekly", "0.8"),
        ]
    elif host == "shop.meetseek.ai":
        urls = [
            sitemap_url(f"{SHOP_BASE_URL}/", today, "weekly", "1.0"),
        ]
    else:
        urls = main_sitemap_urls(today)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">'
        + "".join(urls)
        + "</urlset>"
    )
    return Response(xml, media_type="application/xml; charset=utf-8")


@app.get("/prompt/{item_id}", response_class=HTMLResponse)
async def prompt_detail_page(item_id: str, request: Request):
    if public_host(request) != "prompts.meetseek.ai":
        return RedirectResponse(f"{PROMPTS_BASE_URL}/prompt/{item_id}", status_code=302)
    async with prompt_gallery_lock:
        index = prompt_gallery_index_for_id(item_id)
        item = prompt_gallery_item_at_index(index)
    if item.get("kind") == "ad":
        raise HTTPException(status_code=404, detail="提示词不存在")
    favorited = False
    user = user_from_request(request)
    if user:
        with db() as conn:
            row = conn.execute(
                "SELECT id FROM favorites WHERE user_id = ? AND prompt_id = ?",
                (user["id"], int(item.get("_index") or 0)),
            ).fetchone()
        favorited = bool(row)
    return render_prompt_detail_html(item, favorited)


@app.get("/admin", include_in_schema=False)
async def sqladmin_redirect() -> RedirectResponse:
    return RedirectResponse("/admin/", status_code=307)


@app.get("/admin-legacy", response_class=HTMLResponse)
async def admin_legacy_redirect() -> RedirectResponse:
    return RedirectResponse("/admin-tools", status_code=307)


@app.get("/admin-tools", response_class=HTMLResponse)
async def admin_tools_page(request: Request) -> Response:
    if not valid_any_admin_session(request):
        return RedirectResponse("/admin/login", status_code=302)
    response = HTMLResponse((APP_ROOT / "static" / "admin.html").read_text(encoding="utf-8"))
    if valid_sqladmin_session(request) and not valid_admin_session(request) and ADMIN_TOKEN:
        set_admin_cookie(response)
    return response


@app.get("/account", response_class=HTMLResponse)
async def account_page(request: Request) -> str:
    track_visit(request)
    return render_account_html(request)


@app.get("/shop", response_class=HTMLResponse)
async def shop_page(request: Request):
    track_visit(request)
    return render_shop_page(request)


@app.get("/products/{slug}", response_class=HTMLResponse)
async def shop_product_page(request: Request, slug: str):
    track_visit(request)
    host = public_host(request)
    if host != "shop.meetseek.ai":
        return RedirectResponse(f"{SHOP_BASE_URL}/products/{slug}", status_code=302)
    return render_shop_product_page(request, slug)


@app.get("/shop/pay/{order_id}", response_class=HTMLResponse)
async def shop_pay_page(request: Request, order_id: str):
    track_visit(request)
    host = public_host(request)
    if host != "shop.meetseek.ai":
        return RedirectResponse(f"{SHOP_BASE_URL}/shop/pay/{order_id}", status_code=302)
    return render_shop_pay_page(request, order_id)


@app.get("/api/shop/products")
async def api_shop_products() -> dict[str, Any]:
    categories = [public_shop_category(row) for row in shop_category_rows()]
    products = [public_shop_product(row) for row in shop_product_rows(public_only=True)]
    return {"categories": categories, "products": products}


@app.get("/api/shop/orders/mine")
async def api_my_shop_orders(request: Request) -> dict[str, Any]:
    user = require_user(request)
    with db() as conn:
        rows = conn.execute(
            """
            SELECT
                shop_orders.*,
                shop_products.title AS product_title,
                shop_products.slug AS product_slug
            FROM shop_orders
            JOIN shop_products ON shop_products.id = shop_orders.product_id
            WHERE shop_orders.user_id = ?
            ORDER BY shop_orders.created_at DESC
            LIMIT 50
            """,
            (user["id"],),
        ).fetchall()
    return {"orders": [public_shop_order(row) for row in rows]}


@app.post("/api/shop/orders")
async def api_create_shop_order(
    request: Request,
    product_id: int = Form(...),
    quantity: int = Form(1),
    payment_method: str = Form("manual"),
    customer_note: str = Form(""),
) -> dict[str, Any]:
    check_rate_limit(request)
    user = require_user(request)
    quantity = max(1, min(int(quantity or 1), 99))
    payment_method = payment_method.strip().lower()
    if payment_method not in {"manual", "points"}:
        raise HTTPException(status_code=400, detail="支付方式不支持")
    created_at = int(now())
    order_id = uuid.uuid4().hex
    with db() as conn:
        product = conn.execute(
            """
            SELECT
                shop_products.*,
                shop_categories.name AS category_name,
                shop_categories.slug AS category_slug
            FROM shop_products
            LEFT JOIN shop_categories ON shop_categories.id = shop_products.category_id
            WHERE shop_products.id = ? AND shop_products.status = 'published'
            """,
            (product_id,),
        ).fetchone()
        if not product:
            raise HTTPException(status_code=404, detail="商品不存在或未上架")
        stock = int(product["stock"] if product["stock"] is not None else -1)
        if stock == 0 or (stock > 0 and quantity > stock):
            raise HTTPException(status_code=400, detail="库存不足")
        amount_cents = int(product["price_cents"] or 0) * quantity
        points_amount = int(product["points_price"] or 0) * quantity
        status = "pending"
        if payment_method == "points":
            if points_amount <= 0:
                raise HTTPException(status_code=400, detail="该商品未开放积分支付")
            updated = conn.execute(
                "UPDATE users SET points = points - ? WHERE id = ? AND points >= ?",
                (points_amount, user["id"], points_amount),
            )
            if updated.rowcount != 1:
                raise HTTPException(status_code=402, detail=f"积分不足，需要 {points_amount} 分")
            status = "approved"
            if stock > 0:
                conn.execute("UPDATE shop_products SET stock = stock - ?, updated_at = ? WHERE id = ?", (quantity, created_at, product_id))
        conn.execute(
            """
            INSERT INTO shop_orders(
                id, user_id, product_id, quantity, amount_cents, points_amount,
                payment_method, status, customer_note, admin_note, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?)
            """,
            (
                order_id,
                user["id"],
                product_id,
                quantity,
                amount_cents,
                points_amount,
                payment_method,
                status,
                clean_plain_text(customer_note, 500),
                created_at,
                created_at,
            ),
        )
        row = conn.execute(
            """
            SELECT
                shop_orders.*,
                shop_products.title AS product_title,
                shop_products.slug AS product_slug
            FROM shop_orders
            JOIN shop_products ON shop_products.id = shop_orders.product_id
            WHERE shop_orders.id = ?
            """,
            (order_id,),
        ).fetchone()
    delivery_sent = False
    if status == "approved":
        try:
            delivery_sent = send_shop_delivery_email(user, product, order_id)
        except Exception as exc:
            log_event("error", "虚拟商品自动发货失败", user=user["email"], order_id=order_id, error=str(exc)[:180])
    log_event("info", "商城订单已创建", user=user["email"], order_id=order_id, product_id=product_id, method=payment_method)
    return {
        "order": public_shop_order(row),
        "delivery_sent": delivery_sent,
        "payment_url": f"{SHOP_BASE_URL}/shop/pay/{order_id}",
    }


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> str:
    if user_from_request(request):
        return RedirectResponse("/", status_code=302)
    return (APP_ROOT / "static" / "login.html").read_text(encoding="utf-8")


@app.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request) -> str:
    if user_from_request(request):
        return RedirectResponse("/account", status_code=302)
    return (APP_ROOT / "static" / "forgot-password.html").read_text(encoding="utf-8")


@app.head("/forgot-password")
async def forgot_password_head() -> Response:
    return Response(status_code=200)


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request) -> str:
    if user_from_request(request):
        return RedirectResponse("/", status_code=302)
    return (APP_ROOT / "static" / "register.html").read_text(encoding="utf-8")


@app.get("/user/profile", response_class=HTMLResponse)
async def user_profile_page(request: Request):
    user = user_from_request(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    return render_user_profile_html(request, user)


@app.get("/prompts", response_class=HTMLResponse)
async def prompts_page(request: Request):
    host = public_host(request)
    if host != "prompts.meetseek.ai":
        return RedirectResponse("https://prompts.meetseek.ai/", status_code=302)
    async with prompt_gallery_lock:
        items = prompt_gallery_items(save_missing_ids=True)
    return render_prompt_index_html(items)


@app.get("/reverse", response_class=HTMLResponse)
async def reverse_page(request: Request):
    host = public_host(request)
    if host != "prompts.meetseek.ai":
        return RedirectResponse("https://prompts.meetseek.ai/reverse", status_code=302)
    return (APP_ROOT / "static" / "reverse.html").read_text(encoding="utf-8")


@app.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request) -> str:
    track_visit(request)
    return (APP_ROOT / "static" / "reset-password.html").read_text(encoding="utf-8")


@app.head("/reset-password")
async def reset_password_head() -> Response:
    return Response(status_code=200)


SEARCH_TYPE_LABELS = {
    "article": "长文",
    "short": "短文",
    "link": "链接",
    "tool": "工具",
    "post": "内容",
}


@app.get("/api/search")
async def api_search(q: str = "") -> list[dict[str, Any]]:
    query = re.sub(r"\s+", " ", str(q or "").strip())[:80]
    if not query:
        return []
    like = f"%{query}%"
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id, type, title, summary, content_html, category_slug, slug, canonical_url,
                   published_at, created_at, pinned_at, recommended_at
            FROM posts
            WHERE status = 'published'
              AND visibility = 'public'
              AND (
                title LIKE ? COLLATE NOCASE
                OR summary LIKE ? COLLATE NOCASE
                OR content_html LIKE ? COLLATE NOCASE
              )
            ORDER BY pinned_at DESC, recommended_at DESC, published_at DESC, created_at DESC
            LIMIT 12
            """,
            (like, like, like),
        ).fetchall()
    results: list[dict[str, Any]] = []
    for row in rows:
        post_type = str(row["type"] or "post")
        title = str(row["title"] or "").strip()
        if not title:
            title = post_excerpt(row["content_html"] or row["summary"] or "", 40) or "未命名内容"
        snippet = post_plain_text(row["summary"] or row["content_html"] or "")
        results.append(
            {
                "id": int(row["id"]),
                "title": title,
                "type": post_type,
                "type_label": SEARCH_TYPE_LABELS.get(post_type, "内容"),
                "url": row["canonical_url"] or f"/{row['category_slug']}/{row['slug']}",
                "snippet": snippet[:140],
            }
        )
    return results


@app.get("/{category_slug}", response_class=HTMLResponse)
async def community_category_page(category_slug: str, request: Request):
    host = public_host(request)
    if host == "www.meetseek.ai":
        return RedirectResponse(f"{MAIN_BASE_URL}/{category_slug}", status_code=301)
    if host != "meetseek.ai":
        raise HTTPException(status_code=404, detail="页面不存在")
    current_user = user_from_request(request)
    current_user_is_admin = is_site_admin(request, current_user)
    current_user_id = int(current_user["id"]) if current_user else 0
    with db() as conn:
        category = conn.execute("SELECT * FROM categories WHERE slug = ?", (category_slug,)).fetchone()
        if not category:
            raise HTTPException(status_code=404, detail="分类不存在")
        if current_user_id:
            rows = conn.execute(
                """
                SELECT posts.*, users.name AS author_name, users.avatar_url AS author_avatar_url
                FROM posts
                JOIN users ON users.id = posts.author_id
                WHERE posts.category_slug = ?
                  AND posts.status = 'published'
                  AND posts.visibility = 'public'
                  AND NOT EXISTS (
                    SELECT 1
                    FROM user_post_preferences
                    WHERE user_post_preferences.user_id = ?
                      AND user_post_preferences.post_id = posts.id
                      AND user_post_preferences.kind IN ('hidden', 'not_interested')
                  )
                  AND NOT EXISTS (
                    SELECT 1
                    FROM user_blocks
                    WHERE user_blocks.user_id = ?
                      AND user_blocks.author_id = posts.author_id
                  )
                ORDER BY posts.pinned_at DESC, posts.published_at DESC, posts.updated_at DESC
                LIMIT 30
                """,
                (category_slug, current_user_id, current_user_id),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT posts.*, users.name AS author_name, users.avatar_url AS author_avatar_url
                FROM posts
                JOIN users ON users.id = posts.author_id
                WHERE posts.category_slug = ? AND posts.status = 'published' AND posts.visibility = 'public'
                ORDER BY posts.pinned_at DESC, posts.published_at DESC, posts.updated_at DESC
                LIMIT 30
                """,
                (category_slug,),
            ).fetchall()
        following_author_ids = {
            int(row["author_id"])
            for row in conn.execute(
                "SELECT author_id FROM user_follows WHERE follower_id = ?",
                (current_user_id,),
            ).fetchall()
        } if current_user else set()
    items_parts = []
    for row in rows:
        post = public_post(row)
        item = home_feed_item_from_post(
            post,
            author_name=str(row["author_name"] or "meetseek"),
            author_avatar_url=str(row["author_avatar_url"] if "author_avatar_url" in row.keys() else ""),
            current_user=current_user,
            is_admin=current_user_is_admin,
            is_following=int(row["author_id"]) in following_author_ids,
        )
        items_parts.append(render_home_feed_card(item, current_user=current_user, is_admin=current_user_is_admin))
    items = "".join(items_parts)
    category_interactions_script = """
    <script>
      (function () {
        function showToast(text) {
          let toast = document.getElementById("category-toast");
          if (!toast) {
            toast = document.createElement("div");
            toast.id = "category-toast";
            toast.className = "fixed bottom-6 left-1/2 z-[80] -translate-x-1/2 rounded-full bg-slate-950 px-5 py-3 text-sm font-black text-white shadow-lg transition";
            document.body.appendChild(toast);
          }
          toast.textContent = text;
          toast.style.opacity = "1";
          clearTimeout(window.__categoryToastTimer);
          window.__categoryToastTimer = setTimeout(() => { toast.style.opacity = "0"; }, 1800);
        }
        function closeMoreMenus(exceptMenu) {
          document.querySelectorAll(".more-menu").forEach((menu) => {
            if (menu !== exceptMenu) menu.classList.add("hidden");
          });
        }
        function setReactionState(button, active, count) {
          const label = button.querySelector("[data-count-label]");
          button.dataset.active = active ? "true" : "false";
          button.dataset.count = String(Math.max(0, count));
          button.classList.toggle("text-emerald-600", button.classList.contains("btn-like") && active);
          button.classList.toggle("text-orange-500", button.classList.contains("btn-bookmark") && active);
          if (label) label.textContent = String(Math.max(0, count));
        }
        async function toggleReaction(button, endpoint) {
          const postId = Number(button.dataset.postId || 0);
          if (!postId) return;
          if (button.dataset.busy === "true") return;
          button.dataset.busy = "true";
          const wasActive = button.dataset.active === "true";
          const previousCount = Number(button.dataset.count || 0);
          const optimisticCount = Math.max(0, previousCount + (wasActive ? -1 : 1));
          setReactionState(button, !wasActive, optimisticCount);
          try {
            const response = await fetch(endpoint.replace(":id", String(postId)), { method: "POST" });
            if (response.status === 401) {
              window.location.href = "/account";
              return;
            }
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.detail || "操作失败");
            setReactionState(button, Boolean(payload.active), Number(payload.count || 0));
          } catch (error) {
            setReactionState(button, wasActive, previousCount);
          } finally {
            button.dataset.busy = "false";
          }
        }
        async function runPostMenuAction(button) {
          const action = button.dataset.menuAction;
          const article = button.closest("article");
          if (action === "copy") {
            const url = new URL(button.dataset.url || window.location.href, window.location.origin).toString();
            await navigator.clipboard.writeText(url);
            showToast("已复制");
            return;
          }
          if (action === "follow") {
            const authorId = Number(button.dataset.authorId || 0);
            const wasFollowing = button.dataset.following === "true";
            button.dataset.following = wasFollowing ? "false" : "true";
            button.textContent = wasFollowing ? "关注" : "取消关注";
            const response = await fetch(`/api/users/${authorId}/toggle_follow`, { method: "POST" });
            if (response.status === 401) { window.location.href = "/account"; return; }
            const payload = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(payload.detail || "操作失败");
            button.dataset.following = payload.following ? "true" : "false";
            button.textContent = payload.following ? "取消关注" : "关注";
            showToast(payload.message || "已更新");
            return;
          }
          if (action === "bookmark") {
            const postId = Number(button.dataset.postId || 0);
            const response = await fetch(`/api/posts/${postId}/toggle_bookmark`, { method: "POST" });
            if (response.status === 401) { window.location.href = "/account"; return; }
            const payload = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(payload.detail || "操作失败");
            showToast(payload.active ? "已收藏" : "已取消收藏");
            return;
          }
          const postId = Number(button.dataset.postId || 0);
          if (!postId) return;
          if (["hide", "delete", "private", "not_interested", "block_author", "violation", "ban_author"].includes(action) && article) {
            article.style.transition = "opacity .18s ease, transform .18s ease";
            article.style.opacity = "0";
            article.style.transform = "translateY(6px)";
            setTimeout(() => article.remove(), 180);
          }
          const response = await fetch(`/api/posts/${postId}/action`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action })
          });
          if (response.status === 401) { window.location.href = "/account"; return; }
          const payload = await response.json().catch(() => ({}));
          if (!response.ok) throw new Error(payload.detail || "操作失败");
          showToast(payload.message || "已更新");
        }
        document.addEventListener("click", async (event) => {
          const toggle = event.target.closest(".more-menu-toggle");
          if (toggle) {
            event.preventDefault();
            const menu = toggle.parentElement?.querySelector(".more-menu");
            if (!menu) return;
            const willOpen = menu.classList.contains("hidden");
            closeMoreMenus(menu);
            menu.classList.toggle("hidden", !willOpen);
            return;
          }
          const menuAction = event.target.closest(".more-menu-action");
          if (menuAction) {
            event.preventDefault();
            closeMoreMenus();
            try {
              await runPostMenuAction(menuAction);
            } catch (error) {
              showToast(error.message || "操作失败");
            }
            return;
          }
          if (!event.target.closest(".more-menu")) closeMoreMenus();
          const likeButton = event.target.closest(".btn-like");
          if (likeButton) {
            event.preventDefault();
            await toggleReaction(likeButton, "/api/posts/:id/toggle_like");
            return;
          }
          const bookmarkButton = event.target.closest(".btn-bookmark");
          if (bookmarkButton) {
            event.preventDefault();
            await toggleReaction(bookmarkButton, "/api/posts/:id/toggle_bookmark");
            return;
          }
          const shareButton = event.target.closest(".btn-share");
          if (shareButton) {
            event.preventDefault();
            const label = shareButton.querySelector("span:last-child");
            const oldText = label?.textContent || "分享";
            const url = new URL(shareButton.dataset.url || window.location.href, window.location.origin).toString();
            await navigator.clipboard.writeText(url);
            if (label) label.textContent = "✅ 已复制";
            setTimeout(() => { if (label) label.textContent = oldText; }, 2000);
          }
        });
      })();
    </script>
    """
    title = category["seo_title"] or f'{category["name"]} - meetseek'
    description = category["seo_description"] or category["description"] or f'meetseek {category["name"]} 分类内容聚合。'
    return templates.TemplateResponse(
        "category.html",
        {
            "request": request,
            "site_name": "meetseek",
            "main_base_url": MAIN_BASE_URL,
            "tools_base_url": TOOLS_BASE_URL,
            "prompts_base_url": PROMPTS_BASE_URL,
            "current_user": current_user,
            "meta": {
                "title": title,
                "description": description,
                "canonical_url": f"{MAIN_BASE_URL}/{category_slug}",
                "image_url": "",
                "type": "website",
            },
            "category": dict(category),
            "category_description": category["description"] or description,
            "items_html": items,
            "interactions_script": category_interactions_script,
        },
    )


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/settings")
async def public_settings() -> dict[str, Any]:
    ads = {
        key: {
            "label": value.get("label"),
            "enabled": value.get("enabled"),
            "layout": value.get("layout", "banner"),
            "items": [item for item in value.get("items", []) if item.get("html")],
            "html": value.get("html", ""),
        }
        for key, value in ads_from_db(public_only=True).items()
    }
    return {"ads": ads, "features": feature_flags, "video": public_video_config()}


def clean_contact_field(value: str, limit: int) -> str:
    clean = bleach.clean(str(value or ""), tags=[], attributes={}, strip=True)
    clean = re.sub(r"[ \t\r\f\v]+", " ", clean).strip()
    clean = re.sub(r"\n{3,}", "\n\n", clean)
    return clean[:limit]


def request_ip_address(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return (forwarded or (request.client.host if request.client else ""))[:80]


@app.post("/api/contact-submissions")
async def create_contact_submission(payload: ContactSubmissionPayload, request: Request) -> dict[str, Any]:
    inquiry_type = clean_contact_field(payload.inquiry_type, 32).lower()
    if inquiry_type not in {"contact", "advertise"}:
        inquiry_type = "contact"
    name = clean_contact_field(payload.name, 120)
    company = clean_contact_field(payload.company, 160)
    contact = clean_contact_field(payload.contact, 180)
    budget = clean_contact_field(payload.budget, 120)
    placement = clean_contact_field(payload.placement, 160)
    message = clean_contact_field(payload.message, 3000)
    if not contact:
        raise HTTPException(status_code=400, detail="请填写联系方式")
    if not message:
        raise HTTPException(status_code=400, detail="请填写需求内容")
    timestamp = int(now())
    with db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO contact_submissions(
                inquiry_type, name, company, contact, budget, placement, message,
                status, source_path, ip_address, user_agent, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'new', ?, ?, ?, ?, ?)
            """,
            (
                inquiry_type,
                name,
                company,
                contact,
                budget,
                placement,
                message,
                str(request.headers.get("referer", ""))[:500],
                request_ip_address(request),
                str(request.headers.get("user-agent", ""))[:500],
                timestamp,
                timestamp,
            ),
        )
        submission_id = int(cursor.lastrowid)
    return {"ok": True, "id": submission_id, "message": "已提交，我们会尽快处理。"}


@app.get("/api/visitor-stats")
async def public_visitor_stats() -> dict[str, Any]:
    summary = visitor_summary()
    return {
        "today": summary["today"],
        "month": summary["month"],
        "total": summary["total"],
    }


def normalized_client_ip(request: Request) -> str:
    candidates = [
        request.headers.get("cf-connecting-ip", ""),
        request.headers.get("x-real-ip", ""),
        request.headers.get("x-forwarded-for", "").split(",", 1)[0],
        request.client.host if request.client else "",
    ]
    for candidate in candidates:
        value = str(candidate or "").strip()
        if value:
            return value
    return "unknown"


async def ip_geo_lookup(ip: str) -> dict[str, Any]:
    try:
        parsed = ipaddress.ip_address(ip)
        if parsed.is_private or parsed.is_loopback or parsed.is_link_local or parsed.is_reserved:
            return {}
    except ValueError:
        return {}
    endpoints = [
        f"https://ipapi.co/{quote(ip)}/json/",
        f"https://ipwho.is/{quote(ip)}",
    ]
    async with httpx.AsyncClient(timeout=3.0, follow_redirects=True) as client:
        for endpoint in endpoints:
            try:
                response = await client.get(endpoint, headers={"user-agent": "Mozilla/5.0 MeetSeek-IP-Tool"})
                if response.status_code >= 400:
                    continue
                data = response.json()
                if "error" in data and data.get("error"):
                    continue
                return {
                    "country": data.get("country_name") or data.get("country") or "",
                    "country_code": data.get("country_code") or data.get("country_code_iso3") or "",
                    "region": data.get("region") or data.get("region_name") or "",
                    "city": data.get("city") or "",
                    "asn": data.get("asn") or (data.get("connection") or {}).get("asn") or "",
                    "org": data.get("org") or (data.get("connection") or {}).get("org") or data.get("isp") or "",
                    "timezone": data.get("timezone") or "",
                }
            except Exception:
                continue
    return {}


async def public_trace_ip(endpoint: str) -> str:
    async with httpx.AsyncClient(timeout=4.0, follow_redirects=True) as client:
        response = await client.get(endpoint, headers={"user-agent": "Mozilla/5.0 MeetSeek-IP-Tool Chrome/120 Safari/537.36"})
        response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "json" in content_type:
        data = response.json()
        return str(data.get("ip") or data.get("query") or "").strip()
    for line in response.text.splitlines():
        if line.startswith("ip="):
            return line.split("=", 1)[1].strip()
    return ""


async def ip_security_lookup(ip: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=4.0, follow_redirects=True) as client:
            response = await client.get(
                f"https://ipwho.is/{quote(ip)}",
                headers={"user-agent": "Mozilla/5.0 MeetSeek-IP-Tool Chrome/120 Safari/537.36"},
            )
        if response.status_code >= 400:
            return {}
        data = response.json()
        security = data.get("security") if isinstance(data.get("security"), dict) else {}
        return {
            "vpn": bool(security.get("vpn")),
            "proxy": bool(security.get("proxy")),
            "tor": bool(security.get("tor")),
            "crawler": bool(security.get("crawler")),
            "hosting": bool(security.get("hosting")),
        }
    except Exception:
        return {}


DEFAULT_IP_INTEL_DB: dict[str, Any] = {
    "version": 1,
    "ip_overrides": {
        "38.244.38.21": {"label": "家宽 IP", "tone": "emerald", "detail": "本地情报确认的住宅/家宽出口"}
    },
    "cidr_rules": [
        {"cidr": "114.92.0.0/16", "label": "家宽 IP", "tone": "emerald", "detail": "上海电信宽带出口"},
        {"cidr": "38.0.0.0/8", "label": "机房 IP", "tone": "amber", "detail": "Cogent/IDC 常见出口段"},
        {"cidr": "45.192.0.0/16", "label": "机房 IP", "tone": "amber", "detail": "云服务器/IDC 常见出口段"},
    ],
    "asn_rules": {
        "13335": {"label": "广播 IP", "tone": "slate", "detail": "Cloudflare Anycast/CDN"},
        "20940": {"label": "广播 IP", "tone": "slate", "detail": "Akamai Anycast/CDN"},
        "54113": {"label": "广播 IP", "tone": "slate", "detail": "Fastly Anycast/CDN"},
        "174": {"label": "机房 IP", "tone": "amber", "detail": "Cogent 机房/企业骨干出口"},
        "401701": {"label": "机房 IP", "tone": "amber", "detail": "Vapeline 云服务器/IDC 出口"},
        "4812": {"label": "家宽 IP", "tone": "emerald", "detail": "中国电信上海宽带出口"},
    },
    "org_rules": [
        {"contains": "cloudflare", "label": "广播 IP", "tone": "slate", "detail": "Cloudflare Anycast/CDN"},
        {"contains": "akamai", "label": "广播 IP", "tone": "slate", "detail": "Akamai Anycast/CDN"},
        {"contains": "fastly", "label": "广播 IP", "tone": "slate", "detail": "Fastly Anycast/CDN"},
        {"contains": "cogent", "label": "机房 IP", "tone": "amber", "detail": "Cogent 机房/企业骨干出口"},
        {"contains": "vapeline", "label": "机房 IP", "tone": "amber", "detail": "Vapeline 云服务器/IDC 出口"},
        {"contains": "chinanet", "label": "家宽 IP", "tone": "emerald", "detail": "中国电信宽带出口"},
        {"contains": "china telecom", "label": "家宽 IP", "tone": "emerald", "detail": "中国电信宽带出口"},
    ],
}


def load_ip_intel_db() -> dict[str, Any]:
    data = json.loads(json.dumps(DEFAULT_IP_INTEL_DB, ensure_ascii=False))
    try:
        if IP_INTEL_FILE.exists():
            custom = json.loads(IP_INTEL_FILE.read_text(encoding="utf-8"))
            if isinstance(custom.get("ip_overrides"), dict):
                data["ip_overrides"].update(custom["ip_overrides"])
            if isinstance(custom.get("asn_rules"), dict):
                data["asn_rules"].update(custom["asn_rules"])
            if isinstance(custom.get("cidr_rules"), list):
                data["cidr_rules"].extend(custom["cidr_rules"])
            if isinstance(custom.get("org_rules"), list):
                data["org_rules"].extend(custom["org_rules"])
        else:
            IP_INTEL_FILE.parent.mkdir(parents=True, exist_ok=True)
            IP_INTEL_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return data


def normalize_asn(value: Any) -> str:
    return re.sub(r"^as", "", str(value or "").strip().lower())


def ip_intel_rule_match(ip: str, geo: dict[str, Any]) -> dict[str, str] | None:
    db = load_ip_intel_db()
    if ip and isinstance(db.get("ip_overrides"), dict):
        override = db["ip_overrides"].get(ip)
        if isinstance(override, dict):
            return {
                "label": str(override.get("label") or "公网 IP"),
                "tone": str(override.get("tone") or "slate"),
                "detail": str(override.get("detail") or "本地 IP 情报库覆盖"),
                "source": "local_override",
            }
    if ip:
        try:
            address = ipaddress.ip_address(ip)
            for rule in db.get("cidr_rules", []):
                try:
                    if address in ipaddress.ip_network(str(rule.get("cidr")), strict=False):
                        return {
                            "label": str(rule.get("label") or "公网 IP"),
                            "tone": str(rule.get("tone") or "slate"),
                            "detail": str(rule.get("detail") or "本地 CIDR 规则命中"),
                            "source": "local_cidr",
                        }
                except Exception:
                    continue
        except ValueError:
            pass
    asn = normalize_asn(geo.get("asn"))
    rule = (db.get("asn_rules") or {}).get(asn)
    if isinstance(rule, dict):
        return {
            "label": str(rule.get("label") or "公网 IP"),
            "tone": str(rule.get("tone") or "slate"),
            "detail": str(rule.get("detail") or "本地 ASN 规则命中"),
            "source": "local_asn",
        }
    org = str(geo.get("org") or "").lower()
    for rule in db.get("org_rules", []):
        needle = str(rule.get("contains") or "").lower()
        if needle and needle in org:
            return {
                "label": str(rule.get("label") or "公网 IP"),
                "tone": str(rule.get("tone") or "slate"),
                "detail": str(rule.get("detail") or "本地机构规则命中"),
                "source": "local_org",
            }
    return None


def infer_ip_property(geo: dict[str, Any], security: dict[str, Any], ip: str = "") -> dict[str, str]:
    local_rule = ip_intel_rule_match(ip, geo)
    if local_rule:
        return local_rule
    org = str(geo.get("org") or "").lower()
    asn = str(geo.get("asn") or "").lower()
    country = str(geo.get("country") or "").lower()
    text = f"{org} {asn}"
    broadcast_keywords = ("cloudflare", "akamai", "fastly", "anycast", "cdn77", "gcore", "edgio")
    hosting_keywords = (
        "amazon", "aws", "google", "cogent", "digitalocean", "vultr", "linode",
        "akamai", "microsoft", "azure", "ovh", "hetzner", "oracle", "leaseweb", "datacamp",
        "alibaba", "tencent", "huawei", "zenlayer", "colo", "hosting", "server", "data center",
        "datacenter", "data centre", "cloud", "communications", "llc", "inc", "limited",
        "global", "network services", "internet services", "rack", "colo", "vps", "vapeline",
    )
    residential_keywords = (
        "telecom", "chinanet", "china telecom", "mobile", "china mobile", "unicom", "comcast",
        "verizon", "charter", "vodafone", "orange", "bt", "softbank", "kddi", "ntt",
        "sk broadband", "residential", "broadband", "cable", "dsl", "ftth", "fiber",
        "fibre", "home", "consumer", "telefonica", "telekom", "telstra", "docomo",
    )
    mobile_keywords = ("mobile", "cellular", "wireless", "lte", "5g", "4g", "cell")
    education_keywords = ("university", "college", "school", "education", "research", "academy")
    government_keywords = ("government", "gov", "military", "public sector")
    if security.get("vpn") or security.get("proxy") or security.get("tor"):
        return {"label": "代理 IP", "tone": "amber", "detail": "检测到代理、VPN 或 Tor 特征"}
    if any(keyword in text for keyword in broadcast_keywords):
        return {"label": "广播 IP", "tone": "slate", "detail": "更像 CDN/Anycast 广播出口"}
    if security.get("hosting"):
        return {"label": "机房 IP", "tone": "amber", "detail": "安全画像标记为 hosting 出口"}
    if any(keyword in text for keyword in education_keywords):
        return {"label": "机构 IP", "tone": "emerald", "detail": "更像学校、科研或机构网络"}
    if any(keyword in text for keyword in government_keywords):
        return {"label": "机构 IP", "tone": "emerald", "detail": "更像政府或公共机构网络"}
    if any(keyword in text for keyword in mobile_keywords) and country in {"china", "united states", "japan", "korea", "south korea", "hong kong"}:
        return {"label": "移动 IP", "tone": "emerald", "detail": "更像移动网络出口"}
    if any(keyword in text for keyword in hosting_keywords):
        return {"label": "机房 IP", "tone": "amber", "detail": "更像云服务器或数据中心出口"}
    if any(keyword in text for keyword in residential_keywords):
        return {"label": "家宽 IP", "tone": "emerald", "detail": "更像运营商住宅或原生出口"}
    if org:
        return {"label": "公网 IP", "tone": "slate", "detail": "已识别运营商，但无法精确确认住宅或机房"}
    return {"label": "公网 IP", "tone": "slate", "detail": "已确认公网地址，归属库暂缺运营商细分"}


def claude_trust_score(meta: dict[str, Any], geo: dict[str, Any], security: dict[str, Any], claude_ok: bool, ip: str = "") -> dict[str, Any]:
    score = 82
    reasons: list[str] = []
    if not meta.get("public"):
        score -= 45
        reasons.append("不是公网 IP")
    if security.get("vpn"):
        score -= 25
        reasons.append("VPN 风险")
    if security.get("proxy"):
        score -= 20
        reasons.append("代理风险")
    if security.get("tor"):
        score -= 35
        reasons.append("Tor 风险")
    if security.get("crawler"):
        score -= 12
        reasons.append("爬虫特征")
    ip_property = infer_ip_property(geo, security, ip)
    if ip_property["tone"] == "amber":
        score -= 12
        reasons.append(ip_property["label"])
    if claude_ok:
        score += 8
    else:
        score -= 18
        reasons.append("Claude 连通异常")
    score = max(0, min(100, score))
    if score >= 80:
        label = "纯净"
    elif score >= 60:
        label = "可用"
    elif score >= 40:
        label = "偏风险"
    else:
        label = "高风险"
    return {"score": score, "label": label, "reasons": reasons or ["该 IP 信誉优异"], "property": ip_property}


IP_PROBE_TARGETS = {
    "cloudflare": {"name": "Cloudflare", "url": "https://www.cloudflare.com/cdn-cgi/trace", "category": "网络"},
    "google": {"name": "Google", "url": "https://www.google.com/generate_204", "category": "搜索"},
    "bing": {"name": "Bing", "url": "https://www.bing.com/", "category": "搜索"},
    "github": {"name": "GitHub", "url": "https://github.com/", "category": "开发"},
    "stackoverflow": {"name": "Stack Overflow", "url": "https://stackoverflow.com/", "category": "开发"},
    "openai": {"name": "OpenAI", "url": "https://api.openai.com/v1/models", "category": "AI"},
    "anthropic": {"name": "Claude", "url": "https://api.anthropic.com/", "category": "AI"},
    "youtube": {"name": "YouTube", "url": "https://www.youtube.com/generate_204", "category": "视频"},
    "netflix": {"name": "Netflix", "url": "https://www.netflix.com/", "category": "视频"},
    "telegram": {"name": "Telegram", "url": "https://telegram.org/", "category": "社交"},
    "x": {"name": "X / Twitter", "url": "https://x.com/", "category": "社交"},
    "bilibili": {"name": "Bilibili", "url": "https://www.bilibili.com/", "category": "国内"},
    "weibo": {"name": "微博", "url": "https://weibo.com/", "category": "国内"},
    "baidu": {"name": "百度", "url": "https://www.baidu.com/", "category": "国内"},
    "qq": {"name": "QQ", "url": "https://www.qq.com/", "category": "国内"},
}


def ip_public_meta(ip: str) -> dict[str, Any]:
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        return {"version": "", "public": False, "scope": "invalid"}
    if parsed.is_loopback:
        scope = "loopback"
    elif parsed.is_link_local:
        scope = "link-local"
    elif parsed.is_reserved:
        scope = "reserved"
    elif parsed.is_multicast:
        scope = "multicast"
    elif parsed.is_private:
        scope = "private"
    else:
        scope = "public"
    return {"version": f"IPv{parsed.version}", "public": scope == "public", "scope": scope}


def resolve_host_addresses(hostname: str) -> list[dict[str, Any]]:
    addresses: dict[str, dict[str, Any]] = {}
    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            records = socket.getaddrinfo(hostname, None, family, socket.SOCK_STREAM)
        except socket.gaierror:
            continue
        for family_value, _, _, _, sockaddr in records:
            ip = sockaddr[0]
            if ip not in addresses:
                meta = ip_public_meta(ip)
                addresses[ip] = {"ip": ip, "version": meta["version"], "scope": meta["scope"], "public": meta["public"]}
    return list(addresses.values())[:12]


def normalize_lookup_target(value: str) -> tuple[str, str]:
    raw = str(value or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="请输入 IP 或域名")
    if len(raw) > 253:
        raise HTTPException(status_code=400, detail="查询内容过长")
    parsed = urlparse(raw if "://" in raw else f"//{raw}")
    host = (parsed.hostname or raw).strip().strip(".").lower()
    if not host or not re.match(r"^[a-z0-9.-]+$|^[0-9a-f:.]+$", host):
        raise HTTPException(status_code=400, detail="只支持查询 IP 或域名")
    try:
        ipaddress.ip_address(host)
        return "ip", host
    except ValueError:
        if "." not in host:
            raise HTTPException(status_code=400, detail="域名格式不正确")
        return "domain", host


PROXY_PROTOCOL_PROFILES: tuple[dict[str, Any], ...] = (
    {
        "key": "hysteria2",
        "name": "Hysteria 2",
        "transport": "UDP / QUIC",
        "tcp_ports": (),
        "udp_ports": (443, 8443, 2053, 2083, 4433),
        "note": "Hysteria 2 基于加密 UDP/QUIC，公开探测只能判断常见 UDP 端口是否有响应。",
    },
    {
        "key": "vless_reality_vision",
        "name": "VLESS + REALITY + VISION",
        "transport": "TCP / TLS-like",
        "tcp_ports": (443, 8443, 2053, 2083, 2087, 2096, 4433),
        "udp_ports": (),
        "note": "REALITY 会伪装成正常 TLS，没有私钥和 serverName 时无法直接确认，只能做端口暴露判断。",
    },
    {
        "key": "tuic",
        "name": "TUIC",
        "transport": "UDP / QUIC",
        "tcp_ports": (),
        "udp_ports": (443, 8443, 10443, 4433),
        "note": "TUIC 基于 QUIC，通常不会返回可识别 banner，结果为低置信度特征判断。",
    },
    {
        "key": "wireguard",
        "name": "WireGuard",
        "transport": "UDP",
        "tcp_ports": (),
        "udp_ports": (51820, 2408, 13231),
        "note": "WireGuard 对无效握手通常保持静默；未响应不代表一定没有运行。",
    },
    {
        "key": "openvpn",
        "name": "OpenVPN",
        "transport": "TCP / UDP",
        "tcp_ports": (1194, 443, 943),
        "udp_ports": (1194,),
        "note": "OpenVPN 常见端口可做暴露判断，但 443 与普通 HTTPS 可能重叠，需要人工复核。",
    },
    {
        "key": "shadowsocks",
        "name": "Shadowsocks",
        "transport": "TCP / UDP",
        "tcp_ports": (8388, 8389),
        "udp_ports": (8388, 8389),
        "note": "Shadowsocks 没有固定 banner，且端口可任意配置；仅检测少量常见默认端口。",
    },
)


async def tcp_port_open(ip: str, port: int, timeout: float = 0.8) -> bool:
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=timeout)
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), timeout=0.2)
        except Exception:
            pass
        return True
    except Exception:
        return False


async def udp_port_responds(ip: str, port: int, timeout: float = 0.8) -> bool:
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        return False
    family = socket.AF_INET6 if parsed.version == 6 else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_DGRAM)
    sock.setblocking(False)
    try:
        loop = asyncio.get_running_loop()
        address = (ip, port, 0, 0) if parsed.version == 6 else (ip, port)
        await loop.sock_sendto(sock, b"\x00", address)
        await asyncio.wait_for(loop.sock_recv(sock, 64), timeout=timeout)
        return True
    except Exception:
        return False
    finally:
        sock.close()


async def detect_proxy_protocols(ip: str) -> list[dict[str, Any]]:
    async def inspect_profile(profile: dict[str, Any]) -> dict[str, Any]:
        tcp_ports = tuple(int(port) for port in profile.get("tcp_ports", ()))
        udp_ports = tuple(int(port) for port in profile.get("udp_ports", ()))
        tcp_results = await asyncio.gather(*(tcp_port_open(ip, port) for port in tcp_ports)) if tcp_ports else []
        udp_results = await asyncio.gather(*(udp_port_responds(ip, port) for port in udp_ports)) if udp_ports else []
        open_tcp = [port for port, is_open in zip(tcp_ports, tcp_results) if is_open]
        responsive_udp = [port for port, responds in zip(udp_ports, udp_results) if responds]
        evidence: list[str] = []
        if open_tcp:
            evidence.append("TCP " + ", ".join(str(port) for port in open_tcp))
        if responsive_udp:
            evidence.append("UDP " + ", ".join(str(port) for port in responsive_udp))

        if profile["key"] in {"hysteria2", "tuic", "wireguard"}:
            if responsive_udp:
                status = "possible"
                confidence = "低"
                summary = "检测到常见 UDP 端口响应"
            else:
                status = "unknown"
                confidence = "低"
                summary = "未获得 UDP 响应，无法确认"
        elif profile["key"] == "vless_reality_vision":
            if open_tcp:
                status = "possible"
                confidence = "低"
                summary = "检测到常见 TLS 伪装端口开放"
            else:
                status = "not_detected"
                confidence = "低"
                summary = "未检测到常见端口开放"
        else:
            if open_tcp or responsive_udp:
                status = "possible"
                confidence = "中" if profile["key"] == "openvpn" and (1194 in open_tcp or 1194 in responsive_udp) else "低"
                summary = "检测到常见端口开放或响应"
            else:
                status = "not_detected"
                confidence = "低"
                summary = "未检测到常见端口开放"

        return {
            "key": profile["key"],
            "name": profile["name"],
            "transport": profile["transport"],
            "status": status,
            "confidence": confidence,
            "summary": summary,
            "evidence": evidence,
            "tested_tcp_ports": list(tcp_ports),
            "tested_udp_ports": list(udp_ports),
            "note": profile["note"],
        }

    return list(await asyncio.gather(*(inspect_profile(profile) for profile in PROXY_PROTOCOL_PROFILES)))


@app.get("/api/ip/me")
async def public_ip_me(request: Request) -> dict[str, Any]:
    ip = normalized_client_ip(request)
    geo, security = await asyncio.gather(ip_geo_lookup(ip), ip_security_lookup(ip))
    meta = ip_public_meta(ip)
    return {
        "ip": ip,
        "version": meta["version"],
        "scope": meta["scope"],
        "is_public": meta["public"],
        "geo": geo,
        "security": security,
        "property": infer_ip_property(geo, security, ip),
        "headers": {
            "user_agent": request.headers.get("user-agent", ""),
            "accept_language": request.headers.get("accept-language", ""),
            "cf_ray": request.headers.get("cf-ray", ""),
            "protocol": request.headers.get("x-forwarded-proto") or request.url.scheme,
        },
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/ip/protocols")
async def public_ip_protocols(request: Request, target: str = "") -> dict[str, Any]:
    if target.strip():
        kind, normalized = normalize_lookup_target(target)
        addresses = [{"ip": normalized, **ip_public_meta(normalized)}] if kind == "ip" else resolve_host_addresses(normalized)
        public_addresses = [item for item in addresses if item.get("public")]
        if not public_addresses:
            raise HTTPException(status_code=400, detail="只能检测公网 IP，不能检测内网、保留地址或未解析域名")
        ip = public_addresses[0]["ip"]
    else:
        ip = normalized_client_ip(request)

    meta = ip_public_meta(ip)
    if not meta.get("public"):
        raise HTTPException(status_code=400, detail="只能检测公网 IP")
    protocols = await detect_proxy_protocols(ip)
    possible_count = sum(1 for item in protocols if item["status"] == "possible")
    return {
        "ip": ip,
        "version": meta["version"],
        "scope": meta["scope"],
        "possible_count": possible_count,
        "protocols": protocols,
        "disclaimer": "这些协议大多会加密、伪装或对无效探测保持静默；本检测只做固定常见端口和握手响应的暴露面判断，不能替代真实节点配置验证。",
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/ip/probes")
async def public_ip_probes(targets: str = "") -> dict[str, Any]:
    requested = [item.strip().lower() for item in targets.split(",") if item.strip()]
    if not requested:
        requested = list(IP_PROBE_TARGETS.keys())
    requested = [key for key in requested if key in IP_PROBE_TARGETS][:12]
    if not requested:
        raise HTTPException(status_code=400, detail="没有可检测的目标")

    async def probe(key: str) -> dict[str, Any]:
        target = IP_PROBE_TARGETS[key]
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
                response = await client.get(
                    target["url"],
                    headers={"user-agent": "Mozilla/5.0 MeetSeek-IP-Tool Chrome/120 Safari/537.36"},
                )
            latency_ms = int((time.perf_counter() - started) * 1000)
            ok = response.status_code < 500
            return {
                "key": key,
                "name": target["name"],
                "category": target["category"],
                "status": "ok" if ok else "error",
                "status_code": response.status_code,
                "latency_ms": latency_ms,
            }
        except Exception as exc:
            return {
                "key": key,
                "name": target["name"],
                "category": target["category"],
                "status": "error",
                "status_code": 0,
                "latency_ms": None,
                "error": str(exc)[:120],
            }

    results = await asyncio.gather(*(probe(key) for key in requested))
    grouped: dict[str, dict[str, Any]] = {}
    for item in results:
        category = item["category"]
        bucket = grouped.setdefault(category, {"category": category, "total": 0, "ok": 0, "avg_latency_ms": None})
        bucket["total"] += 1
        if item["status"] == "ok":
            bucket["ok"] += 1
    for bucket in grouped.values():
        latencies = [item["latency_ms"] for item in results if item["category"] == bucket["category"] and item.get("latency_ms") is not None]
        bucket["avg_latency_ms"] = int(sum(latencies) / len(latencies)) if latencies else None
    return {"results": results, "summary": list(grouped.values()), "checked_at": datetime.now(timezone.utc).isoformat()}


@app.get("/api/ip/claude-risk")
async def public_ip_claude_risk(request: Request) -> dict[str, Any]:
    current_ip = normalized_client_ip(request)
    current_meta = ip_public_meta(current_ip)
    current_geo, current_security = await asyncio.gather(ip_geo_lookup(current_ip), ip_security_lookup(current_ip))

    async def trace_with_geo(label: str, endpoint: str) -> dict[str, Any]:
        try:
            ip = await public_trace_ip(endpoint)
            geo = await ip_geo_lookup(ip) if ip else {}
            security = await ip_security_lookup(ip) if ip else {}
            prop = infer_ip_property(geo, security, ip) if ip else {}
            return {"label": label, "ip": ip, "meta": ip_public_meta(ip) if ip else {}, "geo": geo, "security": security, "property": prop}
        except Exception as exc:
            return {"label": label, "ip": "", "meta": {}, "geo": {}, "security": {}, "property": {}, "error": str(exc)[:160]}

    async def claude_availability() -> dict[str, Any]:
        started = time.perf_counter()
        checks = []
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
            for name, url in (("claude.ai", "https://claude.ai/"), ("anthropic.com", "https://www.anthropic.com/")):
                try:
                    response = await client.get(url, headers={"user-agent": "Mozilla/5.0 MeetSeek-IP-Tool Chrome/120 Safari/537.36"})
                    checks.append({"name": name, "ok": response.status_code < 500, "status_code": response.status_code, "latency_ms": int((time.perf_counter() - started) * 1000)})
                except Exception as exc:
                    checks.append({"name": name, "ok": False, "status_code": 0, "latency_ms": None, "error": str(exc)[:120]})
        return {"ok": all(item["ok"] for item in checks), "checks": checks}

    cloudflare_exit, generic_exit, availability = await asyncio.gather(
        trace_with_geo("Cloudflare 出口 IP", "https://www.cloudflare.com/cdn-cgi/trace"),
        trace_with_geo("Claude AI 看到的 IP", "https://claude.ai/cdn-cgi/trace"),
        claude_availability(),
    )
    trust_source = generic_exit if generic_exit.get("ip") else {"meta": current_meta, "geo": current_geo, "security": current_security}
    trust = claude_trust_score(
        trust_source.get("meta") or {},
        trust_source.get("geo") or {},
        trust_source.get("security") or {},
        bool(availability.get("ok")),
        str(trust_source.get("ip") or ""),
    )
    return {
        "current": {
            "label": "当前出口 IPv4",
            "ip": current_ip,
            "meta": current_meta,
            "geo": current_geo,
            "security": current_security,
            "property": infer_ip_property(current_geo, current_security, current_ip),
        },
        "cloudflare_exit": cloudflare_exit,
        "claude_exit": generic_exit,
        "trust": trust,
        "availability": availability,
        "dns": {
            "status": "server_side",
            "message": "浏览器无法直接暴露本机 DNS 出口；此处结合 IP 归属与连接可用性做风险参考。",
        },
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/ip/lookup")
async def public_ip_lookup(target: str) -> dict[str, Any]:
    kind, normalized = normalize_lookup_target(target)
    addresses = [{"ip": normalized, **ip_public_meta(normalized)}] if kind == "ip" else resolve_host_addresses(normalized)
    if kind == "domain" and not addresses:
        raise HTTPException(status_code=404, detail="没有解析到 IP 地址")
    geo_items = []
    for item in addresses[:4]:
        geo, security = await asyncio.gather(ip_geo_lookup(item["ip"]), ip_security_lookup(item["ip"]))
        geo_items.append({
            "ip": item["ip"],
            "geo": geo,
            "security": security,
            "property": infer_ip_property(geo, security, item["ip"]),
        })
    return {
        "target": normalized,
        "kind": kind,
        "addresses": addresses,
        "geo": geo_items,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/prompts/gallery")
async def public_prompt_gallery(request: Request) -> dict[str, Any]:
    search = str(request.query_params.get("search") or "")
    category = str(request.query_params.get("category") or "")
    model_engine = str(request.query_params.get("model_engine") or "")
    async with prompt_gallery_lock:
        prompts = prompt_gallery_items(
            save_missing_ids=True,
            search=search,
            category=category,
            model_engine=model_engine,
        )
    user = user_from_request(request)
    favorite_ids: set[int] = set()
    if user:
        with db() as conn:
            rows = conn.execute("SELECT prompt_id FROM favorites WHERE user_id = ?", (user["id"],)).fetchall()
        favorite_ids = {int(row["prompt_id"]) for row in rows}
    for item in prompts:
        prompt_id = int(item.get("_index") or 0)
        item["prompt_id"] = prompt_id
        item["favorited"] = prompt_id in favorite_ids
    return {"prompts": prompts, "models": prompt_image_models, "default_count": 0}


@app.get("/api/prompts/images/{filename}")
async def prompt_gallery_image(filename: str):
    safe = Path(filename).name
    path = PROMPT_IMAGE_DIR / safe
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="图片不存在")
    return FileResponse(path)


@app.get("/api/shop/images/{filename}")
async def shop_image(filename: str):
    safe = Path(filename).name
    path = SHOP_IMAGE_DIR / safe
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="图片不存在")
    return FileResponse(path, media_type="image/webp", headers={"cache-control": "public, max-age=31536000, immutable"})


@app.get("/api/plugins/images/{filename}")
async def plugin_image(filename: str):
    safe = Path(filename).name
    path = PLUGIN_IMAGE_DIR / safe
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="图片不存在")
    media_type = "image/svg+xml" if safe.endswith(".svg") else "image/webp"
    return FileResponse(path, media_type=media_type, headers={"cache-control": "public, max-age=31536000, immutable"})


@app.post("/api/plugins/submit")
async def submit_plugin(
    request: Request,
    title: str = Form(""),
    category: str = Form(""),
    category_other: str = Form(""),
    short_description: str = Form(""),
    long_description: str = Form(""),
    version: str = Form(""),
    chrome_store_url: str = Form(""),
    edge_store_url: str = Form(""),
    direct_url: str = Form(""),
    support_url: str = Form(""),
    tags: str = Form(""),
    developer_name: str = Form(""),
    developer_email: str = Form(""),
    accent: str = Form(""),
    icon: UploadFile | None = File(default=None),
    cover_image: UploadFile | None = File(default=None),
    gallery_images: list[UploadFile] | None = File(default=None),
) -> dict[str, Any]:
    user = require_user(request)
    clean_title = title.strip()[:120]
    if len(clean_title) < 2:
        raise HTTPException(status_code=400, detail="请填写插件名称")
    clean_short = short_description.strip()[:160]
    if len(clean_short) < 6:
        raise HTTPException(status_code=400, detail="请填写一句话推荐")
    clean_long = long_description.strip()[:8000]
    if len(clean_long) < 20:
        raise HTTPException(status_code=400, detail="请填写详细功能说明")
    clean_category = (category_other.strip() or category.strip() or "AI & ChatGPT")[:80]
    clean_version = (version.strip() or "1.0.0")[:40]
    clean_chrome = clean_plugin_url(chrome_store_url, "Chrome 商店链接")
    clean_edge = clean_plugin_url(edge_store_url, "Edge 商店链接")
    clean_direct = clean_plugin_url(direct_url, "直接访问网址")
    clean_support = clean_plugin_url(support_url, "支持链接")
    install_url = clean_chrome or clean_edge or clean_direct
    if not install_url:
        raise HTTPException(status_code=400, detail="请至少填写一个安装源或访问网址")
    clean_developer_name = (developer_name.strip() or str(user.get("name") or ""))[:80]
    clean_developer_email = developer_email.strip()[:160]
    if clean_developer_email and not EMAIL_RE.match(clean_developer_email):
        raise HTTPException(status_code=400, detail="开发者邮箱格式不正确")
    allowed_accents = {
        "from-violet-500 to-blue-500",
        "from-emerald-500 to-teal-500",
        "from-orange-500 to-amber-400",
        "from-sky-500 to-cyan-400",
        "from-fuchsia-500 to-rose-500",
        "from-slate-800 to-slate-950",
    }
    clean_accent = accent.strip() if accent.strip() in allowed_accents else "from-violet-500 to-blue-500"
    icon_url = await save_plugin_icon(icon)
    cover_url = await save_plugin_image(cover_image, "plugin-cover", max_side=1800)
    gallery_urls: list[str] = []
    for image in (gallery_images or [])[:8]:
        if image and image.filename:
            gallery_urls.append(await save_plugin_image(image, "plugin-gallery", max_side=2200))
    timestamp = int(now())
    with db() as conn:
        slug = unique_plugin_slug(conn, clean_title)
        conn.execute(
            """
            INSERT INTO plugins(
                slug, title, description, short_description, long_description, category,
                rating, users, icon, accent, version, install_url, chrome_store_url,
                edge_store_url, direct_url, icon_url, tags, developer_name, developer_email,
                submitter_id, review_note, website_url, support_url, cover_image, gallery_images,
                status, is_featured, is_trending, is_new, sort_order, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                slug,
                clean_title,
                clean_short,
                clean_short,
                clean_long,
                clean_category,
                "0.0",
                "",
                clean_title[:1].upper(),
                clean_accent,
                clean_version,
                install_url,
                clean_chrome,
                clean_edge,
                clean_direct,
                icon_url,
                tags.strip()[:500],
                clean_developer_name,
                clean_developer_email,
                int(user["id"]),
                "",
                clean_direct or install_url,
                clean_support,
                cover_url,
                json.dumps(gallery_urls, ensure_ascii=False),
                "pending",
                0,
                0,
                0,
                0,
                timestamp,
                timestamp,
            ),
        )
    return {"status": "success", "message": "插件已提交，等待平台审核", "slug": slug}


@app.get("/api/avatars/{filename}")
async def avatar_image(filename: str):
    safe = Path(filename).name
    path = AVATAR_DIR / safe
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="头像不存在")
    return FileResponse(path, media_type="image/webp", headers={"cache-control": "public, max-age=31536000, immutable"})


@app.get("/api/post-media/{filename}")
async def post_media_file(filename: str):
    safe = Path(filename).name
    path = POST_MEDIA_DIR / safe
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="媒体不存在")
    media_type = "video/mp4" if safe.endswith((".mp4", ".m4v")) else "video/quicktime" if safe.endswith(".mov") else "video/webm" if safe.endswith(".webm") else "image/gif" if safe.endswith(".gif") else "image/webp"
    return FileResponse(path, media_type=media_type, headers={"cache-control": "public, max-age=31536000, immutable"})


@app.post("/api/prompts/gallery")
async def create_prompt_gallery_item(
    request: Request,
    kind: str = Form("prompt"),
    title: str = Form(""),
    category: str = Form(""),
    tags: str = Form(""),
    zh: str = Form(""),
    en: str = Form(""),
    description: str = Form(""),
    url: str = Form(""),
    cta: str = Form(""),
    sort_order: str = Form("0"),
    models: str = Form(""),
    client_nonce: str = Form(""),
    image: UploadFile | None = File(default=None),
) -> dict[str, Any]:
    user = require_prompt_admin(request)
    kind = "ad" if kind.strip().lower() == "ad" else "prompt"
    if kind == "prompt" and not zh.strip() and not en.strip():
        raise HTTPException(status_code=400, detail="请至少填写中文或英文 Prompt")
    if kind == "ad" and not title.strip() and not description.strip():
        raise HTTPException(status_code=400, detail="请填写广告标题或广告说明")
    nonce = clean_prompt_client_nonce(client_nonce)
    item_key = new_custom_prompt_item_id()
    now_text = datetime.now(timezone.utc).isoformat()
    image_url = ""
    if image and image.filename:
        image_url = await save_prompt_gallery_image(image, "prompt-custom")
    updated = clean_prompt_gallery_item({
        "id": item_key,
        "kind": kind,
        "title": title.strip()[:120] or "未命名提示词",
        "category": category.strip()[:40] or ("广告" if kind == "ad" else "未分类"),
        "tags": parse_prompt_tag_text(tags),
        "zh": zh.strip()[:5000],
        "en": en.strip()[:5000],
        "description": description.strip()[:1000],
        "url": clean_prompt_ad_url(url) if kind == "ad" else "",
        "cta": cta.strip()[:24] or "查看详情",
        "sort_order": clean_prompt_sort_order(sort_order),
        "created_at": now_text,
        "models": clean_prompt_models(models),
        "client_nonce": nonce,
        "image": image_url,
    })
    async with prompt_gallery_lock:
        if nonce:
            with db() as conn:
                existing = conn.execute(
                    "SELECT * FROM prompts WHERE client_nonce = ? AND hidden = 0",
                    (nonce,),
                ).fetchone()
            if existing:
                item = prompt_db_row_to_item(existing)
                log_event("info", "提示词图库重复发布已拦截", user=user["email"], index=item["_index"], title=item["title"], kind=item["kind"])
                return {"prompt": item, "index": item["_index"], "deduped": True}
        with db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO prompts(
                    item_key, kind, title, cover_image, model_engine, prompt_text, negative_prompt,
                    author_id, category, tags, models, gradient, zh, en, description, url, cta,
                    sort_order, hidden, is_featured, client_nonce, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?)
                """,
                (
                    item_key,
                    updated["kind"],
                    updated["title"],
                    updated.get("image", ""),
                    ", ".join(updated["models"]),
                    updated["zh"],
                    "",
                    user["id"],
                    updated["category"],
                    json.dumps(updated["tags"], ensure_ascii=False),
                    json.dumps(updated["models"], ensure_ascii=False),
                    updated["gradient"],
                    updated["zh"],
                    updated["en"],
                    updated["description"],
                    updated["url"],
                    updated["cta"],
                    updated["sort_order"],
                    updated["client_nonce"],
                    now_text,
                    now_text,
                ),
            )
            index = int(cursor.lastrowid)
            row = conn.execute("SELECT * FROM prompts WHERE id = ?", (index,)).fetchone()
        item = prompt_db_row_to_item(row)
        log_event("info", "提示词图库已新增", user=user["email"], index=index, title=item["title"], kind=kind)
        return {"prompt": item, "index": index}


@app.post("/api/prompts/gallery/{index}")
async def update_prompt_gallery_item(
    request: Request,
    index: int,
    kind: str = Form("prompt"),
    title: str = Form(...),
    category: str = Form(""),
    tags: str = Form(""),
    zh: str = Form(...),
    en: str = Form(...),
    description: str = Form(""),
    url: str = Form(""),
    cta: str = Form(""),
    sort_order: str = Form("0"),
    models: str = Form(""),
    image: UploadFile | None = File(default=None),
) -> dict[str, Any]:
    user = require_prompt_admin(request)
    if index < 0:
        raise HTTPException(status_code=404, detail="提示词不存在")
    kind = "ad" if kind.strip().lower() == "ad" else "prompt"
    if kind == "prompt" and not zh.strip() and not en.strip():
        raise HTTPException(status_code=400, detail="请至少填写中文或英文 Prompt")
    if kind == "ad" and not title.strip() and not description.strip():
        raise HTTPException(status_code=400, detail="请填写广告标题或广告说明")
    updated = {
        "kind": kind,
        "title": title.strip()[:120] or "未命名提示词",
        "category": category.strip()[:40] or ("广告" if kind == "ad" else "未分类"),
        "tags": parse_prompt_tag_text(tags),
        "zh": zh.strip()[:5000],
        "en": en.strip()[:5000],
        "description": description.strip()[:1000],
        "url": clean_prompt_ad_url(url) if kind == "ad" else "",
        "cta": cta.strip()[:24] or "查看详情",
        "sort_order": clean_prompt_sort_order(sort_order),
        "models": clean_prompt_models(models),
    }
    if image and image.filename:
        updated["image"] = await save_prompt_gallery_image(image, f"prompt-{index}")
    async with prompt_gallery_lock:
        with db() as conn:
            current = conn.execute("SELECT * FROM prompts WHERE id = ? AND hidden = 0", (index,)).fetchone()
            if not current:
                raise HTTPException(status_code=404, detail="提示词不存在")
            fallback = prompt_db_row_to_item(current)
            if "image" not in updated:
                updated["image"] = fallback.get("image", "")
            cleaned = clean_prompt_gallery_item(updated, fallback)
            now_text = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """
                UPDATE prompts
                SET kind = ?, title = ?, cover_image = ?, model_engine = ?, prompt_text = ?,
                    negative_prompt = ?, category = ?, tags = ?, models = ?, gradient = ?,
                    zh = ?, en = ?, description = ?, url = ?, cta = ?, sort_order = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    cleaned["kind"],
                    cleaned["title"],
                    cleaned.get("image", ""),
                    ", ".join(cleaned["models"]),
                    cleaned["zh"],
                    str(updated.get("negative_prompt") or current["negative_prompt"] or ""),
                    cleaned["category"],
                    json.dumps(cleaned["tags"], ensure_ascii=False),
                    json.dumps(cleaned["models"], ensure_ascii=False),
                    cleaned["gradient"],
                    cleaned["zh"],
                    cleaned["en"],
                    cleaned["description"],
                    cleaned["url"],
                    cleaned["cta"],
                    cleaned["sort_order"],
                    now_text,
                    index,
                ),
            )
            row = conn.execute("SELECT * FROM prompts WHERE id = ?", (index,)).fetchone()
        item = prompt_db_row_to_item(row)
    log_event("info", "提示词图库已更新", user=user["email"], index=index, title=item["title"])
    return {"prompt": item}


@app.post("/api/prompts/gallery/id/{item_id}")
async def update_prompt_gallery_item_by_id(
    request: Request,
    item_id: str,
    kind: str = Form("prompt"),
    title: str = Form(...),
    category: str = Form(""),
    tags: str = Form(""),
    zh: str = Form(...),
    en: str = Form(...),
    description: str = Form(""),
    url: str = Form(""),
    cta: str = Form(""),
    sort_order: str = Form("0"),
    models: str = Form(""),
    image: UploadFile | None = File(default=None),
) -> dict[str, Any]:
    async with prompt_gallery_lock:
        index = prompt_gallery_index_for_id(item_id)
    return await update_prompt_gallery_item(
        request=request,
        index=index,
        kind=kind,
        title=title,
        category=category,
        tags=tags,
        zh=zh,
        en=en,
        description=description,
        url=url,
        cta=cta,
        sort_order=sort_order,
        models=models,
        image=image,
    )


@app.delete("/api/prompts/gallery/{index}")
async def delete_prompt_gallery_item(request: Request, index: int) -> dict[str, Any]:
    user = require_prompt_admin(request)
    if index < 0:
        raise HTTPException(status_code=404, detail="提示词不存在")
    async with prompt_gallery_lock:
        with db() as conn:
            current = conn.execute("SELECT * FROM prompts WHERE id = ?", (index,)).fetchone()
            if not current:
                raise HTTPException(status_code=404, detail="提示词不存在")
            title = str(current["title"] or "未命名提示词")
            if int(current["hidden"] or 0):
                return {"status": "ok", "index": index, "action": "删除", "title": title, "deduped": True}
            delete_prompt_gallery_image_ref(current["cover_image"])
            conn.execute(
                "UPDATE prompts SET hidden = 1, updated_at = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), index),
            )
            action = "删除"
    log_event("info", f"提示词图库已{action}", user=user["email"], index=index, title=title)
    return {"status": "ok", "index": index, "action": action, "title": title}


@app.delete("/api/prompts/gallery/id/{item_id}")
async def delete_prompt_gallery_item_by_id(request: Request, item_id: str) -> dict[str, Any]:
    async with prompt_gallery_lock:
        index = prompt_gallery_index_for_id(item_id)
    return await delete_prompt_gallery_item(request, index)


@app.post("/api/prompts/{prompt_id}/favorite")
async def favorite_prompt(prompt_id: int, current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    with db() as conn:
        prompt = conn.execute("SELECT id FROM prompts WHERE id = ? AND hidden = 0", (prompt_id,)).fetchone()
        if not prompt:
            raise HTTPException(status_code=404, detail="提示词不存在")
        existing = conn.execute(
            "SELECT id FROM favorites WHERE user_id = ? AND prompt_id = ?",
            (current_user["id"], prompt_id),
        ).fetchone()
        if existing:
            conn.execute("DELETE FROM favorites WHERE id = ?", (existing["id"],))
            return {"favorited": False}
        conn.execute(
            "INSERT INTO favorites(user_id, prompt_id, created_at) VALUES (?, ?, ?)",
            (current_user["id"], prompt_id, int(now())),
        )
    return {"favorited": True}


@app.get("/api/payment/config")
async def payment_config() -> dict[str, Any]:
    return {"payment": public_payment_config(), "reward": public_reward_config(), "checkin": public_checkin_config()}


@app.get("/api/payment/proofs/{filename}")
async def payment_proof(filename: str):
    safe = Path(filename).name
    path = PAYMENT_DIR / safe
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="凭证不存在")
    return FileResponse(path)


def public_credit_order(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "email": row["email"] if "email" in row.keys() else "",
        "name": row["name"] if "name" in row.keys() else "",
        "package_id": row["package_id"],
        "package_name": row["package_name"],
        "points": row["points"],
        "amount": row["amount"],
        "method": row["method"],
        "transaction_no": row["transaction_no"],
        "screenshot": f"/api/payment/proofs/{row['screenshot']}" if row["screenshot"] else "",
        "status": row["status"],
        "stripe_session_id": row["stripe_session_id"] if "stripe_session_id" in row.keys() else "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def public_member_credit_order(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "package_id": row["package_id"],
        "package_name": row["package_name"],
        "points": row["points"],
        "amount": row["amount"],
        "method": row["method"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def money_yuan(cents: int | float | str | None) -> str:
    value = int(cents or 0)
    amount = Decimal(value) / Decimal(100)
    return str(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def public_shop_category(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "id": int(row["id"]),
        "name": row["name"],
        "slug": row["slug"],
        "description": row["description"],
        "enabled": bool(row["enabled"]),
        "sort_order": int(row["sort_order"]),
    }


def public_shop_product(row: sqlite3.Row) -> dict[str, Any]:
    category = {
        "id": row["category_id"] if "category_id" in row.keys() else None,
        "name": row["category_name"] if "category_name" in row.keys() else "",
        "slug": row["category_slug"] if "category_slug" in row.keys() else "",
    }
    price_cents = int(row["price_cents"] or 0)
    points_price = int(row["points_price"] or 0)
    stock = int(row["stock"] if row["stock"] is not None else -1)
    gallery_images = [
        item.strip()
        for item in re.split(r"[\n,]+", str(row["gallery_images"] if "gallery_images" in row.keys() else ""))
        if item.strip()
    ][:12]
    cover_image = str(row["cover_image"] or "").strip() or (gallery_images[0] if gallery_images else "")
    return {
        "id": int(row["id"]),
        "category": category,
        "title": row["title"],
        "slug": row["slug"],
        "subtitle": row["subtitle"],
        "description": row["description"],
        "cover_image": cover_image,
        "gallery_images": gallery_images,
        "product_type": row["product_type"],
        "price_cents": price_cents,
        "price_yuan": money_yuan(price_cents),
        "points_price": points_price,
        "stock": stock,
        "stock_label": "不限量" if stock < 0 else str(stock),
        "status": row["status"],
        "fulfillment_note": row["fulfillment_note"],
        "auto_delivery": bool(row["auto_delivery"]) if "auto_delivery" in row.keys() else False,
        "sort_order": int(row["sort_order"]),
        "created_at": int(row["created_at"]),
        "updated_at": int(row["updated_at"]),
    }


def public_shop_order(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": int(row["user_id"]),
        "product_id": int(row["product_id"]),
        "product_title": row["product_title"] if "product_title" in row.keys() else "",
        "product_slug": row["product_slug"] if "product_slug" in row.keys() else "",
        "quantity": int(row["quantity"]),
        "amount_cents": int(row["amount_cents"]),
        "amount_yuan": money_yuan(row["amount_cents"]),
        "points_amount": int(row["points_amount"]),
        "payment_method": row["payment_method"],
        "status": row["status"],
        "customer_note": row["customer_note"],
        "admin_note": row["admin_note"] if "admin_note" in row.keys() else "",
        "created_at": int(row["created_at"]),
        "updated_at": int(row["updated_at"]),
    }


def shop_product_rows(public_only: bool = True) -> list[sqlite3.Row]:
    where = "WHERE shop_products.status = 'published'" if public_only else ""
    with db() as conn:
        return conn.execute(
            f"""
            SELECT
                shop_products.*,
                shop_categories.name AS category_name,
                shop_categories.slug AS category_slug
            FROM shop_products
            LEFT JOIN shop_categories ON shop_categories.id = shop_products.category_id
            {where}
            ORDER BY shop_products.sort_order DESC, shop_products.id DESC
            """
        ).fetchall()


def shop_category_rows() -> list[sqlite3.Row]:
    with db() as conn:
        return conn.execute(
            """
            SELECT * FROM shop_categories
            WHERE enabled = 1
            ORDER BY sort_order DESC, id ASC
            """
        ).fetchall()


@app.post("/api/payment/orders")
async def create_payment_order(
    request: Request,
    package_id: str = Form(...),
    method: str = Form(...),
    transaction_no: str = Form(""),
    screenshot: UploadFile | None = File(default=None),
) -> dict[str, Any]:
    check_rate_limit(request)
    user = require_user(request)
    config = public_payment_config()
    if not config.get("manual_enabled", True):
        raise HTTPException(status_code=403, detail="人工充值暂未开放")
    if method not in {"wechat", "alipay"}:
        raise HTTPException(status_code=400, detail="请选择微信或支付宝")
    package = package_by_id(package_id)
    proof_file = save_optional_image(screenshot, PAYMENT_DIR, "proof")
    if not transaction_no.strip() and not proof_file:
        raise HTTPException(status_code=400, detail="请填写付款单号或上传付款截图")
    order_id = uuid.uuid4().hex
    created_at = int(now())
    with db() as conn:
        conn.execute(
            """
            INSERT INTO credit_orders(id, user_id, package_id, package_name, points, amount, method, transaction_no, screenshot, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (
                order_id,
                user["id"],
                str(package.get("id")),
                str(package.get("name")),
                int(package.get("points", 0)),
                float(package.get("amount", 0)),
                method,
                transaction_no.strip()[:120],
                proof_file,
                created_at,
                created_at,
            ),
        )
        row = conn.execute("SELECT credit_orders.*, users.email, users.name FROM credit_orders JOIN users ON users.id = credit_orders.user_id WHERE credit_orders.id = ?", (order_id,)).fetchone()
    log_event("info", "积分充值订单已提交", user=user["email"], order_id=order_id, points=package.get("points"))
    return {"order": public_credit_order(row)}


@app.post("/api/payment/stripe/checkout")
async def create_stripe_checkout_session(request: Request, package_id: str = Form(...)) -> dict[str, Any]:
    check_rate_limit(request)
    user = require_user(request)
    config = raw_payment_config()
    secret_key = str(config.get("stripe_secret_key") or "").strip()
    if not bool(config.get("stripe_enabled", False)) or not secret_key:
        raise HTTPException(status_code=403, detail="Stripe 支付暂未开启")
    package = package_by_id(package_id)
    order_id = uuid.uuid4().hex
    created_at = int(now())
    currency = str(config.get("stripe_currency") or "usd").strip().lower()
    success_url = str(config.get("stripe_success_url") or "").strip() or stripe_default_success_url()
    cancel_url = str(config.get("stripe_cancel_url") or "").strip() or stripe_default_cancel_url()
    amount_minor = stripe_amount_minor(float(package.get("amount", 0)), currency)
    form_data = {
        "mode": "payment",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": order_id,
        "metadata[order_id]": order_id,
        "metadata[user_id]": str(user["id"]),
        "metadata[package_id]": str(package.get("id")),
        "metadata[points]": str(int(package.get("points", 0))),
        "line_items[0][quantity]": "1",
        "line_items[0][price_data][currency]": currency,
        "line_items[0][price_data][unit_amount]": str(amount_minor),
        "line_items[0][price_data][product_data][name]": str(package.get("name")),
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://api.stripe.com/v1/checkout/sessions",
                data=form_data,
                headers={
                    "Authorization": f"Bearer {secret_key}",
                    "Stripe-Version": "2026-02-25.clover",
                },
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Stripe 暂时不可用：{exc}")
    data = response.json()
    if response.status_code >= 400:
        message = data.get("error", {}).get("message") if isinstance(data, dict) else response.text[:180]
        raise HTTPException(status_code=502, detail=f"Stripe 创建收银台失败：{message}")
    with db() as conn:
        conn.execute(
            """
            INSERT INTO credit_orders(id, user_id, package_id, package_name, points, amount, method, transaction_no, screenshot, status, stripe_session_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'stripe', '', '', 'pending', ?, ?, ?)
            """,
            (
                order_id,
                user["id"],
                str(package.get("id")),
                str(package.get("name")),
                int(package.get("points", 0)),
                float(package.get("amount", 0)),
                str(data.get("id") or ""),
                created_at,
                created_at,
            ),
        )
        row = conn.execute("SELECT credit_orders.*, users.email, users.name FROM credit_orders JOIN users ON users.id = credit_orders.user_id WHERE credit_orders.id = ?", (order_id,)).fetchone()
    log_event("info", "Stripe Checkout 已创建", user=user["email"], order_id=order_id, session=data.get("id"))
    return {"url": data.get("url"), "session_id": data.get("id"), "order": public_credit_order(row)}


@app.post("/api/payment/stripe/webhook")
async def stripe_webhook(request: Request, stripe_signature: str | None = Header(default=None, alias="Stripe-Signature")) -> dict[str, Any]:
    config = raw_payment_config()
    webhook_secret = str(config.get("stripe_webhook_secret") or "").strip()
    if not webhook_secret:
        raise HTTPException(status_code=400, detail="Stripe Webhook Secret 未配置")
    payload = await request.body()
    verify_stripe_signature(payload, stripe_signature or "", webhook_secret)
    try:
        event = json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Stripe 事件 JSON 无效")
    event_id = str(event.get("id") or "")
    event_type = str(event.get("type") or "")
    if not event_id:
        raise HTTPException(status_code=400, detail="Stripe 事件缺少 id")
    with db() as conn:
        if conn.execute("SELECT id FROM stripe_events WHERE id = ?", (event_id,)).fetchone():
            return {"received": True, "deduped": True}
        conn.execute("INSERT INTO stripe_events(id, type, created_at) VALUES (?, ?, ?)", (event_id, event_type, int(now())))
    if event_type != "checkout.session.completed":
        return {"received": True, "ignored": event_type}
    session = event.get("data", {}).get("object", {}) if isinstance(event.get("data"), dict) else {}
    if session.get("payment_status") != "paid":
        return {"received": True, "ignored": "unpaid"}
    metadata = session.get("metadata") or {}
    order_id = str(metadata.get("order_id") or session.get("client_reference_id") or "")
    session_id = str(session.get("id") or "")
    payment_intent = str(session.get("payment_intent") or "")
    if not order_id:
        raise HTTPException(status_code=400, detail="Stripe Session 缺少订单号")
    with db() as conn:
        row = conn.execute(
            "SELECT credit_orders.*, users.email, users.name FROM credit_orders JOIN users ON users.id = credit_orders.user_id WHERE credit_orders.id = ?",
            (order_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="本地订单不存在")
        if row["status"] == "approved":
            return {"received": True, "already_approved": True}
        if row["method"] != "stripe":
            raise HTTPException(status_code=400, detail="订单类型不是 Stripe")
        conn.execute("UPDATE users SET points = points + ? WHERE id = ?", (row["points"], row["user_id"]))
        conn.execute(
            "UPDATE credit_orders SET status = 'approved', transaction_no = ?, stripe_session_id = ?, stripe_payment_intent_id = ?, updated_at = ? WHERE id = ?",
            (payment_intent or session_id, session_id, payment_intent, int(now()), order_id),
        )
        updated = conn.execute(
            "SELECT credit_orders.*, users.email, users.name FROM credit_orders JOIN users ON users.id = credit_orders.user_id WHERE credit_orders.id = ?",
            (order_id,),
        ).fetchone()
    log_event("info", "Stripe 支付成功并自动加分", order_id=order_id, user=updated["email"], points=updated["points"])
    return {"received": True, "order": public_credit_order(updated)}


@app.post("/api/payment/xunhu/checkout")
async def create_xunhu_checkout(request: Request, package_id: str = Form(...)) -> dict[str, Any]:
    check_rate_limit(request)
    user = require_user(request)
    config = raw_payment_config()
    appid = str(config.get("xunhu_appid") or "").strip()
    appsecret = str(config.get("xunhu_appsecret") or "").strip()
    gateway = str(config.get("xunhu_gateway") or default_payment_config["xunhu_gateway"]).strip()
    if not bool(config.get("xunhu_enabled", False)) or not appid or not appsecret:
        raise HTTPException(status_code=403, detail="虎皮椒支付暂未开启")
    package = package_by_id(package_id)
    order_id = uuid.uuid4().hex
    created_at = int(now())
    payload = {
        "version": "1.1",
        "appid": appid,
        "trade_order_id": order_id,
        "total_fee": format_yuan_amount(float(package.get("amount", 0))),
        "title": str(package.get("name")),
        "time": str(created_at),
        "notify_url": str(config.get("xunhu_notify_url") or "").strip() or f"{PUBLIC_BASE_URL}/api/payment/xunhu/notify",
        "return_url": str(config.get("xunhu_return_url") or "").strip() or stripe_default_success_url(),
        "callback_url": str(config.get("xunhu_callback_url") or "").strip() or stripe_default_cancel_url(),
        "nonce_str": secrets.token_hex(8),
        "plugins": "meetseek-tools",
        "attach": json.dumps({"user_id": user["id"], "package_id": package.get("id"), "points": int(package.get("points", 0))}, ensure_ascii=False),
    }
    payload["hash"] = xunhu_sign(payload, appsecret)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(gateway, json=payload)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"虎皮椒支付暂时不可用：{exc}")
    try:
        data = response.json()
    except ValueError:
        raise HTTPException(status_code=502, detail=f"虎皮椒返回异常：{response.text[:180]}")
    if response.status_code >= 400 or str(data.get("errcode", "0")) not in {"0", ""}:
        raise HTTPException(status_code=502, detail=f"虎皮椒创建订单失败：{data.get('errmsg') or data.get('message') or response.text[:180]}")
    if data.get("hash") and not verify_xunhu_hash(data, appsecret):
        raise HTTPException(status_code=502, detail="虎皮椒返回签名校验失败")
    pay_url = data.get("url") or data.get("url_qrcode")
    if not pay_url:
        raise HTTPException(status_code=502, detail="虎皮椒未返回支付链接")
    with db() as conn:
        conn.execute(
            """
            INSERT INTO credit_orders(id, user_id, package_id, package_name, points, amount, method, transaction_no, screenshot, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'xunhupay', '', '', 'pending', ?, ?)
            """,
            (
                order_id,
                user["id"],
                str(package.get("id")),
                str(package.get("name")),
                int(package.get("points", 0)),
                float(package.get("amount", 0)),
                created_at,
                created_at,
            ),
        )
        row = conn.execute("SELECT credit_orders.*, users.email, users.name FROM credit_orders JOIN users ON users.id = credit_orders.user_id WHERE credit_orders.id = ?", (order_id,)).fetchone()
    log_event("info", "虎皮椒支付订单已创建", user=user["email"], order_id=order_id, points=package.get("points"))
    return {"url": pay_url, "qrcode_url": data.get("url_qrcode") or "", "order": public_credit_order(row)}


@app.post("/api/payment/xunhu/notify")
async def xunhu_notify(request: Request) -> Response:
    config = raw_payment_config()
    appid = str(config.get("xunhu_appid") or "").strip()
    appsecret = str(config.get("xunhu_appsecret") or "").strip()
    if not appid or not appsecret:
        raise HTTPException(status_code=400, detail="虎皮椒支付未配置")
    form = await request.form()
    payload = {key: str(value) for key, value in form.items()}
    if payload.get("appid") and payload.get("appid") != appid:
        raise HTTPException(status_code=400, detail="虎皮椒 APPID 不匹配")
    if not verify_xunhu_hash(payload, appsecret):
        raise HTTPException(status_code=400, detail="虎皮椒签名校验失败")
    if payload.get("status") != "OD":
        return Response("success", media_type="text/plain")
    order_id = str(payload.get("trade_order_id") or "")
    if not order_id:
        raise HTTPException(status_code=400, detail="虎皮椒通知缺少订单号")
    with db() as conn:
        row = conn.execute(
            "SELECT credit_orders.*, users.email, users.name FROM credit_orders JOIN users ON users.id = credit_orders.user_id WHERE credit_orders.id = ?",
            (order_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="本地订单不存在")
        if row["status"] == "approved":
            return Response("success", media_type="text/plain")
        if row["method"] != "xunhupay":
            raise HTTPException(status_code=400, detail="订单类型不是虎皮椒")
        paid_amount = Decimal(str(payload.get("total_fee") or "0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        expected_amount = Decimal(str(row["amount"])).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if paid_amount != expected_amount:
            raise HTTPException(status_code=400, detail="虎皮椒支付金额不匹配")
        transaction_no = str(payload.get("transaction_id") or payload.get("open_order_id") or payload.get("order_id") or "")[:120]
        conn.execute("UPDATE users SET points = points + ? WHERE id = ?", (row["points"], row["user_id"]))
        conn.execute(
            "UPDATE credit_orders SET status = 'approved', transaction_no = ?, updated_at = ? WHERE id = ?",
            (transaction_no, int(now()), order_id),
        )
        updated = conn.execute(
            "SELECT credit_orders.*, users.email, users.name FROM credit_orders JOIN users ON users.id = credit_orders.user_id WHERE credit_orders.id = ?",
            (order_id,),
        ).fetchone()
    log_event("info", "虎皮椒支付成功并自动加分", order_id=order_id, user=updated["email"], points=updated["points"])
    return Response("success", media_type="text/plain")


@app.get("/api/payment/orders/mine")
async def my_payment_orders(request: Request) -> dict[str, Any]:
    user = require_user(request)
    with db() as conn:
        rows = conn.execute(
            "SELECT credit_orders.*, users.email, users.name FROM credit_orders JOIN users ON users.id = credit_orders.user_id WHERE user_id = ? ORDER BY created_at DESC LIMIT 20",
            (user["id"],),
        ).fetchall()
    return {"orders": [public_member_credit_order(row) for row in rows]}


@app.post("/api/rewards/ad/start")
async def reward_ad_start(request: Request) -> dict[str, Any]:
    user = require_user(request)
    config = public_reward_config()
    if not config.get("enabled", True) or config.get("points", 0) <= 0:
        raise HTTPException(status_code=403, detail="看广告赚积分暂未开放")
    token = secrets.token_urlsafe(24)
    reward_sessions[token] = {"user_id": user["id"], "started_at": now(), "seconds": config["seconds"]}
    return {"token": token, "seconds": config["seconds"], "points": config["points"], "daily_limit": config["daily_limit"]}


@app.post("/api/rewards/ad/claim")
async def reward_ad_claim(request: Request, token: str = Form(...)) -> dict[str, Any]:
    user = require_user(request)
    config = public_reward_config()
    session = reward_sessions.get(token)
    if not session or session.get("user_id") != user["id"]:
        raise HTTPException(status_code=400, detail="广告任务已失效，请重新开始")
    if now() - float(session.get("started_at", 0)) < int(session.get("seconds", config["seconds"])):
        raise HTTPException(status_code=400, detail="观看时间还不够")
    day = today_key()
    identity = f"user:{user['id']}"
    with db() as conn:
        row = conn.execute("SELECT count FROM usage_counts WHERE day = ? AND identity = ? AND tool = 'ad_reward'", (day, identity)).fetchone()
        current = row["count"] if row else 0
        if current >= config["daily_limit"]:
            raise HTTPException(status_code=429, detail=f"今日广告积分已领完：上限 {config['daily_limit']} 次")
        conn.execute(
            """
            INSERT INTO usage_counts(day, identity, tool, count, updated_at)
            VALUES (?, ?, 'ad_reward', 1, ?)
            ON CONFLICT(day, identity, tool)
            DO UPDATE SET count = count + 1, updated_at = excluded.updated_at
            """,
            (day, identity, int(now())),
        )
        conn.execute("UPDATE users SET points = points + ? WHERE id = ?", (config["points"], user["id"]))
        updated = conn.execute("SELECT id, email, name, nickname, tier, points, avatar_url, bio, created_at FROM users WHERE id = ?", (user["id"],)).fetchone()
    reward_sessions.pop(token, None)
    log_event("info", "广告积分已领取", user=user["email"], points=config["points"])
    return {"user": public_user(updated), "points": config["points"]}


@app.get("/api/member/space")
async def member_space(request: Request) -> dict[str, Any]:
    user = require_user(request)
    with db() as conn:
        row = conn.execute("SELECT id, email, name, nickname, tier, points, avatar_url, bio, phone, disabled, deleted_at, created_at FROM users WHERE id = ?", (user["id"],)).fetchone()
        orders = conn.execute(
            "SELECT credit_orders.*, users.email, users.name FROM credit_orders JOIN users ON users.id = credit_orders.user_id WHERE user_id = ? ORDER BY created_at DESC LIMIT 5",
            (user["id"],),
        ).fetchall()
    return {
        "user": api_public_user_with_stats(row),
        "checkin": checkin_state(user["id"]),
        "checkin_config": public_checkin_config(),
        "payment_orders": [public_member_credit_order(order) for order in orders],
    }


@app.post("/api/member/profile")
async def member_profile_update(
    request: Request,
    name: str = Form(""),
    nickname: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    bio: str = Form(""),
    avatar: UploadFile | None = File(default=None),
) -> dict[str, Any]:
    return await update_user_profile_payload(request, nickname or name, email, phone, bio, avatar)


@app.post("/api/user/profile")
async def user_profile_update(
    request: Request,
    nickname: str = Form(...),
    email: str = Form(""),
    phone: str = Form(""),
    bio: str = Form(""),
    avatar: UploadFile | None = File(default=None),
) -> dict[str, Any]:
    return await update_user_profile_payload(request, nickname, email, phone, bio, avatar)


async def update_user_profile_payload(
    request: Request,
    nickname: str,
    email: str = "",
    phone: str = "",
    bio: str = "",
    avatar: UploadFile | None = None,
) -> dict[str, Any]:
    check_rate_limit(request)
    user = require_user(request)
    clean_name = re.sub(r"\s+", " ", nickname.strip())[:60]
    if len(clean_name) < 2:
        raise HTTPException(status_code=400, detail="昵称至少 2 个字")
    clean_email = str(email or user.get("email") or "").strip().lower()[:160]
    if not EMAIL_RE.fullmatch(clean_email):
        raise HTTPException(status_code=400, detail="请输入有效邮箱")
    clean_phone = re.sub(r"\s+", " ", str(phone or "").strip())[:24]
    if clean_phone and not PHONE_RE.fullmatch(clean_phone):
        raise HTTPException(status_code=400, detail="请输入有效手机号")
    clean_bio = re.sub(r"\s+", " ", html.unescape(bleach.clean(str(bio or ""), tags=[], attributes={}, strip=True))).strip()[:150]
    avatar_url = ""
    if avatar and avatar.filename:
        avatar_url = await save_avatar_image(avatar)
    with db() as conn:
        email_owner = conn.execute("SELECT id FROM users WHERE email = ? AND id != ?", (clean_email, user["id"])).fetchone()
        if email_owner:
            raise HTTPException(status_code=400, detail="这个邮箱已经被其他账号绑定")
        if clean_phone:
            phone_owner = conn.execute("SELECT id FROM users WHERE phone = ? AND id != ?", (clean_phone, user["id"])).fetchone()
            if phone_owner:
                raise HTTPException(status_code=400, detail="这个手机号已经被其他账号绑定")
        if avatar_url:
            conn.execute(
                "UPDATE users SET name = ?, nickname = ?, email = ?, phone = ?, bio = ?, avatar_url = ? WHERE id = ?",
                (clean_name, clean_name, clean_email, clean_phone, clean_bio, avatar_url, user["id"]),
            )
        else:
            conn.execute(
                "UPDATE users SET name = ?, nickname = ?, email = ?, phone = ?, bio = ? WHERE id = ?",
                (clean_name, clean_name, clean_email, clean_phone, clean_bio, user["id"]),
            )
        row = conn.execute("SELECT id, email, name, nickname, tier, points, avatar_url, bio, phone, disabled, deleted_at, created_at FROM users WHERE id = ?", (user["id"],)).fetchone()
    log_event("info", "会员资料已更新", user=user["email"])
    return {"user": api_public_user_with_stats(row)}


@app.post("/api/member/password")
async def member_password_update(
    request: Request,
    old_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
) -> dict[str, Any]:
    check_rate_limit(request)
    user = require_user(request)
    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="新密码至少 8 位")
    if new_password != confirm_password:
        raise HTTPException(status_code=400, detail="两次输入的新密码不一致")
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ? AND disabled = 0 AND deleted_at = 0", (user["id"],)).fetchone()
        if not row or not verify_password(old_password, user_password_hash(row)):
            raise HTTPException(status_code=400, detail="旧密码不正确")
        new_hash = hash_password(new_password)
        conn.execute("UPDATE users SET password_hash = ?, hashed_password = ? WHERE id = ?", (new_hash, new_hash, user["id"]))
        conn.execute("DELETE FROM sessions WHERE user_id = ? AND token != ?", (user["id"], request.cookies.get("meetseek_session", "")))
        conn.execute("UPDATE password_resets SET used_at = ? WHERE user_id = ? AND used_at = 0", (int(now()), user["id"]))
    log_event("info", "会员密码已修改", user=user["email"])
    return {"ok": True}


@app.post("/api/member/checkin")
async def member_checkin(request: Request) -> dict[str, Any]:
    user = require_user(request)
    config = public_checkin_config()
    if not config.get("enabled", True):
        raise HTTPException(status_code=403, detail="签到功能暂未开放")
    if config["points"] <= 0 and config["streak_bonus"] <= 0:
        raise HTTPException(status_code=403, detail="签到积分暂未配置")
    today = today_key()
    yesterday = yesterday_key()
    with db() as conn:
        existing = conn.execute("SELECT * FROM daily_checkins WHERE user_id = ? AND day = ?", (user["id"], today)).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="今天已经签到过了")
        yesterday_row = conn.execute("SELECT * FROM daily_checkins WHERE user_id = ? AND day = ?", (user["id"], yesterday)).fetchone()
        streak = int(yesterday_row["streak"]) + 1 if yesterday_row else 1
        bonus = config["streak_bonus"] if config["streak_bonus"] and streak % config["streak_days"] == 0 else 0
        points = config["points"] + bonus
        created_at = int(now())
        try:
            conn.execute(
                "INSERT INTO daily_checkins(user_id, day, points, streak, created_at) VALUES (?, ?, ?, ?, ?)",
                (user["id"], today, points, streak, created_at),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=400, detail="今天已经签到过了")
        conn.execute("UPDATE users SET points = points + ? WHERE id = ?", (points, user["id"]))
        updated = conn.execute("SELECT id, email, name, nickname, tier, points, avatar_url, bio, disabled, deleted_at, created_at FROM users WHERE id = ?", (user["id"],)).fetchone()
    log_event("info", "会员签到积分已领取", user=user["email"], points=points, streak=streak)
    return {
        "user": api_public_user(updated),
        "points": points,
        "streak": streak,
        "bonus": bonus,
        "checkin": checkin_state(user["id"]),
        "checkin_config": config,
    }


@app.get("/api/auth/me")
async def auth_me(request: Request) -> dict[str, Any]:
    return {"user": api_public_user_with_stats(user_from_request(request))}


@app.get("/api/user/me")
async def api_user_me(current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    return {"user": api_public_user_with_stats(current_user)}


@app.get("/tools/ip-check", response_class=HTMLResponse)
async def ip_check_page(request: Request) -> Response:
    track_visit(request)
    return (APP_ROOT / "static" / "ip-check.html").read_text(encoding="utf-8")


@app.get("/tools/transparent-image", response_class=HTMLResponse)
async def transparent_image_tool(request: Request) -> Response:
    host = public_host(request)
    if host in {"www.meetseek.ai", "meetseek.ai"}:
        return RedirectResponse(f"{TOOLS_BASE_URL}/tools/transparent-image", status_code=301)
    return templates.TemplateResponse(
        "transparent_image.html",
        {
            "request": request,
            "site_name": "meetseek",
            "main_base_url": MAIN_BASE_URL,
            "tools_base_url": TOOLS_BASE_URL,
            "prompts_base_url": PROMPTS_BASE_URL,
            "current_user": user_from_request(request),
            "meta": {
                "title": "透明图生成器 - meetseek AI 工具箱",
                "description": "上传图片后本地抠除指定背景色，导出透明 PNG 或 WebP，并可按自定义宽高调整图片尺寸。",
                "canonical_url": f"{TOOLS_BASE_URL}/tools/transparent-image",
                "image_url": "",
                "type": "website",
            },
        },
    )


@app.get("/tools/green-video", response_class=HTMLResponse)
async def green_video_tool(request: Request) -> Response:
    host = public_host(request)
    if host in {"www.meetseek.ai", "meetseek.ai"}:
        return RedirectResponse(f"{TOOLS_BASE_URL}/tools/green-video", status_code=301)
    return templates.TemplateResponse(
        "green_video.html",
        {
            "request": request,
            "site_name": "meetseek",
            "main_base_url": MAIN_BASE_URL,
            "tools_base_url": TOOLS_BASE_URL,
            "prompts_base_url": PROMPTS_BASE_URL,
            "current_user": user_from_request(request),
            "meta": {
                "title": "视频解析下载 - meetseek AI 工具箱",
                "description": "粘贴公开视频链接，解析标题、封面、视频格式、音频格式和封面图，支持直接下载到本地。",
                "canonical_url": f"{TOOLS_BASE_URL}/tools/green-video",
                "image_url": "",
                "type": "website",
            },
        },
    )


@app.get("/tools/video-downloader", response_class=HTMLResponse)
async def video_downloader_tool(request: Request) -> Response:
    host = public_host(request)
    if host in {"www.meetseek.ai", "meetseek.ai"}:
        return RedirectResponse(f"{TOOLS_BASE_URL}/tools/video-downloader", status_code=301)
    return templates.TemplateResponse(
        "video_downloader.html",
        {
            "request": request,
            "site_name": "meetseek",
            "main_base_url": MAIN_BASE_URL,
            "tools_base_url": TOOLS_BASE_URL,
            "prompts_base_url": PROMPTS_BASE_URL,
            "current_user": user_from_request(request),
            "meta": {
                "title": "万能视频下载 - meetseek AI 工具箱",
                "description": "粘贴公开视频链接，解析标题、封面、时长和清晰度，支持 4K、2K、1080P、720P、仅音频 MP3 和批量下载。",
                "canonical_url": f"{TOOLS_BASE_URL}/tools/video-downloader",
                "image_url": "",
                "type": "website",
            },
        },
    )


def wechat_geo_plain_text(content: str) -> str:
    value = (content or "").replace("\r\n", "\n").replace("\r", "\n")
    if "<" in value and ">" in value:
        soup = BeautifulSoup(value, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "aside"]):
            tag.decompose()
        value = soup.get_text("\n")
    value = bleach.clean(value, tags=[], strip=True)
    value = re.sub(r"[ \t\u3000]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def estimate_geo_tokens(text: str) -> int:
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin_words = len(re.findall(r"[A-Za-z0-9_]+(?:[-'][A-Za-z0-9_]+)?", text))
    symbols = len(re.findall(r"[^\s\w\u4e00-\u9fff]", text))
    return max(1, int(chinese_chars * 0.75 + latin_words * 1.15 + symbols * 0.25))


def split_geo_chunks(text: str, target_tokens: int = 300, overlap_tokens: int = 50) -> list[dict[str, Any]]:
    paragraphs = [item.strip() for item in re.split(r"\n{2,}", text) if item.strip()]
    if not paragraphs:
        paragraphs = [text.strip()] if text.strip() else []
    chunks: list[dict[str, Any]] = []
    current: list[str] = []
    current_tokens = 0
    for paragraph in paragraphs:
        paragraph_tokens = estimate_geo_tokens(paragraph)
        if current and current_tokens + paragraph_tokens > target_tokens:
            chunk_text = "\n\n".join(current).strip()
            chunks.append({"index": len(chunks) + 1, "tokens": estimate_geo_tokens(chunk_text), "text": chunk_text})
            if overlap_tokens > 0 and current:
                tail: list[str] = []
                tail_tokens = 0
                for item in reversed(current):
                    tail.insert(0, item)
                    tail_tokens += estimate_geo_tokens(item)
                    if tail_tokens >= overlap_tokens:
                        break
                current = tail
                current_tokens = tail_tokens
            else:
                current = []
                current_tokens = 0
        current.append(paragraph)
        current_tokens += paragraph_tokens
    if current:
        chunk_text = "\n\n".join(current).strip()
        chunks.append({"index": len(chunks) + 1, "tokens": estimate_geo_tokens(chunk_text), "text": chunk_text})
    return chunks[:80]


def wechat_geo_metrics(text: str) -> dict[str, Any]:
    token_count = estimate_geo_tokens(text)
    numbers = len(re.findall(r"\d+(?:\.\d+)?%?|\d{4}年?", text))
    headings = len(re.findall(r"(^|\n)\s*(#{1,3}\s+|[一二三四五六七八九十]+[、.．]|[0-9]+[、.．])", text))
    entities = len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}(?:公司|集团|模型|系统|平台|市场|行业|工具|算法|Agent|RAG|AI)", text))
    fluff = len(re.findall(r"极大|显著|大幅|领先|重磅|赋能|革命性|全新升级|遥遥领先|非常重要|极致", text))
    data_points = numbers + headings + entities
    semantic_density = min(100, int((data_points * 9 + max(0, 18 - fluff) * 2) / max(1, token_count / 180)))
    noise_score = max(0, min(100, 100 - int(fluff * 6 + len(re.findall(r"<div|style=", text)) * 8)))
    geo_score = max(0, min(100, int(semantic_density * 0.52 + noise_score * 0.28 + min(100, headings * 16) * 0.2)))
    suggestions: list[str] = []
    if numbers < 2:
        suggestions.append("补充年份、比例、金额或样本量，提升信息增益。")
    if headings < 2:
        suggestions.append("增加 H2/H3 问答式小标题，方便 RAG 切片召回。")
    if fluff:
        suggestions.append("减少“大幅、显著、赋能”等泛化词，改成可验证事实。")
    if token_count > 2400:
        suggestions.append("文章较长，建议按问题拆成多个直答段落。")
    if not suggestions:
        suggestions.append("结构干净，适合直接复制到公众号或知识库。")
    return {
        "token_count": token_count,
        "semantic_density": semantic_density,
        "noise_score": noise_score,
        "geo_score": geo_score,
        "suggestions": suggestions,
    }


def wechat_geo_analysis_payload(title: str, content: str, context_note: str = "") -> dict[str, Any]:
    plain = wechat_geo_plain_text(content)
    chunks = split_geo_chunks(plain)
    metrics = wechat_geo_metrics(plain)
    return {
        "title": title.strip() or "未命名公众号文章",
        "plain_text": plain,
        "context_note": context_note.strip(),
        "chunks": chunks,
        **metrics,
    }


def paragraph_to_wechat_html(paragraph: str) -> str:
    raw = paragraph.strip()
    image_match = re.fullmatch(r"!\[([^\]]*)\]\(([^)]+)\)", raw)
    if image_match:
        alt = html_escape(image_match.group(1) or "公众号配图")
        src = html_escape(image_match.group(2))
        return (
            '<figure style="margin:22px 0;text-align:center;">'
            f'<img src="{src}" alt="{alt}" style="display:block;width:100%;max-width:100%;border-radius:14px;" />'
            f'<figcaption style="margin-top:8px;color:#94a3b8;font-size:13px;line-height:1.6;">{alt}</figcaption>'
            '</figure>'
        )
    code_match = re.fullmatch(r"```(?:[a-zA-Z0-9_-]+)?\n?([\s\S]+?)\n?```", raw)
    if code_match:
        return (
            '<pre style="margin:18px 0;padding:16px;border-radius:14px;background:#0f172a;'
            'color:#d1fae5;font-size:13px;line-height:1.75;white-space:pre-wrap;overflow:auto;">'
            f"{html_escape(code_match.group(1))}</pre>"
        )
    text = inline_wechat_format(raw)
    if not text:
        return ""
    if re.match(r"^(#{1,3}\s+|[一二三四五六七八九十]+[、.．]|[0-9]+[、.．])", raw):
        clean = re.sub(r"^#{1,3}\s+", "", raw)
        return (
            '<h2 style="margin:28px 0 12px;padding-left:12px;border-left:4px solid #f97316;'
            'font-size:20px;line-height:1.45;color:#0f172a;font-weight:800;">'
            f"{inline_wechat_format(clean)}</h2>"
        )
    if re.match(r"^[-*]\s+", raw):
        items = [inline_wechat_format(re.sub(r"^[-*]\s+", "", item.strip())) for item in paragraph.split("\n") if item.strip()]
        inner = "".join(f'<li style="margin:6px 0;">{item}</li>' for item in items)
        return f'<ul style="margin:12px 0;padding-left:22px;color:#334155;line-height:1.9;">{inner}</ul>'
    return f'<p style="margin:14px 0;color:#334155;font-size:16px;line-height:1.95;">{text}</p>'


def inline_wechat_format(value: str) -> str:
    escaped = html_escape(value)
    escaped = re.sub(r"\*\*(.+?)\*\*", r'<strong style="font-weight:800;color:#0f172a;">\1</strong>', escaped)
    escaped = re.sub(
        r"\[color=(#[0-9a-fA-F]{3,6}|[a-zA-Z]+)\](.+?)\[/color\]",
        r'<span style="color:\1;font-weight:700;">\2</span>',
        escaped,
    )
    return escaped


def build_wechat_geo_exports(title: str, content: str, context_note: str = "") -> dict[str, str]:
    analysis = wechat_geo_analysis_payload(title, content, context_note)
    title_text = html_escape(analysis["title"])
    paragraphs = [item for item in re.split(r"\n{2,}", analysis["plain_text"]) if item.strip()]
    body = "\n".join(paragraph_to_wechat_html(item) for item in paragraphs)
    context_html = f"\n<!-- Context: {html_escape(analysis['context_note'])} -->" if analysis["context_note"] else ""
    wechat_html = (
        '<section style="box-sizing:border-box;margin:0 auto;padding:24px 18px;max-width:677px;'
        'font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif;background:#ffffff;">'
        f'<h1 style="margin:0 0 20px;color:#020617;font-size:26px;line-height:1.35;font-weight:900;">{title_text}</h1>'
        '<section style="margin:20px 0;padding:16px 18px;border-radius:14px;background:#fff7ed;'
        'border:1px solid #fed7aa;color:#9a3412;font-size:14px;line-height:1.8;">'
        f"AI 摘要：本文约 {analysis['token_count']} Tokens，GEO 评分 {analysis['geo_score']}。"
        '</section>'
        f"{body}</section>{context_html}"
    )
    ai_sections = []
    for index, paragraph in enumerate(paragraphs, start=1):
        clean = html_escape(paragraph.strip())
        if re.match(r"^(#{1,3}\s+|[一二三四五六七八九十]+[、.．]|[0-9]+[、.．])", paragraph.strip()):
            clean_heading = html_escape(re.sub(r"^#{1,3}\s+", "", paragraph.strip()))
            ai_sections.append(f'<h2 id="geo-section-{index}" data-semantic="question-or-section">{clean_heading}</h2>')
        else:
            ai_sections.append(f'<p data-semantic="answer-or-evidence" data-chunk-anchor="geo-section-{index}">{clean}</p>')
    ai_html = (
        f'<article data-semantic="wechat-geo-article" data-geo-score="{analysis["geo_score"]}">'
        f"<h1>{title_text}</h1>{''.join(ai_sections)}</article>{context_html}"
    )
    markdown = f"# {analysis['title']}\n\n" + "\n\n".join(paragraphs)
    return {"wechat_html": wechat_html, "ai_html": ai_html, "markdown": markdown}


@app.get("/tools/wechat-geo-editor", response_class=HTMLResponse)
async def wechat_geo_editor(request: Request) -> Response:
    return templates.TemplateResponse(
        "wechat_geo_editor.html",
        {
            "request": request,
            "site_name": "meetseek",
            "main_base_url": MAIN_BASE_URL,
            "tools_base_url": TOOLS_BASE_URL,
            "prompts_base_url": PROMPTS_BASE_URL,
            "current_user": user_from_request(request),
            "meta": {
                "title": "公众号 GEO 排版工具 - meetseek AI 工具箱",
                "description": "面向微信公众号和 AI 知识库的双轨排版工具，支持 RAG 切片预览、GEO 评分、公众号 HTML 与 AI 语义 HTML 导出。",
                "canonical_url": f"{TOOLS_BASE_URL}/tools/wechat-geo-editor",
                "image_url": "",
                "type": "website",
            },
        },
    )


@app.post("/api/wechat-geo/analyze")
async def api_wechat_geo_analyze(request: Request, payload: WechatGeoPayload) -> dict[str, Any]:
    check_rate_limit(request)
    return {"analysis": wechat_geo_analysis_payload(payload.title, payload.content, payload.context_note)}


@app.post("/api/wechat-geo/export")
async def api_wechat_geo_export(request: Request, payload: WechatGeoPayload) -> dict[str, Any]:
    check_rate_limit(request)
    analysis = wechat_geo_analysis_payload(payload.title, payload.content, payload.context_note)
    exports = build_wechat_geo_exports(payload.title, payload.content, payload.context_note)
    timestamp = now()
    with db() as conn:
        cur = conn.execute(
            """
            INSERT INTO wechat_geo_articles(
                title, source_text, context_note, wechat_html, ai_html, clean_markdown,
                chunk_json, suggestions_json, geo_score, semantic_density, noise_score,
                token_count, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                analysis["title"],
                analysis["plain_text"],
                analysis["context_note"],
                exports["wechat_html"],
                exports["ai_html"],
                exports["markdown"],
                json.dumps(analysis["chunks"], ensure_ascii=False),
                json.dumps(analysis["suggestions"], ensure_ascii=False),
                analysis["geo_score"],
                analysis["semantic_density"],
                analysis["noise_score"],
                analysis["token_count"],
                "draft",
                timestamp,
                timestamp,
            ),
        )
    return {"status": "success", "draft_id": cur.lastrowid, "analysis": analysis, "exports": exports}


@app.get("/api/wechat-geo/images/{filename}")
async def wechat_geo_image(filename: str):
    safe = Path(filename).name
    path = IMAGE_DIR / safe
    if not safe.startswith("wechat-geo-") or not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="图片不存在")
    return FileResponse(path, media_type="image/webp", headers={"cache-control": "public, max-age=31536000, immutable"})


@app.post("/api/wechat-geo/upload-image")
async def api_wechat_geo_upload_image(request: Request, image: UploadFile = File(...)) -> dict[str, str]:
    check_rate_limit(request)
    filename = await save_uploaded_image_webp(image, IMAGE_DIR, "wechat-geo", max_side=2200, quality=88, max_mb=8)
    return {"url": f"/api/wechat-geo/images/{filename}", "alt": Path(image.filename or "公众号配图").stem[:80] or "公众号配图"}


@app.get("/tools/identity-builder", response_class=HTMLResponse)
async def identity_builder(request: Request) -> Response:
    host = public_host(request)
    if host == "www.meetseek.ai":
        return RedirectResponse(f"{MAIN_BASE_URL}/tools/identity-builder", status_code=301)
    return templates.TemplateResponse(
        "identity_builder.html",
        {
            "request": request,
            "site_name": "meetseek",
            "main_base_url": MAIN_BASE_URL,
            "tools_base_url": TOOLS_BASE_URL,
            "prompts_base_url": PROMPTS_BASE_URL,
            "meta": {
                "title": "JSON 身份锁组装台 - meetseek",
                "description": "通过可视化表单实时生成用于 AI 绘画的结构化 JSON 身份锁提示词。",
                "canonical_url": f"{MAIN_BASE_URL}/tools/identity-builder",
                "image_url": "",
                "type": "website",
            },
        },
    )


@app.get("/tools/video-scripter", response_class=HTMLResponse)
async def video_scripter(request: Request) -> Response:
    host = public_host(request)
    if host == "www.meetseek.ai":
        return RedirectResponse(f"{MAIN_BASE_URL}/tools/video-scripter", status_code=301)
    return templates.TemplateResponse(
        "video_scripter.html",
        {
            "request": request,
            "site_name": "meetseek",
            "main_base_url": MAIN_BASE_URL,
            "tools_base_url": TOOLS_BASE_URL,
            "prompts_base_url": PROMPTS_BASE_URL,
            "meta": {
                "title": "视频分镜提示词时间轴 - meetseek",
                "description": "通过可视化时间轴节点实时生成 Seedance 等视频模型可用的运镜分镜 Prompt。",
                "canonical_url": f"{MAIN_BASE_URL}/tools/video-scripter",
                "image_url": "",
                "type": "website",
            },
        },
    )


@app.get("/tools/view-matrix", response_class=HTMLResponse)
async def view_matrix(request: Request) -> Response:
    host = public_host(request)
    if host == "www.meetseek.ai":
        return RedirectResponse(f"{MAIN_BASE_URL}/tools/view-matrix", status_code=301)
    return templates.TemplateResponse(
        "view_matrix.html",
        {
            "request": request,
            "site_name": "meetseek",
            "main_base_url": MAIN_BASE_URL,
            "tools_base_url": TOOLS_BASE_URL,
            "prompts_base_url": PROMPTS_BASE_URL,
            "meta": {
                "title": "角色多视角矩阵生成器 - meetseek",
                "description": "通过摄影棚级视角、镜头和光影补丁，生成保持角色一致性的多视角 AI 绘图 Prompt。",
                "canonical_url": f"{MAIN_BASE_URL}/tools/view-matrix",
                "image_url": "",
                "type": "website",
            },
        },
    )


@app.get("/tools/article-similarity", response_class=HTMLResponse)
async def article_similarity_page(request: Request) -> Response:
    host = public_host(request)
    if host == "www.meetseek.ai":
        return RedirectResponse(f"{MAIN_BASE_URL}/tools/article-similarity", status_code=301)
    return templates.TemplateResponse(
        "article_similarity.html",
        {
            "request": request,
            "site_name": "meetseek",
            "main_base_url": MAIN_BASE_URL,
            "tools_base_url": TOOLS_BASE_URL,
            "prompts_base_url": PROMPTS_BASE_URL,
            "current_user": user_from_request(request),
            "meta": {
                "title": "文章相似度检查 - meetseek",
                "description": "对比两篇文章的全文相似度和语言结构相似度，并高亮右侧疑似重复片段。",
                "canonical_url": f"{MAIN_BASE_URL}/tools/article-similarity",
                "image_url": "",
                "type": "website",
            },
        },
    )


@app.get("/api/tools/extract-article")
async def api_extract_article(request: Request, url: str) -> dict[str, Any]:
    check_rate_limit(request)
    clean = legal_url(url)
    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True, headers=LINK_PREVIEW_HEADERS) as client:
            response = await client.get(clean)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"原文提取失败：{str(exc)[:120]}")
    result = extract_article_text_from_html(response.text, clean)
    if not result.get("content"):
        raise HTTPException(status_code=422, detail="没有提取到可用正文，请手动粘贴文章内容")
    return {"article": result}


class ArticleSimilarityRequest(BaseModel):
    text_a: str = Field(..., min_length=1, max_length=200_000)
    text_b: str = Field(..., min_length=1, max_length=200_000)


plagiarism_detector = PlagiarismDetector()


def _normalize_with_map(text: str) -> tuple[str, list[int]]:
    chars: list[str] = []
    index_map: list[int] = []
    for index, char in enumerate(text or ""):
        if re.match(r"[\u4e00-\u9fa5A-Za-z0-9]", char):
            chars.append(char.lower())
            index_map.append(index)
    return "".join(chars), index_map


def _merge_offset_spans(spans: list[dict[str, int]]) -> list[dict[str, int]]:
    merged: list[dict[str, int]] = []
    for span in sorted((s for s in spans if s["end"] > s["start"]), key=lambda item: (item["start"], -item["end"])):
        if not merged or span["start"] > merged[-1]["end"]:
            merged.append(dict(span))
        else:
            merged[-1]["end"] = max(merged[-1]["end"], span["end"])
            if span.get("kind") == "exact" or merged[-1].get("kind") == "exact":
                merged[-1]["kind"] = "exact"
    return merged


def _continuous_match_spans(text_a: str, text_b: str, min_len: int = 13) -> list[dict[str, int]]:
    norm_a, _ = _normalize_with_map(text_a)
    norm_b, map_b = _normalize_with_map(text_b)
    if len(norm_a) < min_len or len(norm_b) < min_len:
        return []

    index: dict[str, list[int]] = {}
    for i in range(0, len(norm_a) - min_len + 1):
        key = norm_a[i : i + min_len]
        bucket = index.setdefault(key, [])
        if len(bucket) < 24:
            bucket.append(i)

    spans: list[dict[str, int]] = []
    i = 0
    while i <= len(norm_b) - min_len:
        positions = index.get(norm_b[i : i + min_len])
        if not positions:
            i += 1
            continue
        best = 0
        for pos in positions:
            k = 0
            while pos + k < len(norm_a) and i + k < len(norm_b) and norm_a[pos + k] == norm_b[i + k]:
                k += 1
            best = max(best, k)
        if best >= min_len:
            spans.append({"start": map_b[i], "end": map_b[i + best - 1] + 1, "kind": "exact"})
            i += best
        else:
            i += 1
    return _merge_offset_spans(spans)


def _sentence_spans(text: str) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    pattern = re.compile(r"[^。！？!?；;\n]+(?:[。！？!?；;]+|\n+|$)")
    for match in pattern.finditer(text or ""):
        value = match.group(0).strip()
        if len(re.sub(r"\s+", "", value)) >= 24:
            lead = len(match.group(0)) - len(match.group(0).lstrip())
            tail = len(match.group(0).rstrip())
            spans.append({"start": match.start() + lead, "end": match.start() + tail, "text": value})
    return spans


def _compact_structure_text(text: str) -> str:
    masked = plagiarism_detector.masker.mask(text or "")
    if plagiarism_detector._is_mostly_english(masked):
        return " ".join(plagiarism_detector._english_structure_tokens(masked))
    return "".join(plagiarism_detector._chinese_structure_tokens(masked))


def _short_ngrams(value: str, size: int) -> set[str]:
    compact = re.sub(r"\s+", " ", value or "").strip()
    if len(compact) < size:
        return set()
    return {compact[i : i + size] for i in range(len(compact) - size + 1)}


def _span_overlap(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return not (a["end"] <= b["start"] or a["start"] >= b["end"])


def _subtract_blocked_spans(spans: list[dict[str, Any]], blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for span in spans:
        chunks = [(int(span["start"]), int(span["end"]))]
        for blocker in blockers:
            next_chunks: list[tuple[int, int]] = []
            for start, end in chunks:
                if blocker["end"] <= start or blocker["start"] >= end:
                    next_chunks.append((start, end))
                    continue
                if start < blocker["start"]:
                    next_chunks.append((start, blocker["start"]))
                if blocker["end"] < end:
                    next_chunks.append((blocker["end"], end))
            chunks = next_chunks
        for start, end in chunks:
            if end - start >= 12:
                new_span = dict(span)
                new_span["start"] = start
                new_span["end"] = end
                cleaned.append(new_span)
    return cleaned


def _structure_sentence_spans(text_a: str, text_b: str, exact_spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    left_sentences = _sentence_spans(text_a)
    right_sentences = _sentence_spans(text_b)
    if not left_sentences or not right_sentences:
        return []

    left_cache: list[dict[str, Any]] = []
    for item in left_sentences:
        structure = _compact_structure_text(item["text"])
        if len(structure) >= 12:
            left_cache.append({"structure": structure, "grams": _short_ngrams(structure, 6)})

    spans: list[dict[str, Any]] = []
    for item in right_sentences:
        structure = _compact_structure_text(item["text"])
        if len(structure) < 12:
            continue
        grams = _short_ngrams(structure, 6)
        best = 0.0
        for left in left_cache:
            gram_score = plagiarism_detector._jaccard(grams, left["grams"])
            seq_score = SequenceMatcher(None, structure[:500], left["structure"][:500]).ratio()
            best = max(best, gram_score, seq_score * 0.78)
        if best >= 0.38 and not any(_span_overlap(item, exact) for exact in exact_spans):
            spans.append({"start": item["start"], "end": item["end"], "kind": "structure", "score": round(best, 4)})
    return _merge_offset_spans(_subtract_blocked_spans(spans, exact_spans))


@app.post("/api/tools/article-similarity")
async def api_article_similarity(request: Request, payload: ArticleSimilarityRequest) -> dict[str, Any]:
    check_rate_limit(request)
    text_a = payload.text_a.strip()
    text_b = payload.text_b.strip()
    if not text_a or not text_b:
        raise HTTPException(status_code=400, detail="请先填入左右两篇文章内容")

    result = await asyncio.to_thread(plagiarism_detector.analyze, text_a, text_b)
    exact_spans = await asyncio.to_thread(_continuous_match_spans, text_a, text_b, 13)
    structure_spans = await asyncio.to_thread(_structure_sentence_spans, text_a, text_b, exact_spans)
    right_spans = sorted(exact_spans + structure_spans, key=lambda item: (item["start"], item["end"]))
    copied = result.textual_similarity >= 0.20 or result.structural_similarity >= 0.30
    final_message = (
        f"判定结果：认定为抄袭。文字相似度 {result.textual_similarity:.0%}，"
        f"剔除专有名词后语言结构重合度 {result.structural_similarity:.0%}。"
        "命中规则：文字相似度≥20% 或 剔除专有名词后语言结构重合度≥30%。"
        if copied
        else (
            f"判定结果：认定为非抄袭。文字相似度 {result.textual_similarity:.0%}，"
            f"剔除专有名词后语言结构重合度 {result.structural_similarity:.0%}，均未达到抄袭阈值。"
        )
    )
    return {
        "textual_similarity": result.textual_similarity,
        "structural_similarity": result.structural_similarity,
        "entity_ratio": result.entity_ratio_in_overlaps,
        "entity_count_a": result.text_a_shadow.count(ENTITY_TOKEN),
        "entity_count_b": result.text_b_shadow.count(ENTITY_TOKEN),
        "ner_engines": result.ner_engines,
        "verdict": result.verdict,
        "reason": result.reason,
        "copied": copied,
        "final_message": final_message,
        "right_spans": right_spans,
        "exact_spans": exact_spans,
        "structure_spans": structure_spans,
        "overlap_blocks": result.overlap_blocks,
    }


@app.post("/api/auth/register")
async def auth_register(request: Request, response: Response, email: str = Form(...), password: str = Form(...), name: str = Form("")) -> dict[str, Any]:
    check_rate_limit(request)
    clean_email = email.strip().lower()
    display_name = name.strip() or clean_email.split("@", 1)[0]
    if "@" not in clean_email or len(clean_email) > 160:
        raise HTTPException(status_code=400, detail="请输入有效邮箱")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="密码至少 8 位")
    password_hash = hash_password(password)
    try:
        with db() as conn:
            cur = conn.execute(
                "INSERT INTO users(email, name, nickname, password_hash, hashed_password, tier, created_at) VALUES (?, ?, ?, ?, ?, 'free', ?)",
                (clean_email, display_name[:60], display_name[:60], password_hash, password_hash, int(now())),
            )
            user_id = cur.lastrowid
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="这个邮箱已经注册")
    token = create_access_token(user_id)
    set_session_cookie(response, token)
    log_event("info", "新用户注册", email=clean_email)
    return {"user": api_public_user(row)}


@app.post("/api/auth/login")
async def auth_login(request: Request, response: Response, email: str = Form(...), password: str = Form(...)) -> dict[str, Any]:
    check_rate_limit(request)
    clean_email = email.strip().lower()
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (clean_email,)).fetchone()
        if not row or not verify_password(password, user_password_hash(row)):
            raise HTTPException(status_code=400, detail="邮箱或密码不正确")
        if row["deleted_at"] or row["disabled"]:
            raise HTTPException(status_code=403, detail="这个账号已被禁用，请联系管理员")
        if not str(row["hashed_password"] if "hashed_password" in row.keys() else ""):
            conn.execute("UPDATE users SET hashed_password = ? WHERE id = ?", (row["password_hash"], row["id"]))
    token = create_access_token(row["id"])
    set_session_cookie(response, token)
    return {"user": api_public_user(row)}


@app.post("/api/auth/forgot-password")
async def auth_forgot_password(request: Request, email: str = Form(...)) -> dict[str, Any]:
    check_rate_limit(request)
    clean_email = email.strip().lower()
    if "@" not in clean_email or len(clean_email) > 160:
        raise HTTPException(status_code=400, detail="请输入注册邮箱")
    generated = False
    mail_sent = False
    link = ""
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ? AND deleted_at = 0", (clean_email,)).fetchone()
        if row and not row["disabled"]:
            created_at = int(now())
            expires_at = created_at + PASSWORD_RESET_SECONDS
            reset_token = create_access_token(
                row["id"],
                {
                    "purpose": "password_reset",
                    "nonce": secrets.token_urlsafe(12),
                    "exp": expires_at,
                },
            )
            conn.execute("UPDATE password_resets SET used_at = ? WHERE user_id = ? AND used_at = 0", (created_at, row["id"]))
            conn.execute(
                "INSERT INTO password_resets(token, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (reset_token, row["id"], expires_at, created_at),
            )
            link = password_reset_link(reset_token, request)
            generated = True
    if generated:
        try:
            mail_sent = send_password_reset_email(clean_email, link)
        except Exception as exc:
            log_event("error", "密码重置邮件发送失败", email=clean_email, error=str(exc)[:180])
        log_event(
            "info",
            "密码重置链接已生成",
            email=clean_email,
            delivery="email" if mail_sent else "admin-log",
            reset_link=link,
        )
    return {
        "status": "ok",
        "mail_enabled": bool(SMTP_HOST and SMTP_FROM),
        "message": "如果邮箱存在，重置链接会发送到邮箱；未配置邮件时，管理员可在后台日志里处理。",
    }


@app.post("/api/auth/reset-password")
async def auth_reset_password(
    token: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
) -> dict[str, str]:
    clean_token = token.strip()
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="新密码至少 8 位")
    if password != confirm_password:
        raise HTTPException(status_code=400, detail="两次输入的新密码不一致")
    payload = decode_access_token(clean_token)
    if not payload or payload.get("purpose") != "password_reset" or not str(payload.get("sub") or "").isdigit():
        raise HTTPException(status_code=400, detail="重置链接无效或已过期")
    with db() as conn:
        row = conn.execute(
            """
            SELECT password_resets.*, users.email, users.disabled, users.deleted_at
            FROM password_resets
            JOIN users ON users.id = password_resets.user_id
            WHERE password_resets.token = ?
            """,
            (clean_token,),
        ).fetchone()
        if (
            not row
            or str(payload.get("sub")) != str(row["user_id"])
            or row["used_at"]
            or row["expires_at"] < int(now())
            or row["disabled"]
            or row["deleted_at"]
        ):
            raise HTTPException(status_code=400, detail="重置链接无效或已过期")
        used_at = int(now())
        new_hash = hash_password(password)
        conn.execute("UPDATE users SET password_hash = ?, hashed_password = ? WHERE id = ?", (new_hash, new_hash, row["user_id"]))
        conn.execute("UPDATE password_resets SET used_at = ? WHERE token = ?", (used_at, clean_token))
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (row["user_id"],))
    log_event("info", "用户已重置密码", email=row["email"])
    return {"status": "ok", "message": "密码已更新，请用新密码登录。"}


@app.post("/api/auth/logout")
async def auth_logout(request: Request, response: Response) -> dict[str, str]:
    token = request.cookies.get("meetseek_session")
    if token and not decode_access_token(token):
        with db() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    clear_session_cookie(response)
    return {"status": "ok"}


@app.post("/api/admin/login")
async def admin_login(response: Response, password: str = Form(...)) -> dict[str, str]:
    if not ADMIN_TOKEN or not hmac.compare_digest(password.strip(), ADMIN_TOKEN):
        raise HTTPException(status_code=401, detail="管理员密码不正确")
    set_admin_cookie(response)
    log_event("info", "管理员登录")
    return {"status": "ok"}


@app.post("/api/admin/logout")
async def admin_logout(request: Request, response: Response) -> dict[str, str]:
    clear_admin_cookie(response)
    try:
        request.session.clear()
    except AssertionError:
        pass
    return {"status": "ok"}


@app.post("/api/credits/charge")
async def credits_charge(request: Request, key: str = Form(...)) -> dict[str, Any]:
    local_rules = {"metadata_strip", "social_card"}
    if key not in local_rules:
        raise HTTPException(status_code=400, detail="这个积分项目不能手动扣除")
    check_usage_limit(request, key)
    credit = charge_points(request, key)
    return {
        "status": "ok",
        "user": credit["user"],
        "credit_cost": credit["cost"],
        "label": credit["rule"].get("label", key),
    }


@app.post("/api/video/info")
async def video_info(request: Request, url: str = Form(...), agree: str = Form("false")) -> dict[str, Any]:
    check_rate_limit(request)
    require_feature("video")
    if agree != "true":
        raise HTTPException(status_code=400, detail="请确认只处理您有权保存的内容")
    clean = legal_url(url)
    check_usage_limit(request, "video_info")
    try:
        info = await asyncio.to_thread(ydl_info, clean)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"解析失败：{str(exc)[:180]}")

    return {
        "title": info.get("title") or "未命名视频",
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
        "uploader": info.get("uploader"),
        "webpage_url": info.get("webpage_url") or clean,
        "sizes": {
            "4k": readable_size(best_size_for_quality(info, "4k")),
            "2k": readable_size(best_size_for_quality(info, "2k")),
            "1080p": readable_size(best_size_for_quality(info, "1080p")),
            "720p": readable_size(best_size_for_quality(info, "720p")),
            "audio": readable_size(best_size_for_quality(info, "audio")),
        },
        "video_config": public_video_config(),
    }


@app.post("/api/green-video/info")
async def green_video_info(request: Request, url: str = Form(...), agree: str = Form("false")) -> dict[str, Any]:
    check_rate_limit(request)
    require_feature("video")
    if agree != "true":
        raise HTTPException(status_code=400, detail="请确认只解析您有权保存或使用的公开视频内容")
    clean = legal_url(url)
    try:
        info = await asyncio.to_thread(ydl_info, clean)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=readable_video_parse_error(clean, exc))

    if info.get("_type") == "playlist" and info.get("entries"):
        info = next((entry for entry in info["entries"] if entry), info)

    thumbnail = info.get("thumbnail")
    if not thumbnail:
        thumbnails = info.get("thumbnails") or []
        thumbnail = (thumbnails[-1] or {}).get("url") if thumbnails else None

    formats = public_direct_video_formats(info)
    if not formats["video"] and not formats["audio"] and not thumbnail:
        raise HTTPException(status_code=400, detail="没有解析到可用的视频、音频或封面资源")

    check_usage_limit(request, "video_info")
    parsed = urlparse(info.get("webpage_url") or clean)
    return {
        "title": info.get("title") or "未命名视频",
        "description": (info.get("description") or "")[:500],
        "thumbnail": thumbnail,
        "duration": video_duration_label(info.get("duration")),
        "uploader": info.get("uploader") or info.get("channel") or "",
        "webpage_url": info.get("webpage_url") or clean,
        "domain": parsed.netloc.replace("www.", ""),
        "formats": formats,
        "cover": {"url": thumbnail, "filename": f"{safe_file_part(info.get('title') or 'cover')}.jpg"} if thumbnail else None,
    }


@app.post("/api/green-video/download")
async def green_video_download(request: Request, url: str = Form(...), quality: str = Form("1080p"), agree: str = Form("false")) -> dict[str, Any]:
    check_rate_limit(request)
    require_feature("video")
    if agree != "true":
        raise HTTPException(status_code=400, detail="请确认只处理您有权保存的内容")
    quality = validate_video_quality(quality)
    clean = legal_url(url)
    require_user(request)
    check_usage_limit(request, "video_download")
    credit = charge_points(request, "video_download")
    task_id = uuid.uuid4().hex
    tasks[task_id] = {
        "type": "video",
        "status": "queued",
        "message": "任务已排队",
        "progress": 0,
        "quality": quality,
        "url": clean,
        "credit_user_id": credit["user"]["id"],
        "credit_cost": credit["cost"],
        "credit_label": credit["rule"].get("label"),
        "created_at": now(),
    }
    asyncio.create_task(run_video_download(task_id, clean))
    return public_task(task_id)


@app.post("/api/video/download")
async def video_download(request: Request, url: str = Form(...), quality: str = Form("1080p"), agree: str = Form("false")) -> dict[str, Any]:
    check_rate_limit(request)
    require_feature("video")
    if agree != "true":
        raise HTTPException(status_code=400, detail="请确认只处理您有权保存的内容")
    quality = validate_video_quality(quality)
    clean = legal_url(url)
    require_user(request)
    check_usage_limit(request, "video_download")
    credit = charge_points(request, "video_download")
    task_id = uuid.uuid4().hex
    tasks[task_id] = {
        "type": "video",
        "status": "queued",
        "message": "任务已排队",
        "progress": 0,
        "quality": quality,
        "url": clean,
        "credit_user_id": credit["user"]["id"],
        "credit_cost": credit["cost"],
        "credit_label": credit["rule"].get("label"),
        "created_at": now(),
    }
    asyncio.create_task(run_video_download(task_id, clean))
    return public_task(task_id)


@app.post("/api/video/batch")
async def video_batch(request: Request, urls: str = Form(...), quality: str = Form("720p"), agree: str = Form("false")) -> dict[str, Any]:
    check_rate_limit(request)
    require_feature("video")
    if agree != "true":
        raise HTTPException(status_code=400, detail="请确认只处理您有权保存的内容")
    lines = [line.strip() for line in urls.splitlines() if line.strip()]
    if not lines:
        raise HTTPException(status_code=400, detail="请至少输入一个链接")
    if len(lines) > 5:
        raise HTTPException(status_code=400, detail="一次最多处理 5 个链接")
    quality = validate_video_quality(quality)
    clean_urls = [legal_url(line) for line in lines]
    require_user(request)
    check_usage_limit(request, "video_batch", len(clean_urls))
    credit = charge_points(request, "video_batch", len(clean_urls))
    created = []
    for clean in clean_urls:
        task_id = uuid.uuid4().hex
        tasks[task_id] = {
            "type": "video",
            "status": "queued",
            "message": "任务已排队",
            "progress": 0,
            "quality": quality,
            "url": clean,
            "credit_user_id": credit["user"]["id"],
            "credit_cost": credit["unit_cost"],
            "credit_label": credit["rule"].get("label"),
            "created_at": now(),
        }
        asyncio.create_task(run_video_download(task_id, clean))
        created.append(public_task(task_id))
    return {"tasks": created}


@app.post("/api/video/cover-info")
async def cover_info(request: Request, url: str = Form(...), agree: str = Form("false")) -> dict[str, Any]:
    check_rate_limit(request)
    require_feature("cover")
    if agree != "true":
        raise HTTPException(status_code=400, detail="请确认只提取您有权保存的内容")
    clean = legal_url(url)
    check_usage_limit(request, "cover_info")
    try:
        info = await asyncio.to_thread(ydl_info, clean)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"解析失败：{str(exc)[:180]}")
    thumbnail = info.get("thumbnail")
    if not thumbnail:
        thumbnails = info.get("thumbnails") or []
        thumbnail = (thumbnails[-1] or {}).get("url") if thumbnails else None
    return {
        "title": info.get("title") or "未命名视频",
        "thumbnail": thumbnail,
        "duration": info.get("duration"),
        "uploader": info.get("uploader"),
        "webpage_url": info.get("webpage_url") or clean,
    }


@app.post("/api/video/cover-download")
async def cover_download(request: Request, thumbnail: str = Form(...), title: str = Form("cover")):
    check_rate_limit(request)
    require_feature("cover")
    clean = legal_url(thumbnail)
    check_usage_limit(request, "cover_download")
    credit = charge_points(request, "cover_download")
    task_id = uuid.uuid4().hex
    output = TMP_DIR / f"{task_id}-{safe_file_part(title, 'cover')}.jpg"
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(clean)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "image/jpeg").split(";")[0]
            if not content_type.startswith("image/"):
                raise HTTPException(status_code=400, detail="封面地址没有返回图片")
            suffix = ".png" if "png" in content_type else ".webp" if "webp" in content_type else ".jpg"
            output = output.with_suffix(suffix)
            output.write_bytes(response.content)
    except HTTPException:
        refund_points(credit["user"]["id"], credit["cost"], "封面提取失败")
        raise
    except Exception as exc:
        output.unlink(missing_ok=True)
        refund_points(credit["user"]["id"], credit["cost"], "封面提取失败")
        raise HTTPException(status_code=502, detail=f"封面下载失败：{str(exc)[:160]}")
    return FileResponse(
        output,
        filename=output.name,
        media_type="application/octet-stream",
        background=BackgroundTask(remove_file, output),
    )


@app.get("/api/tasks/{task_id}")
async def task_status(task_id: str) -> dict[str, Any]:
    return public_task(task_id)


@app.get("/api/files/{task_id}")
async def download_file(task_id: str):
    task = tasks.get(task_id)
    if not task or task.get("status") != "done" or not task.get("file"):
        raise HTTPException(status_code=404, detail="文件不存在或任务未完成")
    path = Path(task["file"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件已过期")
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/octet-stream",
        background=BackgroundTask(remove_download_task, task_id, path),
    )


@app.post("/api/image/cleanup")
async def image_cleanup(
    request: Request,
    image: UploadFile = File(...),
    mask: UploadFile = File(...),
    agree: str = Form("false"),
):
    check_rate_limit(request)
    require_feature("image")
    if agree != "true":
        raise HTTPException(status_code=400, detail="请确认只处理您拥有版权或授权的图片")

    image_bytes = await image.read()
    mask_bytes = await mask.read()
    if len(image_bytes) > MAX_IMAGE_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"图片不能超过 {MAX_IMAGE_MB}MB")

    check_usage_limit(request, "image_cleanup")
    credit = charge_points(request, "image_cleanup")
    task_id = uuid.uuid4().hex
    output = IMAGE_DIR / f"{task_id}.png"

    try:
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(
                f"{IOPAINT_URL}/api/v1/inpaint",
                json={
                    "image": base64.b64encode(image_bytes).decode("ascii"),
                    "mask": base64.b64encode(mask_bytes).decode("ascii"),
                    "ldm_steps": 20,
                    "hd_strategy": "Crop",
                    "hd_strategy_crop_trigger_size": 800,
                    "hd_strategy_crop_margin": 128,
                },
            )
    except httpx.HTTPError as exc:
        refund_points(credit["user"]["id"], credit["cost"], "AI 图片修复失败")
        raise HTTPException(status_code=502, detail=f"AI 引擎暂时不可用：{exc}")

    if response.status_code >= 400:
        refund_points(credit["user"]["id"], credit["cost"], "AI 图片修复失败")
        raise HTTPException(status_code=502, detail=f"AI 引擎处理失败：{response.text[:180]}")

    output.write_bytes(response.content)
    return Response(content=response.content, media_type=response.headers.get("content-type", "image/png"))


def ai_remove_background_bytes(
    image_bytes: bytes,
    width: int | None = None,
    height: int | None = None,
    keep_ratio: bool = True,
    output_format: str = "png",
) -> tuple[bytes, str]:
    from PIL import Image, ImageOps
    from rembg import remove

    with Image.open(BytesIO(image_bytes)) as opened:
        source = ImageOps.exif_transpose(opened)
        source.load()
        if max(source.size) > 6000:
            source.thumbnail((6000, 6000), Image.Resampling.LANCZOS)
        result = remove(source).convert("RGBA")

    requested_width = max(0, min(int(width or 0), 8000))
    requested_height = max(0, min(int(height or 0), 8000))
    if requested_width or requested_height:
        if keep_ratio:
            ratio = result.width / result.height
            if requested_width and not requested_height:
                requested_height = max(1, round(requested_width / ratio))
            elif requested_height and not requested_width:
                requested_width = max(1, round(requested_height * ratio))
        requested_width = requested_width or result.width
        requested_height = requested_height or result.height
        result = result.resize((requested_width, requested_height), Image.Resampling.LANCZOS)

    output = BytesIO()
    normalized_format = "webp" if output_format.lower() == "webp" else "png"
    if normalized_format == "webp":
        result.save(output, "WEBP", lossless=True, quality=95, method=6)
        return output.getvalue(), "image/webp"
    result.save(output, "PNG", optimize=True, compress_level=9)
    return output.getvalue(), "image/png"


@app.post("/api/image/remove-background")
async def image_remove_background(
    request: Request,
    image: UploadFile = File(...),
    width: int | None = Form(default=None),
    height: int | None = Form(default=None),
    keep_ratio: str = Form("true"),
    output_format: str = Form("png"),
):
    check_rate_limit(request)
    require_feature("image")

    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="请先上传图片")
    if len(image_bytes) > MAX_IMAGE_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"图片不能超过 {MAX_IMAGE_MB}MB")

    try:
        from PIL import Image

        with Image.open(BytesIO(image_bytes)) as opened:
            opened.verify()
    except Exception:
        raise HTTPException(status_code=400, detail="图片格式无法识别，请换一张 JPG、PNG 或 WebP")

    try:
        content, media_type = await asyncio.to_thread(
            ai_remove_background_bytes,
            image_bytes,
            width,
            height,
            keep_ratio.lower() in {"1", "true", "yes", "on"},
            output_format,
        )
    except ImportError:
        raise HTTPException(status_code=500, detail="AI 抠图模型未安装，请先安装 rembg 和 onnxruntime")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI 抠图失败：{str(exc)[:180]}")

    return Response(content=content, media_type=media_type)


@app.post("/api/image/opencv-inpaint")
async def image_opencv_inpaint(
    request: Request,
    image: UploadFile = File(...),
    mask: UploadFile = File(...),
    agree: str = Form("false"),
    radius: int = Form(3),
    algorithm: str = Form("telea"),
):
    check_rate_limit(request)
    require_feature("image")
    if agree != "true":
        raise HTTPException(status_code=400, detail="请确认只处理您拥有版权或授权的图片")

    try:
        import cv2
        import numpy as np
    except ImportError:
        raise HTTPException(status_code=500, detail="OpenCV 组件未安装，暂时无法使用快速清除")

    image_bytes = await image.read()
    mask_bytes = await mask.read()
    if len(image_bytes) > MAX_IMAGE_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"图片不能超过 {MAX_IMAGE_MB}MB")

    image_array = np.frombuffer(image_bytes, dtype=np.uint8)
    source = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
    if source is None:
        raise HTTPException(status_code=400, detail="图片读取失败，请换一张图片试试")

    mask_array = np.frombuffer(mask_bytes, dtype=np.uint8)
    mask_image = cv2.imdecode(mask_array, cv2.IMREAD_GRAYSCALE)
    if mask_image is None:
        raise HTTPException(status_code=400, detail="涂抹区域读取失败，请重新标记")
    if mask_image.shape[:2] != source.shape[:2]:
        mask_image = cv2.resize(mask_image, (source.shape[1], source.shape[0]), interpolation=cv2.INTER_NEAREST)

    _, binary_mask = cv2.threshold(mask_image, 127, 255, cv2.THRESH_BINARY)
    if int(cv2.countNonZero(binary_mask)) == 0:
        raise HTTPException(status_code=400, detail="请先涂抹需要清除的水印区域")

    radius = max(1, min(int(radius or 3), 12))
    kernel = np.ones((3, 3), np.uint8)
    binary_mask = cv2.dilate(binary_mask, kernel, iterations=1)
    method = cv2.INPAINT_NS if algorithm.lower() == "ns" else cv2.INPAINT_TELEA

    check_usage_limit(request, "image_cleanup")
    credit = charge_points(request, "image_cleanup")
    try:
        output_image = cv2.inpaint(source, binary_mask, radius, method)
        ok, encoded = cv2.imencode(".png", output_image)
        if not ok:
            raise RuntimeError("OpenCV 编码失败")
    except Exception as exc:
        refund_points(credit["user"]["id"], credit["cost"], "OpenCV 图片修复失败")
        raise HTTPException(status_code=500, detail=f"OpenCV 处理失败：{exc}")

    content = encoded.tobytes()
    task_id = uuid.uuid4().hex
    (IMAGE_DIR / f"{task_id}.png").write_bytes(content)
    return Response(content=content, media_type="image/png")


@app.post("/api/media/compress")
async def media_compress(
    request: Request,
    file: UploadFile = File(...),
    mode: str = Form("balanced"),
    agree: str = Form("false"),
):
    check_rate_limit(request)
    require_feature("compress")
    if agree != "true":
        raise HTTPException(status_code=400, detail="请确认只压缩自己有权处理的文件")
    if mode not in {"clear", "balanced", "small"}:
        raise HTTPException(status_code=400, detail="不支持的压缩模式")

    original_name = safe_file_part(file.filename or "media")
    suffix = Path(original_name).suffix.lower()
    image_suffixes = {".jpg", ".jpeg", ".png", ".webp"}
    video_suffixes = {".mp4", ".mov"}
    if suffix not in image_suffixes | video_suffixes:
        raise HTTPException(status_code=400, detail="仅支持 JPG、PNG、WebP、MP4、MOV")

    limit_mb = MAX_IMAGE_MB if suffix in image_suffixes else MAX_VIDEO_FILE_MB
    task_id = uuid.uuid4().hex
    task_dir = COMPRESS_DIR / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    input_path = task_dir / f"source{suffix}"

    original_size = 0
    credit: dict[str, Any] | None = None
    try:
        with input_path.open("wb") as handle:
            while chunk := await file.read(1024 * 1024):
                original_size += len(chunk)
                if original_size > limit_mb * 1024 * 1024:
                    raise HTTPException(status_code=413, detail=f"文件不能超过 {limit_mb}MB")
                handle.write(chunk)

        check_usage_limit(request, "media_compress")
        credit = charge_points(request, "media_compress")
        stem = safe_file_part(Path(original_name).stem, "compressed")
        if suffix in image_suffixes:
            output_suffix = ".jpg" if suffix == ".jpeg" else suffix
            output_path = task_dir / f"{stem}-compressed{output_suffix}"
            await asyncio.to_thread(compress_image_file, input_path, output_path, mode)
        else:
            output_path = task_dir / f"{stem}-compressed.mp4"
            await compress_video_file(input_path, output_path, mode)
    except HTTPException:
        remove_directory(task_dir)
        if credit:
            refund_points(credit["user"]["id"], credit["cost"], "媒体压缩失败")
        raise
    except Exception as exc:
        remove_directory(task_dir)
        if credit:
            refund_points(credit["user"]["id"], credit["cost"], "媒体压缩失败")
        log_event("error", "媒体压缩失败", filename=original_name, error=str(exc)[:240])
        raise HTTPException(status_code=500, detail=f"压缩失败：{str(exc)[:180]}")

    compressed_size = output_path.stat().st_size if output_path.exists() else 0
    log_event(
        "info",
        "媒体压缩完成",
        filename=original_name,
        original=readable_size(original_size),
        compressed=readable_size(compressed_size),
        mode=mode,
    )
    return FileResponse(
        output_path,
        filename=output_path.name,
        media_type="application/octet-stream",
        headers={
            "x-original-size": str(original_size),
            "x-compressed-size": str(compressed_size),
            "x-output-name": output_path.name,
        },
        background=BackgroundTask(remove_directory, task_dir),
    )


@app.post("/api/office/convert")
async def office_convert(
    request: Request,
    files: list[UploadFile] = File(...),
    mode: str = Form("pdf-to-docx"),
    agree: str = Form("false"),
):
    check_rate_limit(request)
    require_feature("office")
    if agree != "true":
        raise HTTPException(status_code=400, detail="请确认只转换自己有权处理的文件")
    if mode not in {"pdf-to-docx", "pdf-to-long-image", "images-to-pdf"}:
        raise HTTPException(status_code=400, detail="不支持的转换方式")
    if not files:
        raise HTTPException(status_code=400, detail="请上传文件")

    task_id = uuid.uuid4().hex
    task_dir = OFFICE_DIR / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    input_paths: list[Path] = []
    total_size = 0
    credit: dict[str, Any] | None = None

    try:
        if mode in {"pdf-to-docx", "pdf-to-long-image"}:
            upload = files[0]
            suffix = Path(upload.filename or "").suffix.lower()
            if suffix != ".pdf":
                raise HTTPException(status_code=400, detail="请上传 PDF 文件")
            input_path = task_dir / "source.pdf"
            total_size = await save_upload(upload, input_path, MAX_OFFICE_FILE_MB)
            input_paths.append(input_path)
            check_usage_limit(request, "office_convert")
            credit = charge_points(request, "office_convert")
            if mode == "pdf-to-docx":
                output_path = task_dir / "meetseek-converted.docx"
                await asyncio.to_thread(pdf_to_docx, input_path, output_path)
            else:
                output_path = task_dir / "meetseek-long-image.png"
                await asyncio.to_thread(pdf_to_long_image, input_path, output_path)
        else:
            allowed = {".jpg", ".jpeg", ".png", ".webp"}
            if len(files) > 20:
                raise HTTPException(status_code=400, detail="一次最多合并 20 张图片")
            for index, upload in enumerate(files, start=1):
                suffix = Path(upload.filename or "").suffix.lower()
                if suffix not in allowed:
                    raise HTTPException(status_code=400, detail="图片转 PDF 仅支持 JPG、PNG、WebP")
                input_path = task_dir / f"image-{index}{'.jpg' if suffix == '.jpeg' else suffix}"
                total_size += await save_upload(upload, input_path, MAX_OFFICE_FILE_MB)
                if total_size > MAX_OFFICE_FILE_MB * 1024 * 1024:
                    raise HTTPException(status_code=413, detail=f"文件总大小不能超过 {MAX_OFFICE_FILE_MB}MB")
                input_paths.append(input_path)
            check_usage_limit(request, "office_convert")
            credit = charge_points(request, "office_convert")
            output_path = task_dir / "meetseek-images.pdf"
            await asyncio.to_thread(images_to_pdf, input_paths, output_path)
    except HTTPException:
        remove_directory(task_dir)
        if credit:
            refund_points(credit["user"]["id"], credit["cost"], "办公转换失败")
        raise
    except Exception as exc:
        remove_directory(task_dir)
        if credit:
            refund_points(credit["user"]["id"], credit["cost"], "办公转换失败")
        log_event("error", "办公转换失败", mode=mode, error=str(exc)[:240])
        raise HTTPException(status_code=500, detail=f"转换失败：{str(exc)[:180]}")

    output_size = output_path.stat().st_size if output_path.exists() else 0
    log_event("info", "办公转换完成", mode=mode, size=readable_size(output_size))
    return FileResponse(
        output_path,
        filename=output_path.name,
        media_type="application/octet-stream",
        headers={
            "x-original-size": str(total_size),
            "x-output-size": str(output_size),
            "x-output-name": output_path.name,
        },
        background=BackgroundTask(remove_directory, task_dir),
    )


@app.post("/api/copy/rewrite")
async def copy_rewrite(request: Request, text: str = Form(...), style: str = Form("xiaohongshu"), agree: str = Form("false")) -> dict[str, str]:
    check_rate_limit(request)
    require_feature("copy")
    if agree != "true":
        raise HTTPException(status_code=400, detail="请确认只转换自己有权处理的文案")
    if style not in {"xiaohongshu", "zhihu"}:
        raise HTTPException(status_code=400, detail="不支持的文案风格")
    if len(text.strip()) < 5:
        raise HTTPException(status_code=400, detail="请输入至少 5 个字")
    if len(text) > 4000:
        raise HTTPException(status_code=400, detail="文案不能超过 4000 字")
    check_usage_limit(request, "copy_rewrite")
    credit = charge_points(request, "copy_rewrite")
    try:
        result = await ai_rewrite(text, style)
    except Exception:
        refund_points(credit["user"]["id"], credit["cost"], "文案转换失败")
        raise
    log_event("info", "文案风格转换完成", style=style, provider=result["provider"])
    return result


@app.post("/api/prompt/image")
async def prompt_from_image(request: Request, image: UploadFile = File(...), agree: str = Form("false")) -> dict[str, str]:
    check_rate_limit(request)
    require_feature("prompt")
    user = require_user(request)
    if agree != "true":
        raise HTTPException(status_code=400, detail="请确认只分析自己有权处理的图片")
    if not (image.content_type or "").startswith("image/"):
        raise HTTPException(status_code=400, detail="请上传图片文件")
    content = await image.read()
    if not content:
        raise HTTPException(status_code=400, detail="图片不能为空")
    if len(content) > MAX_IMAGE_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"图片不能超过 {MAX_IMAGE_MB}MB")
    check_usage_limit(request, "image_prompt_reverse")
    credit = charge_points(request, "image_prompt_reverse")
    try:
        result = await ai_image_prompt(image, content)
    except Exception:
        refund_points(credit["user"]["id"], credit["cost"], "图片反推提示词失败")
        raise
    log_event("info", "图片提示词生成完成", provider=result["provider"], size=readable_size(len(content)), user=user["email"])
    return result


@app.post("/api/prompt/translate")
async def prompt_translate(request: Request, text: str = Form(...), target: str = Form("en"), use_api: str = Form("true")) -> dict[str, Any]:
    check_rate_limit(request)
    require_feature("prompt")
    user = require_user(request)
    clean = text.strip()
    if target not in {"zh", "en"}:
        raise HTTPException(status_code=400, detail="目标语言只能是 zh 或 en")
    if len(clean) < 3:
        raise HTTPException(status_code=400, detail="请输入需要翻译/补全的提示词")
    if len(clean) > 4000:
        raise HTTPException(status_code=400, detail="提示词不能超过 4000 字")
    check_usage_limit(request, "prompt_translate")
    credit = charge_points(request, "prompt_translate")
    engine = prompt_engine_config("prompt_translate")
    instruction = (
        "请把用户提供的 AI 绘图提示词翻译并补全为英文 Prompt。保留原意，补充主体、场景、构图、镜头、光线、色彩、材质、风格、画质关键词。只输出英文提示词。"
        if target == "en"
        else "请把用户提供的 AI image prompt 翻译并补全为中文提示词。保留原意，补充主体、场景、构图、镜头、光线、色彩、材质、风格、画质关键词。只输出中文提示词。"
    )
    use_backend_api = use_api == "true" and bool(engine.get("api_key"))
    if use_api == "true" and not engine.get("api_key"):
        log_event("info", "提示词翻译 API Key 未配置，已使用本地兜底", user=user["email"])
    if not use_backend_api:
        output = fallback_translate_prompt(clean, target)
        provider = "local-fallback"
    else:
        try:
            output = await prompt_chat_completion(engine, [
                {"role": "system", "content": f"{engine.get('skill') or DEFAULT_TRANSLATE_SKILL}\n\n{instruction}"},
                {"role": "user", "content": clean},
            ])
            provider = engine["provider"]
        except Exception as exc:
            log_event("error", "提示词翻译失败，已使用兜底", error=str(exc)[:180], user=user["email"])
            output = fallback_translate_prompt(clean, target)
            provider = "local-fallback"
    return {"text": output, "target": target, "provider": provider, "credit_cost": credit["cost"]}


@app.post("/api/posts")
async def create_post(
    request: Request,
    title: str = Form(...),
    content_html: str = Form(""),
    post_type: str = Form("short"),
    category_slug: str = Form("ai-tools"),
    summary: str = Form(""),
    cover_image: str = Form(""),
    source_url: str = Form(""),
    status: str = Form("published"),
    visibility: str = Form("public"),
) -> dict[str, Any]:
    user = require_user(request)
    ensure_user_can_post(user)
    with db() as conn:
        row = save_post_record(
            conn,
            author_id=user["id"],
            title=title,
            content_html=content_html,
            post_type=post_type,
            category_slug=category_slug,
            summary=summary,
            cover_image=cover_image,
            source_url=source_url,
            status=status,
            visibility=visibility,
        )
    post = public_post(row)
    post_html = render_home_feed_card(
        home_feed_item_from_post(
            post,
            author_name=str(user.get("name") or "我"),
            author_avatar_url=str(user.get("avatar_url") or ""),
            current_user=user,
            is_admin=is_site_admin(request, user),
        ),
        current_user=user,
        is_admin=is_site_admin(request, user),
    )
    log_event("info", "帖子已保存", user=user["email"], post_id=post["id"], slug=post["slug"])
    return {"post": post, "html": post_html}


def public_comment(row: sqlite3.Row) -> dict[str, Any]:
    display_name = str((row["nickname"] if "nickname" in row.keys() and row["nickname"] else "") or row["name"] or "用户")
    return {
        "id": int(row["id"]),
        "content": str(row["content"] or ""),
        "target_id": int(row["target_id"]),
        "target_type": str(row["target_type"]),
        "created_at": int(row["created_at"] or 0),
        "author": {
            "name": display_name,
            "avatar_url": str(row["avatar_url"] or ""),
        },
    }


@app.get("/api/comments/{target_type}/{target_id}")
async def get_comments(target_type: str, target_id: int) -> dict[str, Any]:
    if target_type not in {"post", "prompt"} or target_id <= 0:
        raise HTTPException(status_code=400, detail="评论目标不正确")
    with db() as conn:
        rows = conn.execute(
            """
            SELECT comments.*, users.name, users.nickname, users.avatar_url
            FROM comments
            JOIN users ON users.id = comments.user_id
            WHERE comments.target_type = ? AND comments.target_id = ?
            ORDER BY comments.created_at DESC, comments.id DESC
            LIMIT 100
            """,
            (target_type, target_id),
        ).fetchall()
    return {"comments": [public_comment(row) for row in rows]}


@app.post("/api/comments")
async def create_comment(
    request: Request,
    target_type: str = Form(...),
    target_id: int = Form(...),
    content: str = Form(...),
) -> dict[str, Any]:
    check_rate_limit(request)
    user = require_user(request)
    ensure_user_can_comment(user)
    clean_target_type = target_type.strip().lower()
    if clean_target_type not in {"post", "prompt"} or target_id <= 0:
        raise HTTPException(status_code=400, detail="评论目标不正确")
    clean_content = bleach.clean(str(content or ""), tags=[], attributes={}, strip=True)
    clean_content = re.sub(r"\s+", " ", html.unescape(clean_content)).strip()[:1000]
    if not clean_content:
        raise HTTPException(status_code=400, detail="请输入评论内容")
    created_at = int(now())
    with db() as conn:
        if clean_target_type == "post":
            target = conn.execute(
                "SELECT id FROM posts WHERE id = ? AND status = 'published' AND visibility = 'public'",
                (target_id,),
            ).fetchone()
        else:
            target = conn.execute(
                "SELECT id FROM prompts WHERE id = ? AND hidden = 0",
                (target_id,),
            ).fetchone()
        if not target:
            raise HTTPException(status_code=404, detail="评论目标不存在")
        cursor = conn.execute(
            """
            INSERT INTO comments(content, user_id, target_id, target_type, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (clean_content, user["id"], target_id, clean_target_type, created_at),
        )
        if clean_target_type == "post":
            conn.execute("UPDATE posts SET comment_count = comment_count + 1, updated_at = ? WHERE id = ?", (created_at, target_id))
        row = conn.execute(
            """
            SELECT comments.*, users.name, users.nickname, users.avatar_url
            FROM comments
            JOIN users ON users.id = comments.user_id
            WHERE comments.id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()
    log_event("info", "评论已发布", user=user["name"], target_type=clean_target_type, target_id=target_id)
    return {"comment": public_comment(row)}


def toggle_post_reaction(conn: sqlite3.Connection, user_id: int, post_id: int, kind: str) -> dict[str, Any]:
    if kind not in {"like", "bookmark"}:
        raise HTTPException(status_code=400, detail="操作类型不正确")
    post = conn.execute(
        "SELECT id, author_id FROM posts WHERE id = ? AND status = 'published' AND visibility = 'public'",
        (post_id,),
    ).fetchone()
    if not post:
        raise HTTPException(status_code=404, detail="帖子不存在")
    existing = conn.execute(
        "SELECT id FROM post_reactions WHERE user_id = ? AND post_id = ? AND kind = ?",
        (user_id, post_id, kind),
    ).fetchone()
    count_column = "like_count" if kind == "like" else "bookmark_count"
    if existing:
        conn.execute("DELETE FROM post_reactions WHERE id = ?", (existing["id"],))
        conn.execute(f"UPDATE posts SET {count_column} = MAX(0, {count_column} - 1), updated_at = ? WHERE id = ?", (int(now()), post_id))
        if kind == "like":
            conn.execute("UPDATE users SET points = MAX(0, points - 1) WHERE id = ?", (post["author_id"],))
        active = False
    else:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO post_reactions(user_id, post_id, kind, created_at) VALUES (?, ?, ?, ?)",
            (user_id, post_id, kind, int(now())),
        )
        if cursor.rowcount:
            conn.execute(f"UPDATE posts SET {count_column} = {count_column} + 1, updated_at = ? WHERE id = ?", (int(now()), post_id))
            if kind == "like":
                conn.execute("UPDATE users SET points = points + 1 WHERE id = ?", (post["author_id"],))
        active = True
    updated = conn.execute(f"SELECT {count_column} AS count FROM posts WHERE id = ?", (post_id,)).fetchone()
    return {"active": active, "count": int(updated["count"] or 0)}


@app.post("/api/posts/{post_id}/toggle_like")
async def toggle_post_like(request: Request, post_id: int) -> dict[str, Any]:
    check_rate_limit(request)
    user = require_user(request)
    with db() as conn:
        result = toggle_post_reaction(conn, user["id"], post_id, "like")
    return result


@app.post("/api/posts/{post_id}/toggle_bookmark")
async def toggle_post_bookmark(request: Request, post_id: int) -> dict[str, Any]:
    check_rate_limit(request)
    user = require_user(request)
    with db() as conn:
        result = toggle_post_reaction(conn, user["id"], post_id, "bookmark")
    return result


@app.post("/api/posts/{post_id}/action")
async def post_action(request: Request, post_id: int, payload: PostActionPayload) -> dict[str, str]:
    check_rate_limit(request)
    user = require_user(request)
    action = payload.action.strip().lower()
    allowed = {
        "hide", "delete", "pin", "private", "report", "recommend", "unrecommend",
        "not_interested", "block_author", "violation", "ban_author",
    }
    if action not in allowed:
        raise HTTPException(status_code=400, detail="未知操作")
    timestamp = int(now())
    with db() as conn:
        post = conn.execute(
            "SELECT id, author_id, status, visibility FROM posts WHERE id = ?",
            (post_id,),
        ).fetchone()
        if not post:
            raise HTTPException(status_code=404, detail="帖子不存在")
        is_admin = is_site_admin(request, user)
        is_author = int(post["author_id"]) == int(user["id"])

        if action in {"delete", "pin", "private"} and not (is_admin or is_author):
            raise HTTPException(status_code=403, detail="没有权限操作该内容")
        if action in {"recommend", "unrecommend", "violation", "ban_author"} and not is_admin:
            raise HTTPException(status_code=403, detail="需要管理员权限")

        message = "操作成功"
        if action == "delete":
            conn.execute("UPDATE posts SET status = 'hidden', updated_at = ? WHERE id = ?", (timestamp, post_id))
            message = "内容已删除"
        elif action == "pin":
            conn.execute("UPDATE posts SET pinned_at = ?, updated_at = ? WHERE id = ?", (timestamp, timestamp, post_id))
            message = "内容已置顶"
        elif action == "private":
            conn.execute(
                "UPDATE posts SET visibility = 'private', canonical_url = '', updated_at = ? WHERE id = ?",
                (timestamp, post_id),
            )
            message = "已设为仅自己可见"
        elif action == "recommend":
            conn.execute("UPDATE posts SET recommended_at = ?, updated_at = ? WHERE id = ?", (timestamp, timestamp, post_id))
            message = "已推荐到首页"
        elif action == "unrecommend":
            conn.execute("UPDATE posts SET recommended_at = 0, updated_at = ? WHERE id = ?", (timestamp, post_id))
            message = "已取消推荐"
        elif action == "hide":
            if is_admin:
                conn.execute("UPDATE posts SET status = 'hidden', updated_at = ? WHERE id = ?", (timestamp, post_id))
                message = "内容已隐藏"
            else:
                conn.execute(
                    "INSERT OR IGNORE INTO user_post_preferences(user_id, post_id, kind, created_at) VALUES (?, ?, 'hidden', ?)",
                    (user["id"], post_id, timestamp),
                )
                message = "已隐藏这条内容"
        elif action == "not_interested":
            conn.execute(
                "INSERT OR IGNORE INTO user_post_preferences(user_id, post_id, kind, created_at) VALUES (?, ?, 'not_interested', ?)",
                (user["id"], post_id, timestamp),
            )
            message = "已减少类似内容推荐"
        elif action == "block_author":
            if int(post["author_id"]) == int(user["id"]):
                raise HTTPException(status_code=400, detail="不能屏蔽自己")
            conn.execute(
                "INSERT OR IGNORE INTO user_blocks(user_id, author_id, created_at) VALUES (?, ?, ?)",
                (user["id"], post["author_id"], timestamp),
            )
            message = "已屏蔽该作者"
        elif action == "report":
            conn.execute(
                "INSERT OR IGNORE INTO post_reports(user_id, post_id, reason, created_at) VALUES (?, ?, '用户举报', ?)",
                (user["id"], post_id, timestamp),
            )
            message = "已收到举报"
        elif action == "violation":
            conn.execute(
                "INSERT OR IGNORE INTO post_reports(user_id, post_id, reason, created_at) VALUES (?, ?, '管理员标记违规', ?)",
                (user["id"], post_id, timestamp),
            )
            conn.execute("UPDATE posts SET status = 'hidden', updated_at = ? WHERE id = ?", (timestamp, post_id))
            message = "已标记为违规"
        elif action == "ban_author":
            if int(post["author_id"]) == int(user["id"]):
                raise HTTPException(status_code=400, detail="不能封禁自己")
            conn.execute("UPDATE users SET disabled = 1 WHERE id = ?", (post["author_id"],))
            conn.execute("UPDATE posts SET status = 'hidden', updated_at = ? WHERE author_id = ?", (timestamp, post["author_id"]))
            message = "作者已封禁"
    return {"status": "success", "message": message}


@app.post("/api/users/{author_id}/toggle_follow")
async def toggle_follow_author(request: Request, author_id: int) -> dict[str, Any]:
    check_rate_limit(request)
    user = require_user(request)
    if int(user["id"]) == int(author_id):
        raise HTTPException(status_code=400, detail="不能关注自己")
    timestamp = int(now())
    with db() as conn:
        author = conn.execute(
            "SELECT id FROM users WHERE id = ? AND disabled = 0 AND deleted_at = 0",
            (author_id,),
        ).fetchone()
        if not author:
            raise HTTPException(status_code=404, detail="作者不存在")
        existing = conn.execute(
            "SELECT id FROM user_follows WHERE follower_id = ? AND author_id = ?",
            (user["id"], author_id),
        ).fetchone()
        if existing:
            conn.execute("DELETE FROM user_follows WHERE id = ?", (existing["id"],))
            following = False
            message = "已取消关注"
        else:
            conn.execute(
                "INSERT OR IGNORE INTO user_follows(follower_id, author_id, created_at) VALUES (?, ?, ?)",
                (user["id"], author_id, timestamp),
            )
            following = True
            message = "已关注"
    return {"status": "success", "message": message, "following": following}


@app.post("/api/posts/editor-image")
async def upload_editor_image(request: Request, image: UploadFile = File(...)) -> dict[str, Any]:
    check_rate_limit(request)
    require_user(request)
    url = await save_prompt_gallery_image(image, "post-editor")
    return {"success": 1, "file": {"url": url}}


@app.post("/api/posts/media")
async def upload_post_media(request: Request, kind: str = Form(...), file: UploadFile = File(...)) -> dict[str, Any]:
    check_rate_limit(request)
    require_user(request)
    media = await save_post_media_file(file, kind)
    return {"media": media}


@app.get("/api/posts/link-preview")
async def post_link_preview(request: Request, url: str) -> dict[str, Any]:
    check_rate_limit(request)
    clean = legal_url(url)
    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True, headers=LINK_PREVIEW_HEADERS) as client:
            response = await client.get(clean)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"链接预览抓取失败：{str(exc)[:120]}")
    preview = parse_link_preview_html(response.text, clean)
    return {
        "success": 1,
        "meta": {
            "title": preview["title"],
            "description": preview["description"],
            "image": {"url": preview["image"]},
            "site_name": preview["domain"],
        },
    }


@app.get("/editor/posts/{post_id}", response_class=HTMLResponse)
async def edit_post_page(request: Request, post_id: int) -> str:
    user = require_user(request)
    with db() as conn:
        row = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="帖子不存在")
    if int(row["author_id"]) != int(user["id"]) and not is_site_admin(request, user):
        raise HTTPException(status_code=403, detail="没有权限编辑")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>编辑内容 - meetseek</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="min-h-screen bg-[#f8fafc] text-slate-950">
  <main class="mx-auto max-w-3xl px-5 py-10">
    <a class="text-sm font-black text-slate-400 hover:text-slate-700" href="{html_escape(row["canonical_url"] or "/")}">← 返回内容</a>
    <section class="mt-5 rounded-3xl border border-slate-100 bg-white p-6 shadow-sm">
      <h1 class="text-2xl font-black">编辑内容</h1>
      <form id="edit-post-form" class="mt-6 grid gap-4">
        <input id="edit-title" class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-lg font-black outline-none focus:border-orange-300" value="{html_escape(row["title"])}" placeholder="标题">
        <textarea id="edit-content" class="min-h-72 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm leading-7 outline-none focus:border-orange-300" placeholder="正文">{html_escape(row["content_html"])}</textarea>
        <div class="flex items-center justify-between gap-3">
          <p id="edit-status" class="text-sm font-bold text-slate-400"></p>
          <button class="rounded-full bg-orange-600 px-7 py-3 text-sm font-black text-white hover:bg-orange-700" type="submit">保存</button>
        </div>
      </form>
    </section>
  </main>
  <script>
    document.getElementById("edit-post-form").addEventListener("submit", async (event) => {{
      event.preventDefault();
      const status = document.getElementById("edit-status");
      const data = new FormData();
      data.append("title", document.getElementById("edit-title").value);
      data.append("content_html", document.getElementById("edit-content").value);
      data.append("summary", document.getElementById("edit-content").value.replace(/\\s+/g, " ").slice(0, 160));
      data.append("post_type", "{html_escape(row["type"])}");
      data.append("category_slug", "{html_escape(row["category_slug"])}");
      data.append("status", "{html_escape(row["status"])}");
      data.append("visibility", "{html_escape(row["visibility"])}");
      const response = await fetch("/api/posts/{int(row["id"])}", {{ method: "PATCH", body: data }});
      const payload = await response.json().catch(() => ({{}}));
      if (!response.ok) {{
        status.textContent = payload.detail || "保存失败";
        status.className = "text-sm font-bold text-rose-600";
        return;
      }}
      window.location.href = payload.post.canonical_url || "/";
    }});
  </script>
</body>
</html>"""


@app.patch("/api/posts/{post_id}")
async def update_post(
    post_id: int,
    request: Request,
    title: str = Form(...),
    content_html: str = Form(""),
    post_type: str = Form("short"),
    category_slug: str = Form("ai-tools"),
    summary: str = Form(""),
    cover_image: str = Form(""),
    source_url: str = Form(""),
    status: str = Form("published"),
    visibility: str = Form("public"),
) -> dict[str, Any]:
    user = require_user(request)
    ensure_user_can_post(user)
    with db() as conn:
        existing = conn.execute("SELECT id FROM posts WHERE id = ? AND author_id = ?", (post_id, user["id"])).fetchone()
        if not existing and not valid_admin_session(request):
            raise HTTPException(status_code=404, detail="帖子不存在或无权修改")
        author_id = user["id"]
        if not existing:
            owner = conn.execute("SELECT author_id FROM posts WHERE id = ?", (post_id,)).fetchone()
            if not owner:
                raise HTTPException(status_code=404, detail="帖子不存在")
            author_id = owner["author_id"]
        row = save_post_record(
            conn,
            author_id=author_id,
            post_id=post_id,
            title=title,
            content_html=content_html,
            post_type=post_type,
            category_slug=category_slug,
            summary=summary,
            cover_image=cover_image,
            source_url=source_url,
            status=status,
            visibility=visibility,
        )
    post = public_post(row)
    log_event("info", "帖子已更新", user=user["email"], post_id=post["id"], slug=post["slug"])
    return {"post": post}


@app.post("/api/cleanup")
async def manual_cleanup() -> dict[str, int]:
    return cleanup_old_files()


def require_admin(x_admin_token: str | None = None, request: Request | None = None) -> None:
    request = request or current_request_var.get()
    if valid_any_admin_session(request):
        return
    if not ADMIN_TOKEN or x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="需要管理员 token")


def directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.glob("**/*") if item.is_file())


@app.get("/api/admin/status")
async def admin_status(x_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    require_admin(x_admin_token)
    return {
        "tasks": [public_task(task_id) for task_id in list(tasks.keys())[:50]],
        "disk": {
            "downloads": readable_size(directory_size(DOWNLOAD_DIR)),
            "images": readable_size(directory_size(IMAGE_DIR)),
            "tmp": readable_size(directory_size(TMP_DIR)),
            "compressed": readable_size(directory_size(COMPRESS_DIR)),
            "office": readable_size(directory_size(OFFICE_DIR)),
            "payments": readable_size(directory_size(PAYMENT_DIR)),
        },
        "features": feature_flags,
        "video_config": public_video_config(),
        "ads": ads_from_db(public_only=False),
        "credit_rules": settings.get("credit_rules", {}),
        "usage_rules": settings.get("usage_rules", {}),
        "payment_config": public_payment_config(admin=True),
        "reward_config": public_reward_config(),
        "checkin_config": public_checkin_config(),
        "prompt_config": prompt_engine_config("image_prompt_reverse", mask_secret=True),
        "ai_configs": public_ai_configs(),
        "ai_config_defaults": default_ai_configs,
        "prompt_admin_emails": settings.get("prompt_admin_emails", []),
        "link_card_config": settings.get("link_card_config", default_link_card_config),
        "prompt_provider_presets": prompt_provider_presets,
        "visitors": visitor_summary(),
        "checkins": recent_admin_checkins(),
        "password_resets": recent_password_resets(),
        "logs": list(event_logs)[:50],
        "limits": {"max_video_mb": MAX_VIDEO_FILE_MB, "max_image_mb": MAX_IMAGE_MB, "max_office_mb": MAX_OFFICE_FILE_MB, "rate_per_minute": RATE_LIMIT_PER_MINUTE},
    }


@app.post("/api/admin/cleanup")
async def admin_cleanup(x_admin_token: str | None = Header(default=None)) -> dict[str, int]:
    require_admin(x_admin_token)
    result = cleanup_old_files(0)
    log_event("info", "管理员手动清理", removed=result["removed"])
    return result


@app.get("/api/admin/users")
async def admin_users(x_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    require_admin(x_admin_token)
    with db() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY deleted_at ASC, id DESC LIMIT 200").fetchall()
    return {"users": [public_user(row) for row in rows]}


@app.get("/api/admin/payment-orders")
async def admin_payment_orders(x_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    require_admin(x_admin_token)
    with db() as conn:
        rows = conn.execute(
            """
            SELECT credit_orders.*, users.email, users.name
            FROM credit_orders
            JOIN users ON users.id = credit_orders.user_id
            ORDER BY credit_orders.created_at DESC
            LIMIT 200
            """
        ).fetchall()
    return {"orders": [public_credit_order(row) for row in rows]}


@app.post("/api/admin/users/tier")
async def admin_user_tier(user_id: int = Form(...), tier: str = Form(...), x_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    require_admin(x_admin_token)
    if tier not in {"free", "pro", "vip"}:
        raise HTTPException(status_code=400, detail="会员等级只能是 free/pro/vip")
    with db() as conn:
        conn.execute("UPDATE users SET tier = ? WHERE id = ?", (tier, user_id))
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="用户不存在")
    log_event("info", "会员等级已更新", user_id=user_id, tier=tier)
    return {"user": public_user(row)}


@app.post("/api/admin/users/points")
async def admin_user_points(user_id: int = Form(...), points: int = Form(...), x_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    require_admin(x_admin_token)
    if points < 0:
        raise HTTPException(status_code=400, detail="积分不能小于 0")
    with db() as conn:
        conn.execute("UPDATE users SET points = ? WHERE id = ?", (points, user_id))
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="用户不存在")
    log_event("info", "用户积分已更新", user_id=user_id, points=points)
    return {"user": public_user(row)}


@app.post("/api/admin/users/points-adjust")
async def admin_user_points_adjust(user_id: int = Form(...), delta: int = Form(...), x_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    require_admin(x_admin_token)
    if delta == 0:
        raise HTTPException(status_code=400, detail="积分增减不能为 0")
    with db() as conn:
        conn.execute("UPDATE users SET points = MAX(0, points + ?) WHERE id = ?", (delta, user_id))
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="用户不存在")
    log_event("info", "用户积分已增减", user_id=user_id, delta=delta, points=row["points"])
    return {"user": public_user(row)}


@app.post("/api/admin/users/password")
async def admin_user_password(user_id: int = Form(...), password: str = Form(...), x_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    require_admin(x_admin_token)
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="新密码至少 8 位")
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row or row["deleted_at"]:
            raise HTTPException(status_code=404, detail="用户不存在或已删除")
        new_hash = hash_password(password)
        conn.execute("UPDATE users SET password_hash = ?, hashed_password = ? WHERE id = ?", (new_hash, new_hash, user_id))
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.execute("UPDATE password_resets SET used_at = ? WHERE user_id = ? AND used_at = 0", (int(now()), user_id))
        updated = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    log_event("info", "管理员已修改用户密码", user_id=user_id, user=updated["email"])
    return {"user": public_user(updated)}


@app.post("/api/admin/users/prompt-publisher")
async def admin_user_prompt_publisher(user_id: int = Form(...), enabled: str = Form("true"), x_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    require_admin(x_admin_token)
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row or row["deleted_at"]:
        raise HTTPException(status_code=404, detail="用户不存在或已删除")
    email = row["email"].strip().lower()
    publishers = {item.strip().lower() for item in settings.get("prompt_admin_emails", []) if item.strip()}
    if enabled == "true":
        publishers.add(email)
    else:
        publishers.discard(email)
    settings["prompt_admin_emails"] = sorted(publishers)
    save_settings(settings)
    log_event("info", "提示词发布权限已更新", user_id=user_id, user=email, enabled=enabled)
    return {"user": public_user(row), "prompt_admin_emails": settings["prompt_admin_emails"]}


@app.post("/api/admin/users/status")
async def admin_user_status(user_id: int = Form(...), disabled: str = Form("false"), x_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    require_admin(x_admin_token)
    with db() as conn:
        conn.execute("UPDATE users SET disabled = ? WHERE id = ? AND deleted_at = 0", (1 if disabled == "true" else 0, user_id))
        if disabled == "true":
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="用户不存在")
    log_event("info", "用户状态已更新", user_id=user_id, disabled=disabled)
    return {"user": public_user(row)}


@app.post("/api/admin/users/posting")
async def admin_user_posting(user_id: int = Form(...), disabled: str = Form("false"), x_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    require_admin(x_admin_token)
    with db() as conn:
        conn.execute("UPDATE users SET posting_disabled = ? WHERE id = ? AND deleted_at = 0", (1 if disabled == "true" else 0, user_id))
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="用户不存在")
    log_event("info", "用户发文权限已更新", user_id=user_id, disabled=disabled)
    return {"user": public_user(row)}


@app.post("/api/admin/users/mute")
async def admin_user_mute(user_id: int = Form(...), hours: int = Form(0), x_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    require_admin(x_admin_token)
    if hours < 0:
        raise HTTPException(status_code=400, detail="禁言小时不能小于 0")
    muted_until = int(now()) + hours * 3600 if hours > 0 else 0
    with db() as conn:
        conn.execute("UPDATE users SET muted_until = ? WHERE id = ? AND deleted_at = 0", (muted_until, user_id))
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="用户不存在")
    log_event("info", "用户禁言状态已更新", user_id=user_id, muted_until=muted_until)
    return {"user": public_user(row)}


@app.post("/api/admin/users/delete")
async def admin_user_delete(user_id: int = Form(...), x_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    require_admin(x_admin_token)
    deleted_at = int(now())
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="用户不存在")
        if row["deleted_at"]:
            return {"user": public_user(row)}
        conn.execute("UPDATE users SET disabled = 1, deleted_at = ? WHERE id = ?", (deleted_at, user_id))
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        updated = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    log_event("info", "用户已软删除", user_id=user_id)
    return {"user": public_user(updated)}


@app.post("/api/admin/payment-orders/approve")
async def admin_payment_order_approve(order_id: str = Form(...), x_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    require_admin(x_admin_token)
    with db() as conn:
        row = conn.execute(
            "SELECT credit_orders.*, users.email, users.name FROM credit_orders JOIN users ON users.id = credit_orders.user_id WHERE credit_orders.id = ?",
            (order_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="订单不存在")
        if row["status"] == "approved":
            return {"order": public_credit_order(row)}
        if row["status"] != "pending":
            raise HTTPException(status_code=400, detail="只能批准待审核订单")
        conn.execute("UPDATE users SET points = points + ? WHERE id = ?", (row["points"], row["user_id"]))
        conn.execute("UPDATE credit_orders SET status = 'approved', updated_at = ? WHERE id = ?", (int(now()), order_id))
        updated = conn.execute(
            "SELECT credit_orders.*, users.email, users.name FROM credit_orders JOIN users ON users.id = credit_orders.user_id WHERE credit_orders.id = ?",
            (order_id,),
        ).fetchone()
    log_event("info", "积分充值已审核通过", order_id=order_id, user=updated["email"], points=updated["points"])
    return {"order": public_credit_order(updated)}


@app.post("/api/admin/payment-orders/reject")
async def admin_payment_order_reject(order_id: str = Form(...), x_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    require_admin(x_admin_token)
    with db() as conn:
        row = conn.execute("SELECT * FROM credit_orders WHERE id = ?", (order_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="订单不存在")
        if row["status"] != "pending":
            raise HTTPException(status_code=400, detail="只能驳回待审核订单")
        conn.execute("UPDATE credit_orders SET status = 'rejected', updated_at = ? WHERE id = ?", (int(now()), order_id))
        updated = conn.execute(
            "SELECT credit_orders.*, users.email, users.name FROM credit_orders JOIN users ON users.id = credit_orders.user_id WHERE credit_orders.id = ?",
            (order_id,),
        ).fetchone()
    log_event("info", "积分充值已驳回", order_id=order_id)
    return {"order": public_credit_order(updated)}


@app.post("/api/admin/features")
async def admin_features(name: str = Form(...), enabled: str = Form(...), x_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    require_admin(x_admin_token)
    if name not in feature_flags:
        raise HTTPException(status_code=400, detail="未知工具")
    feature_flags[name] = enabled == "true"
    log_event("info", "工具开关已更新", name=name, enabled=feature_flags[name])
    return {"features": feature_flags}


@app.post("/api/admin/video-config")
async def admin_video_config(max_quality: str = Form("4k"), x_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    require_admin(x_admin_token)
    if max_quality not in video_quality_options:
        raise HTTPException(status_code=400, detail="未知清晰度限制")
    settings["video_config"] = {"max_quality": max_quality}
    save_settings(settings)
    log_event("info", "视频最高清晰度限制已更新", max_quality=max_quality)
    return {"video_config": public_video_config()}


@app.post("/api/admin/video-usage-config")
async def admin_video_usage_config(
    single_free: int = Form(...),
    single_pro: int = Form(...),
    single_vip: int = Form(...),
    batch_free: int = Form(...),
    batch_pro: int = Form(...),
    batch_vip: int = Form(...),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    require_admin(x_admin_token)
    values = [single_free, single_pro, single_vip, batch_free, batch_pro, batch_vip]
    if any(value < -1 for value in values):
        raise HTTPException(status_code=400, detail="次数不能小于 -1，-1 表示不限制")
    rules = settings.get("usage_rules", {})
    single_current = default_usage_rules["video_download"] | rules.get("video_download", {})
    batch_current = default_usage_rules["video_batch"] | rules.get("video_batch", {})
    rules["video_download"] = single_current | {
        "enabled": True,
        "guest_limit": 0,
        "free_limit": single_free,
        "pro_limit": single_pro,
        "vip_limit": single_vip,
    }
    rules["video_batch"] = batch_current | {
        "enabled": True,
        "guest_limit": 0,
        "free_limit": batch_free,
        "pro_limit": batch_pro,
        "vip_limit": batch_vip,
    }
    settings["usage_rules"] = rules
    save_settings(settings)
    log_event("info", "视频下载会员次数限制已更新", single_free=single_free, single_pro=single_pro, single_vip=single_vip, batch_free=batch_free, batch_pro=batch_pro, batch_vip=batch_vip)
    return {"usage_rules": settings["usage_rules"], "video_config": public_video_config()}


@app.post("/api/admin/credit-rules")
async def admin_credit_rules(
    key: str = Form(...),
    enabled: str = Form("true"),
    cost: int = Form(...),
    tiers: str = Form(""),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    require_admin(x_admin_token)
    if key not in default_credit_rules:
        raise HTTPException(status_code=400, detail="未知积分规则")
    if cost < 0:
        raise HTTPException(status_code=400, detail="扣除积分不能小于 0")
    allowed_tiers = [tier for tier in tiers.split(",") if tier in {"free", "pro", "vip"}]
    if not allowed_tiers:
        raise HTTPException(status_code=400, detail="至少选择一个可用会员等级")
    rules = settings.get("credit_rules", {})
    current = default_credit_rules[key] | rules.get(key, {})
    rules[key] = current | {"enabled": enabled == "true", "cost": cost, "tiers": allowed_tiers}
    settings["credit_rules"] = rules
    save_settings(settings)
    log_event("info", "积分规则已更新", item=rules[key]["label"], cost=cost, tiers=",".join(allowed_tiers))
    return {"credit_rules": settings["credit_rules"]}


@app.post("/api/admin/usage-rules")
async def admin_usage_rules(
    key: str = Form(...),
    enabled: str = Form("true"),
    guest_limit: int = Form(...),
    free_limit: int = Form(...),
    pro_limit: int = Form(...),
    vip_limit: int = Form(...),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    require_admin(x_admin_token)
    if key not in default_usage_rules:
        raise HTTPException(status_code=400, detail="未知次数规则")
    rules = settings.get("usage_rules", {})
    current = default_usage_rules[key] | rules.get(key, {})
    rules[key] = current | {
        "enabled": enabled == "true",
        "guest_limit": guest_limit,
        "free_limit": free_limit,
        "pro_limit": pro_limit,
        "vip_limit": vip_limit,
    }
    settings["usage_rules"] = rules
    save_settings(settings)
    log_event("info", "次数限制已更新", item=rules[key]["label"])
    return {"usage_rules": settings["usage_rules"]}


@app.post("/api/admin/payment-config")
async def admin_payment_config(
    manual_enabled: str = Form("true"),
    stripe_enabled: str = Form("false"),
    stripe_secret_key: str = Form(""),
    stripe_webhook_secret: str = Form(""),
    stripe_currency: str = Form("usd"),
    stripe_success_url: str = Form(""),
    stripe_cancel_url: str = Form(""),
    clear_stripe_secret: str = Form("false"),
    clear_stripe_webhook_secret: str = Form("false"),
    xunhu_enabled: str = Form("false"),
    xunhu_appid: str = Form(""),
    xunhu_appsecret: str = Form(""),
    xunhu_gateway: str = Form(""),
    xunhu_notify_url: str = Form(""),
    xunhu_return_url: str = Form(""),
    xunhu_callback_url: str = Form(""),
    clear_xunhu_appsecret: str = Form("false"),
    instructions: str = Form(""),
    packages_json: str = Form(""),
    wechat_qr: UploadFile | None = File(default=None),
    alipay_qr: UploadFile | None = File(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    require_admin(x_admin_token)
    current = raw_payment_config()
    packages = current.get("packages", [])
    if packages_json.strip():
        try:
            raw_packages = json.loads(packages_json)
            packages = [
                {
                    "id": str(item.get("id") or f"points_{int(item.get('points', 0))}"),
                    "name": str(item.get("name") or f"{int(item.get('points', 0))} 积分"),
                    "points": max(1, int(item.get("points", 0))),
                    "amount": max(0.01, float(item.get("amount", 0))),
                }
                for item in raw_packages
            ]
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"套餐 JSON 不正确：{exc}")
        if not packages:
            raise HTTPException(status_code=400, detail="至少保留一个积分套餐")
    updated = current | {
        "manual_enabled": manual_enabled == "true",
        "stripe_enabled": stripe_enabled == "true",
        "stripe_currency": (stripe_currency.strip().lower() or current.get("stripe_currency") or "usd")[:12],
        "stripe_success_url": stripe_success_url.strip(),
        "stripe_cancel_url": stripe_cancel_url.strip(),
        "xunhu_enabled": xunhu_enabled == "true",
        "xunhu_appid": xunhu_appid.strip() or current.get("xunhu_appid", ""),
        "xunhu_gateway": xunhu_gateway.strip() or current.get("xunhu_gateway") or default_payment_config["xunhu_gateway"],
        "xunhu_notify_url": xunhu_notify_url.strip(),
        "xunhu_return_url": xunhu_return_url.strip(),
        "xunhu_callback_url": xunhu_callback_url.strip(),
        "instructions": instructions.strip() or current.get("instructions", default_payment_config["instructions"]),
        "packages": packages,
    }
    if clear_stripe_secret == "true":
        updated["stripe_secret_key"] = ""
    elif stripe_secret_key.strip():
        updated["stripe_secret_key"] = stripe_secret_key.strip()
    if clear_stripe_webhook_secret == "true":
        updated["stripe_webhook_secret"] = ""
    elif stripe_webhook_secret.strip():
        updated["stripe_webhook_secret"] = stripe_webhook_secret.strip()
    if clear_xunhu_appsecret == "true":
        updated["xunhu_appsecret"] = ""
    elif xunhu_appsecret.strip():
        updated["xunhu_appsecret"] = xunhu_appsecret.strip()
    if wechat_qr and wechat_qr.filename:
        updated["wechat_qr"] = f"/api/payment/proofs/{save_optional_image(wechat_qr, PAYMENT_DIR, 'qr-wechat')}"
    if alipay_qr and alipay_qr.filename:
        updated["alipay_qr"] = f"/api/payment/proofs/{save_optional_image(alipay_qr, PAYMENT_DIR, 'qr-alipay')}"
    settings["payment_config"] = updated
    save_settings(settings)
    log_event("info", "充值配置已更新")
    return {"payment_config": public_payment_config(admin=True)}


@app.post("/api/admin/reward-config")
async def admin_reward_config(
    enabled: str = Form("true"),
    seconds: int = Form(...),
    points: int = Form(...),
    daily_limit: int = Form(...),
    title: str = Form(""),
    description: str = Form(""),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    require_admin(x_admin_token)
    if seconds < 1 or points < 0 or daily_limit < 0:
        raise HTTPException(status_code=400, detail="秒数、积分和每日上限不能为负")
    settings["reward_config"] = {
        "enabled": enabled == "true",
        "seconds": seconds,
        "points": points,
        "daily_limit": daily_limit,
        "title": title.strip() or default_reward_config["title"],
        "description": description.strip() or default_reward_config["description"],
    }
    save_settings(settings)
    log_event("info", "广告积分规则已更新", points=points, seconds=seconds)
    return {"reward_config": public_reward_config()}


@app.post("/api/admin/checkin-config")
async def admin_checkin_config(
    enabled: str = Form("true"),
    points: int = Form(...),
    streak_days: int = Form(...),
    streak_bonus: int = Form(...),
    title: str = Form(""),
    description: str = Form(""),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    require_admin(x_admin_token)
    if points < 0 or streak_bonus < 0 or streak_days < 1:
        raise HTTPException(status_code=400, detail="积分不能为负，连续天数至少为 1")
    settings["checkin_config"] = {
        "enabled": enabled == "true",
        "points": points,
        "streak_days": streak_days,
        "streak_bonus": streak_bonus,
        "title": title.strip() or default_checkin_config["title"],
        "description": description.strip() or default_checkin_config["description"],
    }
    save_settings(settings)
    log_event("info", "签到积分规则已更新", points=points, streak_days=streak_days, streak_bonus=streak_bonus)
    return {"checkin_config": public_checkin_config()}


@app.post("/api/admin/prompt-config")
async def admin_prompt_config(
    config_key: str = Form("image_prompt_reverse"),
    provider: str = Form("openai"),
    api_base: str = Form(""),
    model: str = Form(""),
    api_key: str = Form(""),
    clear_api_key: str = Form("false"),
    skill: str = Form(""),
    admin_emails: str = Form(""),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    require_admin(x_admin_token)
    if config_key not in default_ai_configs:
        raise HTTPException(status_code=400, detail="未知 API 用途")
    if provider not in prompt_provider_presets:
        raise HTTPException(status_code=400, detail="未知 API 平台")
    preset = prompt_provider_presets[provider]
    stored_current = prompt_task_defaults(config_key) | settings.get("ai_configs", {}).get(config_key, {})
    current = prompt_engine_config(config_key)
    default = prompt_task_defaults(config_key)
    updated = {
        "label": default["label"],
        "description": default.get("description", ""),
        "kind": default.get("kind", "text"),
        "provider": provider,
        "api_base": (api_base.strip() or current.get("api_base") or preset["api_base"]).rstrip("/"),
        "model": model.strip() or current.get("model") or default_model_for_preset(preset, default.get("kind", "text")),
        "api_key": stored_current.get("api_key", ""),
        "skill": skill.strip() or default.get("skill") or DEFAULT_PROMPT_SKILL,
    }
    if clear_api_key == "true":
        updated["api_key"] = ""
    elif clean_api_key(api_key):
        updated["api_key"] = clean_api_key(api_key)
    ai_configs = settings.get("ai_configs", {})
    ai_configs[config_key] = updated
    settings["ai_configs"] = ai_configs
    if config_key == "image_prompt_reverse":
        settings["prompt_config"] = updated
    if admin_emails.strip():
        settings["prompt_admin_emails"] = [item.strip().lower() for item in admin_emails.split(",") if item.strip()]
    save_settings(settings)
    log_event("info", "AI API 配置已更新", config=default["label"], api_base=updated["api_base"], model=updated["model"])
    return {
        "prompt_config": prompt_engine_config("image_prompt_reverse", mask_secret=True),
        "ai_configs": public_ai_configs(),
        "prompt_admin_emails": settings.get("prompt_admin_emails", []),
    }


@app.post("/api/admin/prompt-test")
async def admin_prompt_test(
    config_key: str = Form("image_prompt_reverse"),
    provider: str = Form(""),
    api_base: str = Form(""),
    model: str = Form(""),
    api_key: str = Form(""),
    skill: str = Form(""),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    require_admin(x_admin_token)
    if config_key not in default_ai_configs:
        raise HTTPException(status_code=400, detail="未知 API 用途")
    engine = prompt_engine_from_values(config_key, provider, api_base, model, api_key, skill) if provider else prompt_engine_config(config_key)
    if engine.get("kind") == "vision" and not engine_supports_vision(engine):
        return {
            "ok": False,
            "provider": engine["provider"],
            "model": engine["model"],
            "error": "当前用途需要视觉模型，但该平台/模型看起来是文本模型。DeepSeek deepseek-chat 不能直接分析图片。",
        }
    try:
        if engine.get("kind") == "vision":
            test_image = "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAIAAAD8GO2jAAAAKUlEQVR4nO3NoQ0AAAgDsP1/LRIHVyBImtQ31XMqAoFAIBAIBAKB4EuwsAucppOHF6kAAAAASUVORK5CYII="
            output = await prompt_chat_completion(engine, [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "这是 API 视觉连通性测试。请只回复 OK。"},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{test_image}"}},
                    ],
                },
            ])
        else:
            output = await prompt_chat_completion(engine, [
                {"role": "system", "content": "你是 API 连通性测试助手。"},
                {"role": "user", "content": "请只回复 OK"},
            ])
        warning = "连接测试只验证 API 能通；图片反推还需要确保模型支持视觉输入。" if engine.get("kind") == "vision" else ""
        return {"ok": True, "provider": engine["provider"], "model": engine["model"], "sample": output[:120], "warning": warning}
    except Exception as exc:
        return {"ok": False, "provider": engine["provider"], "model": engine["model"], "error": readable_api_error(engine, exc)[:700]}


@app.post("/api/admin/ads")
async def admin_ads(
    slot: str = Form(...),
    enabled: str = Form("false"),
    layout: str = Form("banner"),
    html: str = Form(""),
    items_json: str = Form(""),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    require_admin(x_admin_token)
    current_ads = ads_from_db(public_only=False)
    if slot not in current_ads:
        raise HTTPException(status_code=400, detail="未知广告位")
    if layout not in ad_layouts:
        raise HTTPException(status_code=400, detail="未知广告版式")
    try:
        raw_items = json.loads(items_json) if items_json.strip() else [{"html": html}]
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="广告内容格式不正确")
    count = ad_layouts[layout]["count"]
    items = []
    for index in range(count):
        raw = raw_items[index] if isinstance(raw_items, list) and index < len(raw_items) and isinstance(raw_items[index], dict) else {}
        items.append({"html": sanitize_ad_html_fragment(str(raw.get("html") or "").strip()[:30000])})
    current = current_ads[slot]
    config = normalize_ad_slot(current | {
        "enabled": enabled == "true",
        "layout": layout,
        "items": items,
        "html": items[0]["html"] if items else "",
    })
    timestamp = int(now())
    with db() as conn:
        conn.execute(
            """
            INSERT INTO ad_slots(slot, label, note, enabled, layout, html, items_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slot) DO UPDATE SET
                label = excluded.label,
                note = excluded.note,
                enabled = excluded.enabled,
                layout = excluded.layout,
                html = excluded.html,
                items_json = excluded.items_json,
                updated_at = excluded.updated_at
            """,
            (
                slot,
                config.get("label", current.get("label", slot)),
                config.get("note", current.get("note", "")),
                1 if config.get("enabled") else 0,
                config.get("layout", "banner"),
                config.get("html", ""),
                json.dumps(config.get("items", []), ensure_ascii=False),
                timestamp,
            ),
        )
    settings["ads"] = ads_from_db(public_only=False)
    save_settings(settings)
    log_event("info", "广告位已更新", slot=slot, enabled=config["enabled"], layout=layout)
    return {"ads": settings["ads"]}


@app.post("/api/admin/link-card-config")
async def admin_link_card_config(
    whitelist: str = Form(""),
    blacklist: str = Form(""),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    require_admin(x_admin_token)
    settings["link_card_config"] = {
        "whitelist": normalize_domain_list(whitelist),
        "blacklist": normalize_domain_list(blacklist),
    }
    save_settings(settings)
    log_event("info", "链接卡片规则已更新", whitelist=len(settings["link_card_config"]["whitelist"]), blacklist=len(settings["link_card_config"]["blacklist"]))
    return {"link_card_config": settings["link_card_config"]}


@app.get("/{category_slug}/{slug}", response_class=HTMLResponse)
async def community_post_detail(category_slug: str, slug: str, request: Request):
    host = public_host(request)
    if host == "www.meetseek.ai":
        return RedirectResponse(f"{MAIN_BASE_URL}/{category_slug}/{slug}", status_code=301)
    if host != "meetseek.ai":
        raise HTTPException(status_code=404, detail="页面不存在")
    with db() as conn:
        row = conn.execute(
            """
            SELECT posts.*, users.name AS author_name, users.nickname AS author_nickname,
                   users.email AS author_email, users.avatar_url AS author_avatar_url
            FROM posts
            JOIN users ON users.id = posts.author_id
            WHERE posts.category_slug = ? AND posts.slug = ?
              AND posts.status = 'published' AND posts.visibility = 'public'
            """,
            (category_slug, slug),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="帖子不存在")
        conn.execute("UPDATE posts SET view_count = view_count + 1 WHERE id = ?", (row["id"],))
        related_rows = conn.execute(
            """
            SELECT * FROM posts
            WHERE category_slug = ? AND id != ? AND status = 'published' AND visibility = 'public'
            ORDER BY pinned_at DESC, published_at DESC, updated_at DESC
            LIMIT 3
            """,
            (category_slug, row["id"]),
        ).fetchall()
        current_user = user_from_request(request)
        following = is_following_author(conn, int(current_user["id"]) if current_user else None, int(row["author_id"]))
    post = public_post(row)
    parsed_editor = parse_editorjs_raw(row["content_html"] or "") if str(row["content_html"] or "").lstrip().startswith("{") else None
    article_html = parsed_editor["html"] if parsed_editor else (
        render_short_detail_content(row["content_html"] or row["summary"] or "", post.get("link_previews", []))
        if str(row["type"] or "") == "short"
        else post["content_html"]
    )
    seo_description = (parsed_editor or {}).get("seo_description") or post["meta_description"]
    seo_image = (parsed_editor or {}).get("seo_image") or post["og_image"]
    if seo_image and not seo_image.startswith(("http://", "https://")):
        seo_image = absolute_public_url(seo_image, MAIN_BASE_URL)
    meta = {
        "title": f"{post['meta_title']} - meetseek",
        "description": seo_description,
        "canonical_url": post["canonical_url"],
        "image_url": seo_image,
        "type": "article",
    }
    return templates.TemplateResponse(
        "post_detail.html",
        {
            "request": request,
            "site_name": "meetseek",
            "main_base_url": MAIN_BASE_URL,
            "tools_base_url": TOOLS_BASE_URL,
            "prompts_base_url": PROMPTS_BASE_URL,
            "meta": meta,
            "post": post,
            "more_menu_html": post_more_menu_html(
                post_id=post["id"],
                author_id=post["author_id"],
                post_url=post["canonical_url"],
                current_user=current_user,
                is_admin=is_site_admin(request, current_user),
                is_following=following,
                is_recommended=bool(post.get("recommended_at")),
            ),
            "html": article_html,
            "seo_description": seo_description,
            "seo_image": seo_image,
            "author": {
                "name": row["author_nickname"] or row["author_name"],
                "email": row["author_email"],
                "avatar_url": row["author_avatar_url"] or "",
            },
            "published_at_label": datetime.fromtimestamp(post["published_at"], CN_TZ).strftime("%Y年%m月%d日"),
            "related": [public_post(item) for item in related_rows],
            "user": current_user,
        },
    )


@app.on_event("startup")
async def startup_cleanup_loop():
    init_db()

    async def loop() -> None:
        while True:
            cleanup_old_files()
            await asyncio.sleep(60 * 60)

    asyncio.create_task(loop())
