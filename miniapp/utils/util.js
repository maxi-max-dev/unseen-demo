// 三页共用的小工具：方向词、真数据地址、空间数据的单次拉取+缓存。
// 不重新发明口径——dirWord 从 web/show.html 原样抄来（任务书原文要求），
// SPACE_JSON_URL / UPLOAD_H5_URL 是仓库里已经在跑的真实公网地址，不是占位符。

// ============================================================
// 朝向：八方位词。原样抄自 web/show.html 的 dirWord()（第463行），
// 口径是"相对本次全景朝向"（正前方/右前方/右侧…），不是罗盘东南西北——
// 这是任务书明确要求"照抄"的函数，故意不改成设计稿里出现的罗盘词。
// ============================================================
function dirWord(yaw) {
  if (typeof yaw !== "number") return "";
  var words = ["正前方", "右前方", "右侧", "右后方", "正后方", "左后方", "左侧", "左前方"];
  return words[Math.round((((yaw % 360) + 360) % 360) / 45) % 8];
}

var SPACE_ID = "s4"; // 老默认值，字段保留，行为不变（下面 DEFAULT_SPACE_ID 是同一个值的新名字）
var OSS_BASE = "https://psm-advx-2026.oss-cn-hangzhou.aliyuncs.com";
var SPACE_JSON_URL = OSS_BASE + "/spaces/s4/space.json";
// 传照片走 H5 过渡：个人主体小程序拿不到 web-view 权限，复制这个链接去浏览器打开，
// 是 app/contract.md 之外这次任务书明确指定的方案，不是我们自己发明的权宜之计。
var UPLOAD_H5_URL = "https://unseen-d3gtp0sxh53bbef61-1316841054.tcloudbaseapp.com/web/join.html?s=s4";

// 批次J新增：sid 贯穿三页。DEFAULT_SPACE_ID 是没带 sid 参数时的兜底（=老默认值 s4，
// 行为完全不变）；EXPERIENCE_SPACE_ID 是 index 页新增的「体验空间」入口卡固定指向的
// 公共体验空间（2026-07-29 实测：nodes=1、published=true、upload policy 有效期到
// 2026-07-31，已就绪）——这条不读 s4 婚礼卡是故意的，测试上传不该混进真实婚礼相册。
var DEFAULT_SPACE_ID = SPACE_ID;
var EXPERIENCE_SPACE_ID = "stressexp1";

function spaceJsonUrl(sid) {
  return OSS_BASE + "/spaces/" + encodeURIComponent(sid) + "/space.json";
}

// 模块级缓存（不再挂 app.globalData）：小程序里 require() 同一个文件路径拿到的是
// 同一份模块实例（跟 Node 的 CommonJS 缓存同一个道理），三个页面 require 这个文件
// 天然共享这份 spaceCache，不需要经过 App() 实例中转。按 sid 分槽，換空间不会互相
// 冲掉缓存。
var spaceCache = {};

// 三页共用同一份空间数据：先看有没有缓存，没有才真的发一次请求。
// 失败不编数据，把 error 原样交回调用方，页面自己决定诚实空态长什么样。
// 兼容老调用方式 ensureSpace(cb)（sid 缺省=DEFAULT_SPACE_ID，行为跟批次I之前完全一样），
// 也支持新调用方式 ensureSpace(sid, cb)。
function ensureSpace(sidOrCb, cb) {
  var sid = DEFAULT_SPACE_ID;
  if (typeof sidOrCb === "function") {
    cb = sidOrCb;
  } else if (sidOrCb) {
    sid = sidOrCb;
  }
  if (spaceCache[sid]) {
    cb(null, spaceCache[sid]);
    return;
  }
  fetchSpaceFresh(sid, cb);
}

// 批次J新增：强制重拉，跳过缓存直接发请求（给上传/轮询用——上传前要拿最新 policy，
// 轮询要看 worker 刚写回的新照片，两者都不能用可能过时的缓存）。带时间戳打掉 OSS 的
// 缓存，跟 web/join.html 的 loadSpace() 同一个理由：不打时间戳，OSS 可能一直回旧的
// 那一份。成功了顺手把结果写回 spaceCache，其余读它的地方（比如页面下一次
// ensureSpace）也能看到最新数据，不用各自再发一次请求。
function fetchSpaceFresh(sid, cb) {
  wx.request({
    url: spaceJsonUrl(sid) + "?t=" + Date.now(),
    success: function (res) {
      if (res.statusCode === 200 && res.data && typeof res.data === "object") {
        spaceCache[sid] = res.data;
        cb(null, res.data);
      } else {
        cb(new Error("space.json http " + res.statusCode));
      }
    },
    fail: function (err) {
      cb(err || new Error("wx.request failed"));
    }
  });
}

module.exports = {
  dirWord: dirWord,
  SPACE_ID: SPACE_ID,
  SPACE_JSON_URL: SPACE_JSON_URL,
  UPLOAD_H5_URL: UPLOAD_H5_URL,
  OSS_BASE: OSS_BASE,
  DEFAULT_SPACE_ID: DEFAULT_SPACE_ID,
  EXPERIENCE_SPACE_ID: EXPERIENCE_SPACE_ID,
  spaceJsonUrl: spaceJsonUrl,
  ensureSpace: ensureSpace,
  fetchSpaceFresh: fetchSpaceFresh
};
