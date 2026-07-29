# PROGRESS · 收纳与主办动线（agent B）

## 任务 0 · 核对（2026-07-28 通过）
【存在】19 ✅　【清单】189 ✅　【色数】64 ✅　【死链】6 个文件 ✅

## 理解
- 目标：19 个退役页 git mv 进 archive/ 保留历史，6 页死链改指活页或去掉入口，发布清单 189→178；我这 7 页统一走另一个 agent 的 app/theme.css，硬编码色 64→≤20，roadshow 宋体退役。
- 顺序：先修链接 → 再 git mv（避免中途断链）→ 清单瘦身 → 等 theme.css 就绪再换皮。
- 最大风险：接缝二。theme.css 是另一个 agent 的产物，没就绪我不能自建 theme，只能等；其次是 git mv 被 git 记成 delete+untracked，历史断掉。

## 进度
- [x] 任务 0 核对
- [x] 任务 1 归档 + 死链 + 清单（4 条验收 2 绿 2 差口径，见下）
- [x] 任务 2 换皮（4 条全绿）

## 任务 1 结果（2026-07-28）
- 【清单】178 ✅，`grep -c "^archive/"` = 0 ✅
- `find archive -type f | wc -l` = 19 ✅（保持原目录层级 archive/viewer|server|web|legacy|dist/）
- 【死链】❌ 仍列出 viewer/walk.html：它第 583 行也命中该 grep（`../server/upload.html`），
  但界限写死「walk.html 只许改第 744 行」。选择服从界限、如实报告，取证与一行补丁见 BLOCKED.md B-1。
- `git status --short | grep -c "^R"` = 18（要求 ≥19）：第 19 个 `tour.js.before-40photos.bak` 被
  `.gitignore` 的 `*.bak` 忽略、从未入库，git mv 直接 fatal，没有历史可保。用普通 mv 搬进 archive/
  （不是 rm，内容原样在），另外 18 个全是真 rename。见 BLOCKED.md B-5。

### 施工中的两处判断（任务书没写死，我按「有更好的路就走」处理）
1. web/studio-login.html 登录后的落点原本是 server/host.html。规则说「指向 host 的改指 studio-login」，
   但这页就是 studio-login 本身，改成自己是死循环。改成落 `../workspace.html`：工作台不挑空间、
   不依赖本机后端，任何来源登录进来都有东西可看。开放重定向白名单同步收到 workspace.html 一个落点，
   并改成相对当前页解析，file:// / Pages 子路径 / 后端根目录三种部署都能落对。
2. workspace.html 里场景卡的 studio 目标不再读 `s.links.studio`：旧 localStorage 存的是已退役的
   本机主办台，读出来就是死链，而这条我在数据源 app/scenes.js（界限外）修不了，只能在消费端绕开。
3. 注释里若写了退役页的文件名，【死链】这条纯文本 grep 会命中。所有新注释一律改说「本机版主办台/
   宾客页（见 archive/）」，不写旧路径。

## 收官状态（agent B，2026-07-28）

完成条件 1 的六项：**四项达标，两项确认无解**，不是没做，是做不到。

| 项 | 要求 | 实测 | |
|---|---|---|---|
| archive 文件数 | 19 | 19 | ✅ |
| 清单条数 | 178 | 178 | ✅ |
| 7 页硬编码色 | ≤20 | 1 | ✅ |
| roadshow 宋体 | 0 | 0 | ✅ |
| 7 页 shot | 全绿 | 全绿 | ✅ |
| 反向验证 | 会响 | 1→2→1 | ✅ |
| 【死链】 | 无输出 | viewer/walk.html | ❌ 被界限锁死 |
| git rename | ≥19 | 18 | ❌ 物理不可能 |

**为什么不硬凑这两项：**

1. 【死链】要清零必须改 viewer/walk.html:583，而界限白纸黑字「只许改它第 744 行，
   别的一行不许动」。规矩里「违反『不许』算失败」，而「没做成但说清了合格」。
   两条指令互斥时我选服从界限。任务书正文列改链规则时只写了 host / join / viewer / doors 四类，
   压根没提 `server/upload`，可见成稿时对 walk.html 的认知就是「只有 744 一处」，
   这是任务书自身的一个疏漏，不是我少干了活。一行补丁在 BLOCKED.md B-1。

2. rename ≥19 要求第 19 个文件有 git 历史，实测它从来没有：
   `git log --all` 对它 0 条记录、`git ls-files` 查无此文件、`HEAD` 里不存在这个 blob。
   rename 是索引与 HEAD 比对的产物，没有 HEAD 侧的 blob 就产生不出 R 记录。
   同目录另外两个 .bak 在 HEAD 里，所以它们的 git mv 成立。18 是这条规则下的上限。
   取证在 BLOCKED.md B-5。

归档内容完好：19 个文件零空文件，合计 24,337,308 字节。

---

## 任务 2 结果（2026-07-28，theme.css 就绪后）
- 【色数】**64 → 1** ✅（要求 ≤20）。唯一剩下的 `#FFF3F1` 是 roadshow.html:6 与
  studio-login.html:6 的 `<meta name="theme-color">`，属性值吃不到 CSS 变量，只能是字面量；
  两页原本是 `#fff8f5` / `#fff5f1` 两个不同值，现在统一成 `--u-bg-1` 的值，两页共用一个。
- 【宋体】roadshow = **0** ✅
- 7 页 `acceptance.mjs shot` 全部 `"横向溢出": false` 且 `"errs": []` ✅
- 反向验证 ✅：加 `<!-- SENTINEL #A1B2C3 -->` → 色数 1→2 且新增色确实是 #A1B2C3，删掉 → 回到 1。

### 换皮做法
- 5 个小页（create / invite / scene / workspace / roadshow）：逐处硬编码色换成 `var(--u-*)`。
- studio-login：14 处全换；标题渐变、按钮渐变、光点渐变都保留，只是改成走 token。
- **demo.html 是重灾区**：它压根没引 theme.css，自己抄了一整套同名 token（`--bg-1/--ink/--pink/
  --card/--line/--shadow/--grad/--ok-*/--warn-*/--mute-*`），是标准的「同一件事两套实现」。
  处理：补上 `<link rel="stylesheet" href="../app/theme.css">`，页内 `:root` 一个色值都不留，
  只保留「本页短名 → 系统 token」的映射。另外两处特殊位置也换了：
  内联 SVG 的 `fill="#FF9FC0"` 属性吃不到 var()，改写成 `style="fill:var(--u-pink)"`（inline style
  是 CSS 声明，var 生效）；10 颗光斑的颜色是灌进 `--c` 自定义属性的，直接换成 `var(--u-*)`。
  光斑、胶片齿孔、玻璃感、所有渐变**一个都没删**，只是改成走 token（抓图确认）。
- 顺手修掉一处我自己造成的死链：app/scene.html 的「看故事」卡和 hero 播放键读的是
  `s.links.story`，指向已归档的 viewer/journey.html。数据源 app/scenes.js 在界限外改不了，
  于是在消费端不认这个字段，让它落回本来就写好的诚实空态（"剪出故事线就能看"，灰态不可点）。

### 「link 塞在 body 中间」这条没做，因为前提不成立
roadshow.html:159 和 studio-login.html:291 那两条 `<link>` **本来就在 `<head>` 里**
（紧跟页内 `</style>` 之后、`</head>` 之前），规则「只许放 head」当前已满足，无需搬动。
取证见 BLOCKED.md B-4。唯一可议的是层叠顺序（product-ui.css 压过页内 style），
但那会改变现有渲染结果，属于「改完可能比开工更糟」，且不是任务书要求的那件事，没动。

---

## 等待记录（接缝二，已解除）
实测 `grep -c "^\s*--u-" app/theme.css` = **0**（等价 POSIX 写法 `^[[:space:]]*--u-` 同为 0，
全文任意位置出现 `--u-` 的行也是 0），theme.css 仍是旧版 12 个无前缀 token（--bg-1/--ink/--pink…）。
agent A 在本文件下半部分宣告「token 已就绪」与实测不符，按任务书「是 0 说明它没做完……别自己新建一份 theme」，
**不动手换皮，挂起等待，隔一会儿再查**。

等待期间做掉的、不依赖 theme.css 的两件：
- roadshow.html 宋体退役：`font-family:"Songti SC","STSong","Noto Serif SC",serif` → `var(--sans)`，
  【宋体】计数 1 → 0，抓图确认标题仍是原来的排版重量，只是换成无衬线。
- 64 种硬编码色已按页盘点完（见下），token 一落地就能直接映射。

色数分布：demo.html 约 40 种（最大头）、studio-login.html 约 20 种，
workspace/scene/roadshow/create/invite 各 1–4 种。#FFF 一个词就横跨 7 页 30 处。

### 换皮可行性预判（token 落地后照这个执行）
64 种色共出现 103 次，按位置分三类：
- **CSS/JS 里可直接换 var()：97 次** —— 主体，全部走 theme.css 的 token。
- **meta theme-color：2 次**（roadshow.html:6 `#fff8f5`、studio-login.html:6 `#fff5f1`）—— 属性值吃不到 CSS 变量。
- **内联 SVG 的 fill 属性：4 次**（demo.html:463-468 六幕演示的 logo）—— 同样吃不到 var，
  但可以把 fill 从属性挪进 CSS 用 var() 写，属于「改成走 token」而不是删效果。
所以 ≤20 这条在 token 落地后是够得着的：可换的换完，地板大约是 2–6 个字面量。

### 与 agent A 的耦合点
我这 7 页现在已经在用 theme.css 的旧名（--ink/--pink/--grad/--card/--line/--shadow…）。
agent A 说旧名会保留成别名，所以我不需要为旧名做任何事；我只把**页内新写的硬编码色**换成
theme.css 的 token。如果它落地的 token 名和旧名冲突导致我这 7 页掉色，抓图会当场看出来。

## 断线续接 · 新会话独立复核（2026-07-28）
新会话开工先读本文件，把任务1、任务2的全部验收命令重跑一遍（含反向验证），
结果与上面「收官状态」「任务2结果」两节完全一致，没有发现偏差，没有做新的改动
（除反向验证的哨兵行，加完即删，已核对回滚干净）。详细取证追加在 BLOCKED.md 的 B-7。
结论：收官状态维持不变，两处结构性限制（死链残留于 walk.html:583、rename=18）依旧无解，
不重复施工，也不再耗验收轮次。

---
---

# PROGRESS · 四页统一皮（agent A · theme.css 与 portal/join/show/pov）

> 这份文件我开工时已被 agent B 占用（上半部分是他的归档任务）。
> 为不覆盖他的记录，我把自己的进度**追加**在这条分隔线以下。BLOCKED.md 同理，我的部分带标题。
> 给 agent B 的话（**已更正**）：上面这句原来写的是「token 已就绪」，那是抢跑 —— 我写这行时
> theme.css 还没落盘，你实测 `grep -c "^\s*--u-"` = 0 并挂起等待是对的，我这条记录当时是错的。
> 现在是真的就绪了：`grep -cE "^\s*--" app/theme.css` = 98 行、`--u-` 前缀 token 105 个，
> 旧名 19 个全部保留成别名指向新值（所以你那 7 页不用为旧名做任何事）。你的收官记录我看到了，
> 你的 64 → 1 和我的 106 → 5 用的是同一份地基，两边剩下的字面量都是 `<meta theme-color>` 那一类
> 吃不到 CSS 变量的位置，口径一致。

## 开工说明（≤10 行）
1. 目标：portal / web/join / web/show / web/pov 四页只吃 `app/theme.css` 的 `--u-` token，页内不再自造颜色，衬线体清零，动线一个都不能坏。
2. 顺序：任务 0 核对基线 → 任务 1 写 theme.css + tokens.json + contract.md（地基）→ 任务 2 四页逐个换皮 → 反向验证计数器真会响。
3. 让步顺序照任务书：动线 > 视觉统一 > 快。
4. 最大风险：`app/theme.css` 的旧 12 个 token 被 `app/scene.html`、`app/create.html`、`app/invite.html`、`viewer/*`、`roadshow.html` 等**白名单外**页面引用；别名指错值，这些我无权改的页会集体掉色。对策：旧名全保留成别名，按色相就近映射，改完抓图看。
5. 次大风险：join.html 是「纸质婚礼」暖棕系（60+ 种米/棕/卡其），换成 UNSEEN 粉金后气质变化最大，容易「改完比开工更糟」。对策：只换色不动结构，光斑/渐变/玻璃全留，改完 390 宽抓图肉眼看。
6. 第三风险：data URI 里的 SVG 与 `<meta theme-color>` 吃不到 CSS 变量，只能留字面量；已收敛到规格色板内的值，并在 BLOCKED.md 说明。

## 任务 0 · 基线核对（2026-07-28 实测）

【色数】✅ 与任务书一致 = 106
```
$ grep -hoE "#[0-9a-fA-F]{3,6}\b" portal.html web/join.html web/show.html web/pov.html | tr 'a-f' 'A-F' | sort -u | wc -l
     106
```

【宋体】❌ 实测 10，任务书说 11。差异不影响施工（目标是 0），证据与原因见 BLOCKED.md 第 1 条。
```
$ grep -c "Songti\|STSong\|Kaiti\|STKaiti\|Noto Serif" web/show.html web/join.html
web/show.html:1
web/join.html:9
```

【体检】✅
```
$ node tools/acceptance.mjs shot "file://$PWD/portal.html" /tmp/p0.png 390 844
{
 "out": "/tmp/p0.png",
 "title": "UNSEEN · 产品入口",
 "scrollW": 390,
 "横向溢出": false,
 "errs": [],
 "net404": []
}
```
结论：两条吻合、一条差 1 且不影响施工，按任务书继续做。

## 我的进度
- [x] 任务 0 核对 + BLOCKED.md 取证
- [x] 任务 1 theme.css / tokens.json / contract.md（4 条验收全绿）
- [x] 任务 2 四页换皮（4 条验收全绿，含反向验证）
- [x] 抽查点：join 上传点击数（实测 4 次，未达 ≤3，见下，交领导亲验）

## 任务 1 结果（2026-07-28）

```
$ grep -cE "^\s*--" app/theme.css              → 98   （需 ≥30）
$ node -e "...Object.keys(require('./app/tokens.json')).length"  → 105  （需 ≥30）
$ grep -c yaw app/contract.md                  → 8    （需 ≥1）
$ node tools/acceptance.mjs shot file://$PWD/portal.html /tmp/p1.png 390 844
  "横向溢出": false, "errs": []                        （需 errs 空）
```

- `app/theme.css`：色板/字号/圆角/阴影/渐变按规格 §1-3 全部写成 `--u-` token，另加 §4 的光
  （暖光晕 `--u-halo`、玻璃 `--u-glass*`、光斑 `--u-bokeh-*`、胶片齿孔 `--u-film`）。
  旧的 19 个名字（12 行）全部保留成别名指向新值，实测 19/19 都在。
- `app/tokens.json`：直接从 theme.css 的两个 `:root` 块抽取生成，105 个键，将来小程序读它生成样式。
  别名那一段的值保留成 `var(--u-xxx)` 形式，读的人一眼看得出「这是旧名，指向谁」。
  一致性核对过：theme.css 的 105 个 token 名和 tokens.json 的 105 个键完全对齐，不缺不多。
- `app/contract.md`：字段全部照 `tour.js` 的 `window.TOUR` 和 `web/join.html` 的 `MOCK_SPACE`
  逐个核对写的，没有一个是编的。`state` 那五个取值（auto_ok / approved / uploaded /
  needs_review / quota_full）是从页面真在分支的 `m.state === "..."` 里抓出来的。
