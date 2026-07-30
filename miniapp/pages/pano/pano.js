// 02 · 全景环视屏。
//
// 渲染方案选型（任务书要求写清楚选了哪个、为什么）：
// 没有用 threejs-miniprogram，改成手写一个全屏四边形 + 等距柱状投影 fragment
// shader（原生 <canvas type="webgl">，零 npm 依赖）。理由：
//   1. 任务的第一让步顺序是"能跑 > 视觉还原 > 功能全"。threejs-miniprogram 要
//      npm install 之后在开发者工具里手动点一次"构建 npm"才能跑，这一步是 GUI
//      操作，本环境里工具是否已登录、能不能自动化都不确定，一旦这步没做，
//      整个小程序直接白屏报"找不到模块"，对"能跑"是致命的。
//   2. 全屏四边形 + shader 只需要原生 WebGL API（gl.createShader/createProgram/
//      createTexture 这些），跟 web 端 viewer/walk.html 用的技术是同一路数，
//      在微信开发者工具里打开就能跑，不需要任何构建步骤。
//   3. 这一版只需要"贴图能拖着看"，不需要 three.js 的场景图/光照/多物体管理，
//      一个全屏 quad 够用，代码量反而比接入 three.js 更小。
//
// yaw 换算推导（写清楚，免得下一个人重新推一遍）：
// 契约里 yaw=0 定义成"全景第0列方向"（等距柱状图 u=0 处）。shader 里相机中心
// 视线方向是 (0,0,-1)，绕 Y 轴转 u_yaw 弧度后取 lon=atan2(x,-z) 反推贴图
// 经度，代入可得：中心视线对准的贴图列 u = 0.5 - u_yaw/(2π)（推导见下面
// dataYawToCameraYawDeg 的注释）。要让相机看向契约 yaw=Y 的方向，解出
// u_yaw = radians(180 - Y)。这个换算是自反的（f(f(x))=x mod 360），所以
// "相机朝向 -> 当前对应的契约 yaw"和"契约 yaw -> 该转到的相机朝向"用同一个函数。
var util = require("../../utils/util.js");
// 批次J新增:上传模块。只在"传一张照片"按钮的 tap 处理器和状态条刷新里用到，
// 不碰渲染/陀螺仪那几块。
var upload = require("../../utils/upload.js");

var VERT_SRC = [
  "attribute vec2 a_pos;",
  "void main() {",
  "  gl_Position = vec4(a_pos, 0.0, 1.0);",
  "}"
].join("\n");

var FRAG_SRC = [
  "precision mediump float;",
  "uniform sampler2D u_pano;",
  "uniform float u_yaw;",
  "uniform float u_pitch;",
  "uniform float u_aspect;",
  "uniform float u_tanHalfFov;",
  "uniform vec2 u_resolution;",
  "const float PI = 3.14159265359;",
  "void main() {",
  "  vec2 uv = (gl_FragCoord.xy / u_resolution) * 2.0 - 1.0;",
  "  vec3 rd = normalize(vec3(uv.x * u_aspect * u_tanHalfFov, uv.y * u_tanHalfFov, -1.0));",
  "  float cp = cos(u_pitch);",
  "  float sp = sin(u_pitch);",
  "  vec3 r1 = vec3(rd.x, rd.y * cp - rd.z * sp, rd.y * sp + rd.z * cp);",
  "  float cy = cos(u_yaw);",
  "  float sy = sin(u_yaw);",
  "  vec3 r2 = vec3(r1.x * cy + r1.z * sy, r1.y, -r1.x * sy + r1.z * cy);",
  "  float lon = atan(r2.x, -r2.z);",
  "  float u = lon / (2.0 * PI) + 0.5;",
  "  float lat = asin(clamp(r2.y, -1.0, 1.0));",
  "  float v = 0.5 - lat / PI;",
  "  gl_FragColor = texture2D(u_pano, vec2(u, v));",
  "}"
].join("\n");

// 批次K：这张打包进小程序的图【降级成 s4 专用的离线兜底】，不再是所有空间的
// 贴图来源。正常路径是服务端为每个节点发的 2048x1024 降档图(space.json 的
// node.panoMini，见 server/publish.py 的 _ensure_pano_mini)，按当前空间和节点取。
// 云端原图是 4096，真机加载失败率接近 100%，任何情况下都不去拉它。
// 兜底地址现在统一登记在 utils/util.js 的 OFFLINE_PANO 表里，这里不再写常量。

