import html
import re
from typing import Any
from urllib.parse import urlparse

import bleach


INLINE_TAGS = ["a", "b", "br", "code", "em", "i", "mark", "strong"]
INLINE_ATTRS = {
    "a": ["href", "title", "target", "rel"],
}


def _inline_html(value: Any) -> str:
    cleaned = bleach.clean(
        str(value or ""),
        tags=INLINE_TAGS,
        attributes=INLINE_ATTRS,
        protocols=["http", "https", "mailto"],
        strip=True,
    )
    return _ugc_links(cleaned)


def _plain_text(value: Any) -> str:
    text = re.sub(r"<[^>]*>", " ", str(value or ""))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _url(value: Any) -> str:
    text = str(value or "").strip()
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"}:
        return ""
    return text


def _image_url(value: Any) -> str:
    text = str(value or "").strip()
    if text.startswith("/"):
        return text
    return _url(text)


def _ugc_links(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        tag = match.group(0)
        href_match = re.search(r'href=["\']([^"\']+)["\']', tag, flags=re.I)
        host = urlparse(href_match.group(1)).hostname if href_match else ""
        if not host or host.endswith("meetseek.ai"):
            return tag
        tag = re.sub(r'\srel=["\'][^"\']*["\']', "", tag, flags=re.I)
        tag = re.sub(r'\starget=["\'][^"\']*["\']', "", tag, flags=re.I)
        return tag[:-1] + ' rel="nofollow ugc" target="_blank">'

    return re.sub(r"<a\b[^>]*>", replace, value, flags=re.I)


def parse_editorjs_blocks(blocks: list) -> dict:
    parts: list[str] = []
    seo_description = ""
    seo_image = ""

    for block in blocks:
        if not isinstance(block, dict):
            continue
        kind = str(block.get("type") or "")
        data = block.get("data") if isinstance(block.get("data"), dict) else {}

        if kind == "header":
            level_raw = data.get("level") or 2
            try:
                level = int(level_raw)
            except (TypeError, ValueError):
                level = 2
            tag = "h3" if level >= 3 else "h2"
            cls = "text-xl font-bold mt-7 mb-3" if tag == "h3" else "text-2xl font-bold mt-8 mb-4"
            text = _inline_html(data.get("text"))
            if text:
                parts.append(f'<{tag} class="{cls}">{text}</{tag}>')

        elif kind == "paragraph":
            text = _inline_html(data.get("text"))
            plain = _plain_text(data.get("text"))
            if plain and not seo_description:
                seo_description = plain[:150]
            if text:
                parts.append(f'<p class="mb-4">{text}</p>')

        elif kind == "list":
            items = data.get("items") if isinstance(data.get("items"), list) else []
            tag = "ol" if data.get("style") == "ordered" else "ul"
            cls = "mb-5 list-decimal pl-6" if tag == "ol" else "mb-5 list-disc pl-6"
            rendered = "".join(f"<li>{_inline_html(item)}</li>" for item in items if _plain_text(item))
            if rendered:
                parts.append(f'<{tag} class="{cls}">{rendered}</{tag}>')

        elif kind == "image":
            file_data = data.get("file") if isinstance(data.get("file"), dict) else {}
            src = _image_url(file_data.get("url") or data.get("url"))
            caption_html = _inline_html(data.get("caption"))
            caption_text = _plain_text(data.get("caption"))
            if src and not seo_image:
                seo_image = src
            if src:
                figcaption = f'<figcaption class="mt-3 text-center text-sm text-slate-400">{caption_html}</figcaption>' if caption_text else ""
                alt = html.escape(caption_text or "文章图片", quote=True)
                parts.append(
                    '<figure class="my-8">'
                    f'<img class="w-full rounded-3xl" src="{html.escape(src, quote=True)}" alt="{alt}" loading="lazy">'
                    f"{figcaption}</figure>"
                )

        elif kind == "quote":
            text = _inline_html(data.get("text"))
            caption = _inline_html(data.get("caption"))
            if text:
                footer = f'<footer class="mt-3 text-sm text-slate-400">{caption}</footer>' if _plain_text(caption) else ""
                parts.append(f'<blockquote class="my-6 border-l-4 border-orange-500 pl-5 text-slate-600">{text}{footer}</blockquote>')

        elif kind == "linkTool":
            meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
            link = _url(data.get("link") or meta.get("url"))
            title = _plain_text(meta.get("title") or link)
            description = _plain_text(meta.get("description"))
            image = _url(meta.get("image") or meta.get("image_url"))
            if link:
                image_html = (
                    f'<img class="h-40 w-full object-cover md:h-full md:w-52" src="{html.escape(image, quote=True)}" '
                    f'alt="{html.escape(title, quote=True)}" loading="lazy">'
                    if image else ""
                )
                parts.append(
                    f'<a class="my-6 grid overflow-hidden rounded-3xl border border-slate-200 bg-white transition hover:border-orange-200 hover:bg-orange-50/40 md:grid-cols-[auto_1fr]" href="{html.escape(link, quote=True)}" rel="nofollow ugc" target="_blank">'
                    f"{image_html}"
                    '<span class="block p-5">'
                    f'<strong class="block text-lg font-black text-slate-950">{html.escape(title)}</strong>'
                    f'<span class="mt-2 line-clamp-3 block text-sm leading-relaxed text-slate-500">{html.escape(description)}</span>'
                    f'<span class="mt-4 block text-xs font-black text-orange-600">{html.escape(urlparse(link).netloc)}</span>'
                    "</span></a>"
                )

    return {
        "html": "\n".join(parts),
        "seo_description": seo_description,
        "seo_image": seo_image,
    }
