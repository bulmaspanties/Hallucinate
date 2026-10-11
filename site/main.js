// Point the main download button at the visitor's platform, and enlarge screenshots on click.
(function () {
  "use strict";

  function detectOS() {
    var data = navigator.userAgentData;
    var platform = ((data && data.platform) || navigator.platform || "").toLowerCase();
    var ua = navigator.userAgent.toLowerCase();
    if (/android|iphone|ipad|ipod/.test(ua)) return null; // desktop app only
    if (platform.indexOf("win") === 0 || ua.indexOf("windows") !== -1) return "windows";
    if (platform.indexOf("mac") === 0 || ua.indexOf("mac os") !== -1) return "mac";
    if (platform.indexOf("linux") !== -1 || ua.indexOf("linux") !== -1 || ua.indexOf("x11") !== -1) return "linux";
    return null;
  }

  var labels = { windows: "Download for Windows", mac: "Download for Mac", linux: "Download for Linux" };
  var os = detectOS();
  var card = os && document.querySelector('.dl[data-os="' + os + '"]');
  var primary = document.getElementById("primary-download");
  if (card && primary) {
    card.classList.add("recommended");
    primary.href = card.querySelector(".btn").href;
    primary.querySelector("span").textContent = labels[os];
  }

  document.querySelectorAll(".gallery img, .themes img").forEach(function (img) {
    img.addEventListener("click", function () {
      var box = document.createElement("div");
      box.className = "lightbox";
      box.setAttribute("role", "dialog");
      box.setAttribute("aria-label", img.alt);
      var big = document.createElement("img");
      big.src = img.currentSrc || img.src;
      big.alt = img.alt;
      box.appendChild(big);
      function close() { box.remove(); document.removeEventListener("keydown", onKey); }
      function onKey(e) { if (e.key === "Escape") close(); }
      box.addEventListener("click", close);
      document.addEventListener("keydown", onKey);
      document.body.appendChild(box);
    });
  });
})();
