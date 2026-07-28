// 压测军团 · 动线执行器。每个函数对应"一次完整宾客动线"或"一个粗暴操作场景",
// 返回统一的 result 记录:{ id, group, pass, bugs[], notes[], shot, ms, ...meta }
//
// ⚠️ localStorage/IndexedDB 是按 origin 存的,不是按 CDP tab 存的 —— 同一个 Chrome profile 里
// 开几个 tab 都共用同一份 http://127.0.0.1:8907 的 storage。所以每个 flow 一进来都必须自己
// clearLS()/clearIDB(),不能假设"新开一个 tab = 干净状态",这是本压测框架的头号地雷,已在下面逐一处理。
import { sleep } from "./cdp.mjs";

export const ORIGIN = "http://127.0.0.1:8907";
export const SHOTS = "/Users/max/code/spatial-memory/tools/stress/shots";
const DEMO_IMGS = [1, 2, 3, 4, 5].map(i => `/Users/max/code/spatial-memory/web/demo-assets/ph_p${i}.jpg`);
function img(i = 0) { return DEMO_IMGS[i % DEMO_IMGS.length]; }

function finalize(id, group, meta, bugs, notes, t0, extra = {}) {
  return {
    id, group, meta, bugs, notes,
    pass: bugs.length === 0,
    ms: Date.now() - t0,
    ...extra
  };
}

// ================================================================ 组 J:join 完整动线
export async function runJoinFlow(tab, v) {
  const t0 = Date.now();
  const bugs = [], notes = [];
  try {
    await tab.metrics(v.width, v.height, true);
    await tab.go(`${ORIGIN}/web/join.html?mock=1`, 300);
    await tab.clearIDB();
    await tab.clearLS();
    if (v.visit === "return") await tab.setLS("psm_nick", "阿哲");
    await tab.reload(1400);

    const welcomeOff = await tab.js("document.getElementById('welcome').classList.contains('off')");
    const expectOff = v.visit === "return";
    if (welcomeOff !== expectOff) bugs.push(`welcome屏状态不符预期(期望off=${expectOff},实测=${welcomeOff})`);

    if (v.visit === "first") {
      if (v.namemode === "fill") {
        await tab.fill("#nickInput", "压测小明");
        await tab.click("#nickGo");
      } else {
        await tab.click("#nickSkip");
      }
      await sleep(400);
    }

    let entryR;
    if (v.uploadpath === "free") {
      entryR = await tab.click("[data-free-upload]");
    } else {
      entryR = await tab.click(".btn-take");
    }
    if (entryR === "NOTFOUND") bugs.push(`入口按钮没找到(uploadpath=${v.uploadpath})`);
    await sleep(400);

    const sheetOn = await tab.js("document.getElementById('sheet').classList.contains('on')");
    if (!sheetOn) bugs.push("点击入口后上传抽屉没打开(#sheet 缺 on)");

    await tab.setFiles("#fInput", [img(v.seq)]);
    await sleep(400);

    const sendDisabled = await tab.js("(document.getElementById('btnSend')||{}).disabled");
    if (sendDisabled !== false) bugs.push("选完 1 张图后「传上去」仍是 disabled");

    await tab.click("#btnSend");
    const appeared = await tab.waitFor(
      "document.querySelectorAll('.res.pending').length > 0 || (document.getElementById('toast')||{}).className && document.getElementById('toast').className.indexOf('on')>=0",
      8000, 200
    );
    if (!appeared) bugs.push("点「传上去」后 8 秒内既无收据面板也无 toast,疑似卡死");
    await sleep(300);

    const savedNick = await tab.getLS("psm_nick");
    const expectNick = v.visit === "return" ? "阿哲" : (v.namemode === "fill" ? "压测小明" : "匿名参与者");
    if (savedNick !== expectNick) bugs.push(`localStorage psm_nick 不符预期(期望"${expectNick}",实测"${savedNick}")`);

    const ov = await tab.overflow(v.width);
    if (ov.overflow !== false) bugs.push(`横向溢出 scrollW=${ov.scrollW} > 视口${v.width}`);

    const p = tab.problems();
    p.errs.forEach(e => bugs.push("console: " + e));
    p.writesUnsafe.forEach(w => bugs.push("!!真实写请求!!: " + w.method + " " + w.url));
    p.externalGets.forEach(w => bugs.push("mock 模式下出现外部请求: " + w.method + " " + w.url));

    await tab.shot(`${SHOTS}/${v.id}.png`);
    return finalize(v.id, "J", v, bugs, notes, t0, { shot: `${v.id}.png`, errsCount: p.errs.length, overflow: ov.overflow });
  } catch (e) {
    bugs.push("脚本异常: " + (e && e.stack || e));
    try { await tab.shot(`${SHOTS}/${v.id}-EXC.png`); } catch {}
    return finalize(v.id, "J", v, bugs, notes, t0, { shot: `${v.id}-EXC.png`, exception: true });
  }
}

