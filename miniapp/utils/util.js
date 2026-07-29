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

var SPACE_ID = "s4";
var SPACE_JSON_URL = "https://psm-advx-2026.oss-cn-hangzhou.aliyuncs.com/spaces/s4/space.json";
// 传照片走 H5 过渡：个人主体小程序拿不到 web-view 权限，复制这个链接去浏览器打开，
// 是 app/contract.md 之外这次任务书明确指定的方案，不是我们自己发明的权宜之计。
var UPLOAD_H5_URL = "https://unseen-d3gtp0sxh53bbef61-1316841054.tcloudbaseapp.com/web/join.html?s=s4";

// 三页共用同一份空间数据：先看 app.globalData 有没有缓存，没有才真的发一次请求。
// 失败不编数据，把 error 原样交回调用方，页面自己决定诚实空态长什么样。
function ensureSpace(cb) {
  var app = getApp();
  if (app.globalData.space) {
    cb(null, app.globalData.space);
    return;
  }
  wx.request({
    url: SPACE_JSON_URL,
    success: function (res) {
      if (res.statusCode === 200 && res.data && typeof res.data === "object") {
        app.globalData.space = res.data;
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
  ensureSpace: ensureSpace
};
