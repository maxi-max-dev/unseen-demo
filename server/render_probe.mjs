#!/usr/bin/env node
/**
 * server/render_probe.mjs -- 自检环【第二闸：无头渲染探针】
 *
 * 干的事:起一个无头 Chrome,把 viewer/walk.html 真跑一遍,不靠人眼判断页面到底出没出画面。
 *   1. 临时 user-data-dir 起 Chrome,裸 CDP 协议(Node 内置 WebSocket)连上去,不装 puppeteer。
 *   2. 收 console 报错(Runtime.consoleAPICalled type=error)和页面异常(Runtime.exceptionThrown)。
 *   3. 轮询等 window.__psmWalk 出现 = 渲染起来了;同时盯 walk.html 的错误卡(#cardError.on)
 *      = 页面自己认怂了,立刻判失败不用干等 30 秒。
 *   4. 可选 --walk-ms:真实派发 W 键并确认相机发生位移，再从移动后的位置截图。
 *   5. 每个 yaw:调 __psmWalk.setYaw(deg) -> 等 3 个真实 rAF 帧 -> Page.captureScreenshot。
 *   6. 截图在 Node 里用 zlib 自解 PNG 算 meanLuma/stdLuma,黑屏(WebGL 没出画面)当场露馅。
 *   7. 顺手把照片钉点 sprite 投影到屏幕坐标回传,给第三闸(语义)当锚点。
 *
 * 跑法:
 *   node server/render_probe.mjs --url "<页面url>" --out "<输出目录绝对路径>" --prefix a1 --yaws 0,120,240 [--walk-ms 400]
 *
 * 输出契约:stdout 只有一行 JSON(= report.json 里的 gates.render 对象),调试信息全走 stderr。
 * 零新依赖:只用 node 内置(child_process/fs/net/zlib/path/os)+ 全局 WebSocket(node >= 22)。
 */
import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import zlib from "node:zlib";

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const READY_TIMEOUT_MS = 30000; // 就绪总超时:第 3 步轮询的上限
const VIEWPORT = { w: 1280, h: 800 };
const TEAR_ANISOTROPY_MAX = 1.45;
const TEAR_VERTICAL_SHARE_MAX = 0.55;

function log(...args) { console.error("[probe]", ...args); } // 调试信息一律 stderr

// ============================================================
// 命令行参数
// ============================================================
function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i++) {
    if (!argv[i].startsWith("--")) continue;
    const key = argv[i].slice(2);
    const val = argv[i + 1] && !argv[i + 1].startsWith("--") ? argv[++i] : "1";
    out[key] = val;
  }
  return out;
}

