#!/usr/bin/env python3
"""
film/make_bgm.py -- 一键成片的背景音乐,现场合成,不下载任何素材。

为什么自己合成:
  media-use 的两条正路都走不通 —— HeyGen 音乐库要登录(本机 `hyperframes auth status`
  = Not signed in,~/.heygen 不存在),本地生成的 Lyria 要 GEMINI_API_KEY、MusicGen 要
  `pip install transformers torch`,而这个项目的铁律是零新依赖。
  网上随手抓一段"免费 BGM"的授权说不清楚,宁可不用。
  所以这段音乐是本文件用 numpy 逐样本算出来的原创片段,版权干净、可复现、离线可重跑。

音乐本身:C 大调,C - G - Am - F 四小节循环(每和弦 4 秒),三层
  1. 垫底和声 pad   正弦叠泛音 + 左右微失谐,慢起慢收
  2. 八音盒旋律      C 大调五声音阶,快起指数衰减,一个音一个音落下来
  3. 低频长音 drone  和弦根音低两个八度,很轻,只负责托住

段落按成片结构走(不是死循环):开头只有 pad(压在标题卡下面),中段进旋律,
结尾旋律退场、pad 收住。全程无随机数,同样的参数每次跑出来逐样本一致。

跑法:
    .venv/bin/python film/make_bgm.py --duration 79.5 --out film/assets/bgm.mp3
"""
import argparse
import os
import subprocess
import tempfile
import wave

import numpy as np

FFMPEG = "/opt/homebrew/bin/ffmpeg"
SR = 44100

# 音名 -> 频率(十二平均律,A4=440)
def _f(name):
    step = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    letter, octv = name[0], int(name[-1])
    semis = step[letter] + (1 if "#" in name else 0)
    n = semis + 12 * (octv - 4) - 9        # 相对 A4 的半音数
    return 440.0 * (2.0 ** (n / 12.0))


CHORD_S = 4.0        # 每个和弦占 4 秒
CYCLE_S = CHORD_S * 4

# 每个和弦:(pad 的三个音, drone 的根音)
PROGRESSION = [
    (["C4", "E4", "G4"], "C2"),
    (["B3", "D4", "G4"], "G2"),
    (["A3", "C4", "E4"], "A2"),
    (["A3", "C4", "F4"], "F2"),
]

# 每个和弦里旋律怎么走:(和弦内偏移秒, 音名, 力度)
PHRASES = [
    [(0.00, "E5", 0.9), (0.75, "G5", 0.7), (1.75, "C6", 1.0), (3.00, "A5", 0.6)],
    [(0.00, "D5", 0.8), (1.00, "G5", 0.9), (2.50, "D6", 0.7)],
    [(0.00, "A5", 0.9), (1.25, "E5", 0.7), (2.50, "C6", 0.8)],
    [(0.00, "C5", 0.8), (1.00, "A5", 0.9), (2.50, "G5", 0.7), (3.25, "E5", 0.5)],
]

# 第 n 个循环里旋律的密度(0 = 整轮不弹)。开头留白给标题卡,结尾让它散掉。
CYCLE_DENSITY = [0.0, 0.75, 1.0, 1.0, 0.6, 0.35]


def _pad_voice(t, freq, amp):
    """垫底和声的一个音:基音 + 前四个泛音,泛音越高越轻(听感上等于自带低通)。"""
    out = np.zeros_like(t)
    for k, w in ((1, 1.0), (2, 0.34), (3, 0.14), (4, 0.06)):
        out += w * np.sin(2 * np.pi * freq * k * t)
    return out * amp