// ================================================================ 组 S:show 五视图
const LIGHTBOX_SEL = {
  exhibition: ".photo", live1: ".photo",
  journey: ".jr-shot", timeline: ".tl-card", album: ".al-plate", machine: ".mc-tile"
};

export async function runShowFlow(tab, v) {
  const t0 = Date.now();
  const bugs = [], notes = [];
  try {
    await tab.metrics(v.width, v.height, true);
    const url = v.view === "live1"
      ? `${ORIGIN}/web/show.html?s=s4&live=1`
      : v.view === "exhibition"
      ? `${ORIGIN}/web/show.html?s=s4`
      : `${ORIGIN}/web/show.html?s=s4&view=${v.view}`;
    await tab.go(url, 2200);

    const dataPhotoCount = await tab.js("document.querySelectorAll('[data-photo]').length");
    notes.push(`data-photo 数量=${dataPhotoCount}`);
    if (v.view !== "live1" && dataPhotoCount === 0) bugs.push("这个视图 data-photo 数量为 0(期望 s4 的 9 张)");

    // 灯箱开关核实:点第一张照片卡,记录 DOM 是否有变化(有变化说明存在某种展开/弹层反应)
    const sel = LIGHTBOX_SEL[v.view];
    const before = await tab.js("document.body.innerHTML.length");
    const hasTarget = await tab.js(`document.querySelectorAll(${JSON.stringify(sel)}).length`);
    if (hasTarget > 0) {
      await tab.click(sel);
      await sleep(500);
      const after = await tab.js("document.body.innerHTML.length");
      const delta = after - before;
      notes.push(`灯箱测试: 点击 ${sel} 前后 body.innerHTML 长度差=${delta}(接近0=确认无灯箱反应/no-op)`);
      // 不把"没有灯箱"当 bug 记(那是产品功能缺口,写进简化建议),只记录客观事实。
    } else {
      notes.push(`灯箱测试: 页面没有 ${sel} 元素可点(可能无照片)`);
    }

    if (v.view === "exhibition") {
      const navHref = await tab.js("(document.querySelector('.section-head') ? true : (document.querySelector('a[href=\"#photos\"]')||{}).href) || null");
      const r = await tab.click('a[href="#photos"]');
      await sleep(400);
      const hash = await tab.js("location.hash");
      if (hash !== "#photos" && r !== "NOTFOUND") bugs.push(`点内部导航"已上传"后 location.hash 未变为 #photos(实测 ${hash})`);
    }

    if (v.view === "live1") {
      await sleep(5400); // 等一轮 pollLive() (5000ms 间隔) 真的跑一次,确认轮询期间不出错
      const p1 = tab.problems();
      p1.errs.forEach(e => bugs.push("console(live轮询后): " + e));
    }

    const ov = await tab.overflow(v.width);
    if (ov.overflow !== false) bugs.push(`横向溢出 scrollW=${ov.scrollW} > 视口${v.width}`);

    const p = tab.problems();
    p.errs.forEach(e => bugs.push("console: " + e));
    p.writesUnsafe.forEach(w => bugs.push("!!真实写请求!!: " + w.method + " " + w.url));

    await tab.shot(`${SHOTS}/${v.id}.png`);
    return finalize(v.id, "S", v, bugs, notes, t0, { shot: `${v.id}.png`, dataPhotoCount, errsCount: p.errs.length, overflow: ov.overflow });
  } catch (e) {
    bugs.push("脚本异常: " + (e && e.stack || e));
    try { await tab.shot(`${SHOTS}/${v.id}-EXC.png`); } catch {}
    return finalize(v.id, "S", v, bugs, notes, t0, { shot: `${v.id}-EXC.png`, exception: true });
  }
}

