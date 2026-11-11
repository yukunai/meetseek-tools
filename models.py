from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class UserRole(str, enum.Enum):
    member = "member"
    moderator = "moderator"
    admin = "admin"


class ContentType(str, enum.Enum):
    short = "short"
    article = "article"
    tool = "tool"


class PostStatus(str, enum.Enum):
    draft = "draft"
    pending = "pending"
    published = "published"
    hidden = "hidden"
    deleted = "deleted"


class Visibility(str, enum.Enum):
    public = "public"
    members = "members"
    private = "private"


class InteractionType(str, enum.Enum):
    like = "like"
    bookmark = "bookmark"
    share = "share"
    report = "report"


class LedgerAction(str, enum.Enum):
    signup = "signup"
    checkin = "checkin"
    post_create = "post_create"
    comment_create = "comment_create"
    like_received = "like_received"
    tool_usage = "tool_usage"
    purchase = "purchase"
    admin_adjust = "admin_adjust"


class AdFormat(str, enum.Enum):
    banner = "banner"
    small_banner = "small_banner"
    tile = "tile"
    native_card = "native_card"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    nickname: Mapped[str | None] = mapped_column(String(80), index=True)
    display_name: Mapped[str] = mapped_column(String(80), index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    bio: Mapped[str | None] = mapped_column(String(280))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role"), default=UserRole.member, index=True)
    reputation: Mapped[int] = mapped_column(Integer, default=0, index=True)
    points: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    posts: Mapped[list[Post]] = relationship(back_populates="author", cascade="all, delete-orphan")
    comments: Mapped[list[Comment]] = relationship(back_populates="author", cascade="all, delete-orphan")
    interactions: Mapped[list[Interaction]] = relationship(back_populates="user", cascade="all, delete-orphan")
    point_entries: Mapped[list[PointLedger]] = relationship(back_populates="user", cascade="all, delete-orphan")
    favorite_prompts: Mapped[list[Favorite]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    type: Mapped[ContentType] = mapped_column(Enum(ContentType, name="content_type"), index=True)
    status: Mapped[PostStatus] = mapped_column(Enum(PostStatus, name="post_status"), default=PostStatus.draft, index=True)
    visibility: Mapped[Visibility] = mapped_column(Enum(Visibility, name="visibility"), default=Visibility.public, index=True)
    category_slug: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(180))
    slug: Mapped[str] = mapped_column(String(220), index=True)
    summary: Mapped[str | None] = mapped_column(String(320))
    body_text: Mapped[str | None] = mapped_column(Text)
    body_html: Mapped[str | None] = mapped_column(Text)
    blocks: Mapped[dict | None] = mapped_column(JSONB)
    cover_image_url: Mapped[str | None] = mapped_column(String(700))
    source_url: Mapped[str | None] = mapped_column(String(1000))
    source_meta: Mapped[dict | None] = mapped_column(JSONB)
    meta_title: Mapped[str | None] = mapped_column(String(220))
    meta_description: Mapped[str | None] = mapped_column(String(320))
    og_image: Mapped[str | None] = mapped_column(String(700))
    canonical_url: Mapped[str | None] = mapped_column(String(700))
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    comment_count: Mapped[int] = mapped_column(Integer, default=0)
    bookmark_count: Mapped[int] = mapped_column(Integer, default=0)
    share_count: Mapped[int] = mapped_column(Integer, default=0)
    pinned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), index=True)

    author: Mapped[User] = relationship(back_populates="posts")
    comments: Mapped[list[Comment]] = relationship(back_populates="post", cascade="all, delete-orphan")
    interactions: Mapped[list[Interaction]] = relationship(back_populates="post", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("category_slug", "slug", name="uq_posts_category_slug"),
        Index("ix_posts_public_feed", "status", "visibility", "pinned_at", "published_at"),
        Index("ix_posts_sitemap", "status", "visibility", "updated_at"),
        Index("ix_posts_author_created", "author_id", "created_at"),
    )


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class Prompt(Base):
    __tablename__ = "prompts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(180), index=True)
    cover_image: Mapped[str | None] = mapped_column(String(700))
    model_engine: Mapped[str] = mapped_column(String(180), default="", index=True)
    prompt_text: Mapped[str] = mapped_column(Text)
    negative_prompt: Mapped[str | None] = mapped_column(Text)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"), index=True)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), index=True)

    favorites: Mapped[list[Favorite]] = relationship(back_populates="prompt", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_prompts_featured_created", "is_featured", "created_at"),
    )