def _env_chord(n):
    """一个和弦的包络:1.2s 慢起,末尾 1.0s 收,中间平。相邻和弦互相叠住,不会有断口。"""
    e = np.ones(n)
    a = min(int(1.2 * SR), n // 2)
    r = min(int(1.0 * SR), n // 2)
    e[:a] = np.linspace(0, 1, a) ** 1.6
    e[-r:] = np.linspace(1, 0, r) ** 1.4
    return e


def _bell(freq, dur, amp):
    """八音盒音色:5ms 起音 + 指数衰减,加两个泛音和一个非整数倍分音(金属味)。"""
    n = int(dur * SR)
    t = np.arange(n) / SR
    env = np.exp(-t * 2.6)
    atk = min(int(0.005 * SR), n)
    env[:atk] *= np.linspace(0, 1, atk)
    sig = (np.sin(2 * np.pi * freq * t)
           + 0.34 * np.sin(2 * np.pi * freq * 2 * t) * np.exp(-t * 4.0)
           + 0.11 * np.sin(2 * np.pi * freq * 3 * t) * np.exp(-t * 6.0)
           + 0.05 * np.sin(2 * np.pi * freq * 4.2 * t) * np.exp(-t * 9.0))
    return sig * env * amp


def synth(duration_s):
    """返回 (n, 2) 的浮点立体声。"""
    n = int(duration_s * SR)
    left = np.zeros(n)
    right = np.zeros(n)

    # --- 1/3. pad + drone:一个和弦一个和弦铺过去 ---
    ci = 0
    start = 0.0
    while start < duration_s:
        notes, root = PROGRESSION[ci % len(PROGRESSION)]
        i0 = int(start * SR)
        seg_n = min(int(CHORD_S * SR), n - i0)
        if seg_n <= 0:
            break
        t = np.arange(seg_n) / SR
        env = _env_chord(seg_n)

        segL = np.zeros(seg_n)
        segR = np.zeros(seg_n)
        for vi, name in enumerate(notes):
            f0 = _f(name)
            # 左右各失谐一点点(约 ±0.12%),两耳听到的不完全一样 -> 声场自然变宽
            det = 0.0012 * (1 + vi * 0.4)
            segL += _pad_voice(t, f0 * (1 - det), 0.30)
            segR += _pad_voice(t, f0 * (1 + det), 0.30)

        fr = _f(root)
        drone = 0.22 * (np.sin(2 * np.pi * fr * t) + 0.25 * np.sin(2 * np.pi * fr * 2 * t))
        segL += drone
        segR += drone

        left[i0:i0 + seg_n] += segL * env
        right[i0:i0 + seg_n] += segR * env
        start += CHORD_S
        ci += 1

    # --- 2/3. 八音盒旋律 ---
    ci = 0
    start = 0.0
    while start < duration_s:
        cycle = int(start // CYCLE_S)
        dens = CYCLE_DENSITY[cycle] if cycle < len(CYCLE_DENSITY) else CYCLE_DENSITY[-1]
        if dens > 0:
            phrase = PHRASES[ci % len(PHRASES)]
            # 密度 <1 时按力度从大到小保留,弱音先被拿掉 —— 听起来是"变稀",不是"变碎"
            keep = max(1, int(round(len(phrase) * dens)))
            chosen = sorted(sorted(phrase, key=lambda p: -p[2])[:keep])
            for k, (off, name, vel) in enumerate(chosen):
                i0 = int((start + off) * SR)
                if i0 >= n:
                    break
                b = _bell(_f(name), 2.2, 0.16 * vel * min(1.0, dens + 0.3))
                b = b[:n - i0]
                # 相邻的音左右轮着落,像有人在两边轻轻敲
                pan = 0.42 + 0.16 * (1 if k % 2 == 0 else -1)
                left[i0:i0 + len(b)] += b * (1 - pan)
                right[i0:i0 + len(b)] += b * pan
        start += CHORD_S
        ci += 1

    stereo = np.stack([left, right], axis=1)

    # --- 3/3. 整体进出场 + 归一化 ---
    fi, fo = int(2.5 * SR), int(4.0 * SR)
    stereo[:fi] *= np.linspace(0, 1, fi)[:, None] ** 1.5
    stereo[-fo:] *= np.linspace(1, 0, fo)[:, None] ** 1.2
    peak = float(np.abs(stereo).max()) or 1.0
    return stereo / peak * 0.82


def write_wav(stereo, path):
    pcm = (np.clip(stereo, -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def main():
    ap = argparse.ArgumentParser(description="一键成片 BGM(本地合成)")
    ap.add_argument("--duration", type=float, default=79.5)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                  "assets", "bgm.mp3"))
    a = ap.parse_args()

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    stereo = synth(a.duration)
    tmp = tempfile.mktemp(suffix=".wav")
    write_wav(stereo, tmp)
    try:
        # 干声太"电子",过一层短混响 + 6.5k 低通把齿感磨掉,再压一层限幅统一响度
        subprocess.run([
            FFMPEG, "-y", "-loglevel", "error", "-i", tmp,
            "-af", ("aecho=0.85:0.75:60|130|240:0.32|0.2|0.11,"
                    "lowpass=f=6500,highpass=f=45,"
                    "alimiter=limit=0.92,"
                    "loudnorm=I=-19:TP=-2.0:LRA=9"),
            "-c:a", "libmp3lame", "-b:a", "160k", a.out,
        ], check=True)
    finally:
        os.path.exists(tmp) and os.remove(tmp)
    print(f"{a.out}  {os.path.getsize(a.out) / 1024:.0f} KB  {a.duration}s")


if __name__ == "__main__":
    main()
