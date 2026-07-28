// 任务 0:基线核对 + mock 安全性证明。
// 1) join.html?mock=1 从打开到「传上去」全程,证明 mock 模式不发任何真实网络写请求。
// 2) show.html 五视图各开一次,errs 全空。
import { boot, Tab, sleep } from "./cdp.mjs";

await boot();

const ORIGIN = "http://127.0.0.1:8907";
const OUT = "/Users/max/code/spatial-memory/tools/stress/shots/task0";

function printReq(r) { return `${r.method} ${r.url}`; }

async function baselineJoin() {
  console.log("\n========== 任务0-A: join.html?mock=1 完整动线 + 网络写请求核实 ==========");
  const t = await Tab.open();
  await t.metrics(390, 844, true);

  // 先进一次页面才能拿到 localStorage 的 origin,再清干净,确保是真·首访
  await t.go(`${ORIGIN}/web/join.html?mock=1`, 300);
  await t.clearLS();
  await t.clearIDB();
  await t.reload(1500);

  const allEvents = []; // 汇总全程(含 reload 之后)的请求,不只是最后一步的 t.events
  const snap = () => { allEvents.push(...t.events); t.events = []; };
  snap();

  console.log("[1] 打开 join.html?mock=1(已清 localStorage+IndexedDB,真·首访)");
  let title = await t.js("document.title");
  let welcomeOff = await t.js("document.getElementById('welcome').classList.contains('off')");
  console.log("    title=", title, " welcome屏是否已关闭(off)=", welcomeOff);

  console.log("[2] 点「先不写名字，直接看看」跳过昵称");
  await t.click("#nickSkip");
  await sleep(500);
  snap();

  console.log("[3] 点「直接交照片」进入上传抽屉");
  await t.click("[data-free-upload]");
  await sleep(400);
  snap();

  console.log("[4] 选 2 张本地测试图片(web/demo-assets)");
  const files = [
    "/Users/max/code/spatial-memory/web/demo-assets/ph_p1.jpg",
    "/Users/max/code/spatial-memory/web/demo-assets/ph_p2.jpg"
  ];
  const pickRes = await t.setFiles("#fInput", files);
  console.log("    ", pickRes);
  await sleep(400);
  snap();

  console.log("[5] 点「传上去」,开始(假)上传");
  await t.click("#btnSend");
  snap();

  console.log("[6] 等待 mock 上传进度条跑完(mockPost 是纯 setInterval,不碰网络)");
  // ⚠️ 发现记一笔:MOCK_SPACE.photos(p1/p2)不带 inboxKey 字段,findMine() 永远配不上刚生成的
  // 短 id,所以 resSum 的"最终结算"只会在 POLL_MAX_MS=120000ms(2分钟)超时后才出现 timeoutRows 文案。
  // 这是静态假数据 fixture 的天然限制,不是产品 bug —— 真实环境靠后端 worker 写回 inboxKey 才能配对。
  // 所以"完整动线"到这里的合理终点是:收据面板正确出现 + pending 行显示"AI 正在定位方向",
  // 不等 2 分钟超时,那不是宾客前台体验的一部分。
  const done = await t.waitFor(`document.querySelectorAll('.res.pending').length > 0 && document.getElementById('waitBar')`, 6000, 200);
  await sleep(300);
  snap();
  console.log("    收据面板(pending 行)已出现:", done);

  const resRows = await t.js("document.querySelectorAll('.res').length");
  const pendingText = await t.js("(document.querySelector('.res .res-t')||{}).textContent");
  const sheetTitle = await t.js("(document.querySelector('#sheetIn h3')||{}).textContent");
  console.log("    抽屉标题:", sheetTitle, " | 回执行数:", resRows, " | 首行文案:", pendingText);

  await t.shot(`${OUT}-join-result.png`);

  console.log("[6b] 点「先去空间里逛逛」确认能正常导航离开(不等 2 分钟 AI 超时)");
  const goWalkHref = await t.js("(document.getElementById('btnGoWalk')||{}).textContent");
  console.log("    按钮文案:", goWalkHref, "(此按钮会跳 viewer/walk.html,这里只读文案不真的跳转,避免拖累压测速度)");

  console.log("[7] 切到「我的贡献」确认本机账本也更新了(纯 localStorage,不是网络)");
  await t.click("#mask"); // 关闭抽屉(点遮罩层,等价于宾客点空白处)
  await sleep(300);
  await t.click("#tabMine");
  await sleep(400);
  snap();
  const mineCount = await t.js("document.getElementById('stPhotos').textContent");
  console.log("    我的贡献 - 张照片数:", mineCount);
  await t.shot(`${OUT}-join-mine.png`);

  console.log("[8] 检查「重新传」补传条是否出现(应为 off,因为 mock 模式下 dbPut 被跳过,IndexedDB 里不会有记录)");
  const redoOff = await t.js("document.getElementById('redoBar').classList.contains('off')");
  console.log("    redoBar off=", redoOff, "(应为 true)");

  const sw = await t.js("document.documentElement.scrollWidth");
  console.log("    横向溢出:", sw > 390 ? sw : false);

  const p = t.problems();
  console.log("    这一步 console errs:", p.errs);

  // ---- 汇总全程网络请求(把合并后的事件塞回 t.events,复用 cdp.mjs 同一套分类逻辑,避免两处口径不一致) ----
  t.events = allEvents;
  const full = t.problems();
  t.events = [];

  console.log("\n---- 全程网络请求清单(" + full.allReqCount + " 条,含 blob:/data: 内联资源) ----");
  full.allReq.forEach((r, i) => console.log(`    ${i + 1}. [${r.isHttp ? (r.isLocal ? "本机" : "外部http") : "blob/data(不出机器)"}] ${r.method} ${r.url.slice(0, 90)}`));

  console.log("\n---- 安全核实结论 ----");
  console.log("    非 GET/HEAD/OPTIONS 且打到外部主机的请求(真正的写):", full.writesUnsafe.length, full.writesUnsafe.map(printReq));
  console.log("    GET/HEAD 打到外部主机的请求(mock 模式下也不该有,因为不该碰真实网络):", full.externalGets.length, full.externalGets.map(printReq));
  const SAFE = full.writesUnsafe.length === 0 && full.externalGets.length === 0;
  console.log("    >>> mock=1 全程零真实网络请求(读+写都没有):", SAFE ? "确认安全 PASS" : "危险!发现真实请求 FAIL");

  await t.close();
  return { SAFE, allReqCount: full.allReqCount, writesUnsafeCount: full.writesUnsafe.length, externalGetsCount: full.externalGets.length, errs: p.errs, overflow: sw > 390 ? sw : false };
}

