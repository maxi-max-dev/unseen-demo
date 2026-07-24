#!/usr/bin/env python3
"""
film/gen_composition.py -- 读 film/assets/shots.json,生成 HyperFrames 合成 film/index.html。

合成分层(数字 = data-track-index,大的盖上面):
    0  黑底         视频放完之后的兜底,别让最后几秒露白
    1  背景飞行视频   film/assets/flythrough.mp4(build_bg.py 产的,无声)
    2  暗角         压一层 vignette,把注意力收到画面中间
    3  方位尺        画面顶上那把刻度尺,跟着镜头一起滑 —— 全片唯一"只有我们能做"的 HUD
    4  照片 + 说明   飞到位时浮现,含 caption 和方位罗盘
    5  章节卡        接亲 09:08 / 出发 10:30 / 仪式 12:18 / 宴席 18:00
    6  首尾卡        「重温那一天」/ 片尾
    7  背景音乐       make_bgm.py 现场合成的原创片段

方位尺怎么保证和背景严丝合缝:
    film.py 渲每一帧的 yaw 是 y0 + shortest_delta * ease(t)。这里直接 import 它的
    _ease_for / shortest_delta,同一套函数算出刻度尺该滑到哪:
      - reveal       线性        -> GSAP ease "none",完全一致
      - fly / transition 三次缓入缓出 -> GSAP "power2.inOut",公式逐字相同(GSAP 的
                                        power2 = cubic,别写成 power3,那是四次)
      - establish    smoothstep  -> GSAP 没有对应曲线,所以拆成 10 段线性,
                                    直接按 film.py 的函数采样,误差 < 0.1°
    所以尺子不是"看着差不多",是同一个函数算出来的。

铁律(踩过的坑,见 server/FILM-NOTES.md):
    - <video>/<audio> 必须是 root 的直接子元素
    - 满屏底色放全出血子元素,不能放 root 自己(否则渲出黑帧)
    - 只有一条 paused 时间轴,注册到 window.__timelines
    - 动画一律 fromTo(两端写死),不用 to():渲染器是多 worker 乱序 seek 的,
      to() 的起始值是首次渲染时才捕获的,乱序下会拿到错的值
    - 动的是 .clip 里面那层 wrapper,不动 .clip 本身(显隐归框架管)

跑法:
    .venv/bin/python film/gen_composition.py
"""
import json
import math
import os
import shutil
import sys
import urllib.parse

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from server import film  # noqa: E402

FILM_DIR = os.path.dirname(os.path.abspath(__file__))
SHOTS_JSON = os.path.join(FILM_DIR, "assets", "shots.json")
PHOTO_DIR = os.path.join(FILM_DIR, "assets", "photos")
OUT_HTML = os.path.join(FILM_DIR, "index.html")

COMP_ID = "memoryfilm"

# ---- 片尾占位:换成真新人只改这三行 ----------------------------------------
COUPLE = "新郎 与 新娘"          # 例:"陈屿 与 林见月"
FILM_DATE = "二〇二六年 · 那一天"
TITLE_MAIN = "重温那一天"
TITLE_SUB = "空间记忆 · 把每张照片放回它被拍下的方位"

# ---- 版面参数 ---------------------------------------------------------------
TITLE_S = 4.0        # 开场卡时长(压在第一个定场镜头上,不额外占片长)
END_LEAD = 0.85      # 片尾卡提前多久进来(压住背景视频最后那点黑场淡出)
END_HOLD = 5.4       # 背景视频放完之后片尾还留多久
CHAPTER_DELAY = 0.35 # 章节卡比定场镜头晚一点进,别和切换的黑场撞一起
CHAPTER_S = 3.0
RIBBON_PX_PER_DEG = 5.0
ESTABLISH_SEGS = 10  # 定场镜头的方位尺拆成几段线性
RIBBON_GAP_S = 0.004 # 相邻两段之间留的缝(见下面 check 那条注释)
# 音量:全片没有旁白,音乐就是唯一的声音,不该压成"垫底 bed"。
# 0.5 实测成片 mean_volume 只有 -28.4 dB,现场外放基本听不见;0.85 约 -24 dB。
BGM_VOLUME = 0.85


