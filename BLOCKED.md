# BLOCKED

> 本仓库同时有两个 agent 在干活。以下是 **agent A（theme.css 与 portal/join/show/pov 四页统一皮）** 的部分。
> agent B（归档任务）如需登记，请追加自己的标题段，不要覆盖本段。

## agent A / 与任务书对不上的地方

## 1. 【宋体】基线对不上：任务书说 11，实测 10（2026-07-28）

任务书原文口径：`grep -c "Songti\|STSong\|Kaiti\|STKaiti\|Noto Serif" web/show.html web/join.html` 合计应为 11。

实测输出：

```
$ grep -c "Songti\|STSong\|Kaiti\|STKaiti\|Noto Serif" web/show.html web/join.html
web/show.html:1
web/join.html:9
合计 = 10
```

按出现次数（`grep -o | wc -l`）是 16 次，落在 10 行里。逐行清单：

```
web/show.html:24   .hero h2  "Songti SC","STSong",serif
web/join.html:71   .names    "Songti SC","STSong",serif
web/join.html:77   （副题）   "Songti SC","STSong",serif
web/join.html:86   .proof b  "Songti SC",serif
web/join.html:131  .head-names "Songti SC","STSong",serif
web/join.html:221  .card.wish .card-title "Kaiti SC","STKaiti","Songti SC",serif
web/join.html:241  .bounty   "Songti SC",serif
web/join.html:265  .wish-quote "Songti SC",serif
web/join.html:295  .stat b   "Songti SC",serif
web/join.html:376  .res-sum b "Songti SC",serif
```

无论基线是 10 还是 11，本项验收目标都是 **0**，删干净的动作完全一样，
所以这条差异**不影响施工**，按任务书「只做不受影响的部分」继续做，不停工。
差 1 的最可能原因：任务书成稿时的口径把 `grep -c` 的「行数」和「次数」混了，或量的是更早一版文件。
另两条基线（色数 106、portal 体检 errs 空）实测完全吻合，见 PROGRESS.md。

## 2. 任务书说「join.html 第 432 行那条 link 塞在 body 中间」——实测不在 body 里

```
$ grep -n "<link" web/join.html
39:<link rel="stylesheet" href="../app/theme.css">
432:<link rel="stylesheet" href="../app/product-ui.css">
$ sed -n '431,434p' web/join.html
</style>
<link rel="stylesheet" href="../app/product-ui.css">
</head>
<body>
```

第 432 行在 `</head>`（433 行）之前，已经在 head 里。四页全部 `<link>` 都在 head 内，
没有一条在 body。所以「挪回 head」这个动作**没有对象**，不动它就是正确结果。
（同样情形：show.html:198、pov.html:69 也都在各自 `</head>` 之前。）

## 3. 越界不碰、只记录的东西

- `viewer/walk.html`、`app/scene.html`、`app/create.html`、`app/invite.html`、`roadshow.html`、
  `index.html`、`workspace.html` 也有大量硬编码色和旧 token 引用，**不在白名单里，一律没动**。
  它们靠 `app/theme.css` 的旧 12 个别名吃色，本次已把别名全部指向新值，所以它们跟着换皮但没被改文件。
- `web/join.html` 里那张占位「通缉令」海报是 `data:image/svg+xml` 的**外部 SVG 文档**，
  CSS 变量跨不进 data URI，`fill="var(--u-ink)"` 在里面不生效。
  处理办法：把它的 7 个杂色改成规格色板里已有的 4 个字面量（ink / ink-2 / gold / ink-3），
  不是「收敛失败」，是 data URI 的硬限制。三处 `<meta name="theme-color">` 同理，必须字面量。
- `tools/acceptance.mjs`、`DESIGN-UNSEEN.md` 一个字没改。

## 4. 顺手看见但没动手的 bug（按任务书要求只登记）

- `portal.html:842 / 949` 的 `data-local-path="/server/host.html..."` 指向另一个 agent 正在归档的
  本机页。本次已按任务书把它改成云版路径（见 PROGRESS.md 任务 2），但 `roadshow.html`、
  `index.html` 里可能还有同类指向，不在白名单，没查没动。
- `web/join.html` 有 `tour.js.before-*.bak` 系列同源代码残留在仓库根，属于清理范畴，不是本次的活。

## 5. 施工中新发现、但按界限没动手的三件

### 5-1. join 上传要 4 次点击，不是 ≤3（抽查点未达标，不是我能单方面改的）
实测步数和每一步已写进 PROGRESS.md 的「抽查点」一节。差的那一次点击有两条去法
（删开场屏 / 选完照片自动上传），两条都会动产品语义：前者删掉这一页唯一解释
「照片会回到它当时朝着的方向」的地方，后者让宾客选错照片没有撤回机会。
让步顺序里「动线不能坏」排第一，所以我只测不改，摆给领导定。

### 5-2. `archive/server/host.html` 会丢 AI 状态色（影响极小，登记备案）
`--u-ai-*` 这批 token 原来定义在 `app/product-ui.css` 里，本次搬进了 `app/theme.css`
（原因见 PROGRESS.md 判断 2：product-ui.css 排在 theme.css 之后，同名 token 会把 theme 的压掉）。
全仓库引用 product-ui.css 的 8 个页面里，7 个都同时引了 theme.css，只有
`archive/server/host.html` 只引了 product-ui.css 没引 theme.css，它的 AI 卡片描边/小圆点
会拿不到颜色。这一页已经被 agent B 归档退役、不在发布清单里，所以我没为它加回退值
（加回退值等于把颜色又写回 product-ui.css，正是这次要消灭的那件事）。
真要救，一行：给那页补一条 `<link rel="stylesheet" href="../../app/theme.css">`，但它在我界限外。

