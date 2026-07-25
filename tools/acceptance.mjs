// 泛自己的验收车道(独立端口 9361)。零依赖,Node ≥22 自带 WebSocket。
//   node fan-acceptance.mjs shot <url> <out.png> [w] [h]
//   node fan-acceptance.mjs sweep <urls.json>    批量体检:每个 url 打开+截图+收错
//   node fan-acceptance.mjs walk <spec.json>     剧本:[{name,metrics,go,click,wait,eval,shot}]
//   node fan-acceptance.mjs kill
import { spawn, execSync } from "node:child_process";
import { writeFileSync, mkdirSync, readFileSync } from "node:fs";
import { basename, dirname } from "node:path";

const PORT = process.env.CDP_PORT || 9361;
const PROFILE = `/private/tmp/claude-501/-/f506cf64-86e8-4789-8bf6-74a51f9007df/scratchpad/chrome-${PORT}`;
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function boot() {
  try { if ((await fetch(`http://127.0.0.1:${PORT}/json/version`)).ok) return "reused"; } catch {}
  mkdirSync(PROFILE, { recursive: true });
  spawn(CHROME, ["--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`,
    "--use-gl=angle", "--use-angle=swiftshader",            // 防 canvas 截图伪影
    "--no-first-run", "--no-default-browser-check", "--window-size=1280,860"],
    { detached: true, stdio: "ignore" }).unref();
  for (let i = 0; i < 80; i++) {
    await sleep(250);
    try { if ((await fetch(`http://127.0.0.1:${PORT}/json/version`)).ok) return "booted"; } catch {}
  }
  throw new Error("Chrome 起不来");
}

async function apiUpload(spec) {
  const fd = new FormData();
  for (const [k, v] of Object.entries(spec.fields || {})) fd.append(k, String(v));
  for (const p of spec.files || []) {
    fd.append("photos", new Blob([readFileSync(p)]), basename(p));
  }
  const r = await fetch(spec.url, { method: "POST", body: fd });
  const raw = await r.text();
  let body = raw;
  try { body = JSON.parse(raw); } catch {}
  return { status: r.status, body };
}

