# BUGS · 压测军团(批次D)

72 个变体(join 完整动线 24 + show 五视图/live 24 + 粗暴操作 16 + portal/pov 补充烟测 8)
全部执行完毕,`runlog.txt` 累计 221 行(含修复前后的重跑对比)。发现并修复 2 个真 bug,
另登记 1 条判断为"不需要修"的观察项、1 条环境抖动型 flake、1 条产品功能缺口(非 bug)。

---

## 先说清楚:任务书要问的「灯箱」不存在,不是我漏测

show.html 的五种视图(展览/旅程/时光轴/画册/监控墙)+ `live=1` 大屏模式,一共对
24 个「宽度 × 视图」组合各点了一次照片卡片(`.photo` / `.jr-shot` / `.tl-card` /
`.al-plate` / `.mc-tile`),点击前后 `document.body.innerHTML` 的字符长度差
**全部是 0**。翻源码确认:show.html 里这几个元素没有绑 `addEventListener`、没有
`href`、没有 `onclick`,点了就是点了空气。

不算 bug(不崩溃、不报错、不影响其它功能),是这一版 show.html 压根没做"点开大图"
这个交互。原样如实记录,不属于 P0/P1/P2 分级,详见文末「简化建议」第 1 条。
证据:所有 S 组 runlog 行(`node tools/stress/run-all.mjs S` 的完整输出)+
`tools/stress/shots/S*.png`(84 张截图之一,任选一张放大看,照片卡片没有任何放大态)。

---

## Bug 列表

### BUG-1 ·【P1 · 已修复】超长昵称把头部胶囊撑爆,整页横向溢出

**复现步骤:**
1. 打开 `web/join.html?mock=1`(320/390/430 三档宽度都能复现,768 因视口够宽不复现)。
2. 在这台设备的 `localStorage` 里,把 `psm_nick` 设成一个 30 字、emoji 与中文混排的名字,
   例如 `小明😀🎉🚀测试嘉宾超级无敌长昵称走过路过别错过呀哈哈哈哈`。
   **真实触发途径**:页面输入框有 `maxlength="12"`,正常在这台设备上打字或粘贴打不出
   这么长的名字;但 `maxlength` 挡不住 `localStorage` 里已经存在的旧值——换新设备、
   旧版本页面写入过、或者跨端同步带过来的名字都可能超长。
3. 刷新页面(回访态,`welcome` 屏直接跳过)。

**现象:** 头部「你好,XXX」胶囊(`.head-me`)被撑到 437px 宽,同一行的「陈屹 ♥ 林沐」
被挤到只剩几像素宽、逐字换行成竖排;`document.documentElement.scrollWidth` 变成
437,超出 320/390 视口,产生真实横向滚动。

**严重度:** P1 — 功能没死(点击、上传都还能用),但核心品牌区域视觉损毁 + 产生
真实横向可滚动,用户第一眼看到的就是破版页面。

**截图:**
- 修复前:`tools/stress/shots/BUG1-long-nickname-BEFORE-w390.png`(scrollWidth=437)
- 修复后:`tools/stress/shots/BUG1-long-nickname-AFTER-w390.png`(scrollWidth=390)
- 压测原始留档:`tools/stress/shots/R07/R08/R09-long-nickname-emoji-w*.png`

**修复(`web/join.html`):** `.head-me` 加 `max-width:52%; min-width:0`;
`.head-me b`(昵称本体)加 `flex:1 1 auto; min-width:0; overflow:hidden;
text-overflow:ellipsis; white-space:nowrap`。"你好," 三个字保持完整不截断,
名字超宽时省略号收尾,胶囊整体封顶头部区域 52% 宽度。短名字(绝大多数真实场景)
视觉零变化。

**回归:** R07(320)/R08(390)/R09(768)三个宽度重跑,`node tools/stress/run-all.mjs R`
全部 `result=PASS overflow=false`。基线任务 0(join+show)重跑同样全绿。

```
修复前 runlog: [R07-long-nickname-emoji-w320] result=FAIL overflow=437 bugs=3 :: 头部昵称 pill 右边缘(437.25px)超出视口(320px)...
修复后 runlog: [R07-long-nickname-emoji-w320] result=PASS overflow=false ms=4971 bugs=0
```

---

### BUG-2 ·【P2 · 已修复】填完名字的 toast 会叠在刚打开的上传抽屉标题上

**复现步骤:**
1. 打开 `web/join.html?mock=1`,填名字点「好了,带我去看看→」(或点「先不写名字」)。
2. **400ms 内**紧接着点「直接交照片」或任一任务卡的「我去拍这张」。这不是刻意手快,
   是完全正常速度的宾客都会做的操作——填完名字立刻点下一步。

**现象:** 名字提交后触发的 toast(`好的 XX,挑一个任务吧`,展示 2.4 秒,
`z-index:70`)和刚打开的上传抽屉标题(`正在上传到云端…` / `收到了,一共 N 张`,
`z-index:50`)落在屏幕同一块区域,两段文字肉眼可见地叠在一起,抽屉标题被半遮住。

**严重度:** P2 — 纯视觉问题,上传流程本身没有受影响(toast 有
`pointer-events:none`,不挡点击),但用户这一下读不清抽屉标题在说什么。

**截图:**
- 修复前:`tools/stress/shots/BUG2-toast-sheet-overlap-BEFORE-w390.png`
- 修复后:`tools/stress/shots/BUG2-toast-sheet-overlap-AFTER-w390.png`
- 压测原始留档:`tools/stress/shots/J01/J19-*-first-fill-free.png`

