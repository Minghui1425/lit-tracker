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
| **③ 收藏库** | 把看中的文献存下来，可筛选、评级、写笔记、挂全文 PDF、按课题打标签 | `add` / `library` / `serve` / `pdf` |
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
# 「文章类型」页列了全部 62 种 PubMed 类型与中文对照，填「保留/排除类型」时照抄即可
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

网页支持按板块、子板块、年份、月份、期刊、分区、IF、文章类型、引用情况、评级、
标题词、摘要词、项目、有无全文筛选，可打分（○/⭐/🚩）、写笔记、挂全文 PDF、
导出 nbib 给 EndNote。

**IF、文章类型、引用情况是收起式多选**：区间互不重叠，勾多个取并集（比如 IF 同时勾
「< 5」和「≥ 20」看两头）；文章类型有 60 多种，摊平成一排勾选框会把筛选栏撑爆，
所以收进下拉里。

**下拉之间是联动的**：选定板块后，子板块和期刊会收窄到该板块**实际有文章**的那些；
选定年份后月份同理。列出 0 篇的选项等于给人挖坑——选中后一片空白，还得回头怀疑是不是
自己筛错了。换板块时**已经选好的期刊/子板块会尽量保留**（在新板块里也存在就留着，
不存在才回到「全部」），不用每换一次就重选一遍。

> 注意这只影响**筛选栏**。「添加文献」弹窗里的子板块仍是配置里的全量——新收的文章
> 本来就可能是某个目前还空着的子板块的第一篇，那个选项必须能选到。

导出只给 nbib，不自己拼 RIS——库里没存卷/期/页，本地拼出来的条目导进 EndNote 是残的，
还得手工补；nbib 直接向 PubMed 要官方 MEDLINE 记录，字段由 NLM 生成。

**也可以不回终端直接在网页上添加**：点筛选栏的「添加文献」，粘贴 PubMed 文章的完整标题
或输入 PMID（多个用空格/逗号分隔，一次最多 50 篇），归类逻辑与命令行 `add` 完全一致——
同样自动判定板块，也可在弹窗里手动指定。走标题时若在 PubMed 匹配到多篇（会议摘要、
勘误、同名综述并不少见），会直接报错让你改用 PMID，**不猜**——猜错就是往库里加了
一篇别人的文章，事后很难发现。这条路要 `serve` 开着，且 `.env` 里配了 `NCBI_API_KEY`。

