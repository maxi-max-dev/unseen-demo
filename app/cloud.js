/* 公网入口地址。
 *
 * 为什么要有这个文件:二维码和分享链接原来写死在三个地方(server/host.html、
 * app/scene.html、app/invite.html),换主机就得三处手改,漏一处现场就发出去一个死码。
 * 2026-07-25 Max 实测 Vercel 在国内不挂加速器打不开,这个开关就是为那一刻准备的。
 *
 * 正式站自动使用当前域名,所以部署到阿里云自定义域名后不用再改源码。
 * 本机开发仍回到当前 Vercel 公网入口。后端那一份对应环境变量 PSM_CLOUD_JOIN_BASE。
 */
(function () {
  "use strict";
  var FALLBACK = "https://unseen-demo.vercel.app";
  var STORE_KEY = "unseen.public.origin.v1";

  function isLocalHost(host) {
    host = String(host || "").toLowerCase();
    if (/^(localhost\.?|127(?:\.\d{1,3}){3}|\[::1\]|.*\.local)$/.test(host)) return true;
    if (/^(10|192\.168)\./.test(host)) return true;
    var m = host.match(/^172\.(\d{1,3})\./);
    return !!(m && Number(m[1]) >= 16 && Number(m[1]) <= 31);
  }

  function originOf(value) {
    try {
      var u = new URL(String(value || ""), location.href);
      // 这是宾客公网入口,只接受 HTTPS。这样旧缓存里的 localhost、局域网地址
      // 和误填的 HTTP 域名都不会污染后续二维码。
      return u.protocol === "https:" ? u.origin : "";
    } catch (e) { return ""; }
  }

  var local = isLocalHost(location.hostname);
  // 正式站被教程强制为 HTTPS。HTTP 一律不当公网,这样局域网 IP 和带尾点的
  // localhost 都不会被误做成宾客二维码。
  var hosted = location.protocol === "https:" && !local;
  var remembered = "";
  try { remembered = originOf(localStorage.getItem(STORE_KEY)); } catch (e) {}

  window.UNSEEN_IS_LOCAL_ORIGIN = local;
  window.UNSEEN_CLOUD_ORIGIN = hosted ? location.origin : (remembered || FALLBACK);
  window.UNSEEN_SET_CLOUD_ORIGIN = function (value) {
    var origin = originOf(value);
    if (!origin) return false;
    window.UNSEEN_CLOUD_ORIGIN = origin;
    if (local) {
      try { localStorage.setItem(STORE_KEY, origin); } catch (e) {}
    }
    return true;
  };
})();