// ============================================================
// PNG 亮度统计:Chrome 截图是 8bit 非隔行 RGB/RGBA,自己 inflate + 反滤波就够
// (页面 renderer 没开 preserveDrawingBuffer,canvas.toDataURL() 拿不到画面,
//  所以只能走 CDP 截图 + 这里自解码这条路)
// ============================================================
function pngLumaStats(buf) {
  if (buf.length < 8 || buf.readUInt32BE(0) !== 0x89504e47) throw new Error("不是 PNG 数据");
  let off = 8, w = 0, h = 0, bitDepth = 0, colorType = 0, interlace = 0;
  const idat = [];
  while (off + 8 <= buf.length) {
    const len = buf.readUInt32BE(off);
    const type = buf.toString("ascii", off + 4, off + 8);
    const data = buf.subarray(off + 8, off + 8 + len);
    if (type === "IHDR") {
      w = data.readUInt32BE(0); h = data.readUInt32BE(4);
      bitDepth = data[8]; colorType = data[9]; interlace = data[12];
    } else if (type === "IDAT") idat.push(data);
    else if (type === "IEND") break;
    off += 12 + len; // 4 长度 + 4 类型 + data + 4 CRC
  }
  if (bitDepth !== 8 || interlace !== 0 || (colorType !== 2 && colorType !== 6)) {
    throw new Error(`PNG 格式不支持: bitDepth=${bitDepth} colorType=${colorType} interlace=${interlace}`);
  }
  const ch = colorType === 6 ? 4 : 3;
  const raw = zlib.inflateSync(Buffer.concat(idat));
  const stride = w * ch;
  const lumaPixels = new Float32Array(w * h);
  let prev = Buffer.alloc(stride), cur = Buffer.alloc(stride);
  let p = 0, n = 0, sum = 0, sumSq = 0;

  for (let y = 0; y < h; y++) {
    const filter = raw[p++];
    raw.copy(cur, 0, p, p + stride); p += stride;
    // PNG 逐行滤波器还原(0 无 / 1 左 / 2 上 / 3 平均 / 4 Paeth)
    if (filter === 1) {
      for (let i = ch; i < stride; i++) cur[i] = (cur[i] + cur[i - ch]) & 255;
    } else if (filter === 2) {
      for (let i = 0; i < stride; i++) cur[i] = (cur[i] + prev[i]) & 255;
    } else if (filter === 3) {
      for (let i = 0; i < stride; i++) {
        const a = i >= ch ? cur[i - ch] : 0;
        cur[i] = (cur[i] + ((a + prev[i]) >> 1)) & 255;
      }
    } else if (filter === 4) {
      for (let i = 0; i < stride; i++) {
        const a = i >= ch ? cur[i - ch] : 0, b = prev[i], c = i >= ch ? prev[i - ch] : 0;
        const pp = a + b - c, pa = Math.abs(pp - a), pb = Math.abs(pp - b), pc = Math.abs(pp - c);
        const pred = pa <= pb && pa <= pc ? a : (pb <= pc ? b : c);
        cur[i] = (cur[i] + pred) & 255;
      }
    }
    for (let x = 0; x < stride; x += ch) {
      const lum = 0.2126 * cur[x] + 0.7152 * cur[x + 1] + 0.0722 * cur[x + 2];
      sum += lum; sumSq += lum * lum; n++;
      lumaPixels[y * w + x / ch] = lum;
    }
    const swap = prev; prev = cur; cur = swap; // 这行做完 prev 才是"上一行"
  }
  const mean = n ? sum / n : 0;
  const variance = n ? Math.max(0, sumSq / n - mean * mean) : 0;

  // 几何撕裂指标：裁掉顶部 HUD 和底部署名后，统计水平/垂直一阶差分。
  // “竖向幕布”沿竖直方向延伸，因此跨 x 的变化(gx)会远强于跨 y 的变化(gy)。
  // q80 只让最强 20% 边缘参与方向占比，避免天空/墙面等平坦区域稀释信号。
  const x0 = Math.max(0, Math.min(w - 2, Math.round(w * 20 / 1280)));
  const x1 = Math.max(x0 + 2, Math.min(w, Math.round(w * 1260 / 1280)));
  const y0 = Math.max(0, Math.min(h - 2, Math.round(h * 100 / 800)));
  const y1 = Math.max(y0 + 2, Math.min(h, Math.round(h * 720 / 800)));
  let dxSum = 0, dxCount = 0, dySum = 0, dyCount = 0;
  for (let y = y0; y < y1; y++) {
    const row = y * w;
    for (let x = x0; x < x1 - 1; x++) {
      dxSum += Math.abs(lumaPixels[row + x + 1] - lumaPixels[row + x]);
      dxCount++;
    }
  }
  for (let y = y0; y < y1 - 1; y++) {
    const row = y * w, next = row + w;
    for (let x = x0; x < x1; x++) {
      dySum += Math.abs(lumaPixels[next + x] - lumaPixels[row + x]);
      dyCount++;
    }
  }
  const cellW = x1 - x0 - 1, cellH = y1 - y0 - 1;
  const magnitudes = new Float32Array(Math.max(0, cellW * cellH));
  let mi = 0;
  for (let y = y0; y < y1 - 1; y++) {
    const row = y * w, next = row + w;
    for (let x = x0; x < x1 - 1; x++) {
      const gx = Math.abs(lumaPixels[row + x + 1] - lumaPixels[row + x]);
      const gy = Math.abs(lumaPixels[next + x] - lumaPixels[row + x]);
      magnitudes[mi++] = Math.hypot(gx, gy);
    }
  }
  magnitudes.sort();
  let q80 = 0;
  if (magnitudes.length) {
    const pos = 0.8 * (magnitudes.length - 1);
    const lo = Math.floor(pos), hi = Math.ceil(pos);
    q80 = magnitudes[lo] + (magnitudes[hi] - magnitudes[lo]) * (pos - lo);
  }
  let strongCount = 0, verticalCount = 0;
  for (let y = y0; y < y1 - 1; y++) {
    const row = y * w, next = row + w;
    for (let x = x0; x < x1 - 1; x++) {
      const gx = Math.abs(lumaPixels[row + x + 1] - lumaPixels[row + x]);
      const gy = Math.abs(lumaPixels[next + x] - lumaPixels[row + x]);
      if (Math.hypot(gx, gy) > q80) {
        strongCount++;
        if (gx > 2 * gy) verticalCount++;
      }
    }
  }
  const dxMean = dxCount ? dxSum / dxCount : 0;
  const dyMean = dyCount ? dySum / dyCount : 0;
  const anisotropy = dxMean / Math.max(dyMean, 1e-6);
  const verticalShare = strongCount ? verticalCount / strongCount : 0;
  const geometryTear = anisotropy > TEAR_ANISOTROPY_MAX &&
    verticalShare > TEAR_VERTICAL_SHARE_MAX;
  return {
    meanLuma: +mean.toFixed(2),
    stdLuma: +Math.sqrt(variance).toFixed(2),
    width: w,
    height: h,
    dxMean: +dxMean.toFixed(3),
    dyMean: +dyMean.toFixed(3),
    anisotropy: +anisotropy.toFixed(3),
    edgeQ80: +q80.toFixed(3),
    verticalShare: +verticalShare.toFixed(3),
    geometryTear,
  };
}