def esc(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


# ---------------------------------------------------------------------------
# 方位尺:把全片的 yaw 展成一条不回绕的连续曲线
# ---------------------------------------------------------------------------

def unwrap_track(shots):
    """算出每个镜头首尾在"展开后"的方位轴上的位置(度)。

    yaw 本身是 0-360 循环的,直接拿来当坐标会在 359->0 处炸回原点。
    所以按最短弧一路累加:每个镜头内部累加自己的转角,镜头之间累加接缝处的最短弧。
    节点切换处画面本来就是硬切,尺子跟着瞬移是对的(那一刻它正淡出)。

    ⚠ 起点必须取第一个镜头的 fromYaw,不能图省事从 0 开始。
    每一步加的都是 shortest_delta(a,b) ≡ b-a (mod 360),所以从 fromYaw 起步的话
    展开坐标全程 ≡ 真实方位角 (mod 360),尺子上的数字才是真读数。
    从 0 起步的话整条尺子会平移第一个 fromYaw 那么多度 —— 画面照样跟得动,
    但数字全是错的(实测偏了 334°:照片标 020°,尺子读 045°)。
    """
    out = []
    acc = float(shots[0]["fromYaw"]) if shots else 0.0
    prev_yaw = None
    for s in shots:
        y0, y1 = float(s["fromYaw"]), float(s["toYaw"])
        if prev_yaw is not None:
            acc += film.shortest_delta(prev_yaw, y0)
        start = acc
        acc += film.shortest_delta(y0, y1)
        out.append((start, acc))
        prev_yaw = y1
    return out


def ribbon_tweens(shots, track):
    """[(时间, 时长, 起始 x, 结束 x, ease), ...],x 是刻度尺的 translateX(px)。"""
    def to_x(deg):
        return -deg * RIBBON_PX_PER_DEG

    tws = []
    for s, (d0, d1) in zip(shots, track):
        st, dur, typ = float(s["startS"]), float(s["durationS"]), s["type"]
        if typ == "reveal":
            tws.append((st, dur, to_x(d0), to_x(d1), "none"))
        elif typ == "establish":
            # smoothstep 在 GSAP 里没有对应曲线,按 film.py 自己的函数采样成折线
            for i in range(ESTABLISH_SEGS):
                t0, t1 = i / ESTABLISH_SEGS, (i + 1) / ESTABLISH_SEGS
                e0, e1 = film._ease_for(typ, t0), film._ease_for(typ, t1)
                tws.append((st + dur * t0, dur / ESTABLISH_SEGS,
                            to_x(d0 + (d1 - d0) * e0), to_x(d0 + (d1 - d0) * e1), "none"))
        else:
            # fly / transition:三次缓入缓出,和 GSAP power2.inOut 逐字相同
            tws.append((st, dur, to_x(d0), to_x(d1), "power2.inOut"))
    return tws


def ribbon_strip(track):
    """刻度尺画成一张 SVG 贴图(data URI),不产生任何 DOM 元素。

    为什么不用 DOM:刻度尺是一条几千像素的长条,只靠父级 overflow:hidden 裁出
    中间那个窗口。hyperframes check 的排版/对比度那两关是逐元素量的,不认这个裁剪 ——
    它会去量早就被裁到画面外的那些 <b> 数字压在什么背景上,报一屏
    canvas_overflow / text_occluded / 对比度不足。画成一张图之后,整条尺子就是
    一个元素的 background,没有文本节点可查,画面效果一模一样。

    返回 (data URI, 起始度数 lo, 图宽 px)。
    """
    lo = math.floor((min(a for a, _ in track) - 120.0) / 30.0) * 30.0
    hi = math.ceil((max(b for _, b in track) + 120.0) / 30.0) * 30.0
    w = (hi - lo) * RIBBON_PX_PER_DEG
    h = 34

    body = []
    d = lo
    while d <= hi:
        x = (d - lo) * RIBBON_PX_PER_DEG
        if abs(d % 30.0) < 1e-6:
            body.append(f'<rect x="{x - 0.6:.1f}" y="2" width="1.2" height="12" '
                        f'fill="#f3ede3" fill-opacity=".82"/>')
            # 标签写回绕之后的真实方位角(观众看的是罗盘读数,不是展开轴)
            body.append(f'<text x="{x:.1f}" y="29" text-anchor="middle" font-size="12" '
                        f'font-family="Helvetica,Arial,sans-serif" letter-spacing="1.3" '
                        f'fill="#f3ede3" fill-opacity=".95">{int(round(d)) % 360:03d}&#176;</text>')
        else:
            body.append(f'<rect x="{x - 0.5:.1f}" y="4" width="1" height="7" '
                        f'fill="#f3ede3" fill-opacity=".5"/>')
        d += 5.0

    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.0f}" height="{h}" '
           f'viewBox="0 0 {w:.0f} {h}">{"".join(body)}</svg>')
    return "data:image/svg+xml;utf8," + urllib.parse.quote(svg, safe="") , lo, w


