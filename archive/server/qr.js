/*!
 * server/qr.js —— 自包含二维码生成器（零依赖、零外链、单文件）
 *
 * 为什么要自己写:项目铁律禁止外链任何 CDN,也不许 npm install,
 * 所以二维码只能自己按 ISO/IEC 18004 标准实现一遍(RS 纠错 + 位流 + 掩码 + 格式信息)。
 *
 * 实现范围(够用即可,刻意收窄以降低出错面):
 *   - 编码模式:只做 byte 模式(先 UTF-8 编码成字节),不做数字/字母数字/汉字模式。
 *     URL 全是 ASCII,byte 模式一样能装,只是比专用模式多占几个字节,不影响使用。
 *   - 纠错级别:固定 M(约 15% 冗余)。选 M 不选 L 的原因:婚礼现场是打印/投屏 + 手机扫,
 *     纸面反光、屏幕摩尔纹都会吃掉一部分模块,M 比 L 抗造,而容量对 URL 来说绰绰有余。
 *   - 版本:1..10 自动选择。版本 10-M 的 byte 容量是 213 字符,
 *     隧道地址 https://xxxx-xxxx-xxxx.trycloudflare.com/join?s=s1 大概 60 字符,远远够。
 *   - 掩码:8 种全试,按标准的 4 条惩罚规则算分,取分数最低的那个(不是写死 mask 0)。
 *
 * 对外接口(挂在 window.PSMQR,node 里挂 globalThis.PSMQR):
 *   PSMQR.toMatrix(text)            -> { size, version, mask, modules }  modules 是 size×size 的布尔二维数组(true=黑)
 *   PSMQR.render(canvasEl, text, opts) -> 同上的对象;把二维码画到 canvas 上
 *       opts = { size: 输出边长像素(默认 256), margin: 静区模块数(默认 4),
 *                dark: 深色(默认 '#000'), light: 浅色(默认 '#fff') }
 *
 * 自测:node server/qr_selftest.mjs
 */
