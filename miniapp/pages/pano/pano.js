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

// 本地测试贴图：任务1把 s4 真实节点(n1/宴会厅)的云端全景降到 2048 后存在这里。
// 云端原图是 4096，已知在真机上加载失败率接近 100%，明知故犯是任务书里点名的
// 失败条件，绝不接：
// var PANO_SRC = "https://psm-advx-2026.oss-cn-hangzhou.aliyuncs.com/spaces/s4/nodes/n1/pano.jpg";
var PANO_SRC = "/assets/panos/s4-n1.jpg";

var FOV_DEG = 78;
var DRAG_YAW_SENSITIVITY = 0.28; // 手感如果反了，把 onTouchMove 里这个系数前的减号换成加号即可
var DRAG_PITCH_SENSITIVITY = 0.22;
var PITCH_CLAMP_DEG = 72;

function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

// 契约 yaw <-> 相机内部 yaw 的换算，自反函数，两个方向都调它。
function dataYawToCameraYawDeg(yawDeg) {
  var d = 180 - (Number(yawDeg) || 0);
  return ((d % 360) + 360) % 360;
}

Page({
  data: {
    statusBarHeight: 20,
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
    loadError: false
  },

  onLoad: function (query) {
    var app = getApp();
    this.setData({ statusBarHeight: app.globalData.statusBarHeight || 20 });

    this.cameraYawDeg = dataYawToCameraYawDeg(0); // 默认看向契约 yaw=0 的方向
    this.cameraPitchDeg = 0;
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
  },

  loadSpace: function () {
    var self = this;
    var focusYaw = this._focusYaw;
    util.ensureSpace(function (err, space) {
      if (err || !space) {
        self.setData({ loadError: true });
        return;
      }
      var node = (space.nodes && space.nodes[0]) || null;
      var photos = (space.photos || []).slice().sort(function (a, b) {
        return (Number(a.yaw) || 0) - (Number(b.yaw) || 0);
      });

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
        photos: photos,
        photoCount: photos.length,
        activeIndex: activeIndex
      });
      self.updateCurrentDirLabel();
    });
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

    if (!canvasNode.createImage) {
      console.error("[pano] canvas.createImage 不可用");
      self.setData({ loadError: true });
      return;
    }
    var img = canvasNode.createImage();
    img.onload = function () {
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, img);
    };
    img.onerror = function (e) {
      console.error("[pano] 全景贴图加载失败", e);
      self.setData({ loadError: true });
    };
    img.src = PANO_SRC;
  },

  startRenderLoop: function () {
    var self = this;
    function frame() {
      self.render();
      self.rafId = self.canvasNode.requestAnimationFrame(frame);
    }
    this.rafId = this.canvasNode.requestAnimationFrame(frame);
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
    this.cameraYawDeg = ((this.cameraYawDeg - dx * DRAG_YAW_SENSITIVITY) % 360 + 360) % 360;
    this.cameraPitchDeg = clamp(
      this.cameraPitchDeg - dy * DRAG_PITCH_SENSITIVITY,
      -PITCH_CLAMP_DEG,
      PITCH_CLAMP_DEG
    );
    this.updateCurrentDirLabel();
  },

  onTouchEnd: function () {
    this.touch = null;
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

  // 陀螺仪只在真机上有意义，模拟器/不支持的设备只要求"降级不崩"。
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
        self.gyroHandler = function (res) {
          if (!res || typeof res.alpha !== "number") return;
          // alpha/beta 在不同机型/模拟器上口径不完全统一，这里只做"能转、不崩"
          // 的降级体验，不是精密的姿态解算；真机手感需要 Max 实测后再调系数。
          self.cameraYawDeg = ((res.alpha % 360) + 360) % 360;
          self.cameraPitchDeg = clamp((res.beta || 0) - 90, -PITCH_CLAMP_DEG, PITCH_CLAMP_DEG);
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
  },

  onBack: function () {
    if (getCurrentPages().length > 1) {
      wx.navigateBack();
    } else {
      wx.reLaunch({ url: "/pages/index/index" });
    }
  },

  goPhotos: function () {
    wx.navigateTo({ url: "/pages/photos/photos" });
  }
});
