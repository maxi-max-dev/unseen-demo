# 一键成片 · memory-film

把散在各人手机里的照片,按它们**当时朝着的方向**排成一条片子:
镜头转向那个方向 → 照片在那儿浮现 → 再转向下一张 → 走进下一个空间。

不是幻灯片。幻灯片谁都能做,这条片子的顺序、转角、停留时长,全部由每张照片的
yaw / pitch 算出来 —— 只有我们有这个数据。

**成片:`film/out/memory-film.mp4` · 1 分 19 秒 · 1280×720 · 30fps · h264 + aac 立体声 · 58 MB**

---

## 快速重渲

```bash
cd /Users/max/code/spatial-memory
.venv/bin/python film/build_bg.py          # 1. 背景飞行视频 + 镜头时间表(约 40 秒)
.venv/bin/python film/make_bgm.py          # 2. 背景音乐(约 5 秒)
.venv/bin/python film/gen_composition.py   # 3. 生成 film/index.html(瞬间)
cd film && npm run check                 # 4. 体检,必须 Check passed 才往下走
npm run render                           # 5. 渲染高质量母版(约 55 秒)
npm run web                              # 6. 压成网页版本并把 moov 前置
```

只改字幕/版面就跑 3 → 5(约 1 分钟)。改镜头节奏要从 1 开始重来。

---

## 四个文件各干什么

| 文件 | 干什么 | 产物 |
| --- | --- | --- |
| `build_bg.py` | 决定"喂给 film.py 的节点长什么样",调 `server/film.py` 排镜头 + 渲飞行 | `assets/flythrough.mp4`(74.0s 无声)、`assets/shots.json` |
| `make_bgm.py` | 用 numpy 逐样本合成一段原创音乐,ffmpeg 加混响导出 | `assets/bgm.mp3` |
| `gen_composition.py` | 读 `shots.json`,生成 HyperFrames 合成 | `index.html`、`assets/photos/*.jpg` |
| `index.html` | **生成的,别手改**,改了下次重跑被覆盖 | — |

镜头规划和投影数学全在 `server/film.py`(不是这个目录),HyperFrames 的坑在
`server/FILM-NOTES.md`。

---

## 合成分层

| track | 内容 |
| --- | --- |
| 0 | 黑底(视频放完后的兜底) |
| 1 | 背景飞行视频 |
| 2 | 暗角 vignette |
| 3 | **方位尺**:画面顶上那把刻度尺,跟着镜头滑 |
| 4 | 照片卡 + caption + 方位罗盘 |
| 5 | 章节卡(接亲 09:08 / 出发 10:30 / 仪式 12:18 / 宴席 18:00) |
| 6 | 首尾卡 |
| 7 | 背景音乐 |

### 方位尺是怎么和背景对齐的

不是"看着差不多"。`gen_composition.py` 直接 import `server/film.py` 的
`_ease_for` / `shortest_delta`,用**渲背景那一帧时用的同一个函数**算尺子该滑到哪:

- `reveal` 线性 → GSAP `ease:"none"`,完全一致
- `fly` / `transition` 三次缓入缓出 → GSAP `power2.inOut`,公式逐字相同
  (GSAP 的 `power2` 才是 cubic,`power3` 是四次方,别写错)
- `establish` 是 smoothstep,GSAP 没有对应曲线 → 拆成 10 段线性按原函数采样,误差 < 0.1°

验收办法:随便挑一个 reveal 帧,尺子中间红线读到的度数 = 照片说明里的「方位 xxx°」。
实测 020° / 060° / 145° / 185° 四处全部对上。

---

## 怎么换素材

### 换新人名字和日期(片尾)

`gen_composition.py` 顶上三行:

```python
COUPLE    = "新郎 与 新娘"        # 改成 "陈屿 与 林见月"
FILM_DATE = "二〇二六年 · 那一天"
TITLE_MAIN = "重温那一天"
```

改完跑第 3、5 步。

### 换成真实素材(影石全景 + 真照片)

真素材到位后**换 `tour.js` 的 `assets/panos/*.jpg` 和 `assets/photos/*.jpg`**,然后:

```bash
.venv/bin/python film/build_bg.py --source tour
```