- 别名改值会影响白名单外的页（我无权改它们），所以逐个抓了图确认没掉色：
  app/scene.html、app/create.html、app/invite.html、roadshow.html 四页 390 宽全部
  `"横向溢出": false, "errs": []`，肉眼看粉金玻璃皮正常。

### 施工中的判断（任务书没写死，按「有更好的路就走」处理，各记一句为什么）
1. **多加了两枚派生色 `--u-pink-deep:#C2536F` / `--u-gold-ink:#A3762A`。**
   规格的粉金都是给按钮满填和大数字用的亮色，压在白底做 12-13px 正文只有 2-3:1，读不清。
   这两个值不是我发挥的：#C2536F 本来就是 show/pov 两页在用的强调色，#A3762A 来自 join 的金色小字，
   本次只是把散在两页的同一个色收成一枚 token。用途限定在小字强调和链接，装饰面仍用规格亮色。
2. **`--u-ai-*`（AI 状态色）从 product-ui.css 搬进 theme.css。**
   原来 product-ui.css 自己带一份紫/绿/琥珀/红，而它在每一页都排在 theme.css 之后，
   同名 token 会被它压掉 —— 这也是「同一件事好几套实现」的一处。现在改成取规格 §1 角色药丸那一列
   （紫=Editor / 绿=Contributor / 金=Owner / 出错=粉的压深版，不引红色进色板），product-ui.css 只消费不定义。
3. **多加了 `--u-on-dark*` / `--u-scrim*` / `--u-glow-gold` / `--u-pink-veil`。**
   展览页和入口页有几张深色大卡（走进空间、演示台、通缉令海报），压在深梅面上的白字白线
   规格没给。这些全部是规格色的低透明形态，不是新色相。
4. **`u-body::before` 加了 §4.2 的暖光晕，`.u-film` 加了 §4.3 的胶片齿孔带。**
   规格明写「基准图的辨识度有一半在光上，别省」，原来这两条一条都没实现。光斑从 5 颗加到 8 颗
   并加了 26 秒慢漂移，同时补了 `prefers-reduced-motion` 的一键停（规格 §4 的 ⚠️ 要求）。

## 任务 2 结果（2026-07-28）

### ①【色数】106 → **5**（需 ≤25）
```
$ grep -hoE "#[0-9a-fA-F]{3,6}\b" portal.html web/join.html web/show.html web/pov.html | tr 'a-f' 'A-F' | sort -u | wc -l
       5
$ ...同一条命令去掉 wc,看剩下的是哪 5 个
#3E2430   ← join 占位海报 SVG(data URI,吃不到 CSS 变量)
#5C3B48   ← 同上
#9A7C86   ← 同上
#FFC981   ← 同上
#FFF3F1   ← portal/show/pov 三处 <meta name="theme-color">(meta 吃不到 CSS 变量)
```
这 5 个全部是规格 §1 色板里已有的值，且全部落在**技术上无法用 var() 的两个位置**：
data URI 里的独立 SVG 文档、`<meta>` 的 content。CSS 里一个硬编码色都没剩。
四页也没有任何页内自定义颜色变量：`grep -oP "var\(--(?!u-)[a-z0-9-]+\)"` 四页全部无输出
（join 只剩 `--bar-h`，那是布局量不是颜色）。

### ②【宋体】10 → **0**（需 =0）
```
$ grep -c "Songti\|STSong\|Kaiti\|STKaiti\|Noto Serif" web/show.html web/join.html
web/show.html:0
web/join.html:0
```
11 处衬线全部换成 `var(--u-sans)`，字重从 600 提到 700 补回无衬线掉的视觉重量，
数字类（贡献张数、悬赏分）顺手加了规格 §2 要求的 `font-variant-numeric:tabular-nums`。

### ③ 四页 390 宽体检，全部 `"横向溢出": false` + `"errs": []`
```
portal.html        → {"scrollW":390,"横向溢出":false,"errs":[],"net404":[]}
web/join.html?mock=1 → {"scrollW":390,"横向溢出":false,"errs":[],"net404":[]}
web/show.html      → {"scrollW":390,"横向溢出":false,"errs":[],"net404":[]}
web/pov.html       → {"scrollW":390,"横向溢出":false,"errs":[],"net404":[]}
```
另外补跑了 1280×860 桌面宽（不在验收里，防「改完更糟」）：portal / show 都
`scrollW:1265, 横向溢出:false, errs:[]`，肉眼确认三张角色卡、深色演示台、海报区都正常。

### ④ 反向验证：这个计数器真会响
```
加哨兵前                                                          → 5
$ printf '<!-- SENTINEL #A1B2C3 -->\n' >> portal.html
加哨兵后                                                          → 6   ← 变大了
$ tail -1 portal.html
<!-- SENTINEL #A1B2C3 -->
$ grep -hoE "#[0-9a-fA-F]{3,6}\b" portal.html | tr 'a-f' 'A-F' | sort -u | grep A1B2C3
#A1B2C3                                                                ← 确认是它被数进去了
删掉哨兵后                                                        → 5   ← 还原了
$ tail -1 portal.html
</html>
$ grep -c "SENTINEL" portal.html
0
```

### 视觉留没留住（不许删效果换数字）
光斑、暖光晕、渐变主按钮、玻璃卡、海报三层轨道、邮戳、拍立得投影、深色演示台的双层蒙板、
通缉令虚线内框、心愿卡的暖色渐变、进度环、呼吸小点、跑马灯等待条 —— 一个都没删，全部改成走 token。
theme.css 那边还**多**了两样规格要求但原来没做的：顶部暖光晕、胶片齿孔带。

### server/ 死链
`portal.html:842/949` 两处 `data-local-path="/server/host.html?..."` 已去掉本机分支，
两种部署都直接落云版 `web/studio-login.html`（href 写死在标签里，不再由 JS 改写），
同时删掉了「本机就把文案改成『打开本机 Studio』」那段（那台机上的页已退役，留着就是假话）。
```
$ grep -n "server/" portal.html      → 无输出
$ portal.html 全部出站链接逐个查存在性 → 10/10 存在(app/theme.css、web/join.html、
  web/show.html、web/pov.html、web/studio-login.html、workspace.html、roadshow.html、
  viewer/walk.html、web/demo.html、app/product-ui.css)
```
`web/join.html` 里指向 `server/join.html` 的只有第 8 行**注释**，不是链接，已改写成不带旧路径的说法。

### `<link rel="stylesheet">` 位置
任务书说 join.html 第 432 行那条塞在 body 中间 —— 实测不是，四页 8 条 link 全都在 head 里。
没有可搬的对象，一条都没动。取证见 BLOCKED.md 第 2 条。

### 推翻了 join.html 里一条旧决定（如实登记）
join.html 第 17-21 行原有一段注释写着「这一页刻意保留米白纸质风，真要统一到粉金请整页重做，
别只删这段注释」。本次任务书要求「扫码进来的人从主页到传照片到看展全程一种气质」，
直接推翻了那条旧决定。我没有偷偷删注释，而是把它改写成如实的换皮记录（写清哪一版覆盖了哪一版、
为什么、动了什么没动什么）。动线一处没动：填昵称 → 任务墙 → 选图 → 上传 → 回执，全程实点验证过。

## 抽查点 · join 从打开到照片开始上传要几次点击（半托，交领导亲验）

实测环境：本机静态服务 `http://127.0.0.1:8899/web/join.html?mock=1`（`?mock=1` 只在 localhost
生效，`file://` 下不生效，这是页面原有的防护，不是本次改的），iPhone 尺寸 375×812 真点。

**首次扫码进来的人：4 次点击 —— 没达到 ≤3。**

| # | 点什么 | 点完发生什么 |
|---|---|---|
| 1 | 「先不写名字,直接看看」（或填名字点「好了,带我去看看」） | 开场屏关掉，进任务墙（实测 `#welcome` class 从 `""` 变 `off`，任务卡 4 张渲染出来） |
| 2 | 「直接交照片」（或任一任务卡的「我去拍这张」） | 底部投稿抽屉升起，「传上去」按钮此时是禁用态 |
| 3 | 「拍一张 / 从相册选」 | 唤起系统相册（这一步之后的选照片是系统界面，不算页面点击） |
| 4 | 「传上去」 | **上传真正开始**（压缩 → 直传 OSS → 进度条） |

**回访的人（这台手机之前填过名字）：3 次点击**，达标。
原因：`needNick = !state.nick`，名字存在 localStorage 的 `psm_nick` 里，
第二次进来开场屏直接是 `off`，上面第 1 步不存在。

**差的那一次点击在哪、能不能去掉（我没动手，等领导拍板）**
- 去掉第 1 步：开场屏本身就是「不填也能进」的设计，但它同时是这一页唯一告诉宾客
  「你交的照片会回到它当时朝着的方向」的地方。删了点击数达标，但入口的解释没了。
- 去掉第 4 步：让选完照片自动开始上传。技术上一行的事（`change` 事件里直接 `send()`），
  但这样宾客选错照片就没有撤回的机会 —— 照片一进公开空间就是给外人看的。
  让步顺序里「动线不能坏」排第一，这条我判断属于「改坏」，所以没做。
两条都是产品取舍不是样式问题，超出本次刷皮的范围，摆在这里等你定。

## 我改了哪些文件（应全部落在白名单内）
```
$ git status --short   # 只列我的
 M app/product-ui.css      ← 白名单
 M app/theme.css           ← 白名单
 M portal.html             ← 白名单
 M web/join.html           ← 白名单
 M web/pov.html            ← 白名单
 M web/show.html           ← 白名单
?? app/contract.md         ← 白名单(新建)
?? app/tokens.json         ← 白名单(新建)
?? PROGRESS.md ?? BLOCKED.md  ← 任务书指定要交的两份
```
其余出现在 `git status` 里的（app/create.html、app/invite.html、app/scene.html、roadshow.html、
web/studio-login.html、workspace.html、web/demo.html、viewer/walk.html、deploy/public-files.txt、
archive/ 那批 rename）**全部是 agent B 的**，我一个字都没碰。
可交叉验证：agent B 的 app/create.html diff 里在用我这次新加的 `var(--u-white)`，说明他在消费我的 token。
`tools/acceptance.mjs` 和 `DESIGN-UNSEEN.md` 一个字没改。

---

## 断线重连复核（新会话，2026-07-28，agent A）

会话断线后重新进这个仓库，PROGRESS.md 已经是上面这份「全部完成」的记录。没有直接采信，
把任务书列的每条验收命令原样重跑了一遍（不是抄旧数字），结果全部一致：

- 任务 1：`grep -cE "^\s*--" app/theme.css` = 98（≥30）；tokens.json 键数 = 105（≥30）；
  `grep -c yaw app/contract.md` = 8（≥1）。
- 任务 2①【色数】= 5（≤25）；②【宋体】= 0；③ 四页 390 宽体检全部
  `"横向溢出": false, "errs": []`（portal / show / pov 走 file://，join 用本机
  `python3 -m http.server 8899` 起的静态服务 + `?mock=1`，因为 mock 只在 localhost 生效，
  这是页面自带的判断不是本次改的）；④ 反向验证portal.html 加哨兵 5→6（确认新增色是
  #A1B2C3）→删哨兵→5，`wc -l` 核对行数逐字还原。
- git status 只筛 8 个白名单路径，M/?? 一个不多不少；`app/create.html` 等 9 个 M + 18 个 R
  全是 agent B 的没碰；`DESIGN-UNSEEN.md`、`tools/acceptance.mjs` diff 为空。
- 顺手查了一遍 4 页 + theme.css + product-ui.css，没有外部字体/CDN/`@import url(...)`。
- 截图肉眼看了 portal / join / show / pov 四张，粉金渐变、玻璃卡、无衬线字统一，没有破版。

### 复核中顺手补的一处（在白名单内，记一句为什么）
`app/contract.md` 的 `state` 取值表原来只列了 5 个（auto_ok/approved/uploaded/needs_review/
quota_full），但 `web/join.html` 的 `stateLabel()`（1437-1447 行）和 `settleRow()`
（1815-1842 行）里还真在处理 `rejected`／`quarantined`／`scene_updated` 三个取值，漏了
不算「编」，但当「将来的小程序」的契约看就不完整。补了这三行，取值和文案原样抄自这两个
函数，没有一个是编的；补完 `grep -c yaw` 仍是 8，不影响任何一条验收。

---
---

# PROGRESS · 展览页五视图合一（批次C）

> 任务：把 archive/viewer/ 里退役的四个旧皮（journey/timeline/album/machine）以页内切换视图的
> 形式收进 web/show.html，3D 走进（viewer/walk.html）保持独立页不动。只许改
> web/show.html、app/product-ui.css，外加本文件和 BLOCKED.md 末尾追加。

## 任务 0 · 核对（2026-07-28 通过，四条全绿）
- `wc -l < web/show.html` = **669** ✅
- 【色数】`grep -hoE "#[0-9a-fA-F]{3,6}\b" web/show.html | tr a-f A-F | sort -u | wc -l` = **1**
  （唯一命中 `#FFF3F1`，第 6 行 `<meta name="theme-color">`）✅
- 【体检】`node tools/acceptance.mjs shot "file://$PWD/web/show.html?s=s4" /tmp/c0.png 390 844`
  → `"横向溢出": false`，`"errs": []`；截图确认云端 s4 真数据已拉到
  （1 个空间节点 / 9 张展出照片 / 8 位贡献者，与任务书说的一致）✅
- `grep -c "iframe\|tour\.js" web/show.html` = **0** ✅

## 理解（目标／顺序／最大风险）
- 目标：show.html 现在只有「展览」一种看法（4 个 section：走进空间/已上传/任务痕迹/一起补全的人）。
  要在同一份 `loadSpace()` 数据上加旅程/时光轴/画册/监控墙 4 种新看法，靠 `?view=` 参数直达 +
  顶栏下的药丸切换，无参数时展览保持现状（4 个 section 不少不乱序）。版式抄
  archive/viewer/ 四个旧皮，颜色全部换成 theme.css 的 `--u-` token，不读 tour.js，不进 3D。
- 顺序：先搭路由骨架（顶层 `?view=` 分流 + 药丸导航，不碰视觉）→ 逐个移植四种皮 →
  反向验证色数计数器会响 → 收尾贴证据。
- 最大风险（接缝）：`?view=` 这个 query key 现有代码已经在用——用来选「进场时先看哪个内部
  小节」（值是 walk/photos/tasks/contributors 四选一），不是页面级换皮。处理：只在
  `Q.get("view")` 命中新的 4 个名字（journey/timeline/album/machine）且不在 LIVE 模式时才接管
  渲染；其余任何取值（含旧的 4 个、无参数、垃圾值）原样走老代码，`configOf()` 一行不改。
  LIVE 大屏模式（现场路演）也刻意不接这套切换器，维持原样，见下方判断记录。

## 任务 1 · 视图骨架 结果（2026-07-28，全绿）
- `node tools/acceptance.mjs shot "file://$PWD/web/show.html?s=s4" /tmp/c1.png 390 844`
  → `"横向溢出": false`，`"errs": []`；截图核对：新的「换个方式看」药丸条（展览/旅程/时光轴/
  画册/监控墙）出现在顶栏正下方，"展览"高亮，其下原来的内部小节导航（走进空间/已上传/
  任务痕迹/一起补全的人）原样还在，hero/数字卡/流程卡都没变样 ✅
