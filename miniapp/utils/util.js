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

// ============================================================
// 批次K：sid 贯穿三页，不许中途丢
// ============================================================
// 以前每一页各写一句 `(query && query.sid) || DEFAULT_SPACE_ID`。看着没问题，
// 真正的坑在【跳转那一头】：index 的「走进这段记忆」跳 pano 时压根没带 sid，
// 于是不管你从哪个空间进来，pano 都"兜底"回 s4——数据是别的空间的，背景是 s4 的，
// 正是 P0-3 那条。所以现在统一：读用 resolveSid()，跳用 pageUrl()，谁都别再手拼。
function resolveSid(query) {
  var raw = query && query.sid;
  var sid = String(raw || "").trim();
  if (!sid) {
    // 兜底本身是合法的（用户直接从小程序历史入口进来，确实没有 sid），
    // 但要留一句日志——线上真出现"怎么又是 s4"的时候，这句是唯一的线索。
    console.warn("[unseen] 这一跳没带 sid，兜底成 " + DEFAULT_SPACE_ID + "。若不是从首页直接进来，就是某处跳转漏了 sid。");
    return DEFAULT_SPACE_ID;
  }
  return sid;
}

// 页面间跳转统一从这里拼 url，sid 永远在。
function pageUrl(page, sid, extra) {
  var url = "/pages/" + page + "/" + page + "?sid=" + encodeURIComponent(sid || DEFAULT_SPACE_ID);
  if (extra) {
    Object.keys(extra).forEach(function (k) {
      if (extra[k] !== undefined && extra[k] !== null && extra[k] !== "") {
        url += "&" + k + "=" + encodeURIComponent(extra[k]);
      }
    });
  }
  return url;
}

// ============================================================
// 批次K：全景取图。动态跟着空间和节点走，不再写死 s4
// ============================================================
// 服务端(server/publish.py 的 _ensure_pano_mini)现在每个节点都发一张 2048x1024
// 的降档图，字段 panoMini，文件名带源图内容哈希。真机加载 >2000px 的图失败率
// 接近 100%（开发者工具测不出来），所以【优先取 panoMini】；没有它宁可退回本地
// 兜底也不去拉 4096 的原图——拉了大概率就是白屏。
var OFFLINE_PANO = { s4: "/assets/panos/s4-n1.jpg" };

function panoSourceFor(sid, node) {
  if (node && node.panoMini) return { src: node.panoMini, offline: false };
  // 这个空间还没发过降档图（老快照/生成失败）。只有打包进小程序的那个空间
  // 才有离线兜底可用，其余空间诚实报没有，页面去显示空态，绝不拿 s4 的背景
  // 冒充别人的空间。
  if (OFFLINE_PANO[sid]) return { src: OFFLINE_PANO[sid], offline: true };
  return { src: null, offline: false };
}

// 当前该看哪个节点：带了 nodeId 就找它，找不到或没带就用第一个。
function pickNode(space, nodeId) {
  var nodes = (space && space.nodes) || [];
  if (!nodes.length) return null;
  if (nodeId) {
    for (var i = 0; i < nodes.length; i++) {
      if (String(nodes[i].id) === String(nodeId)) return nodes[i];
    }
  }
  return nodes[0];
}

// 照片按 nodeId 过滤。老快照里的照片可能没有 nodeId 字段——那种情况下整个空间
// 也只可能有一个节点（多节点是后来才有的），所以缺字段时归给当前节点，不丢照片。
function photosOfNode(space, nodeId) {
  var all = (space && space.photos) || [];
  if (!nodeId) return all.slice();
  return all.filter(function (p) {
    return !p.nodeId || String(p.nodeId) === String(nodeId);
  });
}

// ============================================================
// 批次K：投稿状态文案。【唯一真源在 web/join.html 的 stateLabel()】
// ============================================================
// 契约要求两端同源(app/contract.md)。这张表是从 web/join.html:1466-1476 逐条抄的，
// 改任何一条都必须两边一起改，不然同一张照片在 H5 和小程序里会有两个说法。
var STATE_LABELS = {
  auto_ok: "已进空间",
  approved: "主办方通过",
  needs_review: "等主办方确认",
  rejected: "没被选上",
  quarantined: "放错地方了",
  scene_updated: "场景已更新",
  quota_full: "名额已满",
  uploaded: "AI 正在定位"
};

function stateLabel(state) {
  return STATE_LABELS[state] || "AI 处理中";
}

// 这些是【终态】：到这一步就别再说"排队中"了，也不用继续轮询。
// needs_review 不在里面是故意的——主办方随时可能通过它，下次打开小程序还要再看一眼。
var TERMINAL_STATES = ["auto_ok", "approved", "rejected", "quarantined", "scene_updated", "quota_full"];

function isTerminalState(state) {
  return TERMINAL_STATES.indexOf(state) >= 0;
}

// ============================================================
// 批次K：进入页的「选个空间看看」预设区
// ============================================================
var PRESET_SPACES = [
  { sid: "s4", name: "陈屹 ♥ 林沐", sub: "真实婚礼空间，只看不传" },
  { sid: "stressexp1", name: "体验空间 · 宴会厅", sub: "随便传张照片试试，看它回到方位" }
];

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
  fetchSpaceFresh: fetchSpaceFresh,
  resolveSid: resolveSid,
  pageUrl: pageUrl,
  panoSourceFor: panoSourceFor,
  pickNode: pickNode,
  photosOfNode: photosOfNode,
  stateLabel: stateLabel,
  isTerminalState: isTerminalState,
  PRESET_SPACES: PRESET_SPACES
};
