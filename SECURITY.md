# 安全说明

## 报告安全问题

请使用 GitHub 仓库的 **Security → Report a vulnerability** 私下提交，附上复现步骤、
影响范围和你所用的版本（commit 号）。如果仓库暂未显示这个入口，请不要在公开 issue
披露漏洞细节；可以只开一个不含技术细节的 issue，请维护者启用私密报告渠道。
收到后会尽快回复；修复前请先不要公开细节。

这是一个个人小工具，没有 SLA，也没有赏金。

## 本地服务的安全模型

`python3 cli.py serve` 会起一个本地 HTTP 服务，为收藏库页面提供评级、笔记、项目标签、
删除和 Obsidian 导出接口。它的边界是：

- **只监听 `127.0.0.1`**，不绑 `0.0.0.0`，同网段的其它机器连不上。
- **所有写接口都要求凭据**：请求头 `X-LitTrack-Token` 必须与 `output/.token` 一致
  （`hmac.compare_digest` 比对）。没有这道门，只要你开着服务，任何网页都能在后台向
  `127.0.0.1` 发跨源写请求——浏览器只阻止读取响应，不阻止请求本身生效。
- **Host 白名单**：只接受 `127.0.0.1:<端口>` 与 `localhost:<端口>`，用于挡 DNS
  rebinding（攻击者把自己的域名解析到 127.0.0.1，让其页面变成「同源」进而读走 token）。
- **CORS 白名单**：只对本机两个 origin 与 `null`（`file://` 打开的页面）回显
  `Access-Control-Allow-Origin`，不再使用通配 `*`。
- **GET 只提供收藏库页面本身**（`/` 与 `/library.html`），不是静态文件服务器，
  不会顺着路径读到仓库里的其它文件。

## 凭据文件

- `output/.token` 在首次运行时生成，权限 `0600`，位于已被 `.gitignore` 排除的 `output/`
  目录内。
- 它以明文嵌在生成的 `library.html` 里——**这个 HTML 等同于凭据，不要分享给别人**。
  需要给同事看结果时，请用报告页（`weekly_*.html` / `history_*.html`），那里不含 token。
- 怀疑泄露时：删掉 `output/.token`，重跑 `python3 cli.py library --config <配置>`
  重新生成页面即可。旧页面会因凭据不匹配而失效。

## 你的密钥

`NCBI_API_KEY`、`DEEPL_API_KEY` 只存在于 `.env`（已被 `.gitignore` 排除）。
日志里的 `api_key=` / `email=` 会被自动打码后再输出，异常信息也走同一条脱敏路径。
