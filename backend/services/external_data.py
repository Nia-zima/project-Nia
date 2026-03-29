from __future__ import annotations

import json
import logging
import re
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Literal, Optional, Protocol
from urllib.parse import quote

import requests

from backend.core.config import settings

logger = logging.getLogger(__name__)


ExternalCategory = Literal["fact_check", "definition", "data"]


class TextLLM(Protocol):
    def generate(self, prompt: str, max_tokens: int = 200) -> str:
        ...


@dataclass
class ExternalDataRequest:
    """外部データ取得のリクエスト。"""

    reason: str
    query: str
    category: ExternalCategory

    @staticmethod
    def has_clear_reasoning(reason: str, category: ExternalCategory) -> bool:
        required_patterns = {
            "fact_check": ["確認したい", "事実が不明", "年号", "人名", "日付", "発生年"],
            "definition": ["定義が曖昧", "用語の意味", "基準", "定義", "意味"],
            "data": ["数値", "統計", "比較データ", "比較", "データ"],
        }
        reason_norm = (reason or "").strip()
        if len(reason_norm) < 20:
            return False
        patterns = required_patterns.get(category, [])
        return any(p in reason_norm for p in patterns)

    def validate(self) -> bool:
        has_reason = self.has_clear_reasoning(self.reason, self.category)
        has_query = bool((self.query or "").strip())
        return has_reason and has_query


@dataclass
class ExternalDataResult:
    data: str
    source: str = "unknown"
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error: Optional[str] = None
    confidence: float = 0.0
    evidence: list[dict[str, Any]] = field(default_factory=list)
    contradiction_flag: bool = False


@dataclass
class ThinkingResult:
    thought: str
    external_reason: Optional[str] = None
    external_used: bool = False
    request: Optional[ExternalDataRequest] = None
    external_priority: float = 0.0
    external_confidence: float = 0.0
    contradiction_flag: bool = False


class LanguageGate:
    """言語化ゲート: 外部データ取得要否を判定する。"""

    def __init__(self, llm: TextLLM):
        self.llm = llm

    def generate_request(self, thought: str, context: Optional[dict[str, Any]] = None) -> Optional[ExternalDataRequest]:
        payload = context or {}
        prompt = (
            "あなたは外部データ取得判定器です。以下を厳密に守ってください。\n"
            "1) 必ずJSONのみを返す。説明文は禁止。\n"
            "2) 形式: "
            '{"need":true/false,"reason":"...","query":"...","category":"fact_check|definition|data"}\n'
            "3) need=false の場合は reason/query/category を空文字にする。\n"
            "4) need=true の場合、reasonは20文字以上で具体化する。\n\n"
            f"thought: {thought}\n"
            f"context: {json.dumps(payload, ensure_ascii=False)}"
        )
        raw = self.llm.generate(prompt, max_tokens=200)
        parsed = self._parse_json_response(raw)
        if not parsed:
            return None
        if not bool(parsed.get("need")):
            return None
        category = str(parsed.get("category") or "").strip()
        if category not in {"fact_check", "definition", "data"}:
            return None
        request = ExternalDataRequest(
            reason=str(parsed.get("reason") or "").strip(),
            query=str(parsed.get("query") or "").strip(),
            category=category,  # type: ignore[arg-type]
        )
        request.query = self._generate_safe_query(thought=thought, reason=request.reason, query=request.query)
        return request if request.validate() else None

    def _parse_json_response(self, response: str) -> Optional[dict[str, Any]]:
        text = (response or "").strip()
        if not text:
            return None

        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
        if fenced:
            text = fenced.group(1).strip()
        else:
            obj = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if obj:
                text = obj.group(0).strip()

        try:
            parsed = json.loads(text)
        except Exception:
            logger.debug("[ExternalData] JSON parse failed: %s", text[:200], exc_info=True)
            return None
        return parsed if isinstance(parsed, dict) else None

    def _generate_safe_query(self, *, thought: str, reason: str, query: str) -> str:
        # Query must represent uncertainty, not a guessed conclusion.
        reason_norm = (reason or "").strip()
        thought_norm = (thought or "").strip()
        query_norm = (query or "").strip()
        entity = self._extract_entity_hint(thought_norm)

        if any(k in reason_norm for k in ["年号", "発生年", "日付", "いつ"]):
            return f"{entity} いつ".strip() if entity else query_norm
        if any(k in reason_norm for k in ["人名", "誰"]):
            return f"{entity} 誰".strip() if entity else query_norm
        if any(k in reason_norm for k in ["定義", "意味", "用語"]):
            return f"{entity} 定義".strip() if entity else query_norm
        if any(k in reason_norm for k in ["数値", "統計", "比較"]):
            return f"{entity} 統計 比較".strip() if entity else query_norm

        # Remove hard-coded year assumptions to avoid baking guessed facts.
        return re.sub(r"\b(19|20)\d{2}\b", "", query_norm).strip() or query_norm

    def _extract_entity_hint(self, thought: str) -> str:
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9_\-]{1,30}|[一-龥ぁ-んァ-ンー]{2,24}", thought or "")
        if not tokens:
            return ""
        return tokens[0]


