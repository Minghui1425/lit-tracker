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
import time
import unicodedata
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

def _download(url: str) -> bytes | None:
    """下载并确认真的是 PDF（出版商常返回 HTML 拦截页 + 200）。"""
    try:
        r = requests.get(url, timeout=90, allow_redirects=True,
                         headers={"User-Agent": f"Mozilla/5.0 ({entrez.TOOL})"})
        if r.status_code != 200 or r.content[:4] != _MAGIC:
            return None
        return r.content
    except requests.RequestException:
        return None


def fetch_oa(pmid: str, doi: str = "", pmcid: str = "") -> tuple:
    """尝试免费拿到某篇的 PDF，返回 (bytes|None, 来源说明)。

    两条路：① PMC（Europe PMC 的 ?pdf=render 直出 PDF）；② Unpaywall 的 best OA
    location 直链（需 .env 配 UNPAYWALL_EMAIL，未配则跳过）。订阅刊多数两条路都拿
    不到，这是预期结果，不是 bug——那些仍靠手动拖进页面。
    """
    if pmcid:
        data = _download(f"https://europepmc.org/articles/{pmcid}?pdf=render")
        if data:
            return data, f"PMC({pmcid})"
    email = os.environ.get("UNPAYWALL_EMAIL", "").strip()
    if doi and email:
        try:
            j = requests.get(f"https://api.unpaywall.org/v2/{doi}",
                             params={"email": email}, timeout=30).json()
            loc = j.get("best_oa_location") or {}
            for url in (loc.get("url_for_pdf"), loc.get("url")):
                if not url:
                    continue
                data = _download(url)
                if data:
                    return data, f'Unpaywall({loc.get("host_type") or "oa"})'
        except (requests.RequestException, ValueError) as e:
            log.warning(f"Unpaywall 查询失败：{entrez.mask_secret(e)}")
    elif doi and not email:
        log.debug("未设置 UNPAYWALL_EMAIL，跳过 Unpaywall 这条路")
    return None, ""


def fetch_many(articles: list[dict], pdf_dir: Path, *,
               skip_existing: bool = True, sleep: float = 0.3) -> dict:
    """批量抓 OA 全文。articles 里每项要有 pmid，doi 可缺。"""
    got = have(pdf_dir)
    todo = [a for a in articles if not (skip_existing and a["pmid"] in got)]
    if not todo:
        return {"requested": len(articles), "fetched": 0, "failed": 0,
                "skipped": len(articles), "detail": []}

    pmc = entrez.pmc_ids([a["pmid"] for a in todo])
    fetched = failed = 0
    detail = []
    for a in todo:
        data, src = fetch_oa(a["pmid"], a.get("doi") or "", pmc.get(a["pmid"], ""))
        if data:
            try:
                save(pdf_dir, a["pmid"], data)
            except PdfError as e:
                failed += 1
                detail.append({"pmid": a["pmid"], "ok": False, "source": "", "error": str(e)})
                continue
            fetched += 1
            detail.append({"pmid": a["pmid"], "ok": True, "source": src})
            log.info(f"  ✓ {a['pmid']}  {src}  {len(data)//1024}KB")
        else:
            failed += 1
            detail.append({"pmid": a["pmid"], "ok": False, "source": ""})
        time.sleep(sleep)
    return {"requested": len(articles), "fetched": fetched, "failed": failed,
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