# ---------------------------------------------------------------------------
# 罗盘徽标(照片说明右边那枚小表盘,指针指着这张照片的方位)
# ---------------------------------------------------------------------------

def compass_svg(yaw, idx):
    """指针指向这张照片的 yaw。画在照片的白纸上,所以用墨色描边,只有指针是朱色。"""
    a = math.radians(yaw - 90.0)         # 0° 朝上
    cx = cy = 21.0
    x2, y2 = cx + 15.0 * math.cos(a), cy + 15.0 * math.sin(a)
    return (
        f'<svg class="cps" viewBox="0 0 42 42" width="42" height="42" aria-hidden="true">'
        f'<circle cx="21" cy="21" r="18.5" fill="none" stroke="rgba(36,31,27,.3)" stroke-width="1"/>'
        f'<circle cx="21" cy="21" r="1.9" fill="#c8402f"/>'
        f'<line x1="21" y1="2.5" x2="21" y2="6.5" stroke="rgba(36,31,27,.55)" stroke-width="1"/>'
        f'<line id="nd{idx}" x1="21" y1="21" x2="{x2:.2f}" y2="{y2:.2f}" '
        f'stroke="#c8402f" stroke-width="2.2" stroke-linecap="round"/>'
        f'</svg>')


# ---------------------------------------------------------------------------
# 生成
# ---------------------------------------------------------------------------

