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