class Favorite(Base):
    __tablename__ = "favorites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    user: Mapped[User] = relationship(back_populates="favorite_prompts")
    prompt: Mapped[Prompt] = relationship(back_populates="favorites")

    __table_args__ = (
        UniqueConstraint("user_id", "prompt_id", name="uq_favorites_user_prompt"),
        Index("ix_favorites_user_created", "user_id", "created_at"),
    )


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("comments.id", ondelete="CASCADE"), index=True)
    body_text: Mapped[str] = mapped_column(Text)
    body_html: Mapped[str | None] = mapped_column(Text)
    status: Mapped[PostStatus] = mapped_column(Enum(PostStatus, name="comment_status"), default=PostStatus.published, index=True)
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    post: Mapped[Post] = relationship(back_populates="comments")
    author: Mapped[User] = relationship(back_populates="comments")
    parent: Mapped[Comment | None] = relationship(remote_side=[id], back_populates="replies")
    replies: Mapped[list[Comment]] = relationship(back_populates="parent", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_comments_post_created", "post_id", "created_at"),
    )


class Interaction(Base):
    __tablename__ = "interactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    type: Mapped[InteractionType] = mapped_column(Enum(InteractionType, name="interaction_type"), index=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    user: Mapped[User] = relationship(back_populates="interactions")
    post: Mapped[Post] = relationship(back_populates="interactions")

    __table_args__ = (
        UniqueConstraint("user_id", "post_id", "type", name="uq_interactions_user_post_type"),
        Index("ix_interactions_post_type", "post_id", "type"),
    )


class PointLedger(Base):
    __tablename__ = "point_ledger"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    action: Mapped[LedgerAction] = mapped_column(Enum(LedgerAction, name="ledger_action"), index=True)
    points: Mapped[int] = mapped_column(Integer)
    balance_after: Mapped[int] = mapped_column(Integer)
    related_type: Mapped[str | None] = mapped_column(String(50), index=True)
    related_id: Mapped[int | None] = mapped_column(Integer, index=True)
    note: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    user: Mapped[User] = relationship(back_populates="point_entries")

    __table_args__ = (
        CheckConstraint("points <> 0", name="points_not_zero"),
        Index("ix_point_ledger_user_created", "user_id", "created_at"),
    )


class AdSlot(Base):
    __tablename__ = "ad_slots"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    page: Mapped[str] = mapped_column(String(80), index=True)
    position: Mapped[str] = mapped_column(String(80), index=True)
    format: Mapped[AdFormat] = mapped_column(Enum(AdFormat, name="ad_format"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    creatives: Mapped[list[AdCreative]] = relationship(back_populates="slot", cascade="all, delete-orphan")


class AdCreative(Base):
    __tablename__ = "ad_creatives"

    id: Mapped[int] = mapped_column(primary_key=True)
    slot_id: Mapped[int] = mapped_column(ForeignKey("ad_slots.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    html_code: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(String(700))
    target_url: Mapped[str | None] = mapped_column(String(1000))
    weight: Mapped[int] = mapped_column(Integer, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    slot: Mapped[AdSlot] = relationship(back_populates="creatives")

    __table_args__ = (
        Index("ix_ad_creatives_slot_active", "slot_id", "is_active", "starts_at", "ends_at"),
    )


class Advertisement(Base):
    __tablename__ = "advertisements"

    id: Mapped[int] = mapped_column(primary_key=True)
    location: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    html_content: Mapped[str] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=100, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_advertisements_location_status", "location", "status", "sort_order"),
    )
