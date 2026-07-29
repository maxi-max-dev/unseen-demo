// 批次J验收脚本:真传一次，证明小程序的上传字段组装逻辑在真实 OSS 面前真的能走通。
// 不是另起一套"看起来像"的字段构造代码——直接 require 小程序自己的
// utils/upload.js / utils/util.js，跑的是同一份 extractPolicy()/buildKey()，
// 只在"wx.* 这几个宿主API"上打了个最小垫片(node 没有 wx 全局对象)。
//
// 用法: node ui-check/verify-upload.js [sid]  (默认 stressexp1)
"use strict";

var fs = require("fs");
var path = require("path");

// 小程序运行时提供的宿主API，node 里没有，这里只垫 upload.js 真正用到的那一个
// (encNick 里的 wx.arrayBufferToBase64)。不垫 wx.request/wx.chooseMedia 等——
// 本脚本不调用 startUpload()/ensureSpace() 这些需要完整宿主环境的函数，只用
// extractPolicy()/buildKey() 这两个纯数据函数，跟真机上跑的是同一段代码。
global.wx = {
  arrayBufferToBase64: function (buf) {
    return Buffer.from(buf).toString("base64");
  }
};

var upload = require(path.join(__dirname, "..", "miniapp", "utils", "upload.js"));

var SID = process.argv[2] || "stressexp1";
var OSS_BASE = "https://psm-advx-2026.oss-cn-hangzhou.aliyuncs.com";
var TEST_IMAGE = path.join(__dirname, "..", "miniapp", "assets", "panos", "expo.jpg");

function redact(s) {
  if (!s) return s;
  s = String(s);
  if (s.length <= 18) return s.slice(0, 4) + "...REDACTED";
  return s.slice(0, 10) + "..." + s.length + "chars...REDACTED..." + s.slice(-6);
}

async function main() {
  console.log("=== 批次J 上传链路真传验收 ===");
  console.log("sid =", SID);
  console.log("测试图 =", TEST_IMAGE, "(", fs.statSync(TEST_IMAGE).size, "bytes )");

  var spaceUrl = OSS_BASE + "/spaces/" + encodeURIComponent(SID) + "/space.json?t=" + Date.now();
  console.log("\n[1] 拉 space.json:", spaceUrl);
  var spRes = await fetch(spaceUrl, { cache: "no-store" });
  console.log("    HTTP", spRes.status);
  if (!spRes.ok) throw new Error("space.json 拉不到，HTTP " + spRes.status);
  var sp = await spRes.json();
  console.log("    nodes=" + (sp.nodes || []).length, "photos=" + (sp.photos || []).length, "published=" + sp.published);

  // 跟小程序上传模块同一个函数：extractPolicy() 是 upload.js 里真在跑的那份。
  var pol = upload.extractPolicy(sp, SID);
  if (!pol) throw new Error("这个空间没有可用的上传 policy(extractPolicy 返回 null)");
  console.log("\n[2] extractPolicy() 结果(跟 miniapp/utils/upload.js 同一份代码算出来的):");
  console.log("    host       =", pol.host);
  console.log("    keyPrefix  =", pol.keyPrefix);
  console.log("    maxSize    =", pol.maxSize, "bytes");
  console.log("    expiresAt  =", pol.expiresAt, "(", new Date(pol.expiresAt * 1000).toISOString(), ")");
  console.log("    now        =", "(", new Date().toISOString(), ")");
  console.log("    accessKeyId=", redact(pol.accessKeyId));
  console.log("    policy(b64)=", redact(pol.policy));
  console.log("    signature  =", redact(pol.signature));
  if (pol.expiresAt && pol.expiresAt * 1000 < Date.now()) {
    console.log("    !! policy 已过期，接下来的 POST 预期会被 OSS 拒绝(这也是诚实的一部分，不假装)");
  }

  // 跟小程序上传模块同一个函数：buildKey() 是 upload.js 里真在跑的那份。
  var built = upload.buildKey(pol.keyPrefix, "验收脚本测试");
  console.log("\n[3] buildKey() 结果:");
  console.log("    key      =", built.key);
  console.log("    inboxKey =", built.inboxKey, " (worker 应该会拿这段回填 photos[]/pending[] 的 inboxKey 字段)");

  // 跟 miniapp/utils/upload.js 的 uploadOne() 里 wx.uploadFile 的 formData 参数
  // 完全一致的字段集合(顺序也一致)，file 字段在 wx.uploadFile 里由平台单独用
  // filePath/name 处理、天然排在 formData 所有字段之后，这里用 FormData.append()
  // 顺序复刻同一个效果。
  var formDataFields = {
    key: built.key,
    OSSAccessKeyId: pol.accessKeyId,
    policy: pol.policy,
    Signature: pol.signature,
    "x-oss-object-acl": "private",
    success_action_status: "201"
  };
  console.log("\n[4] miniapp uploadOne() 组装的 formData 字段(顺序即下方顺序,file 最后):");
  Object.keys(formDataFields).forEach(function (k) {
    var v = formDataFields[k];
    if (k === "OSSAccessKeyId" || k === "policy" || k === "Signature") {
      console.log("    " + k + " =", redact(v));
    } else {
      console.log("    " + k + " =", v);
    }
  });
  console.log("    file (最后一个字段) = " + TEST_IMAGE);

  var fd = new FormData();
  Object.keys(formDataFields).forEach(function (k) { fd.append(k, formDataFields[k]); });
  var fileBuf = fs.readFileSync(TEST_IMAGE);
  fd.append("file", new Blob([fileBuf], { type: "image/jpeg" }), "photo.jpg");

  console.log("\n[5] 真传 POST ->", pol.host);
  var postRes = await fetch(pol.host, { method: "POST", body: fd });
  var bodyText = await postRes.text();
  console.log("    HTTP", postRes.status);
  console.log("    响应体:", bodyText.slice(0, 800) || "(空)");

  var ok = postRes.status >= 200 && postRes.status < 300;
  console.log("\n=== 结果:", ok ? ("成功，HTTP " + postRes.status) : ("失败，HTTP " + postRes.status), "===");

  if (ok) {
    console.log("\n[6] curl 收件箱前缀，确认对象是否可见(private ACL，预期可能拿到403——");
    console.log("    那是权限层面的诚实拒绝，不代表对象没写进去；201本身已经是OSS写入成功的权威判断):");
    var listUrl = OSS_BASE + "/?prefix=" + encodeURIComponent(pol.keyPrefix) + "&list-type=2&max-keys=5";
    try {
      var listRes = await fetch(listUrl);
      var listText = await listRes.text();
      console.log("    GET", listUrl);
      console.log("    HTTP", listRes.status);
      console.log("    响应体前800字:", listText.slice(0, 800));
    } catch (e) {
      console.log("    listing 请求本身失败:", e.message);
    }
    var objUrl = OSS_BASE + "/" + built.key.split("/").map(encodeURIComponent).join("/");
    try {
      var objRes = await fetch(objUrl, { method: "HEAD" });
      console.log("    HEAD", objUrl, "-> HTTP", objRes.status, "(private对象预期403，不代表不存在)");
    } catch (e) {
      console.log("    HEAD 对象请求失败:", e.message);
    }
  }

  console.log("\n[7] 待清理记录(写进 BLOCKED.md): sid=" + SID + " key=" + built.key);
  process.exit(ok ? 0 : 1);
}

main().catch(function (err) {
  console.error("\n!! 脚本出错:", err.message);
  process.exit(2);
});