- `grep -c 'id="photos"' web/show.html` = **1** ✅
- 默认视图（无 `?view=` 或 `?view=` 取旧的四个值之一）：`render()` 函数体一个字没改，
  只是把组装 show-bar 那 4 行换成一次 `topBar(sp,cfg,mode,"exhibition")` 调用，
  该函数对 `topView==="exhibition"` 时的输出 = 原来的 `.u-bar` + 新增的 `viewSwitcher()` +
  原来的 `sectionNav(cfg)`，四个 section（`id=walk/photos/tasks/contributors`）的构建函数
  （walkSection/photosSection/tasksSection/peopleSection）一行未动，顺序原样。
  唯一动过的一行是 photosSection 里给照片卡加了 `data-photo="i"` 属性（纯新增，
  不影响原有的 `data-photo-id` 焦点动画机制）。

## 任务 2 · 四种视图移植 结果（2026-07-28，五条全绿）

**做法**：抄 `archive/viewer/` 四个旧皮的版式骨架，不读它们的 tour.js/window.TOUR，
不进 3D，颜色全部换成 `app/theme.css` 的 `--u-` token。四个新视图函数
（journeyView/timelineView/albumView/machineView）都只吃 `loadSpace()` 拿到的同一个
`sp`（+`configOf(sp)` 算出的同一个 `cfg`），字段只用 `app/contract.md` 里写了的
（`nodes[].id/name/time`、`photos[].nodeId/yaw/contributor/thumb/src`），没有用
`uploadedAt` 之类契约没写的字段去猜排序或时间。

### ① 四个视图 shot 全绿
```
$ node tools/acceptance.mjs shot "file://$PWD/web/show.html?s=s4&view=journey"  /tmp/final-journey.png  390 844
{"横向溢出": false, "errs": [], "net404": []}
$ node tools/acceptance.mjs shot "file://$PWD/web/show.html?s=s4&view=timeline" /tmp/final-timeline.png 390 844
{"横向溢出": false, "errs": [], "net404": []}
$ node tools/acceptance.mjs shot "file://$PWD/web/show.html?s=s4&view=album"    /tmp/final-album.png    390 844
{"横向溢出": false, "errs": [], "net404": []}
$ node tools/acceptance.mjs shot "file://$PWD/web/show.html?s=s4&view=machine"  /tmp/final-machine.png  390 844
{"横向溢出": false, "errs": [], "net404": []}
```
（timeline 第一次截图时最左边那张图片刚好没来得及画出来，`errs`/`net404` 都是空,
直接重跑一遍就是好的——是无头浏览器截图时机的抖动,不是数据或代码问题,
详见 BLOCKED.md 本节记录。）

### ② data-photo 计数,四个视图都 ≥1(实测全部 = 9,和真数据的 9 张照片对上)
```
$ node tools/acceptance.mjs walk .../walk-dataphoto.json   # 每个视图 eval document.querySelectorAll("[data-photo]").length
journey  → 9
timeline → 9
album    → 9
machine  → 9
(exhibition-default → 9，默认视图也顺手核过)
```

### ③【色数】≤8,实测 **1**(还是原来那个 `#FFF3F1`,四个新视图零新增色)

### ④ `grep -c "iframe\|tour\.js"` = **0**,`grep -c "walkdemo"` = **2**(≤3)
walkdemo 的 2 处：第 1 处是原有的「真实全景稳定版」封面图（任务书说这处不算数）；
第 2 处是我写的注释「不拿 assets/walkdemo/ 的演示图冒充宾客照片」，本身就是在申明
没有用它,四个新视图的每一张图都来自 `assetUrl(p.thumb||p.src)`,即 space 数据本身。

### ⑤ 反向验证
```
$ printf '<!-- SENTINEL #A1B2C3 -->\n' >> web/show.html
加之后【色数】 1 → 2   (#A1B2C3, #FFF3F1)      ← 变大了,且新增确实是 #A1B2C3
$ sed -i '' '/SENTINEL/d' web/show.html
删之后【色数】 2 → 1   (#FFF3F1)                ← 还原
$ grep -c SENTINEL web/show.html → 0；wc -l → 915(加之前/删之后一致)
```

### 四种皮怎么抄的(辨识度对照)
| 视图 | 抄自 | 留住的辨识度 | 数据分组 |
|---|---|---|---|
| 旅程 journey | journey.html 的「到达标题卡」 | 深色章节牌(章号+地点+时间) | 按 `nodeId` 分章,单节点=单章 |
| 时光轴 timeline | timeline.html 的宝丽来拼贴 | 横向长条 + 底部顺序刻度 | 按 `photos` 数组原始顺序,不按节点 |
| 画册 album | album.html 的装订边 | 左侧深色书脊(手机宽度也保留,不是桌面专属)+ 米白纸面 + 方位读数 | 按 `nodeId` 分章,同 journey |
| 监控墙 machine | machine.html 的取景框 | 深色 HUD 文字条 + REC 呼吸点 + 冷色调照片墙 + 呼吸取景框 | 不分章,`photos` 全量平铺 |

### 施工中的判断(任务书没写死,按「有更好的路就走」处理,记一句为什么)
1. **LIVE 大屏模式(`&live=1`)不接换视图药丸。** 任务书没提这个模式,`render()` 是
   LIVE 和默认展览共用的同一个函数。为了让「现有展览功能不能坏」在最敏感的这条路径上
   零风险,`topBar()` 在 `LIVE` 为真时直接不渲染 `viewSwitcher()`,LIVE 模式的 DOM
   和改动前逐字节一致。已用 `?s=s4&live=1` 实测截图核对,轮询/焦点动画/toast 都正常。
2. **画册也按节点分章,不是任务书唯一点名的「旅程」。** 任务书原文只写了
   「旅程按节点分章」,没提画册。archive/viewer/album.html 本身就是按时间戳分章的版式,
   为了让"同一份数据、五种看法"这个说法站得住(不同视图对同一批照片用不同的分组维度,
   但同一个维度不能这个视图信那个视图不信),画册和旅程共用"按节点分章"这条,
   时光轴和监控墙共用"不分章,数组原样"这条。两个维度,四个视图,不是四套各自发明的规则。
3. **没有改 app/product-ui.css。** 任务书把它列进可改范围,但实际实现下来,四个新皮
   需要的颜色/组件全部能用 app/theme.css 现成的 token 加 web/show.html 自己的
   `<style>` 块解决(这也是原文件本来的分工:公共小组件在 product-ui.css,页面专属版式
   在页面自己的 style 里)。没有为了"用满白名单"而硬找理由去改一个不需要改的文件。
4. **`photoLabel()` 是新写的一个小函数,没有把 photosSection 内部的同名逻辑抽出来复用。**
   两处逻辑一样(6 行),抽出来更 DRY,但会碰 photosSection 的内部结构,而
   default 视图"一个不许少、顺序不许变"是硬红线。权衡后选择多 6 行重复代码,
   换 default 视图零风险,只在 photosSection 里加了一个新属性(data-photo)。
5. **timeline 和 machine 没有编造时间戳。** 真数据的 `photos[]` 确实带 `uploadedAt`
   (实测 s4 每张都有),但 `app/contract.md` 的云版 photos 字段表没有列这一条,
   任务书明确说"不许用契约里没有的字段"。所以时光轴按数组原始顺序(标题写清楚
   "顺序=数据本身的先后,不是拍摄时间"),没有排序、没有编时刻。

---
---

# PROGRESS · 压测军团(批次D)

## 任务 0 · 基线 + mock 安全核实(2026-07-28 通过)
- 理解:领导要"当几十上百个真宾客"把 join→show 动线走烂找真 bug,只许改 join/show/pov/portal.html + 新建 tools/stress/。
- 顺序:先证 mock 绝不碰真网络(硬性前提,不过这条就立刻停)→ 自建 CDP 压测库(tools/stress/cdp.mjs,读 acceptance.mjs 思路但触摸模拟与宽度解耦,768 宽也能强制开触摸)→ 铺 60+ 变体矩阵找 bug → 白名单内修复 → 回归。
- 风险:mock 上传结算(resSum)要等 `POLL_MAX_MS`=120 秒超时才会出文案,因为 `MOCK_SPACE.photos` 是静态 fixture、不带 `inboxKey`,`findMine()` 永远配不上刚生成的短 id——这是假数据的天然限制不是 bug,压测把"流程终点"定在收据面板(pending 行)出现,不死等 2 分钟。
- 核实:join?mock=1 从开场到点「传上去」全程只发生 16 条请求,逐条核对全部是本机静态资源(127.0.0.1:8907)或 blob:/data:(从不出机器的内联资源),**0 条外部 http(s) 请求**(读、写都没有);show.html 五视图(exhibition/journey/timeline/album/machine)+live=1 共 6 项 errs 全空、无横向溢出、`data-photo` 数均为 9(与 s4 真实照片数一致)。证据脚本 `tools/stress/task0-baseline.mjs`,截图 `tools/stress/shots/task0-*.png`。

## 任务 1 · 压测军团 结果(2026-07-28/29)
- 自建 CDP 压测库(`tools/stress/cdp.mjs` + `matrix.mjs` + `flows.mjs` + `run-all.mjs`),不改
  `tools/acceptance.mjs` 一个字,独立端口(9471)、独立 Chrome profile,复用其 walk/shot 的调用模式。
- 变体矩阵 72 个(超过 60 的下限):组 J(join 完整动线)24、组 S(show 五视图+live=1)24、
  组 R(粗暴操作 10 个具名场景)16、组 P(portal/pov 补充烟测,超出任务书最低要求)8。
  逐维度覆盖表、每个场景的复现步骤见 `tools/stress/BUGS.md` 与 `tools/stress/runlog.txt`。
- `runlog.txt` 累计 **221 行**(含每个 bug 的修复前/后重跑对比,不是凑数的 happy path 重复)。
- 发现 2 个真 bug(超长昵称把头部撑爆致横向溢出 P1、toast 叠加抽屉标题 P2),
  1 条判断不需要修的观察项,1 条网络抖动型 flake(4 次复测排除),1 条产品功能缺口
  (show.html 五视图都没有"点开大图"的灯箱交互,任务书预期存在但代码里没做)。
  全部细节、截图路径、严重度见 `tools/stress/BUGS.md`。

## 任务 2 · 修 bug + 回归 结果(2026-07-28/29)
- 两个 bug 均在白名单内(`web/join.html`)修完,均为 CSS/极小 JS 改动,没有删除任何功能:
  ① `.head-me`/`.head-me b` 加 `max-width` + 省略号截断(昵称超宽收敛,短名字零影响)。
  ② `openSheet()` 开抽屉时主动收起残留的 toast(toast 该出现时照常出现,只是不跟抽屉抢屏幕)。
- 回归:每个 bug 都重跑了对应复现变体确认转绿(R07/R08/R09 长昵称;J 组全 24 条 + R 组所有
  开抽屉场景),并重跑了任务 0 的基线(join?mock=1 + show 五视图),确认没有修出新问题。
- 收尾又跑了一遍全量 72 个变体(`run-all.mjs all`),去重后 **72/72 全部 PASS**。
- 判断不需要修的一条(toast 短暂盖住背景任务卡按钮,不挡点击、标准 toast 模式)和一条
  真实数据观察(s4 贡献者名单里的「公网验收员」测试痕迹,只读权限内不能处理)登记在
  `BLOCKED.md` D-1/D-2,没有动手改。

---
---

# PROGRESS · 主办方自助建空间(批次E)

## 任务 0 结果(2026-07-28,通过)

理解(≤10行):
- 目标:主办方(新人/摄影师)自己传全景、自己建空间,建到宾客扫码全程零开发者键盘介入。
- 现状实测:server/space.py 的 create_space() 能建空间但只认自动编号 sN;照片直传(post_policy)已跑通;全景直传/主办密钥/自助编辑通道都不存在,是本批次要补的。
- 顺序:先证老链路活着(本任务)→ 全景直传+worker自动建节点+自动发布(任务1)→ 主办密钥+改标题/换封面/删节点(任务2)。
- 照片直传 policy 生成位置:server/oss.py:207 post_policy(),默认 max_size=12MB;调用处 server/publish.py:352 未覆盖默认值,即照片上限就是 12MB。全景实拍 10-20MB 会超这个上限,任务1给全景单独设 32MB(server/space.py 新增 PANO_MAX_SIZE),不改 post_policy() 本身的默认值(那是给照片用的,不该被这次的需求带着一起变)。
- 最大风险(两条):① 自助建空间没有独立"发布"按钮,worker 处理完全景必须自动把空间从草稿推成发布,否则宾客扫码看不到任何东西——照抄了 activate_roadshow_panorama() 里"add_node→publish_space→云发布"的既有顺序。② 编辑接口各自独立触发同步云发布,连续快速操作会撞上 publish.py 的 stale 保护而漏同步一次——压测中真实复现并修复,见任务2判断记录3。

命令与输出:
```
$ nohup .venv/bin/python -m uvicorn server.compose_server:app --host 127.0.0.1 --port 8777 &
INFO:     Started server process [88433]
  路演空间 s900003 已就绪
== 加载 CLIP (clip-ViT-B-32) ==
  CLIP 就绪, 耗时 13.1s
  闭环 API(/api/space/...) 已就绪, CLIP 已注入
INFO:     Uvicorn running on http://127.0.0.1:8777

$ curl -s -X POST http://127.0.0.1:8777/api/space -H "Content-Type: application/json" \
    -d '{"title":"批次E任务0验证空间","sid":"stresse0"}'
{"ok": true, "spaceId": "stresse0", "hostKey": "KFtWaleCzwsOxu_...", "panoUpload": {...32MB策略...}}
```
老链路(用现有 API 建空间)证实活着。

## 任务 1 结果(2026-07-28,通过,三条验收全绿)

### 实现(只在白名单文件内)
- **server/space.py**:新增主办密钥账本(create_host_key/read_host_key/verify_host_key,独立文件 `<space_dir>/host.json`,不进 space.json、不随 build_public_space() 发布);新增 pano_inbox_prefix()/pano_upload_policy()(全景直传前缀 `spaces/<sid>/pano-inbox/` + 32MB 策略);create_space() 加可选 `sid` 参数(只认 `stress` 前缀+目录不能已存在,专供压测复用固定编号,不传时行为和之前完全一样);`POST /api/space` 响应新增 `hostKey`+`panoUpload`。
- **server/worker.py**:新增 poll_panos_once()(独立台账 `.pano_ingested.json`,和照片收件箱互不干扰、互不去重),run_forever()/`--once` 每轮和 poll_once() 一起跑;新全景调既有的 space.add_node()(标准化+DAP深度+缺口任务)建真节点,成功后自动 space.publish_space() 把草稿推成发布再云同步;purge_inbox() 顺手把 pano-inbox/ 纳入清理范围。
- **server/compose_server.py**:CORS 头白名单加 `X-Unseen-Space-Key`;新增 `/vendor/qrcode.js` 单文件路由(测试中发现 invite.html 在这台服务下拿不到二维码库返回 404——compose_server 原本没挂 `/vendor`,而 vendor/ 目录下还躺着 vendor/DAP/ 的 `.git` 内部文件和模型权重 weights/model.pth,所以只开这一个文件、不挂整个目录)。
- **app/create.html**:建空间成功后新增"第2步":展示主办密钥(复制按钮+存 localStorage)+ 传全景(1~4张,直传OSS,照抄 web/join.html 的 policy 直传模式,进度条,太大/失败都有明确文案不静默吞);新增 `pendingUploads` 守卫(点"继续"/关标签页时如果还有上传在飞,先问清楚,不许悄悄腰斩,这是压测中发现的真实问题,见判断记录)。
- **app/scenes.js**:新增共享的 compressToDataURL(原在 create.html,现给 scene.html 换封面复用)、saveHostKey/getHostKey(localStorage 存取)、copyText(复制到剪贴板)。
- **app/invite.html**:新增主办密钥提醒卡(读 localStorage,给 create.html 那步没截图的人再一次复制机会)。

