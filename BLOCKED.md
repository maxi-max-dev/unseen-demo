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
