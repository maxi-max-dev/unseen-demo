// 批次J验收:三屏截图，含新入口卡(index)与上传按钮(pano)可见。
"use strict";
var connectHelper = require("./connectHelper.js");

function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

async function main() {
  var projectPath = "/Users/max/code/spatial-memory/miniapp";
  console.log("connecting...");
  var mp = await connectHelper.connect(projectPath);
  console.log("connected.");

  await mp.reLaunch("/pages/index/index");
  await sleep(1800);
  await mp.screenshot({ path: "/Users/max/code/spatial-memory/ui-check/j-01-index.png" });
  console.log("shot 1 (index) done");

  await mp.reLaunch("/pages/pano/pano?sid=stressexp1");
  await sleep(2200);
  await mp.screenshot({ path: "/Users/max/code/spatial-memory/ui-check/j-02-pano.png" });
  console.log("shot 2 (pano, sid=stressexp1) done");

  await mp.reLaunch("/pages/photos/photos?sid=stressexp1");
  await sleep(1800);
  await mp.screenshot({ path: "/Users/max/code/spatial-memory/ui-check/j-03-photos.png" });
  console.log("shot 3 (photos, sid=stressexp1) done");

  await mp.disconnect();
  console.log("done, disconnected.");
  process.exit(0);
}

main().catch(function (err) {
  console.error("ERROR:", err && err.stack || err);
  process.exit(1);
});
