// 03 · 照片方位屏。
// 卡片正文没有照抄设计稿里那种"钢琴旁的一小段安静"式文案——那是美术demo图里的
// 摆拍文案，云版 space.json 的 photos[] 根本没有这个字段（见 app/contract.md），
// 编一句诗意文案出来就是编数据。改成接 tasks[].brief（这张补的是哪个任务、
// 任务简报怎么写的），没有对应任务就诚实标"宾客自由上传"，全部是契约里真实
// 存在的字段。
var util = require("../../utils/util.js");

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
    spaceTitle: "",
    spaceCouple: "",
    photos: [],
    contributorCount: 0,
    loading: true,
    loadError: false
  },

  onLoad: function () {
    var app = getApp();
    this.setData({ statusBarHeight: app.globalData.statusBarHeight || 20 });
    this.fetchData();
  },

  onRetry: function () {
    getApp().globalData.space = null;
    this.fetchData();
  },

  fetchData: function () {
    var self = this;
    self.setData({ loading: true, loadError: false });
    util.ensureSpace(function (err, space) {
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
    var url = "/pages/pano/pano";
    if (yaw !== "" && yaw !== undefined && yaw !== null && !isNaN(yaw)) {
      url += "?yaw=" + encodeURIComponent(yaw);
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