**网页添加会顺手试抓一次 [OA 全文](#全文-pdf)**：能免费拿到的直接挂上，省得事后再点
一次「抓取 OA 全文」。所以这个按钮会比之前慢几秒——它把该做的一次做完了。抓不到是常态
（订阅刊），提示里会说明，文献本身照样收进来了：**全文是附加品，抓取失败绝不会让入库
变成一次失败**。只试这次**新增**的那几篇——已在库的要么早有 PDF，要么之前就试过没拿到。

命令行的 `add` 默认**不**抓，要的话加 `--fetch`：

```bash
python3 cli.py add --config <配置> --pmid 42482656 --fetch
```

在终端里本来就能随手补一条 `pdf --fetch`，默认不抓是为了让 `add` 保持快；网页上没有
终端可用，所以那边一律会试。

### 引文网络

```bash
python3 cli.py citations --config <配置>            # 增量：只抓没抓过的
python3 cli.py citations --config <配置> --force    # 全量重抓
```

回答的是「**我收藏的这批文献里，哪几篇是被反复引用的基石**」：取每篇的参考文献列表，
与库内 PMID 求交集，算出谁引用了谁。跑完页面上会多出两个徽章——

- **库内被引 N**：点开列出是库里的哪几篇引了它
- **被引 N（高影响 M）**：Semantic Scholar 统计的全球被引数与其中的高影响被引

筛选栏的「引用情况」下拉把两个维度合在一起，可多选、取并集：

- 全球被引区间：`1～10` / `10～30` / `30～50` / `50～100` / `≥100`（左闭右开）
- 库内引用关系：`有库内被引` / `库内被引 ≥ 3 篇` / `无库内被引`

前者用来找这个领域公认的重头文章，后者用来找**在你自己这批文献里**起支点作用的那几篇——
两者常常不是同一批，这也是库内引用值得单独算一遍的原因。

数据来自 [Semantic Scholar](https://www.semanticscholar.org/product/api)（PubMed 自己不提供
参考文献列表）。不填 `SEMANTIC_SCHOLAR_API_KEY` 也能跑，但走匿名共享池、限速严格，
几百篇可能要跑很久；key 免费，填进 `.env` 会快一个量级。

跑的过程中**随时可以 Ctrl+C**：每篇抓完立即写库，下次运行自动跳过抓过的、只补新增的；
抓失败的不留记录，下次会自动重试。新收藏的文献只需再跑一次 `citations`，不用重来。

### 全文 PDF

每篇可以挂一份全文，存在 `output/pdf/<pmid>.pdf`。页面上有 PDF 的显示红色 **PDF**
徽章；没有的显示灰色 **+ PDF**，点它选文件——**或者直接把 PDF 拖到那一行**，这是日常
最快的一条路。旁边的 ✕ 把 PDF 挪进 `pdf/_trash/`（不删文献）；删除文献时，它的 PDF
也一并进 `_trash`。筛选栏的「全文」下拉选「无 PDF」就只看还缺全文的，用来查漏。

点 **PDF** 徽章会**用你系统的默认 PDF 应用打开**（Windows 上是文件关联指向的那个，
macOS 上多半是「预览」）——浏览器内置阅读器做不了高亮批注，而系统阅读器的标注直接
存回同一个文件，下次点开还是这份。这条要 `serve` 开着；没开就自动退回浏览器打开，
功能不至于全丢。想直接用浏览器看，**按住 ⌘ / Ctrl 点**。

命令行：

```bash
python3 cli.py pdf --config <配置> --status                    # 覆盖情况
python3 cli.py pdf --config <配置> --fetch                     # 抓 OA 全文（全库补缺）
python3 cli.py pdf --config <配置> --fetch --pmid 42482656     # 只抓这几篇
python3 cli.py pdf --config <配置> --import ~/Downloads/论文    # 从文件夹认领
python3 cli.py pdf --config <配置> --import ~/下载 --dry-run    # 先看会认领哪些
python3 cli.py pdf --config <配置> --add --pmid 42482656 --file ~/x.pdf
```

**「有没有 PDF」以文件系统为准**，不在库表里另存字段——两处记录必然会漂移（手动往
目录里丢文件、或手动删文件都会让字段撒谎）。

`--fetch` 走两条免费路：PMC（Europe PMC 直出 PDF）和 Unpaywall 的 OA 直链（后者需
在 `.env` 配 `UNPAYWALL_EMAIL`，不配就只走前一条）。**新收藏的文献在网页上添加时会自动
走一遍这个流程**，所以日常多半不用手动跑；`--fetch` 主要用来给早先收的文献补全文。**订阅刊（Nature / NEJM /
Lancet 等）多半两条都抓不到，这是预期结果**，那些仍靠自己下载后拖进页面。抓下来的
一律校验 `%PDF` 文件头——出版商的拦截页是 200 + HTML，不验就会存下一堆「请登录」。

`--import` 按三级认领：文件名里的 PMID → 正文里的 DOI → 正文里出现库内标题。下载
下来的文件多半已被改成人话文件名，所以实际主要靠后两级，**需要装 PyMuPDF**：

```bash
pip install PyMuPDF
```

没装也能跑，只是退化成只认文件名里的 PMID。认不出的文件原样留在原处不动，`--move`
只删认领成功的那些。拿不准就先 `--dry-run`。

### 项目标签

与板块/子板块**正交**：板块回答「这篇是什么」（自动分类），项目回答
「我拿它干什么」（手动归档）。一篇可属多个项目，且**可跨板块**——
比如一个课题会同时用到心脏、消化、代谢几个板块下的文献。

日常用网页：勾选文献 → 点「加入项目」→ 弹窗里**勾选已有项目（可多选）**，或在下方
输入框里打个新名字即新建。每个项目后面标着「已含 2/5 篇」，一眼看出勾选的文献里有几篇
已经在里面了。「移出项目」只列勾选文献实际所属的项目，选完即时生效，不用刷新页面。

> 早先这里是个 `prompt()` 让人手打项目名——打错一个字就静默新建了个近似重名的项目，
> 而且看不到哪些勾选的文献已经在里面。

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
| `pdf` | 全文 PDF：`--status` / `--fetch` / `--import <目录>` / `--add --file` |
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
- [x] **M2** 本地收藏库（SQLite + 可筛选页面 + 项目标签 + 全文 PDF）
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