### 5-3. 四页的 rgba() 阴影/发光没有全部 token 化
硬编码 hex 已经清零，但一次性用的 `rgba()`（比如某个 `:active` 态的按压阴影）还有少量
留在页内，值都取自规格色板的低透明形态。判断依据：复用 ≥2 次的都提成了 token
（`--u-shadow*` / `--u-glass*` / `--u-scrim*` / `--u-wash-*` / `--u-on-dark*` / `--u-glow-gold`），
只用 1 次的留在原处，硬要全提会造出一堆只有一个消费者的 token，反而更难维护。
CSS 没法对一个 hex token 直接调透明度（`color-mix` 能做，但那是新语法，
离线演示要跑在现场那台机的浏览器上，我不敢在验收前引入）。

---

# agent B（归档 / 主办动线）

## B-1. 【死链】验收与「walk.html 只许改第 744 行」直接打架 —— 未解，按界限执行

界限原文：「viewer/walk.html 特批：只许改它第 744 行那处指向 `server/join.html` 的链接，别的一行不许动。」
验收 3 要求【死链】命令无输出。但 walk.html 里有**两处**命中该命令的模式，任务书只点了一处：

```
$ grep -n "server/join\|server/upload" viewer/walk.html
583:    var backHref = backTarget("../server/upload.html");
744:    var localBack = "../server/join.html?space=" + encodeURIComponent(sid);   ← 已改（唯一获授权的一处）
```

583 行在 `bootCompose()` 里，是 compose 模式（`?compose=<manifestUrl>`，由 server/compose_server.py 驱动）
的返回按钮落点。server/upload.html 属于本次退役的本机页，搬进 archive/ 后这个返回按钮就是死链。

**我没有改它**：改它违反「别的一行不许动」（任务书定义为失败），不改只是某条验收不达标（任务书允许如实报告）。
让步顺序里「动线不能坏」排第一，但 compose 模式属于已整体退役的断网本机线，实际动线影响接近零。

下一批只要一行：
```
- 583:    var backHref = backTarget("../server/upload.html");
+ 583:    var backHref = backTarget("../web/join.html");
```
（或直接去掉 backHref，让 backTarget 走它自己的兜底。）

## B-2. 归档后仍指向已退役页、但在我界限之外的文件（我一个都没动）

```
$ grep -n "server/host\|server/join\|viewer/journey\|viewer/index\|viewer/online" app/scenes.js app/cloud.js tour.js tools/pack.py
app/scenes.js:27    story:  PREFIX + "viewer/journey.html"          ← 死链（viewer/journey.html 已归档）
app/scenes.js:31    studio: PREFIX + (LOCAL_ORIGIN ? "server/host.html?space=s4" : "web/studio-login.html")  ← 本机分支死链
app/cloud.js:3      注释里提到 server/host.html（仅注释，无功能影响）
tour.js:6,7         注释里提到 viewer/index.html、viewer/online.html（仅注释）
tools/pack.py:6,17  文档字符串里的示例命令引用 viewer/index.html（工具已随离线包一起退役）
```

其中 **app/scenes.js 那两条是真死链**，且是内置空间 s4 的数据源，属于主办动线。
我的 workspace.html / app/scene.html 已在**消费端**绕开 `s.links.studio`（不再读它，直接指 web/studio-login.html），
所以这两页点不出死链；但任何其它读 `s.links.story` 的页面仍会中招。app/scenes.js 不在我的白名单里，没动。

建议下一批：`viewer/journey.html` 已进 archive/，`story` 这个入口应整条去掉；
`studio` 那行去掉 LOCAL_ORIGIN 分叉，恒等于 `web/studio-login.html`。

## B-3. 后端 Python 仍会去读已搬走的 HTML（按「后端 Python 全部保留不动」未处理）

```
$ grep -rn "host.html\|join.html\|upload.html\|report.html" server/*.py | head
server/compose_server.py, server/space.py, server/verify.py 中有对这几页的路径引用
```
板子写明「后端 Python 全部保留不动」，且这整条本机线已退役，所以我一行没改。
如果下一批还想跑本机后端，需要同步把这些路径指到 archive/ 或一并退役。

## B-4. 任务 2 的前提「两条 link 塞在 body 中间」与实测不符

任务书：「roadshow.html 第 159 行、web/studio-login.html 第 291 行那两条塞在 body 中间的挪回去」。
实测两条都**已经在 `<head>` 里**（紧跟在页内 `</style>` 之后、`</head>` 之前）：

```
$ grep -n "<head>\|</head>\|<body\|<link rel=\"stylesheet\"\|<style>\|</style>" roadshow.html
3:<head>
9:  <link rel="stylesheet" href="app/theme.css">
10:  <style>
158:  </style>
159:  <link rel="stylesheet" href="app/product-ui.css">
160:</head>
161:<body class="u-body">

$ grep -n "<head>\|</head>\|<body\|<link rel=\"stylesheet\"\|<style>\|</style>" web/studio-login.html
3:<head>
9:<link rel="stylesheet" href="../app/theme.css">
10:<style>
290:</style>
291:<link rel="stylesheet" href="../app/product-ui.css">
292:</head>
293:<body class="u-body">
```

规则「`<link rel="stylesheet">` 只许放 `<head>`」当前**已满足**，无需搬动。
唯一可议之处是**层叠顺序**：product-ui.css 排在页内 `<style>` 之后，会压过本页自己的样式。
把它提到 `<style>` 之前更合理，但那会改变现有渲染结果，属于「改完可能比开工更糟」，
且不是任务书要求的那件事（要求只是「放进 head」）。故不动，登记在此。

## B-5. 第 19 个归档文件从未入库，`git mv` 不可能，rename 数只能到 18

验收 4 要求 `git status --short | grep -c "^R"` ≥19。实测 = 18，差的那一个是 `tour.js.before-40photos.bak`：

```
$ git check-ignore -v tour.js.before-40photos.bak
.gitignore:7:*.bak	tour.js.before-40photos.bak

$ git mv tour.js.before-40photos.bak archive/tour.js.before-40photos.bak
fatal: not under version control, source=tour.js.before-40photos.bak, destination=archive/...
```

