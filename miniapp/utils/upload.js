// 批次J新增：上传模块。动线：拉 space.json 拿 policy(缓存,一批最多3张共用一次)
// -> wx.chooseMedia 选图 -> 压缩 -> wx.uploadFile 直传 OSS -> 轮询 space.json
// 等 worker 把 yaw 算出来。
//
// 唯一验证过的真源是 web/join.html(任务书原文点名)，机制照抄它:
//   - 直传字段: key / OSSAccessKeyId / policy / Signature / x-oss-object-acl，
//     file 必须最后一个字段(OSS硬要求,join.html ossPost()注释原话)。
//   - key 命名: <keyPrefix><毫秒时间戳>_<短id>__<base64url昵称>__<taskId>.jpg，
//     跟 Mac 上的 worker 对齐(join.html buildKey()注释)。
//   - 压缩参数: 长边1600、JPEG质量0.82(join.html CFG，任务书要求"抄join.html口径"，
//     不是任务书自己写的"2000/80"那两个数字，那只是任务书作者的粗略估计)。
//   - success_action_status:"201" 是任务书明确要求的字段(join.html本身没有，
//     默认应该是OSS的204)——已实测(见 PROGRESS.md 批次J)加了这个字段之后
//     OSS 真的回 201，policy 的 conditions 里没有限制这个字段，加了不会导致
//     签名校验失败。产品代码这边仍然把"任意 2xx"都当成功(不因为万一没拿到
//     201而误判失败)，双重保险。
// 跟 join.html 不同的一点:那边"每次真正POST前都重新拉一次space.json"(每文件
// 都拉)；这里"一批(最多3张)共用一次policy"，只在遇到"策略过期"类失败时才
// 补拉一次重试——任务书原文写的就是"policy过期重拉一次"，不是"每张都拉"。
//
// inboxKey 匹配:实测 s4 真实 space.json 里 pending[]/photos[] 都带 inboxKey
// 字段,格式正是"<毫秒时间戳>_<短id>"(跟 buildKey 拼出来的 key 前两段完全对上)，
// app/contract.md 的字段表没写这个字段(文档没跟上实际结构)，这里以实测数据为准。
var util = require("./util.js");

var MAX_COUNT = 3;
var MAX_EDGE = 1600; // 长边像素上限，抄 join.html CFG.maxEdge
var JPEG_QUALITY = 82; // wx.compressImage 用 0-100 标度，抄 join.html CFG.quality(0.82)*100
var POLL_INTERVAL_MS = 10000; // 10秒一次，任务书明确要求
var POLL_MAX_MS = 180000; // 最多3分钟，任务书明确要求——到点就诚实超时，不无限转

// ============================================================
// 批次K：上传回执 + 待重传队列落 wx 本地存储，杀进程重开能恢复
// ============================================================
// 批次J 这份记录只活在模块级数组里，小程序被杀就没了——宾客传完照片退出去，
// 再打开时"我传的"是空的，他分不清是没传成功还是记录丢了。现在写 wx 存储：
//   · 回执：每张照片的 key/inboxKey/状态/方位，重开后原样恢复，并且会再去
//     服务器核一次状态（主办方可能在这期间通过了待审的那张）。
//   · 待重传：传失败的那张，把【压缩后的文件】用 saveFile 存成持久路径再记下来。
//     wx.chooseMedia 给的 tempFilePath 进程一杀就失效，不落持久文件的话，
//     "待重传队列"只是一句好听的空话，重开之后根本没有东西可传。
var STORE_KEY = "unseen_uploads_v1";
var STORE_MAX = 60;              // 只留最近 60 条，别把人家的存储撑爆
var myUploads = [];
var pollTimers = {}; // sid -> setTimeout句柄，按sid分开，互不打断

// 落盘的字段是白名单。tempFilePath / _retried 这些进程内的东西一律不存——
// 存了下次也是错的（临时路径已失效），反而会骗自己"还能重传"。
var PERSIST_FIELDS = ["sid", "key", "inboxKey", "status", "serverState", "yaw",
  "thumb", "src", "error", "uploadedAt", "retryFilePath", "note"];

