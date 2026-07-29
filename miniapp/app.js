// UNSEEN 空间记忆小程序 · 只读看展壳
// 三页共用的全局态：拉到的 space.json 缓存一次、状态栏高度算一次，
// 避免每页各拉一次数据、各算一次安全区（导航栏是 custom，没有原生条兜底）。
App({
  globalData: {
    space: null, // util.ensureSpace() 写入，结构见 app/contract.md 云版 space.json
    statusBarHeight: 20
  },

  onLaunch: function () {
    var info = null;
    try {
      info = wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync();
    } catch (e) {
      info = null;
    }
    this.globalData.statusBarHeight = (info && info.statusBarHeight) || 20;
  }
});
