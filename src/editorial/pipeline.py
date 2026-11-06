from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from src.analyzers.ai_provider import AIProvider, ProviderFactory
from src.config.settings import Settings
from src.editorial.analysis import (
    build_analysis_markdown,
    build_sources_markdown,
    normalize_analysis,
)
from src.editorial.models import (
    EditorialArticle,
    EditorialDraft,
    ResearchSource,
    SelfQuality,
    TopicCandidate,
    kst_now,
)
from src.editorial.profiles import BlogProfile
from src.editorial.prompts import SYSTEM_PROMPT, build_article_prompt, build_topic_prompt
from src.editorial.publisher import EditorialTistoryPublisher, target_for_profile
from src.editorial.quality import assess_quality, decide_publication
from src.editorial.research import GoogleNewsResearchClient, select_sources_for_topic
from src.editorial.state import EditorialState
from src.editorial.text import safe_slug

logger = logging.getLogger(__name__)

_CITATION = re.compile(r"\[S(\d+)\]")


class EditorialError(RuntimeError):
    pass


@dataclass
class EditorialRunResult:
    blog: str
    decision: str = "DO NOT PUBLISH"
    quality_total: float = 0.0
    title: str = ""
    url: str = ""
    reason: str = ""
    report_path: str = ""
    draft_path: str = ""
    skipped: bool = False
    error: str = ""