function persist() {
  try {
    var slim = myUploads.slice(0, STORE_MAX).map(function (item) {
      var out = {};
      PERSIST_FIELDS.forEach(function (k) {
        if (item[k] !== undefined && item[k] !== null) out[k] = item[k];
      });
      return out;
    });
    wx.setStorageSync(STORE_KEY, slim);
  } catch (e) {
    // 存不下不该影响正在进行的上传，本次会话内的内存记录仍然是准的。
    console.warn("[unseen] 上传回执没存进本地存储", e);
  }
}

function restore() {
  try {
    var saved = wx.getStorageSync(STORE_KEY);
    if (!saved || !saved.length) return;
    myUploads = saved.filter(function (item) { return item && item.sid; }).map(function (item) {
      // 上次被杀掉时还卡在"上传中"的，重开后既没在传也没有结果，如实标成失败，
      // 不能继续显示"上传中"骗人。有持久文件的进重传队列，没有的只能说清楚。
      if (item.status === "uploading") {
        item.status = "error";
        item.error = item.retryFilePath ? "上次没传完，可以重传" : "上次没传完，照片已经找不到了";
      }
      return item;
    });
  } catch (e) {
    myUploads = [];
  }
}

restore();

function errWithKind(message, kind) {
  var e = new Error(message);
  e.kind = kind;
  return e;
}

function shortId() {
  return Math.random().toString(36).slice(2, 8);
}

// 字符串 -> UTF-8 字节数组。小程序 JS 环境没有 TextEncoder/btoa，手写这一小段
// (含代理对/emoji 处理)，配合 wx.arrayBufferToBase64 凑出跟 join.html encNick()
// 等价的效果(那边用的是浏览器原生 TextEncoder+btoa)。
function utf8Bytes(str) {
  var bytes = [];
  for (var i = 0; i < str.length; i++) {
    var code = str.charCodeAt(i);
    if (code < 0x80) {
      bytes.push(code);
    } else if (code < 0x800) {
      bytes.push(0xc0 | (code >> 6), 0x80 | (code & 0x3f));
    } else if (code >= 0xd800 && code <= 0xdbff && i + 1 < str.length) {
      var next = str.charCodeAt(i + 1);
      if (next >= 0xdc00 && next <= 0xdfff) {
        var cp = 0x10000 + ((code - 0xd800) << 10) + (next - 0xdc00);
        bytes.push(
          0xf0 | (cp >> 18),
          0x80 | ((cp >> 12) & 0x3f),
          0x80 | ((cp >> 6) & 0x3f),
          0x80 | (cp & 0x3f)
        );
        i++;
      } else {
        bytes.push(0xe0 | (code >> 12), 0x80 | ((code >> 6) & 0x3f), 0x80 | (code & 0x3f));
      }
    } else {
      bytes.push(0xe0 | (code >> 12), 0x80 | ((code >> 6) & 0x3f), 0x80 | (code & 0x3f));
    }
  }
  return bytes;
}

// 昵称 -> base64url(UTF-8)，算法等价 join.html 的 encNick()。
function encNick(nick) {
  var s = String(nick || "guest");
  try {
    var bytes = utf8Bytes(s);
    var buf = new Uint8Array(bytes).buffer;
    var b64 = wx.arrayBufferToBase64(buf);
    return b64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  } catch (e) {
    return s.replace(/[^A-Za-z0-9_-]/g, "") || "guest";
  }
}

// key 命名约定跟 Mac 上的 worker 对齐(join.html buildKey()注释)：
//   <keyPrefix><毫秒时间戳>_<短id>__<base64url昵称>__free.jpg
// taskId 固定写 "free"——小程序这版没有任务墙/领任务流程，全部算自由投稿。
function buildKey(keyPrefix, nick) {
  var ts = Date.now();
  var sid = shortId();
  var key = keyPrefix + ts + "_" + sid + "__" + encNick(nick) + "__free.jpg";
  return { key: key, inboxKey: ts + "_" + sid };
}