let _id = 0;
class Tab {
  constructor(ws) { this.ws = ws; this.waiters = new Map(); this.events = []; }
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
    await tab.send("Emulation.setFocusEmulationEnabled", { enabled: true });  // 不然 rAF 冻结
    // ⚠️踩过的坑:profile 是复用的,不禁缓存就会拿到改动前的旧页面,
    // 于是"改了没效果"的假象会让你去改别的地方。2026-07-25 在 walk.html 上真中过一次。
    await tab.send("Network.setCacheDisabled", { cacheDisabled: true });
    return tab;
  }
  send(method, params = {}) {
    const id = ++_id;
    return new Promise((res) => { this.waiters.set(id, res); this.ws.send(JSON.stringify({ id, method, params })); });
  }
  // 真手机宽必须走这个,--window-size 压不到 500 以下,量到的 390 是假的
  // ⚠️2026-07-25 补:光给宽度不够。setDeviceMetricsOverride 不会让 ontouchstart 和
  // maxTouchPoints 变真,而 walk.html 这类页面靠 isTouchDevice() 决定给摇杆还是给
  // WASD 提示卡,于是 390 宽截图里手机用户看到的是"WASD 移动 · ESC 退出",
  // 那是量具造出来的假象不是产品 bug。手机宽必须同时开触摸模拟。
  async metrics(w, h) {
    await this.send("Emulation.setDeviceMetricsOverride",
      { width: w, height: h, deviceScaleFactor: 2, mobile: w < 500 });
    return this.send("Emulation.setTouchEmulationEnabled",
      { enabled: w < 500, maxTouchPoints: w < 500 ? 5 : 0 });
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
  async js(expr) {
    const r = await this.send("Runtime.evaluate", {
      expression: `(()=>{try{return JSON.stringify(${expr})}catch(e){return JSON.stringify("ERR:"+e.message)}})()`,
      returnByValue: true, userGesture: true });
    try { return JSON.parse(r.result?.result?.value ?? "null"); } catch { return r.result?.result?.value; }
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
  async responseBody(pattern) {
    const e = [...this.events].reverse().find((x) =>
      x.method === "Network.responseReceived" && x.params.response.url.includes(pattern));
    if (!e) return null;
    const r = await this.send("Network.getResponseBody", { requestId: e.params.requestId });
    const raw = r.result?.body || "";
    let body = raw;
    try { body = JSON.parse(raw); } catch {}
    return { status: e.params.response.status, url: e.params.response.url, body };
  }
  async shot(out) {
    mkdirSync(dirname(out), { recursive: true });
    const r = await this.send("Page.captureScreenshot", { format: "png" });
    writeFileSync(out, Buffer.from(r.result.data, "base64"));
  }
  problems() {
    const errs = [], net = [];
    for (const e of this.events) {
      if (e.method === "Runtime.exceptionThrown")
        errs.push("EXC " + (e.params.exceptionDetails?.exception?.description || e.params.exceptionDetails?.text || "").slice(0, 220));
      if (e.method === "Runtime.consoleAPICalled" && e.params.type === "error")
        errs.push("ERR " + e.params.args.map(a => a.value ?? a.description ?? a.type).join(" ").slice(0, 220));
      if (e.method === "Network.responseReceived" && e.params.response.status >= 400)
        net.push(e.params.response.status + " " + e.params.response.url.replace(/^https?:\/\/127\.0\.0\.1:8777/, ""));
    }
    return { errs: [...new Set(errs)], net404: [...new Set(net)] };
  }
  close() { return fetch(`http://127.0.0.1:${PORT}/json/close/${this.id}`).catch(() => {}); }
}

const [, , cmd, ...a] = process.argv;
if (cmd === "kill") { try { execSync(`pkill -f "remote-debugging-port=${PORT}"`); } catch {} console.log("killed"); }
else if (cmd === "shot") {
  await boot();
  const [url, out, w = 390, h = 844] = a;
  const t = await Tab.open(); await t.metrics(+w, +h); await t.go(url); await t.shot(out);
  const sw = await t.js("document.documentElement.scrollWidth");
  console.log(JSON.stringify({ out, title: await t.js("document.title"), scrollW: sw, 横向溢出: sw > +w, ...t.problems() }, null, 1));
  await t.close();
}
else if (cmd === "sweep") {
  await boot();
  const spec = JSON.parse(readFileSync(a[0], "utf8"));
  const t = await Tab.open(); await t.metrics(390, 844);
  const rows = [];
  for (const u of spec.urls) {
    await t.go(u.url, u.settle ?? 1800);
    if (u.shot) await t.shot(u.shot);
    const p = t.problems();
    const sw = await t.js("document.documentElement.scrollWidth");
    rows.push({ 页: u.name, url: u.url.replace("http://127.0.0.1:8777", ""),
      标题: await t.js("document.title"), 溢出: sw > 390 ? sw : false,
      正文字数: await t.js("(document.body.innerText||'').replace(/\\s+/g,'').length"),
      报错: p.errs, 死链: p.net404.filter(x => !/favicon/.test(x)), shot: u.shot || null });
  }
  console.log(JSON.stringify(rows, null, 1));
  await t.close();
}
else if (cmd === "walk") {
  await boot();
  const spec = JSON.parse(readFileSync(a[0], "utf8"));
  const t = await Tab.open(); const log = [];
  for (const s of spec.steps) {
    if (s.metrics) await t.metrics(s.metrics[0], s.metrics[1]);
    if (s.go) await t.go(s.go, s.settle ?? 1500);
    if (s.mouse) {
      const [x, y] = s.mouse;
      await t.send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y });
      await t.send("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", clickCount: 1 });
      await t.send("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", clickCount: 1 });
      log.push({ step: s.name, mouse: [x, y] });
    }
    if (s.press) {
      const [x, y] = s.press;
      await t.send("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", clickCount: 1 });
      await t.send("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", clickCount: 1 });
      log.push({ step: s.name, press: [x, y] });
    }
    if (s.move) {
      const [x, y] = s.move;
      await t.send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y });
      log.push({ step: s.name, move: [x, y] });
    }
    if (s.file) {
      log.push({ step: s.name, file: await t.setFiles(s.file.selector, s.file.paths) });
    }
    if (s.fill) {
      log.push({ step: s.name, fill: await t.js(`(function(){var e=document.querySelector(${JSON.stringify(s.fill.selector)});if(!e)return "元素没找到";e.value=${JSON.stringify(s.fill.value)};e.dispatchEvent(new Event("input",{bubbles:true}));e.dispatchEvent(new Event("change",{bubbles:true}));return e.value})()`) });
    }
    if (s.apiUpload) {
      log.push({ step: s.name, apiUpload: await apiUpload(s.apiUpload) });
    }
    if (s.click) log.push({ step: s.name, r: await t.js(`(function(){var e=document.querySelector(${JSON.stringify(s.click)});if(!e)return "元素没找到";var h=e.getAttribute&&e.getAttribute("href")||"";e.click();return "点了 "+h})()`) });
    if (s.wait) await sleep(s.wait);
    if (s.eval) log.push({ step: s.name, eval: await t.js(s.eval) });
    if (s.response) log.push({ step: s.name, response: await t.responseBody(s.response) });
    if (s.shot) {
      await t.shot(s.shot);
      const sw = await t.js("document.documentElement.scrollWidth");
      log.push({ step: s.name, shot: s.shot, url: await t.js("location.href"), 溢出: sw > 390 ? sw : false, ...t.problems() });
      t.events = [];
    }
  }
  console.log(JSON.stringify(log, null, 1));
  await t.close();
} else console.log("shot | sweep | walk | kill");
