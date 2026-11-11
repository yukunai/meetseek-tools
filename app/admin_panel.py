import os
import re
import time
import uuid
import hmac
import hashlib
from io import BytesIO
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, relationship
from sqladmin import Admin, BaseView, ModelView, expose
from sqladmin.authentication import AuthenticationBackend
from wtforms import DecimalField, SelectField
from wtforms.validators import Optional


class AdminBase(DeclarativeBase):
    pass


SHOP_IMAGE_DIR = Path(os.getenv("DATA_DIR", "/data")) / "shop_images"


def _now_ts() -> int:
    return int(time.time())


class YuanPriceField(DecimalField):
    def process_data(self, value):
        if value in (None, ""):
            self.data = Decimal("0")
            return
        try:
            self.data = (Decimal(str(value)) / Decimal("100")).quantize(Decimal("0.01"))
        except Exception:
            self.data = Decimal("0")


class AdminUser(AdminBase):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    tier = Column(String, nullable=False)
    points = Column(Integer, nullable=False)
    disabled = Column(Integer, nullable=False)
    posting_disabled = Column(Integer, nullable=False)
    muted_until = Column(Integer, nullable=False)
    deleted_at = Column(Integer, nullable=False)
    avatar_url = Column(String, nullable=False)
    created_at = Column(Integer, nullable=False)

    posts = relationship("AdminPost", back_populates="author")

    def __str__(self) -> str:
        return self.name or self.email or f"User #{self.id}"


class AdminPost(AdminBase):
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    type = Column(String, nullable=False)
    title = Column(String, nullable=False)
    slug = Column(String, nullable=False)
    category_slug = Column(String, nullable=False)
    summary = Column(Text, nullable=False)
    content_html = Column(Text, nullable=False)
    content_json = Column(Text, nullable=False)
    cover_image = Column(String, nullable=False)
    source_url = Column(String, nullable=False)
    visibility = Column(String, nullable=False)
    status = Column(String, nullable=False)
    meta_title = Column(String, nullable=False)
    meta_description = Column(String, nullable=False)
    og_image = Column(String, nullable=False)
    canonical_url = Column(String, nullable=False)
    view_count = Column(Integer, nullable=False)
    comment_count = Column(Integer, nullable=False)
    like_count = Column(Integer, nullable=False)
    bookmark_count = Column(Integer, nullable=False)
    pinned_at = Column(Integer, nullable=False)
    published_at = Column(Integer, nullable=False)
    created_at = Column(Integer, nullable=False)
    updated_at = Column(Integer, nullable=False)

    author = relationship("AdminUser", back_populates="posts")

    def __str__(self) -> str:
        return self.title or f"Post #{self.id}"


class AdminCategory(AdminBase):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, nullable=False)
    description = Column(Text, nullable=False)
    seo_title = Column(String, nullable=False)
    seo_description = Column(String, nullable=False)
    sort_order = Column(Integer, nullable=False)
    created_at = Column(Integer, nullable=False)

    def __str__(self) -> str:
        return self.name or self.slug or f"Category #{self.id}"


class AdminCreditOrder(AdminBase):
    __tablename__ = "credit_orders"

    id = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    package_id = Column(String, nullable=False)
    package_name = Column(String, nullable=False)
    points = Column(Integer, nullable=False)
    amount = Column(Float, nullable=False)
    method = Column(String, nullable=False)
    transaction_no = Column(String, nullable=False)
    screenshot = Column(String, nullable=False)
    status = Column(String, nullable=False)
    stripe_session_id = Column(String, nullable=False)
    stripe_payment_intent_id = Column(String, nullable=False)
    created_at = Column(Integer, nullable=False)
    updated_at = Column(Integer, nullable=False)

    user = relationship("AdminUser")

    def __str__(self) -> str:
        return self.id


class AdminAdSlot(AdminBase):
    __tablename__ = "ad_slots"

    slot = Column(String, primary_key=True)
    label = Column(String, nullable=False)
    note = Column(Text, nullable=False)
    enabled = Column(Integer, nullable=False)
    layout = Column(String, nullable=False)
    html = Column(Text, nullable=False)
    items_json = Column(Text, nullable=False)
    updated_at = Column(Integer, nullable=False)

    def __str__(self) -> str:
        return self.label or self.slot


class AdminContactSubmission(AdminBase):
    __tablename__ = "contact_submissions"

    id = Column(Integer, primary_key=True)
    inquiry_type = Column(String, nullable=False, default="contact")
    name = Column(String, nullable=False, default="")
    company = Column(String, nullable=False, default="")
    contact = Column(String, nullable=False, default="")
    budget = Column(String, nullable=False, default="")
    placement = Column(String, nullable=False, default="")
    message = Column(Text, nullable=False, default="")
    status = Column(String, nullable=False, default="new")
    source_path = Column(String, nullable=False, default="")
    ip_address = Column(String, nullable=False, default="")
    user_agent = Column(Text, nullable=False, default="")
    created_at = Column(Integer, nullable=False)
    updated_at = Column(Integer, nullable=False)

    def __str__(self) -> str:
        return f"{self.inquiry_type} #{self.id}"


