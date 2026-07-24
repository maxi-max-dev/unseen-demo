# HyperFrames 一键成片 · 环境笔记

写给下一个工兵。全部结论都是 2026-07-24 在这台 Mac（M4 / 16GB / macOS 24.6）上真跑出来的，
不是抄文档。冒烟工程在 `/tmp/hf_smoke/`（smoke = 图片背景版，vid = 视频底层版），
两条 mp4 都真出来了、亲眼验过、中文没乱码。

---

## 0. 一句话结论

HyperFrames 能用，**本地渲染不需要 HeyGen 账号，全程没登录过**。
5 秒 1080p / 30fps 渲一遍 **3～9 秒**，现场演示完全跑得动。
唯一必须提前踩的坑是**中文字体**（见第 4 节），不处理就是豆腐块 + `check` 直接报错。

---

## 1. 环境体检 `npx hyperframes doctor`

真实输出（0.7.70）：

```
✓ Version          0.7.70 (latest)
✓ Node.js          v25.8.0 (darwin arm64)
✓ CPU              10 cores · Apple M4
✓ Memory           16.0 GB total · 5.9 GB available
✓ Disk             13.3 GB free
✓ Frames cache     /var/folders/.../hyperframes-extract-cache-501
✓ FFmpeg           ffmpeg 8.1.2 at /opt/homebrew/bin/ffmpeg
✓ FFprobe          ffprobe 8.1.2
✓ Chrome           system: /Applications/Google Chrome.app/...
✓ whisper-cpp      /opt/homebrew/bin/whisper-cli
✗ TTS (Kokoro)     未装（可选，本地配音兜底）
✗ BGM (MusicGen)   未装（可选，本地配乐兜底）
✗ Docker           未装（只有 render --docker 才需要）
```

要点：

- **硬性依赖全绿**：Node ≥ 22（我们 v25.8.0）、FFmpeg、Chrome 都满足。
- **Chrome 用的是系统装的那个**，没有额外下载一份 Chromium，省了几百 MB。
- 那三个 ✗ 全是可选项，**不影响渲染**。`doctor` 因为它们整体判 “Some checks failed”，
  别被吓到 —— 要脚本判定就用 `npx hyperframes doctor --json | jq -e '.ok'`，或者直接看具体行。
- 我们不需要 Docker（`--docker` 只是为了跨机器逐字节复现），不需要 TTS/BGM（不做配音配乐）。

## 2. 本地渲染要不要 HeyGen 账号？—— 不要

**实测结论：全程零登录、零 API key。** 从 `init` → `check` → `render` 出 mp4，
没有跑过 `hyperframes auth`，没有任何鉴权提示。
渲染就是本机起无头 Chrome 逐帧截图 + 本机 ffmpeg 编码。

需要账号的只有这几条我们用不到的路：`cloud render`（HeyGen 托管渲染）、`publish`（上传拿公开链接）、
云端 TTS。本地路完全自足。

**但注意联网点**：脚手架默认从 `cdn.jsdelivr.net` 拉 GSAP。这条我们必须干掉（见第 3 节），
否则断网演示当场白屏。干掉之后，除了第一次 `npx` 装包，整条链路可以断网跑。

## 3. 目录结构 + 从零到一条 5 秒视频要几步

### 建工程

```bash
HYPERFRAMES_SKIP_SKILLS=1 npx -y hyperframes init smoke \
  --non-interactive --example blank --resolution landscape
```

- 非 TTY（我们这种 agent 环境）**必须给 `--example`**，否则报 usage 错。
- `HYPERFRAMES_SKIP_SKILLS=1` 跳过它去 GitHub 拉 AI skills（我们本地已经有了，省一次联网）。
- `--resolution landscape` = 1920×1080。还有 portrait / square / 4k 档。

脚手架产物只有 32KB，六个文件：

```
smoke/
  index.html        ← 唯一要写的东西，主合成
  package.json      ← 脚本里把 CLI 钉死在 hyperframes@0.7.70
  hyperframes.json  ← 路径约定：assets/ 放素材，compositions/ 放子合成
  meta.json         ← {id, name}
  AGENTS.md / CLAUDE.md  ← 给 AI agent 看的项目约定，可以不管
```

后续自己加的：

```
  assets/           ← 素材全放这，HTML 里用相对路径 assets/xxx.jpg
  out.mp4           ← 渲染产物
```

### 三步出片

