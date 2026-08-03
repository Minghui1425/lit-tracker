# 配置字段说明

一份配置描述「你要追踪什么」。改配置不需要动代码。

> **不想直接写 YAML？** 用 Excel 模板更省事，不会踩缩进和中文冒号的坑：
> ```bash
> python3 cli.py template   --out 我的配置.xlsx     # 生成模板
> python3 cli.py from-excel --excel 我的配置.xlsx   # 填好后转成 YAML
> ```
> Excel 的 4 张表与本文字段一一对应（设置 / 板块 / 子板块 / 期刊），
> **两条路共用同一套校验**，规则和报错完全一致。本文仍是字段语义的权威说明。

改完先校验，能省很多试错时间：

```bash
python3 cli.py check    --config configs/你的配置.yaml   # 离线，很快
python3 cli.py validate --config configs/你的配置.yaml   # 联网核对期刊名与关键词
```

`check` 只查结构；**`validate` 才能查出期刊名写错**——那种错误 PubMed 不会报，
只会静默搜不到东西。

---

## 顶层字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `project_name` | 否 | 报告标题，默认 `lit-tracker` |
| `output_dir` | 否 | HTML 输出目录，默认 `output` |
| `translate_titles` | 否 | 是否调 DeepL 把标题译成中文，默认 `true`。未配 `DEEPL_API_KEY` 时自动跳过，不报错 |
| `full_inclusion_journals` | 视情况 | **全量收录**的刊：没命中关键词也收（需配 `fallback_subsection`）。`期刊全名: 显示名`，或只写一列期刊名 |
| `keyword_filtered_journals` | 视情况 | **只收命中关键词**的刊。绝大多数期刊都该放这里 |
| `journal_order` | 否 | 报告中期刊的固定展示顺序，未列出的排后面 |
| `allowed_quartiles` | 否 | 允许的 JCR 分区，默认 `[Q1, Q2]` |
| `min_impact_factor` | 否 | IF 下限，默认 `0` |
| `sections` | **是** | 板块列表，见下 |

> 期刊名必须是 **PubMed 里的全名**。查法：在 PubMed 搜一篇该刊文章，看
> 「Journal」字段。写错不会报错，只会静默搜不到东西——所以建议先用 `check`
> 跑一遍，再用 `history` 拉一个短区间看看有没有结果。

---

## 板块（`sections`）

**板块的书写顺序 = 去重优先级。** 一篇文章只会归入第一个命中的板块，不会在多个板块重复出现。把最重要、最专的板块写在前面。

| 字段 | 必填 | 说明 |
|---|---|---|
| `name` | **是** | 板块名 |
| `matcher` | 否 | `simple_keyword`（默认）或 `cross_product` |
| `scope` | 否 | `journals`（默认，只在你列的期刊里找）或 `pubmed_all`（全 PubMed） |
| `search_field` | 否 | `ti` 仅标题（默认，推荐）；`tiab` 标题+摘要（结果多但杂得多） |
| `quality_filter` | 否 | 仅 `scope: pubmed_all` 可用。按分区/IF 过滤 |
| `keywords` | 视情况 | `simple_keyword` 用。板块级关键词 |
| `trigger_keywords` | 视情况 | `cross_product` 用。AND 的 A 侧 |
| `exclude_keywords` | 否 | 标题命中即排除 |
| `include_types` | 否 | 只保留这些文章类型 |
| `exclude_types` | 否 | 排除这些文章类型 |
| `fallback_subsection` | 否 | `full_inclusion_journals` 里**没命中任何关键词**的文章归到该子板块（＝全量订阅这些刊） |
| `subsections` | **是** | 子板块列表 |

### 两种匹配器

**`simple_keyword`** —— 标题命中任一关键词即收录。适合「我关注这几个主题」。

```yaml
- name: 心衰进展
  matcher: simple_keyword
  scope: journals
  subsections:
    - name: 射血分数保留
      keywords: [HFpEF, preserved ejection fraction]
    - name: 其他
      keywords: []          # 留空＝不主动匹配，仅作兜底
```

**`cross_product`** —— 需**同时**命中 A 侧（`trigger_keywords`）和 B 侧（子板块的 `cross_keywords`）。适合「A 类药 × B 类结局」这种交叉主题，能大幅减少噪音。

