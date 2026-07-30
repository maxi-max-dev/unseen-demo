#!/usr/bin/env node
/**
 * 小程序达标六条的自动化回归（批次K）。
 *
 * 跑法（仓库根目录）：
 *     node tools/test_miniapp_contract.js
 * 退出码 0 = 通过。
 *
 * 为什么是这种写法：直接 require() 小程序【自己的】 utils/*.js，只给 wx 那几个
 * 宿主 API 打垫片。不另起一套"看起来像"的对照实现——那种测试只能证明我抄得对，
 * 证明不了产品代码对。这条路数是批次J的 ui-check/verify-upload.js 立的先例。
 *
 * 覆盖：a) sid 贯穿  b) 全景动态加载 + 内容哈希  c) nodeId 过滤
 *      d) photos[]+pending[] 全部终态  e) 回执/待重传落本地存储
 *      f) 预设空间清单
 * 测不到的（真机项，任务书明令不做）：chooseMedia 原生选图、真机大图加载、
 * 弱网、杀进程重开的真实体感。这几条如实留在 BLOCKED.md。
 */
const path = require("path");
const https = require("https");

const ROOT = path.dirname(__dirname);
const OSS = "https://psm-advx-2026.oss-cn-hangzhou.aliyuncs.com";

// ---------------------------------------------------------------- wx 垫片
const storage = {};
global.wx = {
  setStorageSync(k, v) { storage[k] = JSON.parse(JSON.stringify(v)); },
  getStorageSync(k) { return storage[k] !== undefined ? storage[k] : ""; },
  removeStorageSync(k) { delete storage[k]; },
  request() { throw new Error("本测试不该走 wx.request，用真 https 拉快照"); },
  arrayBufferToBase64: (buf) => Buffer.from(buf).toString("base64"),
  getFileSystemManager: () => ({ saveFile() {}, removeSavedFile() {} })
};

const util = require(path.join(ROOT, "miniapp/utils/util.js"));
const upload = require(path.join(ROOT, "miniapp/utils/upload.js"));

function get(url) {
  return new Promise((resolve, reject) => {
    https.get(url, (res) => {
      let body = "";
      res.on("data", (d) => (body += d));
      res.on("end", () => {
        if (res.statusCode !== 200) return reject(new Error(`HTTP ${res.statusCode} ${url}`));
        try { resolve(JSON.parse(body)); } catch (e) { reject(e); }
      });
    }).on("error", reject);
  });
}

const fails = [];
const ok = (cond, label, detail) => {
  console.log(`${cond ? "✅" : "❌"} ${label}${detail ? "  " + detail : ""}`);
  if (!cond) fails.push(label);
};