class AdminWechatGeoArticle(AdminBase):
    __tablename__ = "wechat_geo_articles"

    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False, default="")
    source_text = Column(Text, nullable=False, default="")
    context_note = Column(Text, nullable=False, default="")
    wechat_html = Column(Text, nullable=False, default="")
    ai_html = Column(Text, nullable=False, default="")
    clean_markdown = Column(Text, nullable=False, default="")
    chunk_json = Column(Text, nullable=False, default="[]")
    suggestions_json = Column(Text, nullable=False, default="[]")
    geo_score = Column(Integer, nullable=False, default=0)
    semantic_density = Column(Integer, nullable=False, default=0)
    noise_score = Column(Integer, nullable=False, default=0)
    token_count = Column(Integer, nullable=False, default=0)
    status = Column(String, nullable=False, default="draft")
    created_at = Column(Integer, nullable=False)
    updated_at = Column(Integer, nullable=False)

    def __str__(self) -> str:
        return self.title or f"公众号草稿 #{self.id}"


class AdminPlugin(AdminBase):
    __tablename__ = "plugins"

    id = Column(Integer, primary_key=True)
    slug = Column(String, unique=True, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False, default="")
    category = Column(String, nullable=False, default="AI & ChatGPT")
    rating = Column(String, nullable=False, default="4.7")
    users = Column(String, nullable=False, default="")
    icon = Column(String, nullable=False, default="◆")
    accent = Column(String, nullable=False, default="from-violet-600 to-blue-500")
    short_description = Column(Text, nullable=False, default="")
    long_description = Column(Text, nullable=False, default="")
    version = Column(String, nullable=False, default="1.0.0")
    install_url = Column(String, nullable=False, default="")
    chrome_store_url = Column(String, nullable=False, default="")
    edge_store_url = Column(String, nullable=False, default="")
    direct_url = Column(String, nullable=False, default="")
    icon_url = Column(String, nullable=False, default="")
    tags = Column(String, nullable=False, default="")
    developer_name = Column(String, nullable=False, default="")
    developer_email = Column(String, nullable=False, default="")
    submitter_id = Column(Integer, nullable=False, default=0)
    review_note = Column(Text, nullable=False, default="")
    website_url = Column(String, nullable=False, default="")
    support_url = Column(String, nullable=False, default="")
    cover_image = Column(String, nullable=False, default="")
    gallery_images = Column(Text, nullable=False, default="")
    status = Column(String, nullable=False, default="published")
    is_featured = Column(Boolean, nullable=False, default=False)
    is_trending = Column(Boolean, nullable=False, default=False)
    is_new = Column(Boolean, nullable=False, default=False)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(Integer, nullable=False, default=_now_ts)
    updated_at = Column(Integer, nullable=False, default=_now_ts, onupdate=_now_ts)

    def __str__(self) -> str:
        return self.title or self.slug or f"Plugin #{self.id}"


class AdminPrompt(AdminBase):
    __tablename__ = "prompts"

    id = Column(Integer, primary_key=True)
    item_key = Column(String, unique=True, nullable=False)
    kind = Column(String, nullable=False)
    title = Column(String, nullable=False)
    cover_image = Column(String, nullable=True)
    model_engine = Column(String, nullable=False)
    prompt_text = Column(Text, nullable=False)
    negative_prompt = Column(Text, nullable=True)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    category_id = Column(Integer, nullable=True)
    category = Column(String, nullable=False)
    tags = Column(Text, nullable=False)
    models = Column(Text, nullable=False)
    zh = Column(Text, nullable=False)
    en = Column(Text, nullable=False)
    hidden = Column(Integer, nullable=False)
    is_featured = Column(Boolean, nullable=False)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)

    author = relationship("AdminUser")

    def __str__(self) -> str:
        return self.title or f"Prompt #{self.id}"


class AdminComment(AdminBase):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True)
    content = Column(Text, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    target_id = Column(Integer, nullable=False)
    target_type = Column(String, nullable=False)
    created_at = Column(Integer, nullable=False)

    user = relationship("AdminUser")

    def __str__(self) -> str:
        return (self.content or "")[:40] or f"Comment #{self.id}"


class AdminShopCategory(AdminBase):
    __tablename__ = "shop_categories"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, nullable=False)
    description = Column(Text, nullable=False, default="")
    enabled = Column(Integer, nullable=False, default=1)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(Integer, nullable=False, default=_now_ts)
    updated_at = Column(Integer, nullable=False, default=_now_ts, onupdate=_now_ts)

    products = relationship("AdminShopProduct", back_populates="category")

    def __str__(self) -> str:
        return self.name or self.slug or f"ShopCategory #{self.id}"


