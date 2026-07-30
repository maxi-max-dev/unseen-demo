# 公网静态站巡检（sweep / walk）

`tools/acceptance.mjs` 的 `sweep` 和 `walk` 都要一个 JSON 参数，仓库里原来没有现成的清单，
2026-07-30（批次 K 第 4 件）补上这两份。

## 先起一个静态服务器

页面之间是相对路径，而且要 fetch OSS 上的 `space.json`（OSS 的 CORS 是 `*`，本机来源没问题）。
`file://` 起不来这套，所以先在仓库根目录起一个静态服务器：

```bash
cd ~/code/spatial-memory && .venv/bin/python -m http.server 8791 --bind 127.0.0.1
```

端口写死在两份 JSON 里，换端口要一起改。

## 巡检 13 个公开页面

```bash
cd ~/code/spatial-memory && node tools/acceptance.mjs sweep tools/sweep-public.json
```

覆盖 `deploy/public-files.txt` 里全部 13 个 HTML。每页报四件事：标题、横向溢出、
控制台报错、4xx/5xx 死链。截图落在 `tools/shots-k/`。
**全绿的判据**：每一行 `报错=[] 死链=[] 溢出=false`。

## 主办入口死循环回归

```bash
cd ~/code/spatial-memory && node tools/acceptance.mjs walk tools/walk-host-loop.json
```

走一遍「产品门户 → 主办方 Studio → 输 1111 → 工作台 → 再点 Studio」。
最后一步必须**停在登录页**并给出一句说明，不能又被弹回 `workspace.html`。
这条回归防的是 P0-1 里那个把人夹在两页之间的循环。

## 收工

```bash
node tools/acceptance.mjs kill
```

关掉验收用的无头 Chrome（独立端口 9361，不碰你平时用的浏览器）。