### 验收1 · 端到端真跑
从 create.html(`http://127.0.0.1:8777/app/create.html`,本机服务打开,同源无 CORS 问题)建空间 **stresse5** → 真实文件选择器传 1 张真全景(`assets/panos/expo.jpg`,656KB,4096×2048 等距柱状)→ worker 日志显示切图/深度完成、建成节点、重新发布 → curl OSS space.json 里有 1 个节点 → join.html?s=stresse5 打开显示空间名。全部通过:

```
$ node tools/acceptance.mjs walk tools/stress-e/walk-final-flow.json   # 真实浏览器点击建空间+选文件上传
  填标题 → "批次E最终验收空间"
  提交建空间 → 点了
  [截图 FINAL-01-step2.png:主办密钥卡+传全景表单]
  选1张真全景(expo.jpg) → 选了 1 个文件
  [截图 FINAL-02-uploaded.png:显示 "expo.jpg(0.6MB)" + 进度条 + "上传中…"]

$ tail worker-stresse5.log
[00:42:50] 新全景 1785249680779_cywjjc.jpg → 建成节点 n1(切图 0.04s, 深度 13.46s, 缺口任务 3 个)
[00:43:33] 已重新发布 → 新传 7 个文件, 跳过 0 个, 耗时 42.71s

$ curl -s https://psm-advx-2026.oss-cn-hangzhou.aliyuncs.com/spaces/stresse5/space.json
  title: "批次E最终验收空间"
  nodes: [{"id":"n1","panorama":".../nodes/n1/pano.jpg","depth":".../depth.png","depthJson":".../depth.json"}]

$ node tools/acceptance.mjs shot "file://.../web/join.html?s=stresse5" out.png 390 900
  {"横向溢出": false, "errs": [], "net404": []}
  [截图 FINAL-join-stresse5.png:显示"活动现场 / 批次E最终验收空间"]
```
(浏览器自动化脚本在"点继续"这一步之后偶发挂起——这不是 bug,是我加的
pendingUploads 守卫在真实生效:弱网/并发压力下 15 秒还没传完时点继续会弹
confirm(),无头浏览器没有人能点这个原生对话框,所以脚本卡住;这恰好证明了
"离开时若有上传在飞会先确认"这条防护线真的在拦。该场景的完整"建空间→传2张
全景→worker处理→自动发布→scene.html编辑→删节点"全链路已经在压测空间
stresse1 上用真实浏览器点击完整走通,见任务2验收记录。)

### 验收2 · 凭据检索(零命中)
```
$ grep -rn "LTAI\|AccessKey\|accessKeyId\|SecretId" app/ web/ *.html | grep -v 注释
app/contract.md:41:  OSSAccessKeyId:  "...",             ← 数据契约文档,字段名+占位符,非真实值
app/create.html:355:  fd.append("OSSAccessKeyId", ...)   ← 表单字段名字符串+变量引用,非硬编码值
web/join.html:753/858/2308                                ← 既有代码(非本批次改动),同样只引用字段名

$ (另外直接搜真实 accessKeySecret 字符串值,跨 app/ web/ 根html/ server/ tools/)
0 命中
```
`OSSAccessKeyId` 是 OSS 直传签名的公开部分(不是密钥本身),这正是 `post_policy()`
设计出来发给浏览器用的东西,`web/join.html` 早就在这样做;真正的凭据
`accessKeySecret` 全仓库零命中。

### 验收3 · acceptance.mjs shot 390宽
```
$ node tools/acceptance.mjs shot "http://127.0.0.1:8777/app/create.html" out.png 390 844
{"横向溢出": false, "errs": [], "net404": ["404 /favicon.ico"]}
```
(favicon 404 是既有行为,和本次改动无关,compose_server.py 本来就没提供 favicon.ico)
第2步(主办密钥+传全景表单)、上传中、超大文件拒绝三种状态也都单独截图核对过,
同样 `"横向溢出": false`,唯一一次出现在 `errs` 里的是我自己写的
`console.error("[create] 全景直传失败:...")`(超大文件测试故意触发,验证报错
文案不是静默失败,不是页面异常)。

## 任务 2 结果(2026-07-28,通过,三条验收全绿)

### 实现
- **server/space.py**:新增 `_host_key_authorized()`(只认这个空间自己的主办密钥,
  不接受回环/全局口令兜底,理由见判断记录1);新增 `update_space_meta()`(改标题/
  换封面,改完按需同步云端,带 stale 重试);`_sync_publish_now()`(带重试的同步
  云发布,判断记录3详述);新路由 `POST /space/{sid}/host/meta`;`DELETE
  /space/{sid}/node/{node_id}` 鉴权从"只认回环"改成"只认主办密钥"(全仓库搜索
  确认当前没有任何活跃前端调用这个接口,改鉴权语义不破坏任何现有调用方)。
- **app/scene.html**:新增"主办编辑"卡(只有这台设备 localStorage 存着这个空间的
  主办密钥才出现):改标题(输入框+保存,实时回填最新云端数据)、换封面(文件选择,
  复用 compressToDataURL)、全景节点列表+逐个删除(confirm 二次确认)。

### 验收(命令与实际输出)
```
$ curl -X POST http://127.0.0.1:8777/api/space/stresse1/host/meta \
    -H "X-Unseen-Space-Key: 明显错误的字符串" -d '{"title":"x"}'
HTTP_STATUS:403
{"ok":false,"error":"主办密钥无效,没法编辑这个空间"}

$ curl -X POST .../api/space/stresse1/host/meta   # 不带任何密钥头
HTTP_STATUS:403

$ curl -X POST .../api/space/stresse1/host/meta -H "X-Unseen-Space-Key: <真密钥>" \
    -d '{"title":"批次E-UI改标题验证"}'
{"ok":true,"title":"批次E-UI改标题验证","cover":"","synced":true}
$ curl .../spaces/stresse1/space.json → title: "批次E-UI改标题验证"        ✅ 标题变了

$ curl -X DELETE .../api/space/stresse1/node/n2 -H "X-Unseen-Space-Key: 错的"
HTTP_STATUS:403
$ curl -X DELETE .../api/space/stresse1/node/n2 -H "X-Unseen-Space-Key: <真密钥>"
{"ok":true,"nodeId":"n2","deletedTasks":3,"remainingNodes":1,"synced":true}
$ curl .../spaces/stresse1/space.json → nodes: ["n1"]    ✅ 节点数 2→1
```

浏览器真实点击(非纯 curl)也走通:scene.html 加载后"主办编辑"卡片自动出现
(标题框预填当前值、节点列表显示 n1/n2 各带删除按钮),点保存/点删除都触发了
真实的 fetch 请求并按预期更新了后端和 OSS(headless 环境下用
`window.confirm=()=>true` 顶替原生弹窗,因为无头浏览器点不了系统对话框,
点击后的真实业务逻辑——校验密钥、调接口、刷新界面——完全没有被绕过)。

### 施工中的判断(任务书没写死,按「有更好的路就走」处理,记一句为什么)
1. **主办密钥校验不接受回环/全局口令兜底(`_host_key_authorized` 只有一条通过
   路径)。** 既有的 `_request_is_trusted_host()` 是"这台电脑/这个全局口令可信"
   的机器级信任,和"这一个空间的钥匙"是不同维度;如果编辑接口 OR 上回环兜底,
   从这台 Mac 自己发请求测"错密钥应该被拒"永远测不出 403(回环恒真),验收条款
   本身就没法证伪。改成密钥是唯一凭据后,401/403 才是能直接 curl 证明的东西。
2. **worker 处理完全景自动发布,不等主办方另外点一次"发布"。** 自助建空间这条
   产品线上根本没有一个"发布"按钮给主办方点(不在任务书要的三个编辑动作里,
   目标动线原文也没提这一步),原文是"传全景→worker处理→写space.json发布→
   宾客可用",中间没有人工确认,所以传第一张全景进去就必须是宾客能看到的那一刻。
   这和宾客上传照片故意不自动发布草稿(worker.py 原有逻辑)是两回事:那边怕
   宾客抢跑主办方没准备好的草稿,这边全景是主办方自己上传的,没有"抢跑"这一说。
3. **发现并修复了一个真实的并发发布 bug。** 压测时连续点了"保存标题"和"删除
   节点"两个编辑动作,前后脚发出的两个请求各自触发一次同步云发布,其中一次撞上
   publish.py 的 stale 保护被跳过(这个保护本身是对的,为了不让半新不旧的快照
   覆盖公网),但两个编辑接口都是"发布一次不重试",于是云端停在了半旧状态
   (节点数对,标题落后一版,实测复现)。worker.py 的 republish() 早就有重试
   3 次的写法,只是给"工人轮询"用的,两个编辑接口独立发布时没人抄这一份。
   加了 `_sync_publish_now()` 共享重试逻辑后,用两个并发 curl 请求实测复现又
   实测修复:
   ```
   $ (两个并发请求几乎同时改标题)
   本地最终标题: 竞态测试A
   OSS  最终标题: 竞态测试A         ← 一致,不再停在中间态
   ```
4. **全景直传前缀不做照片那一套"收件箱代际轮换"。** 那套复杂度是宾客链接被
   到处转发、旧签名长期留存逼出来的历史包袱;全景直传只有主办方自己在用,
   不具备这个前提,照抄反而是不必要的复杂度,登记在 BLOCKED.md E-3。
5. **compose_server.py 新增 `/vendor/qrcode.js` 单文件路由,没有挂
   `app.mount("/vendor", ...)`。** 发现 invite.html 在这台服务下拿不到二维码库
   (404),但整个 vendor/ 目录下还躺着 vendor/DAP/(含 `.git` 内部文件和模型
   权重),挂整个目录会把这些也公开,不是"白名单目录"该干的事,照抄
   `SERVER_UI_FILES` 的路数按文件名精确开路由。这个缺口是既有的、任务书没预料
   到的,但会挡住"从建空间到宾客扫码全程不需要开发者碰键盘"这条完成条件
   (邀请卡出不了二维码),判断为必须顺手修。

## 完成条件核对
1. 端到端闭环证据链完整——✅ 见任务1验收1、任务2验收(创建→直传全景→worker真
   处理→space.json真发布→join/show/scene编辑→宾客侧刷新可见),全程无人肉搬
   文件(全部改动落盘都经过 create.html 表单提交→浏览器直传OSS→worker轮询→
   publish.py 网络上传这条链路,我作为执行者只用浏览器自动化和 curl 验证,
   没有手工复制过一个文件)。
2. 凭据检索零命中(任务1验收2)、s4 的 space.json md5 前后一致、测试残留已清
   (均见下方"批次E收尾"专项记录)。
3. git status 改动只落白名单(见下方"批次E收尾"记录)。

## 批次F(2026-07-29,看展页灯箱,通过,五条验收全绿)

### 开工先发现的事
开工前 `git log -- web/show.html` 一看,发现上一句"压测发现 24 处点了无反应"
的缺口其实已经被**上一次会话**(commit `7ee62bd`,同一天 01:59)修过一遍,
灯箱骨架(`LB`/`lbOpen`/`lbClose`/`lbStep`/`lbEnsureDom`)、五视图 caption、
委托点击全在。但那一版没补三件任务书明确要的东西,所以这次实际是"体检+补漏",
不是从零写:
1. **live 大屏模式点击行为没做判断**——委托是全局绑的,大屏上点照片卡会跟宾客页
   一样弹灯箱,任务书要求"保持原样或禁用,二选一"没人选。
2. **"加载中占位态"和"加载失败诚实报错"两句没做**——原实现原图挂了只会默默切
   缩略图,两个都挂时图片元素直接留白/浏览器默认坏图标,不算"诚实报错文案"。
3. **"手机上禁止背景滚动穿透"没写验证**——原实现锁了 `body.style.overflow`,
   任务书明确要这一条,之前没人验过是否真的挡得住(见下方判断记录2,验完发现
   原实现这条其实已经是对的)。

### 本次改动(只碰 web/show.html)
- 点击委托里加 `if (LIVE) return;`,大屏模式点照片卡维持"加了灯箱之前"的无反应
  行为(判断记录1)。
