// 批次J额外验证(非acceptance硬性要求,是加强证据):不经过我自己写的node验收脚本，
// 而是真的驱动小程序里那份代码本身——mock chooseMedia的选图结果(自动化工具摸不到
// 原生相册弹窗，这是automator的标准限位)，之后 compress/uploadFile/轮询全部走
// 小程序自己的 utils/upload.js 真实代码路径，不是另一套模拟。
"use strict";
var connectHelper = require("./connectHelper.js");
var path = require("path");

function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

async function main() {
  var projectPath = "/Users/max/code/spatial-memory/miniapp";
  var testImage = process.argv[2] || path.join(projectPath, "assets", "panos", "expo.jpg");
  console.log("connecting...");
  var mp = await connectHelper.connect(projectPath);
  console.log("connected.");

  var page = await mp.reLaunch("/pages/pano/pano?sid=stressexp1");
  await sleep(2000);

  console.log("mocking wx.chooseMedia -> 真实本地文件", testImage);
  await mp.mockWxMethod("chooseMedia", {
    tempFiles: [{ tempFilePath: testImage, size: 199953, fileType: "image" }],
    type: "image"
  });

  var btn = await page.$(".upload-btn");
  if (!btn) throw new Error("找不到 .upload-btn 元素");
  console.log("tap .upload-btn ...");
  await btn.tap();

  var lastText = null;
  for (var i = 0; i < 20; i++) {
    await sleep(1500);
    var text = await page.data("uploadStatusText");
    var visible = await page.data("uploadBarVisible");
    if (text !== lastText) {
      console.log("[t+" + (i * 1.5).toFixed(1) + "s] uploadBarVisible=" + visible + " uploadStatusText=" + JSON.stringify(text));
      lastText = text;
    }
    if (text && (text.indexOf("回到方位") >= 0 || text.indexOf("排队") >= 0 || text.indexOf("传失败") >= 0 || text.indexOf("过期") >= 0)) {
      break;
    }
  }

  await mp.screenshot({ path: "/Users/max/code/spatial-memory/ui-check/j-04-upload-e2e.png" });
  console.log("screenshot j-04-upload-e2e.png saved");

  await mp.disconnect();
  console.log("done.");
  process.exit(0);
}

main().catch(function (err) {
  console.error("ERROR:", err && err.stack || err);
  process.exit(1);
});
