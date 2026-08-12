#!/usr/bin/env python3
"""lit-tracker 统一入口。

配置有两条路，二选一即可：

  Excel（推荐，不用碰 YAML 缩进）
    python3 cli.py template   --out 我的配置.xlsx        # 生成空白模板
    python3 cli.py from-excel --excel 我的配置.xlsx      # 填好后转成 YAML

  直接写 YAML
    照 configs/example-minimal.yaml 改

然后：
    python3 cli.py check    --config configs/我的配置.yaml   # 离线校验（快）
    python3 cli.py validate --config configs/我的配置.yaml   # 联网核对期刊名与关键词
    python3 cli.py weekly   --config configs/我的配置.yaml [--date 2026-07-28]
    python3 cli.py history  --config configs/我的配置.yaml --from 2025-01-01 --to 2025-12-31

收藏库（存下看中的文献，网页可评级/写笔记/按课题分组）：
    python3 cli.py add       --config configs/我的配置.yaml --pmid 42482656
    python3 cli.py library   --config configs/我的配置.yaml   # 生成收藏库网页
    python3 cli.py serve     --config configs/我的配置.yaml   # 网页按钮的后端（含网页上「添加文献」），保持开着
    python3 cli.py citations --config configs/我的配置.yaml   # 算库内引用关系与被引数
    python3 cli.py pdf       --config configs/我的配置.yaml --status   # 全文 PDF 覆盖情况
"""
from __future__ import annotations

import argparse
import datetime
import logging
import os
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

try:
    from dotenv import load_dotenv
    load_dotenv(BASE / ".env")
except ImportError:
    pass

from littrack import config as cfgmod        # noqa: E402
from littrack import entrez, render, search  # noqa: E402
from littrack.journals import JournalIndex   # noqa: E402


def _setup_log(verbose: bool):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    # urllib3 的 DEBUG 会把完整 URL 打出来，其中含 api_key 与 email——
    # 我们自己的日志有脱敏，它没有。-v 常配合重定向到日志文件，密钥会就此落盘。
    logging.getLogger("urllib3").setLevel(logging.INFO)


def _load(path: str):
    try:
        return cfgmod.load(path)
    except cfgmod.ConfigError as e:
        print(f"\n配置有误：\n{e}\n", file=sys.stderr)
        sys.exit(1)


def _require_key():
    if not os.environ.get("NCBI_API_KEY"):
        print("未设置 NCBI_API_KEY。请在项目根目录建 .env 并写入：\n"
              "  NCBI_API_KEY=你的密钥\n"
              "（免费申请：https://www.ncbi.nlm.nih.gov/account/ → API Key Management）",
              file=sys.stderr)
        sys.exit(1)


def _translate(cfg, articles):
    """标题翻译。未配 DEEPL_API_KEY 时静默跳过，不影响主流程。"""
    if not cfg.translate_titles:
        return
    key = os.environ.get("DEEPL_API_KEY", "")
    if not key:
        for a in articles:
            a.setdefault("title_zh", "")
        return
    import time
    import requests
    url = ("https://api-free.deepl.com/v2/translate" if key.endswith(":fx")
           else "https://api.deepl.com/v2/translate")
    titles = [a["title"] for a in articles]
    out = [""] * len(titles)
    for i in range(0, len(titles), 50):
        batch = titles[i:i + 50]
        try:
            r = requests.post(url, headers={"Authorization": f"DeepL-Auth-Key {key}"},
                              json={"target_lang": "ZH", "text": batch}, timeout=30)
            r.raise_for_status()
            for j, t in enumerate(r.json().get("translations", [])):
                out[i + j] = t.get("text", "").rstrip("。.")
        except Exception as e:
            logging.warning(f"DeepL 翻译失败（第 {i//50+1} 批）：{e}")
        time.sleep(0.2)
    for a, zh in zip(articles, out):
        a["title_zh"] = zh


def _run(cfg, start: str, end: str, tag: str):
    _require_key()
    idx = JournalIndex.load(BASE / "if_data.json")
    if not idx.available and any(s.quality_filter for s in cfg.sections):
        logging.warning("未找到 if_data.json，分区/IF 过滤本次跳过（不会因此漏掉文章）")

    arts = search.run(cfg, start, end, journals=idx)
    logging.info(f"合计收录 {len(arts)} 篇")
    _translate(cfg, arts)
    grouped = search.group_by_section(cfg, arts)

    out = (BASE / cfg.output_dir / f"{tag}_{start}_{end}.html")
    # 报告页上的「加入收藏库」要打本地服务，凭据与收藏库页面用同一枚
    render.render(cfg, grouped, start, end, out,
                  port=_port(), token=_token(BASE / cfg.output_dir))
    logging.info(f"HTML 已写入：{out}")
    for sec, subs in grouped.items():
        logging.info(f"  [{sec}] {sum(len(v) for v in subs.values())} 篇")
        for sub, v in subs.items():
            logging.info(f"     {sub}: {len(v)}")
    return out


def _import_refs(cfg, db_path: Path, items: list, *, section: str = "",
                 subsection: str = "", fetch_pdf: bool = False, on_each=None) -> dict:
    """解析出的记录 → PMID → 入库。命令行与收藏库页面走同一条路。

    分批是必须的：`intake.collect` 一次最多 50 篇（每篇都要回 PubMed 取元数据），
    而导出文件动辄几百条。
    """
    from littrack import intake, refs
    r = refs.resolve(items, on_each=on_each)
    out = {**r, "added": 0, "updated": 0, "pdf_fetched": 0, "missing": []}
    idx = JournalIndex.load(BASE / "if_data.json")
    step = intake.MAX_PMIDS
    for i in range(0, len(r["pmids"]), step):
        res = intake.collect(cfg, db_path, r["pmids"][i:i + step], journals=idx,
                             section=section, subsection=subsection,
                             translate=_translate, fetch_pdf=fetch_pdf)
        out["added"] += res["added"]
        out["updated"] += res["updated"]
        out["pdf_fetched"] += res["pdf_fetched"]
        out["missing"] += res["missing"]
    return out


