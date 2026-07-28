// 压测军团 · 主跑批脚本。
//   node tools/stress/run-all.mjs J        只跑组 J(join 完整动线,24)
//   node tools/stress/run-all.mjs S        只跑组 S(show 五视图,24)
//   node tools/stress/run-all.mjs R        只跑组 R(粗暴操作,16)
//   node tools/stress/run-all.mjs P        只跑组 P(portal/pov 补充烟测,8)
//   node tools/stress/run-all.mjs all      全跑(72)
import { boot, Tab } from "./cdp.mjs";
import { buildJoinMatrix, buildShowMatrix, buildRoughMatrix, buildSmokeMatrix } from "./matrix.mjs";
import { runJoinFlow, runShowFlow, runRoughFlow, runSmokeFlow } from "./flows.mjs";
import { appendFileSync, writeFileSync, existsSync, readFileSync } from "node:fs";

const RUNLOG = "/Users/max/code/spatial-memory/tools/stress/runlog.txt";
const BUGSRAW = "/Users/max/code/spatial-memory/tools/stress/bugs-raw.json";

function overflowStr(v) { return v === false || v == null ? "false" : String(v); }

function logLine(r) {
  const line = `[${r.id}] result=${r.pass ? "PASS" : "FAIL"} errs=${r.errsCount ?? "?"} overflow=${overflowStr(r.overflow)} ms=${r.ms} bugs=${r.bugs.length}${r.bugs.length ? " :: " + r.bugs.join(" | ") : ""}\n`;
  appendFileSync(RUNLOG, line);
  console.log(line.trim());
}

function loadRaw() {
  if (!existsSync(BUGSRAW)) return [];
  try { return JSON.parse(readFileSync(BUGSRAW, "utf8")); } catch { return []; }
}
function saveRaw(all) { writeFileSync(BUGSRAW, JSON.stringify(all, null, 1)); }

async function runGroup(name, matrix, flowFn) {
  console.log(`\n===== 开跑组 ${name},共 ${matrix.length} 个变体 =====`);
  const all = loadRaw();
  for (const v of matrix) {
    const t = await Tab.open();
    let r;
    try {
      r = await flowFn(t, v);
    } catch (e) {
      r = { id: v.id, group: name, meta: v, bugs: ["外层异常: " + (e && e.stack || e)], notes: [], pass: false, ms: 0 };
    }
    await t.close();
    logLine(r);
    all.push(r);
    saveRaw(all); // 每跑完一条就落盘,防止中途中断丢结果
  }
  return all;
}

const arg = (process.argv[2] || "all").toUpperCase();
await boot();

if (arg === "J" || arg === "ALL") await runGroup("J", buildJoinMatrix(), runJoinFlow);
if (arg === "S" || arg === "ALL") await runGroup("S", buildShowMatrix(), runShowFlow);
if (arg === "R" || arg === "ALL") await runGroup("R", buildRoughMatrix(), runRoughFlow);
if (arg === "P" || arg === "ALL") await runGroup("P", buildSmokeMatrix(), runSmokeFlow);

const all = loadRaw();
const passCount = all.filter(r => r.pass).length;
console.log(`\n===== 汇总: 共 ${all.length} 条, PASS ${passCount}, FAIL ${all.length - passCount} =====`);
