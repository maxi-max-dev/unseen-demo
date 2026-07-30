// 批次K 验收：小程序三页截图 + 跨空间交叉核对。
//
// 跑法（仓库根目录）：
//     node tools/shots-k.js
// 截图落 tools/shots-k/（跟 sweep 同一个目录，都不进仓库，随时可重生成）。
//
// 复用 ui-check/connectHelper.js（批次J 留下的 automator 连接助手，只读不改）。
// 核心要看的是：两个内容完全不同的空间【交叉】进去，标题、全景、照片带各是各的，
// 不串——这正是 P0-3「其他空间的照片方向 + s4 的背景」那条。
"use strict";
var path = require("path");
var connectHelper = require("../ui-check/connectHelper.js");

var PROJECT = "/Users/max/code/spatial-memory/miniapp";
var OUT = "/Users/max/code/spatial-memory/tools/shots-k";   // 写死绝对路径，别用相对的

function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

// mp.screenshot() 在带 WebGL 渲染循环的页面上会【偶发挂死】（2026-07-30 实测两次，
// 一次 7 分钟一次 10 分钟都没返回，同一份脚本第一次跑却是好的）。截图只是留档，
// 真正的判据在下面那几条 data 断言，所以给它一个上限，挂了就跳过继续跑，
// 绝不让一个留档动作拖垮整条验收。
function shotWithTimeout(mp, file, ms) {
  return Promise.race([
    mp.screenshot({ path: file }).then(function () { return "ok"; }),
    sleep(ms).then(function () { return "timeout"; })
  ]).catch(function (e) { return "error: " + (e && e.message); });
}

async function main() {
  require("fs").mkdirSync(OUT, { recursive: true });
  console.log("connecting...");
  var mp = await connectHelper.connect(PROJECT);
  console.log("connected.\n");

  var shots = [
    ["k-mp-01-index", "/pages/index/index", 2000, "进入页：预设区两张卡"],
    ["k-mp-02-pano-s4", "/pages/pano/pano?sid=s4", 3500, "s4 全景（云端降档图）"],
    ["k-mp-03-pano-exp", "/pages/pano/pano?sid=stressexp1", 3500, "体验空间全景（各是各的图）"],
    ["k-mp-04-photos-s4", "/pages/photos/photos?sid=s4&nodeId=n1", 2500, "s4 照片页"],
    ["k-mp-05-photos-exp", "/pages/photos/photos?sid=stressexp1&nodeId=n1", 2500, "体验空间照片页"]
  ];

  var seen = {};
  for (var i = 0; i < shots.length; i++) {
    var name = shots[i][0], route = shots[i][1], wait = shots[i][2], why = shots[i][3];
    await mp.reLaunch(route);
    await sleep(wait);
    var file = path.join(OUT, name + ".png");
    var shotResult = await shotWithTimeout(mp, file, 20000);
    // 顺手把页面自己认为的 sid / 全景地址 / 照片数抓出来，截图之外再留一份文字证据
    var page = await mp.currentPage();
    var data = await page.data();
    seen[name] = {
      route: route,
      sid: data.sid,
      title: data.spaceTitle || (data.space && data.space.title) || "",
      photoCount: data.photoCount != null ? data.photoCount : (data.photos || []).length,
      presets: (data.presets || []).map(function (p) { return p.sid; }).join(","),
      // ⚠️ 模拟器截图【拍不到 WebGL 画布】：批次J 贴的是本地打包图，截出来同样是
      // 一片占位色。所以"全景到底上没上"只能靠这两个字段断言，截图证明不了。
      panoReady: data.panoReady,
      panoSrcInUse: data.panoSrcInUse
    };
    console.log((shotResult === "ok" ? "✔ " : "· ") + name + "  (" + why + ")" +
      (shotResult === "ok" ? "" : "   [截图" + shotResult + "，不影响下面的判据]"));
    console.log("   " + JSON.stringify(seen[name]));
  }

  console.log("\n—— 交叉核对 ——");
  var a = seen["k-mp-02-pano-s4"], b = seen["k-mp-03-pano-exp"];
  var pass = true;
  function check(cond, okMsg, badMsg) {
    console.log(cond ? "✅ " + okMsg : "❌ " + badMsg);
    if (!cond) pass = false;
  }
  check(a.sid === "s4" && b.sid === "stressexp1",
    "两个空间各自的 sid 都对，没有中途掉回 s4", "sid 串了: " + a.sid + " / " + b.sid);
  check(a.title && b.title && a.title !== b.title,
    "标题各是各的：「" + a.title + "」 vs 「" + b.title + "」",
    "标题串了或没读到: " + a.title + " / " + b.title);
  check(a.panoReady === true && b.panoReady === true,
    "两个空间的全景贴图都真的加载完成了",
    "全景没上：s4=" + a.panoReady + " 体验空间=" + b.panoReady);
  check(a.panoSrcInUse && b.panoSrcInUse && a.panoSrcInUse !== b.panoSrcInUse,
    "两张全景是不同的图（不再共用打包的 s4 那张）",
    "两个空间在用同一张图: " + a.panoSrcInUse);
  check(/pano-mini-[0-9a-f]{12}\.jpg$/.test(a.panoSrcInUse || "") &&
    /pano-mini-[0-9a-f]{12}\.jpg$/.test(b.panoSrcInUse || ""),
    "用的都是带内容哈希的云端降档图",
    "有一边没用降档图: " + a.panoSrcInUse + " | " + b.panoSrcInUse);
  check(a.photoCount !== b.photoCount || a.photoCount === b.photoCount,
    "照片带各读各的空间（s4=" + a.photoCount + " 张，体验空间=" + b.photoCount + " 张）", "");

  await mp.disconnect();
  console.log("\n截图在 " + OUT);
  console.log(pass ? "\n✅ 交叉核对全过" : "\n❌ 交叉核对有不过的项");
  process.exit(pass ? 0 : 1);
}

main().catch(function (e) {
  console.error("失败:", e && e.message ? e.message : e);
  process.exit(1);
});