// ================================================================ 组 R:粗暴操作
async function setupJoinFirstVisitSkip(tab, w, h) {
  await tab.metrics(w, h, true);
  await tab.go(`${ORIGIN}/web/join.html?mock=1`, 300);
  await tab.clearIDB();
  await tab.clearLS();
  await tab.reload(1400);
  await tab.click("#nickSkip");
  await sleep(350);
}

const ROUGH_HANDLERS = {
  async "same-button-3x"(tab, v, bugs, notes) {
    await setupJoinFirstVisitSkip(tab, v.width, v.height);
    await tab.click("[data-free-upload]");
    await sleep(350);
    await tab.setFiles("#fInput", [img(0)]);
    await sleep(350);
    const rect = await tab.js(`(function(){var e=document.getElementById('btnSend');if(!e)return null;var r=e.getBoundingClientRect();return [r.x+r.width/2, r.y+r.height/2]})()`);
    if (!rect) { bugs.push("找不到 #btnSend 无法测连点"); return; }
    const [x, y] = rect;
    // 真实同一像素位置连按 3 次,中间几乎不等待(模拟手指连点/双击误触),
    // 而不是逐次 querySelector 再点(那样按钮一旦被换成进度条模板,选择器自然落空,测不出竞态)。
    await tab.mouseClick(x, y);
    await sleep(60);
    await tab.mouseClick(x, y);
    await sleep(60);
    await tab.mouseClick(x, y);
    await sleep(1800);
    const resRows = await tab.js("document.querySelectorAll('.res').length");
    notes.push(`连点 3 次后收据行数=${resRows}(只选了 1 张图,期望仍是 1 行,>1 说明重复提交)`);
    if (resRows > 1) bugs.push(`连点「传上去」3 次导致重复提交: 1 张图产生了 ${resRows} 条收据`);
    if (resRows === 0) bugs.push("连点后没有任何收据行出现");
    const p = tab.problems();
    p.errs.forEach(e => bugs.push("console: " + e));
  },

  async "refresh-mid-flow"(tab, v, bugs, notes) {
    await setupJoinFirstVisitSkip(tab, v.width, v.height);
    await tab.click("[data-free-upload]");
    await sleep(350);
    await tab.setFiles("#fInput", [img(1)]);
    await sleep(300);
    notes.push("中途状态: 抽屉打开、已选 1 张图、尚未点传上去");
    await tab.reload(1600);
    const p = tab.problems();
    p.errs.forEach(e => bugs.push("刷新后 console: " + e));
    const welcomeOff = await tab.js("document.getElementById('welcome').classList.contains('off')");
    if (!welcomeOff) bugs.push("刷新后 welcome 屏又出现了(此前已跳过昵称,应记住状态)");
    const sheetOn = await tab.js("document.getElementById('sheet').classList.contains('on')");
    if (sheetOn) bugs.push("刷新后上传抽屉仍显示为打开状态(应已重置,选中的文件不可能存活)");
    const maskOn = await tab.js("document.getElementById('mask').classList.contains('on')");
    if (maskOn) bugs.push("刷新后遮罩层 #mask 仍是 on(卡死的半透明遮罩,挡住页面)");
    const ov = await tab.overflow(v.width);
    if (ov.overflow !== false) bugs.push(`刷新后横向溢出 scrollW=${ov.scrollW}`);
    notes.push(`刷新后: welcomeOff=${welcomeOff} sheetOn=${sheetOn} maskOn=${maskOn}`);
  },

  async "browser-back"(tab, v, bugs, notes) {
    await tab.metrics(v.width, v.height, true);
    await tab.go(`${ORIGIN}/portal.html`, 800);
    await tab.clearIDB();
    await tab.clearLS();
    await tab.go(`${ORIGIN}/web/join.html?mock=1&back=portal.html`, 1200);
    await tab.click("#nickSkip");
    await sleep(350);
    await tab.click("[data-free-upload]");
    await sleep(350);
    await tab.js("history.back()");
    await sleep(1200);
    const url = await tab.js("location.href");
    const title = await tab.js("document.title");
    notes.push(`后退后 url=${url} title=${title}`);
    if (!/portal\.html/.test(url)) bugs.push(`后退后没有回到 portal.html(实测 ${url})`);
    const p = tab.problems();
    p.errs.forEach(e => bugs.push("后退后 console: " + e));
    const ov = await tab.overflow(v.width);
    if (ov.overflow !== false) bugs.push(`后退后横向溢出 scrollW=${ov.scrollW}`);
  },

  async "long-nickname-emoji"(tab, v, bugs, notes) {
    // 30 字(含 emoji/CJK 混排),真实向量:localStorage 里已有的历史长昵称(不受 input maxlength=12 限制,
    // maxlength 只挡得住"这次在这台设备上打字/粘贴",挡不住已经存在 storage 里或其它端写入的旧值)。
    const LONG = "小明😀🎉🚀测试嘉宾超级无敌长昵称走过路过别错过呀哈哈哈哈";
    notes.push(`真实字符数(Array.from().length)=${[...LONG].length}`);
    await tab.metrics(v.width, v.height, true);
    await tab.go(`${ORIGIN}/web/join.html?mock=1`, 300);
    await tab.clearIDB();
    await tab.clearLS();
    await tab.setLS("psm_nick", LONG);
    await tab.reload(1400);

    const headRect = await tab.js(`(function(){var e=document.getElementById('hMe');if(!e)return null;var r=e.getBoundingClientRect();return {right:r.right, width:r.width}})()`);
    const headRow = await tab.js(`(function(){var e=document.querySelector('.head-row');if(!e)return null;var r=e.getBoundingClientRect();return {right:r.right}})()`);
    notes.push(`头部昵称pill: right=${headRect && headRect.right}, width=${headRect && headRect.width}; .head-row right=${headRow && headRow.right}; 视口宽=${v.width}`);
    if (headRect && headRect.right > v.width + 1) bugs.push(`头部昵称 pill 右边缘(${headRect.right}px)超出视口(${v.width}px),长昵称把头部撑爆`);

    const ov1 = await tab.overflow(v.width);
    if (ov1.overflow !== false) bugs.push(`回访长昵称: 首屏横向溢出 scrollW=${ov1.scrollW}`);

    // 第二段:首访直接把 30 字塞进输入框再提交(绕开 maxlength=12,测下游渲染的防御性,
    // 不代表真实用户能从键盘打字/粘贴打出 30 字 —— maxlength 会挡住那条路,这里单独注明)。
    await tab.clearLS();
    await tab.reload(1400);
    await tab.fill("#nickInput", LONG);
    await tab.click("#nickGo");
    await sleep(500);
    const ov2 = await tab.overflow(v.width);
    if (ov2.overflow !== false) bugs.push(`首访强灌 30 字昵称提交后横向溢出 scrollW=${ov2.scrollW}`);
    const savedNick = await tab.getLS("psm_nick");
    notes.push(`首访强灌后 localStorage 实际存的值="${savedNick}"(长度 ${savedNick ? savedNick.length : 0})`);

    const p = tab.problems();
    p.errs.forEach(e => bugs.push("console: " + e));
    await tab.shot(`${SHOTS}/${v.id}.png`);
  },

  async "zero-photo-upload"(tab, v, bugs, notes) {
    await setupJoinFirstVisitSkip(tab, v.width, v.height);
    await tab.click("[data-free-upload]");
    await sleep(350);
    const disabled = await tab.js("(document.getElementById('btnSend')||{}).disabled");
    notes.push(`0 张图时 btnSend.disabled=${disabled}(应为 true)`);
    if (disabled !== true) bugs.push("没选任何照片时「传上去」按钮竟然不是 disabled");
    const r1 = await tab.click("#btnSend");
    await sleep(400);
    const stillPicker = await tab.js("!!document.getElementById('fInput')");
    notes.push(`原生 disabled 状态下点击结果=${r1}, 点击后选择器仍存在(仍在选图面板)=${stillPicker}`);
    if (!stillPicker) bugs.push("disabled 按钮被点后页面状态发生了变化(不应该,disabled 应完全拦截)");
    // 再测 JS 层兜底:强行摘掉 disabled 后点,doUpload() 内部 if(!files.length) return; 应静默无事发生
    await tab.js("(function(){var e=document.getElementById('btnSend'); if(e) e.disabled=false; return true})()");
    await tab.click("#btnSend");
    await sleep(500);
    const p = tab.problems();
    p.errs.forEach(e => bugs.push("强制摘除 disabled 后点击, console: " + e));
    const stillPicker2 = await tab.js("!!document.getElementById('fInput')");
    notes.push(`强摘 disabled 后点击,是否仍停留在选图面板=${stillPicker2}(doUpload 应静默 return,不崩不跳转)`);
  },

  async "rapid-view-switch-10x"(tab, v, bugs, notes) {
    await tab.metrics(v.width, v.height, true);
    await tab.go(`${ORIGIN}/web/show.html?s=s4`, 2000);
    const hrefs = await tab.js("Array.from(document.querySelectorAll('.view-nav.mode-switch a')).map(function(a){return a.getAttribute('href')})");
    if (!hrefs || !hrefs.length) { bugs.push("找不到换视图药丸导航"); return; }
    notes.push(`药丸导航共 ${hrefs.length} 个: ${JSON.stringify(hrefs)}`);
    const seq = [];
    for (let i = 0; i < 10; i++) seq.push(hrefs[i % hrefs.length]);
    for (const href of seq) {
      // altViewUrl() 产出的是 location.pathname 拼出来的绝对路径(如 /web/show.html?...),
      // 不是相对路径,直接拼 ORIGIN 前缀即可。
      const full = href.startsWith("http") ? href : `${ORIGIN}${href}`;
      // 直接连续发导航指令,不等上一次 load 完成,模拟不耐烦的人连续快速点导航栏
      await tab.send("Page.navigate", { url: full });
      await sleep(120);
    }
    await sleep(2500); // 最后一次导航真正稳定下来
    const finalUrl = await tab.js("location.href");
    const title = await tab.js("document.title");
    const appHtmlLen = await tab.js("(document.getElementById('app')||{}).innerHTML ? document.getElementById('app').innerHTML.length : 0");
    notes.push(`连续切视图 10 次后: url=${finalUrl} title=${title} appHtml长度=${appHtmlLen}`);
    if (!appHtmlLen || appHtmlLen < 50) bugs.push(`连续快速切视图 10 次后页面主体几乎是空的(#app 长度=${appHtmlLen}),疑似渲染没跟上或卡死`);
    const p = tab.problems();
    p.errs.forEach(e => bugs.push("console: " + e));
    const ov = await tab.overflow(v.width);
    if (ov.overflow !== false) bugs.push(`连续切视图后横向溢出 scrollW=${ov.scrollW}`);
  },

  async "reopen-name-editor"(tab, v, bugs, notes) {
    await tab.metrics(v.width, v.height, true);
    await tab.go(`${ORIGIN}/web/join.html?mock=1`, 300);
    await tab.clearIDB();
    await tab.clearLS();
    await tab.setLS("psm_nick", "阿哲");
    await tab.reload(1400);
    const offBefore = await tab.js("document.getElementById('welcome').classList.contains('off')");
    if (!offBefore) bugs.push("回访理应直接跳过 welcome 屏,实测没跳过");
    await tab.click("#hMe");
    await sleep(350);
    const offAfterClick = await tab.js("document.getElementById('welcome').classList.contains('off')");
    if (offAfterClick) bugs.push("点头部「你好」pill 后 welcome 屏没有重新打开");
    const inputVal = await tab.js("(document.getElementById('nickInput')||{}).value");
    notes.push(`点开重新编辑后输入框预填值="${inputVal}"(期望"阿哲")`);
    if (inputVal !== "阿哲") bugs.push(`重新编辑昵称时输入框没有预填原名(实测"${inputVal}")`);
    await tab.fill("#nickInput", "阿哲改名了");
    await tab.click("#nickGo");
    await sleep(400);
    const headNick = await tab.js("(document.getElementById('hNick')||{}).textContent");
    if (headNick !== "阿哲改名了") bugs.push(`改名提交后头部昵称没有更新(实测"${headNick}")`);
    const p = tab.problems();
    p.errs.forEach(e => bugs.push("console: " + e));
  },

  async "rapid-tab-switch-10x"(tab, v, bugs, notes) {
    await setupJoinFirstVisitSkip(tab, v.width, v.height);
    for (let i = 0; i < 10; i++) {
      await tab.click(i % 2 === 0 ? "#tabMine" : "#tabTasks");
      await sleep(90);
    }
    await sleep(500);
    const finalView = await tab.js("document.getElementById('tabMine').classList.contains('on') ? 'mine' : (document.getElementById('tabTasks').classList.contains('on') ? 'tasks' : 'unknown')");
    const mineDisplay = await tab.js("getComputedStyle(document.getElementById('viewMine')).display");
    const tasksDisplay = await tab.js("getComputedStyle(document.getElementById('viewTasks')).display");
    notes.push(`连续切 10 次 tab 后最终态=${finalView}, viewMine.display=${mineDisplay}, viewTasks.display=${tasksDisplay}`);
    // 结尾第 10 次(i=9,奇数)点的是 tabTasks,期望最终停在 tasks
    if (finalView !== "tasks") bugs.push(`连续切 10 次 tab 后最终态应为 tasks,实测 ${finalView}`);
    if (mineDisplay !== "none" || tasksDisplay === "none") bugs.push("连续切 tab 后两个视图的显示状态自相矛盾(可能同时显示或同时隐藏)");
    const p = tab.problems();
    p.errs.forEach(e => bugs.push("console: " + e));
  },

  async "reopen-sheet-different-task"(tab, v, bugs, notes) {
    await setupJoinFirstVisitSkip(tab, v.width, v.height);
    const titleA = await tab.js("(document.querySelectorAll('.btn-take')[0]||{}).closest ? document.querySelectorAll('.btn-take')[0].closest('.card').querySelector('.card-title').textContent : null");
    await tab.js("document.querySelectorAll('.btn-take')[0].click()");
    await sleep(350);
    const sheetTitleA = await tab.js("(document.querySelector('#sheetIn h3')||{}).textContent");
    await tab.click("#btnCancel");
    await sleep(300);
    const sheetOffAfterCancel = await tab.js("!document.getElementById('sheet').classList.contains('on')");
    if (!sheetOffAfterCancel) bugs.push("取消后抽屉没有关闭");
    await tab.js("document.querySelectorAll('.btn-take')[1].click()");
    await sleep(350);
    const sheetTitleB = await tab.js("(document.querySelector('#sheetIn h3')||{}).textContent");
    notes.push(`任务A标题="${titleA}" 抽屉A标题="${sheetTitleA}" 抽屉B标题="${sheetTitleB}"`);
    if (sheetTitleA === sheetTitleB) bugs.push(`换了不同任务卡重开抽屉,但抽屉标题没变(A="${sheetTitleA}" B="${sheetTitleB}"),疑似状态没刷新`);
    await tab.setFiles("#fInput", [img(2)]);
    await sleep(300);
    await tab.click("#btnSend");
    await sleep(1200);
    const waitingTitle = await tab.js("(document.querySelector('#sheetIn h3')||{}).textContent");
    notes.push(`发送后收据面板标题="${waitingTitle}"(确认没有卡在旧抽屉内容上)`);
    const p = tab.problems();
    p.errs.forEach(e => bugs.push("console: " + e));
  },

  async "double-cancel-cycle"(tab, v, bugs, notes) {
    await setupJoinFirstVisitSkip(tab, v.width, v.height);
    for (let i = 0; i < 4; i++) {
      await tab.click("[data-free-upload]");
      await sleep(250);
      const sheetOn = await tab.js("document.getElementById('sheet').classList.contains('on')");
      if (!sheetOn) bugs.push(`第 ${i + 1} 轮打开抽屉失败`);
      await tab.click("#btnCancel");
      await sleep(250);
      const sheetOff = await tab.js("!document.getElementById('sheet').classList.contains('on')");
      const maskOff = await tab.js("!document.getElementById('mask').classList.contains('on')");
      if (!sheetOff || !maskOff) bugs.push(`第 ${i + 1} 轮取消后 sheet/mask 状态没同步(sheetOff=${sheetOff}, maskOff=${maskOff})`);
    }
    const toastCount = await tab.js("document.querySelectorAll('.toast').length");
    if (toastCount !== 1) bugs.push(`4 轮开合后 .toast 元素数量=${toastCount}(期望 1,说明有 DOM 重复创建)`);
    notes.push(`4 轮开合完成, toast 元素数量=${toastCount}`);
    const p = tab.problems();
    p.errs.forEach(e => bugs.push("console: " + e));
  }
};