`.gitignore` 第 7 行 `*.bak` 把它挡在版本库外（同目录另外两个 .bak 是在这条规则之前入的库，所以是 tracked）。
它从来没有 git 历史，**也就没有历史可保**，rename 记录在物理上就不存在。

处理：用普通 `mv` 搬进 archive/，**不是 rm**，字节数一致（6331 bytes），内容原样在：
```
$ ls -la archive/tour.js.before-40photos.bak
-rw-r--r--@ 1 max staff 6331 Jul 23 23:40 archive/tour.js.before-40photos.bak
```
没有用 `git add -f` 强行入库：那会改变仓库对 `*.bak` 的追踪策略，超出「只许移动」的授权。

所以【archive 里 19 个文件】✅，【18 个 rename】是这条规则下能达到的上限。

## B-6. 「页内不再自定义颜色」我只做到了十六进制这一层

验收口径量的是 `#RRGGBB` 字面量，已从 64 降到 1。但页内还留着 `rgba(...)` 字面量
（阴影、描边、遮罩，如 `rgba(214,124,140,.13)`、`rgba(62,36,48,.82)`）。它们不进计数，
我没有一并换成 token：那是一次大得多的改动，而且多数是品牌色的透明度变体，
硬塞进 token 反而会把「同一个色不同透明度」拆成一堆新 token。登记在此，由下一批决定要不要收。

---

## B-7. 断线续接：新会话独立复核，结果与收官记录一致（2026-07-28）

新开的会话按规则先读 PROGRESS.md，逐条重跑验收命令得到与收官记录完全一致的结果，
未做任何新改动（唯一的写操作是反向验证的哨兵行，加完立刻删除，diff 已核对回到加哨兵前状态）：

- 【清单】178，`grep -c "^archive/"` = 0 ✅
- `find archive -type f | wc -l` = 19，总字节 24,337,308，零空文件 ✅
- 19 个原路径逐个 `[ -e "$f" ]` 检查，全部已不存在（不是复制，是真搬空）✅
- 【死链】仍列出 `viewer/walk.html`（命中行 583 `server/upload.html`），
  `git diff viewer/walk.html` 确认只改了第 744 行一行，其余未动，维持 B-1 的结论 ❌（界限锁死，非漏做）
- `git status --short | grep -c "^R"` = 18，`git log --all -- tour.js.before-40photos.bak`
  和 `git ls-files | grep 40photos` 均为空，重新确认该文件确实从未入库，维持 B-5 的结论 ❌（物理不可能）
- 7 页色数：1（`#FFF3F1`，两处 `<meta theme-color>`，与 `app/theme.css` 的 `--u-bg-1` 值核对一致）✅
- roadshow 宋体：0 ✅
- 7 页 `acceptance.mjs shot` 全部重新截图，全部 `"横向溢出": false`、`"errs": []` ✅
- 反向验证重做一遍：workspace.html 追加 `<!-- SENTINEL #A1B2C3 -->` → 色数 1→2 且新增确实是
  `#A1B2C3` → 删除哨兵 → 还原为 1，`grep -c SENTINEL` = 0，`git diff --stat workspace.html`
  与加哨兵前一致（22 行改动，全部是任务2的换皮内容，无哨兵残留）✅
- 界限复核：本次会话唯一的写操作已完整回滚；接缝一的 6 个文件
  （app/theme.css、app/product-ui.css、portal.html、web/join.html、web/show.html、web/pov.html）
  本会话零写入，只在只读检查里出现过它们目前的改动状态，未曾修改。
- `deploy/public-files.txt` 的 diff 逐行核对：删掉的 11 行精确对应 11 个已归档文件
  （server/host.html、server/join.html、server/qr.js、server/report.html、viewer/album.html、
  viewer/index.html、viewer/journey.html、viewer/machine.html、viewer/online.html、
  viewer/timeline.html、web/doors.html），无关行未动。

结论：收官状态成立，两处未达标（死链残留、rename=18）是结构性限制而非未完成，不再重复施工。

---

# BLOCKED · 批次C（展览页五视图合一）

> 本节是批次C（把 archive/viewer/ 四个旧皮收进 web/show.html 做页内切换视图）的记录，
> 追加在 agent A / agent B 的记录之后，没有动前面任何一个字。

## C-1. 顺手发现：app/contract.md 的云版 photos[] 字段表，和 s4 真实数据对不上（只读，没有动手）

实测拉取 `https://psm-advx-2026.oss-cn-hangzhou.aliyuncs.com/spaces/s4/space.json`，
`photos[]` 里每一条真实字段是：

```
id, src, thumb, nodeId, yaw, pitch, confidence, taskId, uploadedAt, inboxKey, contributor
```

对照 `app/contract.md`「三、一张照片」里云版 `photos[]`/`pending[]` 那张表，列的是：

```
id, src, thumb, nodeId, yaw, confidence, margin, state, reason, contributor, taskId
```

对不上的地方：
- `pitch`：contract.md 只在「本地版 `nodes[].photos[]`」那张表里提到，并写着
  「云版目前不产出这个」——但 s4 真数据的云版 `photos[]` 每条都带 `"pitch": 0`。
- `uploadedAt` / `inboxKey`：两个云版真实存在的字段，契约表里完全没提。
- `margin` / `state` / `reason`：契约表说云版有，但 s4 的 `photos[]`（已选入的 9 张）
  一条都没有这三个字段——实测它们只出现在 `pending[]`（待审核的 6 张）里。

`app/contract.md` 在本次任务的只读清单里，没有改一个字。本次新增的四个视图只用了两边
都对得上的字段（`nodeId`/`yaw`/`contributor`/`thumb`/`src`），这条对不上不影响本次交付，
但下次有人要靠这份契约做小程序，这几个字段的真实情况值得找人核实后回填。

## C-2. timeline 视图第一次截图偶发"最左边那张图片没画出来"，重跑即好（判断为抖动，不是数据/代码问题）

