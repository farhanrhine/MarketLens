from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.db.database import Base


def utc_now():
    return datetime.now(timezone.utc)


class Competitor(Base):
    __tablename__ = "competitors"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    domain = Column(String(255), unique=True, nullable=False, index=True)
    normalized_domain = Column(String(255), nullable=False)
    blog_url = Column(String(1024), nullable=True)
    pricing_url = Column(String(1024), nullable=True)
    status = Column(String(50), default="ACTIVE", nullable=False)  # ACTIVE, NO_BLOG, BLOCKED
    created_at = Column(DateTime, default=utc_now, nullable=False)
    last_scan_at = Column(DateTime, nullable=True)

    scans = relationship("Scan", back_populates="competitor", cascade="all, delete-orphan", order_by="desc(Scan.started_at)")
    articles = relationship("Article", back_populates="competitor", cascade="all, delete-orphan")
    pricing_snapshots = relationship("PricingSnapshot", back_populates="competitor", cascade="all, delete-orphan")
    pricing_changes = relationship("PricingChange", back_populates="competitor", cascade="all, delete-orphan")

    def to_dict(self):
        # Safe async inspection: only read loaded relationships to avoid MissingGreenlet
        articles_count = len(self.articles) if "articles" in self.__dict__ and self.articles is not None else 0
        return {
            "id": self.id,
            "domain": self.domain,
            "normalized_domain": self.normalized_domain,
            "blog_url": self.blog_url,
            "pricing_url": self.pricing_url,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_scan_at": self.last_scan_at.isoformat() if self.last_scan_at else None,
            "articles_count": articles_count,
        }


class Scan(Base):
    __tablename__ = "scans"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    competitor_id = Column(Integer, ForeignKey("competitors.id", ondelete="CASCADE"), nullable=False, index=True)
    started_at = Column(DateTime, default=utc_now, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    status = Column(String(50), nullable=False)  # COMPLETED, FAILED, NO_BLOG, BLOCKED
    is_baseline = Column(Boolean, default=False, nullable=False)
    total_articles_found = Column(Integer, default=0, nullable=False)
    new_articles_found = Column(Integer, default=0, nullable=False)
    ai_summary = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)

    competitor = relationship("Competitor", back_populates="scans")
    articles = relationship("Article", back_populates="last_scan")

    def to_dict(self):
        return {
            "id": self.id,
            "competitor_id": self.competitor_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "status": self.status,
            "is_baseline": self.is_baseline,
            "total_articles_found": self.total_articles_found,
            "new_articles_found": self.new_articles_found,
            "ai_summary": self.ai_summary,
            "error_message": self.error_message,
        }


class Article(Base):
    __tablename__ = "articles"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    competitor_id = Column(Integer, ForeignKey("competitors.id", ondelete="CASCADE"), nullable=False, index=True)
    normalized_url = Column(String(1024), unique=True, nullable=False, index=True)
    title = Column(String(512), nullable=False)
    published_at = Column(DateTime, nullable=True)
    meta_description = Column(Text, nullable=True)
    target_keyword = Column(String(255), nullable=True)
    search_intent = Column(String(50), nullable=True)  # Informational, Commercial, Transactional
    search_volume = Column(Integer, nullable=True)
    enrichment_status = Column(String(50), default="PENDING", nullable=False)  # SUCCESS, FALLBACK_RULE, FAILED_KEY
    first_seen_at = Column(DateTime, default=utc_now, nullable=False)
    last_seen_at = Column(DateTime, default=utc_now, nullable=False)
    last_scan_id = Column(Integer, ForeignKey("scans.id", ondelete="SET NULL"), nullable=True)

    competitor = relationship("Competitor", back_populates="articles")
    last_scan = relationship("Scan", back_populates="articles")

    def to_dict(self):
        return {
            "id": self.id,
            "competitor_id": self.competitor_id,
            "normalized_url": self.normalized_url,
            "title": self.title,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "meta_description": self.meta_description,
            "target_keyword": self.target_keyword,
            "search_intent": self.search_intent,
            "search_volume": self.search_volume,
            "enrichment_status": self.enrichment_status,
            "first_seen_at": self.first_seen_at.isoformat() if self.first_seen_at else None,
            "last_seen_at": self.last_seen_at.isoformat() if self.last_seen_at else None,
            "last_scan_id": self.last_scan_id,
        }


class PricingSnapshot(Base):
    __tablename__ = "pricing_snapshots"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    competitor_id = Column(Integer, ForeignKey("competitors.id", ondelete="CASCADE"), nullable=False, index=True)
    pricing_url = Column(String(1024), nullable=False)
    content_hash = Column(String(128), nullable=False)
    plans_json = Column(Text, nullable=True)
    observed_at = Column(DateTime, default=utc_now, nullable=False)

    competitor = relationship("Competitor", back_populates="pricing_snapshots")

    def to_dict(self):
        return {
            "id": self.id,
            "competitor_id": self.competitor_id,
            "pricing_url": self.pricing_url,
            "content_hash": self.content_hash,
            "plans_json": self.plans_json,
            "observed_at": self.observed_at.isoformat() if self.observed_at else None,
        }


class PricingChange(Base):
    __tablename__ = "pricing_changes"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    competitor_id = Column(Integer, ForeignKey("competitors.id", ondelete="CASCADE"), nullable=False, index=True)
    detected_at = Column(DateTime, default=utc_now, nullable=False)
    summary = Column(Text, nullable=False)

    competitor = relationship("Competitor", back_populates="pricing_changes")

    def to_dict(self):
        return {
            "id": self.id,
            "competitor_id": self.competitor_id,
            "detected_at": self.detected_at.isoformat() if self.detected_at else None,
            "summary": self.summary,
        }
