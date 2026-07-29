// 01 · 进入屏。数据全部来自 space.json 真数据（util.ensureSpace），
// 拉不到就是 loadError=true 的诚实空态，不拿设计稿里的假数字兜底。
var util = require("../../utils/util.js");

Page({
  data: {
    statusBarHeight: 20,
    loading: true,
    loadError: false,
    space: null,
    photoCount: 0,
    contributorCount: 0
  },

  onLoad: function () {
    var app = getApp();
    this.setData({ statusBarHeight: app.globalData.statusBarHeight || 20 });
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

  onEnter: function () {
    wx.navigateTo({ url: "/pages/pano/pano" });
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