```yaml
- name: 药物不良反应
  matcher: cross_product
  scope: pubmed_all
  trigger_keywords: [SGLT2 inhibitor, GLP-1 receptor agonist]   # A 侧
  subsections:
    - name: 肾脏
      cross_keywords: [acute kidney injury, nephropathy]        # B 侧
    - name: 代谢
      cross_keywords: [ketoacidosis, hypoglycemia]
```

### 子板块（`subsections`）

**子板块的书写顺序 = 归类优先级**，取首个命中者。所以要把更specific的写在前面：若「心肌炎」和「心脏」都在，把「心肌炎」写前面，否则它会先被「心脏」抓走。

都没命中时：有 `fallback_subsection` 就用它，否则归入**最后一个**子板块。因此习惯上把「其他」放在最后。

---

## 关键词怎么写

- **只写单数原形**。程序会自动兼容复数与 `-y→-ies`（`neuropathy` 自动匹配 `neuropathies`），送进 PubMed 的检索式也会同步补上复数。**不要手工补变体**。
- 按**词边界**匹配，不会误伤：`optic` 不会命中 `optical`，`skin` 不会命中 `skinny`。
- 大小写不敏感。
- 词组照常写：`interstitial lung`、`acute kidney injury`。
- 含冒号的词要加引号，否则 YAML 会解析错。

## 文章类型可用值

下面是**全部**可填的值，不用自己去想。Excel 模板里也有同一张表（「文章类型」页），
可以直接照抄。「建议」只是默认倾向，按需要改就行。

> ⚠️ 英文名必须与 PubMed 一字不差（含大小写与复数）。**写错不会报错，只会静默筛不到**——
> 所以本表每一条都经过 `"X"[pt]` 实际检索验证。两个最常踩的坑：
> `Erratum` ✗ →`Published Erratum` ✓；`Case Report` ✗ → `Case Reports` ✓（复数）。
>
> 名字里带逗号的（如 `Clinical Trial, Phase III`）在 YAML 的**行内列表**里必须加引号，
> 否则 `[A, Clinical Trial, Phase III]` 会被当成三项——用下面的块状写法就不会有这个问题。

| 类型 | 中文 | 建议 |
|---|---|---|
| `Journal Article` | 期刊论文（绝大多数研究都带这个） | 保留 |
| `Randomized Controlled Trial` | 随机对照试验 | 保留 |
| `Controlled Clinical Trial` | 对照临床试验（非随机） | 保留 |
| `Clinical Trial` | 临床试验（未分期的统称） | 保留 |
| `Clinical Trial, Phase I` | I 期临床试验 | 保留 |
| `Clinical Trial, Phase II` | II 期临床试验 | 保留 |
| `Clinical Trial, Phase III` | III 期临床试验 | 保留 |
| `Clinical Trial, Phase IV` | IV 期临床试验（上市后） | 保留 |
| `Pragmatic Clinical Trial` | 实用性临床试验 | 保留 |
| `Adaptive Clinical Trial` | 适应性设计试验 | 保留 |
| `Equivalence Trial` | 等效性试验 | 保留 |
| `Observational Study` | 观察性研究（队列/病例对照等） | 保留 |
| `Comparative Study` | 比较性研究 | 保留 |
| `Multicenter Study` | 多中心研究 | 保留 |
| `Evaluation Study` | 评价性研究 | 保留 |
| `Validation Study` | 验证性研究 | 保留 |
| `Twin Study` | 双生子研究 | 保留 |
| `Clinical Study` | 临床研究（较旧的统称） | 保留 |
| `Technical Report` | 技术报告 | 视情况 |
| `Review` | 综述（含叙述性综述，量很大） | 保留 |
| `Systematic Review` | 系统综述 | 保留 |
| `Meta-Analysis` | 荟萃分析 | 保留 |
| `Scoping Review` | 范围综述 | 保留 |
| `Evidence Synthesis` | 证据合成 | 保留 |
| `Practice Guideline` | 临床实践指南 | 保留 |
| `Guideline` | 指南（范围更宽） | 保留 |
| `Consensus Statement` | 共识声明 | 保留 |
| `Consensus Development Conference, NIH` | NIH 共识会议 | 视情况 |
| `Case Reports` | 病例报告（注意是复数） | 视情况 |
| `Clinical Trial Protocol` | 试验方案（只有设计，没有结果） | 视情况 |
| `Preprint` | 预印本（未经同行评议） | 视情况 |
| `Dataset` | 数据集 | 视情况 |
| `English Abstract` | 非英文原文但有英文摘要 | 视情况 |
| `Historical Article` | 医学史类 | 视情况 |
| `Introductory Journal Article` | 专题导读 | 视情况 |
| `Personal Narrative` | 个人叙事 | 视情况 |
| `Editorial` | 社论 | 排除 |
| `Letter` | 读者来信 | 排除 |
| `Comment` | 评论（对某篇文章的点评） | 排除 |
| `News` | 新闻报道 | 排除 |
| `Newspaper Article` | 报纸文章 | 排除 |
| `Interview` | 访谈 | 排除 |
| `Biography` | 人物传记 | 排除 |
| `Autobiography` | 自传 | 排除 |
| `Portrait` | 人物照片/小传 | 排除 |
| `Address` | 演讲致辞 | 排除 |
| `Lecture` | 讲座 | 排除 |
| `Congress` | 会议文集（多为摘要） | 排除 |
| `Overall` | 会议合集的总条目 | 排除 |
| `Bibliography` | 文献目录 | 排除 |
| `Directory` | 名录 | 排除 |
| `Festschrift` | 纪念文集 | 排除 |
| `Patient Education Handout` | 患者教育材料 | 排除 |
| `Video-Audio Media` | 视听资料 | 排除 |
| `Webcast` | 网络视频 | 排除 |
| `Legal Case` | 法律案例 | 排除 |
| `Published Erratum` | 勘误声明（不是 Erratum！） | 排除 |
| `Retraction Notice` | 撤稿声明 | 排除 |
| `Retracted Publication` | 已被撤稿的原文——务必排除 | 排除 |
| `Expression of Concern` | 关注声明（结果存疑） | 排除 |
| `Corrected and Republished Article` | 更正后重新发表 | 视情况 |
| `Duplicate Publication` | 重复发表 | 排除 |