// ============================================================
// 裸 CDP 客户端:一条 WebSocket 收发 {id,method,params}
// ============================================================
class CDP {
  constructor(ws) {
    this.ws = ws; this.id = 0; this.pending = new Map(); this.handlers = [];
    ws.addEventListener("message", (ev) => {
      let msg; try { msg = JSON.parse(ev.data); } catch { return; }
      if (msg.id !== undefined && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        msg.error ? reject(new Error(msg.error.message || JSON.stringify(msg.error))) : resolve(msg.result);
      } else if (msg.method) {
        for (const fn of this.handlers) fn(msg.method, msg.params);
      }
    });
  }
  on(fn) { this.handlers.push(fn); }
  send(method, params = {}, timeoutMs = 15000) {
    const id = ++this.id;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`CDP 超时: ${method}`));
      }, timeoutMs);
      this.pending.set(id, {
        resolve: (r) => { clearTimeout(timer); resolve(r); },
        reject: (e) => { clearTimeout(timer); reject(e); },
      });
    });
  }
  // 在页面里跑一段表达式,直接要值(页面里的 THREE / __psmWalk 都是全局的)
  async evaluate(expression, { awaitPromise = false, timeoutMs = 15000 } = {}) {
    const r = await this.send("Runtime.evaluate",
      { expression, returnByValue: true, awaitPromise }, timeoutMs);
    if (r.exceptionDetails) {
      throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text || "页面表达式异常");
    }
    return r.result?.value;
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function freePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.on("error", reject);
    srv.listen(0, "127.0.0.1", () => {
      const port = srv.address().port;
      srv.close(() => resolve(port));
    });
  });
}

// 等 Chrome 的 DevTools HTTP 端口起来,拿到页面 target 的 ws 地址
async function waitForPageWs(port, deadlineMs) {
  const until = Date.now() + deadlineMs;
  let lastErr = "";
  while (Date.now() < until) {
    try {
      const list = await fetch(`http://127.0.0.1:${port}/json/list`).then((r) => r.json());
      const page = list.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
      if (page) return page.webSocketDebuggerUrl;
      lastErr = "还没有 page target";
    } catch (e) { lastErr = String(e.message || e); }
    await sleep(120);
  }
  throw new Error(`Chrome 调试端口没起来: ${lastErr}`);
}

function connectWs(url) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(url);
    ws.addEventListener("open", () => resolve(ws), { once: true });
    ws.addEventListener("error", () => reject(new Error("WebSocket 连不上 CDP")), { once: true });
  });
}