(function (global) {
  'use strict';

  // ── 1. GF(256) 伽罗华域查表(本原多项式 0x11D,QR 标准指定) ──────────────
  var GF_EXP = new Uint8Array(512); // 指数表,多开一倍长度省去取模
  var GF_LOG = new Uint8Array(256); // 对数表
  (function () {
    var x = 1;
    for (var i = 0; i < 255; i++) {
      GF_EXP[i] = x;
      GF_LOG[x] = i;
      x <<= 1;
      if (x & 0x100) x ^= 0x11d;
    }
    for (var j = 255; j < 512; j++) GF_EXP[j] = GF_EXP[j - 255];
  })();

  function gfMul(a, b) {
    if (a === 0 || b === 0) return 0;
    return GF_EXP[GF_LOG[a] + GF_LOG[b]];
  }

  // 生成多项式 g(x) = (x-a^0)(x-a^1)...(x-a^(n-1)),系数从高次到低次
  function rsGenPoly(n) {
    var poly = [1];
    for (var i = 0; i < n; i++) {
      var next = new Array(poly.length + 1).fill(0);
      for (var j = 0; j < poly.length; j++) {
        next[j] ^= poly[j];                       // 乘 x
        next[j + 1] ^= gfMul(poly[j], GF_EXP[i]); // 乘 a^i
      }
      poly = next;
    }
    return poly;
  }

  // 对一块数据码字做 RS 编码,返回 ecCount 个纠错码字
  function rsEncode(data, ecCount) {
    var gen = rsGenPoly(ecCount);
    var rem = new Array(ecCount).fill(0);
    for (var i = 0; i < data.length; i++) {
      var factor = data[i] ^ rem[0];
      rem.shift();
      rem.push(0);
      if (factor !== 0) {
        for (var j = 0; j < ecCount; j++) {
          rem[j] ^= gfMul(gen[j + 1], factor);
        }
      }
    }
    return rem;
  }

  // ── 2. 版本参数表(只列纠错级别 M,版本 1..10) ─────────────────────────
  // 每项:[每块纠错码字数, 组1块数, 组1每块数据码字数, 组2块数, 组2每块数据码字数]
  // 数字来自 ISO/IEC 18004 表 9;校验:总码字 = Σ(块数 × (数据+纠错)) 必须等于该版本总码字数。
  var EC_M = {
    1:  [10, 1, 16, 0, 0],
    2:  [16, 1, 28, 0, 0],
    3:  [26, 1, 44, 0, 0],
    4:  [18, 2, 32, 0, 0],
    5:  [24, 2, 43, 0, 0],
    6:  [16, 4, 27, 0, 0],
    7:  [18, 4, 31, 0, 0],
    8:  [22, 2, 38, 2, 39],
    9:  [22, 3, 36, 2, 37],
    10: [26, 4, 43, 1, 44]
  };

  // 对齐图案中心坐标(版本 1..10)。版本 1 没有对齐图案。
  var ALIGN_POS = {
    1:  [],
    2:  [6, 18],
    3:  [6, 22],
    4:  [6, 26],
    5:  [6, 30],
    6:  [6, 34],
    7:  [6, 22, 38],
    8:  [6, 24, 42],
    9:  [6, 26, 46],
    10: [6, 28, 50]
  };

  var MIN_VERSION = 1;
  var MAX_VERSION = 10;

  function dataCodewordCount(version) {
    var p = EC_M[version];
    return p[1] * p[2] + p[3] * p[4];
  }

  // byte 模式的字符数指示符位宽:版本 1-9 用 8 位,版本 10+ 用 16 位
  function charCountBits(version) {
    return version <= 9 ? 8 : 16;
  }

  // ── 3. 文本 -> UTF-8 字节 ──────────────────────────────────────────────
  function utf8Bytes(str) {
    var out = [];
    for (var i = 0; i < str.length; i++) {
      var c = str.codePointAt(i);
      if (c > 0xffff) i++; // 代理对,跳过低位
      if (c < 0x80) {
        out.push(c);
      } else if (c < 0x800) {
        out.push(0xc0 | (c >> 6), 0x80 | (c & 0x3f));
      } else if (c < 0x10000) {
        out.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 0x3f), 0x80 | (c & 0x3f));
      } else {
        out.push(0xf0 | (c >> 18), 0x80 | ((c >> 12) & 0x3f),
                 0x80 | ((c >> 6) & 0x3f), 0x80 | (c & 0x3f));
      }
    }
    return out;
  }

  // ── 4. 位流构造:模式指示符 + 字符数 + 数据 + 终止符 + 补齐 ─────────────
  function buildBitStream(bytes, version) {
    var totalData = dataCodewordCount(version);
    var capBits = totalData * 8;
    var bits = [];

    function push(value, len) {
      for (var i = len - 1; i >= 0; i--) bits.push((value >> i) & 1);
    }

    push(0b0100, 4);                        // byte 模式指示符
    push(bytes.length, charCountBits(version)); // 字符(字节)数
    for (var i = 0; i < bytes.length; i++) push(bytes[i], 8);

    // 终止符:最多 4 个 0,剩余空间不足就少放几个
    var term = Math.min(4, capBits - bits.length);
    for (var t = 0; t < term; t++) bits.push(0);
    // 补到整字节
    while (bits.length % 8 !== 0) bits.push(0);

    // 交替填充字节 0xEC / 0x11 直到装满
    var padToggle = true;
    while (bits.length < capBits) {
      push(padToggle ? 0xec : 0x11, 8);
      padToggle = !padToggle;
    }

    // 位流 -> 码字
    var codewords = [];
    for (var b = 0; b < bits.length; b += 8) {
      var v = 0;
      for (var k = 0; k < 8; k++) v = (v << 1) | bits[b + k];
      codewords.push(v);
    }
    return codewords;
  }

  // ── 5. 分块 + RS 纠错 + 交织 ──────────────────────────────────────────
  function interleave(codewords, version) {
    var p = EC_M[version];
    var ecPerBlock = p[0];
    var blocks = [];
    var pos = 0;
    var g;
    for (g = 0; g < p[1]; g++) {
      blocks.push(codewords.slice(pos, pos + p[2]));
      pos += p[2];
    }
    for (g = 0; g < p[3]; g++) {
      blocks.push(codewords.slice(pos, pos + p[4]));
      pos += p[4];
    }
    var ecBlocks = blocks.map(function (blk) { return rsEncode(blk, ecPerBlock); });

    var out = [];
    var maxData = Math.max.apply(null, blocks.map(function (b) { return b.length; }));
    var i, j;
    for (i = 0; i < maxData; i++) {
      for (j = 0; j < blocks.length; j++) {
        if (i < blocks[j].length) out.push(blocks[j][i]);
      }
    }
    for (i = 0; i < ecPerBlock; i++) {
      for (j = 0; j < ecBlocks.length; j++) out.push(ecBlocks[j][i]);
    }
    return out;
  }

  // ── 6. 矩阵:功能图案 ─────────────────────────────────────────────────
  function newMatrix(size, fill) {
    var m = new Array(size);
    for (var i = 0; i < size; i++) m[i] = new Array(size).fill(fill);
    return m;
  }

  // 画一个 7×7 定位图案(含外圈黑、白环、3×3 黑心)
  function placeFinder(mod, res, size, row, col) {
    for (var r = -1; r <= 7; r++) {
      for (var c = -1; c <= 7; c++) {
        var rr = row + r, cc = col + c;
        if (rr < 0 || rr >= size || cc < 0 || cc >= size) continue;
        // 分隔符(-1 和 7 那一圈)一律白
        var inner = r >= 0 && r <= 6 && c >= 0 && c <= 6;
        var dark = inner &&
          ((r === 0 || r === 6 || c === 0 || c === 6) ||
           (r >= 2 && r <= 4 && c >= 2 && c <= 4));
        mod[rr][cc] = dark;
        res[rr][cc] = true;
      }
    }
  }

  // 画一个 5×5 对齐图案
  function placeAlign(mod, res, row, col) {
    for (var r = -2; r <= 2; r++) {
      for (var c = -2; c <= 2; c++) {
        var dark = Math.max(Math.abs(r), Math.abs(c)) !== 1;
        mod[row + r][col + c] = dark;
        res[row + r][col + c] = true;
      }
    }
  }

  function buildFunctionPatterns(version) {
    var size = version * 4 + 17;
    var mod = newMatrix(size, false);
    var res = newMatrix(size, false);
    var i;

    // 三个定位图案
    placeFinder(mod, res, size, 0, 0);
    placeFinder(mod, res, size, 0, size - 7);
    placeFinder(mod, res, size, size - 7, 0);

    // 定时图案(第 6 行 / 第 6 列,黑白交替)
    for (i = 8; i < size - 8; i++) {
      var on = i % 2 === 0;
      mod[6][i] = on; res[6][i] = true;
      mod[i][6] = on; res[i][6] = true;
    }

    // 对齐图案(与定位图案重叠的三个位置要跳过)
    var pos = ALIGN_POS[version];
    for (var a = 0; a < pos.length; a++) {
      for (var b = 0; b < pos.length; b++) {
        var r = pos[a], c = pos[b];
        var last = pos[pos.length - 1];
        if ((r === 6 && c === 6) || (r === 6 && c === last) || (r === last && c === 6)) continue;
        placeAlign(mod, res, r, c);
      }
    }

    // 格式信息占位(两处),先只标记为"已占用",内容后面填
    for (i = 0; i <= 8; i++) {
      if (i !== 6) { res[8][i] = true; res[i][8] = true; }
    }
    for (i = 0; i < 8; i++) {
      res[8][size - 1 - i] = true;
      res[size - 1 - i][8] = true;
    }
    // 固定的深色模块
    mod[size - 8][8] = true;
    res[size - 8][8] = true;

    // 版本信息占位(版本 7 及以上才有)
    if (version >= 7) {
      for (i = 0; i < 18; i++) {
        var rr = Math.floor(i / 3), cc = size - 11 + (i % 3);
        res[rr][cc] = true;
        res[cc][rr] = true;
      }
    }
    return { size: size, mod: mod, res: res };
  }

  // ── 7. 数据填充(右下角起,两列一组的之字形,跳过第 6 列) ────────────────
  function placeData(mod, res, size, codewords) {
    var bitIndex = 0;
    var totalBits = codewords.length * 8;

    function nextBit() {
      if (bitIndex >= totalBits) return false; // 余量位(remainder bits)全是 0
      var byte = codewords[bitIndex >> 3];
      var bit = (byte >> (7 - (bitIndex & 7))) & 1;
      bitIndex++;
      return bit === 1;
    }

    var upward = true;
    for (var right = size - 1; right >= 1; right -= 2) {
      if (right === 6) right = 5; // 第 6 列是定时图案,整列跳过
      for (var v = 0; v < size; v++) {
        var row = upward ? size - 1 - v : v;
        for (var k = 0; k < 2; k++) {
          var col = right - k;
          if (res[row][col]) continue;
          mod[row][col] = nextBit();
        }
      }
      upward = !upward;
    }
    return bitIndex;
  }

  // ── 8. 掩码 ──────────────────────────────────────────────────────────
  function maskFn(id, row, col) {
    switch (id) {
      case 0: return (row + col) % 2 === 0;
      case 1: return row % 2 === 0;
      case 2: return col % 3 === 0;
      case 3: return (row + col) % 3 === 0;
      case 4: return (Math.floor(row / 2) + Math.floor(col / 3)) % 2 === 0;
      case 5: return ((row * col) % 2) + ((row * col) % 3) === 0;
      case 6: return (((row * col) % 2) + ((row * col) % 3)) % 2 === 0;
      case 7: return (((row + col) % 2) + ((row * col) % 3)) % 2 === 0;
    }
    return false;
  }

  function applyMask(mod, res, size, id) {
    for (var r = 0; r < size; r++) {
      for (var c = 0; c < size; c++) {
        if (!res[r][c] && maskFn(id, r, c)) mod[r][c] = !mod[r][c];
      }
    }
  }

  // 标准的 4 条惩罚规则,分数越低越好
  function penalty(mod, size) {
    var score = 0, r, c, i;

    // 规则 1:同色连续 5 个及以上,5 个记 3 分,之后每多 1 个加 1 分(行和列各算一遍)
    function runScore(getter) {
      var s = 0;
      for (var a = 0; a < size; a++) {
        var run = 1;
        for (var b = 1; b < size; b++) {
          if (getter(a, b) === getter(a, b - 1)) {
            run++;
          } else {
            if (run >= 5) s += run - 2;
            run = 1;
          }
        }
        if (run >= 5) s += run - 2;
      }
      return s;
    }
    score += runScore(function (a, b) { return mod[a][b]; }); // 按行
    score += runScore(function (a, b) { return mod[b][a]; }); // 按列

    // 规则 2:每个 2×2 同色方块记 3 分
    for (r = 0; r < size - 1; r++) {
      for (c = 0; c < size - 1; c++) {
        var v = mod[r][c];
        if (v === mod[r][c + 1] && v === mod[r + 1][c] && v === mod[r + 1][c + 1]) score += 3;
      }
    }

    // 规则 3:出现 1011101 0000 或 0000 1011101 的形态,每次记 40 分
    var P1 = [true, false, true, true, true, false, true, false, false, false, false];
    var P2 = [false, false, false, false, true, false, true, true, true, false, true];
    function matchAt(line, start, pat) {
      for (var i2 = 0; i2 < 11; i2++) if (line[start + i2] !== pat[i2]) return false;
      return true;
    }
    for (r = 0; r < size; r++) {
      var rowLine = mod[r];
      var colLine = [];
      for (i = 0; i < size; i++) colLine.push(mod[i][r]);
      for (c = 0; c + 11 <= size; c++) {
        if (matchAt(rowLine, c, P1) || matchAt(rowLine, c, P2)) score += 40;
        if (matchAt(colLine, c, P1) || matchAt(colLine, c, P2)) score += 40;
      }
    }

    // 规则 4:深色比例偏离 50% 越多罚得越狠
    var dark = 0;
    for (r = 0; r < size; r++) for (c = 0; c < size; c++) if (mod[r][c]) dark++;
    var pct = (dark * 100) / (size * size);
    score += Math.floor(Math.abs(pct - 50) / 5) * 10;

    return score;
  }

  // ── 9. 格式信息 / 版本信息(BCH 纠错码) ────────────────────────────────
  // 格式信息:5 位(2 位纠错级别 + 3 位掩码)-> BCH(15,5) -> 再异或 0x5412
  function formatBits(maskId) {
    var ecBits = 0b00; // 纠错级别 M
    var data = (ecBits << 3) | maskId;
    var rem = data;
    for (var i = 0; i < 10; i++) {
      rem = (rem << 1) ^ (((rem >> 9) & 1) * 0b10100110111);
    }
    return (((data << 10) | rem) ^ 0b101010000010010) & 0x7fff;
  }

  // 版本信息:6 位版本号 -> BCH(18,6)
  function versionBits(version) {
    var rem = version;
    for (var i = 0; i < 12; i++) {
      rem = (rem << 1) ^ (((rem >> 11) & 1) * 0b1111100100101);
    }
    return (version << 12) | rem;
  }

  // 格式信息 15 位记作 s14 s13 … s0(s14 是最高位)。
  // ⚠️ 这里最容易踩的坑:第一份是「最高位在前」摆的,不是最低位。
  //    2026-07-24 用 macOS CoreImage 生成的参考二维码逐格对拍,才发现原来写反了。
  function placeFormat(mod, size, maskId) {
    var bits = formatBits(maskId);
    function s(k) { return ((bits >> k) & 1) === 1; } // s(k) 取第 k 位
    var i;

    // 第一份:绕着左上角定位图案摆一圈,顺序 s14 → s0
    for (i = 0; i <= 5; i++) mod[8][i] = s(14 - i);    // (8,0)…(8,5) = s14…s9
    mod[8][7] = s(8);
    mod[8][8] = s(7);
    mod[7][8] = s(6);
    for (i = 9; i <= 14; i++) mod[14 - i][8] = s(14 - i); // (5,8)…(0,8) = s5…s0

    // 第二份也是 s14 → s0:先从左下往上走 7 格,再从右上往右走 8 格
    for (i = 0; i <= 6; i++) mod[size - 1 - i][8] = s(14 - i);  // (size-1,8)…(size-7,8) = s14…s8
    for (i = 0; i <= 7; i++) mod[8][size - 8 + i] = s(7 - i);   // (8,size-8)…(8,size-1) = s7…s0

    mod[size - 8][8] = true; // 固定深色模块,不属于格式信息,最后补上
  }

  function placeVersion(mod, size, version) {
    if (version < 7) return;
    var bits = versionBits(version);
    for (var i = 0; i < 18; i++) {
      var on = ((bits >> i) & 1) === 1;
      var r = Math.floor(i / 3), c = size - 11 + (i % 3);
      mod[r][c] = on;
      mod[c][r] = on;
    }
  }

  // ── 10. 主流程 ───────────────────────────────────────────────────────
  function chooseVersion(byteLen) {
    for (var v = MIN_VERSION; v <= MAX_VERSION; v++) {
      var capBits = dataCodewordCount(v) * 8 - 4 - charCountBits(v);
      if (byteLen * 8 <= capBits) return v;
    }
    throw new Error('内容太长,超出本实现支持的版本 1-10(纠错级别 M,最多 213 字节)');
  }

  function encode(text) {
    if (typeof text !== 'string' || text.length === 0) {
      throw new Error('二维码内容不能为空');
    }
    var bytes = utf8Bytes(text);
    var version = chooseVersion(bytes.length);
    var codewords = interleave(buildBitStream(bytes, version), version);

    // 8 种掩码全试,选惩罚分最低的
    var best = null;
    for (var m = 0; m < 8; m++) {
      var fp = buildFunctionPatterns(version);
      placeData(fp.mod, fp.res, fp.size, codewords);
      applyMask(fp.mod, fp.res, fp.size, m);
      placeFormat(fp.mod, fp.size, m);
      placeVersion(fp.mod, fp.size, version);
      var s = penalty(fp.mod, fp.size);
      if (best === null || s < best.score) {
        best = { score: s, mask: m, mod: fp.mod, size: fp.size };
      }
    }
    return {
      size: best.size,
      version: version,
      mask: best.mask,
      penalty: best.score,
      ecLevel: 'M',
      modules: best.mod
    };
  }

  // 只要矩阵(true = 黑块),给需要自己画的地方用
  function toMatrix(text) {
    return encode(text);
  }

  // 画到 canvas。返回值同 toMatrix,方便调用方顺手拿到版本/掩码信息。
  function render(canvas, text, opts) {
    opts = opts || {};
    var qr = encode(text);
    var margin = opts.margin === undefined ? 4 : opts.margin;
    var target = opts.size || 256;
    var total = qr.size + margin * 2;
    // 每个模块占整数像素,避免半像素造成的模糊边(扫码识别率的头号杀手)
    var scale = Math.max(1, Math.floor(target / total));
    var px = total * scale;

    canvas.width = px;
    canvas.height = px;
    if (!canvas.style.width) canvas.style.width = px + 'px';
    if (!canvas.style.height) canvas.style.height = px + 'px';

    var ctx = canvas.getContext('2d');
    ctx.fillStyle = opts.light || '#ffffff';
    ctx.fillRect(0, 0, px, px);
    ctx.fillStyle = opts.dark || '#000000';
    for (var r = 0; r < qr.size; r++) {
      for (var c = 0; c < qr.size; c++) {
        if (qr.modules[r][c]) {
          ctx.fillRect((c + margin) * scale, (r + margin) * scale, scale, scale);
        }
      }
    }
    return qr;
  }

  global.PSMQR = {
    render: render,
    toMatrix: toMatrix,
    MAX_VERSION: MAX_VERSION,
    EC_LEVEL: 'M'
  };
})(typeof window !== 'undefined' ? window : globalThis);