class ExternalDataBroker:
    """
    外部データ取得を担当するBroker。
    デフォルト無効、取得ログのみでも動作可能。
    """

    def __init__(self, enabled: bool = False, max_log_size: int = 200):
        self.enabled = enabled
        self._log_lock = threading.Lock()
        self._fetch_log: deque[dict[str, Any]] = deque(maxlen=max(1, max_log_size))
        self._feedback_log: deque[dict[str, Any]] = deque(maxlen=max(1, max_log_size))
        self.provider = settings.EXTERNAL_SEARCH_PROVIDER
        self.timeout_sec = settings.EXTERNAL_SEARCH_TIMEOUT_SEC
        self.result_limit = settings.EXTERNAL_SEARCH_RESULT_LIMIT
        self.min_confidence = settings.EXTERNAL_MIN_CONFIDENCE
        self._source_scores = {
            "google_custom_search": 0.80,
            "wikipedia": 0.65,
            "duckduckgo": 0.55,
        }

    @property
    def fetch_log(self) -> list[dict[str, Any]]:
        with self._log_lock:
            return list(self._fetch_log)

    def fetch(self, request: ExternalDataRequest) -> Optional[ExternalDataResult]:
        if not self.enabled:
            return None
        if not request.validate():
            return None

        result = self._execute_search(request)
        if result is not None:
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "reason": request.reason,
                "query": request.query,
                "category": request.category,
                "data_length": len(result.data or ""),
                "source": result.source,
                "error": result.error,
                "confidence": float(result.confidence or 0.0),
                "contradiction_flag": bool(result.contradiction_flag),
            }
            with self._log_lock:
                self._fetch_log.append(entry)
        return result

    def prioritize_requests(
        self,
        requests: list[ExternalDataRequest],
        *,
        surprise: float,
    ) -> list[tuple[ExternalDataRequest, float]]:
        ranked: list[tuple[ExternalDataRequest, float]] = []
        for req in requests:
            base = self.compute_priority(surprise=surprise, category=req.category)
            # Slight deterministic tie-breaker by category.
            bias = {"fact_check": 0.03, "data": 0.02, "definition": 0.0}.get(req.category, 0.0)
            ranked.append((req, max(0.0, min(1.0, base + bias))))
        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked

    def _execute_search(self, request: ExternalDataRequest) -> Optional[ExternalDataResult]:
        providers: list[str]
        if self.provider == "auto":
            providers = ["google", "wikipedia"]
        else:
            providers = [self.provider]

        results: list[ExternalDataResult] = []
        for provider in providers:
            if provider == "google":
                out = self._search_google(request.query)
            elif provider in {"wikipedia", "wiki"}:
                out = self._search_wikipedia(request.query)
            elif provider in {"duckduckgo", "ddg"}:
                out = self._search_duckduckgo(request.query)
            else:
                continue
            if out and (out.data or out.error):
                results.append(out)

        if not results:
            return None

        return self._aggregate_results(request.query, results)

    def _search_google(self, query: str) -> Optional[ExternalDataResult]:
        from backend.core.retry import retry_sync

        key = str(getattr(settings, "GOOGLE_API_KEY", "") or "").strip()
        cx = str(getattr(settings, "GOOGLE_CSE_ID", "") or "").strip()
        if not key or not cx:
            return None
        try:
            resp = retry_sync(
                lambda: requests.get(
                    "https://www.googleapis.com/customsearch/v1",
                    params={
                        "key": key,
                        "cx": cx,
                        "q": query,
                        "num": self.result_limit,
                        "lr": "lang_ja",
                        "safe": "off",
                    },
                    timeout=self.timeout_sec,
                ),
                max_retries=1,
                base_delay=1.0,
                retryable_exceptions=(requests.ConnectionError, requests.Timeout),
                service_name="google_search",
            )
            data = resp.json()
            if isinstance(data, dict) and data.get("error"):
                msg = str(data["error"].get("message") or "google search error")
                return ExternalDataResult(data="", source="google_custom_search", error=msg)
            items = (data or {}).get("items") or []
            lines: list[str] = []
            evidence: list[dict[str, Any]] = []
            for it in items[: self.result_limit]:
                title = str(it.get("title") or "").strip()
                snippet = self._clean_text(str(it.get("snippet") or ""))
                link = str(it.get("link") or "").strip()
                if title or snippet:
                    lines.append(f"- {title}\n  {snippet}\n  {link}")
                    evidence.append(
                        {
                            "source": "google_custom_search",
                            "title": title,
                            "url": link,
                            "snippet": snippet,
                            "source_score": self._source_scores["google_custom_search"],
                        }
                    )
            if not lines:
                return ExternalDataResult(data="", source="google_custom_search", error="no_results")
            result = ExternalDataResult(
                data="\n".join(lines),
                source="google_custom_search",
                evidence=evidence,
            )
            result.confidence = self._estimate_single_source_confidence(query=query, result=result)
            result.contradiction_flag = self._detect_contradiction(result.evidence)
            return result
        except Exception as e:
            return ExternalDataResult(data="", source="google_custom_search", error=str(e))

    def _search_wikipedia(self, query: str) -> Optional[ExternalDataResult]:
        from backend.core.retry import retry_sync

        try:
            resp = retry_sync(
                lambda: requests.get(
                    "https://ja.wikipedia.org/w/api.php",
                    params={
                        "action": "query",
                        "list": "search",
                        "srsearch": query,
                        "format": "json",
                        "srlimit": self.result_limit,
                        "utf8": 1,
                    },
                    timeout=self.timeout_sec,
                ),
                max_retries=1,
                base_delay=1.0,
                retryable_exceptions=(requests.ConnectionError, requests.Timeout),
                service_name="wikipedia_search",
            )
            data = resp.json()
            items = ((data or {}).get("query") or {}).get("search") or []
            lines: list[str] = []
            evidence: list[dict[str, Any]] = []
            for it in items[: self.result_limit]:
                title = str(it.get("title") or "").strip()
                snippet = self._clean_text(str(it.get("snippet") or ""))
                page = f"https://ja.wikipedia.org/wiki/{quote(title)}" if title else ""
                if title or snippet:
                    lines.append(f"- {title}\n  {snippet}\n  {page}")
                    evidence.append(
                        {
                            "source": "wikipedia",
                            "title": title,
                            "url": page,
                            "snippet": snippet,
                            "source_score": self._source_scores["wikipedia"],
                        }
                    )
            if not lines:
                return ExternalDataResult(data="", source="wikipedia", error="no_results")
            result = ExternalDataResult(
                data="\n".join(lines),
                source="wikipedia",
                evidence=evidence,
            )
            result.confidence = self._estimate_single_source_confidence(query=query, result=result)
            result.contradiction_flag = self._detect_contradiction(result.evidence)
            return result
        except Exception as e:
            return ExternalDataResult(data="", source="wikipedia", error=str(e))

    def _search_duckduckgo(self, query: str) -> Optional[ExternalDataResult]:
        from backend.core.retry import retry_sync

        try:
            resp = retry_sync(
                lambda: requests.get(
                    "https://api.duckduckgo.com/",
                    params={
                        "q": query,
                        "format": "json",
                        "no_redirect": "1",
                        "no_html": "1",
                        "kl": "jp-jp",
                    },
                    timeout=self.timeout_sec,
                ),
                max_retries=1,
                base_delay=1.0,
                retryable_exceptions=(requests.ConnectionError, requests.Timeout),
                service_name="duckduckgo_search",
            )
            data = resp.json() or {}
            lines: list[str] = []
            evidence: list[dict[str, Any]] = []
            abstract = self._clean_text(str(data.get("AbstractText") or ""))
            abstract_url = str(data.get("AbstractURL") or "").strip()
            if abstract:
                lines.append(f"- DuckDuckGo Abstract\n  {abstract}\n  {abstract_url}")
                evidence.append(
                    {
                        "source": "duckduckgo",
                        "title": "DuckDuckGo Abstract",
                        "url": abstract_url,
                        "snippet": abstract,
                        "source_score": self._source_scores["duckduckgo"],
                    }
                )
            related = data.get("RelatedTopics") or []
            count = 0
            for item in related:
                if count >= self.result_limit:
                    break
                text = ""
                first_url = ""
                if isinstance(item, dict):
                    text = self._clean_text(str(item.get("Text") or ""))
                    first_url = str(item.get("FirstURL") or "").strip()
                    if not text and isinstance(item.get("Topics"), list):
                        for sub in item["Topics"]:
                            text = self._clean_text(str((sub or {}).get("Text") or ""))
                            first_url = str((sub or {}).get("FirstURL") or "").strip()
                            if text:
                                break
                if text:
                    lines.append(f"- Related\n  {text}\n  {first_url}")
                    evidence.append(
                        {
                            "source": "duckduckgo",
                            "title": "Related",
                            "url": first_url,
                            "snippet": text,
                            "source_score": self._source_scores["duckduckgo"],
                        }
                    )
                    count += 1
            if not lines:
                return ExternalDataResult(data="", source="duckduckgo", error="no_results")
            result = ExternalDataResult(
                data="\n".join(lines),
                source="duckduckgo",
                evidence=evidence,
            )
            result.confidence = self._estimate_single_source_confidence(query=query, result=result)
            result.contradiction_flag = self._detect_contradiction(result.evidence)
            return result
        except Exception as e:
            return ExternalDataResult(data="", source="duckduckgo", error=str(e))

    def _clean_text(self, text: str) -> str:
        t = re.sub(r"<[^>]+>", " ", text or "")
        t = re.sub(r"\s+", " ", t).strip()
        return t

    def _aggregate_results(self, query: str, results: list[ExternalDataResult]) -> ExternalDataResult:
        evidence: list[dict[str, Any]] = []
        lines: list[str] = []
        sources: list[str] = []
        for r in results:
            if r.data:
                lines.append(r.data)
            evidence.extend(list(r.evidence or []))
            sources.append(r.source)
        contradiction = self._detect_contradiction(evidence)
        confidence = self._estimate_multi_source_confidence(query=query, evidence=evidence, contradiction=contradiction)
        source = ",".join(sorted(set(sources))) or "unknown"
        return ExternalDataResult(
            data="\n\n".join([ln for ln in lines if ln]),
            source=source,
            error=None if lines else "no_results",
            confidence=confidence,
            evidence=evidence,
            contradiction_flag=contradiction,
        )

    def _estimate_single_source_confidence(self, *, query: str, result: ExternalDataResult) -> float:
        src_score = self._source_scores.get(result.source, 0.50)
        align = self._query_alignment(query=query, evidence=result.evidence)
        # Single source has limited agreement evidence.
        confidence = 0.5 * src_score + 0.3 * 0.5 + 0.2 * align
        return max(0.0, min(1.0, confidence))

    def _estimate_multi_source_confidence(self, *, query: str, evidence: list[dict[str, Any]], contradiction: bool) -> float:
        if not evidence:
            return 0.0
        source_scores = [float(e.get("source_score") or self._source_scores.get(str(e.get("source") or ""), 0.5)) for e in evidence]
        src_score = sum(source_scores) / len(source_scores)
        agreement = self._cross_source_agreement(evidence)
        align = self._query_alignment(query=query, evidence=evidence)
        confidence = 0.5 * src_score + 0.3 * agreement + 0.2 * align
        if contradiction:
            confidence -= 0.25
        return max(0.0, min(1.0, confidence))

    def _cross_source_agreement(self, evidence: list[dict[str, Any]]) -> float:
        sources = {str(e.get("source") or "") for e in evidence if e.get("source")}
        if len(sources) <= 1:
            return 0.5
        years = []
        for e in evidence:
            txt = str(e.get("snippet") or "")
            years.extend(re.findall(r"(?:19|20)\d{2}", txt))
        uniq = {y for y in years}
        if not uniq:
            return 0.6
        if len(uniq) == 1:
            return 0.9
        return 0.2

    def _query_alignment(self, *, query: str, evidence: list[dict[str, Any]]) -> float:
        q_tokens = {t for t in re.findall(r"[A-Za-z0-9一-龥ぁ-んァ-ンー]{2,24}", query or "")}
        if not q_tokens:
            return 0.5
        joined = " ".join(str(e.get("title") or "") + " " + str(e.get("snippet") or "") for e in evidence)
        hits = sum(1 for t in q_tokens if t in joined)
        return max(0.0, min(1.0, hits / max(1, len(q_tokens))))

    def _detect_contradiction(self, evidence: list[dict[str, Any]]) -> bool:
        snippets_by_source: dict[str, str] = {}
        for e in evidence:
            src = str(e.get("source") or "unknown")
            txt = str(e.get("snippet") or "")
            snippets_by_source.setdefault(src, "")
            snippets_by_source[src] += " " + txt

        # 1. Year contradiction (cross-source)
        years_by_source: dict[str, set[str]] = {}
        for src, txt in snippets_by_source.items():
            found = set(re.findall(r"(?:19|20)\d{2}", txt))
            if found:
                years_by_source[src] = found
        if len(years_by_source) >= 2:
            all_years = set()
            for ys in years_by_source.values():
                all_years |= ys
            if len(all_years) >= 2:
                return True

        # 2. Numeric+unit contradiction (cross-source)
        _NUM_UNIT = re.compile(
            r"([\d,]+(?:\.\d+)?)\s*(万|億|兆|人|件|%|パーセント|ドル|円|km|kg|m²|ha)"
        )
        vals_by_source: dict[str, list[tuple[float, str]]] = {}
        for src, txt in snippets_by_source.items():
            for num_str, unit in _NUM_UNIT.findall(txt):
                unit_norm = "%" if unit == "パーセント" else unit
                try:
                    val = float(num_str.replace(",", ""))
                except ValueError:
                    continue
                vals_by_source.setdefault(src, []).append((val, unit_norm))

        sources = list(vals_by_source.keys())
        for i in range(len(sources)):
            for j in range(i + 1, len(sources)):
                for val_i, u_i in vals_by_source[sources[i]]:
                    for val_j, u_j in vals_by_source[sources[j]]:
                        if u_i != u_j or val_i == 0 or val_j == 0:
                            continue
                        ratio = max(val_i, val_j) / min(val_i, val_j)
                        if ratio >= 2.0:
                            return True

        return False

    def record_feedback(
        self,
        *,
        category: ExternalCategory,
        useful: bool,
        source: str = "",
        error: Optional[str] = None,
    ) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "category": category,
            "useful": bool(useful),
            "source": source,
            "error": error,
        }
        with self._log_lock:
            self._feedback_log.append(entry)

    def category_feedback(self, category: ExternalCategory) -> dict[str, float]:
        with self._log_lock:
            rows = [r for r in self._feedback_log if r.get("category") == category]
        total = len(rows)
        useful = sum(1 for r in rows if bool(r.get("useful")))
        success_rate = (useful / total) if total > 0 else 0.0
        return {
            "total": float(total),
            "useful": float(useful),
            "success_rate": float(success_rate),
        }

    def compute_priority(self, *, surprise: float, category: ExternalCategory) -> float:
        base = max(0.0, min(1.0, float(surprise)))
        fb = self.category_feedback(category)
        total = int(fb["total"])
        success = float(fb["success_rate"])
        # Enough history -> adapt priority.
        if total >= 5:
            if success >= 0.8:
                base += 0.05
            elif success <= 0.4:
                base -= 0.10
        return max(0.0, min(1.0, base))

    def get_statistics(self) -> dict[str, Any]:
        by_category: dict[str, int] = {}
        for row in self._fetch_log:
            cat = str(row.get("category") or "unknown")
            by_category[cat] = by_category.get(cat, 0) + 1
        feedback_by_category: dict[str, dict[str, float]] = {}
        for cat in ("fact_check", "definition", "data"):
            feedback_by_category[cat] = self.category_feedback(cat)  # type: ignore[arg-type]
        return {
            "total_fetches": len(self._fetch_log),
            "by_category": by_category,
            "recent": list(self._fetch_log)[-10:],
            "feedback": feedback_by_category,
            "min_confidence": float(self.min_confidence),
        }