class EditorialPipeline:
    def __init__(
        self,
        profile: BlogProfile,
        settings: Settings,
        *,
        provider: AIProvider | None = None,
        research_client: Any | None = None,
        state: EditorialState | None = None,
        publisher: Any | None = None,
        now_fn: Any | None = None,
    ) -> None:
        self.profile = profile
        self.settings = settings
        self.provider = provider
        self.research_client = research_client or GoogleNewsResearchClient()
        self.state = state or EditorialState(profile.key)
        self.publisher = publisher
        self.now_fn = now_fn or kst_now

    # ------------------------------------------------------------------ entry
    def run(self, *, dry_run: bool = False, force: bool = False, allow_mock: bool = False) -> EditorialRunResult:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        try:
            return self._run(run_id=run_id, dry_run=dry_run, force=force, allow_mock=allow_mock)
        except Exception as exc:  # noqa: BLE001 - surface a structured failure
            logger.exception("[editorial:%s] run failed", self.profile.key)
            report = {
                "blog": self.profile.key,
                "run_id": run_id,
                "error": str(exc),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            try:
                path = self.state.save_run(report, run_id=run_id)
            except Exception:  # noqa: BLE001
                path = None
            return EditorialRunResult(
                blog=self.profile.key,
                error=str(exc),
                report_path=str(path) if path else "",
            )

    def _run(
        self,
        *,
        run_id: str,
        dry_run: bool,
        force: bool,
        allow_mock: bool,
    ) -> EditorialRunResult:
        now = self.now_fn()
        if not force and self.state.published_today(now) >= self.profile.max_articles_per_day:
            reason = (
                f"{self.profile.key}: 오늘 이미 {self.profile.max_articles_per_day}건 발행됨 "
                f"(KST {now.date().isoformat()})"
            )
            logger.info("[editorial:%s] skip: %s", self.profile.key, reason)
            return EditorialRunResult(blog=self.profile.key, skipped=True, reason=reason)

        provider = self._get_provider()
        if provider.name == "mock" and not allow_mock:
            raise EditorialError(
                "AI provider가 mock입니다. 실제 OpenAI/Anthropic 키와 AI_PROVIDER를 설정해야 "
                "Crystal/Quartz 글을 생성할 수 있습니다. (mock 결과는 발행하지 않습니다.)"
            )

        sources = self.research_client.fetch(self.profile.topic_queries)
        if len(sources) < self.profile.min_sources:
            raise EditorialError(
                f"리서치 출처가 부족합니다: {len(sources)}개 < 최소 {self.profile.min_sources}개"
            )

        recent_records = self.state.recent_records(self.profile.recent_window)
        recent_titles = [str(record.get("title") or "") for record in recent_records if record.get("title")]

        topic = self._select_topic(provider, sources, recent_titles)
        selected_sources = select_sources_for_topic(
            sources,
            topic.topic,
            max_sources=12,
            required_ids=topic.source_ids,
        )
        if len(selected_sources) < self.profile.min_sources:
            selected_sources = sources[:12]

        raw = self._generate_article(provider, topic, selected_sources)
        analysis_validation = normalize_analysis(raw.get("analysis") or {}, self.profile)
        selected_ids = {source.source_id for source in selected_sources}
        invalid_analysis_sources = sorted(set(analysis_validation.analysis.data_sources) - selected_ids)
        if invalid_analysis_sources:
            analysis_validation.errors.append(
                "분석 data_sources에 리서치 풀 밖 ID가 있음: " + ", ".join(invalid_analysis_sources)
            )

        body = str(raw.get("body_markdown") or "").strip()
        if not body:
            raise EditorialError("AI가 본문(body_markdown)을 반환하지 않았습니다.")

        final_sources = self._final_sources(body, analysis_validation.analysis, selected_sources)
        title = str(raw.get("title") or "").strip()
        slug = safe_slug(
            str(raw.get("slug") or ""),
            fallback=f"{self.profile.key}-{now.date().isoformat()}",
        )
        self_quality = self._self_quality(raw.get("self_quality"))

        draft = EditorialDraft(
            blog=self.profile.key,
            title=title,
            slug=slug,
            meta_description=str(raw.get("meta_description") or "").strip(),
            primary_keyword=str(raw.get("primary_keyword") or topic.primary_keyword or "").strip(),
            secondary_keywords=[str(item) for item in (raw.get("secondary_keywords") or []) if str(item).strip()],
            category=str(raw.get("category") or topic.category or self.profile.default_category).strip(),
            tags=[str(item) for item in (raw.get("tags") or []) if str(item).strip()],
            body_markdown=body,
            analysis=analysis_validation.analysis,
            sources=final_sources,
            source_notes=[item for item in (raw.get("source_notes") or []) if isinstance(item, dict)],
            self_quality=self_quality,
            topic=topic,
        )

        body_with_analysis = body + "\n\n" + build_analysis_markdown(draft.analysis, self.profile)
        draft_for_quality = draft.model_copy(update={"body_markdown": body_with_analysis})
        report = assess_quality(
            draft_for_quality,
            self.profile,
            sources,
            recent_records,
            analysis_errors=analysis_validation.errors,
            analysis_warnings=analysis_validation.warnings,
            provider_name=provider.name,
            raw_body=body,
        )
        decision, reason = decide_publication(report, self.profile)

        body_with_sources = body_with_analysis + "\n\n" + build_sources_markdown(final_sources, self.profile)
        article = EditorialArticle(
            article_id=f"{self.profile.key}-{now.date().isoformat()}-{slug[:24]}",
            blog=self.profile.key,
            title=title,
            slug=slug,
            meta_description=draft.meta_description,
            primary_keyword=draft.primary_keyword,
            secondary_keywords=draft.secondary_keywords,
            category=draft.category,
            tags=draft.tags,
            body_markdown=body_with_analysis,
            body_with_sources=body_with_sources,
            analysis=draft.analysis,
            sources=final_sources,
            source_notes=draft.source_notes,
            topic=topic,
            quality=report,
            decision=decision,
            decision_reason=reason,
            created_at=now.isoformat(),
        )

        report_payload = article.to_report()
        report_payload["run"] = {
            "run_id": run_id,
            "blog": self.profile.key,
            "blog_url": self.profile.blog_url,
            "provider": provider.name,
            "dry_run": dry_run,
            "research_source_count": len(sources),
            "selected_source_count": len(selected_sources),
            "topic": topic.model_dump(),
            "source_notes": draft.source_notes,
            "warnings": report.warnings,
        }
        report_path = self.state.save_run(report_payload, run_id=run_id)
        draft_path, _ = self.state.save_draft(article, run_id=run_id)

        result = EditorialRunResult(
            blog=self.profile.key,
            decision=decision,
            quality_total=report.total,
            title=title,
            reason=reason,
            report_path=str(report_path),
            draft_path=str(draft_path),
        )

        if decision != "PUBLISH":
            logger.warning("[editorial:%s] not published: %s", self.profile.key, reason)
            return result

        if dry_run:
            logger.info("[editorial:%s] dry run: quality passed, publish skipped", self.profile.key)
            result.reason = reason + " (dry run: 발행 생략)"
            return result

        publisher = self.publisher or EditorialTistoryPublisher(
            self.settings,
            target_for_profile(self.profile, dry_run=False),
        )
        publish_result = publisher.publish(article)
        if not publish_result.ok:
            result.error = publish_result.message or "publish failed"
            result.reason = f"발행 실패: {publish_result.error_code} {publish_result.message}"
            report_payload["publish"] = {
                "ok": False,
                "error_code": publish_result.error_code,
                "message": publish_result.message,
            }
            self.state.save_run(report_payload, run_id=f"{run_id}-publish-failed")
            logger.error("[editorial:%s] publish failed: %s", self.profile.key, result.reason)
            return result

        article.published_url = publish_result.url
        article.published_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        record = self.state.record_from_article(article, url=publish_result.url)
        self.state.save_published(record)
        self.state.save_content_archive(article)
        report_payload["publish"] = {
            "ok": True,
            "url": publish_result.url,
            "published_at": article.published_at,
        }
        self.state.save_run(report_payload, run_id=run_id)

        result.url = publish_result.url
        result.reason = reason
        logger.info("[editorial:%s] published: %s", self.profile.key, publish_result.url)
        return result

    # ------------------------------------------------------------------ AI
    def _get_provider(self) -> AIProvider:
        if self.provider is None:
            self.provider = ProviderFactory(self.settings).build()
        return self.provider

    def _select_topic(
        self,
        provider: AIProvider,
        sources: list[ResearchSource],
        recent_titles: list[str],
    ) -> TopicCandidate:
        prompt = build_topic_prompt(self.profile, sources, recent_titles)
        last_error = ""
        for attempt in range(2):
            raw = provider.chat_json(SYSTEM_PROMPT, prompt, temperature=0.2)
            try:
                topic = TopicCandidate.model_validate(raw)
            except Exception as exc:  # noqa: BLE001
                last_error = f"토픽 JSON 검증 실패: {exc}"
                prompt += f"\n\nPrevious answer was invalid: {last_error}. Return the required JSON shape."
                continue

            valid_ids = {source.source_id for source in sources}
            topic.source_ids = [source_id for source_id in topic.source_ids if source_id in valid_ids]
            if topic.topic.strip() and len(topic.source_ids) >= 2:
                return topic
            last_error = (
                "토픽이 비어 있거나 유효한 source_ids가 2개 미만입니다. "
                "제공된 출처 ID만 사용하세요."
            )
            prompt += f"\n\nPrevious answer was invalid: {last_error}"
        raise EditorialError(f"토픽 선정 실패: {last_error}")

    def _generate_article(
        self,
        provider: AIProvider,
        topic: TopicCandidate,
        sources: list[ResearchSource],
    ) -> dict[str, Any]:
        prompt = build_article_prompt(self.profile, topic, sources)
        raw = provider.chat_json(SYSTEM_PROMPT, prompt, temperature=0.3)
        if not isinstance(raw, dict):
            raise EditorialError("AI 기사 응답이 JSON 객체가 아닙니다.")
        if not str(raw.get("body_markdown") or "").strip():
            raise EditorialError("AI 기사 응답에 body_markdown이 없습니다.")
        return raw

    @staticmethod
    def _self_quality(raw: Any) -> SelfQuality | None:
        if not isinstance(raw, dict):
            return None
        try:
            quality = SelfQuality.model_validate(raw)
        except Exception:  # noqa: BLE001
            return None
        component_total = round(
            quality.factual_accuracy
            + quality.originality
            + quality.search_intent
            + quality.source_quality
            + quality.readability
            + quality.seo_quality,
            2,
        )
        if not quality.total and component_total:
            quality.total = component_total
        return quality

    @staticmethod
    def _final_sources(
        body: str,
        analysis: Any,
        selected_sources: list[ResearchSource],
    ) -> list[ResearchSource]:
        cited = {f"S{number}" for number in _CITATION.findall(body or "")}
        cited |= {str(source_id) for source_id in (analysis.data_sources or [])}
        final = [source for source in selected_sources if source.source_id in cited]
        for source in selected_sources:
            if len(final) >= 3:
                break
            if source not in final:
                final.append(source)
        return final