class AdminShopProduct(AdminBase):
    __tablename__ = "shop_products"

    id = Column(Integer, primary_key=True)
    category_id = Column(Integer, ForeignKey("shop_categories.id"), nullable=True)
    title = Column(String, nullable=False)
    slug = Column(String, unique=True, nullable=False)
    subtitle = Column(String, nullable=False, default="")
    description = Column(Text, nullable=False, default="")
    cover_image = Column(String, nullable=False, default="")
    gallery_images = Column(Text, nullable=False, default="")
    product_type = Column(String, nullable=False, default="physical")
    price_cents = Column(Integer, nullable=False, default=0)
    points_price = Column(Integer, nullable=False, default=0)
    stock = Column(Integer, nullable=False, default=-1)
    status = Column(String, nullable=False, default="draft")
    fulfillment_note = Column(Text, nullable=False, default="")
    auto_delivery = Column(Integer, nullable=False, default=0)
    delivery_subject = Column(String, nullable=False, default="")
    delivery_body = Column(Text, nullable=False, default="")
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(Integer, nullable=False, default=_now_ts)
    updated_at = Column(Integer, nullable=False, default=_now_ts, onupdate=_now_ts)

    category = relationship("AdminShopCategory", back_populates="products")

    def __str__(self) -> str:
        return self.title or f"ShopProduct #{self.id}"


