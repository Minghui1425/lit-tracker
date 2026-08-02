"""本地服务的鉴权边界：token、Host 白名单、路径限制。

真的把 `cli.py serve` 起起来打——这几条是安全性质的约束，
用假 handler 测等于测了个寂寞。
"""
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

from conftest import BASE, EXAMPLE, article
from littrack import library

_DIRECT_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _req(url, *, host=None, token=None, data=None, method="GET"):
    r = urllib.request.Request(url, method=method,
                               data=json.dumps(data).encode() if data is not None else None)
    if data is not None:
        r.add_header("Content-Type", "application/json")
    if host:
        # 只改 Host 头，不改实际连接的地址——正是 DNS rebinding 时浏览器的样子
        r.add_header("Host", host)
    if token:
        r.add_header("X-LitTrack-Token", token)
    try:
        # 本机/CI 可能设置全局 HTTP_PROXY；安全边界测试必须直连被测服务。
        with _DIRECT_OPENER.open(r, timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


@pytest.fixture
def server(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    cfg_text = EXAMPLE.read_text(encoding="utf-8").replace(
        "output_dir: output", f"output_dir: {out}")
    cfg_file = tmp_path / "cfg.yaml"
    cfg_file.write_text(cfg_text, encoding="utf-8")

    db = out / "library.db"
    library.upsert(db, [article(section="心衰进展", subsection="其他")])

    port = _free_port()
    env = {"PATH": "/usr/bin:/bin", "LITTRACK_PORT": str(port), "HOME": str(tmp_path)}
    proc = subprocess.Popen(
        [sys.executable, str(BASE / "cli.py"), "serve", "--config", str(cfg_file)],
        cwd=str(BASE), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    base_url = f"http://127.0.0.1:{port}"
    for _ in range(50):                     # 等它起来，最多 5 秒
        try:
            _req(base_url + "/")
            break
        except Exception:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("serve 没能在 5 秒内起来：\n" + (proc.stdout.read() if proc.stdout else ""))
    token = (out / ".token").read_text(encoding="utf-8").strip()
    yield base_url, token, db, port
    proc.terminate()
    proc.wait(timeout=10)


def test_get_serves_the_page(server):
    base, *_ = server
    status, body = _req(base + "/")
    assert status == 200 and "收藏库" in body


def test_get_is_not_a_file_server(server):
    base, *_ = server
    assert _req(base + "/cli.py")[0] == 404
    assert _req(base + "/../cli.py")[0] == 404


def test_write_requires_token(server):
    base, token, db, _ = server
    payload = {"pmid": "1", "rating": "⭐"}
    assert _req(base + "/rating", data=payload, method="POST")[0] == 403
    assert _req(base + "/rating", data=payload, token="wrong", method="POST")[0] == 403
    assert library.all_articles(db)[0]["rating"] == ""      # 没被改动

    status, _ = _req(base + "/rating", data=payload, token=token, method="POST")
    assert status == 200
    assert library.all_articles(db)[0]["rating"] == "⭐"


def test_foreign_host_is_rejected(server):
    """DNS rebinding：攻击者的域名解析到 127.0.0.1 后，Host 头仍是他的域名。"""
    base, token, db, port = server
    evil = f"attacker.example:{port}"
    assert _req(base + "/", host=evil)[0] == 403           # 首页里有 token，不能给
    assert _req(base + "/rating", host=evil, token=token,
                data={"pmid": "1", "rating": "🚩"}, method="POST")[0] == 403
    assert library.all_articles(db)[0]["rating"] == ""

    # localhost 是白名单里的，应当放行
    assert _req(base + "/", host=f"localhost:{port}")[0] == 200


def test_unknown_route_404(server):
    base, token, *_ = server
    assert _req(base + "/wipe", data={}, token=token, method="POST")[0] == 404