### 直接可用的两串

按上表「建议」整理好的完整清单，复制粘贴即可：

```yaml
include_types:
  - Journal Article
  - Randomized Controlled Trial
  - Controlled Clinical Trial
  - Clinical Trial
  - "Clinical Trial, Phase I"
  - "Clinical Trial, Phase II"
  - "Clinical Trial, Phase III"
  - "Clinical Trial, Phase IV"
  - Pragmatic Clinical Trial
  - Adaptive Clinical Trial
  - Equivalence Trial
  - Observational Study
  - Comparative Study
  - Multicenter Study
  - Evaluation Study
  - Validation Study
  - Twin Study
  - Clinical Study
  - Review
  - Systematic Review
  - Meta-Analysis
  - Scoping Review
  - Evidence Synthesis
  - Practice Guideline
  - Guideline
  - Consensus Statement
exclude_types:
  - Editorial
  - Letter
  - Comment
  - News
  - Newspaper Article
  - Interview
  - Biography
  - Autobiography
  - Portrait
  - Address
  - Lecture
  - Congress
  - Overall
  - Bibliography
  - Directory
  - Festschrift
  - Patient Education Handout
  - Video-Audio Media
  - Webcast
  - Legal Case
  - Published Erratum
  - Retraction Notice
  - Retracted Publication
  - Expression of Concern
  - Duplicate Publication
```

想更宽松就把 `include_types` 整段删掉（留空＝不限类型），只保留 `exclude_types`。

---

## 关于 IF / 分区

`quality_filter: true` 需要项目根目录有 `if_data.json`。两条路任选其一：

```bash
python3 cli.py import-if                                  # ① 从第三方仓库下载
python3 cli.py import-if --excel "/路径/你的JCR名单.xlsx"   # ② 用自己的 JCR 名单
```

①来自 EasyPubMed 仓库整理的数据（约 2 万本刊），可能略滞后于官方 JCR，其第三方数据
授权边界尚未由本项目核实，使用前请阅读 README 的「IF / 分区数据」说明；
②数据最新最准，但需要单位订阅的 JCR 导出。生成的文件不随仓库分发。

文件缺失时，程序会**跳过过滤并继续运行**（宁可多收，也不因缺数据而静默漏掉文章），并在日志里提示。

## 常见坑

| 现象 | 原因 |
|---|---|
| 一篇结果都没有 | 期刊名不是 PubMed 全名；或关键词太窄；先用短区间 `history` 试 |
| 某板块吃掉了太多文章 | 它排在前面且关键词太宽——板块顺序即优先级 |
| 「其他」子板块爆炸 | 开了 `fallback_subsection`，那批刊被全量收录 |
| 报 YAML 语法错 | 多半是中文冒号「：」，或缩进混用了 Tab |