// space.json 的 upload 字段 -> 归一化 policy 对象。三个别名(upload/post/direct)
// 都认，跟 join.html policyOf() 一样，防止字段名换了这边突然读不到。
function extractPolicy(sp, sid) {
  var up = (sp && (sp.upload || sp.post || sp.direct)) || null;
  if (!up || up.enabled === false || !up.policy) return null;
  var pol = {
    host: (up.host || "").replace(/\/+$/, ""),
    accessKeyId: up.OSSAccessKeyId || up.accessKeyId || "",
    policy: up.policy,
    signature: up.Signature || up.signature || "",
    keyPrefix: up.keyPrefix || ("spaces/" + sid + "/inbox/"),
    expiresAt: up.expiresAt || 0,
    maxSize: up.maxSize || 12 * 1024 * 1024
  };
  if (!pol.host || !pol.accessKeyId || !pol.policy || !pol.signature) return null;
  return pol;
}

// 强制重拉 space.json(不吃缓存)取最新 policy。上传前必须用这个，不能用
// util.ensureSpace 的缓存版本——缓存里的 policy 可能已经过期太久了(实测过
// s4 的缓存策略过期两天都没人续，见 PROGRESS.md 批次J)。
function fetchPolicy(sid, cb) {
  util.fetchSpaceFresh(sid, function (err, sp) {
    if (err) {
      cb(errWithKind("网络不好,连不上空间", "NETWORK"));
      return;
    }
    var pol = extractPolicy(sp, sid);
    if (!pol) {
      cb(errWithKind("这个空间还没开放上传", "NO_POLICY"));
      return;
    }
    if (pol.expiresAt && pol.expiresAt * 1000 < Date.now()) {
      cb(errWithKind("上传通道已过期,请稍后再试", "POLICY_EXPIRED"));
      return;
    }
    cb(null, pol);
  });
}

// 压缩一张图。优先 wx.compressImage(单次原生调用，任务书允许的两个方案之一)，
// 长边超过 1600 时顺带传 compressedWidth/compressedHeight 做等比缩放(部分老
// 基础库不支持这两个字段，多传的未知字段会被忽略，不会报错，退化成"只压
// 质量不缩尺寸"，仍然满足"传之前压缩过"这个底线)。压缩本身失败(极少见)不
// 阻断上传，退化用原图——压缩是"锦上添花"的体积优化，真正兜底的是 OSS
// policy 自己的 content-length-range，原图超限一样会被诚实分类成"文件太大"。
function compressOne(tempFilePath, cb) {
  function plainCompress() {
    wx.compressImage({
      src: tempFilePath,
      quality: JPEG_QUALITY,
      success: function (res) { cb(res.tempFilePath); },
      fail: function () { cb(tempFilePath); }
    });
  }
  wx.getImageInfo({
    src: tempFilePath,
    success: function (info) {
      var longEdge = Math.max(info.width || 0, info.height || 0);
      var opts = {
        src: tempFilePath,
        quality: JPEG_QUALITY,
        success: function (res) { cb(res.tempFilePath); },
        fail: function () { cb(tempFilePath); }
      };
      if (longEdge > MAX_EDGE && info.width && info.height) {
        var scale = MAX_EDGE / longEdge;
        opts.compressedWidth = Math.round(info.width * scale);
        opts.compressedHeight = Math.round(info.height * scale);
      }
      wx.compressImage(opts);
    },
    fail: plainCompress
  });
}

// 状态文案统一在这里维护一次，pano 页状态条和 photos 页"我传的"标签共用。
//
// 批次K：服务器给的终态一律【如实转述】，不再一律说"排队中"。
// 服务端的状态词表在 util.STATE_LABELS，那张表是从 web/join.html 的 stateLabel()
// 逐条抄的——契约要求两端同源，同一张照片在 H5 和小程序里不能有两个说法。
// 这里只负责把"本地阶段"（还没传完/传失败）和"服务器阶段"接上。
function statusLabel(item) {
  switch (item.status) {
    case "uploading": return "上传中";
    case "localizing": return "AI 正在定位…";
    case "settled": return util.stateLabel(item.serverState);
    case "timeout": return "AI 还在排队,稍后回来看";
    case "error": return item.error || "传失败了";
    default: return "";
  }
}

// 这张照片还该不该继续盯着？
function isSettled(item) {
  return item.status === "settled" && util.isTerminalState(item.serverState);
}

