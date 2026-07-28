// 压测军团 · 变体矩阵定义。纯数据,不含任何执行逻辑(执行逻辑在 flows.mjs)。
// 覆盖面按任务书:
//   组 J(join 完整动线):宽度4 × { 首访×(填名/跳名)×(直接交/任务卡) , 回访×(直接交/任务卡) } = 4×6 = 24
//   组 S(show 五视图+live=1):宽度4 × 6 种视图 = 24
//   组 R(粗暴操作):16 个具名场景
//   组 P(portal/pov 补充烟测,超出任务书最低要求的额外覆盖):8

export const WIDTHS = [320, 390, 430, 768];
export const HEIGHT_OF = { 320: 690, 390: 844, 430: 932, 768: 1024 };

export const JOIN_COMBOS = [
  // visit, namemode(仅 first 有意义), uploadpath
  ["first", "fill", "free"],
  ["first", "fill", "task"],
  ["first", "skip", "free"],
  ["first", "skip", "task"],
  ["return", "na", "free"],
  ["return", "na", "task"]
];

export function buildJoinMatrix() {
  const out = [];
  let n = 0;
  for (const w of WIDTHS) {
    for (const [visit, namemode, uploadpath] of JOIN_COMBOS) {
      n++;
      out.push({
        seq: n, group: "J", width: w, height: HEIGHT_OF[w],
        visit, namemode, uploadpath,
        id: `J${String(n).padStart(2, "0")}-w${w}-${visit}-${namemode}-${uploadpath}`
      });
    }
  }
  return out;
}

export const SHOW_VIEWS = ["exhibition", "journey", "timeline", "album", "machine", "live1"];

export function buildShowMatrix() {
  const out = [];
  let n = 0;
  for (const w of WIDTHS) {
    for (const view of SHOW_VIEWS) {
      n++;
      out.push({
        seq: n, group: "S", width: w, height: HEIGHT_OF[w], view,
        id: `S${String(n).padStart(2, "0")}-w${w}-${view}`
      });
    }
  }
  return out;
}

// 组 R:粗暴操作,每条都是任务书点名的场景,按宽度敏感度分配 1-3 个宽度
export const ROUGH_SPECS = [
  { name: "same-button-3x", widths: [390, 768], desc: "同一按钮(传上去)连点/连按 3 次" },
  { name: "refresh-mid-flow", widths: [390, 320], desc: "动线中途(选图后未传)刷新页面再继续" },
  { name: "browser-back", widths: [390, 768], desc: "浏览器后退(portal→join 后退)" },
  { name: "long-nickname-emoji", widths: [320, 390, 768], desc: "超长昵称 30 字 emoji 混排(回访 localStorage 直灌,真实向量)" },
  { name: "zero-photo-upload", widths: [390], desc: "选 0 张照片点「传上去」" },
  { name: "rapid-view-switch-10x", widths: [390, 768], desc: "show.html 快速连续切视图 10 次(真实整页跳转竞态)" },
  { name: "reopen-name-editor", widths: [390], desc: "回访点头部「你好」pill 重新编辑昵称" },
  { name: "rapid-tab-switch-10x", widths: [390], desc: "join.html 任务墙/我的贡献 连续切 10 次" },
  { name: "reopen-sheet-different-task", widths: [390], desc: "打开抽屉→取消→换一个任务卡再开" },
  { name: "double-cancel-cycle", widths: [320], desc: "打开抽屉→取消,连续 4 轮" }
];

export function buildRoughMatrix() {
  const out = [];
  let n = 0;
  for (const spec of ROUGH_SPECS) {
    for (const w of spec.widths) {
      n++;
      out.push({
        seq: n, group: "R", name: spec.name, desc: spec.desc,
        width: w, height: HEIGHT_OF[w],
        id: `R${String(n).padStart(2, "0")}-${spec.name}-w${w}`
      });
    }
  }
  return out;
}

// 组 P:portal.html / pov.html 补充烟测(任务书矩阵未强制要求,属额外覆盖,
// 因为两页也在白名单内、也属于"现状"里写的宾客动线首尾两段)
export function buildSmokeMatrix() {
  const out = [];
  let n = 0;
  for (const page of ["portal", "pov"]) {
    for (const w of WIDTHS) {
      n++;
      out.push({
        seq: n, group: "P", page, width: w, height: HEIGHT_OF[w],
        id: `P${String(n).padStart(2, "0")}-${page}-w${w}`
      });
    }
  }
  return out;
}

export function totalCount() {
  return buildJoinMatrix().length + buildShowMatrix().length + buildRoughMatrix().length + buildSmokeMatrix().length;
}