def build():
    doc = json.load(open(SHOTS_JSON, encoding="utf-8"))
    shots = doc["shots"]
    meta = doc["meta"]
    W, H = int(meta["width"]), int(meta["height"])
    bg_s = float(meta["durationS"])
    total_s = round(bg_s + END_HOLD, 3)

    shutil.rmtree(PHOTO_DIR, ignore_errors=True)
    os.makedirs(PHOTO_DIR, exist_ok=True)

    reveals = [s for s in shots if s["type"] == "reveal"]
    establishes = [s for s in shots if s["type"] == "establish"]
    track = unwrap_track(shots)
    strip_uri, strip_lo, strip_w = ribbon_strip(track)

    body, tl = [], []

    # ---- 0 黑底 ----------------------------------------------------------
    body.append(f'<div id="backdrop" class="clip" data-start="0" '
                f'data-duration="{total_s}" data-track-index="0"></div>')

    # ---- 1 背景飞行视频(必须是 root 的直接子元素)------------------------
    body.append(f'<video id="bgvid" class="clip" src="assets/flythrough.mp4" '
                f'data-start="0" data-duration="{bg_s}" data-media-start="0" '
                f'data-track-index="1" muted playsinline></video>')

    # ---- 7 背景音乐(同上,必须直接挂 root)-------------------------------
    body.append(f'<audio id="bgm" class="clip" src="assets/bgm.mp3" data-start="0" '
                f'data-duration="{total_s}" data-volume="{BGM_VOLUME}" data-track-index="7"></audio>')

    # ---- 2 暗角 ----------------------------------------------------------
    body.append(f'<div id="vig" class="clip" data-start="0" data-duration="{bg_s}" '
                f'data-track-index="2"></div>')

    # ---- 3 方位尺 --------------------------------------------------------
    rib_start = TITLE_S - 0.4
    rib_dur = round(bg_s - rib_start - 0.4, 3)
    body.append(
        f'<div id="ribbon" class="clip" data-start="{rib_start}" data-duration="{rib_dur}" '
        f'data-track-index="3">'
        f'<div id="rib-fade"><div id="rib-plate"></div>'
        # rib-track 摆在"窗口正中 + 贴图起始度数"的位置:贴图里度数 d 落在 (d-lo)*PPD,
        # 加上这个 left 之后就是 220+d*PPD;整条尺子再平移 -yaw*PPD,两者抵消,
        # "当前 yaw 那根刻度"正好落在窗口中间那道红线上。
        f'<div id="rib-win"><div id="rib-track" data-layout-allow-overflow style="left:{220 + strip_lo * RIBBON_PX_PER_DEG:.1f}px;'
        f'width:{strip_w:.0f}px;background-image:url(&quot;{strip_uri}&quot;)"></div></div>'
        f'<div id="rib-cursor"></div>'
        f'<div id="rib-label">镜头方位</div>'
        f'</div></div>')

    tl.append(f'tl.fromTo("#rib-fade",{{autoAlpha:0}},{{autoAlpha:1,duration:.7,'
              f'ease:"power1.out",immediateRender:true}},{rib_start});')
    tl.append(f'tl.fromTo("#rib-fade",{{autoAlpha:1}},{{autoAlpha:0,duration:.5,'
              f'ease:"power1.in",immediateRender:false}},{round(rib_start + rib_dur - 0.5, 3)});')
    # 每段都写死起止 x(fromTo),所以乱序 seek 也不会串位。
    # 节点之间是硬切,相邻两段的 x 本来就对不上 —— 尺子跟着画面一起瞬移,这是对的。
    # 每段掐掉尾巴 4ms(RIBBON_GAP_S):相邻两段首尾严丝合缝地"贴住"会被
    # check 判 overlapping_gsap_tweens。空出来的 4ms 里前一段的终值继续挂着,
    # 4ms = 0.12 帧,画面上根本不存在。
    for st, dur, x0, x1, ease in ribbon_tweens(shots, track):
        tl.append(f'tl.fromTo("#rib-track",{{x:{x0:.1f}}},'
                  f'{{x:{x1:.1f},duration:{max(0.02, dur - RIBBON_GAP_S):.3f},'
                  f'ease:"{ease}",immediateRender:false}},{st:.3f});')

    # ---- 4 照片 + 说明 ---------------------------------------------------
    for i, s in enumerate(reveals):
        st, dur = float(s["startS"]), float(s["durationS"])
        # 背景在 reveal 段前 30% 才压暗到位,照片跟着这个节奏进来才不会"抢在暗之前"
        p_in, p_out = 0.62, 0.42
        # 素材必须落在工程目录里:HyperFrames 按项目根解析相对路径,
        # 指到 ../assets/ 的照片渲染器读不到,会渲成空白卡。
        src_abs = os.path.join(REPO_ROOT, s["photo"])
        dest = os.path.join(PHOTO_DIR, f"{i:02d}_" + os.path.basename(src_abs))
        shutil.copyfile(src_abs, dest)
        src = os.path.relpath(dest, FILM_DIR)
        yaw = float(s.get("photoYaw") or 0.0)
        body.append(
            f'<div id="ph{i}" class="clip photo" data-start="{st:.3f}" '
            f'data-duration="{dur:.3f}" data-track-index="4">'
            # 说明文字印在照片的白纸上,不是浮在画面上:
            # 背景是活动的全景,浅色墙面一出现白字就糊了(check 的 WCAG 对比度这一关也过不去)。
            # 印在纸上对比度恒定,顺带更像一张洗出来的照片。
            f'<div id="phw{i}" class="phw">'
            f'<div class="card"><img src="{esc(src)}" alt="">'
            f'<div class="cap"><span class="cap-t">{esc(s.get("caption"))}</span>'
            f'<span class="cap-d"></span>'
            f'{compass_svg(yaw, i)}'
            f'<span class="cap-y">方位 {int(round(yaw)) % 360:03d}°</span>'
            f'</div></div></div></div>')
        tl.append(f'tl.fromTo("#phw{i}",{{autoAlpha:0,scale:.94,y:26}},'
                  f'{{autoAlpha:1,scale:1,y:0,duration:{p_in},ease:"power3.out",'
                  f'immediateRender:true}},{st + 0.1:.3f});')
        tl.append(f'tl.fromTo("#phw{i}",{{autoAlpha:1,scale:1}},'
                  f'{{autoAlpha:0,scale:1.03,duration:{p_out},ease:"power2.in",'
                  f'immediateRender:false}},{st + dur - p_out - 0.05:.3f});')

    # ---- 5 章节卡 --------------------------------------------------------
    for i, s in enumerate(establishes):
        st = float(s["startS"]) + CHAPTER_DELAY
        if i == 0:
            st = TITLE_S + 0.25          # 第一章让开开场卡
        body.append(
            f'<div id="ch{i}" class="clip chapter" data-start="{st:.3f}" '
            f'data-duration="{CHAPTER_S}" data-track-index="5">'
            # 左下角压一层软渐变:章节字压在活动画面上,碰到浅色墙就看不清了。
            # 渐变是斜的、到画面中间就化没了,不像贴了个黑条。
            f'<div id="chw{i}" class="chw">'
            f'<div class="ch-scrim"></div>'
            f'<div id="chb{i}" class="ch-body">'
            f'<div class="ch-rule"></div>'
            f'<div class="ch-txt"><div class="ch-time">{esc(s.get("nodeTime"))}</div>'
            f'<div class="ch-name">{esc(s.get("nodeName"))}</div></div>'
            f'</div></div></div>')
        tl.append(f'tl.fromTo("#chw{i}",{{autoAlpha:0}},{{autoAlpha:1,'
                  f'duration:.7,ease:"power3.out",immediateRender:true}},{st + 0.05:.3f});')
        tl.append(f'tl.fromTo("#chb{i}",{{x:-22}},{{x:0,'
                  f'duration:.9,ease:"power3.out",immediateRender:true}},{st + 0.05:.3f});')
        tl.append(f'tl.fromTo("#chw{i}",{{autoAlpha:1}},{{autoAlpha:0,duration:.5,'
                  f'ease:"power1.in",immediateRender:false}},{st + CHAPTER_S - 0.55:.3f});')

    # ---- 6 开场卡 --------------------------------------------------------
    body.append(
        f'<div id="titlecard" class="clip" data-start="0" data-duration="{TITLE_S}" '
        f'data-track-index="6">'
        f'<div id="tt-scrim"></div>'
        f'<div id="tt-wrap">'
        f'<div id="tt-main">{esc(TITLE_MAIN)}</div>'
        f'<div id="tt-rule"></div>'
        f'<div id="tt-sub">{esc(TITLE_SUB)}</div>'
        f'</div></div>')
    tl.append('tl.fromTo("#tt-scrim",{autoAlpha:0},{autoAlpha:1,duration:.5,'
              'ease:"power1.out",immediateRender:true},0);')
    tl.append('tl.fromTo("#tt-main",{autoAlpha:0,y:20},{autoAlpha:1,y:0,duration:1.0,'
              'ease:"power3.out",immediateRender:true},.35);')
    tl.append('tl.fromTo("#tt-rule",{autoAlpha:0,scaleX:0},{autoAlpha:1,scaleX:1,'
              'duration:.9,ease:"power2.out",immediateRender:true},.95);')
    tl.append('tl.fromTo("#tt-sub",{autoAlpha:0,y:12},{autoAlpha:1,y:0,duration:.8,'
              'ease:"power2.out",immediateRender:true},1.25);')
    tl.append(f'tl.fromTo("#tt-wrap",{{autoAlpha:1}},{{autoAlpha:0,duration:.6,'
              f'ease:"power1.in",immediateRender:false}},{TITLE_S - 0.7});')
    tl.append(f'tl.fromTo("#tt-scrim",{{autoAlpha:1}},{{autoAlpha:0,duration:.75,'
              f'ease:"power1.in",immediateRender:false}},{TITLE_S - 0.8});')

    # ---- 6 片尾卡 --------------------------------------------------------
    end_st = round(bg_s - END_LEAD, 3)
    end_dur = round(total_s - end_st, 3)
    stat = (f'{doc["summary"]["nodeCount"]} 个空间 · {doc["summary"]["photoCount"]} 张照片'
            f' · 每一张都回到了它被拍下的方位')
    body.append(
        f'<div id="endcard" class="clip" data-start="{end_st}" data-duration="{end_dur}" '
        f'data-track-index="6">'
        f'<div id="ed-scrim"></div>'
        f'<div id="ed-wrap">'
        f'<div id="ed-names">{esc(COUPLE)}</div>'
        f'<div id="ed-date">{esc(FILM_DATE)}</div>'
        f'<div id="ed-rule"></div>'
        f'<div id="ed-stat">{esc(stat)}</div>'
        f'<div id="ed-mark">空间记忆</div>'
        f'</div></div>')
    tl.append(f'tl.fromTo("#ed-scrim",{{autoAlpha:0}},{{autoAlpha:1,duration:.8,'
              f'ease:"power1.out",immediateRender:true}},{end_st});')
    tl.append(f'tl.fromTo("#ed-names",{{autoAlpha:0,y:18}},{{autoAlpha:1,y:0,duration:1.0,'
              f'ease:"power3.out",immediateRender:true}},{end_st + 0.55:.3f});')
    tl.append(f'tl.fromTo("#ed-date",{{autoAlpha:0}},{{autoAlpha:1,duration:.9,'
              f'ease:"power2.out",immediateRender:true}},{end_st + 1.15:.3f});')
    tl.append(f'tl.fromTo("#ed-rule",{{autoAlpha:0,scaleX:0}},{{autoAlpha:1,scaleX:1,'
              f'duration:1.0,ease:"power2.out",immediateRender:true}},{end_st + 1.5:.3f});')
    tl.append(f'tl.fromTo("#ed-stat",{{autoAlpha:0,y:10}},{{autoAlpha:1,y:0,duration:.9,'
              f'ease:"power2.out",immediateRender:true}},{end_st + 1.9:.3f});')
    tl.append(f'tl.fromTo("#ed-mark",{{autoAlpha:0}},{{autoAlpha:1,duration:1.0,'
              f'ease:"power2.out",immediateRender:true}},{end_st + 2.6:.3f});')
    tl.append(f'tl.fromTo("#ed-wrap",{{autoAlpha:1}},{{autoAlpha:0,duration:1.0,'
              f'ease:"power1.in",immediateRender:false}},{round(total_s - 1.2, 3)});')

    html = TEMPLATE.format(
        w=W, h=H, total=total_s, comp=COMP_ID,
        body="\n  ".join(body),
        timeline="\n  ".join(tl),
    )
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"{OUT_HTML}")
    print(f"  片长 {total_s}s = 背景 {bg_s}s + 片尾留 {END_HOLD}s")
    print(f"  {len(reveals)} 张照片 / {len(establishes)} 个章节 / {len(tl)} 条动画")