def _report_refs(r: dict) -> None:
    """把「哪些落到了 PMID、哪些没落上」讲清楚。没落上的多半不是 bug。"""
    print(f"\n落到 PMID 的有 {len(r['pmids'])} 篇"
          f"（文件里带的 {r['how']['pmid']} · DOI 查到 {r['how']['doi']} · "
          f"标题查到 {r['how']['title']}）")
    if r["unresolved"]:
        print(f"  没能落到 PMID 的 {len(r['unresolved'])} 条"
              f"（多半是书籍/网页/会议摘要，PubMed 本来就没有）：")
        for it in r["unresolved"]:
            print(f"    ? {(it['title'] or it['doi'] or '（无标题）')[:60]}：{it['why']}")


def _date(text: str, flag: str) -> datetime.date:
    try:
        return datetime.date.fromisoformat(text.strip())
    except ValueError:
        print(f"{flag} 的日期格式不对：{text!r}\n"
              f"  需要 YYYY-MM-DD，例：{flag} 2026-07-28", file=sys.stderr)
        sys.exit(1)


# ── 补跑判断（--catchup）────────────────────────────────────────────────────
# 定时任务的老问题：到点时电脑关着，这一期就没了。launchd 的 RunAtLoad 能在下次
# 登录时补一脚，但它的语义是「每次加载都跑」——每天开机就重跑一次，且按当天重新
# 回溯 7 天，只会产出一堆窗口互相重叠的报告。
#
# 所以 RunAtLoad 必须配 --catchup：以「上次运行日」为准，判断**本周期**是否已经
# 跑过；跑过就安静退出。周期起点取最近一个计划运行日（周几），因此手动跑一次不会
# 顶掉下个周期的定时跑。

def _period_start(today: datetime.date, weekday: int) -> datetime.date:
    """本周期的起点，即最近一个「周 weekday」（含今天）。

    weekday 用 launchd 的口径：0=周日, 1=周一 … 6=周六，与 plist 的 Weekday 键一致，
    免得用户在两处填不同的数字。
    """
    cur = (today.weekday() + 1) % 7          # Python 的 Mon=0 转成 launchd 的 Sun=0
    return today - datetime.timedelta(days=(cur - weekday) % 7)


def _marker(out_dir: Path, tag: str) -> Path:
    return out_dir / f".last_run_{tag}"