async function baselineShow() {
  console.log("\n========== 任务0-B: show.html 五视图基线(390 宽) ==========");
  const views = [
    ["exhibition(默认)", `${ORIGIN}/web/show.html?s=s4`],
    ["journey 旅程", `${ORIGIN}/web/show.html?s=s4&view=journey`],
    ["timeline 时光轴", `${ORIGIN}/web/show.html?s=s4&view=timeline`],
    ["album 画册", `${ORIGIN}/web/show.html?s=s4&view=album`],
    ["machine 监控墙", `${ORIGIN}/web/show.html?s=s4&view=machine`],
    ["live=1 大屏", `${ORIGIN}/web/show.html?s=s4&live=1`]
  ];
  const results = [];
  const t = await Tab.open();
  await t.metrics(390, 844, true);
  for (const [name, url] of views) {
    await t.go(url, 2200);
    const sw = await t.js("document.documentElement.scrollWidth");
    const p = t.problems();
    const dataPhotoCount = await t.js("document.querySelectorAll('[data-photo]').length");
    const shotPath = `${OUT}-show-${name.replace(/[^a-zA-Z0-9]/g, "")}.png`;
    await t.shot(shotPath);
    console.log(`    [${name}] scrollW=${sw} 横向溢出=${sw > 390 ? sw : false} errs=${JSON.stringify(p.errs)} data-photo数=${dataPhotoCount} shot=${shotPath}`);
    results.push({ name, url, scrollW: sw, overflow: sw > 390 ? sw : false, errs: p.errs, dataPhotoCount });
  }
  await t.close();
  return results;
}

const j = await baselineJoin();
const s = await baselineShow();

console.log("\n========== 任务0 总结 ==========");
console.log("join mock 安全:", j.SAFE, " console errs:", j.errs, " 横向溢出:", j.overflow);
console.log("show 五视图 errs 是否全空:", s.every(r => r.errs.length === 0), " 是否全部无溢出:", s.every(r => r.overflow === false));
process.exit(j.SAFE && j.errs.length === 0 && s.every(r => r.errs.length === 0) ? 0 : 1);