```bash
cd smoke
npx --yes hyperframes@0.7.70 check                      # 1. 体检（lint+运行时+排版+动效+对比度）
npx --yes hyperframes@0.7.70 render --output out.mp4    # 2. 渲染
ffprobe -v error -show_entries format=duration out.mp4  # 3. 验货
```

`check` 一条命令就把 lint 跑了，别再单独 `lint`。它开一次浏览器 seek 一遍，
查运行时报错、请求失败、排版塌陷、动效断言、WCAG 对比度。**过不了就别渲。**

### 合成 HTML 的硬规矩（踩过的都在这）

1. **根节点必须显式写死尺寸**，`#root { width:1920px; height:1080px; position:relative; overflow:hidden }`，
   并且 `data-composition-id / data-start / data-duration / data-width / data-height` 五个属性齐全。
2. **满屏底色/底图放在 root 的「全出血子元素」上**（`position:absolute; inset:0`），
   **不能放 root 自己** —— producer 合帧时会丢掉 root 自身的 background，渲出黑帧，
   而 preview 和 snapshot 看着都是好的，最阴的一种坑。
3. **每个有时间的元素都要 `class="clip"` + `data-start` + `data-duration` + `data-track-index`**。
   track-index 就是层级，数字大的盖在上面。
4. **只有一条 GSAP 时间轴**，`gsap.timeline({ paused: true })`，页面加载时同步建好，
   注册到 `window.__timelines["<composition-id>"]`。片长以 root 的 `data-duration` 为准，
   不是时间轴长度。
5. **要做位移/缩放的元素必须 block 级 + 有尺寸**，并且别直接动带时间的 `.clip` 本身 ——
   在 `.clip` 里再套一层不带时间的 wrapper，动 wrapper。
6. **禁止不确定性**：不许 `Date.now()`、不许没种子的 `Math.random()`、不许网络请求、
   不许 `repeat: -1`（要循环写有限次数）。
7. 正文里不许 `<br>`。

### GSAP 本地化（零外链 CDN，必做）

脚手架的 `index.html` 里是这行：

```html
<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
```

断网就废。做法是把它扒到本地（71KB）：

```bash
cd /tmp && npm pack gsap@3.14.2 && tar -xzf gsap-3.14.2.tgz package/dist/gsap.min.js
cp package/dist/gsap.min.js <项目>/assets/gsap.min.js
```

HTML 改成 `<script src="assets/gsap.min.js"></script>`。**实测 check 和 render 全过**，
渲染器不关心 GSAP 从哪来，只要 `window.__timelines` 注册上了就行。
（Lottie / Three.js 同理，也是 CDN，要用也得先本地化。）

## 4. 中文字体 —— 这是真坑，必须照抄

### 症状

直接写 `font-family: "PingFang SC", "Hiragino Sans GB", sans-serif;`，
`check` 会直接**报错**（不是警告）：

```
✗ font_family_without_font_face: Font families used without @font-face declaration:
  pingfang sc, hiragino sans gb, ... These are not in the auto-resolved font list,
  so the renderer cannot supply them automatically. Text will fall back to a generic
  font, producing incorrect typography in the video.
```

### 解法

给系统自带字体补一条 `@font-face`，`src` 用 `local()`（**不需要字体文件**），
一条声明里串一串 `local()` 就是回退链：

```css
@font-face {
  font-family: "SpatialCN";
  src: local("PingFang SC"), local("PingFangSC-Regular"),
       local("Hiragino Sans GB"), local("Heiti SC"), local("STHeiti"),
       local("Songti SC"), local("Arial Unicode MS");
  font-weight: 100 900;
  font-style: normal;
}
body { font-family: "SpatialCN", sans-serif; }
```

改完 `check` 立刻 **0 errors 0 warnings**，渲出来的中文清清楚楚，
标题「空间记忆」和小字「那一天，散落在每个人的手机里」都是标准苹方，**没有一个豆腐块**。

### 附带的排版细节

中文加 `letter-spacing` 会让最后一个字右边多出一格空白、整体看着偏左。
补一个同值的 `text-indent` 抵消掉：

```css
#title { letter-spacing: 0.22em; text-indent: 0.22em; text-align: center; }
```

### 提醒

这套 `local()` 方案**只在有中文字体的机器上成立**（macOS 自带苹方/冬青黑/黑体/宋体，稳）。
如果哪天要 `render --docker` 或者上云渲染，容器里没有中文字体，还是会变豆腐块 ——
那种情况必须打包一个真的 `.woff2` 进 `assets/` 并用 `src: url(...)`。
我们现场演示是本机渲染，暂时不用管。