var FOV_DEG = 78;
// 批次I调参:原值0.28在本机模拟器(390px宽)算出来拖一屏只转102°，任务要求~120°。
// 120/390≈0.3077，取0.31——在常见机型宽度375~414px上都落在116°~128°，是"约120°"
// 的合理范围(算式和验证见 PROGRESS.md 批次I)。手感如果反了，把 onTouchMove 里
// 这个系数前的减号换成加号即可。
var DRAG_YAW_SENSITIVITY = 0.31;
var DRAG_PITCH_SENSITIVITY = 0.22;
// 批次I:72→85，陀螺仪/拖动共用同一个夹角上限(任务书对陀螺仪明确要求±85°，
// "pitch同样夹角"要求拖动一致，85°比72°更贴近抬头看/低头看的真实极限但仍留
// 一点余量不会翻到镜头背面)。
var PITCH_CLAMP_DEG = 85;
// 批次I新增:松手惯性摩擦系数，每帧(rAF,约60fps)衰减到92%，约1~1.5秒内自然停下。
var DRAG_FRICTION = 0.92;
// 惯性速度低于这个阈值(度/帧)就直接清零停止，不然会有跑不完的极小数值计算。
var INERTIA_EPS = 0.008;
// 惯性初速度上限(度/帧)。touchmove 事件不是等间隔触发的(真机偶尔卡顿/触摸
// 采样率不稳时，两次事件之间可能隔了不止一帧)，如果直接拿"这次事件的位移"
// 当"每帧速度"用，事件间隔一旦变长，换算出来的单帧速度会失真地大，松手后
// 感觉像"猛地弹飞"。用 REF_FRAME_MS 把速度归一化到"每约16.67ms(60fps一帧)"
// 的量级，再用这个上限兜底，双保险防止任何异常输入(含本批次验收脚本用
// automator 模拟的大位移单次touchmove)造成失控的甩动。
var MAX_INERTIA_STEP = 6;
var REF_FRAME_MS = 16.67;
// 陀螺仪低通滤波系数，任务书建议值。
var GYRO_LOWPASS = 0.15;

function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

// 环形角度最短路径差值，结果落在(-180,180]。陀螺仪 alpha 是 0~360 循环量，
// 直接相减在 359→0 这种边界会得到 -359 这种错误的"绕了一大圈"的差值，
// 必须走这条最短路径换算，滤波和取相对量两处都要用。
function shortestDelta(from, to) {
  var d = ((to - from) % 360 + 540) % 360 - 180;
  return d;
}

// 契约 yaw <-> 相机内部 yaw 的换算，自反函数，两个方向都调它。
function dataYawToCameraYawDeg(yawDeg) {
  var d = 180 - (Number(yawDeg) || 0);
  return ((d % 360) + 360) % 360;
}