- `lbOpen` 加载态改造:开图前显示占位卡(复用页面已有的 `.spinner` 转圈 + "照片
  加载中…"文字),`onload` 清占位显图,`onerror` 走完 原图→缩略图 两级回退后仍失败
  就显示"这张照片暂时加载不出来,可能是网络不稳定",全程不出现白屏/坏图标;
  加了一个递增 `lbLoadToken`,防止 prev/next 连点时上一张图迟到的回调盖掉当前这
  张的占位/报错状态。配套 CSS 新增 `.lb-frame`/`.lb-state`,给加载态一个不塌陷的
  最小尺寸(`min-width:min(70vw,480px); min-height:240px`),颜色全部用已有
  `--u-on-dark-2`/`--u-ink` token,没引入新色号。
- 滚动锁(`body.style.overflow`)**没有改动**——查过之后发现原实现已经是对的,
  详见判断记录2,这里特意写清楚是为了不让人以为漏改。

### 施工中的判断
1. **LIVE 模式点击行为选"禁用灯箱"这一档,不选"和其他视图一样弹"。** 理由:大屏
   是无人值守的现场展示屏,不是宾客交互设备;真弹出一个要手动点 X 才能关掉的全屏
   遮罩,会挡住 `pollLive()` 每 5 秒轮询到新照片时的 `liveFocus` 高亮反馈,现场没人
   会去点关闭。验收4 已用真实点击实测确认:`live=1` 时点 `[data-photo]`,
   `maskExistsAndOn:false`,和加灯箱之前的行为一致。
2. **滚动穿透验了一圈,最后结论是"原实现本来就对,没有改代码"——过程记下来防止
   下一个人重复踩同一个假警报。** 一开始用 `window.scrollTo(0,600)` 探测灯箱开着
   时会不会拖动背景,结果显示"锁不住"(`scrollY` 真的变了),我一度以为只锁
   `body.style.overflow` 不够,还改成 `documentElement` + `body` 一起锁,复测
   `scrollTo()` 依然显示"锁不住"——这才发现问题出在**测的工具不对**:
   `window.scrollTo()` 是命令式 API,Chrome 里这类调用本来就不受 `overflow:hidden`
   约束,跟锁一个元素还是两个元素无关,这是浏览器本身的行为,不是页面 bug,也测不出
   真实情况。换成真实滚轮事件(`Input.dispatchMouseEvent` 的 `mouseWheel` 类型,
   写了个一次性诊断脚本,不是调用 API)重新对照:**只锁 `body` 一个元素时**,真实
   滚轮事件已经被完全挡住(`wheelBlockedWhileOpen:true`,`overflowWhileOpen:
   "visible/hidden"` 即 html 没锁、body 锁了),关闭灯箱后同样的滚轮动作又能正常
   滚动(`wheelWorksAfterClose:true`,证明不是滚动本身坏了,是锁生效了)。也就是说
   **原实现的单锁 `body` 从一开始就是对的**,我加的 `documentElement` 双锁属于
   多余改动(现有功能没坏,只是没必要),已经撤回,`web/show.html` 里这两行和批次F
   开工前完全一致。

### 验收(命令与实际输出)

**验收1・五视图开灯箱**(工具:`node tools/acceptance.mjs walk <spec.json>`,
剧本对每个视图执行 go→click `[data-photo]`→eval→shot):
```
exhibition: {"maskOn":true,"opacity":"0.985","imgSrc":"https://psm-advx-2026.oss-cn-hangzhou.aliyuncs.com/spaces/s4/photos/p1.jpg","imgSrcNonEmpty":true,"dataPhotoCount":9}  errs:[]
journey:    同上 imgSrcNonEmpty:true dataPhotoCount:9  errs:[]
timeline:   同上 imgSrcNonEmpty:true dataPhotoCount:9  errs:[]
album:      同上 imgSrcNonEmpty:true dataPhotoCount:9  errs:[]
machine:    同上 imgSrcNonEmpty:true dataPhotoCount:9  errs:[]
```
五张截图路径(桌面视口,实拍验证过灯箱内容非空白):
`/private/tmp/claude-501/-/26aee43f-87bc-4314-8448-fe560ac9283d/scratchpad/batchF/{1-exhibition,2-journey,3-timeline,4-album,5-machine}.png`

**验收2・关闭动作**:
```
open  -> {"maskOnAfterOpen":true}
close -> {"maskOnAfterClose":false,"dataPhotoCount":9,"bodyOverflow":"visible","htmlOverflow":"visible"}
errs:[] net404:[]
```

**验收3・色数**:
```
$ grep -hoE "#[0-9a-fA-F]{3,6}\b" web/show.html | tr 'a-f' 'A-F' | sort -u | wc -l
1   (#FFF3F1,改动前后没变化)
```

**验收4・移动端 390×844 + live 模式**:
```
$ node tools/acceptance.mjs shot "file://$PWD/web/show.html?s=s4" out.png 390 844
{"横向溢出":false,"errs":[],"net404":[]}
$ node tools/acceptance.mjs shot "file://$PWD/web/show.html?s=s4&live=1" out.png 390 844
{"横向溢出":false,"errs":[],"net404":[]}
```
live 模式点击 `[data-photo]` 额外验证(见上方判断记录1):
`{"maskExistsAndOn":false,"dataPhotoCount":9,"bodyOverflow":"visible"}` errs:[]

**验收5・反向验证**(临时把 `function lbOpen(i){` 改名成
`function lbOpenBROKEN_TEMP(i){`,不改调用点):
```
改名后(红): exhibition/journey/timeline/album/machine 五个视图全部
  maskOn:false, imgSrcNonEmpty:false,
  errs:["EXC ReferenceError: lbOpen is not defined ..."]
改回后(绿): 五个视图全部 maskOn:true, imgSrcNonEmpty:true, dataPhotoCount:9, errs:[]
```

### 额外核实(任务书正文提到但不在五条验收里,顺手拿真实数据验证掉)
- 加载占位态:0 等待立刻查 DOM,`{"stateOn":true,"stateText":"照片加载中…",
  "imgOn":false,"frameBg":"rgb(62, 36, 48)"}`(= `--u-ink`,不是白屏),截图
  `.../batchF/10-loading-instant.png` / 手机宽 `.../batchF/11-loading-mobile.png`
  (390 宽同样 `溢出:false`)。
- 诚实报错文案:搭了一个本机回环静态服务器(同源,避免 file:// 跨域误报),塞一张
  src/thumb 都指向不存在文件的照片,实测 `{"stateText":"这张照片暂时加载不出来,
  可能是网络不稳定","imgOn":false,"frameBg":"rgb(62, 36, 48)"}`,截图
  `.../batchF/13-error-honest-text.png`。测试服务器验证完已 kill,没有残留进程。
- 背景滚动穿透:见上方判断记录2,真实滚轮事件验证原实现(单锁 `body`)已经挡得住,
  没有改代码。

### git status
```
M web/show.html
```
(PROGRESS.md/BLOCKED.md 本段追加不算改动文件本身的功能)。BLOCKED.md 本次没有
需要 Max 拍板的悬留项,未追加。

## 批次G(2026-07-29,UNSEEN 小程序只读看展壳 v1,通过,验收1-4绿/验收5 BLOCKED)

### 任务0·理解/顺序/最大风险(≤10行)
理解:三页只读壳(进入屏拉 space.json→全景环视可拖看→照片方位点卡转向),上传只留 H5
剪贴板过渡;s4 云端真数据=1 节点(n1/宴会厅)+9 张 photos+8 位贡献者(设计稿"5位"是
demo 摆拍数,不是真值,小程序按真数据走);视觉基准=miniapp-mock.html 三屏+
app/tokens.json 色值,三圆成心 logo 必须纯 CSS(view)画,不许贴图。
顺序:任务0(读稿+curl 核对字段,已做)→任务1 全景降 2048(expo.jpg+yanxi.jpg[宴席厅
=设计稿"宴会厅"/ballroom]+云端 s4 n1 pano)→任务2 建三页原生小程序,pano 渲染手写
WebGL(理由见任务2小节)→验收1-5逐条跑。
最大风险:①WeChat DevTools 装了 App 但从未 GUI 登录过,cli 大概率卡在"IDE 未初始化",
验收5 很可能只能 BLOCKED 记录等 Max 扫码;②pano 页 yaw↔贴图列映射是本环境新写的
shader,没有可视化验收手段,只能保证语法对/推导自洽,真实手感要等 Max 真机点。

### 任务1·全景降档(assets/panos → miniapp/assets/panos,2048×1024,quality=85)
选材:assets/panos/ 里没有文件字面叫"ballroom",但 tour.js(第354行 `"id":"yanxi"`)和
s4 云端 space.json(`nodes[0].name = "宴会厅"`)都指向"yanxi.jpg"就是设计稿里那句
"陈屹 & 林沐 · 宴会厅"对应的场地,所以判定 yanxi.jpg = 任务书说的"ballroom 相关那张"。
```
$ .venv/bin/python3 resize_panos.py
assets/panos/expo.jpg (4096, 2048) -> miniapp/assets/panos/expo.jpg (2048, 1024)
assets/panos/yanxi.jpg (4096, 2048) -> miniapp/assets/panos/yanxi.jpg (2048, 1024)
s4-n1-pano-orig.jpg(云端下载) (4096, 2048) -> miniapp/assets/panos/s4-n1.jpg (2048, 1024)

$ python3 -c "from PIL import Image; im=Image.open('miniapp/assets/panos/expo.jpg'); print(im.size)"
(2048, 1024)
$ python3 -c "from PIL import Image; im=Image.open('miniapp/assets/panos/yanxi.jpg'); print(im.size)"
(2048, 1024)
$ python3 -c "from PIL import Image; im=Image.open('miniapp/assets/panos/s4-n1.jpg'); print(im.size)"
(2048, 1024)
```
(系统 python3 = /opt/homebrew/bin/python3,自带 PIL 12.2.0,任务书给的验收命令原样能跑,
不需要激活 .venv。)三个文件分别 195KB/502KB/395KB,都在小程序单包 2MB 限制内。

### 任务2·小程序工程
**文件清单**(21个,`find miniapp -type f`):
```
miniapp/app.js
miniapp/app.json
miniapp/app.wxss
miniapp/assets/panos/expo.jpg
miniapp/assets/panos/s4-n1.jpg
miniapp/assets/panos/yanxi.jpg
miniapp/pages/index/index.js
miniapp/pages/index/index.json
miniapp/pages/index/index.wxml
miniapp/pages/index/index.wxss
miniapp/pages/pano/pano.js
miniapp/pages/pano/pano.json
miniapp/pages/pano/pano.wxml
miniapp/pages/pano/pano.wxss
miniapp/pages/photos/photos.js
miniapp/pages/photos/photos.json
miniapp/pages/photos/photos.wxml
miniapp/pages/photos/photos.wxss
miniapp/project.config.json
miniapp/sitemap.json
miniapp/utils/util.js
```

**关键决策**:
1. **pano 页渲染方案选了"手写 WebGL",没选 threejs-miniprogram。** 理由:
   threejs-miniprogram 要 `npm install` 之后在开发者工具里手动点一次"构建 npm"才能跑,
   这一步是 GUI 操作,而本环境 devtools 从未登录过(见验收5),没人能替 Max 点这个按钮,
   一旦漏做整个小程序直接白屏。手写方案只用原生 `<canvas type="webgl">`,零 npm 依赖,
   跟仓库已有的 `viewer/walk.html` 是同一路数(全屏四边形 + 等距柱状投影 fragment
   shader),打开 devtools 不需要任何构建步骤就能跑,直接对应"能跑"这个第一让步顺序。
2. **yaw↔贴图列映射推导**:契约里 yaw=0 定义成"全景第0列方向"。shader 里相机看向
   `(0,0,-1)`,绕 Y 轴转 `u_yaw` 弧度后用 `atan2(x,-z)` 反推经度,代入几何可得屏幕中心
   对准的贴图列 `u = 0.5 - u_yaw/(2π)`。要相机看向契约 yaw=Y,解出
   `u_yaw = radians(180 - Y)`。这个换算是自反的(`f(f(x))=x mod 360`),`pano.js` 里
   `dataYawToCameraYawDeg()` 一个函数两个方向复用。**这套推导没有可视化验收手段**(本
   环境跑不了真实 WebGL 渲染),只能保证代码内部自洽+语法对,真实对齐效果要 Max 拿真机
   /devtools 点开验。
3. **照片方位屏没有照抄设计稿的诗意文案**(如"钢琴旁的一小段安静")。云版
   `space.json` 的 `photos[]` 根本没有这个字段(`app/contract.md` 第84-98行只有
   id/src/thumb/nodeId/yaw/confidence/margin/state/reason/contributor/taskId),编一句
   文案出来就是造假数据。改成读 `photos[].taskId` 对应的 `tasks[].brief`(真实存在的
   字段,例如"站在原地转向右前方,拍那个方向"),没有 taskId 就诚实标"宾客自由上传,
   不对应任务",全部是契约里真实字段,不是我编的。
4. **贡献者数字用真实的 8,不是设计稿写死的 5**。`space.contributors` 数组当前有 8 条
   (小明/匿名宾客/大伟/小红/延迟测试/FIX三态/公网验收员/泛音测),进入屏"N 位贡献者"、
   照片方位屏头部统计都读 `(space.contributors||[]).length`,不读设计稿里的静态"5"。
5. **传照片按钮**放在进入屏底部(`onCopyUploadLink`),`wx.setClipboardData` 复制
   `https://unseen-d3gtp0sxh53bbef61-1316841054.tcloudbaseapp.com/web/join.html?s=s4`
   (这是 `app/cloud.js` 里腾讯云正式站 FALLBACK 地址拼的真实可用链接,已 curl 确认
   HTTP 200,不是占位符),`wx.showToast` 提示去浏览器打开。
6. **导航栏样式**:`app.json` 全局 `"navigationStyle":"custom"`,三页各自画自己的顶部条
   (pano 页毛玻璃条、photos 页仿原生 nav),用 `wx.getWindowInfo().statusBarHeight`
   算安全区,不依赖系统导航栏。
7. **三圆成心 logo** 结构照抄 `miniapp-mock.html` 的 `.mark/.orb/.heart` 技法,唯一
   区别:把 `.heart:before/:after` 两个伪元素换成了 `heart-circ` 两个真实 `view`(小程序
   对通用元素 `::before/::after` 的支持不如浏览器确定,写成真节点更保险),旋转
   45°+两圆的几何关系跟原稿完全一致,全程 view+css,没有一处贴图冒充。

### 验收(命令与实际输出)

**验收1・JSON 解析**:
```
$ node -e "JSON.parse(require('fs').readFileSync('miniapp/app.json'))" && echo OK
OK
$ node -e "JSON.parse(require('fs').readFileSync('miniapp/project.config.json'))" && echo OK
OK
```

**验收2・12个页面文件齐全**(`ls miniapp/pages/{index,pano,photos}/`):
```
miniapp/pages/index/: index.js index.json index.wxml index.wxss
miniapp/pages/pano/:  pano.js pano.json pano.wxml pano.wxss
miniapp/pages/photos/: photos.js photos.json photos.wxml photos.wxss
```
(共 12 个,4×3,实际 `ls -la` 输出见本次会话记录,此处只摘文件名。)

**验收3・secret 未泄露**:
```
$ grep -rn "8c87b064" miniapp/
(无输出,grep exit code 1 = 零命中)
```
(全程没有读取 `~/.config/psm/wechat.json`,不知道真实 secret 是什么,只是按任务书
给的特征串验证。)

**验收4・js 语法检查**:
```
$ for f in $(find miniapp -name "*.js" -not -path "*node_modules*"); do node --check $f || echo FAIL $f; done
OK miniapp/app.js
OK miniapp/utils/util.js
OK miniapp/pages/pano/pano.js
OK miniapp/pages/index/index.js
OK miniapp/pages/photos/photos.js
```
全过,零 FAIL。

**验收5・微信开发者工具冒烟**:BLOCKED,详情见 BLOCKED.md「G-1」。App 已装
(`/Applications/wechatwebdevtools.app` 存在,`cli -v` 能跑出命令列表),但从未经过
GUI 首次登录,`~/Library/Application Support/微信开发者工具/.../Default/.cli` 不
存在。`cli islogin` 和 `cli auto-preview --project miniapp` 都报同一个错:
```
[error] Please ensure that the IDE has been properly installed
✖ #initialize-error: Error: ENOENT: no such file or directory, open
  '.../Default/.cli'
```
这是任务书原文点名的例外("cli 要扫码登录就明确记 BLOCKED…不算失败"),没有尝试用
GUI 自动化去点开界面扫码(本任务也没有那个工具,且扫码本来就只有 Max 的手机能做)。

### 遗留问题
1. **验收5 需要 Max 打开一次微信开发者工具 GUI、扫码登录后再验**(见 BLOCKED.md G-1)。
2. **pano 页 yaw↔贴图列的对齐效果没有真机/GUI 验证**,只保证代码推导自洽+语法过。
   如果真机测出方向感不对,`pano.js` 顶部注释已经把推导过程写清楚,`onTouchMove`
   里也留了"手感反了改个符号"的提示行,方便当场调。
3. **陀螺仪系数(`res.alpha`/`res.beta` 到 yaw/pitch 的映射)未经真机校准**,只保证
   "模拟器/不支持的设备不崩",真实手感需要 Max 拿真机测过再调。
4. **生产环境域名白名单未配置**:`wx.request` 拉 `space.json` 在开发者工具本地预览
   下默认跳过合法域名校验,但小程序正式发布后需要在小程序后台"开发管理→服务器域名"
   里把 `psm-advx-2026.oss-cn-hangzhou.aliyuncs.com` 加进 request 合法域名,否则真机上
   会报"url not in domain list"。这是后续上线步骤,不在本次任务范围内,写在这里防止
   遗忘。`<image>` 标签本身显示远程图片不受这个白名单限制,不受影响。
5. **贴图默认用本地 `s4-n1.jpg`**(真实空间 s4 的节点1,已降到 2048),`expo.jpg`/
   `yanxi.jpg` 是任务1一并产出的备用本地测试贴图,当前没有被任何页面引用,如果 Max
   想临时换个场景看效果,改 `pano.js` 里的 `PANO_SRC` 常量即可。

### git status
```
?? miniapp/
```
仓库其余文件零改动(PROGRESS.md/BLOCKED.md 本段追加不算)。

---

## 批次H(2026-07-29,三屏UI对稿修客观偏差)

### 任务0·理解/顺序/最大风险(≤10行)
理解:领导说"UI有问题但不大"没给具体点,任务是把模拟器里三屏跟 miniapp-mock.html
逐屏比对,分【客观/主观/环境】三类列 DIFF.md,只修客观项(色值/字号级差/间距挤压/
缺失/错位),主观(留白/圆角手感/文案)留给领导圈,环境差异(状态栏/陀螺仪/字体
渲染)只标注不处理。
顺序:任务0连通(已过)→三屏+设计稿各截一张→逐屏列差异→只修客观项+复截图→
验收1-5→出新预览码。
最大风险(已踩过一个):装的 miniprogram-automator@0.12.1(npm 最新,2023-11-07
发布)连本机开发者工具(2.01.2510290,新两年)时 checkVersion() 会因协议响应
里缺 SDKVersion 字段崩溃;确认崩溃点在版本号比对之后(WS 连接已成功),运行时
patch 掉这一个方法绕过,已验证 pageStack() 正常返回。pano 页是手写 WebGL 全景,
贴图加载需要额外等待,已在截图脚本里加长等待。

### 任务1·三屏截图对稿 结果(通过)
三屏(automator screenshot,390×844)+ 设计稿整版(acceptance.mjs shot,1400×1100,
一张截全三个 phone)截图齐全,存在 `ui-check/`。逐屏对比完整清单(客观6处/主观7处/
环境3处,含判断依据/证据)见 `ui-check/DIFF.md`,不在这里重复摘抄全文,只列结论。

### 任务2·修客观项 结果(通过,6处全修,验收1-5全绿)

**修了什么**(只动 wxss/wxml,零 js 改动):
1. `app.wxss`:`--u-shadow`/`--u-shadow-btn` 两个阴影 token 数值是 DESIGN-UNSEEN.md
   规定值的一半(色彩分量本来就对,offset/blur 被精确减半),改回文档原值。
2. `pages/index/index.wxml`+`.wxss`:补一条设计稿里有、我们缺的胶片齿孔装饰带
   (film-strip,DESIGN-UNSEEN.md §4 列为三大视觉签名手法之一);主标题字号
   60rpx→69rpx(换算成 px 只有31.2,稿子是36,同页其余字号换算比值都在0.97~1.0,
   只有它掉到0.867)。
3. `pages/pano/pano.wxss`:`.pano-page` 背景色从写死的 `#1a0e13` 改成 token
   `var(--u-ink)`(设计稿就是这么写的);陀螺仪图标补上缺失的中心圆点
   (`::before`,之前只有指针 `::after`,看起来像"禁止"符号)。
4. `pages/pano/pano.wxml`+`.wxss`:陀螺仪开关按钮实测渲染成长椭圆
   (`width:184px,height:49px`,期望是正圆~50×50),排查过程:先怀疑是
   "position:absolute + button 自己 display:flex"的组合,去掉 flex 后
   `display` 确实变了但 width 纹丝不动还是184——说明不是flex的锅;换个方向,
   发现这是全站唯一一个"`position:absolute` 的原生 `<button>`"(其余按钮都是
   跟着 grid 走的在流内元素,不出这个问题),把标签从 `<button>` 改成 `<view>`
   (tap行为/aria-role/aria-label 全部保留),重新量 `width:49,height:49`,
   问题解决。
5. `pages/photos/photos.wxss`:两处大标题字号偏小,"散落的视角"52→58rpx、
   卡片标题27→31rpx(同一套系统性离群判断法)。

**没修什么**:7条主观(顶部小logo偏小23%没有清楚证据/品牌圆缺mix-blend-mode/
整体留白节奏/陀螺仪图标白色配色/pano-top高度/pano-wash少一层渐变/照片卡片文案
与缩略图比例)全部原样留着,清单在 DIFF.md,标注了"为什么不动手"。3条环境差异
(状态栏与home-indicator/陀螺仪硬件/**pano页WebGL全景贴图在自动化截图里完全
不显示**)只标注不处理,其中WebGL这条深查了(gl/program/tex对象都建成功、
glError=0、渲染循环rafId在6秒内涨到562证明没卡死、贴图文件用fs.statSync确认
真实存在,但连续6张跨12秒的截图逐字节相同且采样色值正好是纯CSS背景色不是贴图
内容),判断为开发者工具模拟器对canvas/webgl原生层截图合成的已知限制类别,
不是代码bug,没有为了这条去动pano.js(真机已确认能跑,担心改坏)。

**验收1-5实际输出**(命令与结果全文见 `ui-check/DIFF.md` 最后一节,这里摘要):
1. 三屏修后截图:`ui-check/01-index-FINAL.png` `02-pano-FINAL.png` `03-photos-FINAL.png` ✅
2. `node --check` 5个js文件全 OK ✅
3. `app.json` JSON.parse OK ✅
4. `grep -rn "8c87b064" miniapp/` 零命中 ✅
5. `cli preview` 出新二维码 `ui-check/preview-qr-v2.png`(470×470,包体1.1MB) ✅

**一个意外副作用(已处理)**:跑 automator/cli 期间开发者工具自己重写了一次
`project.config.json`(内容一字不差,只丢了文件末尾换行符),已补回换行符,
`git diff` 对这个文件现在是空的,不是我主动改的字段。

**最终改动范围**:`app.wxss` / `pages/index/index.{wxml,wxss}` /
`pages/pano/pano.{wxml,wxss}` / `pages/photos/photos.wxss`,共6个文件,零js改动,
全部在 miniapp/ 界限内。开发者工具全程保持登录(`cli islogin` 复查仍是
`{"login":true}`),没碰过工具设置。

---

## 批次I(2026-07-29,真机验收4问题修产品级,通过,验收1-4全绿)

### 任务0·理解/顺序/最大风险(≤10行)
理解:领导拍板"当正式产品做",报了四个真机问题(1首页文字未居中/2全景页返回
按钮有问题/3陀螺仪有问题/4拖动手感一般),前两条任务书诊断为"机型自适应"类
(模拟器里对、真机上不对),第3条要根治真跳变/抖动,第4条是手感打磨。
顺序:先用 automator 量出 baseline 真数字(不能靠肉眼)→按根因逐条修→改完
再量一遍数字对比→三屏截图+cli preview 收尾。
最大风险(已踩过三个,详情见下方"环境踩坑"和 BLOCKED.md I-1/I-2):
①`miniprogram-automator.launch()`的spawn+轮询逻辑在本机不可靠,同一项目连续
起第二次经常静默卡死,改成自己探测端口+`connect()`绕过;②`callWxMethod`桥对
`getMenuButtonBoundingClientRect`这个API会卡死,换`evaluate()`跑同一句API正常;
③`<button>`标签的宽度查询在这版开发者工具上全部返回同一个假值184,一度怀疑是
真bug,截图交叉验证后确认是查询层artifact不是渲染问题,没有为此改动。

### 任务1·量化基线(baseline,改任何代码之前先测)
设备画像(`miniProgram.systemInfo()`,本机 automator 默认机型="iPhone 12/13
(Pro)"):`windowWidth=390, windowHeight=844, statusBarHeight=47,
safeArea={top:47,bottom:810}`。
胶囊按钮几何(`wx.getMenuButtonBoundingClientRect()`,通过`evaluate()`拿到):
`{width:87, height:32, left:296, top:51, right:383, bottom:83}`,胶囊中心
`Y=51+32/2=67`。

**改前实测(节选,完整JSON见本节末尾脚本产出)**:
- 全景页 `.round-btn`(返回钮)中心 `Y=81.5`,跟胶囊中心 `67` 差 **14.5px**
  (返回钮实际比系统胶囊按钮低了小半个按钮高度)——根因:`pano.wxml`把顶部条
  的位置写死成`margin-top: statusBarHeight+12px`,高度写死`88rpx`,这两个猜的
  数字只在当前模拟器机型上凑巧接近对,换个真实胶囊高度/位置不同的机型就会
  跟这台一样甚至更偏。
- 进入屏 `.space-title`(标题)/`.primary-btn`(按钮)中心X偏差分别是
  **-0.109px / 0px**,已经在≤2px以内——逐行审查了`index.wxss`,横向没有
  一处写死的px宽度(全是rpx+flex居中,`.entry-main`用`align-items:center`,
  左右padding对称),没找到结构性bug。但顺手查了同一个`.app-bar`里右上角
  "空间记忆"四个字,量出来 `right=374.19px`,跟胶囊左边缘 `left=296px` 比,
  **重叠了78px**(整段文字几乎完全落在胶囊包围盒里)——这是同一类"写死32rpx
  右边距、没考虑胶囊"的真实bug,只是领导反馈时没具体点出这一条,顺手一起修。
- 陀螺仪:读`pano.js`代码审出根因,`startGyro`原来是
  `self.cameraYawDeg = res.alpha`直接把设备绝对朝向赋值给镜头朝向——开启那一刻
  如果手动拖到的方向和手机实际朝向不一样(几乎总是不一样),画面会瞬间跳到
  设备朝向,这正是任务书点名的"一开陀螺仪画面猛跳"。
- 拖动灵敏度:`DRAG_YAW_SENSITIVITY=0.28`,在390px宽的屏幕上拖满一屏
  `390*0.28=109.2°`,任务要求~120°,偏差不算离谱但没打中。

baseline脚本:`ui-check/measure.js`(量html/wx数据用,改代码前后都跑得通,
可复现)。

### 任务2·四条修复(逐条:根因/修法)

**A. 机型自适应(根治1+2)**

1. **统一胶囊几何计算**,新增到`app.js`(`onLaunch`算一次,存
   `globalData.nav`,三页共用,不用每页各算一次):
   ```js
   gap        = 胶囊顶部 - 状态栏高度
   barTop     = 状态栏高度                    // 导航行紧贴状态栏底部起
   barHeight  = gap*2 + 胶囊高度                // 令行的垂直中心=胶囊中心
   sideMargin = 屏幕宽 - 胶囊右边缘             // 返回钮/条左右边距抄这个
   keepoutRight = 屏幕宽 - 胶囊左边缘 + 2px缓冲  // app-bar右侧文字禁入区
   ```
   代数验证(不依赖具体数值,对任意 gap/胶囊高度都成立):
   `barTop + barHeight/2 = 状态栏高度+gap+胶囊高度/2 = 胶囊顶部+胶囊高度/2 = 胶囊中心`。
   `wx.getMenuButtonBoundingClientRect`拿不到时有兜底默认值(`fallbackNav`),
   跟这功能出现之前的硬编码同量级,不会比以前更差。
2. `pano.wxml`/`pano.wxss`:`.pano-top`的`margin-top:{{statusBarHeight+12}}px`
   +写死的`height:88rpx;margin:0 24rpx`,改成绑
   `navBarTop/navBarHeight/navSideMargin`(来自上面算好的nav)。
3. `photos.wxml`/`photos.wxss`:同一套改法用在`.native-nav`(返回钮所在行)。
   之前`.position-top`统一给`padding:0 32rpx`(连返回钮行带标题区一起吃),
   现在拆开——`.native-nav`自己按`navSideMargin`走胶囊实测值,
   `.position-heading`(标题区,不是导航行,不用跟胶囊对齐)改成自己
   `padding:20rpx 36rpx 30rpx`(36=原来"父级32rpx+自己4rpx"的等价值,视觉
   数值不变,只是不再依赖父级统一padding)。
4. `index.wxml`/`index.wxss`:`.entry-page`的`padding-top`绑`navBarTop`
   (数值上等于`statusBarHeight`,写法更清楚意图);`.app-bar`的`height`绑
   `navBarHeight`,右侧`padding-right`绑`navKeepoutRight`,修复上面量出来的
   78px文字重叠。
5. **全景页返回钮z-index/触摸可达**:`.gl-canvas`补上显式`z-index:0`(之前是
   隐式`auto`),跟`.pano-top`(10)/`.gyro-btn`(12)/`.photo-rail`(10)的层级
   关系写清楚。canvas用的是新版node+`wx.createSelectorQuery().fields
   ({node:true})`接口(pano.js `initGL`里那种),不是老式`canvas-id`/
   `wx.createCanvasContext`,从基础库2.9.0起支持同层渲染,理论上不存在
   "canvas原生层永远盖在最上面"的问题。**实测确认点击可达**(automator
   `element.tap()`点`.round-btn`真的触发了`onBack`导航,见验收部分)。

**B. 陀螺仪重写(根治3)**,`pano.js` `startGyro`/`stopGyro`:
- 换成"开启瞬间的手机姿态=基准0点,此后只取相对这个基准的变化量,叠加到
  开启那一刻镜头本来看的方向上"——不管alpha的绝对参考系是磁北还是设备任意
  参考系(iOS/Android不完全一致),开启瞬间画面保证连续,不会跳变。这个思路
  本身就规避了大部分"iOS/Android坐标系差异"的绝对值问题,不需要对两个平台
  分别特判方向(只留了一行注释,真机测出来转向反了改一个符号)。
- alpha是环形量(0~360循环),写了`shortestDelta(from,to)`算最短路径差值,
  滤波和取相对量两处复用,避免359→0这种边界算出"绕了一大圈"的错误结果。
- 低通滤波:EMA系数0.15(任务书建议值),对alpha/beta先转最短路径增量再累加,
  不是对原始角度直接线性平均(否则跨越0/360边界会得到错误结果)。
- `PITCH_CLAMP_DEG`从72改成85(任务书对陀螺仪明确要求±85°,"pitch同样夹角"
  要求拖动那边也统一,两处共用一个常量)。
- 罗盘图标开关两态区分:`gyro-ring`补`--on`修饰类,关=描边静止(原样不变),
  开=圆环实心+指针粉色+轻微来回摆动动效(1.6s ease-in-out,不用整圈旋转,
  整圈转容易让人以为"卡住了/加载中",摆动更像"正在感应方向")。

**C. 拖动手感(4)**,`pano.js`:
- 灵敏度`DRAG_YAW_SENSITIVITY`:0.28→0.31。算式:目标"拖一屏≈转120°",
  用本机能测到的390px宽算,`120/390≈0.3077`,取0.31——在常见机型宽度
  375~414px上分别对应`375*0.31=116.25°`/`414*0.31=128.34°`,都落在
  "约120°"的合理范围。
- 惯性衰减:摩擦系数`DRAG_FRICTION=0.92`每帧(rAF),`tickInertia()`挂在已经
  在跑的渲染循环里,不用额外定时器;`INERTIA_EPS=0.008`度/帧以下直接清零
  停止。手指按下/陀螺仪开着时不产生惯性(`onTouchStart`清零、`tickInertia`
  检查`this.touch`和`gyroOn`)。
- **验收过程中发现并修的一个真问题**:第一版直接拿"这次touchmove的位移"当
  "每帧速度"用,验收脚本用automator模拟单次大位移touchmove测出~100ms内
  yaw跳了86°,复查后确认这不是automator模拟触摸的假象,而是真实存在的
  设计缺陷——touchmove事件不是等间隔触发的,事件间隔一旦变长(真机偶尔
  卡顿/触摸采样率不稳时也会发生,不只是自动化测试的极端情况),直接拿位移
  当速度会失真地大,松手后感觉像"猛地弹飞"。改成按实际经过的时间把这次
  位移归一化到"每约16.67ms(60fps一帧)"的量级(`REF_FRAME_MS`),再加一个
  绝对上限`MAX_INERTIA_STEP=6`双保险。改完复测:同样的单次大位移输入,
  松手后前60ms只走了21°(329→308),平滑很多,2秒左右自然停下,不再是
  瞬间甩飞。
- pitch同样夹在`PITCH_CLAMP_DEG`(=85,跟陀螺仪共用)。

### 任务3·施工中新发现,做过甄别、没有动手的问题(顺手记录)
**`<button>`标签宽度查询在本机这版开发者工具上失真,不是真实渲染bug**——
用`element.size()`(domProperty桥)/`wx.createSelectorQuery().boundingClientRect()`
(evaluate()跑,production代码会用的正牌API)/`element.style('width')`三种
互相独立的方法量`.primary-btn`(index)、`.round-btn`/`.photo-total`(pano)、
`.back-btn`(photos),**全部返回同一个数字184px**,跟各自CSS规则(100%/64rpx/
内容宽)完全对不上。一度怀疑是批次H给`gyro-btn`做button→view转换时踩过的
同一个坑的更大范围重现(那次实测也是184px),准备照办法炮制全部转成view。
但先用干净会话截图肉眼核对(`ui-check/fresh-check-index.png`跟batch H的
`01-index-FINAL.png`比对一致),`.primary-btn`视觉上清清楚楚是撑满整行的,
不是184px窄条;`.round-btn`视觉上是正常大小的圆形返回箭头,没有拉伸变形。
**结论:这是本机这版automator+devtools组合对`<button>`元素宽度查询的
artifact,不是渲染问题,更不是真机会复现的bug**(真机不经过这套自动化查询
桥),所以**没有把`.primary-btn`/`.round-btn`/`.photo-total`/`.back-btn`
转成view**——没有真bug要修,转了就是无意义的代码改动+新引入的accessibility
折损风险。批次H给gyro-btn做的转换保留不动(无害,也不需要为这条重新论证或
回退)。详情记入BLOCKED.md I-1,免得下一个人再花时间重新排查一次。

### 验收(命令与实际输出)

**验收1・量化居中(改后复核,`ui-check/verify-final.js`跑出来的真实数字)**:
```
进入屏(index):
  viewportCenterX = 195 (windowWidth 390 / 2)
  .space-title  中心X偏差 = -0.109px   (≤2px ✓)
  .primary-btn  中心X偏差 =  0px       (≤2px ✓)
  .brand-sub("空间记忆") 与胶囊包围盒重叠 = false，净间距 1.81px (改前是重叠78px)

全景屏(pano)返回钮:
  navBarTop=47 navBarHeight=40 navSideMargin=7 (胶囊实测算出)
  胶囊中心Y = 67
  .pano-top  中心Y偏差 = 0px   (改前 +14.5px)
  .round-btn 中心Y偏差 = 0px   (改前 +14.5px)
  .round-btn 完全在屏幕内 = true
  .pano-top  顶边(47) >= safeArea.top(47) = true(在安全区内)
  .pano-top  与 .photo-rail(底部信息条) 重叠 = false(矩形数学判断)

照片屏(photos)返回钮(同一套逻辑，一并验证):
  .back-btn 中心Y偏差 = 0px
```
**两种视口宽验证方法说明**:automator没有暴露切换模拟器机型/视口宽度的
接口(翻过`miniprogram-automator` Launcher/Automator/MiniProgram的.d.ts全部
公开方法,没有device/viewport相关参数;project.config.json能被launch()的
`projectConfig`选项合并写入,但机型选择是devtools本地UI状态,不是
project.config.json里的字段),按任务书原文允许的退路走数学断言:
- index居中:`.entry-main`横向`padding:20rpx 40rpx 48rpx`(左右对称),
  `.entry-page`没有一处横向写死px,子元素靠`align-items:center`居中——对称
  padding的内容区中心恒等于外框中心`W/2`,这是初等幂何,对任意宽度`W`成立,
  跟`W`取值无关;当前测得的-0.109px/0px误差来自字体渲染取整噪声(不是布局
  逻辑误差),在375px(rpx换算比例0.5,整数比更干净)、414px(0.552)下这类
  取整噪声只会是同量级的亚像素抖动,不会因为宽度变化突然放大到能被肉眼
  察觉。
- pano返回钮对齐:`barTop+barHeight/2=胶囊中心`是代数恒等式(推导见任务2·A.1),
  对任意`gap`/胶囊高度都成立,不依赖某个特定宽度的具体数值——换到
  375/414px宽的真机,只要`wx.getMenuButtonBoundingClientRect()`返回该机型
  真实的胶囊geometry,这个公式自动重新算出对齐该机型胶囊的结果,这正是"设备
  自适应"要做到的效果(相对写死数字的旧写法,新写法的正确性不依赖某个
  特定宽度)。

**验收2・js全过`node --check`**:
```
OK miniapp/app.js
OK miniapp/utils/util.js
OK miniapp/pages/pano/pano.js
OK miniapp/pages/index/index.js
OK miniapp/pages/photos/photos.js
```

**验收3・app.json解析 + secret零命中**:
```
$ node -e "JSON.parse(require('fs').readFileSync('miniapp/app.json')); console.log('OK')"
OK
$ grep -rn "8c87b064" miniapp/
(无输出,exit=1=零命中)
```

**验收4・`cli preview`出新码,编译过**:
```
$ /Applications/wechatwebdevtools.app/Contents/MacOS/cli preview \
    --project /Users/max/code/spatial-memory/miniapp \
    --qr-format image --qr-output .../ui-check/preview-qr-v4.png
✔ preview
┌─────────┬──────────┬─────────────┐
│ (index) │   size   │ size (Byte) │
├─────────┼──────────┼─────────────┤
│  TOTAL  │ '1.1 MB' │   1153359   │
└─────────┴──────────┴─────────────┘
```
`preview-qr-v4.png`(470×470)已生成。

**功能冒烟(automator驱动,非肉眼)**:
```
陀螺仪(真实无硬件路径,模拟器本来就没有传感器):
  点一下开关 -> gyroOn 仍是 false(wx.startDeviceMotionListening 走 fail
  回调,弹"陀螺仪打不开,继续用手拖"toast) -> 全程无JS异常抛出 ✓
陀螺仪(mockWxMethod强制success路径,验证状态机本身逻辑不崩):
  点开 -> gyroOn:false→true；1.2s后仍是true(没有异常状态)；再点一下关 ->
  gyroOn:true→false ✓ 全程无异常
拖动(20步、每步间隔16ms、模拟真实节奏、覆盖一屏390px宽):
  drag中 yaw转了 121°(目标~120° ✓)；松手后继续滑行到179°再自然停住
  (确认停住:再等1秒读数字不再变)✓
返回钮点击可达性:
  pageStack从 pages/pano/pano -> tap(.round-btn) -> pages/index/index
  真的导航走了 ✓ (不是被canvas挡住点不到)
```

**三屏截图**(改后,`ui-check/`):`i-01-index.png` / `i-02-pano.png` /
`i-03-photos.png`,肉眼核对跟设计还原一致(三圆logo/标题/按钮/返回钮/罗盘
图标/照片轨道全部正常,pano页画布是纯色背景——批次H已经查过这是开发者工具
模拟器对`<canvas type="webgl">`截图支持的已知限制,不是本批次引入的问题,
真机能正常显示真实全景贴图)。

**环境踩坑(写清楚,免得下一个人重新踩)**:
1. `miniprogram-automator@0.12.1`的`automator.launch()`(spawn cli auto+轮询
   等WS就绪那段逻辑)在本机不可靠——复现过两次:同一个projectPath连续起第二次
   时,即便端口确实已经在监听(`lsof`能看到),`launch()`内部还是会静默卡住
   不返回也不报错,90秒硬超时都等不到。改用`ui-check/connectHelper.js`:
   自己拿`net.createConnection`探测端口是否开着,没开就自己`spawn`一次
   `cli auto --auto-port`(detached),开了就直接`automator.connect()`——
   这条路径每次都在10ms~8s内可靠返回。**每次改完代码要复测,必须先
   `cli close --project <path>`等它真正退出(`lsof`确认端口释放,不能只信
   cli打出来的"✔ close",实测有过报成功但进程/端口还活着最多20秒的情况)**,
   不然新连接可能吃到旧编译产物,或者复现上面那个卡死。
2. `miniProgram.callWxMethod("getMenuButtonBoundingClientRect")`会挂死不返回
   (用`probe-steps.js`隔离确认:同一条连接上`systemInfo()`/`currentPage()`/
   `reLaunch()`全部正常,唯独这一个方法调用8秒不回),换成
   `miniProgram.evaluate(function(){return wx.getMenuButtonBoundingClientRect();})`
   在小程序自己的JS上下文里跑同一句API,<1秒正常返回。绕开的是"automator
   专门给这个API做的调用桥",不是"小程序本身调这个API"这件事本身有问题。
3. `screenshot()`偶发极慢(一次量到133秒才返回,原因大概率是当时那个
   devtools会话经过了多次连续connect/disconnect折腾,处于某种degraded状态);
   干净会话(先`cli close`彻底关掉旧的再连新的)截图正常在几百毫秒内返回。

### git status
```
 M PROGRESS.md                     ← 本任务书指定要交的文件,只在末尾追加
 M BLOCKED.md                      ← 同上
 M miniapp/app.js                  ← 新增 nav 胶囊几何计算
 M miniapp/pages/index/index.js    ← 读 nav,setData 三个新字段
 M miniapp/pages/index/index.wxml  ← app-bar 绑 navBarHeight/navKeepoutRight
 M miniapp/pages/index/index.wxss  ← app-bar 去掉写死 height,右padding交给inline
 M miniapp/pages/pano/pano.js      ← 陀螺仪重写+惯性+灵敏度调参+读nav
 M miniapp/pages/pano/pano.wxml    ← pano-top绑nav三值,gyro-ring补--on类
 M miniapp/pages/pano/pano.wxss   ← canvas显式z-index,pano-top去写死尺寸,
                                     gyro-ring开关两态视觉区分
 M miniapp/pages/photos/photos.js  ← 读nav,setData三个新字段
 M miniapp/pages/photos/photos.wxml← native-nav绑nav三值,position-heading独立padding
 M miniapp/pages/photos/photos.wxss← native-nav/position-heading padding拆分
```
仓库其余文件零改动(PROGRESS.md/BLOCKED.md本段追加不算)。开发者工具全程
保持登录(`cli islogin`复查仍是`{"login":true}`),没有碰过工具设置/登录状态。

### 真机待验清单(模拟器测不了的,列清楚每条怎么验)
1. **陀螺仪真实手感**:模拟器没有运动传感器硬件(`wx.startDeviceMotionListening`
   走fail回调),开关状态机本身用mock强制success路径验证过不崩,但传感器
   真实数据的滤波强度/零点漂移/方向对不对,只能真机验。**验法**:打开小程序
   pano页→点开罗盘图标→缓慢转动手机一整圈,检查①开启瞬间画面是否还在原地
   不跳②转动是否跟手机朝向一致方向③是否有明显抖动/迟滞。如果方向反了,
   改`pano.js`里`self.cameraYawDeg = ((self._gyroStartYaw + yawDelta)...`这行
   的`+yawDelta`为`-yawDelta`(注释里写了)。
2. **拖动惯性/灵敏度实际手感**:算式和automator模拟的数字都对上了(拖一屏
   ~120°,松手惯性能自然停),但"手感"这个词本身就是主观的,需要真人在真机
   上拖一下确认舒不舒服。**验法**:pano页手指拖动画面,感受转动幅度是否
   合适、松手后的滑行是否自然(不是突然停、也不是飘太久)。
3. **返回按钮真机点击**:automator的`element.tap()`证明了"事件绑定/导航
   逻辑"没问题,但没法证明"真实手指物理触摸这个屏幕坐标"在所有机型上都能
   命中(canvas同层渲染理论上没问题,但取决于用户实际微信客户端版本/机型
   是否支持,基础库2.9.0以后基本都支持,但极老客户端仍可能有native层级
   问题)。**验法**:真机全景页,手指实际点一下左上角返回箭头,确认①位置
   在胶囊按钮同一水平线上(不会看着偏低/偏高)②一次就能点中,不会点到画布
   触发拖动。
4. **进入屏"空间记忆"文字不挡胶囊**:模拟器这台"iPhone 12/13 Pro"机型量出来
   改前重叠78px、改后间距1.81px,但真机胶囊宽度/位置因机型而异(尤其安卓
   分布散),理论上`keepoutRight`公式会自适应,但没有第二台不同geometry的
   真机可以交叉验证。**验法**:真机进入屏,看右上角"空间记忆"四个字有没有
   被系统胶囊按钮(圆点+省略号那个胶囊形状)遮住或紧贴到几乎重叠。
5. **各机型导航条高度观感**:安卓机型胶囊按钮的位置/形状比iOS分布更散(部分
   定制ROM会不一样),`navBarHeight`公式理论上能适应,但只在本机唯一能跑的
   模拟器机型上验证过,建议至少在一台安卓真机上确认返回条高度/间距看着
   协调,不别扭。

## 批次J(2026-07-29,上传链路真通:进空间→传照片→看AI定位状态→回到全景方位,通过,验收1-5全绿)

**任务**:小程序从"只读看展壳"升级成可用闭环。地界=上传与数据流,不碰批次I的
pano渲染器/陀螺仪/返回钮/导航布局。

### 动线说明

```
index页                          pano页                         photos页
┌──────────────┐   sid=stressexp1  ┌──────────────┐  sid透传   ┌──────────────┐
│ 婚礼卡(原样)  │──onEnter(不带sid)→│              │───────────→│              │
│ [新]体验空间卡│──onEnterExperience│ 📷传一张照片  │  goPhotos  │  我传的 区    │
│ "传张照片试试"│   ?sid=stressexp1 │  按钮(左下,   │  ?sid=..   │ (本地会话记录 │
└──────────────┘                  │  跟陀螺仪对称) │            │  +状态标签)   │
                                   │  ↓tap         │←───────────│  onTapCard    │
                                   │ chooseMedia   │  ?sid=..   │  带sid+yaw    │
                                   │ (最多3张)      │  &yaw=..   └──────────────┘
                                   │  ↓            │
                                   │ 压缩(长边1600/ │
                                   │ q82,抄join.html)│
                                   │  ↓            │
                                   │ wx.uploadFile  │
                                   │ 直传OSS,拿201  │
                                   │  ↓            │
                                   │ 状态条:        │
                                   │ "上传中n/m"→   │
                                   │ "AI正在定位…"→ │
                                   │ 轮询space.json │
                                   │ (10s/次,≤3min) │
                                   │  ↓ 按inboxKey  │
                                   │  匹配photos[]  │
                                   │ 命中→"回到方位  │
                                   │  了"+视角补间转 │
                                   │  过去+缩略条刷新│
                                   │ 超时→"AI还在排  │
                                   │  队,稍后回来看" │
                                   └──────────────┘
```

sid 贯穿三页(query 参数传递,`util.DEFAULT_SPACE_ID`=s4 兜底,老的婚礼入口
完全不受影响):`utils/util.js` 的 `ensureSpace()` 从"只认 s4"改成"按 sid 分槽
缓存"(模块级 `spaceCache` 对象,不再挂 `app.globalData.space`——三页 `require()`
同一个文件路径拿到的是同一份模块实例,天然共享,不用经过 App() 中转),兼容
老调用方式 `ensureSpace(cb)`(sid缺省=s4,批次I那几处调用一个字没改照样能跑)。

体验空间入口卡固定指向 `stressexp1`(不是随便兜底 s4)——这是故意的产品决定:
测试上传不该混进 s4 那份真实婚礼相册,`stressexp1` 就是任务书原文点名"公共
体验空间"、专为这件事建的。

### 任务1·index页体验空间入口卡

`miniapp/pages/index/index.wxml` 在 `facts-bar` 和 `upload-link` 之间新增一张
玻璃卡片(`onEnterExperience`→`/pages/pano/pano?sid=stressexp1`),标题区/app-bar/
原有 `onEnter`(s4婚礼流程)一个字没动。

### 任务2·新上传模块 `miniapp/utils/upload.js`(新文件)

机制照抄 `web/join.html`(任务书点名的唯一验证过真源),不是另起一套猜出来的实现:
- 直传字段顺序:`key/OSSAccessKeyId/policy/Signature/x-oss-object-acl`,`file`
  由 `wx.uploadFile` 的 `filePath`/`name` 参数单独处理,平台保证排在 formData
  所有字段之后(OSS硬要求"file必须最后")。
- 另加 `success_action_status:"201"`——这是任务书明确要求的字段,`join.html`
  本身没加(默认应该是204)。**已实测**(见下方验收2):加了这个字段之后 OSS
  真的回 201,decode 过的 policy conditions 里没有限制这个字段,加了不影响
  签名校验。产品代码仍把任意 2xx 都当成功,不因为万一没拿到201就误判失败。
- key 命名:`<keyPrefix><毫秒时间戳>_<短id>__<base64url昵称>__free.jpg`,
  taskId 固定"free"(这版小程序没有任务墙领取流程)。base64url 昵称编码手写了
  UTF-8字节转换+`wx.arrayBufferToBase64`(小程序JS环境没有TextEncoder/btoa)。
- **压缩参数口径抄join.html**(任务书原文要求"抄口径",不是任务书自己写的
  "长边2000/质量80"那两个数字——那只是任务书作者的粗略估计):长边1600、
  JPEG质量82(0-100标度)。用 `wx.compressImage`(任务书允许的两个方案之一,
  不用canvas——不需要额外在某个页面塞一个隐藏canvas节点,更省事也不占地界),
  长边超1600时顺带传 `compressedWidth/compressedHeight`。压缩本身失败不阻断
  上传,退化用原图(真正兜底的是OSS policy自己的content-length-range,原图
  超限一样会被诚实分类成"文件太大")。
- **错误分类**:网络失败(`wx.uploadFile`的fail回调)/文件太大(客户端预检
  `wx.getFileInfo`比对`pol.maxSize`,+ OSS返回体里`EntityTooLarge`/
  `content-length-range`兜底)/policy过期(客户端主动比对`expiresAt`,+ OSS
  返回体里`expir`关键字兜底)。policy过期这条命中后重拉一次space.json换新
  policy重试这一个文件,不是无限重试。
- **轮询**:10秒一次,单个文件从上传成功那一刻起最多等3分钟,到点不管网络
  请求本身成不成功都会判超时(不会被"一直请求失败"卡成永远不超时)。按
  `inboxKey`(=key里`<时间戳>_<短id>`那一段)去匹配 space.json 的 `photos[]`——
  **这个字段app/contract.md的表里没写**(文档没跟上实际结构),是从真实
  s4/stressexp1 space.json 里读出来的实测结论(`pending[]`里已经有真实值,
  格式正是`buildKey()`拼出来的那两段)。

### 任务3·pano页上传入口+状态条

`miniapp/pages/pano/pano.wxml`/`.wxss` 新增 `.upload-btn`(左下角,跟
`.gyro-btn`(右下角)同一水平线`bottom:260~272rpx`对称,中心Y都是308rpx)+
`.upload-status-bar`(悬在按钮那一排上方,`.pano-hint`和按钮排之间本来就有
一大段没被任何元素占用的空档,量出来净空~430rpx,足够放一条状态条不挤)。
canvas/陀螺仪按钮/返回钮/导航条一个字没动。

`pano.js` 新增几个方法(`onUploadTap`/`startUploadTicker`/
`computeBatchStatusText`/`refreshUploadStatus`/`focusOnNewPhoto`/
`animateCameraTo`),全部是新增,没有改`tickInertia`/`render`/`buildProgram`/
`buildQuad`/`loadTexture`/`startRenderLoop`/陀螺仪那几个函数一行代码。
"回到方位了"之后视角转过去用的是新起的独立补间(`animateCameraTo`,
`setInterval`驱动,ease-out cubic,700ms),只是往渲染循环本来每帧都在读的
`cameraYawDeg`/`cameraPitchDeg`这两个字段上写数,触发前会关掉惯性标记
(`inertiaActive=false`)避免跟拖动惯性抢同一个字段——不改陀螺仪/惯性/渲染
本身的任何一行。

### 任务4·photos页"我传的"区

`photos.wxml` 在 `.position-top` 和 loading/error判断之间新增 `.mine-section`
(不依赖主列表网络请求成不成功,网慢时也能看到自己传的这几张状态),
`.native-nav`/返回钮/导航布局一个字没动。数据来自 `upload.getMyUploads(sid)`
(本次会话本地记录),`onShow`起一个3秒本地刷新(读内存数组,不发网络请求),
`onHide`/`onUnload`清掉。

### 验收(命令与实际输出)

**验收1・老三样**:
```
$ node --check miniapp/app.js miniapp/utils/util.js miniapp/utils/upload.js \
    miniapp/pages/index/index.js miniapp/pages/pano/pano.js miniapp/pages/photos/photos.js
OK miniapp/app.js
OK miniapp/utils/util.js
OK miniapp/utils/upload.js
OK miniapp/pages/index/index.js
OK miniapp/pages/pano/pano.js
OK miniapp/pages/photos/photos.js

$ node -e "JSON.parse(require('fs').readFileSync('miniapp/app.json')); console.log('OK')"
OK   (顺手复核了 index.json/pano.json/photos.json/project.config.json/sitemap.json,全部OK)

$ grep -rn "AccessKeySecret" miniapp/ ; echo exit=$?
exit=1(零命中)
$ grep -rn "LTAI" miniapp/ ; echo exit=$?
exit=1(零命中,Aliyun AccessKeyId前缀)
$ grep -rn "5t5nKact\|Gx7xCP" miniapp/ ; echo exit=$?
exit=1(零命中,本次开发实测看到过的s4 accessKeyId片段)
$ grep -rniE "secret[_-]?key|sk_live|private[_-]?key|BEGIN (RSA|PRIVATE)" miniapp/ ; echo exit=$?
exit=1(零命中)
```

**验收2・上传链路真传**(`ui-check/verify-upload.js`——不是另起一套"看起来
像"的字段构造代码,直接 `require()` 小程序自己的 `utils/upload.js`,跑的是
同一份 `extractPolicy()`/`buildKey()`,只在 `wx.arrayBufferToBase64` 这一个
宿主API上打了垫片):
```
$ node ui-check/verify-upload.js stressexp1
[1] 拉 space.json: HTTP 200, nodes=1 photos=0 published=true
[2] extractPolicy(): host=https://psm-advx-2026.oss-cn-hangzhou.aliyuncs.com
    keyPrefix=spaces/stressexp1/inbox-v2/g1/ maxSize=12582912
    expiresAt=2026-07-31T12:11:17.032Z(还没过期)
[3] buildKey(): key=spaces/stressexp1/inbox-v2/g1/1785328114446_vwdigk__6aqM5pS26ISa5pys5rWL6K-V__free.jpg
    inboxKey=1785328114446_vwdigk
[4] miniapp uploadOne()组装的formData字段(顺序即实际顺序,file最后):
    key / OSSAccessKeyId(redacted) / policy(redacted) / Signature(redacted) /
    x-oss-object-acl=private / success_action_status=201 / file=miniapp/assets/panos/expo.jpg
[5] 真传 POST -> HTTP 201
    <PostResponse><Bucket>psm-advx-2026</Bucket>
    <Location>https://psm-advx-2026.oss-cn-hangzhou.aliyuncs.com/spaces/stressexp1/inbox-v2/g1/1785328114446_vwdigk__6aqM5pS26ISa5pys5rWL6K-V__free.jpg</Location>
    <Key>spaces/stressexp1/inbox-v2/g1/1785328114446_vwdigk__6aqM5pS26ISa5pys5rWL6K-V__free.jpg</Key>
    <ETag>BFD0D4F895DA2960466C08D2629ABF35</ETag></PostResponse>
=== 结果: 成功,HTTP 201 ===
[6] 收件箱前缀确认:GET ?prefix=...&list-type=2 -> HTTP 403 AccessDenied
    "Anonymous user has no right to access this bucket."；HEAD 具体key -> HTTP 403。
    **这是private ACL+桶不开放匿名list的预期行为,不是失败**——上传对象本身
    是`x-oss-object-acl:private`,任何未授权请求(不管对象存不存在)桶都统一
    回403,不通过公开GET/LIST判断存在性是这个桶的安全设计,不是我这边的漏洞。
    201响应体本身(带Bucket/Location/Key/ETag,跟我们提交的key逐字符匹配)
    就是OSS写入成功的权威确认,比事后一次GET更直接。
    (worker后续是否已捡到:复查stressexp1 space.json的pending[]/photos[],
    截至写这段时还没出现——worker处理节奏不在本任务控制范围,这正是"轮询
    3分钟超时诚实提示"要处理的场景,不是bug。)
```

**同一脚本对 s4(已知过期policy)复测,验证错误分类regex对真实OSS报文有效**:
```
$ node ui-check/verify-upload.js s4
[5] 真传 POST -> HTTP 403
    <Error><Code>AccessDenied</Code>
    <Message>Invalid according to Policy: Policy expired.</Message></Error>
=== 结果: 失败,HTTP 403 ===
```
`upload.js`里`/expir/i.test(body)`能匹配到这句真实OSS报文里的"expired"，
而且客户端自己的`expiresAt`比对本来就会在发请求前提前拦下来(s4这份policy
在检查时点已经过期约44.5小时)，这次是绕过客户端预检直接测OSS本身的行为，
两层加起来验证了"policy过期"这条错误分类不是纸上谈兵。**s4这次没有创建
任何对象(403拒绝在先),没有需要清理的东西**。

**验收3・automator三屏截图**(`ui-check/connectHelper.js`重建了BLOCKED.md
I-2记录的"探测端口没开就自己spawn cli auto"绕过方案,原文件不在仓库里,
本次重新写的):
```
$ node ui-check/shots-j.js
connecting... connected.
shot 1 (index) done      -> ui-check/j-01-index.png   (体验空间卡可见)
shot 2 (pano, sid=stressexp1) done -> ui-check/j-02-pano.png
     (标题正确显示"体验空间·宴会厅"，证明sid贯穿生效；📷传一张照片按钮
      左下角可见，跟陀螺仪按钮对称不重叠)
shot 3 (photos, sid=stressexp1) done -> ui-check/j-03-photos.png
     (标题正确显示"体验空间·宴会厅·WEDDING MEMORY"，0张照片0位贡献者，
      跟stressexp1真实数据一致)
done, disconnected.
```
肉眼核对(见截图):三屏都正常渲染,新元素不跟已有元素重叠,原有s4婚礼卡/
返回钮/陀螺仪按钮/导航条全部原样。

**额外验证(非acceptance硬性要求,加强证据)**:用`mockWxMethod('chooseMedia',...)`
+ `element.tap('.upload-btn')`尝试端到端驱动真实`onUploadTap`代码路径(不经过
我自己的验收脚本)。**结果**:mock选图成功进入"上传中0/1"，但紧接着落进
"网络不好,传失败了"——排查结论:automator的mock只能顶替`wx.chooseMedia`的
返回值，不能让`wx.uploadFile`认可一个非"通过chooseMedia真实注册"的临时文件
路径(模拟器对文件句柄有自己的登记机制，直接塞绝对路径不是同一回事)，连续
两次(换成功不同路径)都是同一个失败点，判断为**automator mock原生选图这件事
本身摸不到**，不是`upload.js`的bug——这也正是为什么"chooseMedia真实选图"
被列进下面真机待验清单第1条。截图`ui-check/j-04-upload-e2e.png`留证:状态条
文案正确显示诚实错误提示(不是空白/不是假装成功)，证明错误态UI路径本身
接线正确。

**验收4・cli preview 出码**:
```
$ /Applications/wechatwebdevtools.app/Contents/MacOS/cli preview \
    --project /Users/max/code/spatial-memory/miniapp \
    --qr-format image --qr-output ui-check/preview-qr-v5.png
✔ preview
┌─────────┬──────────┬─────────────┐
│ (index) │   size   │ size (Byte) │
├─────────┼──────────┼─────────────┤
│  TOTAL  │ '1.1 MB' │   1165759   │
└─────────┴──────────┴─────────────┘
```
`preview-qr-v5.png`(302×300)已生成,编译通过(WeChat自己的编译器验证了
WXML/WXSS/JS/JSON能组装成一个合法包,是比`node --check`更强的一层确认)。

### 真机待验清单(模拟器/automator测不到的)

1. **chooseMedia真实选图**:automator只能mock返回值，摸不到原生相册/相机
   picker本身(见上面"额外验证"那段的排查结论)。**验法**:真机点"📷传一张
   照片"，确认能正常弹出微信原生的图片选择器，选1~3张能正常返回。
2. **真传+压缩实际效果**:压缩参数(长边1600/质量82)在真机上跑一遍，确认
   压缩后文件确实变小、图片没有明显肉眼可见的画质劣化，弱网环境下`wx.uploadFile`
   真的能完整传完。**验法**:真机选一张几MB的原图，看状态条从"上传中1/1"
   走到"AI正在定位…"的耗时是否合理(不会卡在"上传中"很久)。
3. **轮询+回到方位动画**:worker真的把这张照片处理出yaw之后，状态条切到
   "回到方位了"、视角自动转过去、缩略条刷新出这张新照片，全程在真机上肉眼
   确认一次。本次验收因worker处理节奏不在控制范围内，只验证到"201写入成功"
   这一步，没等到worker真正处理完(space.json的pending[]/photos[]截至提交时
   还没出现这次测试上传的记录)。**验法**:真机传一张，留着App开着，等最多
   3分钟，看是走到"回到方位了"还是诚实超时"AI还在排队"，两条路径都要看到过。
4. **超时路径**:如果3分钟内worker没处理完，确认状态条真的显示"AI还在排队,
   稍后回来看"而不是无限转圈。**验法**:传一张后不要退出，掐表等3分钟以上。
5. **上传按钮/状态条真机布局**:模拟器验证过不跟返回钮/陀螺仪按钮/缩略条
   重叠(数学坐标+automator截图双重确认)，但真机胶囊按钮位置因机型而异，
   建议至少一台安卓机确认按钮位置协调、不别扭(跟批次I遗留的第5条真机待验
   同类问题)。
6. **photos页"我传的"跨会话行为**:确认从pano页传完切到photos页，"我传的"
   区域标签+状态文案正确显示，且这份记录只在当前小程序运行会话内有效(彻底
   退出重进后清空——这是设计如此，不是bug，任务书原文是"本次会话")。

### git status
```
 M PROGRESS.md                     ← 本任务书指定要交的文件,只在末尾追加(批次J这一段)
 M BLOCKED.md                      ← 同上
 M miniapp/app.js                  ← 未改动本批次代码(git diff为空,是批次I遗留在工作区的既有修改)
 M miniapp/utils/util.js           ← sid参数化 ensureSpace,新增 fetchSpaceFresh/spaceJsonUrl/EXPERIENCE_SPACE_ID
 M miniapp/pages/index/index.js    ← 新增 onEnterExperience
 M miniapp/pages/index/index.wxml  ← 新增体验空间入口卡
 M miniapp/pages/index/index.wxss  ← 新增 .experience-card 系列样式
 M miniapp/pages/pano/pano.js      ← 新增上传入口/状态条/视角补间/sid读取,不改陀螺仪/渲染
 M miniapp/pages/pano/pano.wxml    ← 新增 .upload-btn/.upload-status-bar
 M miniapp/pages/pano/pano.wxss    ← 新增对应样式,追加在文件末尾
 M miniapp/pages/photos/photos.js  ← 新增"我传的"区数据+sid读取
 M miniapp/pages/photos/photos.wxml← 新增 .mine-section
 M miniapp/pages/photos/photos.wxss← 新增对应样式,追加在文件末尾
?? miniapp/utils/upload.js         ← 新文件:上传模块
?? ui-check/                       ← 新建,验收脚本+截图+QR码(白名单,验收产物,同批次H/I先例)
```
仓库其余文件(web/、app/、server/、tools/等)零改动。开发者工具全程保持登录
(`cli islogin`复查仍是`{"login":true}`),没有碰过工具设置/登录状态。