TEMPLATE = """<!doctype html>
<!-- 由 film/gen_composition.py 生成,别手改;改了下次重跑会被覆盖 -->
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width={w}, height={h}" />
<title>空间记忆 · 一键成片</title>
<script src="assets/gsap.min.js"></script>
<style>
  /* 中文字体:给系统自带字体补一条 @font-face 用 local(),不需要字体文件。
     不补这条 hyperframes check 会直接报 font_family_without_font_face,
     渲出来就是豆腐块。这套只在有中文字体的机器上成立(本机渲染没问题),
     哪天上 Docker 或云渲染必须打包真 woff2。 */
  @font-face {{
    font-family: "SpatialCN";
    src: local("PingFang SC"), local("PingFangSC-Regular"), local("Hiragino Sans GB"),
         local("Heiti SC"), local("STHeiti"), local("Songti SC"), local("Arial Unicode MS");
    font-weight: 100 900;
    font-style: normal;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html, body {{ width: {w}px; height: {h}px; overflow: hidden; background: #07080c; }}
  body {{ font-family: "SpatialCN", sans-serif; }}

  #root {{ width: {w}px; height: {h}px; position: relative; overflow: hidden;
           color: #f3ede3; }}

  #backdrop {{ position: absolute; inset: 0; background: #07080c; }}
  #bgvid {{ position: absolute; inset: 0; width: 100%; height: 100%;
            object-fit: cover; }}
  #vig {{ position: absolute; inset: 0;
          background:
            radial-gradient(120% 88% at 50% 46%, rgba(0,0,0,0) 42%, rgba(0,0,0,.34) 74%,
                            rgba(0,0,0,.62) 100%),
            linear-gradient(to bottom, rgba(0,0,0,.30) 0%, rgba(0,0,0,0) 16%,
                            rgba(0,0,0,0) 72%, rgba(0,0,0,.42) 100%); }}

  /* ---- 方位尺 ---- */
  #ribbon {{ position: absolute; inset: 0; }}
  #rib-fade {{ position: absolute; left: 0; right: 0; top: 26px; height: 54px; }}
  /* 尺子底下垫一块两头化开的暗板:刻度和数字压在活动画面上,
     背景一亮就读不出来了(WCAG 那关也会红)。垫上之后对比度和画面无关。 */
  /* 垫板的不透明区必须比刻度窗口宽一圈(窗口 440,不透明区 ~351-929):
     窗口边缘那几个数字虽然被 mask 化没了,自动对比度检查看不见 mask,
     只看文字色和背后的画面 —— 垫板盖不住就一路报红。 */
  #rib-plate {{ position: absolute; left: 50%; top: -14px; width: 760px;
                margin-left: -380px; height: 82px;
                background: linear-gradient(to right, rgba(7,8,12,0) 0%,
                            rgba(7,8,12,.86) 12%, rgba(7,8,12,.86) 88%,
                            rgba(7,8,12,0) 100%); }}
  #rib-win {{ position: absolute; left: 50%; top: 0; width: 440px; height: 34px;
              margin-left: -220px; overflow: hidden;
              -webkit-mask-image: linear-gradient(to right, transparent 0%, #000 18%,
                                                  #000 82%, transparent 100%);
              mask-image: linear-gradient(to right, transparent 0%, #000 18%,
                                          #000 82%, transparent 100%); }}
  #rib-track {{ position: absolute; top: 0; height: 34px;
                background-repeat: no-repeat; background-position: 0 0; }}
  #rib-cursor {{ position: absolute; left: 50%; top: 0; width: 1px; height: 20px;
                 margin-left: -0.5px; background: #c8402f;
                 box-shadow: 0 0 8px rgba(200,64,47,.85); }}
  #rib-label {{ position: absolute; left: 50%; top: 38px; width: 200px;
                margin-left: -100px; text-align: center; font-size: 11px;
                letter-spacing: .34em; text-indent: .34em;
                color: rgba(243,237,227,.82); }}

  /* ---- 照片 ---- */
  .photo {{ position: absolute; inset: 0; display: grid; place-items: center; }}
  .phw {{ display: block; width: 560px; }}
  .card {{ display: block; padding: 14px 14px 4px; background: #f6f2ea;
           box-shadow: 0 26px 60px rgba(0,0,0,.62), 0 2px 10px rgba(0,0,0,.4); }}
  .card img {{ display: block; width: 532px; height: 399px; object-fit: cover; }}
  .cap {{ display: flex; align-items: center; gap: 12px; padding: 13px 2px 12px; }}
  .cap-t {{ font-size: 23px; font-weight: 500; letter-spacing: .06em;
            text-indent: .06em; color: #241f1b; }}
  .cap-d {{ flex: 1 1 auto; height: 1px; background: rgba(36,31,27,.2); }}
  .cps {{ display: block; flex: 0 0 auto; }}
  .cap-y {{ flex: 0 0 auto; font-size: 14px; letter-spacing: .1em; text-indent: .1em;
            color: #4a423a; }}

  /* ---- 章节卡 ---- */
  .chapter {{ position: absolute; inset: 0; }}
  .chw {{ position: absolute; inset: 0; }}
  /* 只压左下角。两件事同时要满足:
     1) 不能铺满屏,否则盖住顶上的方位尺(会判 text_occluded,画面里也确实压灰一层);
     2) 渐变必须在盒子边界之前就化到全透明 —— 之前用 linear-gradient(to top right)
        在盒子左上角还剩一点不透明度,盒子上边缘就露出一道横向硬边(实测可见)。
        改成锚在左下角的径向渐变,78% 处归零,盒子边界外全透明。 */
  .ch-scrim {{ position: absolute; left: 0; bottom: 0; width: 100%; height: 60%;
               background: radial-gradient(58% 115% at 2% 100%,
                           rgba(7,8,12,.96) 0%, rgba(7,8,12,.86) 26%,
                           rgba(7,8,12,.4) 52%, rgba(7,8,12,0) 78%); }}
  .ch-body {{ position: absolute; left: 88px; bottom: 92px; display: flex;
              align-items: center; gap: 22px; }}
  .ch-rule {{ width: 2px; height: 76px; background: #c8402f;
              box-shadow: 0 0 14px rgba(200,64,47,.7); }}
  .ch-time {{ font-size: 21px; letter-spacing: .3em; text-indent: .3em;
              color: #f7f4ef; }}
  .ch-name {{ margin-top: 6px; font-size: 48px; font-weight: 600;
              letter-spacing: .16em; text-indent: .16em; color: #f6f2ea; }}

  /* ---- 首尾卡 ---- */
  #titlecard, #endcard {{ position: absolute; inset: 0; }}
  /* 满屏遮罩必须在 CSS 里就 opacity:0,交给时间轴淡进来。
     直接写成可见的,hyperframes check 会判 gsap_fullscreen_overlay_starts_visible:
     渲染器在时间轴生效之前有可能先出一帧被它盖死的画面。 */
  #tt-scrim {{ position: absolute; inset: 0; background: rgba(7,8,12,.74); opacity: 0; }}
  #ed-scrim {{ position: absolute; inset: 0; background: rgba(7,8,12,.92); opacity: 0; }}
  #tt-wrap, #ed-wrap {{ position: absolute; inset: 0; display: flex;
                        flex-direction: column; align-items: center;
                        justify-content: center; }}
  #tt-main {{ font-size: 66px; font-weight: 600; letter-spacing: .3em;
              text-indent: .3em; color: #f6f2ea; }}
  #tt-rule {{ width: 220px; height: 1px; margin: 26px 0 24px;
              background: linear-gradient(to right, transparent, #c8402f 22%,
                                          #c8402f 78%, transparent); }}
  #tt-sub {{ font-size: 21px; letter-spacing: .22em; text-indent: .22em;
             color: rgba(246,242,234,.78); }}
  #ed-names {{ font-size: 52px; font-weight: 500; letter-spacing: .24em;
               text-indent: .24em; color: #f6f2ea; }}
  #ed-date {{ margin-top: 20px; font-size: 19px; letter-spacing: .28em;
              text-indent: .28em; color: rgba(246,242,234,.7); }}
  #ed-rule {{ width: 260px; height: 1px; margin: 34px 0 30px;
              background: linear-gradient(to right, transparent, rgba(200,64,47,.9) 22%,
                                          rgba(200,64,47,.9) 78%, transparent); }}
  #ed-stat {{ font-size: 20px; letter-spacing: .14em; text-indent: .14em;
              color: rgba(246,242,234,.84); }}
  #ed-mark {{ margin-top: 44px; font-size: 14px; letter-spacing: .52em;
              text-indent: .52em; color: rgba(246,242,234,.42); }}
</style>
</head>
<body>

<div id="root" data-composition-id="{comp}" data-start="0" data-duration="{total}"
     data-width="{w}" data-height="{h}">
  {body}
</div>

<script>
  window.__timelines = window.__timelines || {{}};
  const tl = gsap.timeline({{ paused: true }});
  {timeline}
  window.__timelines["{comp}"] = tl;
</script>

</body>
</html>
"""


if __name__ == "__main__":
    build()
