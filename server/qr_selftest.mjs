/**
 * server/qr_selftest.mjs —— qr.js 的自检脚本(node 里跑,零依赖)
 *
 * 跑法:  node server/qr_selftest.mjs
 *
 * 二维码这种东西错了不会报错,只会"生成出来但扫不出",所以必须结构级自检。
 * 这里查 7 组:
 *   1) 矩阵尺寸 == 4*版本+17
 *   2) 三个 7×7 定位图案(左上/右上/左下)形状对不对 + 分隔符是不是白的
 *   3) 定时图案(第 6 行/第 6 列)是不是严格黑白交替
 *   4) 固定深色模块 + 对齐图案位置
 *   5) Reed-Solomon 纠错:用"校验子必须全 0"这个数学性质验(不依赖任何外部参考数据),
 *      再顺手对一组公开的已知测试向量
 *   6) 格式信息 / 版本信息的 BCH 编码是否等于标准表里的值
 *   7) 回环解码:另写一个独立解码器把矩阵读回来,还原出的字符串必须等于原文
 *      (这一步能抓出之字形填充顺序、掩码、交织这三处最容易静默出错的地方)
 */
import { readFileSync, writeFileSync, mkdtempSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
// qr.js 是给浏览器写的普通脚本,这里用间接 eval 在全局作用域跑一遍拿到 PSMQR
(0, eval)(readFileSync(join(HERE, 'qr.js'), 'utf8'));
const PSMQR = globalThis.PSMQR;

let pass = 0, fail = 0;
function check(name, ok, detail) {
  if (ok) { pass++; console.log(`  ✅ ${name}`); }
  else { fail++; console.log(`  ❌ ${name}${detail ? '  ← ' + detail : ''}`); }
}

// ── 独立实现一份"哪些格子是功能图案"的判断,故意不复用 qr.js 的代码 ──────
function reservedMap(version) {
  const size = version * 4 + 17;
  const res = Array.from({ length: size }, () => new Array(size).fill(false));
  const box = (r0, c0, h, w) => {
    for (let r = r0; r < r0 + h; r++)
      for (let c = c0; c < c0 + w; c++)
        if (r >= 0 && r < size && c >= 0 && c < size) res[r][c] = true;
  };
  // 定位图案 + 分隔符(各占 8×8 的角落)
  box(0, 0, 8, 8);
  box(0, size - 8, 8, 8);
  box(size - 8, 0, 8, 8);
  // 定时图案
  for (let i = 0; i < size; i++) { res[6][i] = true; res[i][6] = true; }
  // 格式信息第一份:第 8 行 0..8 和第 8 列 0..8(注意 8×8 的角落只到下标 7,这一圈是额外的)
  for (let i = 0; i <= 8; i++) { res[8][i] = true; res[i][8] = true; }
  // 格式信息第二份(右上一横、左下一竖,含固定深色模块)
  for (let i = 0; i < 8; i++) { res[8][size - 1 - i] = true; res[size - 1 - i][8] = true; }
  // 对齐图案
  const ALIGN = { 1: [], 2: [6,18], 3: [6,22], 4: [6,26], 5: [6,30], 6: [6,34],
                  7: [6,22,38], 8: [6,24,42], 9: [6,26,46], 10: [6,28,50] }[version];
  const last = ALIGN[ALIGN.length - 1];
  for (const r of ALIGN) for (const c of ALIGN) {
    if ((r === 6 && c === 6) || (r === 6 && c === last) || (r === last && c === 6)) continue;
    box(r - 2, c - 2, 5, 5);
  }
  // 版本信息
  if (version >= 7) { box(0, size - 11, 6, 3); box(size - 11, 0, 3, 6); }
  return res;
}

function maskFn(id, r, c) {
  switch (id) {
    case 0: return (r + c) % 2 === 0;
    case 1: return r % 2 === 0;
    case 2: return c % 3 === 0;
    case 3: return (r + c) % 3 === 0;
    case 4: return (Math.floor(r / 2) + Math.floor(c / 3)) % 2 === 0;
    case 5: return ((r * c) % 2) + ((r * c) % 3) === 0;
    case 6: return (((r * c) % 2) + ((r * c) % 3)) % 2 === 0;
    case 7: return (((r + c) % 2) + ((r * c) % 3)) % 2 === 0;
  }
}

const EC_M = { 1:[10,1,16,0,0], 2:[16,1,28,0,0], 3:[26,1,44,0,0], 4:[18,2,32,0,0],
               5:[24,2,43,0,0], 6:[16,4,27,0,0], 7:[18,4,31,0,0], 8:[22,2,38,2,39],
               9:[22,3,36,2,37], 10:[26,4,43,1,44] };

// 格式信息第一份的 15 个格子,顺序就是标准串 s14 → s0(位置和顺序都对着
// macOS CoreImage 生成的参考二维码逐格核过,不是照抄 qr.js 的写法)
const FORMAT_CELLS_1 = [[8,0],[8,1],[8,2],[8,3],[8,4],[8,5],[8,7],[8,8],
                        [7,8],[5,8],[4,8],[3,8],[2,8],[1,8],[0,8]];
// 第二份:先从左下往上 7 格,再从右上往右 8 格
function formatCells2(size) {
  const cells = [];
  for (let i = 0; i <= 6; i++) cells.push([size - 1 - i, 8]);
  for (let i = 0; i <= 7; i++) cells.push([8, size - 8 + i]);
  return cells;
}
// 读回格式信息串(s14…s0 的字符串)
function readFormatStr(mod, cells) {
  return cells.map(([r, c]) => (mod[r][c] ? '1' : '0')).join('');
}
function readFormat(mod, size) {
  const str = readFormatStr(mod, FORMAT_CELLS_1);
  const v = parseInt(str, 2) ^ 0b101010000010010;
  const data = v >> 10;
  return { ecBits: (data >> 3) & 3, mask: data & 7, str };
}

// 独立的解码器:读矩阵 -> 去掩码 -> 之字形取位 -> 反交织 -> 解 byte 模式
function decode(mod, size, version) {
  const { mask } = readFormat(mod, size);
  const res = reservedMap(version);
  const un = mod.map((row, r) => row.map((v, c) => (res[r][c] ? v : (maskFn(mask, r, c) ? !v : v))));

  const bits = [];
  let upward = true;
  for (let right = size - 1; right >= 1; right -= 2) {
    if (right === 6) right = 5;
    for (let v = 0; v < size; v++) {
      const row = upward ? size - 1 - v : v;
      for (let k = 0; k < 2; k++) {
        const col = right - k;
        if (res[row][col]) continue;
        bits.push(un[row][col] ? 1 : 0);
      }
    }
    upward = !upward;
  }
  const p = EC_M[version];
  const totalCw = p[1] * (p[2] + p[0]) + p[3] * (p[4] + p[0]);
  const cw = [];
  for (let i = 0; i + 8 <= bits.length && cw.length < totalCw; i += 8) {
    let b = 0;
    for (let k = 0; k < 8; k++) b = (b << 1) | bits[i + k];
    cw.push(b);
  }

  // 反交织
  const sizes = [];
  for (let i = 0; i < p[1]; i++) sizes.push(p[2]);
  for (let i = 0; i < p[3]; i++) sizes.push(p[4]);
  const blocks = sizes.map(() => []);
  let idx = 0;
  const maxLen = Math.max(...sizes);
  for (let i = 0; i < maxLen; i++)
    for (let b = 0; b < sizes.length; b++)
      if (i < sizes[b]) blocks[b].push(cw[idx++]);
  const ecBlocks = sizes.map(() => []);
  for (let i = 0; i < p[0]; i++)
    for (let b = 0; b < sizes.length; b++) ecBlocks[b].push(cw[idx++]);

  const data = [].concat(...blocks);

  // 解位流
  let bi = 0;
  const dbits = [];
  for (const byte of data) for (let k = 7; k >= 0; k--) dbits.push((byte >> k) & 1);
  const take = (n) => { let v = 0; for (let i = 0; i < n; i++) v = (v << 1) | dbits[bi++]; return v; };
  const mode = take(4);
  const count = take(version <= 9 ? 8 : 16);
  const bytes = [];
  for (let i = 0; i < count; i++) bytes.push(take(8));
  const text = new TextDecoder().decode(Uint8Array.from(bytes));
  return { mode, count, text, blocks, ecBlocks };
}

// ── GF(256) 校验子:合法 RS 码字在 a^0..a^(n-1) 处求值必须全为 0 ──────────
const EXP = new Uint8Array(512), LOG = new Uint8Array(256);
{ let x = 1; for (let i = 0; i < 255; i++) { EXP[i] = x; LOG[x] = i; x <<= 1; if (x & 0x100) x ^= 0x11d; }
  for (let i = 255; i < 512; i++) EXP[i] = EXP[i - 255]; }
const mul = (a, b) => (a === 0 || b === 0 ? 0 : EXP[LOG[a] + LOG[b]]);
function syndromesAllZero(codeword, ecCount) {
  for (let i = 0; i < ecCount; i++) {
    let s = 0;
    for (const c of codeword) s = mul(s, EXP[i]) ^ c;
    if (s !== 0) return false;
  }
  return true;
}

// ══════════════════════════════════════════════════════════════════════
console.log('\n=== PSMQR 自检 ===\n');

const SAMPLES = [
  'https://a1b2-c3d4-e5f6.trycloudflare.com/join?s=s1',
  'http://192.168.1.23:8777/join?s=s1',
  'HELLO',
  'https://example-tunnel-name-that-is-long.trycloudflare.com/join?s=s1&t=t7&from=qr',
  'x'.repeat(120),
  '陈屹 ♥ 林沐 · 扫码进空间'
];

console.log('[1] 结构检查');
for (const text of SAMPLES) {
  const qr = PSMQR.toMatrix(text);
  const { size, version, modules: m } = qr;
  const label = text.length > 28 ? text.slice(0, 26) + '…' : text;

  check(`尺寸 ${size} == 4*${version}+17  「${label}」`, size === 4 * version + 17, `实际 ${size}`);

  // 定位图案:7×7 的期望图形
  const finderOK = (r0, c0) => {
    for (let r = 0; r < 7; r++) for (let c = 0; c < 7; c++) {
      const want = (r === 0 || r === 6 || c === 0 || c === 6) ||
                   (r >= 2 && r <= 4 && c >= 2 && c <= 4);
      if (m[r0 + r][c0 + c] !== want) return `(${r0 + r},${c0 + c})`;
    }
    return true;
  };
  const f1 = finderOK(0, 0), f2 = finderOK(0, size - 7), f3 = finderOK(size - 7, 0);
  check(`  三个定位图案 7×7 正确`, f1 === true && f2 === true && f3 === true,
        `左上 ${f1} 右上 ${f2} 左下 ${f3}`);

  // 分隔符:定位图案外那一圈必须全白
  let sepBad = null;
  for (let i = 0; i < 8; i++) {
    if (m[7][i] || m[i][7]) sepBad = `左上 (7,${i})`;
    if (m[7][size - 1 - i] || m[i][size - 8]) sepBad = sepBad || `右上`;
    if (m[size - 8][i] || m[size - 1 - i][7]) sepBad = sepBad || `左下`;
  }
  check(`  分隔符全白`, sepBad === null, sepBad);

  // 定时图案严格交替,且偶数下标为黑
  let timingBad = null;
  for (let i = 8; i < size - 8; i++) {
    if (m[6][i] !== (i % 2 === 0)) timingBad = `第6行 i=${i}`;
    if (m[i][6] !== (i % 2 === 0)) timingBad = timingBad || `第6列 i=${i}`;
  }
  check(`  定时图案黑白交替`, timingBad === null, timingBad);

  check(`  固定深色模块 (${size - 8},8)`, m[size - 8][8] === true);
}

console.log('\n[2] 对齐图案(抽版本 2 / 7 各查一处)');
{
  const q2 = PSMQR.toMatrix('x'.repeat(20));                 // 版本 2
  const alignOK = (m, r0, c0) => {
    for (let r = -2; r <= 2; r++) for (let c = -2; c <= 2; c++) {
      const want = Math.max(Math.abs(r), Math.abs(c)) !== 1;
      if (m[r0 + r][c0 + c] !== want) return false;
    }
    return true;
  };
  check(`版本 ${q2.version} 的对齐图案在 (18,18)`, q2.version === 2 && alignOK(q2.modules, 18, 18));
  const q7 = PSMQR.toMatrix('y'.repeat(115));                // 版本 7
  check(`版本 ${q7.version} 的对齐图案在 (22,22) 和 (38,38)`,
        q7.version === 7 && alignOK(q7.modules, 22, 22) && alignOK(q7.modules, 38, 38));
}

console.log('\n[3] Reed-Solomon 纠错');
{
  // 数学性质:任何合法 RS 码字在 a^0..a^(n-1) 处求值都是 0。这条不依赖任何外部参考数据。
  let allOK = true, whichBad = '';
  for (const text of SAMPLES) {
    const qr = PSMQR.toMatrix(text);
    const d = decode(qr.modules, qr.size, qr.version);
    const ecCount = EC_M[qr.version][0];
    for (let b = 0; b < d.blocks.length; b++) {
      if (!syndromesAllZero(d.blocks[b].concat(d.ecBlocks[b]), ecCount)) {
        allOK = false; whichBad = `版本 ${qr.version} 第 ${b} 块`;
      }
    }
  }
  check('每一块的 RS 校验子全为 0', allOK, whichBad);

  // 公开的已知测试向量(QR 教程里常见的 1-M "HELLO WORLD" 例子)
  const known = { data: [32,91,11,120,209,114,220,77,67,64,236,17,236,17,236,17],
                  ec:   [196,35,39,119,235,215,231,226,93,23] };
  check('已知测试向量 1-M 的校验子为 0(等价于该向量确为合法码字)',
        syndromesAllZero(known.data.concat(known.ec), 10));
}

console.log('\n[4] 格式信息 / 版本信息 BCH');
{
  // 标准表:纠错级别 M 的 8 个格式信息串(写法是 s14 → s0)
  const FORMAT_M = ['101010000010010','101000100100101','101111001111100','101101101001011',
                    '100010111111001','100000011001110','100111110010111','100101010100000'];
  let bad = '';
  const seen = new Set();
  for (let i = 0; i < 60; i++) {
    const qr = PSMQR.toMatrix('https://t' + i + '.trycloudflare.com/join?s=s' + i);
    const s1 = readFormatStr(qr.modules, FORMAT_CELLS_1);
    const s2 = readFormatStr(qr.modules, formatCells2(qr.size));
    const idx = FORMAT_M.indexOf(s1);
    if (idx < 0) { bad = `第一份 ${s1} 不在标准表里`; break; }
    if (idx !== qr.mask) { bad = `第一份写的是掩码 ${idx},实际用的是 ${qr.mask}`; break; }
    if (s2 !== s1) { bad = `两份格式信息不一致:${s1} vs ${s2}`; break; }
    seen.add(qr.mask);
  }
  check(`格式信息两份都等于标准表对应串(覆盖掩码 ${[...seen].sort().join(',')})`, bad === '', bad);

  const VERSION_STR = { 7:'000111110010010100', 8:'001000010110111100',
                        9:'001001101010011001', 10:'001010010011010011' };
  let vbad = '';
  for (const [v, want] of Object.entries(VERSION_STR)) {
    const ver = Number(v);
    const len = { 7: 115, 8: 140, 9: 170, 10: 200 }[ver];
    const qr = PSMQR.toMatrix('q'.repeat(len));
    if (qr.version !== ver) { vbad = `文本长度 ${len} 期望版本 ${ver} 实得 ${qr.version}`; continue; }
    const bits = [];
    for (let i = 0; i < 18; i++) {
      const r = Math.floor(i / 3), c = qr.size - 11 + (i % 3);
      bits[i] = qr.modules[r][c] ? 1 : 0;
      if ((qr.modules[c][r] ? 1 : 0) !== bits[i]) vbad = `版本 ${ver} 两份版本信息不一致 i=${i}`;
    }
    const got = bits.slice().reverse().join('');
    if (got !== want) vbad = `版本 ${ver}: 期望 ${want} 实得 ${got}`;
  }
  check('版本 7-10 的 18 位版本信息与标准表一致', vbad === '', vbad);
}

console.log('\n[5] 回环解码(独立解码器把矩阵读回来)');
for (const text of SAMPLES) {
  const qr = PSMQR.toMatrix(text);
  let out;
  try { out = decode(qr.modules, qr.size, qr.version); }
  catch (e) { out = { mode: -1, text: '<解码抛异常:' + e.message + '>' }; }
  const label = text.length > 28 ? text.slice(0, 26) + '…' : text;
  check(`「${label}」 v${qr.version} mask${qr.mask} 罚分${qr.penalty} 解回原文`,
        out.mode === 4 && out.text === text, `实得「${out.text}」`);
}

console.log('\n[6] 掩码是真的在挑(不是写死 0)');
{
  const masks = new Set();
  for (let i = 0; i < 40; i++) {
    masks.add(PSMQR.toMatrix('https://demo-' + i + '.trycloudflare.com/join?s=s' + i).mask);
  }
  check(`40 个样本出现了 ${masks.size} 种掩码:${[...masks].sort().join(',')}`, masks.size >= 3);
}

console.log('\n[7] 版本自动选择的边界');
{
  const cases = [[14,1],[15,2],[26,2],[27,3],[42,3],[43,4],[62,4],[63,5],
                 [84,5],[85,6],[106,6],[107,7],[122,7],[123,8]];
  let bad = '';
  for (const [len, want] of cases) {
    const v = PSMQR.toMatrix('a'.repeat(len)).version;
    if (v !== want) bad += ` ${len}字节→期望v${want}实得v${v};`;
  }
  check('容量边界(14/26/42/62/84/106/122 字节处换版本)', bad === '', bad);
  let overflow = false;
  try { PSMQR.toMatrix('a'.repeat(214)); } catch (e) { overflow = /太长/.test(e.message); }
  check('超长文本会明确报错而不是悄悄画错', overflow);
}

console.log('\n[8] 和系统自带的二维码实现对拍(macOS CoreImage,非 node 依赖)');
{
  // 这一步是整个自检里最有价值的一条:
  //  a) 用 macOS 的 CIQRCodeGenerator(纠错级别 M)生成参考矩阵,和我们的逐格比对;
  //  b) 把我们自己的矩阵画成图,交给 CIDetector(iPhone 相机同一套 CoreImage 引擎)去扫,
  //     看能不能读回原文。
  // 之所以必须有这条:2026-07-24 第一版格式信息的位序写反了,前面 7 组自检全绿,
  // 但真扫码器一个都认不出来 —— 自己写的编码器 + 自己写的解码器会一起错。
  const swiftSrc = `
import Foundation
import CoreImage
let inPath = CommandLine.arguments[1]
let items = try! JSONSerialization.jsonObject(
    with: Data(contentsOf: URL(fileURLWithPath: inPath))) as! [[String: Any]]
let ctx = CIContext(options: [.useSoftwareRenderer: true])

func pixels(_ cg: CGImage) -> [String] {
    let w = cg.width, h = cg.height
    var buf = [UInt8](repeating: 0, count: w * h * 4)
    let bctx = CGContext(data: &buf, width: w, height: h, bitsPerComponent: 8,
                         bytesPerRow: w * 4, space: CGColorSpaceCreateDeviceRGB(),
                         bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
    bctx.draw(cg, in: CGRect(x: 0, y: 0, width: w, height: h))
    var lines: [String] = []
    for y in 0..<h {
        var row = ""
        for x in 0..<w {
            let i = (y * w + x) * 4
            row += (buf[i] < 128 && buf[i + 3] > 128) ? "1" : "0"
        }
        lines.append(row)
    }
    return lines
}

func imageFrom(_ rows: [String], scale: Int, quiet: Int) -> CGImage {
    let n = rows.count, side = (n + quiet * 2) * scale
    var buf = [UInt8](repeating: 255, count: side * side * 4)
    for (r, row) in rows.enumerated() {
        for (c, ch) in Array(row).enumerated() where ch == "1" {
            for dy in 0..<scale { for dx in 0..<scale {
                let y = (r + quiet) * scale + dy, x = (c + quiet) * scale + dx
                let i = (y * side + x) * 4
                buf[i] = 0; buf[i+1] = 0; buf[i+2] = 0; buf[i+3] = 255
            } }
        }
    }
    let bctx = CGContext(data: &buf, width: side, height: side, bitsPerComponent: 8,
                         bytesPerRow: side * 4, space: CGColorSpaceCreateDeviceRGB(),
                         bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
    return bctx.makeImage()!
}

var out: [[String: Any]] = []
let det = CIDetector(ofType: CIDetectorTypeQRCode, context: ctx,
                     options: [CIDetectorAccuracy: CIDetectorAccuracyHigh])!
for item in items {
    let text = item["text"] as! String
    let mine = item["matrix"] as! [String]
    var ref: [String] = []
    let f = CIFilter(name: "CIQRCodeGenerator")!
    f.setValue(text.data(using: .utf8)!, forKey: "inputMessage")
    f.setValue("M", forKey: "inputCorrectionLevel")
    if let img = f.outputImage, let cg = ctx.createCGImage(img, from: img.extent) {
        ref = pixels(cg)
    }
    let ci = CIImage(cgImage: imageFrom(mine, scale: 6, quiet: 4))
    let decoded = det.features(in: ci).compactMap { ($0 as? CIQRCodeFeature)?.messageString }
    out.append(["text": text, "ref": ref, "decoded": decoded])
}
FileHandle.standardOutput.write(try! JSONSerialization.data(withJSONObject: out))
`;
  let result = null, skipReason = '';
  try {
    const dir = mkdtempSync(join(tmpdir(), 'psmqr-'));
    const sw = join(dir, 'ref.swift'), inp = join(dir, 'in.json');
    writeFileSync(sw, swiftSrc);
    writeFileSync(inp, JSON.stringify(SAMPLES.map((t) => {
      const qr = PSMQR.toMatrix(t);
      return { text: t, matrix: qr.modules.map((r) => r.map((b) => (b ? '1' : '0')).join('')) };
    })));
    result = JSON.parse(execFileSync('swift', [sw, inp], { maxBuffer: 1 << 26 }).toString());
  } catch (e) {
    skipReason = String(e.message || e).split('\n')[0];
  }

  if (!result) {
    console.log(`  ⚠️  跳过(这台机器跑不了 swift:${skipReason})`);
  } else {
    let exactMatches = 0;
    for (const row of result) {
      const label = row.text.length > 24 ? row.text.slice(0, 22) + '…' : row.text;
      // a) 真·扫码器能不能读出来
      check(`「${label}」 系统扫码器(CIDetector)读回原文`,
            row.decoded.length === 1 && row.decoded[0] === row.text,
            `实得 ${JSON.stringify(row.decoded)}`);
      // b) 和系统生成的参考矩阵逐格比对
      let ref = row.ref;
      if (!ref.length) { console.log('  ⚠️  参考矩阵为空,跳过逐格比对'); continue; }
      // CoreImage 输出带 1 模块静区;顺手判一下上下方向(定时图案必须落在第 6 行)
      const strip = (a) => a.slice(1, a.length - 1).map((r) => r.slice(1, r.length - 1));
      const timingOK = (m) => m.length > 7 && [...m[6]].every((ch, i) =>
        (i < 8 || i >= m.length - 8) ? true : ch === (i % 2 === 0 ? '1' : '0'));
      let core = strip(ref);
      if (!timingOK(core)) core = strip(ref.slice().reverse());
      const mine = PSMQR.toMatrix(row.text);
      if (core.length !== mine.size) {
        console.log(`  ⏭  「${label}」 系统选了 ${core.length}×${core.length},我们是 ${mine.size}×${mine.size}(编码模式不同),跳过逐格比对`);
        continue;
      }
      let diff = 0, where = [];
      for (let r = 0; r < mine.size; r++) for (let c = 0; c < mine.size; c++) {
        if ((core[r][c] === '1') !== mine.modules[r][c]) { diff++; if (where.length < 8) where.push(`(${r},${c})`); }
      }
      if (diff === 0) {
        exactMatches++;
        console.log(`  ✅ 「${label}」 与系统参考矩阵逐格完全一致(v${mine.version} mask${mine.mask})`);
        pass++;
      } else {
        // 逐格不同不一定是错:系统会挑更省的编码模式(比如 HELLO 走字母数字模式),
        // 也可能选了别的掩码。只要扫码器认得出来,两张都是合法二维码。
        const refMod = core.map((r) => [...r].map((ch) => ch === '1'));
        const rf = readFormat(refMod, core.length);
        console.log(`  ⏭  「${label}」 与参考不同 ${diff} 格 —— 系统用的是 mask${rf.mask},我们是 mask${mine.mask};` +
                    `两边都能被扫出来,属于编码方式不同,不算错`);
      }
    }
    // 逐格完全一致的样本必须够多:这条能锁死功能图案/格式信息/版本信息/RS/掩码的全部布局
    check(`至少 3 个样本与系统参考矩阵逐格完全一致(实得 ${exactMatches} 个)`, exactMatches >= 3);
  }
}

console.log(`\n=== 结果:${pass} 通过 / ${fail} 失败 ===\n`);
process.exit(fail === 0 ? 0 : 1);