**修复(`web/join.html`):** `openSheet()` 一开抽屉就主动收起还在显示的 toast
(`$("toast").classList.remove("on")` + `clearTimeout(toast._t)`)。toast 该出现的
时候照常出现(比如没打开抽屉时的其它提示),只是不会再跟"刚打开的抽屉"抢屏幕。

**回归:** 重跑 J 组全部 24 条 + R 组里所有会打开抽屉的场景(same-button-3x /
refresh-mid-flow / zero-photo-upload / reopen-sheet-different-task /
double-cancel-cycle),全部 `PASS`,并逐张肉眼复核截图确认无重叠。

---

## 观察到、判断不需要修的一条(如实登记,供复核人否决)

### 回访改名后的 toast 偶尔会盖住背景任务卡按钮的一角

出现在 `reopen-name-editor`(R13)、`rapid-tab-switch-10x`(R14)等场景截图里:
提交昵称后的 toast 短暂盖住下方任务卡「我有这张」按钮文字的一部分。

**判断为不需要修,理由:**
1. `.toast` 基础样式是 `pointer-events:none`,`.toast.on` 没有覆盖这一条——
   toast 可见期间点击照样穿透到它背后的按钮,不挡交互,只挡了约 1.5 秒的阅读。
2. 这是几乎所有 app 都有的标准 toast/角标模式(短暂盖住背景内容后自动消失),
   不是这一页特有的错误实现。
3. 和 BUG-2 的关键区别:BUG-2 挡住的是宾客此刻正盯着看的模态框标题(抽屉是
   主动点开、必须读的焦点内容);这一条挡住的是背景里一个此刻不需要点的按钮,
   阅读和操作都不受阻。

截图:`tools/stress/shots/R13-reopen-name-editor-w390.png`、
`tools/stress/shots/R14-rapid-tab-switch-10x-w390.png`。没有改代码。如果复核人
认为也要收敛(比如所有 toast 一律先清场上的旧 toast,或者整体上移离开卡片区),
这是可以另外单独做的小改动,不在本轮的"必须修"范围内。

---

## 一次网络抖动型 flake(非代码 bug,已排除)

`S01-w320-exhibition` 在第二轮全量重跑中出现过 1 次
`这个视图 data-photo 数量为 0(期望 s4 的 9 张)`。show.html 读的是真实云端
`s4` 的 `space.json`(一次真实 HTTPS 请求,允许的"只读"范围内),不是本地假数据,
偶发的网络延迟会导致 2.2 秒的等待窗口里数据还没回来。

**核实:** 用同一 URL(`web/show.html?s=s4`,320 宽)连续单独重跑 4 次,
`data-photo` 数量全部是 9,0 次失败。判定为压测脚本的固定等待时间偶然撞上了
一次真实网络延迟,不是 show.html 的代码缺陷。已在正式 runlog 里重新跑绿并落档
(`node tools/stress/run-all.mjs S` 最终这条 `result=PASS`)。

---

## 简化建议(不动手改语义,列出来给领导拍板)

1. **「换个方式看」五个视图 + 大屏模式,一共 24 处照片卡片都点不开大图。**
   任务书把"灯箱开关"列进必测项,说明预期里这个功能是存在的。现状是纯展示墙,
   点击是死的。要不要做,是产品决定,不在本轮"修 bug"范围内动手加新功能。

2. **`web/join.html` 里 `MOCK_SPACE` 的假上传永远不会在前台"定案"。**
   `mockPost()` 走完进度条后,回执要等 `POLL_MAX_MS`(2 分钟)超时才会出现最终文案,
   因为固定的两张假照片(p1/p2)不带 `inboxKey`,永远配不上刚生成的短 id。如果
   `?mock=1` 以后还会被人当演示/验收工具用,建议让假数据里至少一张能在几秒内
   "配对成功",体验会完整很多(现在演示到"AI 正在定位方向"就只能干等或直接跳走)。

3. **s4(真实线上空间)的贡献者名单里有一条叫「公网验收员」的真实记录**
   (压测时在 `machine`/`journey` 等视图里看到,截图 `S23-w768-machine.png`)。
   这明显是历史测试/验收流程留下的真实数据,`publicName()` 的匿名化黑名单目前只挡
   `泛音测`/`延迟测试`/`阿伟测试`等几个固定词和"并发"开头、"验收测试"等 QA 模式,
   没挡住"公网验收员"这个变体。这是**真实线上数据内容**,不是代码 bug,我对 s4
   只读,没有资格也没有权限去改它;这条挂在 BLOCKED.md 里登记,留给能写 s4 的人判断
   要不要清理数据或者扩大匿名化名单。

---

## 变体矩阵覆盖清单(72 个变体,详见主报告的完整覆盖表)

- 组 J(join 完整动线):24 —— 宽度 4 × { 首访×(填名/跳名)×(直接交/任务卡) ,
  回访×(直接交/任务卡) }
- 组 S(show 五视图 + live=1):24 —— 宽度 4 × 6 种视图场景
- 组 R(粗暴操作):16 —— 10 个具名场景,按宽度敏感度分配 1-3 档宽度
- 组 P(portal/pov 补充烟测,超出任务书最低要求):8 —— 2 页 × 宽度 4

完整逐行结果见 `tools/stress/runlog.txt`(221 行,含每个 bug 的修复前后对比)。
