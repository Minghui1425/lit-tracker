"""全文 PDF 附件：存放、抓取（PMC / Unpaywall）、从文件夹认领。

文件名固定 `<收藏库目录>/pdf/<pmid>.pdf`，收藏库页面用**相对**链接 `pdf/<pmid>.pdf`
打开——相对链接在 file:// 下同源，浏览器直接用内置阅读器打开；走 http:// 时由
`cli.py serve` 提供同一路径。

「有没有 PDF」以**文件系统为唯一真相源**，不在 articles 表另存字段：库表和目录两处
记录必然会漂移（手动往目录里丢文件、或手动删文件都会让字段撒谎）。几百篇量级下
每次生成页面 listdir 一次的开销可以忽略。
"""
from __future__ import annotations

import datetime
import logging
import os
import re
import subprocess
import sys
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from . import entrez

log = logging.getLogger(__name__)

_MAGIC = b"%PDF"
_PMID_RE = re.compile(r"^\d{1,9}$")

# 网页上传要经 base64（体积 +33%）在内存里走一圈，故卡得紧一些；本地文件直接读写，
# 放宽到 200MB——带大图的论文确实有近百 MB 的。
MAX_BYTES = 60 * 1024 * 1024
IMPORT_MAX_BYTES = 200 * 1024 * 1024
FETCH_MAX = 50          # 单次 OA 抓取上限，免得一个请求挂住服务几分钟


class PdfError(ValueError):
    """用户能看懂并自行处理的问题，信息可直接展示。"""


def dir_for(db_path: Path) -> Path:
    return Path(db_path).parent / "pdf"


def path_for(pdf_dir: Path, pmid: str) -> Path:
    return Path(pdf_dir) / f"{str(pmid).strip()}.pdf"


def have(pdf_dir: Path) -> set[str]:
    """已有 PDF 的 PMID 集合（扫目录，不查库）。"""
    d = Path(pdf_dir)
    return {p.stem for p in d.glob("*.pdf")} if d.is_dir() else set()


