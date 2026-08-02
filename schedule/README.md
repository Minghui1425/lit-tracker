# 定时任务

两个任务，按需装：

| 任务 | 模板 | 默认时间 | 干什么 |
|---|---|---|---|
| 周报 | `com.lit-tracker.weekly.plist` | 每周二 20:00 | 抓过去 7 天，出 HTML 周报 |
| 引文网络 | `com.lit-tracker.citations.plist` | 每周三 21:00 | 刷新库内引用关系与全球被引数 |

引文任务排在周报之后：这样每周新收藏的文献到那时已经进库，一次补齐。
它只对收藏库有意义，库还空着就先别装。

配置调好、`history` 试过效果之后，再挂定时任务。

---

## macOS

**1. 先建日志目录**——这一步跳过的话 launchd 会直接启动失败（退出码 78），
因为它打不开重定向的日志文件：

```bash
mkdir -p /path/to/lit-tracker/output/logs
```

**2. 改模板**：打开要用的模板（`com.lit-tracker.weekly.plist` / `.citations.plist`），
把里面所有 `/path/to/...` 换成实际路径。

```bash
which python3   # 查 Python 路径
pwd             # 在项目目录下执行，查项目路径
```

**3. 安装并验证**：

```bash
cp schedule/com.lit-tracker.weekly.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.lit-tracker.weekly.plist
launchctl list | grep lit-tracker
```

要引文任务的话，同样再来一遍（两个任务互不影响，可以只装一个）：

```bash
cp schedule/com.lit-tracker.citations.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.lit-tracker.citations.plist
```

最后一条命令输出的**第 2 列是上次退出码**：`0` 正常；非 0（比如 `78`）表示启动失败，
去看 `output/logs/weekly.err`（引文任务看 `citations.err`）。

**卸载**：

```bash
launchctl unload ~/Library/LaunchAgents/com.lit-tracker.weekly.plist
rm ~/Library/LaunchAgents/com.lit-tracker.weekly.plist
```

（引文任务把上面两条里的 `weekly` 换成 `citations`。）

---

## Windows

用「任务计划程序」：

1. `Win + S` 搜索「任务计划程序」并打开
2. 右侧点 **创建基本任务**，名称填 `lit-tracker-weekly`
3. 触发器选 **每周 · 星期二 · 20:00**
4. 操作选 **启动程序**：
   - 程序：Python 完整路径（`where python` 查）
   - 参数：`cli.py weekly --config configs\我的配置.yaml --catchup 2`
   - 起始于：项目所在目录
5. 在任务属性的「条件」页勾上 **只有在计算机使用交流电源时才启动**（可选），
   在「设置」页勾上 **如果错过计划开始时间，则尽快启动任务**——这一项等价于 macOS 的
   `RunAtLoad` + `--catchup`，是关机错过后能补上的关键

引文网络任务同理，把参数换成
`cli.py citations --config configs\我的配置.yaml --catchup 3`，触发器设为每周三 21:00。

---

## 说明

- **错过的那一期会自动补上**：睡眠中错过的，launchd 唤醒后就跑；关机错过的，靠
  `RunAtLoad` 在下次登录时补。
- `RunAtLoad` 的真实语义是「每次加载都跑」而**不是**「错过才跑」，单用它会天天重跑、
  按当天重新回溯 7 天，产出一堆窗口互相重叠的报告。所以模板里给命令加了 `--catchup`：
  它按「最近一个计划运行日」划分周期，本周期已经成功跑过就安静跳过。
  **`--catchup` 后面的数字必须和 plist 里 `Weekday` 一致**（0=周日, 1=周一 …），
  改了运行日两处都要改。
- 运行记录写在 `output/.last_run_weekly` / `.last_run_citations`，删掉它们等于强制重跑。
  手动跑（不加 `--catchup`）不写记录，也就不会顶掉下一次定时任务。
- 手动补跑某一期：`python3 cli.py weekly --config <配置> --date 2026-07-28`
  （以该日为运行日，往前抓 7 天；填原定的运行日即可拿到与那期一致的窗口）。
- 报告写到 `output/`，同名文件会被覆盖，重复跑同一期不会产生多份。