## 5. 渲染速度（现场演示够不够快）

同一条 5 秒 1080p 合成，实测（含 npx 启动开销之外的净渲染时间）：

| 档位 | 命令 | 耗时 | 文件大小 |
| --- | --- | --- | --- |
| draft | `--quality draft` | **3.4s** | 1.6 MB |
| standard（默认） | `render` | **8.2s** | 3.9 MB |
| high | `--quality high` | **8.5s** | 7.5 MB |
| high + 60fps | `--quality high --fps 60` | **11.6s** | 7.3 MB |
| 底层视频版 standard | `render` | **6.2s** | 1.4 MB |

- 换算：**1080p30 大约 18～45 帧/秒渲染速度**，也就是「比实时快 1.5～3 倍」。
  一条 60 秒的成片，standard 档大概 **1.5～2 分钟**。现场演示可接受，但别当场等 4K。
- 迭代时用 `draft`，交付才 `high`。60fps 只多花 40%，但对我们没意义（平移镜头 30fps 够）。
- 自动开 5 个 worker（每个一个 Chrome 进程）。内存峰值实测 **约 650MB RSS**，16GB 机器毫无压力。
  真嫌吃内存可以 `--workers 3`。

## 6. 磁盘 / 内存占用

| 项 | 大小 | 说明 |
| --- | --- | --- |
| npx 缓存 `~/.npm/_npx/<hash>` | **392 MB** | 一次性，hyperframes 全家桶（含 puppeteer 等）。别删，删了每次重下 |
| 脚手架本体 | 32 KB | 忽略不计 |
| 帧提取缓存 `$TMPDIR/hyperframes-extract-cache-501` | **48 MB**（渲过一条 16s 视频后） | 会随素材增长，**可以随时整个删掉**，下次自动重建 |
| 项目 `.hf-tmp` 中间帧 | 0 | 实测渲完**自动清干净**，项目目录里不留残渣 |
| 内存峰值 | ~650 MB | 5 worker 并行时 |

无头 Chrome 也是**渲完自己退干净**的（`ps aux | grep -i chrome` 里没留 hyperframes 起的进程）。
不用手动 kill。

清缓存：

```bash
rm -rf "$TMPDIR"/hyperframes-extract-cache-*
```

## 7. ⭐ 已有 mp4 当底层 + 上面叠图片和字幕（下一步就要用）

**这条已经真跑通了**，工程在 `/tmp/hf_smoke/vid/`，产物 `out.mp4`（1.4MB / 5.0s / 1920×1080 / 30fps）。
底层是 `assets/videodemo/walkthrough_demo.mp4`，上面浮出一张 `ballroom_j3.jpg` 照片卡，
底部一行中文字幕，全部正常。

### 三条铁律（违反了不报错，直接渲出黑/白块）

1. **`<video>` / `<audio>` 必须是 root 的直接子元素。** 不能包在任何 `<div>` 里，
   更不能放进子合成的 `<template>`。运行时只驱动 root 的直接子级媒体，
   放错地方就永远不解码 → 渲出空白面板，而且 `lint` / `check` 查不出来。
2. **不许在合成代码里 `video.play()` / `pause()` / 改 `currentTime`。** 播放权归框架。
3. **不许给带时间的媒体元素做尺寸动画。** 要动就动它旁边的非计时元素，
   铺满靠 CSS `object-fit: cover`。

### 可以抄的骨架

```html
<div id="root" data-composition-id="main" data-start="0" data-duration="5"
     data-width="1920" data-height="1080">

  <!-- 底层：全景漫游视频。track-index 最小 = 最底下 -->
  <video id="bg-video" class="clip"
         src="assets/walkthrough_demo.mp4"
         data-start="0"            <!-- 在成片时间轴上第几秒出现 -->
         data-duration="5"         <!-- 用多久 -->
         data-media-start="4"      <!-- 从源片第 4 秒开始取（剪辑入点） -->
         data-track-index="0"
         muted playsinline></video>

  <!-- 上层 1：照片浮现。外层 .clip 管时间，内层 wrapper 管变换 -->
  <div id="photo-slot" class="clip" style="position:absolute;inset:0;display:grid;place-items:center"
       data-start="1.2" data-duration="3.8" data-track-index="2">
    <div id="photo-card"><img src="assets/ballroom_j3.jpg" alt="" /></div>
  </div>

  <!-- 上层 2：字幕 -->
  <div id="caption-slot" class="clip" style="position:absolute;inset:0"
       data-start="0.5" data-duration="4.5" data-track-index="3">
    <div id="caption-bg"></div>
    <div id="caption">宴会厅 · 方位 128°，小林拍的第 3 张</div>
  </div>
</div>

<script>
  window.__timelines = window.__timelines || {};
  const tl = gsap.timeline({ paused: true });
  // 时间参数是「成片全局时间」，不是相对 clip 的时间
  tl.from("#photo-card", { scale: 0.86, y: 40, autoAlpha: 0, duration: 0.8, ease: "power3.out" }, 1.3);
  tl.from("#caption",    { y: 24,  autoAlpha: 0, duration: 0.7, ease: "power2.out" }, 0.6);
  window.__timelines["main"] = tl;
</script>
```