export async function runRoughFlow(tab, v) {
  const t0 = Date.now();
  const bugs = [], notes = [];
  try {
    const handler = ROUGH_HANDLERS[v.name];
    if (!handler) { bugs.push("未知的粗暴操作场景: " + v.name); }
    else await handler(tab, v, bugs, notes);
    const ov = await tab.overflow(v.width).catch(() => ({ overflow: false }));
    if (ov.overflow !== false && !bugs.some(b => b.includes("溢出"))) {
      bugs.push(`收尾检查横向溢出 scrollW=${ov.scrollW}`);
    }
    const finalErrs = tab.problems().errs.length;
    await tab.shot(`${SHOTS}/${v.id}.png`);
    return finalize(v.id, "R", v, bugs, notes, t0, { shot: `${v.id}.png`, errsCount: finalErrs, overflow: ov.overflow });
  } catch (e) {
    bugs.push("脚本异常: " + (e && e.stack || e));
    try { await tab.shot(`${SHOTS}/${v.id}-EXC.png`); } catch {}
    return finalize(v.id, "R", v, bugs, notes, t0, { shot: `${v.id}-EXC.png`, exception: true });
  }
}

// ================================================================ 组 P:portal / pov 补充烟测
export async function runSmokeFlow(tab, v) {
  const t0 = Date.now();
  const bugs = [], notes = [];
  try {
    await tab.metrics(v.width, v.height, true);
    const url = v.page === "portal" ? `${ORIGIN}/portal.html` : `${ORIGIN}/web/pov.html`;
    await tab.go(url, 1800);

    if (v.page === "portal") {
      // 全屏按钮:requestFullscreen() 在无头/非受信任手势场景下大概率 reject,
      // 且源码没有 .catch(),测的是这个未处理 rejection 会不会被算成 console 报错。
      await tab.click("#fullBtn");
      await sleep(500);
      const hrefGuest = await tab.js("(document.querySelector('.role-card.guest')||{}).getAttribute ? document.querySelector('.role-card.guest').getAttribute('href') : null");
      const hrefShow = await tab.js("(document.querySelector('.role-card.exhibit')||{}).getAttribute ? document.querySelector('.role-card.exhibit').getAttribute('href') : null");
      notes.push(`宾客入口href=${hrefGuest} 展览入口href=${hrefShow}`);
      if (!/web\/join\.html/.test(hrefGuest || "")) bugs.push(`宾客入口 href 不对: ${hrefGuest}`);
      if (!/web\/show\.html/.test(hrefShow || "")) bugs.push(`展览入口 href 不对: ${hrefShow}`);
    } else {
      await tab.click('a[href="#truth"]');
      await sleep(400);
      const hash = await tab.js("location.hash");
      if (hash !== "#truth") bugs.push(`点"先看它哪里还不行"后 hash 未变为 #truth(实测 ${hash})`);
      const demoHref = await tab.js("(document.getElementById('goDemo')||{}).href");
      notes.push(`goDemo href=${demoHref}`);
    }

    const ov = await tab.overflow(v.width);
    if (ov.overflow !== false) bugs.push(`横向溢出 scrollW=${ov.scrollW}`);
    const p = tab.problems();
    p.errs.forEach(e => bugs.push("console: " + e));

    await tab.shot(`${SHOTS}/${v.id}.png`);
    return finalize(v.id, "P", v, bugs, notes, t0, { shot: `${v.id}.png`, errsCount: p.errs.length, overflow: ov.overflow });
  } catch (e) {
    bugs.push("脚本异常: " + (e && e.stack || e));
    try { await tab.shot(`${SHOTS}/${v.id}-EXC.png`); } catch {}
    return finalize(v.id, "P", v, bugs, notes, t0, { shot: `${v.id}-EXC.png`, exception: true });
  }
}