`node tools/acceptance.mjs shot ".../show.html?s=s4&view=timeline" ...` 第一次跑，
最左边第一张宝丽来卡片的图片区域是空白（白框），但同一张截图的 `errs`/`net404` 都是
空数组。直接 `curl` 测这张图的 OSS 地址（`.../thumbs/p1.jpg`）返回 200，29352 字节，
不是死链。原样重跑一遍（不改任何代码/参数），第一张图片就正常显示了。判断是无头
Chrome 截图时机撞上图片刚好没解码完的抖动，不是 URL 错、不是跨域挡、不是数据缺。
已在 PROGRESS.md「任务2①」记录，交付前最终一轮 `final-timeline.png` 是干净的。

## C-3. journey.html 不是「章节卡列表」，是完整的 Pannellum 3D 漫游（判断记录，不是漏做）

抄版式之前打开 `archive/viewer/journey.html` 发现它整页其实是一个 Pannellum 全景
播放器（内嵌了整份 Pannellum 引擎代码 + 婚车路线转场动画），不是一份 flat 的
「章节卡」列表。任务书写死「3D 走进保持独立页」，所以没有照抄整份 3D 漫游逻辑，
只抽取了它「到达标题卡」（`.title-card`/`.tc-chapter`/`.tc-time`）和「结束页章节列表」
（`.ep-row`）这两处非 3D 的版式语言，重新组成本次 show.html 里 flat 的
「章节牌 + 照片格」卡片（`.jr-plaque`/`.jr-grid`）。如果验收人原本期待的是"能像
3D 旅程一样自动往前走"的体验，现在做出来的是静态卡片，不是动态导览——这是一处
解读判断，不是漏做，记在这里备查，理由见 PROGRESS.md 判断记录第 1、2 条。

## C-4. app/product-ui.css 最终没有改动

任务书把它列进可改范围，但实现下来，四个新视图需要的所有颜色都能直接用
`app/theme.css` 现成的 `--u-` token，组件级 CSS 全部写进了 `web/show.html` 自己的
`<style>` 块（这和原文件的分工一致：product-ui.css 只放跨页面共享的小组件，
页面专属版式留在页面自己的 style 里）。没有为了"用满白名单"而找一个不必要的理由去改它。
`git status --short` 里没有它的 diff，只有 `web/show.html`、`PROGRESS.md`、`BLOCKED.md` 三个。

---
---

# BLOCKED · 批次D（压测军团）

> 本节是批次D（当几十上百个真宾客反复走 join→show 动线找 bug）的记录，
> 追加在前面所有记录之后，没有动前面任何一个字。

## D-1. s4（真实线上空间）的贡献者名单里有一条真实测试记录，我读到了但没有权限处理

压测 show.html 的 `machine`/`journey` 等视图时（`tools/stress/shots/S23-w768-machine.png`
等截图可见），发现 s4 的贡献者名单里有一条显示为「公网验收员」的记录——这明显是
历史验收/测试流程里真实上传过的数据，不是我这次造出来的。

`web/show.html` 的 `publicName()` 匿名化黑名单目前是：

```js
var blocked = {"泛音测":1,"泛音测试":1,"延迟测试":1,"你大爷":1,"阿伟测试":1};
var looksLikeQa = /^(FIX|E2E|QA|TMP|SMOKE|TEST)[-_]?/i.test(n) ||
  /(验收测试|回归测试|攻击测试)/.test(n);
```

「公网验收员」不匹配这几个固定词，也不匹配 `looksLikeQa` 的模式（它不是
"验收测试"而是"验收员"），所以原样显示了出来。

**为什么没有动手：**
1. 这是 **s4 上真实存在的数据**（`contributors[]` 里的一条记录），不是代码逻辑
   算出来的东西。要"修"这条，要么改真实的 `space.json`（我对 s4 只读，任务书
   写死"绝不许真实上传任何照片到云端"，修改既有数据同样是写操作，不在我的权限
   和白名单里），要么扩大 `publicName()` 的黑名单/正则去多挡一个词——但这属于
   "又发现一个没挡住的变体就加一条规则"的打地鼠，治标不治本，且是否要为这一个
   具体名字改动展示逻辑，是内容/产品判断，不是我该单方面决定的代码 bug 修复。
2. 界限里 `web/show.html` 虽然可改，但这次改动的对象应该是"规则该怎么定"而不是
   "补一个特例"，值得由能看到 s4 完整数据、了解这条记录来源的人来决定。

登记在此，不算进 BUGS.md 的 bug 列表（那份文件只登记 web/join.html 等四个白名单
页面里我能确认、能负责修的代码问题）。

## D-2. 「toast 短暂盖住背景任务卡按钮一角」判断为不用修，如实登记

详细复现、判断理由、截图路径见 `tools/stress/BUGS.md`「观察到、判断不需要修的一条」。
没有改代码，摆在这里防止被读成"漏报"。

---
---

# BLOCKED · 批次E(主办方自助建空间)

> 本节记录施工中按界限没动手、或需要下一批决定的事,不覆盖前面任何一个字。

## E-1. 全景直传/主办密钥编辑接口在"非回环+无全局口令"场景下仍会被中间件挡在外面,本批次未做(如实登记)

`server/compose_server.py` 的 `protect_space_assets` 中间件对所有 `/api/` 路径
要求 `host_allowed`(回环请求,或携带全局 `X-Unseen-Host-Pin`),`_public_api_request()`
的公开白名单里没有把我新增的 `POST /space/{sid}/host/meta` 和
`DELETE /space/{sid}/node/{node_id}` 纳入例外。也就是说:一个真正不在这台 Mac
上、也没有全局口令的主办方,即使拿着自己空间的主办密钥,请求也会先被这层中间件
挡在外面,拿不到 space.py 里"只认主办密钥"这一层判断的机会。

**为什么没做**:要打开这条路,中间件自己得先验证"这个请求带的
`X-Unseen-Space-Key` 是不是这个 sid 的真密钥"才能放行,这是对安全中间件的改动。
让步顺序里"凭据安全"排第一,我选择保守:本批次的验收条款(改标题/删节点的
401/403,以及完整端到端流程)全部在回环环境下可以完整验证,不依赖打开这条路;
而"真正的远程、非回环主办方"这个场景我在这个沙盒里也没有能力发起一个真正
非回环的请求来验证改动是否正确——与其做一个自己测不了的安全改动,不如如实
登记,留给能实测的下一批。