class AdminShopOrder(AdminBase):
    __tablename__ = "shop_orders"

    id = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("shop_products.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    amount_cents = Column(Integer, nullable=False)
    points_amount = Column(Integer, nullable=False)
    payment_method = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending")
    customer_note = Column(Text, nullable=False, default="")
    admin_note = Column(Text, nullable=False, default="")
    created_at = Column(Integer, nullable=False, default=_now_ts)
    updated_at = Column(Integer, nullable=False, default=_now_ts, onupdate=_now_ts)

    user = relationship("AdminUser")
    product = relationship("AdminShopProduct")

    def __str__(self) -> str:
        return self.id


_sqladmin_username = (os.getenv("SQLADMIN_USERNAME") or "admin").strip() or "admin"
_sqladmin_password = (os.getenv("SQLADMIN_PASSWORD") or os.getenv("ADMIN_TOKEN") or "").strip()
_admin_token = (os.getenv("ADMIN_TOKEN") or "").strip()
_admin_cookie_domain = os.getenv("COOKIE_DOMAIN", ".meetseek.ai")
_admin_session_seconds = 60 * 60 * 12


def _set_main_admin_cookie(response: RedirectResponse) -> None:
    if not _admin_token:
        return
    timestamp = str(int(time.time()))
    signature = hmac.new(_admin_token.encode("utf-8"), timestamp.encode("utf-8"), hashlib.sha256).hexdigest()
    response.set_cookie(
        "meetseek_admin",
        f"{timestamp}.{signature}",
        max_age=_admin_session_seconds,
        httponly=True,
        secure=True,
        samesite="lax",
        domain=_admin_cookie_domain,
    )


class SqlAdminAuth(AuthenticationBackend):
    async def login(self, request: Request) -> bool:
        form = await request.form()
        username = str(form.get("username") or "").strip()
        password = str(form.get("password") or "")
        if not _sqladmin_password:
            return False
        if username == _sqladmin_username and password == _sqladmin_password:
            request.session.update({"sqladmin_authenticated": True})
            return True
        return False

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        return bool(request.session.get("sqladmin_authenticated"))


class UserAdmin(ModelView, model=AdminUser):
    name = "用户"
    name_plural = "用户"
    icon = "fa-solid fa-users"
    column_list = [AdminUser.id, AdminUser.email, AdminUser.name, AdminUser.tier, AdminUser.points, AdminUser.disabled, AdminUser.posting_disabled, AdminUser.muted_until, AdminUser.created_at]
    column_searchable_list = [AdminUser.email, AdminUser.name]
    column_sortable_list = [AdminUser.id, AdminUser.created_at, AdminUser.points]
    can_create = True
    can_edit = True
    can_delete = True


class PostAdmin(ModelView, model=AdminPost):
    name = "帖子"
    name_plural = "帖子"
    icon = "fa-solid fa-newspaper"
    column_list = [
        AdminPost.id,
        AdminPost.title,
        AdminPost.author,
        AdminPost.type,
        AdminPost.category_slug,
        AdminPost.status,
        AdminPost.visibility,
        AdminPost.like_count,
        AdminPost.created_at,
    ]
    column_searchable_list = [AdminPost.title, AdminPost.slug, AdminPost.category_slug, AdminPost.author_id]
    column_sortable_list = [AdminPost.id, AdminPost.created_at, AdminPost.updated_at, AdminPost.like_count]
    can_create = True
    can_edit = True
    can_delete = True


class CategoryAdmin(ModelView, model=AdminCategory):
    name = "分类"
    name_plural = "分类"
    icon = "fa-solid fa-folder"
    column_list = [AdminCategory.id, AdminCategory.name, AdminCategory.slug, AdminCategory.sort_order, AdminCategory.created_at]
    column_searchable_list = [AdminCategory.name, AdminCategory.slug]
    column_sortable_list = [AdminCategory.id, AdminCategory.sort_order, AdminCategory.created_at]
    can_create = True
    can_edit = True
    can_delete = True


class CreditOrderAdmin(ModelView, model=AdminCreditOrder):
    name = "积分订单"
    name_plural = "积分订单"
    icon = "fa-solid fa-receipt"
    column_list = [
        AdminCreditOrder.id,
        AdminCreditOrder.user_id,
        AdminCreditOrder.package_name,
        AdminCreditOrder.points,
        AdminCreditOrder.amount,
        AdminCreditOrder.method,
        AdminCreditOrder.status,
        AdminCreditOrder.created_at,
    ]
    column_searchable_list = [AdminCreditOrder.id, AdminCreditOrder.package_name, AdminCreditOrder.status]
    column_sortable_list = [AdminCreditOrder.created_at, AdminCreditOrder.points, AdminCreditOrder.amount]
    can_create = True
    can_edit = True
    can_delete = True


class AdSlotAdmin(ModelView, model=AdminAdSlot):
    name = "广告位"
    name_plural = "广告位"
    icon = "fa-solid fa-rectangle-ad"
    column_list = [AdminAdSlot.slot, AdminAdSlot.label, AdminAdSlot.enabled, AdminAdSlot.layout, AdminAdSlot.updated_at]
    column_searchable_list = [AdminAdSlot.slot, AdminAdSlot.label, AdminAdSlot.note, AdminAdSlot.html]
    column_sortable_list = [AdminAdSlot.slot, AdminAdSlot.enabled, AdminAdSlot.updated_at]
    form_columns = [AdminAdSlot.slot, AdminAdSlot.label, AdminAdSlot.note, AdminAdSlot.enabled, AdminAdSlot.layout, AdminAdSlot.html, AdminAdSlot.items_json]
    can_create = True
    can_edit = True
    can_delete = True


class ContactSubmissionAdmin(ModelView, model=AdminContactSubmission):
    name = "联系提交"
    name_plural = "联系提交"
    icon = "fa-solid fa-inbox"
    column_list = [
        AdminContactSubmission.id,
        AdminContactSubmission.inquiry_type,
        AdminContactSubmission.status,
        AdminContactSubmission.name,
        AdminContactSubmission.company,
        AdminContactSubmission.contact,
        AdminContactSubmission.placement,
        AdminContactSubmission.created_at,
    ]
    column_searchable_list = [
        AdminContactSubmission.name,
        AdminContactSubmission.company,
        AdminContactSubmission.contact,
        AdminContactSubmission.message,
        AdminContactSubmission.placement,
    ]
    column_sortable_list = [
        AdminContactSubmission.id,
        AdminContactSubmission.inquiry_type,
        AdminContactSubmission.status,
        AdminContactSubmission.created_at,
    ]
    form_columns = [
        AdminContactSubmission.inquiry_type,
        AdminContactSubmission.status,
        AdminContactSubmission.name,
        AdminContactSubmission.company,
        AdminContactSubmission.contact,
        AdminContactSubmission.budget,
        AdminContactSubmission.placement,
        AdminContactSubmission.message,
        AdminContactSubmission.source_path,
        AdminContactSubmission.ip_address,
        AdminContactSubmission.user_agent,
    ]
    can_create = True
    can_edit = True
    can_delete = True


class WechatGeoArticleAdmin(ModelView, model=AdminWechatGeoArticle):
    name = "公众号GEO草稿"
    name_plural = "公众号GEO草稿"
    icon = "fa-solid fa-newspaper"
    column_list = [
        AdminWechatGeoArticle.id,
        AdminWechatGeoArticle.title,
        AdminWechatGeoArticle.status,
        AdminWechatGeoArticle.geo_score,
        AdminWechatGeoArticle.semantic_density,
        AdminWechatGeoArticle.token_count,
        AdminWechatGeoArticle.created_at,
    ]
    column_searchable_list = [
        AdminWechatGeoArticle.title,
        AdminWechatGeoArticle.source_text,
        AdminWechatGeoArticle.context_note,
        AdminWechatGeoArticle.clean_markdown,
    ]
    column_sortable_list = [
        AdminWechatGeoArticle.id,
        AdminWechatGeoArticle.status,
        AdminWechatGeoArticle.geo_score,
        AdminWechatGeoArticle.token_count,
        AdminWechatGeoArticle.created_at,
    ]
    form_columns = [
        AdminWechatGeoArticle.title,
        AdminWechatGeoArticle.status,
        AdminWechatGeoArticle.source_text,
        AdminWechatGeoArticle.context_note,
        AdminWechatGeoArticle.wechat_html,
        AdminWechatGeoArticle.ai_html,
        AdminWechatGeoArticle.clean_markdown,
        AdminWechatGeoArticle.chunk_json,
        AdminWechatGeoArticle.suggestions_json,
        AdminWechatGeoArticle.geo_score,
        AdminWechatGeoArticle.semantic_density,
        AdminWechatGeoArticle.noise_score,
        AdminWechatGeoArticle.token_count,
    ]
    can_create = True
    can_edit = True
    can_delete = True


class PluginAdmin(ModelView, model=AdminPlugin):
    name = "插件"
    name_plural = "插件管理"
    icon = "fa-solid fa-plug"
    column_list = [
        AdminPlugin.id,
        AdminPlugin.title,
        AdminPlugin.category,
        AdminPlugin.status,
        AdminPlugin.version,
        AdminPlugin.developer_email,
        AdminPlugin.is_featured,
        AdminPlugin.is_trending,
        AdminPlugin.is_new,
        AdminPlugin.sort_order,
    ]
    column_searchable_list = [
        AdminPlugin.title,
        AdminPlugin.slug,
        AdminPlugin.description,
        AdminPlugin.short_description,
        AdminPlugin.long_description,
        AdminPlugin.category,
        AdminPlugin.developer_email,
    ]
    column_sortable_list = [AdminPlugin.id, AdminPlugin.sort_order, AdminPlugin.rating, AdminPlugin.updated_at]
    form_overrides = {"status": SelectField}
    form_args = {
        "status": {
            "label": "状态",
            "choices": [("pending", "待审核"), ("published", "已发布"), ("draft", "草稿"), ("hidden", "隐藏")],
        },
        "slug": {"label": "插件标识", "description": "用于详情页 URL，例如 adguard-adblocker。"},
        "title": {"label": "插件名称"},
        "description": {"label": "兼容简介", "description": "旧字段。通常与一句话推荐保持一致。"},
        "short_description": {"label": "一句话推荐", "description": "用于首页和列表卡片展示。"},
        "long_description": {"label": "详细功能说明", "description": "用于详情页，可填写 Markdown 或纯文本。"},
        "category": {"label": "分类"},
        "version": {"label": "版本号"},
        "install_url": {"label": "主安装源", "description": "Chrome/Edge 商店链接或直接访问网址。"},
        "chrome_store_url": {"label": "Chrome Web Store 链接"},
        "edge_store_url": {"label": "Edge 扩展商店链接"},
        "direct_url": {"label": "直接访问网址"},
        "tags": {"label": "标签", "description": "逗号分隔。"},
        "developer_name": {"label": "开发者名称"},
        "developer_email": {"label": "开发者邮箱"},
        "review_note": {"label": "审核备注"},
        "rating": {"label": "评分"},
        "users": {"label": "用户数"},
        "icon": {"label": "备用图标文字", "description": "不上传图标时使用名称首字母或一个符号。"},
        "icon_url": {"label": "图标 URL", "description": "创作者上传后自动写入，也可手动替换。"},
        "accent": {"label": "卡片色彩", "description": "建议使用提交页预设色。"},
        "website_url": {"label": "官网链接"},
        "support_url": {"label": "支持链接"},
        "cover_image": {"label": "封面图 URL", "description": "创作者上传后自动写入。"},
        "gallery_images": {"label": "展示图集", "description": "JSON 数组或一行一张图片 URL。"},
        "is_featured": {"label": "首页精选"},
        "is_trending": {"label": "趋势榜"},
        "is_new": {"label": "新上架"},
        "sort_order": {"label": "排序"},
    }
    form_columns = [
        AdminPlugin.slug,
        AdminPlugin.title,
        AdminPlugin.short_description,
        AdminPlugin.long_description,
        AdminPlugin.category,
        AdminPlugin.version,
        AdminPlugin.install_url,
        AdminPlugin.chrome_store_url,
        AdminPlugin.edge_store_url,
        AdminPlugin.direct_url,
        AdminPlugin.website_url,
        AdminPlugin.support_url,
        AdminPlugin.tags,
        AdminPlugin.developer_name,
        AdminPlugin.developer_email,
        AdminPlugin.icon_url,
        AdminPlugin.icon,
        AdminPlugin.accent,
        AdminPlugin.cover_image,
        AdminPlugin.gallery_images,
        AdminPlugin.status,
        AdminPlugin.review_note,
        AdminPlugin.description,
        AdminPlugin.rating,
        AdminPlugin.users,
        AdminPlugin.is_featured,
        AdminPlugin.is_trending,
        AdminPlugin.is_new,
        AdminPlugin.sort_order,
    ]
    column_labels = {
        AdminPlugin.id: "ID",
        AdminPlugin.slug: "插件标识",
        AdminPlugin.title: "插件名称",
        AdminPlugin.description: "插件简介",
        AdminPlugin.category: "分类",
        AdminPlugin.rating: "评分",
        AdminPlugin.users: "用户数",
        AdminPlugin.icon: "图标",
        AdminPlugin.accent: "渐变色",
        AdminPlugin.short_description: "一句话推荐",
        AdminPlugin.long_description: "详细说明",
        AdminPlugin.version: "版本",
        AdminPlugin.install_url: "主安装源",
        AdminPlugin.chrome_store_url: "Chrome 链接",
        AdminPlugin.edge_store_url: "Edge 链接",
        AdminPlugin.direct_url: "直接网址",
        AdminPlugin.icon_url: "图标 URL",
        AdminPlugin.tags: "标签",
        AdminPlugin.developer_name: "开发者",
        AdminPlugin.developer_email: "开发者邮箱",
        AdminPlugin.submitter_id: "提交用户",
        AdminPlugin.review_note: "审核备注",
        AdminPlugin.website_url: "官网链接",
        AdminPlugin.support_url: "支持链接",
        AdminPlugin.cover_image: "封面图",
        AdminPlugin.gallery_images: "展示图集",
        AdminPlugin.status: "状态",
        AdminPlugin.is_featured: "首页精选",
        AdminPlugin.is_trending: "趋势榜",
        AdminPlugin.is_new: "新上架",
        AdminPlugin.sort_order: "排序",
        AdminPlugin.created_at: "创建时间",
        AdminPlugin.updated_at: "更新时间",
    }
    can_create = True
    can_edit = True
    can_delete = True

    async def on_model_change(self, data: dict, model: AdminPlugin, is_created: bool, request: Request) -> None:
        title = str(data.get("title") or getattr(model, "title", "") or "plugin").strip()
        slug = str(data.get("slug") or getattr(model, "slug", "") or "").strip().lower()
        if not slug:
            slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "plugin"
            slug = f"{slug[:64]}-{uuid.uuid4().hex[:8]}"
        data["slug"] = slug
        short_description = str(data.get("short_description") or data.get("description") or "").strip()
        long_description = str(data.get("long_description") or data.get("description") or short_description).strip()
        data["short_description"] = short_description
        data["long_description"] = long_description
        data["description"] = str(data.get("description") or short_description).strip()
        install_url = str(data.get("install_url") or data.get("chrome_store_url") or data.get("edge_store_url") or data.get("direct_url") or data.get("website_url") or "").strip()
        data["install_url"] = install_url
        data["website_url"] = str(data.get("website_url") or data.get("direct_url") or install_url).strip()
        data["version"] = str(data.get("version") or "1.0.0").strip()
        if not data.get("icon"):
            data["icon"] = title[:1].upper() or "◆"
        if not data.get("created_at"):
            data["created_at"] = int(getattr(model, "created_at", 0) or time.time())
        data["updated_at"] = int(time.time())


class PromptAdmin(ModelView, model=AdminPrompt):
    name = "提示词"
    name_plural = "提示词"
    icon = "fa-solid fa-wand-magic-sparkles"
    column_list = [AdminPrompt.id, AdminPrompt.title, AdminPrompt.model_engine, AdminPrompt.is_featured]
    column_searchable_list = [AdminPrompt.title, AdminPrompt.prompt_text]
    column_sortable_list = [AdminPrompt.id, AdminPrompt.created_at, AdminPrompt.updated_at]
    can_create = True
    can_edit = True
    can_delete = True


class CommentAdmin(ModelView, model=AdminComment):
    name = "评论"
    name_plural = "评论"
    icon = "fa-solid fa-comments"
    column_list = [AdminComment.id, AdminComment.content, AdminComment.user_id, AdminComment.target_type, AdminComment.target_id, AdminComment.created_at]
    column_searchable_list = [AdminComment.content, AdminComment.target_type]
    column_sortable_list = [AdminComment.id, AdminComment.created_at]
    can_create = True
    can_edit = True
    can_delete = True


class ShopCategoryAdmin(ModelView, model=AdminShopCategory):
    name = "商品分类"
    name_plural = "商品分类"
    icon = "fa-solid fa-layer-group"
    column_list = [AdminShopCategory.id, AdminShopCategory.name, AdminShopCategory.slug, AdminShopCategory.enabled, AdminShopCategory.sort_order]
    column_searchable_list = [AdminShopCategory.name, AdminShopCategory.slug, AdminShopCategory.description]
    column_sortable_list = [AdminShopCategory.id, AdminShopCategory.sort_order, AdminShopCategory.enabled]
    form_columns = [
        AdminShopCategory.name,
        AdminShopCategory.slug,
        AdminShopCategory.description,
        AdminShopCategory.enabled,
        AdminShopCategory.sort_order,
    ]
    column_labels = {
        AdminShopCategory.id: "ID",
        AdminShopCategory.name: "分类名称",
        AdminShopCategory.slug: "分类标识",
        AdminShopCategory.description: "分类说明",
        AdminShopCategory.enabled: "是否启用",
        AdminShopCategory.sort_order: "排序",
        AdminShopCategory.created_at: "创建时间",
        AdminShopCategory.updated_at: "更新时间",
    }
    can_create = True
    can_edit = True
    can_delete = True


class ShopProductAdmin(ModelView, model=AdminShopProduct):
    name = "商品"
    name_plural = "商品"
    icon = "fa-solid fa-box-open"
    column_list = [
        AdminShopProduct.id,
        AdminShopProduct.title,
        AdminShopProduct.category,
        AdminShopProduct.product_type,
        AdminShopProduct.price_cents,
        AdminShopProduct.stock,
        AdminShopProduct.status,
        AdminShopProduct.sort_order,
    ]
    column_searchable_list = [AdminShopProduct.title, AdminShopProduct.slug, AdminShopProduct.subtitle, AdminShopProduct.description]
    column_sortable_list = [AdminShopProduct.id, AdminShopProduct.price_cents, AdminShopProduct.stock, AdminShopProduct.sort_order]
    form_overrides = {
        "price_cents": YuanPriceField,
        "product_type": SelectField,
        "status": SelectField,
    }
    form_args = {
        "price_cents": {
            "label": "价格（元）",
            "places": 2,
            "validators": [Optional()],
            "description": "按人民币元填写，例如 199 或 199.00。",
        },
        "product_type": {
            "label": "商品类型",
            "choices": [("physical", "实物商品"), ("virtual", "虚拟商品")],
            "description": "实物需要物流或安装说明；虚拟商品可填写交付方式。",
        },
        "status": {
            "label": "状态",
            "choices": [("draft", "草稿"), ("published", "已上架"), ("hidden", "隐藏")],
        },
        "stock": {
            "label": "数量",
            "description": "填 -1 表示不限量。",
        },
        "cover_image": {
            "label": "封面图片",
            "description": "粘贴主图 URL。留空时会自动使用商品图集的第一张。",
        },
        "gallery_images": {
            "label": "商品图集",
            "description": "可粘贴多张商品图 URL，一行一张。",
        },
        "fulfillment_note": {
            "label": "服务 / 发货说明",
            "description": "可填写售后、安装、物流、交付方式等。",
        },
        "auto_delivery": {
            "label": "虚拟商品自动发货",
            "description": "仅虚拟商品生效。积分支付成功后会自动把下方交付内容发到用户邮箱。",
        },
        "delivery_subject": {
            "label": "自动发货邮件标题",
            "description": "留空则使用默认标题。",
        },
        "delivery_body": {
            "label": "自动发货内容",
            "description": "填写兑换码、下载链接、账号说明、服务入口等。只有自动发货开启且订单已通过时才发送。",
        },
        "description": {
            "label": "产品展示",
            "description": "可粘贴多图链接、详细说明、参数、服务承诺等。",
        },
    }
    form_columns = [
        AdminShopProduct.category,
        AdminShopProduct.title,
        AdminShopProduct.subtitle,
        AdminShopProduct.cover_image,
        AdminShopProduct.gallery_images,
        AdminShopProduct.stock,
        AdminShopProduct.price_cents,
        AdminShopProduct.product_type,
        AdminShopProduct.status,
        AdminShopProduct.fulfillment_note,
        AdminShopProduct.description,
        AdminShopProduct.auto_delivery,
        AdminShopProduct.delivery_subject,
        AdminShopProduct.delivery_body,
        AdminShopProduct.sort_order,
    ]
    column_labels = {
        AdminShopProduct.id: "ID",
        AdminShopProduct.category: "商品分类",
        AdminShopProduct.title: "商品标题",
        AdminShopProduct.slug: "商品标识",
        AdminShopProduct.subtitle: "规格 / 简介",
        AdminShopProduct.description: "产品展示",
        AdminShopProduct.cover_image: "封面图片",
        AdminShopProduct.gallery_images: "商品图集",
        AdminShopProduct.product_type: "商品类型",
        AdminShopProduct.price_cents: "价格（元）",
        AdminShopProduct.stock: "数量",
        AdminShopProduct.status: "状态",
        AdminShopProduct.fulfillment_note: "服务 / 发货说明",
        AdminShopProduct.auto_delivery: "虚拟商品自动发货",
        AdminShopProduct.delivery_subject: "自动发货邮件标题",
        AdminShopProduct.delivery_body: "自动发货内容",
        AdminShopProduct.sort_order: "排序",
        AdminShopProduct.created_at: "创建时间",
        AdminShopProduct.updated_at: "更新时间",
    }
    can_create = True
    can_edit = True
    can_delete = True

    async def on_model_change(self, data: dict, model: AdminShopProduct, is_created: bool, request: Request) -> None:
        price_yuan = data.get("price_cents") or 0
        data["price_cents"] = int(round(float(price_yuan) * 100))
        title = str(data.get("title") or getattr(model, "title", "") or "product").strip()
        current_slug = str(getattr(model, "slug", "") or "").strip()
        if "slug" not in data or not str(data.get("slug") or "").strip():
            base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "product"
            data["slug"] = current_slug or f"{base[:64]}-{uuid.uuid4().hex[:8]}"


class ShopOrderAdmin(ModelView, model=AdminShopOrder):
    name = "商城订单"
    name_plural = "商城订单"
    icon = "fa-solid fa-cart-shopping"
    column_list = [
        AdminShopOrder.id,
        AdminShopOrder.user,
        AdminShopOrder.product,
        AdminShopOrder.quantity,
        AdminShopOrder.amount_cents,
        AdminShopOrder.points_amount,
        AdminShopOrder.payment_method,
        AdminShopOrder.status,
        AdminShopOrder.created_at,
    ]
    column_searchable_list = [AdminShopOrder.id, AdminShopOrder.status, AdminShopOrder.customer_note, AdminShopOrder.admin_note]
    column_sortable_list = [AdminShopOrder.created_at, AdminShopOrder.amount_cents, AdminShopOrder.points_amount, AdminShopOrder.quantity]
    form_columns = [
        AdminShopOrder.user,
        AdminShopOrder.product,
        AdminShopOrder.quantity,
        AdminShopOrder.amount_cents,
        AdminShopOrder.points_amount,
        AdminShopOrder.payment_method,
        AdminShopOrder.status,
        AdminShopOrder.customer_note,
        AdminShopOrder.admin_note,
    ]
    column_labels = {
        AdminShopOrder.id: "订单号",
        AdminShopOrder.user: "用户",
        AdminShopOrder.product: "商品",
        AdminShopOrder.quantity: "数量",
        AdminShopOrder.amount_cents: "金额（美分）",
        AdminShopOrder.points_amount: "积分金额",
        AdminShopOrder.payment_method: "支付方式",
        AdminShopOrder.status: "订单状态",
        AdminShopOrder.customer_note: "用户备注",
        AdminShopOrder.admin_note: "管理员备注",
        AdminShopOrder.created_at: "创建时间",
        AdminShopOrder.updated_at: "更新时间",
    }
    can_create = True
    can_edit = True
    can_delete = True


class ToolsAdmin(BaseView):
    name = "工具功能管理"
    icon = "fa-solid fa-screwdriver-wrench"

    @expose("/tools", methods=["GET"])
    async def tools_page(self, request: Request):
        response = RedirectResponse("/admin-tools", status_code=302)
        _set_main_admin_cookie(response)
        return response


class ShopImageUploadAdmin(BaseView):
    name = "商城图片上传"
    icon = "fa-solid fa-image"

    @expose("/shop-image-upload", methods=["POST"])
    async def upload(self, request: Request):
        form = await request.form()
        upload = form.get("image")
        if not upload or not getattr(upload, "filename", ""):
            return JSONResponse({"detail": "请选择图片"}, status_code=400)
        content_type = (getattr(upload, "content_type", "") or "").lower()
        if not content_type.startswith("image/"):
            return JSONResponse({"detail": "请上传图片文件"}, status_code=400)
        content = await upload.read()
        if not content:
            return JSONResponse({"detail": "图片不能为空"}, status_code=400)
        if len(content) > 8 * 1024 * 1024:
            return JSONResponse({"detail": "图片不能超过 8MB"}, status_code=413)
        try:
            from PIL import Image, UnidentifiedImageError

            source = Image.open(BytesIO(content))
            source.verify()
            source = Image.open(BytesIO(content))
        except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
            return JSONResponse({"detail": "无法识别真实图片类型"}, status_code=400)
        SHOP_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
        source.thumbnail((2200, 2200))
        if source.mode not in {"RGB", "RGBA"}:
            source = source.convert("RGB")
        filename = f"shop-{uuid.uuid4().hex}.webp"
        source.save(SHOP_IMAGE_DIR / filename, "WEBP", quality=88, method=6)
        return JSONResponse({"url": f"/api/shop/images/{filename}"})


def _sqladmin_cookie_secret() -> str:
    key = (os.getenv("SQLADMIN_SECRET_KEY") or "").strip()
    if key:
        return key
    if os.getenv("MEETSEEK_DEV_INSECURE_JWT", "").lower() in {"1", "true", "yes"}:
        return "meetseek-sqladmin-session-dev-only"
    raise RuntimeError(
        "Set SQLADMIN_SECRET_KEY for /admin session signing (e.g. openssl rand -hex 32), "
        "or MEETSEEK_DEV_INSECURE_JWT=1 for local dev only."
    )


def setup_sqladmin(app: FastAPI, db_file: Path) -> None:
    engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )
    admin = Admin(
        app,
        engine,
        title="MeetSeek Admin",
        base_url="/admin",
        templates_dir=str(Path(__file__).parent / "templates"),
        authentication_backend=SqlAdminAuth(secret_key=_sqladmin_cookie_secret()),
    )
    admin.add_view(UserAdmin)
    admin.add_view(PostAdmin)
    admin.add_view(PluginAdmin)
    admin.add_view(PromptAdmin)
    admin.add_view(CommentAdmin)
    admin.add_view(CategoryAdmin)
    admin.add_view(ShopCategoryAdmin)
    admin.add_view(ShopProductAdmin)
    admin.add_view(ShopOrderAdmin)
    admin.add_view(CreditOrderAdmin)
    admin.add_view(AdSlotAdmin)
    admin.add_view(ContactSubmissionAdmin)
    admin.add_view(WechatGeoArticleAdmin)
    admin.add_base_view(ToolsAdmin)
    admin.add_base_view(ShopImageUploadAdmin)
