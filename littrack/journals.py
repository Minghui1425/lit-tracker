"""期刊显示名、IF 与 JCR 分区。

注意：`if_data.json` 由用户用自己的 JCR 名单在本地生成，**不随本项目分发**
（JCR 数据有版权）。缺失时相关过滤自动跳过，不影响其余功能。
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

_NORM_RE = re.compile(r"[^a-z0-9]+")


def _norm(name: str) -> str:
    return _NORM_RE.sub("", (name or "").lower())


def _norm_loose(name: str) -> str:
    """宽松键：去掉独立的 and / the，兜住「A and B」vs「A & B」、
    「The Journal of X」vs「Journal of X」这类写法差异。
    须与 jcr.py 的同名函数保持一致。"""
    s = re.sub(r"[^\w\s]", " ", (name or "").lower())
    s = re.sub(r"\b(and|the)\b", " ", s)
    return _NORM_RE.sub("", s)


class JournalIndex:
    """按 ISSN / 期刊名查 IF 与分区。"""

    def __init__(self, data: dict | None = None):
        """data 为 jcr.build() 生成的结构：{"by_issn": {...}, "by_name": {...}}"""
        data = data if isinstance(data, dict) else {}
        self._by_issn: dict[str, dict] = dict(data.get("by_issn") or {})
        self._by_name: dict[str, dict] = dict(data.get("by_name") or {})
        self.generated: str = str(data.get("generated") or "")
        self.source: str = str(data.get("source") or "")

    @classmethod
    def empty(cls) -> "JournalIndex":
        return cls(None)

    @classmethod
    def load(cls, path: str | Path | None) -> "JournalIndex":
        if not path:
            return cls.empty()
        p = Path(path).expanduser()
        if not p.exists():
            log.warning(f"未找到 {p.name}，IF/分区过滤将跳过。"
                        f"如需启用：python3 cli.py import-if --excel <你的JCR名单.xlsx>")
            return cls.empty()
        try:
            return cls(json.loads(p.read_text(encoding="utf-8")))
        except Exception as e:
            log.warning(f"{p.name} 读取失败（{e}），IF/分区过滤将跳过")
            return cls.empty()

    @property
    def available(self) -> bool:
        return bool(self._by_issn or self._by_name)

    def _lookup(self, article: dict) -> dict | None:
        for issn in article.get("issns", []):
            rec = self._by_issn.get(issn.replace("-", ""))
            if rec:
                return rec
        for key in ("journal_full", "journal_abbr"):
            raw = article.get(key, "")
            rec = self._by_name.get(_norm(raw)) or self._by_name.get(_norm_loose(raw))
            if rec:
                return rec
        return None

    def impact(self, article: dict) -> tuple[str, str]:
        """返回 (IF 字符串, 分区)；查不到返回 ('', '')。"""
        rec = self._lookup(article)
        if not rec:
            return "", ""
        return str(rec.get("if", "") or ""), str(rec.get("quartile", "") or "")

    def passes_quality(self, article: dict, allowed_quartiles: list[str],
                       min_if: float) -> bool:
        """分区/IF 过滤。数据缺失时**放行**——宁可多收，不因缺数据而静默丢文章。"""
        if not self.available:
            return True
        rec = self._lookup(article)
        if not rec:
            return False
        q = str(rec.get("quartile", "") or "")
        if allowed_quartiles and q not in allowed_quartiles:
            return False
        try:
            if float(rec.get("if", 0) or 0) < min_if:
                return False
        except (TypeError, ValueError):
            return False
        return True

    @staticmethod
    def display_name(raw: str, mapping: dict[str, str]) -> str:
        """把 PubMed 返回的期刊名换成配置里的显示名。"""
        if not raw:
            return ""
        n = _norm(raw)
        for full, disp in mapping.items():
            if _norm(full) == n:
                return disp
        return raw