### 关键属性速查

| 属性 | 意思 |
| --- | --- |
| `data-start` | 这段素材在**成片时间轴**上什么时候出现 |
| `data-duration` | 出现多久。视频省略则用整条素材长度 |
| `data-media-start` | **剪辑入点**：从源视频的第几秒开始取。拼接多段素材全靠它 |
| `data-track-index` | 层级，数字大的盖上面。视频放 0，图片 2，字幕 3 |
| `data-volume` | 静态音量 0~1。**声音必须单独放 `<audio>`，`<video>` 一律 muted** |
| `data-hidden` | 临时隐藏某元素（preview 和 render 都隐藏），调试很好用 |

### 其它实测细节

- **编码不挑**：渲染时是 ffmpeg 先把视频抽成帧再注入 Chrome，所以 H.265/HEVC 也能渲。
  只有浏览器预览会自动转一份 H.264 代理（缓存在临时目录）。
- **底层视频第一帧不黑**：t=0.2s 抽帧验过，画面正常，不是常见的「首帧黑」bug。
- **宽高比会裁**：素材是 2048×1024（2:1），成片 1920×1080（16:9），`object-fit: cover`
  上下各裁掉一点。要全展示就得 `contain` + 上下留黑边，或者干脆把成片改成 2:1 画幅。
- **每个 `id` 在整页里必须唯一**。特别是 `<video>` / `<img>` 的 id 撞车会直接渲成空白，
  因为 producer 是按 `getElementById` 注帧的，而 `lint` 抓不到跨文件重名。

## 8. 一键成片下一步怎么接

我们的「空间驱动自动剪辑」大概率不是一条 mp4 底层，而是**逐帧改 yaw 的平移飞行镜头**。
两条路，按情况选：

- **路 A（推荐先试）：ffmpeg 预渲底层。** 用 `tools/slice.py` 的
  `equirect_to_perspective(pano, fov, yaw, pitch, w, h)` 逐帧改 yaw 出 PNG 序列，
  ffmpeg 压成一条无声 mp4 当底层，然后**完全套用第 7 节的骨架**在上面叠照片和字幕。
  好处：飞行轨迹的数学全在 Python 里，可控、可复算，HyperFrames 只管叠加和转场。
  这也是第 7 节这条冒烟视频存在的意义 —— 那条路已经验通了。
- **路 B：在 HTML 里直接做全景相机。** 用 CSS 3D 或 Three.js 适配器把全景贴到球内壁，
  逐帧动相机 yaw。好处是不用中间文件、转场更顺；坏处是 Three.js 也得本地化，
  而且要遵守 HyperFrames 的 seek-safe 约定（时间轴必须能任意跳帧复现，不能靠 rAF 累加）。

无论哪条，第 4 节的中文字体和第 3 节的 GSAP 本地化都是绕不过去的前置。

---

## 附：冒烟产物清单（可复查）

```
/tmp/hf_smoke/smoke/index.html    图片背景 + 中文标题版 合成源码
/tmp/hf_smoke/smoke/out.mp4       3.9 MB · 5.000s · 1920x1080 · 30fps · h264 · 150 帧
/tmp/hf_smoke/vid/index.html      视频底层 + 叠图 + 叠字幕 合成源码
/tmp/hf_smoke/vid/out.mp4         1.4 MB · 5.000s · 1920x1080 · 30fps · h264 · 150 帧
/tmp/hf_smoke/frame_1s.jpg        抽帧验货：标题浮现中
/tmp/hf_smoke/frame_4s.jpg        抽帧验货：标题+细线+小字全出，背景已推近
/tmp/hf_smoke/vid_a.jpg           抽帧验货：底层视频正常（非黑帧）
/tmp/hf_smoke/vid_b.jpg           抽帧验货：照片卡+中文字幕叠加正常
```
