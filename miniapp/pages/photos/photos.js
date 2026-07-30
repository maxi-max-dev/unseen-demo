// 03 · 照片方位屏。
// 卡片正文没有照抄设计稿里那种"钢琴旁的一小段安静"式文案——那是美术demo图里的
// 摆拍文案，云版 space.json 的 photos[] 根本没有这个字段（见 app/contract.md），
// 编一句诗意文案出来就是编数据。改成接 tasks[].brief（这张补的是哪个任务、
// 任务简报怎么写的），没有对应任务就诚实标"宾客自由上传"，全部是契约里真实
// 存在的字段。
var util = require("../../utils/util.js");
// 批次J新增:上传模块，只用来读"这次会话我传的照片"这份本地记录，不发起新上传。
var upload = require("../../utils/upload.js");

function pad2(n) {
  n = String(n);
  return n.length < 2 ? "0" + n : n;
}

function arrowFor(yaw) {
  var arrows = ["↑", "↗", "→", "↘", "↓", "↙", "←", "↖"];
  var y = ((Number(yaw) || 0) % 360 + 360) % 360;
  return arrows[Math.round(y / 45) % 8];
}

Page({
  data: {
    statusBarHeight: 20,
    // 批次I:导航条几何不再写死，读 app.globalData.nav(算法见 app.js 顶部注释，
    // 跟 pano 页同一套)。
    navBarTop: 20,
    navBarHeight: 44,
    navSideMargin: 12,
    spaceTitle: "",
    spaceCouple: "",
    photos: [],
    contributorCount: 0,
    loading: true,
    loadError: false,
    // 批次J新增:sid 贯穿三页 + 本次会话"我传的"记录。
    sid: "s4",
    myUploads: [],
    retryCount: 0
  },

  onLoad: function (options) {
    var app = getApp();
    var nav = app.globalData.nav || {};
    this.setData({
      statusBarHeight: app.globalData.statusBarHeight || 20,
      navBarTop: nav.barTop != null ? nav.barTop : (app.globalData.statusBarHeight || 20),
      navBarHeight: nav.barHeight != null ? nav.barHeight : 44,
      navSideMargin: nav.sideMargin != null ? nav.sideMargin : 12
    });
    // 批次K:sid/nodeId 统一从 util.resolveSid 拿(没带会打警告)。nodeId 必须跟着，
    // 不然从二号节点点进来会看到整个空间的照片，跟全景页对不上。
    this.sid = util.resolveSid(options);
    this.nodeId = (options && options.nodeId) || null;
    this.setData({ sid: this.sid });
    this.fetchData();
  },

  onShow: function () {
    // 每次这页变可见都刷新一次"我传的"。
    // 批次K:除了读本地记录，还去服务器核一次。回执现在存在 wx 本地存储里，
    // 杀进程重开也在——但存的是【当时】的状态，主办方可能在这期间把待审的
    // 那张点通过了。不核对就是拿旧结论冒充新结论，跟"一律显示排队中"是同一种谎。
    var self = this;
    this.refreshMyUploads();
    upload.refreshFromServer(this.sid, function (changed) {
      if (changed) self.refreshMyUploads();
    });
    if (this._mineTimer) clearInterval(this._mineTimer);
    this._mineTimer = setInterval(function () { self.refreshMyUploads(); }, 3000);
  },

  onHide: function () {
    if (this._mineTimer) { clearInterval(this._mineTimer); this._mineTimer = null; }
  },

  onUnload: function () {
    if (this._mineTimer) { clearInterval(this._mineTimer); this._mineTimer = null; }
  },

  // "我传的"区——当前 sid 下传过的照片，标状态。
  // 批次K:不再只有"本次会话"。记录落 wx 本地存储，杀进程重开还在；状态文案
  // 走 upload.statusLabel()，待审/被拒/隔离/名额满各说各的(口径同源自 web/join.html)，
  // 不再一律"排队中"。
  refreshMyUploads: function () {
    var mine = upload.getMyUploads(this.sid).map(function (item) {
      return {
        key: item.key,
        thumb: item.thumb,
        statusText: upload.statusLabel(item),
        note: item.note || "",
        // 传失败又留着持久副本的，才是真能重传的那些
        canRetry: item.status === "error" && !!item.retryFilePath
      };
    });
    this.setData({
      myUploads: mine,
      retryCount: upload.retryQueue(this.sid).length
    });
  },

  // 批次K:待重传队列。压缩后的文件在失败时被 saveFile 存成了持久路径，
  // 所以这颗按钮杀进程重开之后照样能按。
  onRetryUploads: function () {
    var self = this;
    wx.showToast({ title: "正在重传…", icon: "none" });
    upload.retryFailed(this.sid, function (n, err) {
      self.refreshMyUploads();
      if (err) {
        wx.showToast({ title: err.message || "重传没成功", icon: "none" });
      } else if (!n) {
        wx.showToast({ title: "没有可重传的照片", icon: "none" });
      }
    });
  },

  onRetry: function () {
    getApp().globalData.space = null;
    this.fetchData();
  },

  fetchData: function () {
    var self = this;
    self.setData({ loading: true, loadError: false });
    util.ensureSpace(this.sid, function (err, space) {
      if (err || !space) {
        self.setData({ loading: false, loadError: true });
        return;
      }

      var taskMap = {};
      (space.tasks || []).forEach(function (t) {
        taskMap[t.id] = t;
      });

      // 批次K:按 nodeId 过滤，跟全景页看的是同一批照片(P0-3)。
      var photos = util.photosOfNode(space, self.nodeId)
        .slice()
        .sort(function (a, b) {
          return (Number(a.yaw) || 0) - (Number(b.yaw) || 0);
        })
        .map(function (p, i) {
          var yawNum = typeof p.yaw === "number" ? p.yaw : parseFloat(p.yaw);
          var hasYaw = isFinite(yawNum);
          var task = p.taskId ? taskMap[p.taskId] : null;
          var line = task
            ? (task.brief || task.title || "补拍的一张")
            : "宾客自由上传，不对应任务";
          return {
            id: p.id,
            src: p.src,
            thumb: p.thumb,
            yaw: hasYaw ? yawNum : null,
            indexLabel: pad2(i + 1),
            arrow: hasYaw ? arrowFor(yawNum) : "?",
            dirLabel: hasYaw ? util.dirWord(yawNum) + " " + Math.round(yawNum) + "°" : "方向待定",
            line: line,
            contributor: p.contributor || "匿名宾客"
          };
        });

      self.setData({
        spaceTitle: space.title || "这段记忆",
        spaceCouple: space.couple || "",
        photos: photos,
        contributorCount: (space.contributors || []).length,
        loading: false,
        loadError: false
      });
    });
  },

  onTapCard: function (e) {
    var yaw = e.currentTarget.dataset.yaw;
    // 批次J修:带上 sid，不然从体验空间的照片方位屏点回全景屏会静默掉回 s4。
    // 批次K:sid 和 nodeId 一起带回去，回到的是同一个节点的同一个方向。
    var extra = { nodeId: this.nodeId };
    if (yaw !== "" && yaw !== undefined && yaw !== null && !isNaN(yaw)) extra.yaw = yaw;
    wx.navigateTo({ url: util.pageUrl("pano", this.sid, extra) });
  },

  onBack: function () {
    if (getCurrentPages().length > 1) {
      wx.navigateBack();
    } else {
      wx.reLaunch({ url: "/pages/index/index" });
    }
  }
});
