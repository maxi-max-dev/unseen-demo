// 压测军团的自建 CDP 驱动。仿 tools/acceptance.mjs 的 Tab 模式(只读复用思路,没有改那个文件一个字),
// 额外加:触摸模拟与宽度解耦(768 宽也能强制开触摸)、localStorage 读写、back()/reload()、
// waitFor() 轮询(用来判断"卡死"而不是傻等)、网络请求按 method+host 分类(用于验证 mock 不发真实写请求)。
//
//   node tools/stress/xxx.mjs   (由上层 run.mjs 等脚本 import 这个文件用)
//
import { spawn, execSync } from "node:child_process";
import { writeFileSync, mkdirSync, readFileSync } from "node:fs";
import { dirname } from "node:path";

export const PORT = process.env.STRESS_CDP_PORT || 9471;
export const PROFILE = "/private/tmp/claude-501/-/12c7c2dc-b0ab-4856-aaa2-cabefdac33a8/scratchpad/stress-chrome-" + PORT;
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function boot() {
  try { if ((await fetch(`http://127.0.0.1:${PORT}/json/version`)).ok) return "reused"; } catch {}
  mkdirSync(PROFILE, { recursive: true });
  spawn(CHROME, ["--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`,
    "--use-gl=angle", "--use-angle=swiftshader",
    "--no-first-run", "--no-default-browser-check", "--window-size=1280,900"],
    { detached: true, stdio: "ignore" }).unref();
  for (let i = 0; i < 80; i++) {
    await sleep(250);
    try { if ((await fetch(`http://127.0.0.1:${PORT}/json/version`)).ok) return "booted"; } catch {}
  }
  throw new Error("压测用 Chrome 起不来");
}

export async function killAll() {
  try { execSync(`pkill -f "remote-debugging-port=${PORT}"`); } catch {}
}

let _id = 0;
// 真实写请求的判定:除本机 127.0.0.1:PORT(静态服务)以外,任何 method != GET/HEAD 的请求,
// 或任何指向真实 OSS 桶(oss-cn-hangzhou.aliyuncs.com)的请求,都记进 writes[]。
const OSS_HOST = "psm-advx-2026.oss-cn-hangzhou.aliyuncs.com";