// ============================================================
// 主流程
// ============================================================
async function main() {
  const args = parseArgs(process.argv.slice(2));
  const url = args.url;
  const outDir = args.out;
  const prefix = args.prefix || "a1";
  const yaws = String(args.yaws || "0").split(",").map((s) => Number(s.trim())).filter((n) => Number.isFinite(n));
  const walkMs = Math.max(0, Math.min(2000, Number(args["walk-ms"]) || 0));
  const expectedMode = /^(flat|depth)$/.test(args["expect-mode"] || "")
    ? args["expect-mode"] : "";
  if (!url || !outDir) throw new Error("用法: --url <页面url> --out <输出目录绝对路径> [--prefix a1] [--yaws 0,120,240]");
  fs.mkdirSync(outDir, { recursive: true });

  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), "psm-probe-"));
  const port = await freePort();
  // flag 组合是本机实测消融出来的(Chrome 150 / Apple Silicon),不是照抄网上配方:
  //   - --headless=new 下 Chrome 直接走真 GPU,three.js 的 WebGL 本来就出画面;
  //     --use-gl=angle / --use-angle=swiftshader 加不加,截图亮度一模一样 = 这机器上是空转,所以不加。
  //   - --enable-unsafe-swiftshader 留着当保险:一旦落到没 GPU 的机器(等价于 --disable-gpu),
  //     不带这个 flag 新版 Chrome 会直接拒绝软件光栅 WebGL,页面当场弹"不支持 WebGL"错误卡;
  //     带上就能软渲染跑通。实测过 --disable-gpu 两种情况,差别就在这一个 flag。
  //   - 千万别顺手加 --disable-gpu,那是黑屏的直通车。
  const flags = [
    "--headless=new",
    `--remote-debugging-port=${port}`,
    `--window-size=${VIEWPORT.w},${VIEWPORT.h}`,
    "--hide-scrollbars",
    "--no-first-run",
    "--no-default-browser-check",
    `--user-data-dir=${userDataDir}`,
    "--enable-unsafe-swiftshader",
    "--mute-audio",
    "about:blank",
  ];

  const chromeLog = [];
  // detached:true = Chrome 自己一个进程组。Chrome 是一坨进程(主进程 + GPU/渲染/网络 helper),
  // 只 kill 主进程 helper 会赖着不走,所以收尾按整组 kill(-pid)。
  const chrome = spawn(CHROME, flags, { stdio: ["ignore", "ignore", "pipe"], detached: true });
  chrome.stderr.on("data", (d) => { if (chromeLog.length < 80) chromeLog.push(String(d).trim()); });

  const cleanup = () => {
    try { chrome.stderr.destroy(); } catch { /* 管子早断了就算了 */ }
    try { process.kill(-chrome.pid, "SIGKILL"); } catch { /* 进程组已经没了就算了 */ }
    try { fs.rmSync(userDataDir, { recursive: true, force: true }); } catch { /* 删不掉也不影响结论 */ }
  };
  process.on("exit", cleanup);

  const gate = {
    ok: false, readyMs: null, shots: [],
    consoleErrors: [], pageErrors: [], error: null, sprites: [], movement: null,
    renderMode: null, interactionMode: null, maxWalkRadius: null,
    fov: null, pitchLimitDeg: null, cameraToMeshCenter: null,
  };

  try {
    const wsUrl = await waitForPageWs(port, 15000);
    log("CDP 已连:", wsUrl);
    const cdp = new CDP(await connectWs(wsUrl));

    // 报错收集:console.error 走 consoleAPICalled,未捕获异常走 exceptionThrown
    cdp.on((method, params) => {
      if (method === "Runtime.consoleAPICalled" && params.type === "error") {
        const text = (params.args || [])
          .map((a) => a.value ?? a.description ?? a.unserializableValue ?? "")
          .join(" ").trim();
        gate.consoleErrors.push(text || "(空 console.error)");
      } else if (method === "Runtime.exceptionThrown") {
        const d = params.exceptionDetails || {};
        gate.pageErrors.push(d.exception?.description || d.text || "(未知页面异常)");
      }
    });
    await cdp.send("Runtime.enable");
    await cdp.send("Page.enable");

    const t0 = Date.now();
    await cdp.send("Page.navigate", { url });

    // ---------------- 等就绪:__psmWalk 出现 = 成功;错误卡亮 = 失败,立刻返回 ----------------
    const PROBE_STATE = `(function () {
      var err = document.getElementById('cardError');
      if (err && err.classList.contains('on')) {
        return JSON.stringify({ state: 'error',
          msg: (document.getElementById('errMsg') || {}).textContent || '',
          sub: (document.getElementById('errSub') || {}).textContent || '' });
      }
      if (window.__psmWalk && window.__psmWalk.camera) return JSON.stringify({ state: 'ready' });
      return JSON.stringify({ state: 'wait' });
    })()`;

    let ready = false, pageErrCard = null;
    while (Date.now() - t0 < READY_TIMEOUT_MS) {
      let st;
      try { st = JSON.parse(await cdp.evaluate(PROBE_STATE) || '{"state":"wait"}'); }
      catch { st = { state: "wait" }; } // 导航切换瞬间 evaluate 可能扑空,当没就绪继续等
      if (st.state === "ready") { ready = true; break; }
      if (st.state === "error") { pageErrCard = st; break; }
      await sleep(200);
    }
    gate.readyMs = Date.now() - t0;

    if (pageErrCard) throw new Error(`页面报错卡: ${pageErrCard.msg}${pageErrCard.sub ? " / " + pageErrCard.sub : ""}`);
    if (!ready) throw new Error(`就绪超时(${READY_TIMEOUT_MS}ms):window.__psmWalk 一直没出现`);
    log("就绪耗时", gate.readyMs, "ms");

    const renderState = await cdp.evaluate(`(function(){
      var w = window.__psmWalk;
      if (!w || !w.camera || !w.mesh) return null;
      var dx = w.camera.position.x - w.mesh.position.x;
      var dy = w.camera.position.y - w.mesh.position.y;
      var dz = w.camera.position.z - w.mesh.position.z;
      return {
        mode: w.renderMode || null,
        interactionMode: w.interactionMode || null,
        maxWalkRadius: typeof w.maxWalkRadius === 'number' ? w.maxWalkRadius : null,
        fov: typeof w.fov === 'number' ? w.fov : null,
        pitchLimitDeg: typeof w.pitchLimitDeg === 'number' ? w.pitchLimitDeg : null,
        cameraToMeshCenter: Math.sqrt(dx*dx + dy*dy + dz*dz)
      };
    })()`);
    gate.renderMode = renderState?.mode || null;
    gate.interactionMode = renderState?.interactionMode || null;
    gate.maxWalkRadius = renderState?.maxWalkRadius ?? null;
    gate.fov = renderState?.fov ?? null;
    gate.pitchLimitDeg = renderState?.pitchLimitDeg ?? null;
    gate.cameraToMeshCenter = renderState
      ? +renderState.cameraToMeshCenter.toFixed(4) : null;

    // 桌面端会盖一张"点击画面开始漫游"的半透明遮罩(.center-card#cardLock,背景 rgba(0,0,0,.5)),
    // 它会把整屏压暗一半还挡住中间 —— 那是交互提示不是渲染结果,截图前收掉,
    // 只动这一张卡,错误卡绝不碰(碰了就等于把失败信号抹掉)。
    await cdp.evaluate(`(function(){ var c=document.getElementById('cardLock');
      if (c) c.classList.remove('on'); return 1; })()`);

    // 等 N 个真实渲染帧(rAF 链,不用固定 sleep 猜);页面 renderer 用的 setAnimationLoop,rAF 是活的
    const waitFrames = (n) => cdp.evaluate(`new Promise(function(res){
      var i = 0;
      function step(){ if (++i >= ${n}) res(i); else requestAnimationFrame(step); }
      requestAnimationFrame(step);
      setTimeout(function(){ res(-1); }, 3000); // rAF 万一被节流也别把探针卡死
    })`, { awaitPromise: true, timeoutMs: 8000 });

    // 可选的真实移动检查。直接改 camera.position 只能证明调试出口能写，不能证明
    // keydown → keys.KeyW → tick → clampWalk 这条用户实际走的链路有效，所以通过 CDP
    // 派发一段 W 键。截图随后从移动后的位置采集，也能把“原点正常、一走就撕裂”抓出来。
    if (walkMs > 0) {
      const readCamera = () => cdp.evaluate(`(function(){
        var c = window.__psmWalk && window.__psmWalk.camera;
        return c ? { x:c.position.x, y:c.position.y, z:c.position.z } : null;
      })()`);
      const before = await readCamera();
      await cdp.send("Input.dispatchKeyEvent", {
        type: "keyDown", key: "w", code: "KeyW",
        windowsVirtualKeyCode: 87, nativeVirtualKeyCode: 87,
      });
      // 用真实帧数驱动，避免多个 headless Chrome 并跑时后台 rAF 降频，
      // 500ms 墙钟时间里偶尔只渲染一帧而把正常移动误判成失败。
      const movementFrames = await waitFrames(
        Math.max(3, Math.min(60, Math.round(walkMs / (1000 / 60))))
      );
      await cdp.send("Input.dispatchKeyEvent", {
        type: "keyUp", key: "w", code: "KeyW",
        windowsVirtualKeyCode: 87, nativeVirtualKeyCode: 87,
      });
      await waitFrames(3);
      const after = await readCamera();
      const movedDistance = before && after
        ? Math.hypot(after.x - before.x, after.z - before.z) : 0;
      gate.movement = {
        requestedMs: walkMs,
        frames: movementFrames,
        before,
        after,
        movedDistance: +movedDistance.toFixed(3),
        ok: movedDistance >= 0.05,
      };
      log(`移动检查 ${gate.movement.ok ? "通过" : "失败"}: ${gate.movement.movedDistance}m`);
    }

    // 把照片钉点 sprite 的世界坐标投到屏幕像素坐标(页面里 THREE 是全局的,r128)。
    // 每个 yaw 采一次:onScreen 本来就跟朝向绑定,只在一个朝向采会把"其实转过去就能看到的钉子"
    // 全报成 false(demo 场景 yaw=0 时三张照片确实都在身后)。
    const SPRITE_PROJECT = `(function () {
      var w = window.__psmWalk; if (!w || !w.photoSprites) return [];
      w.camera.updateMatrixWorld();
      var out = [], v = new THREE.Vector3();
      // 钉点正好压在相机平面上时 w≈0,投影会炸出 1e18 这种数;夹一下,只留方向不留天文数字
      var clamp = function (n) { return isFinite(n) ? Math.max(-99999, Math.min(99999, Math.round(n))) : 0; };
      for (var i = 0; i < w.photoSprites.length; i++) {
        w.photoSprites[i].getWorldPosition(v);
        v.project(w.camera);
        var x = (v.x * 0.5 + 0.5) * window.innerWidth;
        var y = (-v.y * 0.5 + 0.5) * window.innerHeight;
        // v.z 落在 (-1,1) 才是在相机前方;身后的点投影出来会翻号+爆量程,坐标没意义
        var on = v.z > -1 && v.z < 1 &&
          x >= 0 && x <= window.innerWidth && y >= 0 && y <= window.innerHeight;
        out.push({ i: i, x: clamp(x), y: clamp(y), onScreen: !!on });
      }
      return out;
    })()`;

    // ---------------- 逐 yaw 转向 + 截图 ----------------
    for (const yaw of yaws) {
      await cdp.evaluate(`window.__psmWalk.setYaw(${yaw})`);
      const frames = await waitFrames(3);
      if (frames === -1) log(`yaw=${yaw} rAF 等帧超时,仍照常截图`);
      const shotName = `${prefix}_yaw${String(((yaw % 360) + 360) % 360).padStart(3, "0")}.png`;
      const abs = path.join(outDir, shotName);
      const { data } = await cdp.send("Page.captureScreenshot", { format: "png" }, 20000);
      const buf = Buffer.from(data, "base64");
      fs.writeFileSync(abs, buf);

      let stats;
      try { stats = pngLumaStats(buf); }
      catch (e) { stats = { meanLuma: null, stdLuma: null, decodeError: String(e.message || e) }; }
      const black = stats.meanLuma !== null && stats.meanLuma < 8 && stats.stdLuma < 4;
      const shotSprites = (await cdp.evaluate(SPRITE_PROJECT)) || [];
      gate.shots.push({
        yaw,
        file: `${path.basename(outDir)}/${shotName}`, // 相对路径,和 report.json 里的 shots/xxx.png 口径一致
        abs,
        meanLuma: stats.meanLuma, stdLuma: stats.stdLuma, black,
        dxMean: stats.dxMean, dyMean: stats.dyMean,
        anisotropy: stats.anisotropy, edgeQ80: stats.edgeQ80,
        verticalShare: stats.verticalShare, geometryTear: !!stats.geometryTear,
        sprites: shotSprites, // 这一张图里各钉点的像素坐标,给第三闸对图用
        ...(stats.decodeError ? { decodeError: stats.decodeError } : {}),
      });
      log(`yaw=${yaw} -> ${shotName} meanLuma=${stats.meanLuma} stdLuma=${stats.stdLuma} black=${black}` +
        ` tear=${!!stats.geometryTear} aniso=${stats.anisotropy} vertical=${stats.verticalShare}` +
        ` 钉点在画面内 ${shotSprites.filter((s) => s.onScreen).length}/${shotSprites.length}`);
    }

    // 顶层 sprites = 逐张汇总:onScreen 表示"这几个朝向里至少有一个能看到它",
    // 坐标取第一次看到它的那一张(都没看到就用第一张的坐标,方便定位它跑哪去了)
    if (gate.shots.length) {
      gate.sprites = gate.shots[0].sprites.map((first, i) => {
        const seen = gate.shots.map((s) => s.sprites[i]).find((s) => s && s.onScreen);
        return seen || first;
      });
    }

    // 闸门口径:出了图 + 没黑屏 + 没页面异常,才算这一闸过
    const anyBlack = gate.shots.some((s) => s.black || s.meanLuma === null);
    const anyGeometryTear = gate.shots.some((s) => s.geometryTear);
    const movementOk = !gate.movement || gate.movement.ok;
    const modeOk = !expectedMode || gate.renderMode === expectedMode;
    const originOk = gate.cameraToMeshCenter !== null && gate.cameraToMeshCenter <= 0.01;
    gate.ok = gate.shots.length === yaws.length && !anyBlack && !anyGeometryTear &&
      gate.pageErrors.length === 0 && movementOk && modeOk && originOk;
    if (!gate.ok && !gate.error) {
      gate.error = anyBlack ? "截图疑似黑屏/无法解码,WebGL 可能没出画面"
        : (anyGeometryTear ? "截图出现强烈竖向几何撕裂(幕布/尖刺)"
          : (gate.pageErrors.length ? "页面抛了未捕获异常"
          : (!modeOk ? `渲染模式不符:期待 ${expectedMode},实际 ${gate.renderMode}`
            : (!originOk ? `相机没有位于全景光心:偏移 ${gate.cameraToMeshCenter}`
              : (!movementOk ? "W 键移动链路没有让相机发生位移" : "截图数量不足")))));
    }
  } catch (e) {
    gate.ok = false;
    gate.error = String(e.message || e);
    log("失败:", gate.error);
    if (chromeLog.length) log("Chrome stderr 末尾:", chromeLog.slice(-3).join(" | "));
  } finally {
    cleanup();
  }

  // stdout 只此一行。写完直接退:Chrome 的子进程句柄和 fetch 的 keep-alive socket 会把
  // event loop 吊住约 15 秒(实测失败路径 30s 的活儿要跑满 46s),自检环要反复调这支探针,
  // 这段空转白等不起。等 write 回调确认刷完再退,不会截断输出。
  process.stdout.write(JSON.stringify(gate) + "\n", () => process.exit(0));
}

main().catch((e) => {
  process.stdout.write(JSON.stringify({
    ok: false, readyMs: null, shots: [], consoleErrors: [], pageErrors: [],
    error: `探针自身崩了: ${String(e.message || e)}`, sprites: [],
  }) + "\n");
  process.exit(1);
});
