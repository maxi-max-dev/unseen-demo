// 01 · 进入屏。数据全部来自 space.json 真数据（util.ensureSpace），
// 拉不到就是 loadError=true 的诚实空态，不拿设计稿里的假数字兜底。
var util = require("../../utils/util.js");

Page({
  data: {
    statusBarHeight: 20,
    // 批次I:导航条几何不再写死。这页没有返回钮，只用 barTop(顶部起点)对齐
    // 胶囊、keepoutRight(胶囊左边缘算起的禁入区)防止右上角"空间记忆"文字
    // 伸进胶囊底下——批次I baseline 实测过，写死32rpx在当前模拟器机型上
    // 已经量出会跟胶囊重叠，算法见 app.js 顶部注释。
    navBarTop: 20,
    navBarHeight: 44,
    navKeepoutRight: 100,
    loading: true,
    loadError: false,
    space: null,
    photoCount: 0,
    contributorCount: 0,
    // 批次K:「选个空间看看」预设区。清单在 utils/util.js 的 PRESET_SPACES，
    // 加空间只改那一处，不用动页面。
    presets: []
  },

  onLoad: function () {
    var app = getApp();
    var nav = app.globalData.nav || {};
    this.setData({
      statusBarHeight: app.globalData.statusBarHeight || 20,
      navBarTop: nav.barTop != null ? nav.barTop : (app.globalData.statusBarHeight || 20),
      navBarHeight: nav.barHeight != null ? nav.barHeight : 44,
      navKeepoutRight: nav.keepoutRight != null ? nav.keepoutRight : 100,
      presets: util.PRESET_SPACES
    });
    this.fetchSpace();
  },

  fetchSpace: function () {
    var self = this;
    self.setData({ loading: true, loadError: false });
    util.ensureSpace(function (err, space) {
      if (err || !space) {
        self.setData({ loading: false, loadError: true });
        return;
      }
      self.setData({
        loading: false,
        loadError: false,
        space: {
          title: space.title || "这段记忆",
          couple: space.couple || "",
          date: space.date || ""
        },
        photoCount: (space.photos || []).length,
        contributorCount: (space.contributors || []).length
      });
    });
  },

  onRetry: function () {
    // 强制重拉，不复用上次失败前缓存里可能存在的半吊子数据
    getApp().globalData.space = null;
    this.fetchSpace();
  },

  // 批次K:这一跳以前【不带 sid】，pano 页只能"兜底"回 s4——不管你从哪进来，
  // 看到的都是 s4。sid 从此由 util.pageUrl() 统一挂上，三页之间不会再丢。
  onEnter: function () {
    wx.navigateTo({ url: util.pageUrl("pano", util.DEFAULT_SPACE_ID) });
  },

  // 批次K:「选个空间看看」里的卡片。sid 从 data-sid 来，同一个处理器管所有预设，
  // 加一个空间不用再加一个方法。
  onEnterPreset: function (e) {
    var sid = e.currentTarget.dataset.sid;
    if (!sid) return;
    wx.navigateTo({ url: util.pageUrl("pano", sid) });
  },

  onCopyUploadLink: function () {
    wx.setClipboardData({
      data: util.UPLOAD_H5_URL,
      success: function () {
        wx.showToast({ title: "上传链接已复制，去浏览器里打开", icon: "none" });
      },
      fail: function () {
        wx.showToast({ title: "复制失败，再试一次", icon: "none" });
      }
    });
  }
});