export class Tab {
  constructor(ws) { this.ws = ws; this.waiters = new Map(); this.events = []; this.reqMeta = new Map(); }
  static async open() {
    const r = await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: "PUT" });
    const t = await r.json();
    const ws = new WebSocket(t.webSocketDebuggerUrl);
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
    const tab = new Tab(ws); tab.id = t.id;
    ws.onmessage = (m) => {
      const d = JSON.parse(m.data);
      if (d.id && tab.waiters.has(d.id)) { tab.waiters.get(d.id)(d); tab.waiters.delete(d.id); }
      else if (d.method) tab.events.push(d);
    };
    for (const m of ["Page.enable", "Runtime.enable", "Network.enable", "DOM.enable", "Page.bringToFront"]) await tab.send(m);
    await tab.send("Emulation.setFocusEmulationEnabled", { enabled: true });
    await tab.send("Network.setCacheDisabled", { cacheDisabled: true });
    return tab;
  }
  send(method, params = {}) {
    const id = ++_id;
    return new Promise((res) => { this.waiters.set(id, res); this.ws.send(JSON.stringify({ id, method, params })); });
  }
  // 宽度和触摸解耦:任务书要求 320/390/430/768 四档【都】开触摸模拟,
  // 不能像 acceptance.mjs 那样拿 w<500 当触摸开关(768 会被判成桌面,拿不到摇杆/touch UI)。
  async metrics(w, h, touch = true) {
    await this.send("Emulation.setDeviceMetricsOverride",
      { width: w, height: h, deviceScaleFactor: 2, mobile: touch });
    return this.send("Emulation.setTouchEmulationEnabled",
      { enabled: touch, maxTouchPoints: touch ? 5 : 0 });
  }
  async go(url, settle = 1500) {
    this.events = [];
    await this.send("Page.navigate", { url });
    for (let i = 0; i < 90; i++) {
      await sleep(120);
      if ((await this.js("document.readyState")) === "complete") break;
    }
    await sleep(settle);
  }
  async back(settle = 1200) {
    this.events = [];
    await this.send("Page.navigate", { url: "javascript:history.back()" }).catch(() => {});
    // history.back() 是异步导航,用 js 直接触发更可靠
    await this.js("history.back()");
    await sleep(settle);
  }
  async reload(settle = 1500) {
    this.events = [];
    await this.send("Page.reload", { ignoreCache: true });
    for (let i = 0; i < 90; i++) {
      await sleep(120);
      if ((await this.js("document.readyState")) === "complete") break;
    }
    await sleep(settle);
  }
  js(expr) {
    return this.send("Runtime.evaluate", {
      expression: `(()=>{try{return JSON.stringify(${expr})}catch(e){return JSON.stringify("ERR:"+e.message)}})()`,
      returnByValue: true, userGesture: true
    }).then((r) => {
      try { return JSON.parse(r.result?.result?.value ?? "null"); } catch { return r.result?.result?.value; }
    });
  }
  // 卡死判定用:轮询一个表达式直到为真或超时。timeoutMs 内没等到就返回 false(调用方按"卡死"处理)。
  async waitFor(expr, timeoutMs = 10000, everyMs = 200) {
    const t0 = Date.now();
    while (Date.now() - t0 < timeoutMs) {
      const v = await this.js(expr);
      if (v) return true;
      await sleep(everyMs);
    }
    return false;
  }
  async setFiles(selector, files) {
    const d = await this.send("DOM.getDocument", { depth: 0 });
    const rootId = d.result?.root?.nodeId;
    if (!rootId) return "文档节点没找到";
    const n = await this.send("DOM.querySelector", { nodeId: rootId, selector });
    const nodeId = n.result?.nodeId;
    if (!nodeId) return "节点没找到";
    await this.send("DOM.setFileInputFiles", { nodeId, files });
    return `选了 ${files.length} 个文件`;
  }
  click(selector) {
    return this.js(`(function(){var e=document.querySelector(${JSON.stringify(selector)});if(!e)return "NOTFOUND";var h=e.getAttribute&&e.getAttribute("href")||"";e.click();return "clicked:"+h})()`);
  }
  clickAll(selector) {
    return this.js(`(function(){var es=document.querySelectorAll(${JSON.stringify(selector)});for(var i=0;i<es.length;i++)es[i].click();return es.length})()`);
  }
  fill(selector, value) {
    return this.js(`(function(){var e=document.querySelector(${JSON.stringify(selector)});if(!e)return "NOTFOUND";e.value=${JSON.stringify(value)};e.dispatchEvent(new Event("input",{bubbles:true}));e.dispatchEvent(new Event("change",{bubbles:true}));return e.value})()`);
  }
  async mouseClick(x, y) {
    await this.send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y });
    await this.send("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", clickCount: 1 });
    await this.send("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", clickCount: 1 });
  }
  setLS(key, value) {
    return this.js(`(function(){try{localStorage.setItem(${JSON.stringify(key)},${JSON.stringify(value)});return "ok"}catch(e){return "ERR:"+e.message}})()`);
  }
  getLS(key) {
    return this.js(`localStorage.getItem(${JSON.stringify(key)})`);
  }
  clearLS() {
    return this.js(`(function(){try{localStorage.clear();return "ok"}catch(e){return "ERR:"+e.message}})()`);
  }
  clearIDB() {
    // IndexedDB 待重传队列(psm-cloud-upload)也清掉,防止上一轮的 mock 记录串到下一轮
    return this.js(`(function(){try{indexedDB.deleteDatabase("psm-cloud-upload");return "ok"}catch(e){return "ERR:"+e.message}})()`);
  }
  async shot(out) {
    mkdirSync(dirname(out), { recursive: true });
    const r = await this.send("Page.captureScreenshot", { format: "png" });
    writeFileSync(out, Buffer.from(r.result.data, "base64"));
  }
  async overflow(w) {
    const sw = await this.js("document.documentElement.scrollWidth");
    return { scrollW: sw, overflow: sw > w ? sw : false };
  }
  // 问题汇总:console 报错、4xx/5xx、以及网络请求按风险分桶。
  //   writesUnsafe: 非 GET/HEAD/OPTIONS 且打到非本机 http(s) 主机 —— 真正的"真实写请求",任何场景都不该出现。
  //   externalGets: GET/HEAD 打到非本机 http(s) 主机 —— show.html 读 s4 真数据时【预期存在】,
  //                 join.html mock=1 时【不该出现】(该由调用方按场景自行判定,这里只如实分类不替调用方下结论)。
  //   blob/data URI 从不出机器,不算网络请求,不进这两个桶,只留在 allReq 里备查。
  problems() {
    const errs = [], net = [], writesUnsafe = [], externalGets = [], allReq = [];
    for (const e of this.events) {
      if (e.method === "Runtime.exceptionThrown")
        errs.push("EXC " + (e.params.exceptionDetails?.exception?.description || e.params.exceptionDetails?.text || "").slice(0, 220));
      if (e.method === "Runtime.consoleAPICalled" && e.params.type === "error")
        errs.push("ERR " + e.params.args.map(a => a.value ?? a.description ?? a.type).join(" ").slice(0, 220));
      if (e.method === "Network.requestWillBeSent") {
        const req = e.params.request;
        const isHttp = /^https?:\/\//.test(req.url);
        const isLocal = /^https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?\//.test(req.url);
        const safeVerb = req.method === "GET" || req.method === "HEAD" || req.method === "OPTIONS";
        allReq.push({ method: req.method, url: req.url, isHttp, isLocal });
        if (isHttp && !isLocal) {
          if (safeVerb) externalGets.push({ method: req.method, url: req.url });
          else writesUnsafe.push({ method: req.method, url: req.url });
        }
      }
      if (e.method === "Network.responseReceived" && e.params.response.status >= 400)
        net.push(e.params.response.status + " " + e.params.response.url.replace(/^https?:\/\/127\.0\.0\.1:\d+/, ""));
    }
    return { errs: [...new Set(errs)], net4xx: [...new Set(net)], writesUnsafe, externalGets, allReqCount: allReq.length, allReq };
  }
  close() { return fetch(`http://127.0.0.1:${PORT}/json/close/${this.id}`).catch(() => {}); }
}