**下一批的一行思路**:在 `_public_api_request()` 里加一个新分支,匹配
`POST /api/space/s\w+/host/meta` 和 `DELETE /api/space/s\w+/node/[^/]+` 这两个
路径,且请求头 `X-Unseen-Space-Key` 非空时才放行(真正的校验仍然交给 space.py
路由自己的 `_host_key_authorized()`,中间件这层只是不提前拦截)。

## E-2. 主办密钥/全景直传策略只在建空间那一次响应里给出,没有"事后再要一次"的接口

如果主办方在 create.html 第2步没截图、没复制,也没能让 localStorage 存下来就
关了标签页(理论上少见,`saveHostKey()` 是同步执行的,但极端场景比如浏览器隐私
模式整体禁用了 localStorage),这个空间就再也拿不到主办密钥,也没有别的入口能
重新申请一份全景直传策略。

**为什么没做**:任务书对任务1的目标动线只描述了"建空间那一次"的路径,没有要求
"创建完之后还能回来接着传";任务2的三个编辑动作里也没有"重新申请全景上传通道"。
按"别做更多"没有加这个入口。

**下一批的建议**:给 `GET /api/space/{sid}` 的 host 角色响应加一个 `panoUpload`
字段(复用现成的 `pano_upload_policy()`),scene.html 的"主办编辑"卡片可以顺手
加一个"补传全景"的文件选择器。

## E-3. 全景直传前缀不做照片那一套"收件箱代际轮换",故意简化(判断记录,非漏做)

`_ensure_private_inbox_prefix()`/`_normal_retired_inboxes()` 这套"收件箱代际
轮换+过期策略自动失效"的机制是照片直传专用的,全景直传前缀
(`spaces/<sid>/pano-inbox/`)固定不变、没有代际。如果主办密钥泄露被人拿去传
垃圾全景,没有"让旧策略失效"的手段,只能等 48 小时策略自然过期。这套复杂度
是宾客链接被到处转发、旧签名长期留存这个前提逼出来的历史包袱(照片场景才有),
全景直传只有主办方自己在用,现有威胁模型下不成比例,是故意简化,已在 PROGRESS.md
判断记录4说明。

## E-4. 批次E收尾:凭据/一致性/残留清理的最终证据

**s4(线上演示空间)只读不写,md5 前后一致**:
```
$ curl -s https://.../spaces/s4/space.json | md5     # 会话中段第一次核实
46e41c7ab5372ea84d8f38c3562c1605
$ curl -s https://.../spaces/s4/space.json | md5     # 会话收尾再次核实
46e41c7ab5372ea84d8f38c3562c1605                       ← 一致
$ ls -la server/spaces/s4/space.json
-rw-r--r--@ 1 max staff 13168 Jul 26 01:38 space.json   ← 本机文件 mtime 早于本次会话(7/28-29),
                                                            证明本地真值也没被写过
```
本次会话没有任何一条命令以 `s4` 为目标 sid(全部测试都用 `stress*` 前缀),
`git diff`/进程日志里也搜不出一次对它的写操作。

**测试残留已清(本机+云端全清)**:
```
$ .venv/bin/python tools/stress-e/cleanup.py --list
本机现存 0 个 stress* 空间: []

$ for sid in stresse0 stresse1 stresse2 stresse3 stresse4 stresse5; do
    curl -s -o /dev/null -w "$sid -> %{http_code}\n" https://.../spaces/$sid/space.json
  done
stresse0 -> 403
stresse1 -> 403
stresse2 -> 403
stresse3 -> 403
stresse4 -> 403
stresse5 -> 403
```
(403 是私有桶对不存在 key 的标准响应,不是权限错误——同一条 curl 对仍存在的
s4/space.json 返回 200,可以对照。)

`tools/stress-e/cleanup.py` 只清理 `stress` 前缀(硬编码校验挡在最前面,传别的
sid 直接拒绝),和 `server/worker.py --purge-inbox` 的区别是它清理整个空间的
OSS 前缀(含已发布素材),不只是收件箱——压测空间用完就该整个消失,不是长期
运营空间那种"只清收件箱、留着已发布素材"的语义。

**测试后台进程已杀干净**:
```
$ pgrep -fl "compose_server|server.worker"
34484 ... server.worker s900002 --interval 5
92963 ... server.worker s900003 --interval 5
```
这两个是本次会话开工前就已经在跑的路演空间工人(和本批次无关,任务书没让碰,
全程没有被误杀),PID 和会话开始时探测到的完全一致。我自己起的
compose_server.py(本机后端)和历次 `server.worker stresseN` 全部已 kill,
不在上面的列表里。

**git status 改动只落白名单**:
```
$ git status --short
 M app/create.html          ← 白名单
 M app/invite.html          ← 白名单
 M app/scene.html           ← 白名单
 M app/scenes.js            ← 白名单
 M server/compose_server.py ← 白名单(server/ 下的 Python 文件)
 M server/space.py          ← 白名单
 M server/worker.py         ← 白名单
?? tools/stress-e/          ← 白名单(新建,压测产物)
 M BLOCKED.md / PROGRESS.md ← 任务书指定要交的两份(只在末尾追加)
```
`web/join.html` 的改动、`tools/stress/`(注意没有 `-e`)、`PROGRESS.md`/
`BLOCKED.md` 里我这段之前的内容,全部是另一位工兵(压测 join/show/pov/portal
那位)的产物——按界限"另一个工兵正在压测它们,别撞",本次会话没有修改这几个
文件的一个字节,只读引用过 `web/join.html`/`web/show.html`(拿它们既有的直传
模式和展示逻辑当参照,验证我的新代码渲染是否正常),从未写入。
`theme.css`/`acceptance.mjs`/`web/pov.html`/`portal.html` 同理,全程只读或
完全没碰。