// 真正的单文件上传(压缩+POST)。pol 用一个单元素容器传，是因为"策略过期重拉
// 一次"命中时要把新 policy 带回给调用方，让同一批里排在后面的文件也用上，
// 不用每个文件各自再判断一次过期。
function uploadOne(sid, polBox, item, doneCb) {
  compressOne(item.tempFilePath, function (compressedPath) {
    wx.getFileInfo({
      filePath: compressedPath,
      success: function (info) { postItem(compressedPath, info.size); },
      fail: function () { postItem(compressedPath, 0); } // 拿不到大小就不做客户端预检，交给OSS的content-length-range条件去拦
    });
  });

  function postItem(filePath, size) {
    var pol = polBox.value;
    if (size && pol.maxSize && size > pol.maxSize) {
      item.status = "error";
      item.error = "文件太大,传不上去(" + (Math.round(size / 1024 / 1024 * 10) / 10) + "MB,上限" + Math.round(pol.maxSize / 1024 / 1024) + "MB)";
      persist();
      // 太大这条不进重传队列：同一张图再传一次还是太大，只会让人白按一次按钮。
      doneCb();
      return;
    }
    var built = buildKey(pol.keyPrefix, "小程序访客");
    item.key = built.key;
    item.inboxKey = built.inboxKey;
    wx.uploadFile({
      url: pol.host,
      filePath: filePath,
      name: "file",
      formData: {
        key: built.key,
        OSSAccessKeyId: pol.accessKeyId,
        policy: pol.policy,
        Signature: pol.signature,
        "x-oss-object-acl": "private",
        // 任务书明确要求的字段，用来拿到确定性的201(join.html本身没加这个字段，
        // 默认会是204——这里加上是任务书的显式要求，见文件头注释)。
        success_action_status: "201"
      },
      success: function (res) { handleResponse(res.statusCode, res.data || "", filePath); },
      fail: function (err) {
        var msg = (err && err.errMsg) || "";
        item.status = "error";
        item.error = /timeout/i.test(msg) ? "网络太慢,传失败了" : "网络不好,传失败了";
        saveForRetry(item, filePath);   // 网络原因，值得留着重传
        doneCb();
      }
    });
  }

  function handleResponse(statusCode, body, filePath) {
    if (statusCode >= 200 && statusCode < 300) {
      item.status = "localizing";
      item.uploadedAt = Date.now();
      dropRetryFile(item);              // 传上去了，持久副本没用了，别占人家存储
      persist();
      doneCb();
      return;
    }
    var expired = /expir/i.test(body);
    var tooBig = /EntityTooLarge|content-length-range/i.test(body);
    if (tooBig) {
      item.status = "error";
      item.error = "文件太大,传不上去";
      persist();
      doneCb();
      return;
    }
    if ((expired || statusCode === 403) && !item._retried) {
      item._retried = true;
      fetchPolicy(sid, function (err2, freshPol) {
        if (err2) {
          item.status = "error";
          item.error = "上传通道过期,请稍后再试";
          saveForRetry(item, filePath); // 通道续上之后这张还能补传
          doneCb();
          return;
        }
        polBox.value = freshPol; // 同一批后面的文件也用这份刷新过的policy
        postItem(filePath, 0); // 重试这一次，不再做大小预检(上一轮已经过了)
      });
      return;
    }
    item.status = "error";
    item.error = "传失败了(HTTP " + statusCode + ")";
    saveForRetry(item, filePath);
    doneCb();
  }
}

// ============================================================
// 批次K：待重传队列
// ============================================================
// wx.chooseMedia 给的 tempFilePath 进程一杀就失效。不把压缩后的文件落成持久
// 文件，"待重传队列"就只是一个失效路径的列表，重开之后按重传只会再失败一次。
// 所以只在【传失败】时才 saveFile（成功的不占存储），成功后立刻删掉副本。
function saveForRetry(item, filePath) {
  if (!filePath || item.retryFilePath) { persist(); return; }
  try {
    wx.getFileSystemManager().saveFile({
      tempFilePath: filePath,
      success: function (res) { item.retryFilePath = res.savedFilePath; persist(); },
      fail: function () { persist(); }   // 存不下就不记，重传时会如实说照片找不到了
    });
  } catch (e) {
    persist();
  }
}

