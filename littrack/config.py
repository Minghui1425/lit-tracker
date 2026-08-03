"""配置加载与校验。

目标用户是医生而非程序员，因此校验的重点不是"能不能跑"，而是**错误信息能不能看懂**：
每条报错都要指出「哪个板块、哪个字段、期望什么、你写了什么」。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:                                   # pragma: no cover
    raise SystemExit("缺少依赖 PyYAML，请先运行：pip3 install -r requirements.txt")


class ConfigError(Exception):
    """配置有误。消息面向非程序员，应可直接照着修改。"""


# 匹配器：本项目只开放两种。第三种「触发词×实体词×语境门控」需要大量领域语义
# （如判断器官词其实指癌种、区分强弱实体词），难以配置化，故不对外开放。
MATCHERS = ("simple_keyword", "cross_product")

# ── PubMed 文章类型总表 ───────────────────────────────────────────────────────
# (英文名, 中文, 建议) —— 建议 ∈ 保留 / 排除 / 视情况，只是给用户的默认倾向，不强制。
#
# 英文名必须与 PubMed XML 里 <PublicationType> 的写法**逐字一致**，否则筛选静默失效。
# 本表每一条都拿 `"X"[pt]` 实际检索验证过，不是凭印象写的。踩过的坑：
#   · Erratum ✗ → Published Erratum ✓      （旧版示例配置里写的就是 Erratum，从未生效）
#   · Retraction of Publication ✗ → Retraction Notice ✓（撤稿声明本身）
#     另有 Retracted Publication ✓，指「被撤掉的那篇原文」，两者不是一回事
# 带逗号的类型（Clinical Trial, Phase III）在 Excel 里也能正常填，见 excel.py 的切分逻辑。
PUB_TYPES: list[tuple[str, str, str]] = [
    # —— 原始研究 ——
    ("Journal Article",             "期刊论文（绝大多数研究都带这个）", "保留"),
    ("Randomized Controlled Trial", "随机对照试验",                     "保留"),
    ("Controlled Clinical Trial",   "对照临床试验（非随机）",           "保留"),
    ("Clinical Trial",              "临床试验（未分期的统称）",         "保留"),
    ("Clinical Trial, Phase I",     "I 期临床试验",                     "保留"),
    ("Clinical Trial, Phase II",    "II 期临床试验",                    "保留"),
    ("Clinical Trial, Phase III",   "III 期临床试验",                   "保留"),
    ("Clinical Trial, Phase IV",    "IV 期临床试验（上市后）",          "保留"),
    ("Pragmatic Clinical Trial",    "实用性临床试验",                   "保留"),
    ("Adaptive Clinical Trial",     "适应性设计试验",                   "保留"),
    ("Equivalence Trial",           "等效性试验",                       "保留"),
    ("Observational Study",         "观察性研究（队列/病例对照等）",    "保留"),
    ("Comparative Study",           "比较性研究",                       "保留"),
    ("Multicenter Study",           "多中心研究",                       "保留"),
    ("Evaluation Study",            "评价性研究",                       "保留"),
    ("Validation Study",            "验证性研究",                       "保留"),
    ("Twin Study",                  "双生子研究",                       "保留"),
    ("Clinical Study",              "临床研究（较旧的统称）",           "保留"),
    ("Technical Report",            "技术报告",                         "视情况"),
    # —— 综述与证据合成 ——
    ("Review",                      "综述（含叙述性综述，量很大）",     "保留"),
    ("Systematic Review",           "系统综述",                         "保留"),
    ("Meta-Analysis",               "荟萃分析",                         "保留"),
    ("Scoping Review",              "范围综述",                         "保留"),
    ("Evidence Synthesis",          "证据合成",                         "保留"),
    # —— 指南与共识 ——
    ("Practice Guideline",          "临床实践指南",                     "保留"),
    ("Guideline",                   "指南（范围更宽）",                 "保留"),
    ("Consensus Statement",         "共识声明",                         "保留"),
    ("Consensus Development Conference, NIH", "NIH 共识会议",           "视情况"),
    # —— 视情况 ——
    ("Case Reports",                "病例报告（注意是复数）",           "视情况"),
    ("Clinical Trial Protocol",     "试验方案（只有设计，没有结果）",   "视情况"),
    ("Preprint",                    "预印本（未经同行评议）",           "视情况"),
    ("Dataset",                     "数据集",                           "视情况"),
    ("English Abstract",            "非英文原文但有英文摘要",           "视情况"),
    ("Historical Article",          "医学史类",                         "视情况"),
    ("Introductory Journal Article", "专题导读",                        "视情况"),
    ("Personal Narrative",          "个人叙事",                         "视情况"),
    # —— 通常排除：非研究性内容 ——
    ("Editorial",                   "社论",                             "排除"),
    ("Letter",                      "读者来信",                         "排除"),
    ("Comment",                     "评论（对某篇文章的点评）",         "排除"),
    ("News",                        "新闻报道",                         "排除"),
    ("Newspaper Article",           "报纸文章",                         "排除"),
    ("Interview",                   "访谈",                             "排除"),
    ("Biography",                   "人物传记",                         "排除"),
    ("Autobiography",               "自传",                             "排除"),
    ("Portrait",                    "人物照片/小传",                    "排除"),
    ("Address",                     "演讲致辞",                         "排除"),
    ("Lecture",                     "讲座",                             "排除"),
    ("Congress",                    "会议文集（多为摘要）",             "排除"),
    ("Overall",                     "会议合集的总条目",                 "排除"),
    ("Bibliography",                "文献目录",                         "排除"),
    ("Directory",                   "名录",                             "排除"),
    ("Festschrift",                 "纪念文集",                         "排除"),
    ("Patient Education Handout",   "患者教育材料",                     "排除"),
    ("Video-Audio Media",           "视听资料",                         "排除"),
    ("Webcast",                     "网络视频",                         "排除"),
    ("Legal Case",                  "法律案例",                         "排除"),
    # —— 通常排除：勘误与撤稿 ——
    ("Published Erratum",           "勘误声明（不是 Erratum！）",       "排除"),
    ("Retraction Notice",           "撤稿声明",                         "排除"),
    ("Retracted Publication",       "已被撤稿的原文——务必排除",        "排除"),
    ("Expression of Concern",       "关注声明（结果存疑）",             "排除"),
    ("Corrected and Republished Article", "更正后重新发表",             "视情况"),
    ("Duplicate Publication",       "重复发表",                         "排除"),
]

_VALID_PUB_TYPES = {t for t, _, _ in PUB_TYPES}
# 小写 → 规范写法，用于纠正大小写（用户写 journal article 也认）
_PUB_TYPE_CANON = {t.lower(): t for t in _VALID_PUB_TYPES}


def default_types(advice: str) -> list[str]:
    """按建议取一组类型，供模板与示例配置预填，省得用户自己想。"""
    return [t for t, _, a in PUB_TYPES if a == advice]


@dataclass
class Subsection:
    name: str
    keywords: list[str] = field(default_factory=list)
    # cross_product 专用：本子板块在 B 侧的关键词（A 侧取板块级 trigger_keywords）
    cross_keywords: list[str] = field(default_factory=list)


@dataclass
class Section:
    name: str
    matcher: str
    subsections: list[Subsection]
    keywords: list[str] = field(default_factory=list)          # simple_keyword 用
    trigger_keywords: list[str] = field(default_factory=list)  # cross_product 的 A 侧
    exclude_keywords: list[str] = field(default_factory=list)
    scope: str = "journals"           # journals | pubmed_all
    search_field: str = "ti"          # ti | tiab
    quality_filter: bool = False      # 仅 pubmed_all 有意义：JCR Q1/Q2 且 IF≥阈值
    include_types: list[str] = field(default_factory=list)
    exclude_types: list[str] = field(default_factory=list)
    fallback_subsection: str = ""     # 专科刊全量收录时，未命中关键词的归属

    @property
    def subsection_names(self) -> list[str]:
        return [s.name for s in self.subsections]


@dataclass
class Config:
    project_name: str
    output_dir: str
    sections: list[Section]
    # 期刊分两组，区别是**收录方式**而非期刊性质：
    #   full_inclusion   —— 全量收录，标题没命中关键词也收（配合 fallback_subsection）
    #   keyword_filtered —— 只收标题命中关键词的
    # 旧版叫「专科刊 / 综合刊」，但那套命名把「收录方式」和「期刊是否综合」混在一起：
    # JCO、Lancet Oncology、Nature Cancer 都是肿瘤专科刊，却因为走关键词筛选而被叫成
    # 「综合刊」，容易误解。这里按行为命名。
    full_inclusion_journals: dict[str, str] = field(default_factory=dict)
    keyword_filtered_journals: dict[str, str] = field(default_factory=dict)
    journal_order: list[str] = field(default_factory=list)
    min_impact_factor: float = 0.0
    allowed_quartiles: list[str] = field(default_factory=lambda: ["Q1", "Q2"])
    translate_titles: bool = True
    path: Path | None = None

    @property
    def section_names(self) -> list[str]:
        return [s.name for s in self.sections]

    @property
    def all_journals(self) -> dict[str, str]:
        return {**self.full_inclusion_journals, **self.keyword_filtered_journals}

    def section(self, name: str) -> Section | None:
        return next((s for s in self.sections if s.name == name), None)

    def subsection_order(self) -> dict[str, dict[str, int]]:
        """{板块: {子板块: 序号}}。收藏库与 Obsidian 的排序都由它驱动，
        避免像旧版那样把子板块名写死进 SQL。"""
        return {s.name: {sub.name: i for i, sub in enumerate(s.subsections, 1)}
                for s in self.sections}


# ─── 校验 ─────────────────────────────────────────────────────────────────────

def _need(d: dict, key: str, where: str, typ=None):
    if key not in d or d[key] in (None, "", [], {}):
        raise ConfigError(f"{where} 缺少必填字段 `{key}`")
    val = d[key]
    if typ and not isinstance(val, typ):
        got = type(val).__name__
        want = typ.__name__ if not isinstance(typ, tuple) else "/".join(t.__name__ for t in typ)
        raise ConfigError(f"{where} 的 `{key}` 应为 {want}，实际是 {got}：{val!r}")
    return val


def _as_str_list(val, where: str, key: str) -> list[str]:
    if isinstance(val, str):
        val = [val]
    if not isinstance(val, list):
        raise ConfigError(f"{where} 的 `{key}` 应为列表，实际是 {type(val).__name__}")
    out = []
    for i, v in enumerate(val):
        if not isinstance(v, (str, int, float)):
            raise ConfigError(f"{where} 的 `{key}` 第 {i+1} 项不是文本：{v!r}")
        s = str(v).strip()
        if not s:
            raise ConfigError(f"{where} 的 `{key}` 第 {i+1} 项是空字符串")
        out.append(s)
    dup = [k for k in set(out) if out.count(k) > 1]
    if dup:
        raise ConfigError(f"{where} 的 `{key}` 有重复词：{sorted(dup)}")
    return out


def _check_types(types: list[str], where: str, key: str) -> list[str]:
    """校验并规范化文章类型，返回改好大小写的列表。

    类型名写错不会报错，只会**静默筛不到东西**——所以这里必须拦住，
    而且要直接给出最接近的正确写法，不能只甩一张几十项的表让人自己找。
    """
    import difflib

    out, unknown = [], []
    for t in types:
        canon = _PUB_TYPE_CANON.get(t.strip().lower())
        if canon:
            out.append(canon)
        else:
            unknown.append(t)
    if unknown:
        lines = []
        for t in unknown:
            near = difflib.get_close_matches(t, sorted(_VALID_PUB_TYPES), n=3, cutoff=0.6)
            lines.append(f"  · {t!r}" + (f"　你是不是想写：{' / '.join(near)}" if near else ""))
        raise ConfigError(
            f"{where} 的 `{key}` 含 PubMed 不认识的文章类型：\n" + "\n".join(lines) +
            f"\n  完整可用值见 configs/schema.md，或用 Excel 模板的「文章类型」页照抄。\n"
            f"  注意几个常写错的：Erratum ✗ → Published Erratum ✓；"
            f"Case Report ✗ → Case Reports ✓（复数）")
    return out


def _parse_section(raw: dict, idx: int) -> Section:
    if not isinstance(raw, dict):
        raise ConfigError(f"第 {idx} 个板块不是字典结构，请检查 YAML 缩进")
    name = _need(raw, "name", f"第 {idx} 个板块", str)
    where = f"板块「{name}」"

    matcher = raw.get("matcher", "simple_keyword")
    if matcher not in MATCHERS:
        raise ConfigError(
            f"{where} 的 `matcher` 不支持：{matcher!r}\n"
            f"  可用值：{', '.join(MATCHERS)}\n"
            f"  · simple_keyword —— 标题命中任一关键词即收录\n"
            f"  · cross_product  —— 需同时命中 trigger_keywords 与子板块关键词")

    scope = raw.get("scope", "journals")
    if scope not in ("journals", "pubmed_all"):
        raise ConfigError(f"{where} 的 `scope` 应为 journals 或 pubmed_all，实际是 {scope!r}")

    search_field = raw.get("search_field", "ti")
    if search_field not in ("ti", "tiab"):
        raise ConfigError(f"{where} 的 `search_field` 应为 ti（仅标题）或 tiab（标题+摘要），"
                          f"实际是 {search_field!r}")

    subs_raw = raw.get("subsections") or []
    if not isinstance(subs_raw, list) or not subs_raw:
        raise ConfigError(f"{where} 至少需要一个子板块（`subsections`）")

    subs, seen = [], set()
    for j, s in enumerate(subs_raw, 1):
        if not isinstance(s, dict):
            raise ConfigError(f"{where} 第 {j} 个子板块不是字典结构，请检查 YAML 缩进")
        sname = _need(s, "name", f"{where} 第 {j} 个子板块", str)
        if sname in seen:
            raise ConfigError(f"{where} 有重名子板块：{sname!r}")
        seen.add(sname)
        kw  = _as_str_list(s.get("keywords", []), f"{where}·{sname}", "keywords") if s.get("keywords") else []
        ckw = _as_str_list(s.get("cross_keywords", []), f"{where}·{sname}", "cross_keywords") if s.get("cross_keywords") else []
        subs.append(Subsection(sname, kw, ckw))

    keywords = _as_str_list(raw.get("keywords", []), where, "keywords") if raw.get("keywords") else []
    triggers = _as_str_list(raw.get("trigger_keywords", []), where, "trigger_keywords") if raw.get("trigger_keywords") else []
    excludes = _as_str_list(raw.get("exclude_keywords", []), where, "exclude_keywords") if raw.get("exclude_keywords") else []

    # 匹配器与字段的搭配校验：这是最容易配错、且错了会静默收不到文章的地方
    if matcher == "cross_product":
        if not triggers:
            raise ConfigError(
                f"{where} 用了 cross_product，必须提供 `trigger_keywords`（AND 的 A 侧）。\n"
                f"  例：trigger_keywords 写癌种词，子板块 cross_keywords 写风湿病词，\n"
                f"      则只收录标题同时含两者的文章。")
        empty = [s.name for s in subs if not s.cross_keywords]
        if empty:
            raise ConfigError(
                f"{where} 用了 cross_product，以下子板块缺少 `cross_keywords`：{empty}\n"
                f"  （AND 的 B 侧，写在每个子板块下）")
    else:
        if not keywords and not any(s.keywords for s in subs):
            raise ConfigError(
                f"{where} 用了 simple_keyword，但板块级 `keywords` 与所有子板块的 "
                f"`keywords` 都是空的——这样不会收到任何文章。")
        if triggers:
            raise ConfigError(
                f"{where} 用了 simple_keyword，却写了 `trigger_keywords`。\n"
                f"  该字段仅 cross_product 使用；若想要 AND 逻辑，请把 matcher 改为 cross_product。")

    inc = _as_str_list(raw.get("include_types", []), where, "include_types") if raw.get("include_types") else []
    exc = _as_str_list(raw.get("exclude_types", []), where, "exclude_types") if raw.get("exclude_types") else []
    inc = _check_types(inc, where, "include_types")
    exc = _check_types(exc, where, "exclude_types")
    both = set(inc) & set(exc)
    if both:
        raise ConfigError(f"{where} 的文章类型同时出现在 include 与 exclude：{sorted(both)}")

    fb = raw.get("fallback_subsection", "")
    if fb and fb not in seen:
        raise ConfigError(
            f"{where} 的 `fallback_subsection` 指向不存在的子板块：{fb!r}\n"
            f"  本板块的子板块有：{sorted(seen)}")

    if raw.get("quality_filter") and scope != "pubmed_all":
        raise ConfigError(
            f"{where} 设了 `quality_filter: true`，但 `scope` 是 {scope!r}。\n"
            f"  分区/IF 过滤只对 scope: pubmed_all 有意义（走期刊表时期刊已经是自己挑的）。")

    return Section(
        name=name, matcher=matcher, subsections=subs, keywords=keywords,
        trigger_keywords=triggers, exclude_keywords=excludes, scope=scope,
        search_field=search_field, quality_filter=bool(raw.get("quality_filter", False)),
        include_types=inc, exclude_types=exc, fallback_subsection=fb,
    )


def load_dict(raw: dict, path: Path | None = None) -> Config:
    """校验已解析好的配置结构。

    YAML 与 Excel 两条入口共用这一套校验，保证两边的规则和报错完全一致——
    否则很容易出现「YAML 能过、Excel 不能过」这类不一致。
    """
    return _build(raw, path)


def load(path: str | Path) -> Config:
    """读取并校验 YAML 配置。任何问题都抛 ConfigError，消息可直接照着改。"""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise ConfigError(f"配置文件不存在：{p}")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        # YAML 语法错误通常是缩进/中文冒号，给出具体行号与常见原因
        mark = getattr(e, "problem_mark", None)
        loc = f"第 {mark.line + 1} 行第 {mark.column + 1} 列" if mark else "位置未知"
        raise ConfigError(
            f"配置文件 YAML 语法有误（{loc}）：{getattr(e, 'problem', e)}\n"
            f"  常见原因：① 用了中文冒号「：」应为半角 `:` 且冒号后有空格；"
            f"② 缩进不一致（请统一用空格，不要用 Tab）；③ 含冒号的词未加引号") from None

    return _build(raw, p)


def _build(raw, p: Path | None = None) -> Config:
    if not isinstance(raw, dict):
        raise ConfigError("配置文件顶层应是「键: 值」结构，请检查文件是否为空或缩进错误")

    project = raw.get("project_name") or "lit-tracker"
    out = raw.get("output_dir") or "output"

    secs_raw = _need(raw, "sections", "配置", list)
    sections, seen = [], set()
    for i, s in enumerate(secs_raw, 1):
        sec = _parse_section(s, i)
        if sec.name in seen:
            raise ConfigError(f"有重名板块：{sec.name!r}")
        seen.add(sec.name)
        sections.append(sec)

    # 兼容旧字段名（specialty_/general_），但推荐用按行为命名的新字段
    _ALIAS = {"full_inclusion_journals": "specialty_journals",
              "keyword_filtered_journals": "general_journals"}

    def _journals(key) -> dict[str, str]:
        v = raw.get(key)
        if v is None:
            v = raw.get(_ALIAS[key]) or {}
        if isinstance(v, list):        # 允许只写全名的简写形式
            v = {x: x for x in v}
        if not isinstance(v, dict):
            raise ConfigError(f"`{key}` 应为「期刊全名: 显示名」的字典，或期刊名列表")
        return {str(k).strip(): str(vv).strip() for k, vv in v.items()}

    spec = _journals("full_inclusion_journals")
    gen = _journals("keyword_filtered_journals")
    overlap = set(spec) & set(gen)
    if overlap:
        raise ConfigError(
            f"以下期刊同时出现在 full_inclusion_journals 与 keyword_filtered_journals："
            f"{sorted(overlap)}\n  一本期刊只能选一种收录方式。")

    if not spec and not gen and any(s.scope == "journals" for s in sections):
        bad = [s.name for s in sections if s.scope == "journals"]
        raise ConfigError(
            f"板块 {bad} 的 scope 是 journals（只在指定期刊里搜），"
            f"但配置里没有任何期刊。\n"
            f"  请填写 `keyword_filtered_journals`（只收命中关键词的）"
            f"或 `full_inclusion_journals`（全量收录），\n"
            f"  或把这些板块改为 `scope: pubmed_all`（全 PubMed 检索）。")

    mif = raw.get("min_impact_factor", 0) or 0
    if not isinstance(mif, (int, float)):
        raise ConfigError(f"`min_impact_factor` 应为数字，实际是 {mif!r}")

    quart = raw.get("allowed_quartiles") or ["Q1", "Q2"]
    quart = _as_str_list(quart, "配置", "allowed_quartiles")
    badq = [q for q in quart if q not in ("Q1", "Q2", "Q3", "Q4")]
    if badq:
        raise ConfigError(f"`allowed_quartiles` 含无效分区：{badq}，可用值 Q1/Q2/Q3/Q4")

    return Config(
        project_name=str(project), output_dir=str(out), sections=sections,
        full_inclusion_journals=spec, keyword_filtered_journals=gen,
        journal_order=_as_str_list(raw["journal_order"], "配置", "journal_order")
                      if raw.get("journal_order") else [],
        min_impact_factor=float(mif), allowed_quartiles=quart,
        translate_titles=bool(raw.get("translate_titles", True)), path=p,
    )
