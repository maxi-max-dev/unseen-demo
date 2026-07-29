// UNSEEN 空间记忆小程序 · 只读看展壳
// 三页共用的全局态：拉到的 space.json 缓存一次、状态栏高度算一次，
// 避免每页各拉一次数据、各算一次安全区（导航栏是 custom，没有原生条兜底）。
//
// 批次I新增：nav 结构统一算胶囊按钮几何（wx.getMenuButtonBoundingClientRect），
// 不再让每个页面各自写死"statusBarHeight + 猜的一个px"当导航条高度/返回钮位置——
// 真机上胶囊按钮的位置、高度、右边距因机型而异（尤其安卓分布很散），写死的数字
// 只在开发时测试的那一台机型上"看起来对"，换一台真机就可能顶到胶囊、或者留白
// 不对（领导反馈1/2两条问题都是这一类"模拟器里对、真机上不对"的机型差异）。
//
// 公式是官方文档 wx.getMenuButtonBoundingClientRect() 的标准用法（本机实测验证过，
// 见 PROGRESS.md 批次I）：
//   gap        = 胶囊顶部 - 状态栏高度（状态栏底部到胶囊顶部的呼吸间距）
//   barTop     = 状态栏高度（导航内容行紧贴状态栏底部起）
//   barHeight  = gap*2 + 胶囊高度（内容行总高度，令行的垂直中心正好等于胶囊中心：
//                验证：barTop + barHeight/2 = 状态栏高度+gap+胶囊高度/2
//                     = 胶囊顶部 + 胶囊高度/2 = 胶囊中心 ✓）
//   sideMargin = 屏幕宽 - 胶囊右边缘（胶囊自己贴右边的间距；返回钮/导航条左边距
//                抄这个数字，让"胶囊贴右"和"内容贴左"用同一份呼吸感）
//   keepoutRight = 屏幕宽 - 胶囊左边缘（胶囊整个宽度的"禁入区"，从屏幕右边算起；
//                进入屏 app-bar 右侧文字用这个数字当右内边距，不然文字会伸进胶囊
//                底下——本批次实测（批次I baseline量出来）当前写死的 32rpx 在
//                iPhone12/13Pro 这台模拟器机型上已经量出真的会跟胶囊重叠）
App({
  globalData: {
    space: null, // util.ensureSpace() 写入，结构见 app/contract.md 云版 space.json
    statusBarHeight: 20,
    nav: fallbackNav(20)
  },

  onLaunch: function () {
    var info = null;
    try {
      info = wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync();
    } catch (e) {
      info = null;
    }
    var statusBarHeight = (info && info.statusBarHeight) || 20;
    this.globalData.statusBarHeight = statusBarHeight;
    this.globalData.nav = computeNav(statusBarHeight, info);
  }
});

// 胶囊按钮几何算不出来时（极老基础库/非微信宿主环境）的兜底值，跟这个功能出现
// 之前的硬编码数量级一致，不会比"没有这个功能"更差，只是不如算出来的准。
function fallbackNav(statusBarHeight) {
  return {
    statusBarHeight: statusBarHeight,
    barTop: statusBarHeight,
    barHeight: 44,
    sideMargin: 12,
    keepoutRight: 100
  };
}

function computeNav(statusBarHeight, windowInfo) {
  if (!wx.getMenuButtonBoundingClientRect) return fallbackNav(statusBarHeight);
  var menu = null;
  try {
    menu = wx.getMenuButtonBoundingClientRect();
  } catch (e) {
    menu = null;
  }
  if (!menu || !menu.height) return fallbackNav(statusBarHeight);
  var gap = menu.top - statusBarHeight;
  if (gap < 0) gap = 0;
  var windowWidth = (windowInfo && windowInfo.windowWidth) || menu.right + gap;
  var sideMargin = windowWidth - menu.right;
  if (sideMargin < 0) sideMargin = 0;
  // +2px 安全缓冲:批次I验收量出来严丝合缝贴到禁入区边界(0.19px的字形/取整
  // 误差)会被矩形重叠判断误判成"贴上了"，加一点余量让"不重叠"这件事不依赖
  // 亚像素取整走向，两个方向都稳。
  var keepoutRight = windowWidth - menu.left + 2;
  if (keepoutRight < 0) keepoutRight = 0;
  return {
    statusBarHeight: statusBarHeight,
    barTop: statusBarHeight,
    barHeight: gap * 2 + menu.height,
    sideMargin: sideMargin,
    keepoutRight: keepoutRight
  };
}