def _catchup_skip(out_dir: Path, tag: str, weekday: int,
                  today: datetime.date | None = None) -> bool:
    try:
        last = datetime.date.fromisoformat(
            _marker(out_dir, tag).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False                          # 没跑过 / 标记坏了，一律跑
    return last >= _period_start(today or datetime.date.today(), weekday)


def _mark_ran(out_dir: Path, tag: str) -> None:
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        _marker(out_dir, tag).write_text(datetime.date.today().isoformat(), encoding="utf-8")
    except OSError as e:
        logging.warning(f"写运行标记失败（不影响本次结果，但下次 --catchup 会重跑）：{e}")


_JRN_CACHE: list = []


def _jrn_index():
    """if_data.json 有几 MB，serve 每来一个请求都重读太浪费，进程内缓存一份。"""
    if not _JRN_CACHE:
        _JRN_CACHE.append(JournalIndex.load(BASE / "if_data.json"))
    return _JRN_CACHE[0]


def _vault() -> Path | None:
    d = os.environ.get("OBSIDIAN_DIR", "").strip()
    return Path(d).expanduser() if d else None


def _port() -> int:
    # 默认 8781：刻意避开常见的 8000/8080/8765 等端口，减少与机器上其它本地服务
    # 撞车的概率。撞车不只是起不来——若对方恰好有同名路由，请求会被它接走，
    # 从而误改到别的数据库（开发时真踩过一次）。可用 LITTRACK_PORT 覆盖。
    raw = os.environ.get("LITTRACK_PORT", "8781").strip()
    try:
        p = int(raw)
    except ValueError:
        print(f"LITTRACK_PORT 必须是数字，当前是 {raw!r}。", file=sys.stderr)
        sys.exit(1)
    if not 1024 <= p <= 65535:
        print(f"LITTRACK_PORT 需在 1024–65535 之间，当前是 {p}。", file=sys.stderr)
        sys.exit(1)
    return p


def _token(out_dir: Path) -> str:
    """收藏库写接口的凭据。

    页面把它放进请求头，服务端逐一校验。没有它的话，只要你开着 serve，
    任何网页都能对 127.0.0.1 发跨源请求改评级、加项目、甚至删文献——
    浏览器不阻止跨源**发送**，只阻止读取响应，而写操作已经生效了。
    首次调用生成并落盘（0600），此后各命令共用同一枚。
    """
    f = out_dir / ".token"
    try:
        t = f.read_text(encoding="utf-8").strip()
        if t:
            return t
    except OSError:
        pass
    import secrets
    t = secrets.token_urlsafe(24)
    out_dir.mkdir(parents=True, exist_ok=True)
    f.write_text(t, encoding="utf-8")
    try:
        os.chmod(f, 0o600)
    except OSError:
        pass
    return t


def _serve(cfg, db_path: Path, idx_path: Path):
    """收藏库页面的后端：评级、笔记、项目标签、删除。

    ⚠️ 常驻进程，Python 启动时载入代码，**改了源码必须重启本服务**，否则页面上的
    操作打到的仍是旧代码。
    """
    import hmac
    import http.server
    import json as _json
    from littrack import library, library_page

    port = _port()
    token = _token(db_path.parent)
    # file:// 打开的页面其 Origin 是 null。允许它，是因为真正的门是 token：
    # 别的网页拿不到 token，光有 Origin 白名单挡不住 no-cors 的写请求。
    allowed_origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}", "null"}

    # Host 白名单：挡 DNS rebinding——攻击者把自己的域名解析到 127.0.0.1，
    # 用户一访问，那个页面就变成「同源」，能读到首页里嵌的 token 再随意写库。
    # 浏览器发的 Host 头是用户输入的域名，所以只认这两个就能断掉这条路。
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _host_ok(self) -> bool:
            return (self.headers.get("Host", "") or "").lower() in allowed_hosts

        def _reject_host(self):
            self.send_response(403)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                f"Host 不被接受：{self.headers.get('Host', '')!r}。"
                f"请用 http://127.0.0.1:{port}/ 访问。".encode())

        def _cors(self):
            origin = self.headers.get("Origin")
            if origin in allowed_origins:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-LitTrack-Token")

        def _body_bytes(self) -> bytes:
            """必须先把请求体读干净再回响应。

            带 body 的请求若被直接拒掉（403/404）就关连接，未读的字节会让内核发 RST，
            客户端往往在读响应时收到 ConnectionReset，看到的不是「403 凭据不匹配」
            而是一个莫名其妙的连接错误。
            """
            try:
                ln = int(self.headers.get("Content-Length", 0))
            except ValueError:
                return b""
            return self.rfile.read(ln) if ln > 0 else b""

        def _authed(self) -> bool:
            return hmac.compare_digest(self.headers.get("X-LitTrack-Token", ""), token)

        def do_OPTIONS(self):
            self._body_bytes()
            if not self._host_ok():
                self._reject_host(); return
            self.send_response(200); self._cors(); self.end_headers()

        def do_GET(self):
            """同源地提供收藏库页面，这样用户可以走 http:// 而不是 file://。"""
            if not self._host_ok():
                self._reject_host(); return
            path = self.path.split("?", 1)[0]
            # 全文 PDF：页面里是相对链接 pdf/<pmid>.pdf，file:// 下浏览器自己就能开，
            # 走 http:// 时得由这里给。只认纯数字文件名，路径穿越无从谈起。
            m = re.fullmatch(r"/pdf/(\d{1,9})\.pdf", path)
            if m:
                from littrack import pdfs
                f = pdfs.path_for(pdfs.dir_for(db_path), m.group(1))
                try:
                    body = f.read_bytes()
                except OSError:
                    self.send_response(404); self.end_headers(); return
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers(); self.wfile.write(body); return
            if path not in ("/", "/library.html"):
                self.send_response(404); self.end_headers(); return
            try:
                body = idx_path.read_bytes()
            except OSError as e:
                self.send_response(500); self.end_headers()
                self.wfile.write(f"页面读取失败：{e}".encode()); return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)

        def do_POST(self):
            raw = self._body_bytes()          # 先读干净，无论后面放行还是拒绝
            if not self._host_ok():
                self._reject_host(); return
            routes = ("/rating", "/note", "/delete",
                      "/article/add", "/article/add-from-report", "/article/import",
                      "/pdf/upload", "/pdf/delete", "/pdf/fetch", "/pdf/open",
                      "/project/add", "/project/remove",
                      "/obsidian/export", "/obsidian/refresh")
            if self.path not in routes:
                self.send_response(404); self.end_headers(); return
            if not self._authed():
                self.send_response(403); self._cors(); self.end_headers()
                self.wfile.write("凭据不匹配".encode()); return
            try:
                d = _json.loads(raw) if raw else {}
                if self.path == "/rating":
                    library.set_rating(db_path, d["pmid"], d.get("rating", ""))
                    res = {"ok": True}
                elif self.path == "/note":
                    library.set_note(db_path, d["pmid"], d.get("text", ""))
                    res = {"ok": True}
                elif self.path == "/delete":
                    res = {"deleted": library.delete(db_path, d.get("pmids", []))}
                elif self.path == "/article/add":
                    from littrack import intake
                    if not os.environ.get("NCBI_API_KEY"):
                        raise ValueError("未设置 NCBI_API_KEY，无法向 PubMed 取数据。\n"
                                         "请在项目根目录的 .env 里写入 NCBI_API_KEY=你的密钥，"
                                         "然后重启本服务。")
                    pmids = intake.resolve(d.get("query", ""))
                    # 网页这条路默认顺手试抓全文：点一次按钮就该把该做的都做了，
                    # 用页面的人手边没有终端可以再补一条 pdf --fetch
                    r = intake.collect(cfg, db_path, pmids, journals=_jrn_index(),
                                       section=(d.get("section") or "").strip(),
                                       subsection=(d.get("subsection") or "").strip(),
                                       translate=_translate, fetch_pdf=True)
                    res = {k: r[k] for k in ("added", "updated", "existing",
                                             "missing", "pdf_fetched")}
                elif self.path == "/article/import":
                    # EndNote / Zotero 导出文件：页面把文件内容当文本发上来（不传路径，
                    # 服务端也就不必去读用户磁盘上的任意文件）。
                    from littrack import refs
                    text = d.get("content") or ""
                    if not isinstance(text, str) or not text.strip():
                        raise ValueError("文件是空的")
                    name = str(d.get("name") or "")[:120]
                    # 先解析再查密钥：文件本身有问题的话，此刻就该告诉用户，
                    # 而不是先甩一句「没设 NCBI_API_KEY」让人查错方向
                    fmt, items = refs.parse_text(text, name, Path(name).suffix)
                    if not os.environ.get("NCBI_API_KEY"):
                        raise ValueError("未设置 NCBI_API_KEY，无法向 PubMed 取数据。\n"
                                         "请在项目根目录的 .env 里写入 NCBI_API_KEY=你的密钥，"
                                         "然后重启本服务。")
                    r = _import_refs(cfg, db_path, items,
                                     section=(d.get("section") or "").strip(),
                                     subsection=(d.get("subsection") or "").strip(),
                                     fetch_pdf=True)
                    res = {"format": refs.FORMAT_NAMES[fmt], "records": len(items),
                           "resolved": len(r["pmids"]), "how": r["how"],
                           "added": r["added"], "updated": r["updated"],
                           "missing": r["missing"], "pdf_fetched": r["pdf_fetched"],
                           "unresolved": [{"title": u["title"], "doi": u["doi"],
                                           "why": u["why"]} for u in r["unresolved"]]}
                elif self.path == "/article/add-from-report":
                    # 周报 / 历史报告页上勾选后的「加入收藏库」。板块与子板块取自
                    # 那页 —— 报告生成时就归好类了，用户看到什么就存成什么。
                    from littrack import intake
                    if not os.environ.get("NCBI_API_KEY"):
                        raise ValueError("未设置 NCBI_API_KEY，无法向 PubMed 取数据。\n"
                                         "请在项目根目录的 .env 里写入 NCBI_API_KEY=你的密钥，"
                                         "然后重启本服务。")
                    items = d.get("items") or []
                    if not isinstance(items, list):
                        raise ValueError("items 需要是数组")
                    pmids = intake.parse_pmids([str(i.get("pmid", "")) for i in items])
                    smap = {str(i.get("pmid", "")).strip():
                            ((i.get("section") or "").strip(),
                             (i.get("subsection") or "").strip())
                            for i in items if (i.get("section") or "").strip()}
                    r = intake.collect(cfg, db_path, pmids, journals=_jrn_index(),
                                       section_map=smap, translate=_translate,
                                       fetch_pdf=True)
                    res = {k: r[k] for k in ("added", "updated", "existing",
                                             "missing", "pdf_fetched")}
                elif self.path.startswith("/pdf/"):
                    from littrack import pdfs
                    pdf_dir = pdfs.dir_for(db_path)
                    if self.path == "/pdf/upload":
                        pmid = str(d.get("pmid", "")).strip()
                        known = {a["pmid"] for a in library.all_articles(db_path)}
                        if pmid not in known:
                            raise ValueError(f"PMID {pmid} 不在收藏库里，请先添加文献再挂 PDF")
                        import base64
                        try:
                            raw = base64.b64decode(d.get("content", ""), validate=True)
                        except Exception:
                            raise ValueError("PDF 内容解码失败，请重试")
                        pdfs.save(pdf_dir, pmid, raw)
                        res = {"pmid": pmid, "bytes": len(raw)}
                    elif self.path == "/pdf/open":
                        pmid = str(d.get("pmid", "")).strip()
                        if not re.fullmatch(r"\d{1,9}", pmid):
                            raise ValueError(f"不是合法的 PMID：{pmid}")
                        res = {"pmid": pmid, "app": pdfs.open_external(pdf_dir, pmid)}
                    elif self.path == "/pdf/delete":
                        pmid = str(d.get("pmid", "")).strip()
                        res = {"pmid": pmid, "removed": pdfs.trash(pdf_dir, pmid)}
                    else:
                        want = [str(p) for p in d.get("pmids", [])]
                        if len(want) > pdfs.FETCH_MAX:
                            raise ValueError(f"一次最多抓 {pdfs.FETCH_MAX} 篇")
                        arts = [a for a in library.all_articles(db_path)
                                if a["pmid"] in set(want)]
                        res = pdfs.fetch_many(arts, pdf_dir)
                elif self.path.startswith("/obsidian/"):
                    root = _vault()
                    if not root:
                        raise ValueError(
                            "未设置 Obsidian 目录。请在 .env 里加一行：\n"
                            "  OBSIDIAN_DIR=/你的/vault/某个文件夹\n"
                            "改完需重启本服务才生效。")
                    from littrack import obsidian
                    pmids = d.get("pmids", []) if self.path.endswith("export") else []
                    res = obsidian.export(cfg, db_path, root, pmids)
                elif self.path == "/project/add":
                    name = (d.get("name") or "").strip()
                    if not name:
                        raise ValueError("项目名不能为空")
                    res = library.add_to_project(db_path, name, d.get("pmids", []))
                else:
                    name = (d.get("name") or "").strip()
                    if not name:
                        raise ValueError("项目名不能为空")
                    res = {"removed": library.remove_from_project(db_path, name, d.get("pmids", []))}
                # /note 改得频繁，/pdf/open 根本没改任何东西——都不必重渲染
                if self.path not in ("/note", "/pdf/open"):
                    library_page.render(cfg, db_path, idx_path, port=port, token=token)
                body = _json.dumps(res, ensure_ascii=False).encode()
                self.send_response(200); self._cors()
                self.send_header("Content-Type", "application/json")
                self.end_headers(); self.wfile.write(body)
            except Exception as e:
                self.send_response(500); self._cors(); self.end_headers()
                self.wfile.write(str(e).encode())

    # 页面里嵌的 token 可能是旧的（比如换过 token 文件），启动时重渲染一次保证一致
    library_page.render(cfg, db_path, idx_path, port=port, token=token)
    try:
        srv = http.server.HTTPServer(("127.0.0.1", port), H)
    except OSError as e:
        if getattr(e, "errno", None) == 48:      # Address already in use
            print(f"端口 {port} 已被占用——很可能是本机另一个服务在用。\n"
                  f"  这不只是起不来的问题：若那个服务恰好有同名接口，页面上的操作会被它\n"
                  f"  接走，从而误改到别的数据库。请换端口再起：\n"
                  f"    LITTRACK_PORT=8782 python3 cli.py serve --config {cfg.path}\n"
                  f"  查看占用者：lsof -nP -iTCP:{port} -sTCP:LISTEN", file=sys.stderr)
            sys.exit(1)
        raise
    print(f"✓ 收藏库服务已启动，请在浏览器打开：http://127.0.0.1:{port}/")
    print(f"  （也可以直接双击 {idx_path}，两种打开方式都能用）")
    print(f"  ⚠️ 改过代码后要重启本服务，否则页面操作走的还是旧代码")
    print("  按 Ctrl+C 停止")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n✓ 服务已停止")
    finally:
        srv.server_close()


