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
    myUploads: []
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
    // 批次J新增:带 sid 就用它(从 pano 页的"N 张"按钮点进来时带的)，没带就
    // 兜底 util.DEFAULT_SPACE_ID(=s4，直接进这页的老路径不受影响)。
    this.sid = (options && options.sid) || util.DEFAULT_SPACE_ID;
    this.setData({ sid: this.sid });
    this.fetchData();
  },

  onShow: function () {
    // 批次J新增:每次这页变可见都刷新一次"我传的"(onLoad后紧跟着onShow也会
    // 走到这里，首次加载不用再单独调一次)，覆盖"在 pano 页传完照片，切回这页
    // 看结果"这条路径。轻量的本地读取(读 utils/upload.js 的内存数组)，不发
    // 网络请求。
    this.refreshMyUploads();
    var self = this;
    if (this._mineTimer) clearInterval(this._mineTimer);
    this._mineTimer = setInterval(function () { self.refreshMyUploads(); }, 3000);
  },

  onHide: function () {
    if (this._mineTimer) { clearInterval(this._mineTimer); this._mineTimer = null; }
  },

  onUnload: function () {
    if (this._mineTimer) { clearInterval(this._mineTimer); this._mineTimer = null; }
  },

  // 批次J新增:"我传的"区——本次会话在当前 sid 下传过的照片，标状态。
  refreshMyUploads: function () {
    var mine = upload.getMyUploads(this.sid).map(function (item) {
      return {
        key: item.key,
        thumb: item.thumb,
        statusText: upload.statusLabel(item)
      };
    });
    this.setData({ myUploads: mine });
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

      var photos = (space.photos || [])
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
    var url = "/pages/pano/pano?sid=" + encodeURIComponent(this.sid);
    if (yaw !== "" && yaw !== undefined && yaw !== null && !isNaN(yaw)) {
      url += "&yaw=" + encodeURIComponent(yaw);
    }
    wx.navigateTo({ url: url });
  },

  onBack: function () {
    if (getCurrentPages().length > 1) {
      wx.navigateBack();
    } else {
      wx.reLaunch({ url: "/pages/index/index" });
    }
  }
});