class ThinkingProcess:
    """思考生成 + 深度制約 + 言語化ゲート + Broker連携。"""

    def __init__(
        self,
        llm: TextLLM,
        *,
        min_depth_for_external: int = 3,
        language_gate: Optional[LanguageGate] = None,
        broker: Optional[ExternalDataBroker] = None,
        surprise_calculator: Optional[Callable[[str, dict[str, Any]], float]] = None,
    ):
        self.llm = llm
        self.min_depth = min_depth_for_external
        self.language_gate = language_gate or LanguageGate(llm)
        self.broker = broker or ExternalDataBroker(enabled=False)
        self.surprise_calculator = surprise_calculator or (lambda _thought, _ctx: 0.0)

    def process(self, user_input: str, depth: int) -> ThinkingResult:
        thought = self._generate_thought(user_input, depth)
        return self.process_existing_thought(thought=thought, user_input=user_input, depth=depth)

    def process_existing_thought(
        self,
        *,
        thought: str,
        user_input: str,
        depth: int,
        context: Optional[dict[str, Any]] = None,
    ) -> ThinkingResult:
        ctx = dict(context or {})
        force_fetch = bool(ctx.get("force_fetch"))
        if not force_fetch and depth < self.min_depth:
            return ThinkingResult(thought=thought)

        # force_fetch 時は LanguageGate LLM 呼び出しをスキップ（既にユーザーが明示要求済み）
        request = None
        if not force_fetch:
            request = self.language_gate.generate_request(
                thought,
                {"depth": depth, "user_input": user_input, **ctx},
            )
        candidates = self._extract_candidate_requests(
            ctx.get("candidate_requests"), force_fetch=force_fetch,
        )
        if request is not None:
            candidates.append(request)
        if not candidates:
            return ThinkingResult(thought=thought)

        surprise = float(self.surprise_calculator(thought, {"user_input": user_input, "depth": depth, **ctx}) or 0.0)
        logger.info("[EXTERNAL_THINK] candidates=%d depth=%d surprise=%.2f force=%s", len(candidates), depth, surprise, force_fetch)
        for c in candidates:
            logger.info("[EXTERNAL_THINK] candidate: cat=%s query=%s", c.category, c.query[:60])
        fetchable = [r for r in candidates if self._should_fetch(request=r, depth=depth, surprise=surprise)]
        logger.info("[EXTERNAL_THINK] fetchable=%d", len(fetchable))
        if not fetchable:
            first = candidates[0]
            priority = self.broker.compute_priority(surprise=surprise, category=first.category)
            return ThinkingResult(thought=thought, request=first, external_priority=priority)

        ranked = self.broker.prioritize_requests(fetchable, surprise=surprise)
        last_error: Optional[str] = None
        last_external: Optional[ExternalDataResult] = None
        for req, priority in ranked:
            external = self.broker.fetch(req)
            last_external = external
            logger.info(
                "[EXTERNAL_THINK] fetch result: data_len=%d conf=%.2f contradict=%s err=%s src=%s",
                len(external.data or "") if external else 0,
                float(external.confidence or 0) if external else 0,
                bool(external.contradiction_flag) if external else None,
                external.error if external else "no_result",
                external.source if external else "none",
            )
            # force_fetch 時はユーザー明示要求なので confidence 閾値を緩める (0.3)
            effective_min_conf = 0.3 if force_fetch else float(self.broker.min_confidence)
            if external and external.data and float(external.confidence or 0.0) >= effective_min_conf and not bool(external.contradiction_flag):
                self.broker.record_feedback(
                    category=req.category,
                    useful=True,
                    source=external.source,
                    error=external.error,
                )
                integrated = self._integrate_external_data(thought, external.data)
                return ThinkingResult(
                    thought=integrated,
                    external_reason=req.reason,
                    external_used=True,
                    request=req,
                    external_priority=priority,
                    external_confidence=float(external.confidence or 0.0),
                    contradiction_flag=bool(external.contradiction_flag),
                )
            last_error = external.error if external else "fetch_failed"
            self.broker.record_feedback(
                category=req.category,
                useful=False,
                source=(external.source if external else ""),
                error=last_error,
            )
        return ThinkingResult(
            thought=thought,
            external_reason=None,
            external_used=False,
            request=ranked[0][0] if ranked else candidates[0],
            external_priority=ranked[0][1] if ranked else 0.0,
            external_confidence=float((last_external.confidence if last_external else 0.0) or 0.0),
            contradiction_flag=bool((last_external.contradiction_flag if last_external else False) or False),
        )

    def _should_fetch(self, *, request: ExternalDataRequest, depth: int, surprise: float) -> bool:
        if depth < self.min_depth:
            return False
        if depth < 6:
            if request.category not in {"fact_check", "data"}:
                return False
            required = self._required_surprise_threshold(category=request.category)
            return surprise > required
        return True

    def _required_surprise_threshold(self, *, category: ExternalCategory) -> float:
        base = 0.8 if category == "fact_check" else 0.85
        feedback = self.broker.category_feedback(category)
        total = int(feedback["total"])
        success = float(feedback["success_rate"])
        # Feedback loop: low-quality category needs stronger trigger.
        if total >= 5:
            if success <= 0.4:
                base += 0.1
            elif success >= 0.8:
                base -= 0.05
        return max(0.5, min(0.95, base))

    def _extract_candidate_requests(
        self, raw: Any, *, force_fetch: bool = False,
    ) -> list[ExternalDataRequest]:
        out: list[ExternalDataRequest] = []
        if not isinstance(raw, list):
            return out
        for item in raw:
            req: Optional[ExternalDataRequest] = None
            if isinstance(item, ExternalDataRequest):
                req = item
            elif isinstance(item, dict):
                category = str(item.get("category") or "").strip()
                if category in {"fact_check", "definition", "data"}:
                    req = ExternalDataRequest(
                        reason=str(item.get("reason") or "").strip(),
                        query=str(item.get("query") or "").strip(),
                        category=category,  # type: ignore[arg-type]
                    )
            # force_fetch 時は validate をスキップ（ユーザー明示要求）
            if req and (force_fetch or req.validate()):
                out.append(req)
        return out

    def _generate_thought(self, user_input: str, depth: int) -> str:
        prompt = (
            "次の入力に対する思考を生成してください。\n"
            f"depth: {depth}\n"
            f"input: {user_input}\n"
            "要点を短くまとめること。"
        )
        return (self.llm.generate(prompt, max_tokens=240) or "").strip()

    def _integrate_external_data(self, thought: str, data: str) -> str:
        prompt = (
            "外部データをもとに、質問への回答を日本語で1〜3文にまとめてください。\n"
            "タメ口で、表やリストは使わず自然な文章で答えること。\n"
            "データに含まれない情報は推測せず、わかる範囲だけ伝えること。\n\n"
            f"質問の文脈: {thought}\n"
            f"外部データ: {data}\n"
        )
        return (self.llm.generate(prompt, max_tokens=240) or "").strip()