function dropRetryFile(item) {
  if (!item.retryFilePath) return;
  var path = item.retryFilePath;
  item.retryFilePath = null;
  try {
    wx.getFileSystemManager().removeSavedFile({ filePath: path, fail: function () {} });
  } catch (e) { /* 删不掉只是占点存储，不影响正确性 */ }
}

function retryQueue(sid) {
  return myUploads.filter(function (p) {
    return p.sid === sid && p.status === "error" && p.retryFilePath;
  });
}

// 把待重传的全部再传一遍。回调 (成功发起的条数, 错误)。
function retryFailed(sid, cb) {
  var queue = retryQueue(sid);
  if (!queue.length) { if (cb) cb(0, null); return; }
  fetchPolicy(sid, function (err, pol) {
    if (err) { if (cb) cb(0, err); return; }
    var polBox = { value: pol };
    queue.forEach(function (item) {
      item.status = "uploading";
      item.error = null;
      item._retried = false;
      item.tempFilePath = item.retryFilePath;   // 持久副本就是这次要传的东西
    });
    persist();
    var i = 0;
    (function next() {
      if (i >= queue.length) {
        if (queue.some(function (it) { return it.status === "localizing"; })) ensurePolling(sid);
        persist();
        if (cb) cb(queue.length, null);
        return;
      }
      uploadOne(sid, polBox, queue[i++], next);
    })();
  });
}

// 轮询 space.json，找 inboxKey 匹配的照片有没有出现在 photos[] 里。每个 sid
// 一条独立的定时器，10秒一次，每个 item 各自的3分钟大限到了就诚实标超时——
// 这个判断在每次tick都做，不依赖网络请求本身成不成功，不会被"一直请求失败"
// 卡成永远不超时。
// 批次K：把一份快照套到本地回执上。photos[] 和 pending[] 【两个都看】。
//
// 批次J 只查 photos[]，那里面只有已入选的照片——待审/被拒/隔离/名额满的照片
// 永远查不到，于是一律显示"排队中"，三分钟后统一说"AI 还在排队"。宾客那张
// 明明已经被主办方拒了，小程序还在让他等，这是 P1-8。
// publish.py 把这四种终态写进 pending[]（不含图、不含机器分，隐私裁剪见 publish.py），
// 现在两个数组一起认，各说各的实话。
function applySnapshot(sid, sp) {
  var photos = (sp && sp.photos) || [];
  var pending = (sp && sp.pending) || [];
  var changed = false;

  myUploads.forEach(function (item) {
    if (item.sid !== sid || !item.inboxKey || isSettled(item)) return;

    var hit = photos.filter(function (p) { return p.inboxKey && p.inboxKey === item.inboxKey; })[0];
    if (hit) {
      // 云版 photos[] 不带 state 字段（只有 pending[] 有）——照 web/join.html
      // photoState() 的口径：能出现在 photos[] 里就说明已入选。
      item.status = "settled";
      item.serverState = hit.state || "auto_ok";
      item.yaw = typeof hit.yaw === "number" ? hit.yaw : parseFloat(hit.yaw);
      item.thumb = hit.thumb || hit.src;
      item.src = hit.src;
      item.note = null;
      changed = true;
      return;
    }

    var wait = pending.filter(function (p) { return p.inboxKey && p.inboxKey === item.inboxKey; })[0];
    if (wait && wait.state) {
      item.status = "settled";
      item.serverState = wait.state;
      item.note = wait.note || null;
      changed = true;
    }
  });

  if (changed) persist();
  return changed;
}

// 还在等结果的条目：刚传完在定位的，以及重开小程序后恢复出来、主办方可能
// 已经处理过的待审条目。
function waitingItems(sid) {
  return myUploads.filter(function (p) {
    if (p.sid !== sid) return false;
    if (p.status === "localizing") return true;
    // 待审不是终态：主办方随时可能点通过，下次打开还要再看一眼。
    return p.status === "settled" && p.serverState === "needs_review";
  });
}

