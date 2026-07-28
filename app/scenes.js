/* UNSEEN 场景注册表 · app 壳所有页面共用的数据契约
   场景三种来源:
   1. builtin  —— s4 婚礼云端空间(真数据,OSS+本地后端都认识它)
   2. local    —— 用户在 create.html 新建的场景,存 localStorage(键 unseen.scenes)
   3. backend  —— 本机后端在跑时,list API 里除 s4 外的真空间(创建成功即归入这类)
   页面根据 kind 决定哪些能力可用,不可用的给诚实空态,不装死也不撒谎 */
(function () {
  "use strict";
  var LS_KEY = "unseen.scenes";
  var API = "http://127.0.0.1:8777";

  // 相对路径前缀:app/ 下的页面取 "../",根目录取 ""
  var PREFIX = /\/app\//.test(location.pathname) ? "../" : "";
  var LOCAL_ORIGIN = /^(127\.0\.0\.1|localhost|\[::1\])$/.test(location.hostname);

  var BUILTIN = [{
    id: "s4",
    kind: "cloud",
    title: "婚礼 · 那一天",
    subtitle: "从接亲到宴席",
    cover: PREFIX + "assets/walkdemo/ballroom_j1.jpg",
    date: "2026-07-19",
    place: "杭州",
    stats: {},   /* 照片数一律读云端真数,不在这里写死(旧值 40 是占位素材的数,云端真值只有个位数) */
    links: {
      join:   PREFIX + "web/join.html?s=s4",
      walk:   PREFIX + "viewer/walk.html?demo=1",
      film:   PREFIX + "film/out/memory-film-web.mp4",
      show:   PREFIX + "web/show.html?s=s4",
      studio: PREFIX + "web/studio-login.html"
    }
  }];

  var TEMPLATES = [
    { t: "wedding", name: "婚礼",   cover: PREFIX + "assets/walkdemo/ballroom_j2.jpg" },
    { t: "event",   name: "活动",   cover: PREFIX + "assets/walkdemo/entrance_hall_j1.jpg" },
    { t: "journey", name: "旅程",   cover: PREFIX + "assets/walkdemo/comfy_cafe_j1.jpg" }
  ];

  // 存进 localStorage 的路径是"仓库根相对"或带 ../ 前缀的字符串,消费页各不相同,
  // 读出来时统一归一化成当前页可用的路径(http/data: 链接原样放行)
  function normPath(v) {
    if (typeof v !== "string" || !v) return v;
    if (/^(https?:|data:)/.test(v)) return v;
    // 存储层可能出现三种写法:仓库根相对(assets/x)、带 ../ 前缀(../assets/x)、根绝对(/assets/x)。
    // 全部剥成仓库根相对再按当前页补前缀,这样 FastAPI 根/Vercel 根/GitHub Pages 子路径/file:// 都能解析
    return PREFIX + v.replace(/^(\.\.\/)+/, "").replace(/^\//, "");
  }
  function normalizeScene(s) {
    if (!s) return s;
    var links = {};
    Object.keys(s.links || {}).forEach(function (k) { links[k] = normPath(s.links[k]); });
    return Object.assign({}, s, { links: links, cover: normPath(s.cover) });
  }
  function localScenes() {
    try {
      return JSON.parse(localStorage.getItem(LS_KEY) || "[]").map(normalizeScene);
    } catch (e) { return []; }
  }
  function saveLocalScene(s) {
    var all = localScenes();
    var i = all.findIndex(function (x) { return x.id === s.id; });
    if (i >= 0) all[i] = s; else all.unshift(s);
    localStorage.setItem(LS_KEY, JSON.stringify(all));
  }
  function removeLocalScene(id) {
    localStorage.setItem(LS_KEY, JSON.stringify(
      localScenes().filter(function (x) { return x.id !== id; })));
  }
  function allScenes() { return BUILTIN.concat(localScenes()); }
  function findScene(id) {
    return allScenes().find(function (x) { return x.id === id; }) || null;
  }

  // 开发期在后端留下的测试空间不该涌进用户看到的列表(Max 原话:现在全部都是 Test)。
  // 只在这一处过滤,所有消费页自动受益。判据保守:只认明确的开发占位词。
  var JUNK = /(测试|验收|勿删|勿用|阈值|临时|debug|^test\b|placeholder)/i;
  function isJunkSpace(s) {
    if (!s) return true;
    var t = String(s.title || "") + " " + String(s.couple || "");
    return JUNK.test(t);
  }

  // 本机后端探测:2 秒说话,探不到就走纯前端模式(这不是错误,是常态)
  // 每个空间打上 _junk 标记,**不删**:列表类消费者自己过滤掉,
  // 按 id 找空间的消费者(拿着直链进来的)必须还能找到它,否则直链就打不开了。
  function probeBackend(cb) {
    var done = false;
    var t = setTimeout(function () { if (!done) { done = true; cb(false); } }, 2000);
    fetch(API + "/api/spaces", { mode: "cors" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        if (done) return;
        done = true; clearTimeout(t);
        if (j && j.spaces) {
          j = Object.assign({}, j, {
            spaces: j.spaces.map(function (s) {
              return Object.assign({}, s, { _junk: isJunkSpace(s) });
            })
          });
        }
        cb(!!j, j);
      })
      .catch(function () { if (!done) { done = true; clearTimeout(t); cb(false); } });
  }

  // ── 返回动线契约 ──
  // 全 App 统一:叶子页接受 ?back=<仓库根相对路径,已 encodeURIComponent>,返回键优先用它。
  // 这样从场景页进走进空间,退出来落回场景页,而不是永远弹回首页。
  // 安全:拒绝 http:// 和 // 开头的值,防开放重定向。
  function backTarget(fallback) {
    try {
      var b = new URLSearchParams(location.search).get("back");
      if (b && !/^(https?:)?\/\//.test(b)) {
        return PREFIX + b.replace(/^(\.\.\/)+/, "").replace(/^\//, "");
      }
    } catch (e) {}
    return fallback;
  }
  // 给出站链接挂上 back。from 写仓库根相对路径(如 "app/scene.html?s=s4")。
  function withBack(href, from) {
    if (!href || !from) return href;
    if (/[?&]back=/.test(href)) return href;
    return href + (href.indexOf("?") >= 0 ? "&" : "?") + "back=" + encodeURIComponent(from);
  }
  // 当前页的仓库根相对路径,直接喂给 withBack 当 from。
  // 兼容四种部署:FastAPI 根 / Vercel 根 / GitHub Pages 子路径 / file://
  function selfPath() {
    var m = location.pathname.match(/(app|web|server|viewer)\/[^\/]*$/);
    var p = m ? m[0] : location.pathname.replace(/^.*\//, "");
    if (!p) p = "index.html";
    return p + location.search;
  }

  function toast(msg, ms) {
    var el = document.querySelector(".u-toast");
    if (!el) {
      el = document.createElement("div");
      el.className = "u-toast";
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.classList.add("show");
    clearTimeout(el._t);
    el._t = setTimeout(function () { el.classList.remove("show"); }, ms || 2400);
  }

  window.UNSEEN = {
    LS_KEY: LS_KEY, API: API, PREFIX: PREFIX,
    BUILTIN: BUILTIN, TEMPLATES: TEMPLATES,
    localScenes: localScenes, saveLocalScene: saveLocalScene,
    removeLocalScene: removeLocalScene,
    allScenes: allScenes, findScene: findScene,
    probeBackend: probeBackend, toast: toast,
    isJunkSpace: isJunkSpace,
    backTarget: backTarget, withBack: withBack, selfPath: selfPath
  };
})();