Page({
  data: {
    statusBarHeight: 20,
    // 批次I:导航条几何不再写死，读 app.globalData.nav(算法见 app.js 顶部注释)。
    // 这三个默认值只在 onLoad 的 setData 落地前的极短一瞬生效，跟原来的兜底值
    // 同一量级，不会闪烁。
    navBarTop: 20,
    navBarHeight: 44,
    navSideMargin: 12,
    spaceTitle: "",
    spaceCouple: "",
    nodeName: "",
    photos: [],
    photoCount: 0,
    activeIndex: 0,
    currentDirWord: "",
    currentYawDeg: 0,
    showHint: true,
    gyroOn: false,
    loadError: false,
    // 批次J新增:上传状态条。sid 决定这页读/传哪个空间(体验空间卡带
    // ?sid=stressexp1 进来，老的婚礼入口不带 sid，兜底 s4，行为不变)。
    sid: "s4",
    uploadBarVisible: false,
    uploadStatusText: "",
    // 批次K:贴图是不是真的上去了。加这两个字段是因为【模拟器截图拍不到 WebGL
    // 画布】——批次J 贴的是本地打包图，截出来同样是一片占位色，所以"截图看着是空的"
    // 完全没法区分"图没加载"和"截图拍不到"。把结果落进 data，验收脚本就能断言，
    // 不用再靠肉眼猜。顺带也让页面有东西可以挂加载态。
    panoReady: false,
    panoSrcInUse: ""
  },

  onLoad: function (query) {
    var app = getApp();
    var nav = app.globalData.nav || {};
    this.setData({
      statusBarHeight: app.globalData.statusBarHeight || 20,
      navBarTop: nav.barTop != null ? nav.barTop : (app.globalData.statusBarHeight || 20),
      navBarHeight: nav.barHeight != null ? nav.barHeight : 44,
      navSideMargin: nav.sideMargin != null ? nav.sideMargin : 12
    });

    this.cameraYawDeg = dataYawToCameraYawDeg(0); // 默认看向契约 yaw=0 的方向
    this.cameraPitchDeg = 0;
    // 批次I:拖动惯性状态。yaw/pitchVelocity 是"每帧衰减前"的瞬时速度(度/帧)，
    // inertiaActive 标记松手后是否还在自然减速滑行。
    this.yawVelocity = 0;
    this.pitchVelocity = 0;
    this.inertiaActive = false;
    this.gl = null;
    this.program = null;
    this.attribs = {};
    this.uniforms = {};
    this.tex = null;
    this.rafId = null;
    this.canvasNode = null;
    this.touch = null;
    this.gyroHandler = null;

    this._focusYaw = null;
    if (query && query.yaw !== undefined) {
      var fy = parseFloat(query.yaw);
      if (!isNaN(fy)) {
        this._focusYaw = fy;
        this.cameraYawDeg = dataYawToCameraYawDeg(fy);
      }
    }

    // 批次K:sid 统一走 util.resolveSid()，没带会打一句警告——线上再出现
    // "怎么又回到 s4 了"时，那句日志是唯一线索。nodeId 同样从 query 拿，
    // 多节点空间从照片页点回来时要落回原来那个节点，不能一律跳回第一个。
    this.sid = util.resolveSid(query);
    this.nodeId = (query && query.nodeId) || null;
    this.setData({ sid: this.sid });

    this.loadSpace();

    var self = this;
    this._hintTimer = setTimeout(function () {
      self.setData({ showHint: false });
    }, 3200);
  },

  onReady: function () {
    // canvas 节点查询要在首次渲染完成后才可靠，onLoad 阶段查不一定查得到。
    this.initGL();
  },

  onUnload: function () {
    if (this._hintTimer) clearTimeout(this._hintTimer);
    if (this.rafId && this.canvasNode && this.canvasNode.cancelAnimationFrame) {
      this.canvasNode.cancelAnimationFrame(this.rafId);
    }
    this.stopGyro();
    // 批次J新增:清掉上传状态条的本地刷新定时器和视角补间定时器，防止离开
    // 页面后还在后台空跑(网络轮询本身在 utils/upload.js 模块作用域里，不受
    // 页面卸载影响，会按自己的3分钟大限走完，这里只清页面自己的两个定时器)。
    if (this._uploadTicker) clearInterval(this._uploadTicker);
    if (this._camAnimTimer) clearInterval(this._camAnimTimer);
  },

  loadSpace: function () {
    var self = this;
    var focusYaw = this._focusYaw;
    util.ensureSpace(this.sid, function (err, space) {
      if (err || !space) {
        self.setData({ loadError: true });
        return;
      }
      // 批次K(P0-3 的两半):
      //   ① 节点跟着 nodeId 走，不再永远 nodes[0]——多节点空间以前全挤在第一个节点上。
      //   ② 照片按 nodeId 过滤。以前是把【整个空间】的照片放进同一条缩略带，
      //      于是二号节点的照片会挂在一号节点的全景上，方向全是错的。
      var node = util.pickNode(space, self.nodeId);
      self.nodeId = node ? node.id : null;
      var photos = util.photosOfNode(space, self.nodeId).slice().sort(function (a, b) {
        return (Number(a.yaw) || 0) - (Number(b.yaw) || 0);
      });
      // ③ 全景贴图跟着当前空间+节点走，不再写死打包进来的那张 s4 背景。
      self.applyPanoSource(util.panoSourceFor(self.sid, node));

      var activeIndex = 0;
      if (focusYaw !== null && photos.length) {
        var best = 0;
        var bestDiff = Infinity;
        photos.forEach(function (p, i) {
          var diff = Math.abs((Number(p.yaw) || 0) - focusYaw);
          if (diff < bestDiff) { bestDiff = diff; best = i; }
        });
        activeIndex = best;
      }

      self.setData({
        spaceTitle: space.title || "这段记忆",
        spaceCouple: space.couple || "",
        nodeName: node ? node.name : "",
        nodeCount: (space.nodes || []).length,
        photos: photos,
        photoCount: photos.length,
        activeIndex: activeIndex
      });
      self.updateCurrentDirLabel();
    });
  },

  // 批次K:全景贴图的来源。空间数据回来才知道该贴哪张图，而 GL 是 onReady 就
  // 初始化好的——两边谁先到都有可能，所以两头都调这个函数，它自己判断另一半
  // 就绪没有。src 没变就不重贴(换节点/重进页面时避免白白重下一张 500KB 的图)。
  applyPanoSource: function (source) {
    var src = source && source.src;
    if (!src) {
      // 这个空间既没有降档全景，也没有可用的离线兜底。诚实报错，绝不拿
      // 别的空间的背景冒充——"其他空间的照片方向 + s4 的背景"正是 P0-3。
      console.error("[pano] 空间 " + this.sid + " 没有可用的全景(缺 panoMini)");
      this.setData({ loadError: true });
      return;
    }
    if (this._panoSrc === src) return;
    this._panoSrc = src;
    this._panoIsOffline = !!source.offline;
    this.setData({ panoReady: false, panoSrcInUse: src });
    if (this.gl && this.canvasNode) this.bindPanoTexture();
  },

  bindPanoTexture: function () {
    var self = this;
    var gl = this.gl;
    if (!gl || !this.tex || !this.canvasNode || !this._panoSrc) return;
    if (!this.canvasNode.createImage) {
      console.error("[pano] canvas.createImage 不可用");
      this.setData({ loadError: true });
      return;
    }
    var wanted = this._panoSrc;
    var img = this.canvasNode.createImage();
    img.onload = function () {
      // 慢请求回来时可能已经换到别的节点了，过期的那张不许覆盖当前贴图。
      if (self._panoSrc !== wanted) return;
      gl.bindTexture(gl.TEXTURE_2D, self.tex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, img);
      self.setData({ loadError: false, panoReady: true, panoSrcInUse: wanted });
    };
    img.onerror = function (e) {
      console.error("[pano] 全景贴图加载失败", wanted, e);
      // 云图拉不动时，只有【这个空间自己】有离线兜底才退回去。别的空间宁可空着。
      var fallback = util.panoSourceFor(self.sid, null);
      if (!self._panoIsOffline && fallback.src) {
        console.warn("[pano] 退回离线兜底:" + fallback.src);
        self._panoSrc = fallback.src;
        self._panoIsOffline = true;
        self.setData({ panoSrcInUse: fallback.src });
        self.bindPanoTexture();
        return;
      }
      self.setData({ loadError: true, panoReady: false });
    };
    img.src = wanted;
  },

  updateCurrentDirLabel: function () {
    // dataYawToCameraYawDeg 是自反的，相机->契约 yaw 用同一个函数换算回去。
    var yaw = dataYawToCameraYawDeg(this.cameraYawDeg || 0);
    this.setData({
      currentYawDeg: Math.round(yaw),
      currentDirWord: util.dirWord(yaw)
    });
  },

  initGL: function () {
    var self = this;
    wx.createSelectorQuery()
      .select("#glcanvas")
      .fields({ node: true, size: true })
      .exec(function (res) {
        if (!res || !res[0] || !res[0].node) {
          self.setData({ loadError: true });
          return;
        }
        var canvas = res[0].node;
        var gl = canvas.getContext("webgl");
        if (!gl) {
          self.setData({ loadError: true });
          return;
        }
        var w = Math.max(1, Math.round(res[0].width || 300));
        var h = Math.max(1, Math.round(res[0].height || 300));
        canvas.width = w;
        canvas.height = h;
        gl.viewport(0, 0, w, h);

        self.gl = gl;
        self.canvasNode = canvas;
        self.aspect = w / h;
        self.canvasW = w;
        self.canvasH = h;

        if (!self.buildProgram()) return;
        self.buildQuad();
        self.loadTexture(canvas);
        self.startRenderLoop();
      });
  },

  buildProgram: function () {
    var gl = this.gl;
    function compile(type, src) {
      var s = gl.createShader(type);
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
        console.error("[pano] shader compile error", gl.getShaderInfoLog(s));
        return null;
      }
      return s;
    }
    var vs = compile(gl.VERTEX_SHADER, VERT_SRC);
    var fs = compile(gl.FRAGMENT_SHADER, FRAG_SRC);
    if (!vs || !fs) {
      this.setData({ loadError: true });
      return false;
    }
    var program = gl.createProgram();
    gl.attachShader(program, vs);
    gl.attachShader(program, fs);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      console.error("[pano] program link error", gl.getProgramInfoLog(program));
      this.setData({ loadError: true });
      return false;
    }
    gl.useProgram(program);
    this.program = program;
    this.attribs = { a_pos: gl.getAttribLocation(program, "a_pos") };
    this.uniforms = {
      u_pano: gl.getUniformLocation(program, "u_pano"),
      u_yaw: gl.getUniformLocation(program, "u_yaw"),
      u_pitch: gl.getUniformLocation(program, "u_pitch"),
      u_aspect: gl.getUniformLocation(program, "u_aspect"),
      u_tanHalfFov: gl.getUniformLocation(program, "u_tanHalfFov"),
      u_resolution: gl.getUniformLocation(program, "u_resolution")
    };
    return true;
  },

  buildQuad: function () {
    var gl = this.gl;
    var buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]),
      gl.STATIC_DRAW
    );
    this.quadBuf = buf;
  },

  loadTexture: function (canvasNode) {
    var self = this;
    var gl = this.gl;
    var tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    // 贴图下载完成前先塞一个纯色像素占位，不留垃圾内存花屏
    gl.texImage2D(
      gl.TEXTURE_2D, 0, gl.RGB, 1, 1, 0, gl.RGB, gl.UNSIGNED_BYTE,
      new Uint8Array([62, 36, 48])
    );
    this.tex = tex;

    // 批次K:贴图地址不再写死。GL 就绪时空间数据可能还没回来(反之亦然)，
    // 谁后到谁负责触发一次绑定，具体逻辑在 applyPanoSource/bindPanoTexture。
    if (this._panoSrc) this.bindPanoTexture();
  },

  startRenderLoop: function () {
    var self = this;
    function frame() {
      self.tickInertia();
      self.render();
      self.rafId = self.canvasNode.requestAnimationFrame(frame);
    }
    this.rafId = this.canvasNode.requestAnimationFrame(frame);
  },

  // 批次I新增:惯性衰减，每帧(rAF)调一次。松手瞬间的速度按摩擦系数逐帧衰减，
  // 衰减到阈值以下就停，不需要额外定时器，直接挂在已经在跑的渲染循环里。
  // 手指按住/陀螺仪开着时都不应该有惯性(前者手在控制，后者传感器在控制)，
  // 两个条件在 onTouchStart/onToggleGyro 里已经互斥清空，这里只需检查
  // inertiaActive 这一个标记。
  tickInertia: function () {
    if (!this.inertiaActive || this.touch) return;
    if (this.data.gyroOn) {
      this.inertiaActive = false;
      return;
    }
    this.cameraYawDeg = ((this.cameraYawDeg + this.yawVelocity) % 360 + 360) % 360;
    this.cameraPitchDeg = clamp(this.cameraPitchDeg + this.pitchVelocity, -PITCH_CLAMP_DEG, PITCH_CLAMP_DEG);
    this.yawVelocity *= DRAG_FRICTION;
    this.pitchVelocity *= DRAG_FRICTION;
    if (Math.abs(this.yawVelocity) < INERTIA_EPS && Math.abs(this.pitchVelocity) < INERTIA_EPS) {
      this.yawVelocity = 0;
      this.pitchVelocity = 0;
      this.inertiaActive = false;
    }
    this.updateCurrentDirLabel();
  },

  render: function () {
    var gl = this.gl;
    if (!gl || !this.program) return;
    gl.useProgram(this.program);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.quadBuf);
    gl.enableVertexAttribArray(this.attribs.a_pos);
    gl.vertexAttribPointer(this.attribs.a_pos, 2, gl.FLOAT, false, 0, 0);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.tex);
    gl.uniform1i(this.uniforms.u_pano, 0);
    gl.uniform1f(this.uniforms.u_yaw, ((this.cameraYawDeg || 0) * Math.PI) / 180);
    gl.uniform1f(this.uniforms.u_pitch, ((this.cameraPitchDeg || 0) * Math.PI) / 180);
    gl.uniform1f(this.uniforms.u_aspect, this.aspect || 1);
    gl.uniform1f(this.uniforms.u_tanHalfFov, Math.tan(((FOV_DEG * Math.PI) / 180) / 2));
    gl.uniform2f(this.uniforms.u_resolution, this.canvasW || 1, this.canvasH || 1);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  },

  onTouchStart: function (e) {
    var t = e.touches && e.touches[0];
    if (!t) return;
    this.touch = { x: t.clientX, y: t.clientY };
    this._lastMoveT = Date.now();
    // 新按下就是"手接管"的信号，把上一次松手留下的惯性立刻清零，不然会跟
    // 新的拖动叠加、感觉像手感失控。
    this.inertiaActive = false;
    this.yawVelocity = 0;
    this.pitchVelocity = 0;
    this.setData({ showHint: false });
    this.stopGyro(); // 手一拖就把控制权收回来，别跟陀螺仪打架
    if (this.data.gyroOn) this.setData({ gyroOn: false });
  },

  onTouchMove: function (e) {
    var t = e.touches && e.touches[0];
    if (!t || !this.touch) return;
    var dx = t.clientX - this.touch.x;
    var dy = t.clientY - this.touch.y;
    this.touch = { x: t.clientX, y: t.clientY };
    var yawStep = -dx * DRAG_YAW_SENSITIVITY;
    var pitchStep = -dy * DRAG_PITCH_SENSITIVITY;
    this.cameraYawDeg = ((this.cameraYawDeg + yawStep) % 360 + 360) % 360;
    this.cameraPitchDeg = clamp(this.cameraPitchDeg + pitchStep, -PITCH_CLAMP_DEG, PITCH_CLAMP_DEG);

    // 记录惯性滑行要用的初速度:touchmove 事件间隔不均匀，直接拿"这次位移"当
    // "每帧速度"用，事件间隔一旦变长(真机卡顿/采样率低)算出来的单帧速度会
    // 失真地大，松手后感觉像"猛地弹飞"而不是自然减速。这里按实际经过的时间
    // 把这次位移归一化到"每约16.67ms(60fps一帧)"的量级，再夹一个绝对上限
    // 兜底(见 MAX_INERTIA_STEP 注释)。
    var now = Date.now();
    var dt = now - (this._lastMoveT || now);
    this._lastMoveT = now;
    var norm = dt > 0 ? clamp(REF_FRAME_MS / dt, 0, 3) : 1;
    this.yawVelocity = clamp(yawStep * norm, -MAX_INERTIA_STEP, MAX_INERTIA_STEP);
    this.pitchVelocity = clamp(pitchStep * norm, -MAX_INERTIA_STEP, MAX_INERTIA_STEP);
    this.updateCurrentDirLabel();
  },

  onTouchEnd: function () {
    this.touch = null;
    // 松手瞬间，只要最后一帧还有明显速度就交给 tickInertia 顺势滑行一段。
    if (Math.abs(this.yawVelocity) > INERTIA_EPS || Math.abs(this.pitchVelocity) > INERTIA_EPS) {
      this.inertiaActive = true;
    }
  },

  onTapThumb: function (e) {
    var index = e.currentTarget.dataset.index;
    var photo = this.data.photos[index];
    if (!photo) return;
    this.cameraYawDeg = dataYawToCameraYawDeg(photo.yaw);
    this.cameraPitchDeg = 0;
    this.setData({ activeIndex: index });
    this.updateCurrentDirLabel();
  },

  onToggleGyro: function () {
    if (this.data.gyroOn) {
      this.stopGyro();
      this.setData({ gyroOn: false });
    } else {
      this.startGyro();
    }
  },

  // 批次I重写:陀螺仪只在真机上有意义，模拟器/不支持的设备只要求"降级不崩"。
  // 根治"一开陀螺仪画面猛跳"：旧版直接把 res.alpha 当成绝对 yaw 赋值，开启那
  // 一瞬间画面会从"手动拖到的方向"瞬间跳到"手机当前朝向"，跳变幅度可以有
  // 大半圈。新版思路是"开启瞬间的手机姿态=基准0点，此后只取相对这个基准的
  // 变化量"，叠加到"开启那一刻镜头本来看的方向"上——这样无论 alpha 的绝对值
  // 参考系是什么(iOS/Android 不完全一致，通常是磁北或设备自己的任意参考系)，
  // 开启瞬间画面保证是连续的，只有后续转动手机才会带动画面转，这个思路本身
  // 就规避了大部分"iOS/Android 坐标系差异"的绝对值问题，不需要对两个平台
  // 分别特判。
  startGyro: function () {
    var self = this;
    if (!wx.startDeviceMotionListening) {
      wx.showToast({ title: "这台设备不支持陀螺仪", icon: "none" });
      return;
    }
    wx.startDeviceMotionListening({
      interval: "game",
      success: function () {
        self.setData({ gyroOn: true });
        self._gyroBaseline = null; // 第一帧数据到达时才设基准，见下方 gyroHandler
        self._gyroFilteredAlpha = null;
        self._gyroFilteredBeta = null;
        self._gyroStartYaw = self.cameraYawDeg; // 开启这一刻镜头本来看的方向
        self._gyroStartPitch = self.cameraPitchDeg;
        self.gyroHandler = function (res) {
          if (!res || typeof res.alpha !== "number" || typeof res.beta !== "number") return;

          // 低通滤波:对原始 alpha/beta 做指数滑动平均(EMA)防抖，系数0.15=
          // 新数据占15%权重，滤掉传感器高频抖动又不会感觉迟钝。alpha是环形量
          // (0~360会在359→0处跳变)，必须先转成"相对上一次滤波值的最短路径
          // 增量"再累加，直接线性平均两个原始角度在跨越0/360边界时会得到
          // 错误结果(比如359和1平均出180，而不是0)。
          if (self._gyroFilteredAlpha === null) {
            self._gyroFilteredAlpha = res.alpha;
            self._gyroFilteredBeta = res.beta;
          } else {
            self._gyroFilteredAlpha = self._gyroFilteredAlpha + GYRO_LOWPASS * shortestDelta(self._gyroFilteredAlpha, res.alpha);
            self._gyroFilteredBeta = self._gyroFilteredBeta + GYRO_LOWPASS * (res.beta - self._gyroFilteredBeta);
          }

          if (self._gyroBaseline === null) {
            // 建立基准的这一帧不产生任何画面变化，避免开启瞬间的第一下跳动。
            self._gyroBaseline = { alpha: self._gyroFilteredAlpha, beta: self._gyroFilteredBeta };
            return;
          }

          var yawDelta = shortestDelta(self._gyroBaseline.alpha, self._gyroFilteredAlpha);
          var pitchDelta = self._gyroFilteredBeta - self._gyroBaseline.beta;
          // 转向手感如果测出来反了(部分安卓机型 alpha 增长方向与 iOS 相反)，
          // 把下面这一行的"+ yawDelta"改成"- yawDelta"即可，不用改别的地方。
          self.cameraYawDeg = ((self._gyroStartYaw + yawDelta) % 360 + 360) % 360;
          self.cameraPitchDeg = clamp(self._gyroStartPitch + pitchDelta, -PITCH_CLAMP_DEG, PITCH_CLAMP_DEG);
          self.updateCurrentDirLabel();
        };
        wx.onDeviceMotionChange(self.gyroHandler);
      },
      fail: function (err) {
        console.error("[pano] startDeviceMotionListening failed", err);
        wx.showToast({ title: "陀螺仪打不开，继续用手拖", icon: "none" });
      }
    });
  },

  stopGyro: function () {
    if (this.gyroHandler) {
      try {
        wx.offDeviceMotionChange(this.gyroHandler);
      } catch (e) {}
      this.gyroHandler = null;
    }
    if (wx.stopDeviceMotionListening) {
      try {
        wx.stopDeviceMotionListening();
      } catch (e) {}
    }
    this._gyroBaseline = null;
    this._gyroFilteredAlpha = null;
    this._gyroFilteredBeta = null;
  },

  onBack: function () {
    if (getCurrentPages().length > 1) {
      wx.navigateBack();
    } else {
      wx.reLaunch({ url: "/pages/index/index" });
    }
  },

  goPhotos: function () {
    // 批次J修:带上 sid，让 photos 页知道读哪个空间(之前没带参数，隐式兜底
    // s4；现在体验空间的照片方位屏也得看得到体验空间自己的照片)。
    // 批次K:带上 nodeId——照片页要跟这一页看的是同一个节点的同一批照片。
    wx.navigateTo({ url: util.pageUrl("photos", this.sid, { nodeId: this.nodeId }) });
  },

  // ================================================================
  // 批次J新增:上传入口。只加这几个方法，不改上面任何一个已有方法的内部逻辑
  // (陀螺仪/拖动/渲染/返回钮全部原样)。
  // ================================================================

  onUploadTap: function () {
    if (this._uploadBatchActive) return; // 上一批还没结束，不叠加新批次，简单可靠
    var self = this;
    this._uploadBatchActive = true;
    this.setData({ uploadBarVisible: true, uploadStatusText: "选照片中…" });
    upload.startUpload(this.sid, function (err, batch) {
      if (err) {
        self._uploadBatchActive = false;
        if (err.kind === "CANCELLED") {
          self.setData({ uploadBarVisible: false, uploadStatusText: "" });
        } else {
          self.setData({ uploadBarVisible: true, uploadStatusText: err.message });
        }
        return;
      }
      self._uploadBatch = batch;
      self._uploadBatchFocused = false;
      self.startUploadTicker();
    });
  },

  startUploadTicker: function () {
    var self = this;
    if (this._uploadTicker) clearInterval(this._uploadTicker);
    this._uploadTicker = setInterval(function () { self.refreshUploadStatus(); }, 800);
    this.refreshUploadStatus();
  },

  // 批次K:状态条如实转述服务器给的终态。以前只有"回到方位了"一种好结局，
  // 待审/被拒/隔离/名额满全被上一版归进"还在排队"，宾客等三分钟等到一句谎话。
  // 现在 settled 的照片直接读 upload.statusLabel()(口径同源自 web/join.html)。
  computeBatchStatusText: function (batch) {
    var total = batch.length;
    var uploading = batch.filter(function (i) { return i.status === "uploading"; }).length;
    if (uploading > 0) return "上传中 " + (total - uploading) + "/" + total;
    if (batch.some(function (i) { return i.status === "localizing"; })) return "AI 正在定位…";
    var settled = batch.filter(function (i) { return i.status === "settled"; })[0];
    if (settled) {
      // 进空间了就说得高兴点，其余终态一律用同源文案原样说，不粉饰。
      return (settled.serverState === "auto_ok" || settled.serverState === "approved")
        ? "回到方位了"
        : upload.statusLabel(settled);
    }
    if (batch.some(function (i) { return i.status === "timeout"; })) return "AI 还在排队,稍后回来看";
    var errItem = batch.filter(function (i) { return i.status === "error"; })[0];
    return errItem ? errItem.error : "";
  },

  refreshUploadStatus: function () {
    var batch = this._uploadBatch;
    if (!batch) return;
    this.setData({ uploadBarVisible: true, uploadStatusText: this.computeBatchStatusText(batch) });

    if (!this._uploadBatchFocused) {
      // 只有真的进了空间(拿得到 yaw)才转视角。待审/被拒的照片没有方位，
      // 转过去看一片空地比不转更让人困惑。
      var justDone = batch.filter(function (i) {
        return i.status === "settled" &&
          (i.serverState === "auto_ok" || i.serverState === "approved");
      })[0];
      if (justDone) {
        this._uploadBatchFocused = true;
        this.focusOnNewPhoto(justDone.yaw);
      }
    }

    var allSettled = batch.every(function (i) {
      return i.status === "settled" || i.status === "timeout" || i.status === "error";
    });
    if (allSettled) {
      clearInterval(this._uploadTicker);
      this._uploadTicker = null;
      this._uploadBatchActive = false;
      var self = this;
      setTimeout(function () {
        // 只在还是同一批时才收起状态条：这几秒内用户完全可能又点了一次
        // "传一张照片"开了新的一批，不能把新一批的文案盖掉。
        if (self._uploadBatch === batch) self.setData({ uploadBarVisible: false });
      }, 4000);
    }
  },

  // 上传成功匹配到新照片后：缩略条刷新 + 视角转过去。用的是 ensureSpace 的
  // 缓存路径(upload.js 轮询时已经用 fetchSpaceFresh 把最新数据写回缓存了，
  // 这里不会再多发一次网络请求)。
  focusOnNewPhoto: function (contractYaw) {
    var self = this;
    if (typeof contractYaw !== "number" || isNaN(contractYaw)) return;
    util.ensureSpace(this.sid, function (err, space) {
      if (err || !space) return; // 静默失败:这只是锦上添花的自动对焦，状态条已经诚实报过"回到方位了"
      var photos = (space.photos || []).slice().sort(function (a, b) {
        return (Number(a.yaw) || 0) - (Number(b.yaw) || 0);
      });
      var activeIndex = 0, bestDiff = Infinity;
      photos.forEach(function (p, i) {
        var diff = Math.abs((Number(p.yaw) || 0) - contractYaw);
        if (diff < bestDiff) { bestDiff = diff; activeIndex = i; }
      });
      self.setData({ photos: photos, photoCount: photos.length, activeIndex: activeIndex });
    });
    this.animateCameraTo(dataYawToCameraYawDeg(contractYaw), 0, 700);
  },

  // 视角补间动画。不改 tickInertia/render/startRenderLoop(批次I的陀螺仪/惯性
  // 渲染逻辑，原样不动)，只是另起一个独立的补间，写的是渲染循环本来每帧都在
  // 读的 cameraYawDeg/cameraPitchDeg 这两个字段——触发前关掉惯性标记，避免
  // 两套逻辑同时抢着改同一个字段。
  animateCameraTo: function (targetYawDeg, targetPitchDeg, durationMs) {
    this.inertiaActive = false;
    this.yawVelocity = 0;
    this.pitchVelocity = 0;
    var self = this;
    var fromYaw = this.cameraYawDeg || 0;
    var yawDelta = shortestDelta(fromYaw, targetYawDeg);
    var fromPitch = this.cameraPitchDeg || 0;
    var pitchDelta = targetPitchDeg - fromPitch;
    var start = Date.now();
    if (this._camAnimTimer) clearInterval(this._camAnimTimer);
    this._camAnimTimer = setInterval(function () {
      var t = Math.min(1, (Date.now() - start) / durationMs);
      var eased = 1 - Math.pow(1 - t, 3); // ease-out cubic，跟拖动惯性一样"减速停下"的手感
      self.cameraYawDeg = ((fromYaw + yawDelta * eased) % 360 + 360) % 360;
      self.cameraPitchDeg = fromPitch + pitchDelta * eased;
      self.updateCurrentDirLabel();
      if (t >= 1) {
        clearInterval(self._camAnimTimer);
        self._camAnimTimer = null;
      }
    }, 32);
  }
});