function ensurePolling(sid) {
  if (pollTimers[sid]) return;
  function tick() {
    var now = Date.now();
    var touched = false;
    myUploads.forEach(function (item) {
      if (item.sid === sid && item.status === "localizing" && now - item.uploadedAt > POLL_MAX_MS) {
        item.status = "timeout";
        touched = true;
      }
    });
    if (touched) persist();
    if (!waitingItems(sid).length) {
      pollTimers[sid] = null;
      return;
    }
    util.fetchSpaceFresh(sid, function (err, sp) {
      if (!err && sp) applySnapshot(sid, sp);
      pollTimers[sid] = waitingItems(sid).length ? setTimeout(tick, POLL_INTERVAL_MS) : null;
    });
  }
  pollTimers[sid] = setTimeout(tick, POLL_INTERVAL_MS);
}

// 页面每次变可见时调一次：拿最新快照核对一遍恢复出来的回执。
// 覆盖的是"传完就退出小程序，主办方后来点了通过，第二天再打开"这条路径——
// 光有本地存储不够，存的是当时的状态，不去核对就是拿旧结论当新结论。
function refreshFromServer(sid, cb) {
  if (!waitingItems(sid).length) {
    if (cb) cb(false);
    return;
  }
  util.fetchSpaceFresh(sid, function (err, sp) {
    var changed = (!err && sp) ? applySnapshot(sid, sp) : false;
    if (cb) cb(changed);
  });
}

// 对外主入口：选图 -> 建批次条目(立刻回调，页面拿到 batch 引用后自己按需
// 轮询这几个对象的 status 字段——上传/压缩/POST 都会直接改这些对象自身，
// 页面手里的引用天然同步，不需要另外一套订阅/发布机制)。
function startUpload(sid, cb) {
  wx.chooseMedia({
    count: MAX_COUNT,
    mediaType: ["image"],
    sourceType: ["album", "camera"],
    success: function (res) {
      var files = res.tempFiles || [];
      if (!files.length) {
        cb(errWithKind("没有选到照片", "CANCELLED"), null);
        return;
      }
      var batch = files.map(function (f) {
        var item = {
          sid: sid,
          tempFilePath: f.tempFilePath,
          key: null,
          inboxKey: null,
          status: "uploading",
          yaw: null,
          thumb: null,
          src: null,
          error: null,
          uploadedAt: 0,
          _retried: false
        };
        myUploads.unshift(item);
        return item;
      });
      persist();
      cb(null, batch);
      runBatch(sid, batch);
    },
    fail: function (err) {
      var msg = (err && err.errMsg) || "";
      if (msg.indexOf("cancel") >= 0) {
        cb(errWithKind("没有选照片", "CANCELLED"), null);
      } else {
        cb(errWithKind("打开相册失败,再试一次", "CHOOSE_FAILED"), null);
      }
    }
  });
}

function runBatch(sid, batch) {
  fetchPolicy(sid, function (err, pol) {
    if (err) {
      batch.forEach(function (item) {
        item.status = "error";
        item.error = err.message;
        // 拉不到 policy 是通道问题不是照片问题，留着重传。
        saveForRetry(item, item.tempFilePath);
      });
      return;
    }
    var polBox = { value: pol };
    processNext(0);
    function processNext(i) {
      if (i >= batch.length) {
        if (batch.some(function (item) { return item.status === "localizing"; })) {
          ensurePolling(sid);
        }
        return;
      }
      uploadOne(sid, polBox, batch[i], function () { processNext(i + 1); });
    }
  });
}

function getMyUploads(sid) {
  return myUploads.filter(function (p) { return p.sid === sid; });
}

module.exports = {
  MAX_COUNT: MAX_COUNT,
  startUpload: startUpload,
  getMyUploads: getMyUploads,
  statusLabel: statusLabel,
  // 批次K新增
  refreshFromServer: refreshFromServer,
  retryFailed: retryFailed,
  retryQueue: retryQueue,
  isSettled: isSettled,
  STORE_KEY: STORE_KEY,
  // 下面几个纯函数导出给验收脚本复用/对照，不是页面代码的依赖路径
  buildKey: buildKey,
  encNick: encNick,
  extractPolicy: extractPolicy,
  applySnapshot: applySnapshot,
  _all: function () { return myUploads; }
};