`--source tour` 完全吃 `tour.js`,一行不用改。整条数据链路(tour.js → plan_shots →
flythrough → shots.json → 合成)已经跑通验过。

### 换章节 / 换每章挑几张照片

`build_bg.py` 顶上的 `CHAPTERS`:每章写 `{裁切图编号: 文案}`。
**文案按方位角从小到大读下来要合乎流程** —— 镜头是按方位单向扫过去的,
画面顺序 = 方位顺序,不是书写顺序。改完先跑 `--plan-only` 核对时间轴上的先后:

```bash
.venv/bin/python film/build_bg.py --plan-only
```

片长上限在 `--max-total`(默认 74 秒)。超了 `film.py` 会自动每章少挑几张。

---

## ⚠️ 交付这一版用的是什么素材(重要,别对外说错)

| | 真的 | 摆拍的 |
| --- | --- | --- |
| 每张照片的 **yaw / pitch** | ✅ 逐像素回解出来的(`film.solve_crop_pose`,残差 0.019–0.161),可复核:`python -m server.film --solve-walk` | |
| 镜头转到那个方向 | ✅ 同一个投影函数渲的,和 `tools/slice.py` 对拍 bit-exact | |
| 画面里的空间 | Poly Haven **CC0** 真实室内全景(`assets/walkdemo/`,来源见同目录 `SOURCE.txt`) | 不是婚礼现场 |
| 章节名 / 时刻 / caption | | ❌ demo 剧本,来自 `tour.js` |

**为什么这么拼**:`tour.js` 配的 `assets/panos/*.jpg` 是 `tools/fixtures.py` 生成的
标定图(彩色扇区 + 印着 000°/030° 的大字),技术上百分之百自洽,但放出来根本不像照片。
`tour.js` 文件头自己也写着"当前内容 = 合成测试素材,真实影石全景到位后替换"。
所以画面换成 Poly Haven 的真实室内,婚礼剧本照旧 —— **空间那部分的主张是真的、可复核的,
婚礼那部分是 demo 剧本**。对外演示时这句话要说清楚。

想看完全自洽(但难看)的那一版:`--source tour`。

---

## 音乐

`assets/bgm.mp3`(79.5s,C 大调 C–G–Am–F,pad + 八音盒 + 低频长音三层)。

**来源 = `film/make_bgm.py` 现场合成的原创片段,没有下载任何素材,没有版权风险。**

为什么不用 `media-use`:它的两条正路本机都走不通 ——

- HeyGen 音乐库要登录(`npx hyperframes auth status` = Not signed in,`~/.heygen` 不存在)
- 本地生成 Lyria 要 `GEMINI_API_KEY`(未设),MusicGen 要 `pip install transformers torch`
  —— 撞项目铁律「零新依赖」

网上随手抓的"免费 BGM"授权说不清楚,所以自己写。想换真曲子就把 `assets/bgm.mp3`
替换掉,音量在 `gen_composition.py` 的 `BGM_VOLUME`(现在 0.85,成片 mean −23.8 dB)。

---

## 已知的取舍

1. **`check` 剩两条 warning**(`timeline_track_too_dense`:track 4 有 12 个照片 clip、
   track 5 有 4 个章节 clip),它建议拆成子合成。没拆:这个 `index.html` 是**生成的**,
   拆子合成要引入 `<template>` 传输那套规则和额外的 id 前缀,风险大于收益。
   errors / 排版 / 动效 / 对比度全 0,WCAG 14/14 过。
2. **照片进出各有一次 0.6s / 0.42s 的淡入淡出**,正好抽在淡出中间的帧会看到照片卡半透明
   (`t=13.2s` 那帧就是),是设计如此,不是渲染 bug。
3. **58 MB / 79 秒偏大**(crf 默认 + 全片持续运镜)。离线演示手机装不下就在 `render`
   后面加 `--quality draft`,或者拿 ffmpeg 再压一道。
4. **中文字体走 `local()` 声明**,只在装了中文字体的机器上成立(macOS 自带苹方,稳)。
   哪天要 `render --docker` 或上云渲染,必须打包真 `.woff2` 进 `assets/`,否则一屏豆腐块。
5. **`assets/flythrough.mp4` 33 MB、`out/memory-film.mp4` 58 MB**,别无脑 `git add`。