## G-1. 微信开发者工具 cli 从未登录过,验收5 的 IDE 冒烟测不了,需要 Max 扫码后人工验

**背景**:批次G(UNSEEN 小程序只读看展壳)任务书验收5要求,若开发者工具装好且 cli 可用,
跑一次 `cli auto-preview` 级别的冒烟;工具没装好或 cli 要扫码登录,就记 BLOCKED,不算
失败。

**实测**:
```
$ ls /Applications | grep -i wechat
wechatwebdevtools.app

$ /Applications/wechatwebdevtools.app/Contents/MacOS/cli -v
(能正常列出全部子命令,说明 App 本体装好了)

$ /Applications/wechatwebdevtools.app/Contents/MacOS/cli islogin
[error] Please ensure that the IDE has been properly installed
✖ #initialize-error: Error: ENOENT: no such file or directory, open
  '/Users/max/Library/Application Support/微信开发者工具/50a7d9210159a32f006158795f893857/Default/.cli'

$ /Applications/wechatwebdevtools.app/Contents/MacOS/cli auto-preview --project /Users/max/code/spatial-memory/miniapp
(同一个 initialize-error)

$ ls -la "/Users/max/Library/Application Support/微信开发者工具/"
只有一个 profile 目录,里面只有 WeappLog,没有 Default/、没有 .cli 标记文件
——这个 profile 目录的 mtime 是本次会话开工的时间点,说明是我这几条 cli 命令
自己触发生成的空壳,不是之前就有登录过的痕迹。
```

**结论**:App 装了,但从来没有经过一次完整的 GUI 打开+微信扫码登录。`cli` 的所有子命令
都依赖 IDE 主进程写的 `.cli` 握手文件,这一步只能靠人在界面上用手机扫码完成,没有任何
命令行/API 能绕过。本任务也没有配到 GUI 自动化工具,而且就算有,扫码这一步本来就必须
是 Max 本人的微信。

**需要 Max 做的**:手动打开一次「微信开发者工具」App,用微信扫码登录,然后可以选择:
(a) 让我再跑一次 `cli auto-preview --project /Users/max/code/spatial-memory/miniapp`
    做冒烟;或
(b) 直接在 GUI 里「导入项目」选 `/Users/max/code/spatial-memory/miniapp` 这个目录,
    AppID 已经写在 `project.config.json` 里(`wx551ef9eb67257f96`),不需要额外填。

**不影响的部分**:验收1-4(JSON 解析/文件齐全/无 secret 泄露/js 语法)全部已跑通,
详见 PROGRESS.md「批次G」。小程序代码本身的静态正确性不依赖这一步。

---

## I-1.〈button〉标签宽度查询在本机这版开发者工具上返回假值,判断为查询层
artifact,不是渲染bug,未做任何代码改动(只读排查,如实登记)

**背景**:批次I 量化验收 index 页 `.primary-btn`/`.round-btn`/`.photo-total`/
`.back-btn` 几个 `<button>` 元素的几何时,发现全部返回同一个数字。

**实测**(三种互相独立的测量路径,结果完全一致):
```
$ element.size()  (automator domProperty(offsetWidth) 桥)
  .primary-btn -> {"width":184,"height":49}

$ miniProgram.evaluate(() => wx.createSelectorQuery().select('.primary-btn')
    .boundingClientRect(...))   (小程序自己的正牌API，非automator专用桥)
  -> {"width":184,"height":49,"left":103,...}

$ element.style('width')
  -> "184px"
```
`.primary-btn` 的 CSS 是 `width:100%`(容器约348px宽),`.round-btn`/`.back-btn`
是 `width:64rpx`(约33px),`.photo-total` 是内容宽(不到60px)——四个元素CSS
规则完全不同,却全部查出同一个184,这不像是各自独立的渲染bug,更像是这版
`automator`(0.12.1,2023年发布)配这版开发者工具(2.01.2510290,新两年)对
`<button>`元素几何查询的一个固定返回值/artifact。

**交叉验证**(排除"真的渲染歪了"这个可能性):用干净会话(先 `cli close`
彻底关掉旧连接再连新的,排除会话degraded state的干扰)截图
`ui-check/fresh-check-index.png`,肉眼核对跟批次H留下的参考截图
`ui-check/01-index-FINAL.png`一致——`.primary-btn`视觉上清清楚楚撑满整行,
不是184px的窄条;`ui-check/fresh-check-pano.png`里`.round-btn`视觉上是正常
大小的圆形返回箭头,没有拉伸变形。中心点计算(`centerX`)在两种情况下都跟
视口中心吻合(`.primary-btn`偏差0px),说明即使宽度数字本身查得不对,
"元素被正确居中"这件事没有受影响。