def save(pdf_dir: Path, pmid: str, data: bytes, *,
         max_bytes: int = MAX_BYTES) -> Path:
    """写入 pdf/<pmid>.pdf。

    校验 %PDF 文件头——出版商拦截页、登录页都是 200 + HTML，不验头就会把一堆
    「请登录」的网页当成全文存下来，等到要读的时候才发现。
    """
    pmid = str(pmid).strip()
    if not _PMID_RE.match(pmid):
        raise PdfError(f"不是合法的 PMID：{pmid}")
    if not data or data[:4] != _MAGIC:
        raise PdfError("这不是有效的 PDF（缺少 %PDF 文件头）")
    if len(data) > max_bytes:
        raise PdfError(f"PDF 有 {len(data)//1024//1024}MB，超过 {max_bytes//1024//1024}MB 上限")
    dest = path_for(pdf_dir, pmid)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def open_external(pdf_dir: Path, pmid: str) -> str:
    """用系统默认 PDF 应用打开某篇全文，返回一句能告诉用户「用什么开的」。

    浏览器内置阅读器做不了高亮批注，而系统阅读器的标注能直接存回同一个文件——文件
    就在 pdf/<pmid>.pdf，批注后下次点开还是这份，不会丢。

    交给系统的默认关联程序，不指定具体应用：Windows 上可能是 Edge / Acrobat，
    macOS 上多半是「预览」，各人装了什么就用什么。
    """
    p = path_for(pdf_dir, pmid)
    if not p.exists():
        raise PdfError(f"PMID {pmid} 还没有 PDF")
    if sys.platform.startswith("win"):
        # os.startfile 直接走文件关联，不像 `cmd /c start` 那样要跟引号较劲
        os.startfile(str(p))            # type: ignore[attr-defined]  # noqa: S606
        return "系统默认 PDF 应用"
    cmd = ["open", str(p)] if sys.platform == "darwin" else ["xdg-open", str(p)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise PdfError((r.stderr or "").strip() or f"打开失败（退出码 {r.returncode}）")
    return "系统默认 PDF 应用"


def trash(pdf_dir: Path, pmid: str) -> bool:
    """移除某篇的 PDF：挪进 pdf/_trash/ 而不是真删，误删可捞回。"""
    src = path_for(pdf_dir, pmid)
    if not src.exists():
        return False
    tdir = Path(pdf_dir) / "_trash"
    tdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    src.rename(tdir / f"{src.stem}_{stamp}.pdf")
    return True


# ─── OA 全文抓取 ──────────────────────────────────────────────────────────────

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")

# 出版商官网普遍拦截非浏览器客户端（Cloudflare / 反爬），脚本永远拿不到。这份名单
# 只用来给 OA location 排序：仓储副本优先、出版商官网垫底，不是黑名单。
_PUBLISHER_HOSTS = ("elsevier", "sciencedirect", "wiley", "cell.com", "thelancet",
                    "springer", "nature.com", "jamanetwork", "acs.org", "tandfonline",
                    "bmj.com", "oup.com", "mdpi.com", "pnas.org", "ascopubs", "ovid.com")

_local = threading.local()


def _session() -> requests.Session:
    """每线程一个 Session。

    连接复用是必需的，不是优化：逐次新建 TLS 连接时 api.unpaywall.org 会大量
    SSLEOFError（"EOF occurred in violation of protocol"），而每次失败还要耗掉
    requests 内部几十秒的重试。改成 Session + 退避后，实测一百多篇的查询从
    「几分钟才跑完几篇」变成半分钟跑完。
    """
    s = getattr(_local, "s", None)
    if s is None:
        s = requests.Session()
        s.headers["User-Agent"] = _UA
        _local.s = s
    return s


def _download(url: str, tries: int = 3) -> bytes | None:
    """下载并确认真的是 PDF（出版商常返回 HTML 拦截页 + 200）。"""
    for attempt in range(tries):
        try:
            r = _session().get(url, timeout=60, allow_redirects=True)
            if r.status_code == 200 and r.content[:4] == _MAGIC:
                return r.content
            return None                 # 明确的非 PDF 响应，重试没有意义
        except requests.RequestException:
            if attempt == tries - 1:
                return None
            time.sleep(2 ** attempt)
    return None


def _pdf_urls(url: str) -> list[str]:
    """把 OA 落地页地址改写成可能的 PDF 直链。

    Unpaywall 的 location 常常只给文章页（url）而没有 url_for_pdf，但多数纯 OA
    平台的 PDF 地址是可推导的。只覆盖不拦脚本的那几家——Elsevier/Wiley 之类推导
    出来也是 403，白费一次请求。
    """
    base = url.split("?")[0].rstrip("/")

    # PMC：location 里常直接带 PMCID，等于白送——不必再问 elink（NCBI 抽风时，
    # 这条是唯一的 PMC 来源）。域名要认全：新版是 pmc.ncbi.nlm.nih.gov/articles/PMC…，
    # 旧版是 …/pmc/articles/PMC…，只认一种会白扔掉一批现成的 PMCID。
    m = re.search(r"(PMC\d+)", base)
    if m and ("pmc.ncbi.nlm.nih.gov" in base or "europepmc.org" in base
              or "/pmc/articles/" in base):
        return [f"https://europepmc.org/articles/{m.group(1)}?pdf=render", url]

    out = [url]
    if "frontiersin.org" in url and base.endswith("/full"):
        out.append(base[:-len("/full")] + "/pdf")       # /full → /pdf，不是追加
    elif "biomedcentral.com" in url and "/articles/" in base:
        out.append(base.replace("/articles/", "/counter/pdf/") + ".pdf")
    return out


def _unpaywall(doi: str, email: str) -> dict | None:
    """查 Unpaywall。404（未收录）与查不到都返回 None。"""
    for attempt in range(4):
        try:
            r = _session().get(f"https://api.unpaywall.org/v2/{doi}",
                               params={"email": email}, timeout=15)
            if r.status_code == 404:            # 没收录，不是错误
                return None
            # 5xx 基本都是限流（批量跑时成片出现 500），退避重试而不是当失败
            if r.status_code >= 500:
                raise requests.HTTPError(f"{r.status_code} from Unpaywall")
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            if attempt == 3:
                log.warning(f"Unpaywall 查询失败：{entrez.mask_secret(e)}")
                return None
            time.sleep(3 * (attempt + 1) ** 2)          # 3s / 12s / 27s
    return None


def fetch_oa(pmid: str, doi: str = "", pmcid: str = "") -> tuple:
    """尝试免费拿到某篇的 PDF，返回 (bytes|None, 来源说明)。

    两条路：① PMC（Europe PMC 的 ?pdf=render 直出 PDF）；② Unpaywall 列出的 OA
    副本（需 .env 配 UNPAYWALL_EMAIL，未配则跳过）。订阅刊多数两条路都拿不到，
    这是预期结果，不是 bug——那些仍靠手动拖进页面。
    """
    if pmcid:
        data = _download(f"https://europepmc.org/articles/{pmcid}?pdf=render")
        if data:
            return data, f"PMC({pmcid})"
    email = os.environ.get("UNPAYWALL_EMAIL", "").strip()
    if not doi:
        return None, ""
    if not email:
        log.debug("未设置 UNPAYWALL_EMAIL，跳过 Unpaywall 这条路")
        return None, ""

    j = _unpaywall(doi, email)
    if not j or not j.get("is_oa"):
        return None, ""

    # 遍历**全部** oa_locations，不只 best_oa_location：best 往往指向出版商官网，
    # 而那些站点一律拦脚本；同一篇文章常另有 PMC / 机构仓储副本可以直接下。
    def _rank(loc):
        u = (loc.get("url_for_pdf") or loc.get("url") or "").lower()
        return (1 if any(h in u for h in _PUBLISHER_HOSTS) else 0,   # 仓储优先
                0 if loc.get("url_for_pdf") else 1)                  # 直链优先

    seen = set()
    for loc in sorted(j.get("oa_locations") or [], key=_rank):
        for cand in (loc.get("url_for_pdf"), loc.get("url")):
            if not cand:
                continue
            for url in _pdf_urls(cand):
                if url in seen:
                    continue
                seen.add(url)
                data = _download(url)
                if data:
                    return data, f'Unpaywall({loc.get("host_type") or "oa"})'
    return None, ""


def fetch_many(articles: list[dict], pdf_dir: Path, *,
               skip_existing: bool = True, workers: int = 2) -> dict:
    """批量抓 OA 全文。articles 里每项要有 pmid，doi 可缺。"""
    got = have(pdf_dir)
    todo = [a for a in articles if not (skip_existing and a["pmid"] in got)]
    if not todo:
        return {"requested": len(articles), "fetched": 0, "failed": 0,
                "skipped": len(articles), "detail": []}

    pmc = entrez.pmc_ids([a["pmid"] for a in todo])

    # 并发 2 路。串行时单篇失败要走完重试退避（几十秒），几百篇能拖一个多小时；
    # 但 4 路会把 Unpaywall 打到成片返回 500（限流），2 路实测稳定。
    #
    # 落盘必须在 worker 里做、只回传状态：Executor.map 会把**所有**返回值缓冲住，
    # 若回传 PDF bytes，全库跑一次就是几百份 PDF（单份可达几十 MB）同时堆在内存里。
    def _one(a):
        pmid = a["pmid"]
        try:
            data, src = fetch_oa(pmid, a.get("doi") or "", pmc.get(pmid, ""))
        except Exception as e:              # noqa: BLE001  一篇的意外不该中断整批
            return {"pmid": pmid, "ok": False, "source": "", "error": str(e)}
        if not data:
            return {"pmid": pmid, "ok": False, "source": ""}
        try:
            save(pdf_dir, pmid, data)
        except (PdfError, OSError) as e:
            return {"pmid": pmid, "ok": False, "source": "", "error": str(e)}
        log.info(f"  ✓ {pmid}  {src}  {len(data)//1024}KB")
        return {"pmid": pmid, "ok": True, "source": src}

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        detail = list(pool.map(_one, todo))
    fetched = sum(1 for d in detail if d["ok"])
    return {"requested": len(articles), "fetched": fetched,
            "failed": len(detail) - fetched,
            "skipped": len(articles) - len(todo), "detail": detail}


# ─── 从文件夹认领 ─────────────────────────────────────────────────────────────

_NAME_PMID_RE = re.compile(r"(?:^|[^\d])(\d{7,9})(?:[^\d]|$)")
_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", re.IGNORECASE)


def _norm(s: str) -> str:
    """比对用归一化：折叠 ﬁ/ﬂ 等连字，去掉所有非字母数字。

    PDF 抽出来的文字里 fi/fl 常是单个连字字符（U+FB01/02），不做 NFKD 归一化会让
    'identifies'/'inflammatory' 这类词永远匹配不上。
    """
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", s).lower())


def _head_text(path: Path, pages: int = 2) -> str:
    """读 PDF 前几页的文字。没装 PyMuPDF 时返回空串，退化为只按文件名认领。"""
    try:
        import fitz
    except ImportError:
        return ""
    try:
        # 有些 PDF 的 xref 有小毛病，MuPDF 会往 stderr 刷几十行 format error 但照样
        # 能抽出文字——关掉这些噪音，免得淹没认领结果
        fitz.TOOLS.mupdf_display_errors(False)
    except Exception:
        pass
    try:
        with fitz.open(path) as doc:
            return " ".join(doc[i].get_text() for i in range(min(pages, len(doc))))
    except Exception:
        return ""


def build_index(articles: list[dict]) -> dict:
    """给认领用的索引：PMID 集合、DOI→PMID、标题特征串→PMID。"""
    titles = {}
    for a in articles:
        # 用标题前 8 个词做特征串，够长才敢用（短标题容易撞车）
        frag = _norm(" ".join((a.get("title") or "").split()[:8]))
        if len(frag) >= 30:
            titles[frag] = a["pmid"]
    return {
        "pmids": {a["pmid"] for a in articles},
        "dois": {(a.get("doi") or "").lower(): a["pmid"] for a in articles if a.get("doi")},
        "titles": titles,
    }


def identify(path: Path, known: dict) -> tuple:
    """认领一个 PDF 属于库里哪篇，返回 (pmid|'', 依据)。

    三级：① 文件名里的 PMID；② 正文里的 DOI；③ 正文里出现库内标题。
    下载下来的文件多半已被改成人话文件名，所以 ① 基本指望不上，实际靠 ②③。
    """
    for g in _NAME_PMID_RE.findall(path.name):
        if g in known["pmids"]:
            return g, "文件名里的 PMID"
    text = _head_text(path)
    if not text:
        return "", ""
    for raw in _DOI_RE.findall(text):
        doi = raw.rstrip(".,;)").lower()
        for cand in (doi, doi.rsplit(".", 1)[0]):   # 尾部常粘上句号或页码
            if cand in known["dois"]:
                return known["dois"][cand], "正文 DOI"
    norm = _norm(text)
    for frag, pmid in known["titles"].items():
        if frag in norm:
            return pmid, "正文标题"
    return "", ""


def import_dir(src_dir, pdf_dir: Path, known: dict, *, move: bool = False,
               recursive: bool = True, dry_run: bool = False) -> dict:
    """把一个文件夹里的 PDF 认领进库（认不出的原样留下，不动源文件）。"""
    src_dir = Path(src_dir).expanduser()
    if not src_dir.is_dir():
        raise PdfError(f"目录不存在：{src_dir}")
    pdf_dir = Path(pdf_dir)
    files = sorted(src_dir.rglob("*.pdf") if recursive else src_dir.glob("*.pdf"))
    imported, unmatched, failed, taken = [], [], [], {}
    for f in files:
        if pdf_dir in f.parents:      # 别把库自己的 pdf/ 再认领一遍
            continue
        pmid, how = identify(f, known)
        if not pmid:
            unmatched.append(str(f))
            continue
        if pmid in taken:             # 同一篇匹配到多个文件（不同版本），只收第一个
            unmatched.append(f"{f}（与 {taken[pmid]} 同属 PMID {pmid}，已跳过）")
            continue
        if not dry_run:
            try:
                save(pdf_dir, pmid, f.read_bytes(), max_bytes=IMPORT_MAX_BYTES)
            except (PdfError, OSError) as e:
                # 单个文件出问题（超大、损坏、没权限）不能让整批中断
                failed.append({"file": str(f), "pmid": pmid, "error": str(e)})
                continue
            if move:
                f.unlink()
        taken[pmid] = f.name
        imported.append({"file": str(f), "pmid": pmid, "how": how})
    return {"imported": imported, "unmatched": unmatched, "failed": failed,
            "scanned": len(files)}
