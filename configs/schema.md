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

`Journal Article` · `Review` · `Systematic Review` · `Meta-Analysis` · `Clinical Trial` · `Randomized Controlled Trial` · `Case Reports` · `Observational Study` · `Multicenter Study` · `Practice Guideline` · `Editorial` · `Letter` · `Comment` · `Erratum`

常见搭配：

```yaml
include_types: [Journal Article, Review, Systematic Review, Meta-Analysis, Case Reports]
exclude_types: [Editorial, Letter, Comment, Erratum]
```

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
