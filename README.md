# lit-tracker

**把 PubMed 检索结果变成你自己的分类周报、收藏库和 Obsidian 文献地图。**

PubMed 的保存检索擅长发来一串结果，但不会按你的研究框架归类，也不会替你维护一个可评级、
可标注、可按课题整理的本地文献库。lit-tracker 用一份 Excel 或 YAML 配置补上这条工作流，
换医学方向只需换关键词和期刊，**不需要改代码**。

> **本地优先**：配置、报告、收藏库和笔记都留在你的电脑上。程序只把检索请求发给 NCBI；
> 启用 DeepL 时，待翻译的标题会发送给 DeepL；跑 `citations` 时，库内文章的 PMID 会发送给
> Semantic Scholar（只发 PMID，不发你的笔记、评级或项目名）。
> Obsidian、JCR 数据、引文网络和定时任务均为可选项。

核心流程已经可用，并有离线测试覆盖和 Python 3.10 / 3.13 的持续集成；当前仍在补充更多
学科示例和便捷启动方式，见[路线图](#路线图)。

---

## 它能做什么

用配置描述你的研究方向后，它提供四件事：

| 功能 | 解决什么 | 命令 |
|---|---|---|
| **① 周报** | 每周自动汇总过去 7 天新文献，按你定义的板块分好类 | `weekly` |
| **② 历史检索** | 任意时间区间回溯查找，用来补齐既往文献或验证配置效果 | `history` |
| **③ 收藏库** | 把看中的文献存下来，可筛选、评级、写笔记、按课题打标签 | `add` / `library` / `serve` |
| **③′ 引文网络** | 算出库内文献之间谁引用了谁，挑出被反复引用的那几篇 | `citations` |
| **④ Obsidian 笔记** | 每篇生成一则笔记并按板块归档，配合双链做知识管理 | `obsidian` |

①②产出可折叠的 HTML 报告；③是本地 SQLite 库 + 可筛选网页；④把库里的文献同步成 Obsidian 笔记。

四者是一条流水线：**周报/历史检索发现文献 → 挑中的存进收藏库 → 需要深读的导出到 Obsidian。**

---

## 最快上手

准备 Python 3.10+，在项目目录运行：

```bash
python3 -m venv .venv
source .venv/bin/activate                       # Windows 见下一节
python -m pip install -r requirements.txt
cp .env.example .env                            # 填 NCBI_API_KEY，并建议填 NCBI_EMAIL

python3 cli.py check --config configs/example-minimal.yaml
python3 cli.py history --config configs/example-minimal.yaml \
  --from 2026-07-01 --to 2026-07-07
```

完成后打开 `output/history_*.html`。这个示例追踪心血管主题；确认程序能跑通后，再用 Excel
模板换成自己的板块、关键词和期刊。首次配置建议先查一周，而不是直接回溯多年。

---

## 一、准备（一次性，约 10 分钟）

需要 **Python ≥ 3.10**（代码用了 `X | None` 这类 3.10 才有的写法）。
`python3 --version` 查一下；低于 3.10 请先升级。

macOS / Linux：

```bash
python3 -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Windows（PowerShell）：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
copy .env.example .env
```

> 后文命令一律写作 `python3 cli.py …`；Windows 下换成 `python cli.py …`。

打开 `.env` 填两项：

- `NCBI_API_KEY`（必填，免费）：注册 <https://www.ncbi.nlm.nih.gov/account/>
  → Account Settings → API Key Management。
- `NCBI_EMAIL`（建议填）：你的联系邮箱。NCBI 的使用规范要求请求带上它，
  以便异常时先联系你而不是直接限流。

`DEEPL_API_KEY` 可选，用于把标题译成中文；不填只是不翻译，其余功能不受影响。

---

## 二、描述你的方向（核心步骤）

配置回答三个问题：**分成哪几个板块、每个板块怎么匹配、盯哪些期刊。**

### 填 Excel（推荐，不用碰 YAML）

```bash
python3 cli.py template --out 我的配置.xlsx     # 生成模板
# 打开后先看第一页「说明」，再填 4 张表：设置 / 板块 / 子板块 / 期刊
python3 cli.py from-excel --excel 我的配置.xlsx  # 转成 YAML
```

模板自带示例行、下拉选项和逐列提示。填错会**指出第几页、第几行、哪一列、可填什么**：

```
「板块」表第 3 行 的「匹配方式」填了「交差」，无法识别。
  可填：关键词 / 交叉

「子板块」表里这些「所属板块」在「板块」表里找不到：['药物不良反映']
  「板块」表现有：['心衰进展', '药物不良反应']
  多半是名字写得不完全一致（多空格、错别字）。
```

会写 YAML 也可以跳过 Excel，直接照 `configs/example-minimal.yaml` 改。
两条路**共用同一套校验**，规则完全一致。字段语义见 **[configs/schema.md](configs/schema.md)**。

### 两种匹配方式

这是配置里最需要想清楚的一项：

- **关键词** —— 标题命中任一关键词即收录。只填子板块的关键词，「触发词」留空。
  适合「我就关注这几个主题」。
- **交叉** —— 标题必须**同时**命中两类词：板块的「触发词」+ 子板块的「关键词」。
  适合「A 类药 × B 类结局」，能挡掉大量只沾一边的文献。

```
交叉示例：触发词 SGLT2 inhibitor ＋ 子板块「肾脏」关键词 acute kidney injury
  收　：Acute kidney injury associated with SGLT2 inhibitors
  不收：SGLT2 inhibitors in heart failure          （缺肾脏词）
  不收：Acute kidney injury after cardiac surgery  （缺药物词）
```

### 跑检索前先核对一次

期刊名写错时 PubMed **不会报错，只会静默一篇都搜不到**。这条命令能提前抓出来：

```bash
python3 cli.py validate --config configs/我的配置.yaml     # 加 --journals-only 更快
```

```
✗ [关键词筛选] Nature Cardiovasc Res   0 篇
    → 改成「Nature cardiovascular research」即可（已确认这个名字能搜到）
✗ 测试·甲 / zzzqqxnotaword   0 篇
    2024 年以来标题里一次都没出现过
! 测试·乙 / cancer   248648 篇
    命中量极大，这个词可能太宽
```

---

## 三、① 周报 与 ② 历史检索

**先用历史检索验收配置效果**，别直接上定时任务：

```bash
python3 cli.py history --config <配置> --from 2026-06-01 --to 2026-06-30
```

看收得对不对、量合不合适。太杂就收窄关键词或改用「交叉」，太少就放宽。调好后再跑周报：

```bash
python3 cli.py weekly --config <配置>              # 过去 7 天
python3 cli.py weekly --config <配置> --date 2026-07-28   # 补跑指定某期
```

想让它每周自动跑，见 **[schedule/](schedule/)**：周报（每周二）与引文网络（每周三）各一份
macOS launchd 模板，外加 Windows 任务计划程序说明。模板都带 `--catchup`——关机错过的那一期
会在下次登录时补上，而**不会**每次开机都重跑一遍。

两者是同一个引擎，**只有日期窗口不同**。报告输出到 `output/`，按板块折叠，
每篇显示期刊、日期、关键词、通讯单位、摘要（可展开），以及 Q 分区与 IF 徽章。

---

## 四、③ 收藏库

报告里看中的文献，用 PMID 存进本地库：

```bash
python3 cli.py add     --config <配置> --pmid 42482656 42456777
python3 cli.py library --config <配置>      # 生成 output/library.html
python3 cli.py serve   --config <配置>      # 页面上的按钮需要它，保持开着
```

`serve` 起来后在浏览器打开 **http://127.0.0.1:8781/** 即可（双击 `output/library.html`
也一样能用）。

板块按配置自动判定；没命中关键词时会提示，可用 `--section / --subsection` 手动指定。
**同一批 PMID 重新 `add` 会按当前配置重新归类**（配置里补了关键词、或这次带上
`--section` 手动指定），PubMed 元数据一并刷新，你的笔记与评级保留。

网页支持按板块、子板块、年份、期刊、评级、标题词、项目筛选，可打分（○/⭐/🚩）、
写笔记、导出 RIS / nbib 给 EndNote。

### 引文网络

```bash
python3 cli.py citations --config <配置>            # 增量：只抓没抓过的
python3 cli.py citations --config <配置> --force    # 全量重抓
```

回答的是「**我收藏的这批文献里，哪几篇是被反复引用的基石**」：取每篇的参考文献列表，
与库内 PMID 求交集，算出谁引用了谁。跑完页面上会多出两个徽章——

- **库内被引 N**：点开列出是库里的哪几篇引了它
- **被引 N（高影响 M）**：Semantic Scholar 统计的全球被引数

筛选栏新增「库内被引」下拉（≥1 / ≥3 / 无），用来快速挑出核心文献，或反过来查漏。

数据来自 [Semantic Scholar](https://www.semanticscholar.org/product/api)（PubMed 自己不提供
参考文献列表）。不填 `SEMANTIC_SCHOLAR_API_KEY` 也能跑，但走匿名共享池、限速严格，
几百篇可能要跑很久；key 免费，填进 `.env` 会快一个量级。

跑的过程中**随时可以 Ctrl+C**：每篇抓完立即写库，下次运行自动跳过抓过的、只补新增的；
抓失败的不留记录，下次会自动重试。新收藏的文献只需再跑一次 `citations`，不用重来。

### 项目标签

与板块/子板块**正交**：板块回答「这篇是什么」（自动分类），项目回答
「我拿它干什么」（手动归档）。一篇可属多个项目，且**可跨板块**——
比如一个课题会同时用到心脏、消化、代谢几个板块下的文献。

日常用网页：勾选文献 → 点「加入项目」→ 输入课题名（**输入新名字即新建**）。
筛选栏的「项目」下拉可只看某课题，选「未归项目」可查漏。

管理项目用命令行：

```bash
python3 cli.py project --config <配置> --list                        # 列出所有项目
python3 cli.py project --config <配置> --name <项目名> --add    --pmid 123 456
python3 cli.py project --config <配置> --name <项目名> --remove --pmid 123
python3 cli.py project --config <配置> --name <项目名> --rename <新名>
python3 cli.py project --config <配置> --name <项目名> --archive     # 课题做完了但想留档
python3 cli.py project --config <配置> --name <项目名> --delete
```

**删项目只解散分组，不删文献。** 改名和删除都会自动同步到 Obsidian 的项目索引。

> `serve` 是常驻进程，改过代码要重启。端口默认 8781，冲突时可设
> `LITTRACK_PORT=8782`。服务只监听本机并校验写操作凭据；含凭据的
> `output/library.html` **不要分享**。完整边界和凭据轮换方法见 [SECURITY.md](SECURITY.md)。

---

## 五、④ Obsidian 笔记

在 `.env` 里设 `OBSIDIAN_DIR`（vault 中存放文献笔记的文件夹）后：

```bash
python3 cli.py obsidian --config <配置> --all          # 导出库中全部
python3 cli.py obsidian --config <配置> --pmid 42482656
python3 cli.py obsidian --config <配置>                # 不加参数＝只刷新已有笔记
```

- 笔记按 **板块/子板块** 建文件夹归档；之后板块改了会自动归位
- 生成 `总录.md`（全部文献一张表）和 `项目/<课题名>.md`（每个项目一张表）
- 表格标题列用双链，Obsidian 图谱里能看到「课题 ↔ 文献」的连线
- **你手写的 `label` 与 `Notes` 永远保留**，刷新只更新元数据

---

## 六、IF / 分区数据（可选）

想按 JCR 分区或 IF 过滤（配置里的「质量过滤」）才需要这步。两条路任选其一：

```bash
python3 cli.py import-if                                  # ① 从第三方仓库下载现成数据
python3 cli.py import-if --excel "/路径/你的JCR名单.xlsx"   # ② 用单位订阅的名单，更准
```

①的数据来自第三方仓库 [EasyPubMed](https://github.com/naivenaive/EasyPubMed) 整理的数据包，
约 2 万本期刊，覆盖面比多数单位导出的名单还广，可能略滞后于官方 JCR。
②适配 Clarivate JCR 的标准导出格式。

> **授权边界**：IF / 分区的原始指标出自 Clarivate 的 Journal Citation Reports，
> 属商业订阅产品，其使用与再分发受 [Clarivate 条款](https://clarivate.com/legal/terms-of-use/)约束。
> EasyPubMed 仓库自身采用 MIT，但**仓库的许可证并不会让其中收录的第三方数据自动变成
> MIT 数据**；本项目未核实该数据包的独立授权，走①请自行判断在你的场景下能否使用。
> 对授权有顾虑的，请用②导入本单位订阅的名单。
>
> 本项目不分发、也不对任何 IF / 分区数据主张权利。生成的 `if_data.json` 已被
> `.gitignore` 排除，不随仓库分发。

**不做这步也能正常用**：程序会跳过该过滤并继续运行（宁可多收，也不因缺数据静默漏文章）。

---

## 命令一览

| 命令 | 用途 |
|---|---|
| `template` | 生成 Excel 配置模板 |
| `from-excel` | Excel → YAML 配置 |
| `check` | 离线校验配置结构（快） |
| `validate` | 联网核对期刊名与关键词命中量 |
| `weekly` | 抓过去 7 天，出 HTML 周报 |
| `history` | 抓指定区间，出 HTML 报告 |
| `add` | 按 PMID 存入收藏库 |
| `library` | 生成收藏库网页（`--projects` 列出所有项目） |
| `serve` | 收藏库网页按钮的后端服务 |
| `obsidian` | 导出/刷新 Obsidian 笔记 |
| `project` | 项目标签：列出 / 增删文献 / 改名 / 归档 / 删除 |
| `citations` | 抓库内引文网络与全球被引数（`--force` 全量重抓） |
| `import-if` | 生成 IF / 分区数据 |

---

## 两个最容易踩的点

- **板块顺序 = 去重优先级**，子板块顺序 = 归类优先级，都取**首个命中者**。
  更专、更具体的写在前面；「其他」放最后。
- **关键词只写单数原形**。复数与 `-y→-ies` 会自动兼容，本地匹配和 PubMed 检索式
  两边都补上——手工补变体反而容易漏。

---

## 适用范围与边界

适合「关键词能描述清楚」的追踪需求。

**不适合**需要复杂语义判断的场景。举例：追踪「免疫检查点抑制剂引起的器官不良反应」时，
标题里的 `renal` 可能指**不良反应**（免疫性肾炎），也可能指**癌种**（renal cell carcinoma）
或**转移灶**（liver metastases）——靠关键词无法区分，实测误判率可达 60% 以上。
这类需求需要领域特定的语境消歧规则，超出本工具的配置能力。

---

## 路线图

- [x] **M1** 配置层 + 检索引擎 + HTML 报告（周报/历史统一）
- [x] **M1.5** Excel 配置模板 + 联网核对期刊名与关键词
- [x] **M2** 本地收藏库（SQLite + 可筛选页面 + 项目标签）
- [x] **M3** Obsidian 笔记导出 + 总录 + 项目索引
- [x] **M4** 定时任务模板（macOS / Windows），关机错过自动补跑
- [x] **M4.5** 库内引文网络 + 全球被引数
- [ ] **M5** 更多学科示例配置、双击运行脚本

## 开发与测试

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

测试**全程离线**，不打 PubMed，也不需要 `NCBI_API_KEY`；`cli.py serve` 的鉴权测试
会真的把服务起在随机端口上打一遍。装了 `node` 的话，收藏库页面的 JS 会额外做一次
真语法检查（`node --check`）——那段 JS 是 f-string 拼的，转义写错会让整段脚本静默失效。

GitHub Actions 在 Python 3.10 / 3.13 上跑同一套测试，见
[`.github/workflows/ci.yml`](.github/workflows/ci.yml)。

## 数据来源与免责声明

- **文献数据**来自 NCBI 的 [E-utilities](https://www.ncbi.nlm.nih.gov/books/NBK25497/)。
  本项目按其使用规范在每个请求中带上 `tool=lit-tracker` 与 `email`（见 `.env` 的
  `NCBI_EMAIL`），并默认使用 API Key 限速。请勿绕开这些设置做高频批量抓取。
- **PubMed 记录中的标题与摘要，版权归原出版方**。本工具生成的报告、收藏库页面和
  Obsidian 笔记只供你个人检索、阅读与整理使用，**不代表你获得了再分发这些内容的
  授权**；对外分享前请自行确认相应出版方的许可。
- NCBI 对其数据不作任何担保，也不对使用后果负责，详见
  [NCBI Policies and Disclaimers](https://www.ncbi.nlm.nih.gov/home/about/policies/)。
- **IF / 分区数据**的版权归 Clarivate，边界见上文「IF / 分区数据」一节。
- 本项目与 NCBI、Clarivate 均无隶属关系，也未获其背书。

## 许可

本项目源码采用 [MIT License](LICENSE)，版权 © 2026 Minghui1425。

许可只覆盖**本项目自己的代码**；运行时抓取或生成的数据（PubMed 记录、JCR 指标）
不在其覆盖范围内，适用上面「数据来源与免责声明」中的条款。

安全问题请按 [SECURITY.md](SECURITY.md) 私下反馈，不要开公开 issue。