def main():
    ap = argparse.ArgumentParser(
        description="按配置追踪 PubMed 文献",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    ap.add_argument("command", choices=["template", "from-excel", "check", "validate",
                                        "weekly", "history", "add", "import-refs",
                                        "library", "obsidian", "project", "import-if",
                                        "serve", "citations", "pdf"])
    ap.add_argument("--pmid", nargs="+", help="add：要收藏的 PMID，可多个")
    ap.add_argument("--section", help="add：手动指定板块（默认按配置自动判定）")
    ap.add_argument("--subsection", help="add：手动指定子板块")
    ap.add_argument("--projects", action="store_true", help="library：列出所有项目")
    # project 子命令
    ap.add_argument("--name", help="project：要操作的项目名")
    ap.add_argument("--list", action="store_true", help="project：列出所有项目")
    ap.add_argument("--add", action="store_true", help="project：把 --pmid 加入该项目")
    ap.add_argument("--remove", action="store_true", help="project：把 --pmid 移出该项目")
    ap.add_argument("--rename", metavar="新名", help="project：给项目改名")
    ap.add_argument("--delete", action="store_true",
                    help="project：删除项目（只解散分组，不删文献）")
    ap.add_argument("--archive", action="store_true", help="project：归档项目")
    ap.add_argument("--unarchive", action="store_true", help="project：取消归档")
    ap.add_argument("--all", action="store_true", help="obsidian：导出库中全部文献")
    # pdf 子命令（--add / --delete / --pmid 与上面共用）
    ap.add_argument("--fetch", action="store_true",
                    help="pdf：抓 OA 全文（PMC / Unpaywall），不带 --pmid 就补全库里缺的")
    ap.add_argument("--no-fetch", action="store_true",
                    help="add / import-refs：不要顺手试抓 OA 全文（默认会试）")
    ap.add_argument("--import", dest="imp", metavar="目录",
                    help="pdf：把一个文件夹里的 PDF 按 DOI/标题认领进库")
    ap.add_argument("--move", action="store_true",
                    help="pdf --import：认领成功后删掉源文件（默认只复制）")
    ap.add_argument("--dry-run", action="store_true",
                    help="pdf --import / import-refs：只报告会做什么，不真的写入")
    ap.add_argument("--file", help="pdf --add：本地 PDF 路径；"
                                   "import-refs：EndNote/Zotero 导出的文献文件")
    ap.add_argument("--status", action="store_true", help="pdf：看全文覆盖情况")
    ap.add_argument("--config", "-c", help="YAML 配置文件路径")
    ap.add_argument("--excel", "-e", help="Excel 配置文件路径")
    ap.add_argument("--out", "-o", help="输出路径（template / from-excel 用）")
    ap.add_argument("--date", help="weekly：以该日为运行日，回溯 7 天（默认今天）")
    ap.add_argument("--from", dest="start", help="history：起始日期 YYYY-MM-DD")
    ap.add_argument("--to", dest="end", help="history：截止日期 YYYY-MM-DD")
    ap.add_argument("--force", action="store_true",
                    help="citations：忽略已抓记录，全部重抓")
    ap.add_argument("--catchup", type=int, metavar="周几",
                    help="weekly / citations：本周期已跑过则跳过（给定时任务用）。"
                         "填计划运行的星期，与 plist 的 Weekday 一致：0=周日 … 6=周六")
    ap.add_argument("--journals-only", action="store_true",
                    help="validate：只核对期刊名，跳过关键词（快很多）")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    _setup_log(args.verbose)

    # ── 导入 JCR 名单生成 if_data.json ──
    if args.command == "import-if":
        from littrack import jcr
        out = args.out or (BASE / "if_data.json")
        if args.excel:
            r = jcr.build(args.excel, out)
            src = "你提供的 JCR 名单"
        else:
            print("未指定 --excel，改从第三方公开仓库（EasyPubMed）下载其整理的 JCR 数据…")
            try:
                r = jcr.download(out)
            except Exception as e:
                print(f"\n下载失败：{e}\n"
                      f"  可改用自己的 JCR 名单：\n"
                      f"    python3 cli.py import-if --excel <你的JCR名单.xlsx>",
                      file=sys.stderr)
                sys.exit(1)
            src = "第三方仓库 EasyPubMed（可能略滞后于官方 JCR）"
        print(f"✓ 已生成：{r['path']}")
        print(f"  来源：{src}")
        print(f"  读取 {r['read']} 条，成功 {r['ok']} 本期刊")
        print(f"  索引：ISSN {r['issn']} 条 · 刊名 {r['name']} 条")
        print(f"  该文件已被 .gitignore 排除，不会随仓库分发")
        if not args.excel:
            print(f"  ⚠️ IF/分区的原始指标出自 Clarivate 的 JCR（商业订阅产品）。"
                  f"本项目未核实\n"
                  f"     该数据包的独立授权，请自行判断在你的场景下能否使用；"
                  f"有顾虑请改用\n"
                  f"     单位订阅导出的名单：import-if --excel <你的JCR名单.xlsx>")
        return

    # ── 生成 Excel 模板 ──
    if args.command == "template":
        from littrack import excel
        out = Path(args.out or "我的配置.xlsx").expanduser()
        p = excel.write_template(out)
        print(f"✓ 模板已生成：{p}\n\n"
              f"  打开后先看第一页「{excel.GUIDE}」——那里讲了「关键词/交叉」的区别\n"
              f"  和「质量过滤」怎么设，是最容易填错的两处。\n\n"
              f"  然后填这 4 张表：{'、'.join(excel.SHEETS)}\n"
              f"    第 1 行列名、第 2 行填写提示（别删）、第 3 行起填内容\n"
              f"    带下拉箭头的格子直接选，不用手打\n"
              f"    模板自带示例行，照着改或删掉重填都行\n\n"
              f"  「保留类型 / 排除类型」两列不用自己想：「{excel.TYPES_SHEET}」页列了\n"
              f"  全部 {len(excel._VALID_PUB_TYPES)} 种 PubMed 类型和中文对照，示例行已按建议预填。\n\n"
              f"  填好后运行：python3 cli.py from-excel --excel {p.name}")
        return

    # ── Excel → YAML ──
    if args.command == "from-excel":
        from littrack import excel
        if not args.excel:
            ap.error("from-excel 需要 --excel 指定填好的 Excel 文件")
        src = Path(args.excel).expanduser()
        try:
            data = excel.read_excel(src)
            cfg = cfgmod.load_dict(data)          # 复用同一套校验
        except cfgmod.ConfigError as e:
            print(f"\nExcel 内容有误：\n{e}\n", file=sys.stderr)
            sys.exit(1)
        out = Path(args.out or (BASE / "configs" / (src.stem + ".yaml"))).expanduser()
        excel.to_yaml(data, out)
        print(f"✓ 已生成配置：{out}")
        print(f"  板块（顺序即去重优先级）：")
        for s in cfg.sections:
            print(f"    · {s.name}  [{s.matcher} / {s.scope}]"
                  f"  子板块：{' > '.join(s.subsection_names)}")
        print(f"  期刊：全量收录 {len(cfg.full_inclusion_journals)} 本 / "
              f"关键词筛选 {len(cfg.keyword_filtered_journals)} 本")
        print(f"\n  下一步建议联网核对期刊名与关键词（能提前发现写错的期刊）：\n"
              f"    python3 cli.py validate --config {out}")
        return

    if not args.config:
        ap.error(f"{args.command} 需要 --config 指定配置文件")
    cfg = _load(args.config)
    db_path = BASE / cfg.output_dir / "library.db"
    idx_path = BASE / cfg.output_dir / "library.html"

    # ── 收藏库 ──
    if args.command == "add":
        if not args.pmid:
            ap.error("add 需要 --pmid，例：--pmid 42031428 42482656")
        _require_key()
        from littrack import intake
        idx = JournalIndex.load(BASE / "if_data.json")
        try:
            pmids = intake.parse_pmids([str(p) for p in args.pmid])
            res = intake.collect(cfg, db_path, pmids, journals=idx,
                                 section=args.section or "",
                                 subsection=args.subsection or "",
                                 translate=_translate, fetch_pdf=not args.no_fetch)
        except intake.IntakeError as e:
            print(e, file=sys.stderr)
            sys.exit(1)
        arts, added, updated = res["articles"], res["added"], res["updated"]
        from littrack import library_page
        library_page.render(cfg, db_path, idx_path, port=_port(),
                            token=_token(db_path.parent))
        print(f"✓ 新增 {added} 篇"
              + (f"，更新 {updated} 篇（已在库中，已按当前配置重新归类；"
                 f"你的笔记与评级保留）" if updated else ""))
        if res["missing"]:
            print(f"    PubMed 没有这些 PMID：{'、'.join(res['missing'])}")
        if not args.no_fetch and added:
            print(f"    其中 {res['pdf_fetched']} 篇已自动挂上 OA 全文"
                  + ("" if res["pdf_fetched"] else "（订阅刊没有 OA 版本，需自行下载）"))
        unmatched = []
        for a in arts:
            if a["section"]:
                print(f"    [{a['section']} / {a['subsection']}] {a['title'][:66]}")
            else:
                unmatched.append(a)
                print(f"    [未归板块] {a['title'][:66]}")
        if unmatched:
            print(f"\n  ⚠️ 有 {len(unmatched)} 篇标题没命中当前配置的任何板块关键词，"
                  f"已按「未归板块」存入。\n"
                  f"     这类文章在收藏库页面的板块筛选里选不到，建议二选一：\n"
                  f"       · 重新入库时手动指定： --section <板块名> [--subsection <子板块名>]\n"
                  f"       · 或在配置里补上相应关键词后重新入库\n"
                  f"     当前配置的板块：{'、'.join(cfg.section_names)}")
        print(f"\n  收藏库页面：{idx_path}")
        return

    # ── 从 EndNote / Zotero 的导出文件批量入库 ──
    if args.command == "import-refs":
        if not args.file:
            ap.error("import-refs 需要 --file 指定导出文件，"
                     "例：--file ~/Downloads/My Library.ris")
        _require_key()
        from littrack import intake, library_page, refs
        try:
            fmt, items = refs.read_file(args.file)
        except refs.RefError as e:
            print(f"错误：{e}", file=sys.stderr); sys.exit(1)
        ready = sum(1 for r in items if r["pmid"])
        print(f"{Path(args.file).name}：按 {refs.FORMAT_NAMES[fmt]} 解析出 {len(items)} 条，"
              f"其中 {ready} 条自带 PMID")
        if ready < len(items):
            print(f"  另外 {len(items)-ready} 条要回 PubMed 按 DOI / 标题查，会慢一些…")

        def _tick(i, total, ref, pmid, why):
            tag = {"pmid": "文件里的 PMID", "doi": "按 DOI 查到",
                   "title": "按标题查到"}.get(why, why)
            head = f"  [{i}/{total}]"
            print(f"{head} {pmid} … {tag}" if pmid
                  else f"{head} ✗ {(ref['title'] or ref['doi'] or '（无标题）')[:50]}：{tag}")

        if args.dry_run:
            r = refs.resolve(items, on_each=_tick)
            _report_refs(r)
            print(f"\n--dry-run：以上 {len(r['pmids'])} 篇未写入。去掉 --dry-run 即入库。")
            return
        try:
            r = _import_refs(cfg, db_path, items, section=args.section or "",
                             subsection=args.subsection or "",
                             fetch_pdf=not args.no_fetch, on_each=_tick)
        except intake.IntakeError as e:
            print(e, file=sys.stderr); sys.exit(1)
        _report_refs(r)
        if not r["pmids"]:
            print("\n没有可入库的文献。", file=sys.stderr)
            sys.exit(1)
        library_page.render(cfg, db_path, idx_path, port=_port(),
                            token=_token(db_path.parent))
        print(f"\n✓ 新增 {r['added']} 篇"
              + (f"，更新 {r['updated']} 篇（原本就在库里，笔记与评级保留）"
                 if r["updated"] else ""))
        if r["missing"]:
            print(f"    PubMed 没有这些 PMID：{'、'.join(r['missing'])}")
        if not args.no_fetch:
            print(f"    顺带抓到 {r['pdf_fetched']} 篇 OA 全文")
        print(f"  收藏库页面：{idx_path}")
        return

    # ── 库内引文网络 ──
    if args.command == "citations":
        from littrack import citations, library, library_page
        out_dir = db_path.parent
        if args.catchup is not None and _catchup_skip(out_dir, "citations", args.catchup):
            print(f"[catchup] 本周期已刷新过引文网络，跳过")
            return
        arts = library.all_articles(db_path)
        if not arts:
            print("收藏库是空的，先用 add 存几篇进来：\n"
                  f"  python3 cli.py add --config {cfg.path} --pmid 42482656",
                  file=sys.stderr)
            sys.exit(1)
        todo = len(library.citation_targets(db_path, force=args.force))
        print(f"库内 {len(arts)} 篇，本次需抓 {todo} 篇"
              + ("" if args.force else f"（已跳过 {len(arts) - todo} 篇抓过的）"))
        if not citations.has_key():
            # 匿名请求走共享池，几百篇能跑上小时级，值得提前说清楚
            print("  未设置 SEMANTIC_SCHOLAR_API_KEY，走匿名共享池：限速严格、耗时较长。\n"
                  "  免费申请后填进 .env 会快很多：https://www.semanticscholar.org/product/api")
        print("  可随时 Ctrl+C 中断，已抓到的不会丢，下次接着跑\n")

        def _tick(done, total, pmid, status, linked):
            tag = {"ok": f"{linked} 篇在库内", "missing": "S2 未收录",
                   "error": "失败（下次续跑重试）"}[status]
            print(f"  [{done}/{total}] {pmid} … {tag}")

        r = citations.refresh(db_path, force=args.force, on_progress=_tick)
        library_page.render(cfg, db_path, idx_path, port=_port(),
                            token=_token(db_path.parent))
        print(f"\n✓ 完成：{r['cited']} 篇有库内被引记录")
        if r["missing"]:
            print(f"  {r['missing']} 篇 S2 未收录（多为新上线或非常规文献），已记为抓过")
        if r["failed"]:
            print(f"  ⚠️ {r['failed']} 篇抓取失败，重跑本命令会自动重试这些")
        print(f"  全球被引数已刷新 {r['counts']} 篇")
        print(f"  收藏库页面：{idx_path}")
        if args.catchup is not None:
            _mark_ran(out_dir, "citations")
        return

    if args.command == "library":
        from littrack import library, library_page
        if args.projects:
            ps = library.list_projects(db_path)
            if not ps:
                print("（暂无项目）")
            for p in ps:
                flag = "（已归档）" if p["archived"] else ""
                print(f"  {p['name']}{flag}：{p['count']} 篇")
            return
        library_page.render(cfg, db_path, idx_path, port=_port(),
                            token=_token(db_path.parent))
        n = len(library.all_articles(db_path))
        print(f"✓ 收藏库页面已生成：{idx_path}（{n} 篇）")
        return

    if args.command == "project":
        from littrack import library, library_page

        def _refresh():
            """项目变动后同步刷新收藏库页面与 Obsidian 项目索引。

            数据库此时已经改完，页面/Obsidian 只是派生产物：写不动就警告，
            别让整条命令以 traceback 收场、让人以为项目操作没生效。
            """
            try:
                library_page.render(cfg, db_path, idx_path, port=_port(),
                            token=_token(db_path.parent))
            except OSError as e:
                print(f"⚠️ 项目已更新，但收藏库页面刷新失败：{e}\n"
                      f"   可稍后重试：python3 cli.py library --config {cfg.path}",
                      file=sys.stderr)
            root = _vault()
            if root and root.exists():
                from littrack import obsidian
                try:
                    obsidian.rebuild_project_notes(cfg, db_path, root)
                except OSError as e:
                    print(f"⚠️ 项目已更新，但 Obsidian 同步失败：{e}\n"
                          f"   检查 OBSIDIAN_DIR={root} 是否可写，再跑：\n"
                          f"   python3 cli.py obsidian --config {cfg.path}",
                          file=sys.stderr)

        if args.list or not args.name:
            ps = library.list_projects(db_path)
            if not ps:
                print("（暂无项目）\n"
                      "  新建方式：在收藏库网页勾选文献点「加入项目」，\n"
                      "  或：python3 cli.py project --config <配置> --name <项目名> --add --pmid 123")
                return
            for p in ps:
                flag = "（已归档）" if p["archived"] else ""
                print(f"  {p['name']}{flag}：{p['count']} 篇")
            return

        name = args.name
        try:
            if args.add:
                if not args.pmid:
                    ap.error("--add 需要配合 --pmid 指定文献")
                r = library.add_to_project(db_path, name, args.pmid)
                msg = f"已加入项目「{name}」{r['added']} 篇"
                if r["missing"]:
                    msg += f"；以下 PMID 不在收藏库中，已跳过：{', '.join(r['missing'])}"
                print(msg)
            elif args.remove:
                if not args.pmid:
                    ap.error("--remove 需要配合 --pmid 指定文献")
                print(f"已从项目「{name}」移出 {library.remove_from_project(db_path, name, args.pmid)} 篇")
            elif args.rename:
                if not library.rename_project(db_path, name, args.rename):
                    print(f"项目「{name}」不存在", file=sys.stderr); sys.exit(1)
                print(f"项目已改名：{name} → {args.rename}")
            elif args.delete:
                if not library.delete_project(db_path, name):
                    print(f"项目「{name}」不存在", file=sys.stderr); sys.exit(1)
                print(f"已删除项目「{name}」（文献仍保留在收藏库中）")
            elif args.archive or args.unarchive:
                want = bool(args.archive)
                if not library.set_archived(db_path, name, want):
                    print(f"项目「{name}」不存在", file=sys.stderr); sys.exit(1)
                print(f"项目「{name}」已{'归档' if want else '取消归档'}")
            else:
                ap.error("请指定操作：--add / --remove / --rename / --delete / --archive / --unarchive")
        except ValueError as e:
            print(f"错误：{e}", file=sys.stderr); sys.exit(1)
        _refresh()
        return

    # ── 全文 PDF ──
    if args.command == "pdf":
        from littrack import library, library_page, pdfs
        pdf_dir = pdfs.dir_for(db_path)
        arts = library.all_articles(db_path)
        known = {a["pmid"] for a in arts}

        def _repage():
            library_page.render(cfg, db_path, idx_path, port=_port(),
                                token=_token(db_path.parent))

        try:
            if args.status or not (args.fetch or args.imp or args.add or args.delete):
                got = pdfs.have(pdf_dir)
                # 目录里可能有已经不在库中的遗留文件，分开数，免得算出「有 5/3 篇」
                live = got & known
                print(f"已有全文 {len(live)} / {len(arts)} 篇，缺 {len(arts)-len(live)} 篇")
                print(f"  存放目录：{pdf_dir}")
                if got - known:
                    print(f"  另有 {len(got-known)} 个 PDF 的 PMID 已不在库中（多半是删过文献）")
                return
            if args.imp:
                r = pdfs.import_dir(args.imp, pdf_dir, pdfs.build_index(arts),
                                    move=args.move, dry_run=args.dry_run)
                head = "将认领" if args.dry_run else "已认领"
                print(f"{head} {len(r['imported'])} 个 PDF（扫描 {r['scanned']} 个）")
                for it in r["imported"]:
                    print(f"  ✓ {it['pmid']}  ←  {Path(it['file']).name}（{it['how']}）")
                for it in r["failed"]:
                    print(f"  ✗ {Path(it['file']).name}：{it['error']}", file=sys.stderr)
                if r["unmatched"]:
                    print(f"\n  没认出来的 {len(r['unmatched'])} 个（源文件没动）：")
                    for name in r["unmatched"]:
                        print(f"    ? {name}")
                    try:
                        import fitz  # noqa: F401
                    except ImportError:
                        print("\n  ⚠️ 没装 PyMuPDF，只能靠文件名里的 PMID 认领。"
                              "装上可从正文里读 DOI 与标题，认领率高得多：\n"
                              "     pip install PyMuPDF")
            elif args.add:
                if not args.pmid or len(args.pmid) != 1 or not args.file:
                    ap.error("pdf --add 需要 --pmid <一个PMID> --file <PDF路径>")
                pmid = str(args.pmid[0])
                if pmid not in known:
                    print(f"PMID {pmid} 不在收藏库里，请先 add 再挂 PDF", file=sys.stderr)
                    sys.exit(1)
                src = Path(args.file).expanduser()
                pdfs.save(pdf_dir, pmid, src.read_bytes(), max_bytes=pdfs.IMPORT_MAX_BYTES)
                print(f"✓ 已挂上全文：{pmid} ← {src.name}")
            elif args.delete:
                if not args.pmid:
                    ap.error("pdf --delete 需要 --pmid")
                n = sum(1 for p in args.pmid if pdfs.trash(pdf_dir, str(p)))
                print(f"已把 {n} 篇的 PDF 挪进 {pdf_dir/'_trash'}（文献本身保留）")
            else:                                    # --fetch
                _require_key()
                want = [a for a in arts if not args.pmid or a["pmid"] in {str(p) for p in args.pmid}]
                if not os.environ.get("UNPAYWALL_EMAIL"):
                    print("提示：没设 UNPAYWALL_EMAIL，本次只走 PMC 这一条路。\n"
                          "      在 .env 里加 UNPAYWALL_EMAIL=你的邮箱 可多一条 OA 直链来源。")
                r = pdfs.fetch_many(want, pdf_dir)
                print(f"✓ OA 抓取：成功 {r['fetched']} 篇，未取到 {r['failed']} 篇，"
                      f"已有跳过 {r['skipped']} 篇（共 {r['requested']} 篇）")
                if r["failed"]:
                    print("  订阅刊（Nature / NEJM / Lancet 等）通常没有 OA 版本，"
                          "这些需要自行下载后拖进收藏库页面，或用 pdf --import")
        except (pdfs.PdfError, OSError) as e:
            print(f"错误：{e}", file=sys.stderr); sys.exit(1)
        if not args.dry_run:
            _repage()
        return

    if args.command == "obsidian":
        from littrack import obsidian
        root = _vault()
        if not root:
            print("未设置 Obsidian 目录。请在 .env 里加：\n"
                  "  OBSIDIAN_DIR=/你的/vault/某个文件夹", file=sys.stderr)
            sys.exit(1)
        from littrack import library
        pmids = args.pmid or ([a["pmid"] for a in library.all_articles(db_path)]
                              if args.all else [])
        r = obsidian.export(cfg, db_path, root, pmids)
        print(f"✓ Obsidian 已更新：{root}")
        print(f"  新增 {r['written']} 篇 · 跳过 {r['skipped']} 篇（已存在）"
              f" · 归位 {r['moved']} 篇 · 现有笔记 {r['total']} 篇")
        print(f"  总录：{root / obsidian.INDEX_NAME}")
        if not pmids:
            print("  （未指定 --pmid / --all，本次只刷新已有笔记并重建总录与项目索引）")
        return

    if args.command == "serve":
        _serve(cfg, db_path, idx_path)
        return

    # ── 联网校验 ──
    if args.command == "validate":
        _require_key()
        from littrack import validate as vd
        print("核对期刊名（PubMed [ta] 检索，统计 2024 年以来收录量）…")
        findings = vd.check_journals(cfg)
        if not args.journals_only:
            print("\n核对关键词命中量…")
            findings += vd.check_keywords(cfg)
        print()
        err, warn = vd.report(findings)
        if err:
            print("\n有错误项，建议修正后再跑检索——否则那部分会静默搜不到东西。")
            sys.exit(1)
        return

    if args.command == "check":
        print(f"✓ 配置校验通过：{cfg.path}")
        print(f"  项目名：{cfg.project_name}")
        print(f"  期刊：全量收录 {len(cfg.full_inclusion_journals)} 本 / "
              f"关键词筛选 {len(cfg.keyword_filtered_journals)} 本")
        print(f"  板块（顺序即去重优先级）：")
        for s in cfg.sections:
            extra = f"，AND 触发词 {len(s.trigger_keywords)} 个" if s.matcher == "cross_product" else ""
            print(f"    · {s.name}  [{s.matcher} / {s.scope}]{extra}")
            print(f"        子板块：{' > '.join(s.subsection_names)}")
        return

    if args.command == "weekly":
        out_dir = BASE / cfg.output_dir
        if args.catchup is not None and _catchup_skip(out_dir, "weekly", args.catchup):
            print(f"[catchup] 本周期的周报已生成过，跳过")
            return
        run_day = _date(args.date, "--date") if args.date else datetime.date.today()
        end = run_day - datetime.timedelta(days=1)
        start = end - datetime.timedelta(days=6)
        _run(cfg, start.isoformat(), end.isoformat(), "weekly")
        if args.catchup is not None:
            _mark_ran(out_dir, "weekly")
    else:
        if not args.start or not args.end:
            ap.error("history 需要 --from 与 --to，例：--from 2025-01-01 --to 2025-12-31")
        start, end = _date(args.start, "--from"), _date(args.end, "--to")
        if start > end:
            ap.error(f"--from（{start}）不能晚于 --to（{end}），两者写反了？")
        _run(cfg, start.isoformat(), end.isoformat(), "history")


if __name__ == "__main__":
    try:
        main()
    except entrez.NetworkError as e:
        # 已在 entrez 里重试过 8 次，走到这里基本可以断定是网络/NCBI 侧的问题
        print(f"\n连不上 NCBI（已重试多次仍失败）：{e}\n"
              f"  依次排查：\n"
              f"    1. 本机网络是否正常（curl -I https://eutils.ncbi.nlm.nih.gov/ ）\n"
              f"    2. 是否需要代理，或代理是否拦了该域名\n"
              f"    3. NCBI 偶发故障：稍等几分钟重跑同一条命令即可\n"
              f"  仍不行时加 -v 看详细日志。", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        print("\n已中断", file=sys.stderr)
        sys.exit(130)
