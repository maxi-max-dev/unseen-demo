// 批次J:重建批次I在BLOCKED.md I-2记录的workaround(当时的文件本身没留在仓库里)。
// automator.launch() 在本机重复调用时会静默卡死(BLOCKED.md I-2的实测结论)，
// 改用"自己探测端口，没开就自己spawn一次cli auto，开了就直接connect()"绕过。
"use strict";
var net = require("net");
var cp = require("child_process");
var automator = require("miniprogram-automator");

var CLI_PATH = "/Applications/wechatwebdevtools.app/Contents/MacOS/cli";
var PORT = 9420;

function probePort(port, cb) {
  var sock = net.createConnection({ port: port, host: "127.0.0.1" });
  var done = false;
  sock.on("connect", function () {
    done = true;
    sock.destroy();
    cb(true);
  });
  sock.on("error", function () {
    if (!done) { done = true; cb(false); }
  });
}

function waitForPort(port, timeoutMs, cb) {
  var start = Date.now();
  (function tick() {
    probePort(port, function (open) {
      if (open) return cb(null);
      if (Date.now() - start > timeoutMs) return cb(new Error("端口" + port + "在" + timeoutMs + "ms内没开"));
      setTimeout(tick, 300);
    });
  })();
}

function connect(projectPath) {
  return new Promise(function (resolve, reject) {
    probePort(PORT, function (open) {
      if (open) {
        automator.connect({ wsEndpoint: "ws://127.0.0.1:" + PORT }).then(resolve, reject);
        return;
      }
      var child = cp.spawn(CLI_PATH, ["auto", "--project", projectPath, "--auto-port", String(PORT)], {
        detached: true,
        stdio: "ignore"
      });
      child.unref();
      waitForPort(PORT, 30000, function (err) {
        if (err) return reject(err);
        automator.connect({ wsEndpoint: "ws://127.0.0.1:" + PORT }).then(resolve, reject);
      });
    });
  });
}

module.exports = { connect: connect, PORT: PORT };