(async () => {
  // ---- a) sid 贯穿三页 ----
  console.log("\n【a】sid 贯穿三页");
  ok(util.resolveSid({ sid: "stressexp1" }) === "stressexp1", "带 sid 时原样用");
  ok(util.resolveSid({}) === util.DEFAULT_SPACE_ID, "没带 sid 时兜底(并打警告)");
  const panoUrl = util.pageUrl("pano", "stressexp1");
  const photosUrl = util.pageUrl("photos", "stressexp1", { nodeId: "n1", yaw: 120 });
  ok(/[?&]sid=stressexp1(&|$)/.test(panoUrl), "跳 pano 一定带 sid", panoUrl);
  ok(/[?&]sid=stressexp1(&|$)/.test(photosUrl) && /nodeId=n1/.test(photosUrl),
    "跳 photos 一定带 sid+nodeId", photosUrl);
  // 去 pano / photos 的跳转必须全部经过 util.pageUrl()，源码里不许再有手拼的。
  // 回首页(/pages/index/index)不在此列：进入页本来就没有 sid，它是 sid 的源头。
  const fs = require("fs");
  const pages = ["index/index", "pano/pano", "photos/photos"]
    .map((p) => fs.readFileSync(path.join(ROOT, "miniapp/pages", p + ".js"), "utf8"));
  const rawNav = (pages.join("\n").match(/url:\s*"\/pages\/[^"]*"/g) || [])
    .filter((u) => !u.includes("/pages/index/index"));
  ok(rawNav.length === 0, "去 pano/photos 的跳转没有一处是手拼的",
    rawNav.join(" | ") || "(零命中)");

  // ---- f) 预设空间 ----
  console.log("\n【f】进入页预设空间");
  const sids = util.PRESET_SPACES.map((p) => p.sid);
  ok(sids.length >= 2 && sids.includes("s4") && sids.includes("stressexp1"),
    "预设区有 s4 和 stressexp1 两张卡", sids.join(", "));

  // ---- b) 全景动态加载 ----
  console.log("\n【b】全景随空间动态加载");
  const s4 = await get(`${OSS}/spaces/s4/space.json?t=${Date.now()}`);
  const exp = await get(`${OSS}/spaces/stressexp1/space.json?t=${Date.now()}`);
  const s4node = util.pickNode(s4, null);
  const expnode = util.pickNode(exp, null);
  ok(!!s4node.panoMini, "s4 的节点带 panoMini", s4node.panoMini);
  ok(!!expnode.panoMini, "stressexp1 的节点带 panoMini", expnode.panoMini);
  ok(s4node.panoMini !== expnode.panoMini,
    "两个空间的全景地址不同(不再共用打包的 s4 那张)");
  const hashRe = /pano-mini-[0-9a-f]{12}\.jpg$/;
  ok(hashRe.test(s4node.panoMini) && hashRe.test(expnode.panoMini),
    "文件名带内容哈希(换图必然换名，旧缓存命不中)");
  const src4 = util.panoSourceFor("s4", s4node);
  const srcE = util.panoSourceFor("stressexp1", expnode);
  ok(src4.src === s4node.panoMini && !src4.offline, "s4 取云端降档图，不是离线兜底");
  ok(srcE.src === expnode.panoMini && !srcE.offline, "stressexp1 取自己的降档图");
  // 降档图必须真的存在且是 2048 宽（真机 >2000px 近乎必挂）
  for (const [label, node] of [["s4", s4node], ["stressexp1", expnode]]) {
    const head = await new Promise((res) => {
      https.request(node.panoMini, { method: "HEAD" }, (r) =>
        res({ code: r.statusCode, len: Number(r.headers["content-length"] || 0) })
      ).on("error", () => res({ code: 0, len: 0 })).end();
    });
    ok(head.code === 200, `${label} 的降档图云端可读`, `HTTP ${head.code}, ${Math.round(head.len / 1024)}KB`);
  }
  // 离线兜底只对 s4 生效，别的空间宁可空着也不拿 s4 的背景冒充
  ok(util.panoSourceFor("s4", null).src === "/assets/panos/s4-n1.jpg",
    "s4 有离线兜底");
  ok(util.panoSourceFor("stressexp1", null).src === null,
    "别的空间没有兜底，宁可报错也不拿 s4 的背景冒充(P0-3 的核心)");

  // ---- c) nodeId 过滤 ----
  console.log("\n【c】照片按 nodeId 过滤");
  const fake = {
    nodes: [{ id: "n1" }, { id: "n2" }],
    photos: [
      { id: "p1", nodeId: "n1", yaw: 10 },
      { id: "p2", nodeId: "n2", yaw: 20 },
      { id: "p3", nodeId: "n1", yaw: 30 },
      { id: "p4", yaw: 40 }        // 老快照没有 nodeId 字段
    ]
  };
  const n1 = util.photosOfNode(fake, "n1").map((p) => p.id);
  const n2 = util.photosOfNode(fake, "n2").map((p) => p.id);
  ok(JSON.stringify(n1) === '["p1","p3","p4"]', "n1 只拿自己的(缺字段的老照片归当前节点)", n1.join(","));
  ok(JSON.stringify(n2) === '["p2","p4"]', "n2 拿不到 n1 的照片", n2.join(","));
  ok(util.pickNode(fake, "n2").id === "n2", "pickNode 认 nodeId，不再永远第一个");
  ok(util.pickNode(fake, "不存在").id === "n1", "nodeId 认不出时退回第一个，不崩");

  // ---- d) photos[] + pending[] 全部终态 ----
  console.log("\n【d】消费 photos[] + pending[] 全部终态");
  const all = upload._all();
  all.length = 0;
  const cases = [
    ["k-auto", "photos", "auto_ok", "已进空间"],
    ["k-appr", "photos", "approved", "主办方通过"],
    ["k-rev", "pending", "needs_review", "等主办方确认"],
    ["k-rej", "pending", "rejected", "没被选上"],
    ["k-qua", "pending", "quarantined", "放错地方了"],
    ["k-full", "pending", "quota_full", "名额已满"],
    ["k-scene", "pending", "scene_updated", "场景已更新"]
  ];
  cases.forEach(([key]) => all.push({
    sid: "T", inboxKey: key, status: "localizing", uploadedAt: Date.now()
  }));
  upload.applySnapshot("T", {
    photos: cases.filter((c) => c[1] === "photos")
      .map((c) => ({ inboxKey: c[0], state: c[2] === "auto_ok" ? undefined : c[2], yaw: 90, src: "x", thumb: "t" })),
    pending: cases.filter((c) => c[1] === "pending")
      .map((c) => ({ inboxKey: c[0], state: c[2], note: "后端给的人话" }))
  });
  cases.forEach(([key, , state, label]) => {
    const item = all.find((i) => i.inboxKey === key);
    ok(item.status === "settled" && upload.statusLabel(item) === label,
      `${state} → 「${label}」`, `实得「${upload.statusLabel(item)}」`);
  });
  ok(!all.some((i) => upload.statusLabel(i) === "AI 还在排队,稍后回来看"),
    "没有任何一条被含糊成「还在排队」(P1-8 就是这条)");
  // 文案必须跟 web/join.html 的 stateLabel() 逐字相同
  const joinSrc = fs.readFileSync(path.join(ROOT, "web/join.html"), "utf8");
  const mismatched = cases.filter(([, , state, label]) =>
    !new RegExp(`s === "${state}"\\) return \\{ cls: "[a-z]+", txt: "${label}" \\}`).test(joinSrc));
  ok(mismatched.length === 0, "七条文案与 web/join.html 逐字同源",
    mismatched.map((m) => m[2]).join(",") || "(零差异)");
  // needs_review 不是终态：主办方随时可能通过，下次打开还要再看
  ok(!util.isTerminalState("needs_review"), "待审不算终态，会继续核对");
  ok(util.isTerminalState("rejected") && util.isTerminalState("quota_full"),
    "被拒/名额满是终态，不再空转轮询");

  // ---- e) 回执落本地存储 ----
  console.log("\n【e】回执与待重传落本地存储");
  const saved = wx.getStorageSync(upload.STORE_KEY);
  ok(Array.isArray(saved) && saved.length === cases.length,
    "终态写进了 wx 本地存储", `${saved.length} 条`);
  ok(saved.every((i) => i.tempFilePath === undefined),
    "临时文件路径没被存(存了下次也是失效路径，等于骗自己还能重传)");
  ok(saved.some((i) => i.serverState === "rejected"),
    "存的是服务器终态本身，不是本地猜的");
  // 模拟杀进程重开：清空内存、重新 require
  all.length = 0;
  delete require.cache[require.resolve(path.join(ROOT, "miniapp/utils/upload.js"))];
  const upload2 = require(path.join(ROOT, "miniapp/utils/upload.js"));
  const restored = upload2.getMyUploads("T");
  ok(restored.length === cases.length, "杀进程重开后回执恢复", `${restored.length} 条`);
  ok(upload2.statusLabel(restored.find((i) => i.inboxKey === "k-rej")) === "没被选上",
    "恢复出来的状态仍然是真实终态");
  // 上次卡在"上传中"的，重开后必须如实变成失败，不能继续显示上传中
  wx.setStorageSync(upload.STORE_KEY, [{ sid: "T", inboxKey: "k-half", status: "uploading" }]);
  delete require.cache[require.resolve(path.join(ROOT, "miniapp/utils/upload.js"))];
  const upload3 = require(path.join(ROOT, "miniapp/utils/upload.js"));
  const half = upload3.getMyUploads("T")[0];
  ok(half.status === "error", "上次没传完的重开后如实标失败，不假装还在传", half.error);

  console.log(fails.length ? `\n❌ 不通过 ${fails.length} 条:\n  - ${fails.join("\n  - ")}`
    : "\n✅ 全部通过");
  process.exit(fails.length ? 1 : 0);
})().catch((e) => {
  console.error("❌ 测试自身出错:", e);
  process.exit(1);
});