**结论**:这是本机 automator+devtools 版本组合对 `<button>` 元素宽度查询的
artifact,不是真实渲染问题,也不会在真机上出现(真机用户的微信客户端不会
经过这套桌面自动化查询协议)。**没有把这四个 button 转成 view**——批次H
给 `gyro-btn` 做过同样的 button→view 转换(理由记的是"184px的长椭圆,视觉
上真的拉伸了"),这次没有照办的原因是:反复截图确认了这次没有对应的视觉
症状,只是数字查不对,没有真bug可修,硬转会是无意义的代码改动
(而且转成view会损失一点原生button的可访问性语义)。批次H那次的转换保留
不动(无害,不需要重新论证或回退)。

**留给下一个人**:如果以后又在这版工具上量出`<button>`元素的width/height
异常,先按这条记录交叉验证一次视觉截图,别急着假设是代码bug、更别急着无脑
转view——先看是不是又是这同一个查询层的坑。

---

## I-2. miniprogram-automator 的 launch() 在本机重复调用时会静默卡死,
改用自建端口探测+connect()绕过(工具链踩坑,如实登记)

**背景**:批次I 用 automator 反复量数字/截图,前后跑了十几次连接。

**实测**:第一次(环境全新)`automator.launch()`在约10秒内正常返回;之后
只要是"同一个projectPath第二次launch()",经常静默卡死——`lsof`能看到
自动化端口(默认9420)已经在监听,说明devtools那一侧其实已经就绪,但
node这边的`launch()`调用就是不返回也不报错,给了90秒硬超时都等不到。
用`probe.js`/`probe-steps.js`逐步隔离确认:`connect()`直连一个已知在监听
的端口,<10ms正常返回;问题精确定位在`launch()`内部"spawn cli auto +
轮询等WS就绪"那段逻辑,不在WS通信本身。

**结论/规避**:自己写了`ui-check/connectHelper.js`——用`net.createConnection`
探测端口是否已经开着,开着直接`automator.connect()`,没开就自己`spawn`一次
`cli auto --project ... --auto-port 9420`(detached,不受当前node进程存活
影响)再轮询端口。全程改用这条路径后,几十次调用没有再卡死过。

**副作用**:这套workaround会在`cli auto`背后留一个"项目自动化窗口"进程,
`disconnect()`不会让它退出,必须显式`cli close --project <path>`才会关掉
(而且`cli close`打印"✔ close"之后进程/端口有时还要再等最多~20秒才真正
释放,不能立刻信"✔"这一行,得用`lsof`轮询确认端口空了)。如果不清理,连续
攒了好几个这种残留窗口后还观察到过一次`screenshot()`异常慢(133秒才返回,
怀疑是当时那个会话已经被来回折腾出某种degraded状态),干净会话截图正常在
几百毫秒到几秒内完成。**下一个人如果要接着用这批automator脚本**:每次跑完
一组操作,养成先`cli close --project /Users/max/code/spatial-memory/miniapp`
再等端口真正释放的习惯,不要在同一个残留会话上无限叠加操作。

---

## J-1. 上传验收测试留下的真实OSS对象,待清理

**背景**:批次J验收2要求真传一张测试图到OSS验证201,不许mock。用
`miniapp/assets/panos/expo.jpg`(199953 bytes)当测试图,`ui-check/verify-upload.js`
真传了两次(一次对stressexp1,一次对s4)。

**stressexp1这次真的写进了OSS,需要人工清理**:
```
sid = stressexp1
key = spaces/stressexp1/inbox-v2/g1/1785328114446_vwdigk__6aqM5pS26ISa5pys5rWL6K-V__free.jpg
状态 = HTTP 201写入成功,ETag=BFD0D4F895DA2960466C08D2629ABF35
       (base64url解码那段昵称是"验收脚本测试")
截至本次会话结束,worker还没把它捡进pending[]/photos[](space.json里查不到
对应inboxKey=1785328114446_vwdigk),大概率还静静躺在inbox-v2/g1/前缀下。
```
**需要Max做的**:方便的时候用有权限的工具(控制台/ossutil,不是这份公开policy)
删掉这一个对象,或者不管它(反正也不会被worker当成正常投稿处理进正式相册,
contributor字段解出来是"验收脚本测试"一望而知是测试数据,不会误导真实展示)。

**s4这次没有创建任何对象,不需要清理**:s4的policy在测试时点已经过期约44~46
小时(`expiresAt`早于测试时刻),OSS直接403拒绝(`Invalid according to Policy:
Policy expired.`),这次POST是刻意用来验证"policy过期"这条错误分类逻辑对
真实OSS报文有效,不是意外——顺带发现的真实情况是:**s4空间的上传policy已经
过期超过一天半,如果不是靠这次批次J顺手测出来,正常宾客现在去s4传照片会
无声失败**(不是小程序或H5代码的问题,是space.json里那份policy本身过期了,
需要跑一次能签发新policy的流程给s4刷新——这条不在本任务改动范围内,记在这
里留给知道怎么刷新space.json的人)。

---

## J-2. automator的mockWxMethod模拟不了chooseMedia到uploadFile的真实文件句柄交接,
只能验证到UI接线正确,选图+真传这一步必须真机验(如实登记,不是代码bug)

**背景**:批次J验收3做完三屏截图后,额外尝试(非acceptance硬性要求)用
`mockWxMethod('chooseMedia', {tempFiles:[...]})` + `element.tap('.upload-btn')`
端到端驱动小程序自己的`onUploadTap`真实代码路径,想验证"从点按钮到传完"整条
链路而不是分开验证。

**实测**:mock让`wx.chooseMedia`成功返回了一个指向本机真实文件的绝对路径
(`miniapp/assets/panos/expo.jpg`,后来换成scratchpad里复制的一份,排除"路径
在项目目录里"这个变量),两次都在几乎第一时间(<1.5s)落进
`upload.js`的`网络不好,传失败了`错误分支(`wx.uploadFile`的fail回调)。

**判断**:不是`upload.js`的bug——`extractPolicy()`/`buildKey()`这两个真正
承载"字段组装对不对"的函数已经在批次J验收2用真实OSS验证过(见PROGRESS.md,
HTTP 201)。这里失败的是automator mock出来的临时文件路径不被模拟器的
`wx.uploadFile`实现认可,推测是模拟器对"合法的临时文件"有自己的登记机制
(真实`wx.chooseMedia`/`wx.compressImage`成功时会把返回路径注册进这套机制,
mock直接伪造返回值绕过了注册这一步),不是网络问题也不是字段问题。

**不打算继续排查**:automator摸不到原生相册picker本身,这是文档记录过的
已知限位(跟I-2记录的"launch()卡死"是同一类"工具链本身的边界",不是产品代码
问题)，继续深挖“怎么伪造一个模拟器认可的临时文件”投入产出比低。**真正的
选图+传图验证挪到真机待验清单第1/2条**,那里才是唯一能测到"chooseMedia真实
弹出picker、真机选真图、真传"这条完整链路的地方。

**保留的证据**:`ui-check/j-04-upload-e2e.png`——状态条正确显示了诚实的
错误文案"网络不好,传失败了"(不是空白、不是卡死转圈、更不是假装成功的
"回到方位了"),证明就算触发失败,UI状态机本身接线是对的。

---

# 批次 K（2026-07-30 · v0.9 止血）遗留

## K-1. 腾讯云站点同步不归我，交主会话

本批次改了 6 个公开静态页（`portal.html` / `web/join.html` / `web/studio-login.html` /
`app/create.html` / `app/invite.html` / `app/scene.html`），**只提交了仓库，没有推腾讯云**。
按地界这件事不归我。

推的时候按记忆里那条硬规矩走**增量发版**（澳洲全量 47MB 必超时）：
`git diff ∩ deploy/public-files.txt` 只推变更，**以线上 md5 对比为唯一裁决**，
CLI 报错是未翻译模板不可信。⚠️ 该环境 2026-08-25 到期。

## K-2. `.gitignore` 不在地界，验收截图只能一直挂着 untracked

`tools/shots-k/` 里 16+ 张验收截图共 8.9MB，太重不进仓库；但 `.gitignore` 不在允许改的
文件清单里，加不了忽略规则，所以本地 `git status` 会一直显示它 untracked。
建议主会话加一行 `tools/shots-k/`。截图随时可重生成（命令见 `tools/sweep-public.md`）。

## K-3. `app/contract.md` 不在地界，三处已经跟代码对不上

契约文档本身不在允许改的清单里，只能登记：
1. **缺 `panoMini` 字段**。本批次给每个节点加了 2048×1024 降档图（字段 `panoMini`，
   文件名带源图内容哈希），公开快照里已经在发了，契约表里还没有这一行。
2. **`contract.md:141` 的任务 title 示例过时**：写的是 `"缺这个角度"`，第 5 件已把口径
   换成内容心愿（新生成的是 `"还想要这边的照片"`）。字段说明本身没错，只是例子旧了。
3. **`contract.md:94` 的 margin 口径漂移**（技术总纲第二章早就点出来了，本批次没动）：
   文档说 margin 是"第一名减第二名"，实际代码是"第一名减全体裁切的均值"
   （`server/space.py` 的 `place_photos`）。

## K-4. `workspace.html` 不在地界，死循环只从一头断了

P0-1 那个「工作台 ↔ 演示登录页」互相弹的死循环，我从 `web/studio-login.html` 这一头断了
（从工作台过来时不再自动跳转，停下并明说一句）。但 `workspace.html` 上仍然有两处
指回登录页的入口（`[data-studio-entry]`），它不在地界里没动。重做主办台时一并处理。

## K-5. P0-1 剩下的一半是 v1.1 的活，本批次只做了「藏/标演示」

走查时实测：静态站上点「验证并进入」，`POST /api/host/login` 返回 **501**，
而 `studio-login.html` 的「请求失败就放行」把它当成了登录成功。这是 P0-1 里的
「失败放行」，技术总纲给它的档期是 **v1.1 重做**，v0.9 的活是「藏/标演示」，已做到。
前后端口令契约互斥（前端只收 4 位且只认 1111，后端要 ≥6 位且拉黑 1111）同理，留 v1.1。

## K-6. 微信开发者工具 `--qr-format image` 在这个版本是坏的

报 `The QR code output path is invalid or does not exist %s`（`%s` 都没替换，是没翻译的
模板）。换 `/tmp`、仓库内相对路径、预建文件都一样。**`terminal` 和 `base64` 两种格式都正常**，
说明预览本身成功，坏的只是 image 这一个输出格式。本批次改用 `base64` 再自己解成 PNG。
任务书里写的是 `--qr-format image`，下次照抄会踩同一个坑。

## K-7. 模拟器截图拍不到 WebGL 画布 + `mp.screenshot()` 偶发挂死

1. **截不到**：全景页截出来永远是一片占位色。回头翻批次J 的 `ui-check/j-02-pano.png`
   一模一样，而那时贴的还是本地打包图 —— 所以这是截图 API 的限制，**"截图看着是空的"
   证明不了全景有没有加载**。本批次因此给页面加了 `panoReady` / `panoSrcInUse` 两个
   可断言字段，验收改看数据不看图。
2. **偶发挂死**：`mp.screenshot()` 在带 WebGL 渲染循环的页面上实测挂过两次
   （一次 7 分钟一次 10 分钟没返回，同一份脚本第一次跑却是好的）。已在 `tools/shots-k.js`
   里给它 20 秒上限，超时跳过继续跑。

## K-8. 明令不做的（等 Max 拍板）

- 体验空间「用户确认归位」方案的实现
- 小程序提审、微信后台三类合法域名配置（`request` / `uploadFile` / `downloadFile` 都要配
  OSS 域名，`urlCheck:false` 只骗开发工具不骗真机）
- 买服务器
- 删除任何页面

## K-9. 真机待验清单（自动化测不到的，任务书明令不做）

小程序达标七条里，本批次只做了能自动化验证的部分。这几条只有真机能验：
1. `chooseMedia` 真实选图（automator 摸不到原生 picker，见 J-2）
2. 真机加载 2048×1024 降档图（>2000px 失败率近 100% 这条正是它要验的）
3. 弱网上传 + 杀进程重开后待重传队列真的能把照片传上去
4. Policy 过期 / worker 重启这两条真实场景
5. 与 ECS worker 的真实端到端（不是只验 POST 201）
6. 两个空间交叉测试里"其一多节点"那一半：**现有 s4 和 stressexp1 都只有 1 个节点**，
   多节点过滤只在构造数据上验过（`tools/test_miniapp_contract.js` 的 n1/n2 用例），
   真实多节点空间还没有。

## K-10. P1-12（第三方视觉验收外发截图）没动，但复查了现状

不在本批次施工顺序里。复查 `server/judge.py:344`：**没有 `STEPFUN_API_KEY` 就走 local，
不外发**，也就是账本里"v0.9 默认关"这个状态**本来就已经满足**。真正缺的是空间级开关
和主办方可见的隐私设置（那是 P1-12 的完整解），仍然没有，所以账本里这一行没标已修。
