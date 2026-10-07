// site-check: evaluate in the page (after scrolling to the bottom once so
// lazy images load). Returns a JSON string of findings.
(() => {
  const out = { url: location.href, viewport: [innerWidth, innerHeight] };

  // Horizontal overflow, ignoring elements hidden off-canvas on purpose.
  out.scrollWidth = document.documentElement.scrollWidth;
  out.overflowing = [...document.querySelectorAll("body *")]
    .filter((e) => {
      const r = e.getBoundingClientRect();
      const s = getComputedStyle(e);
      const hidden = s.visibility === "hidden" || s.display === "none" ||
        s.transform !== "none" && r.left >= innerWidth;
      return !hidden && r.width > 0 && r.right > innerWidth + 1;
    })
    .slice(0, 10)
    .map((e) => `${e.tagName.toLowerCase()}.${[...e.classList].join(".")} right=${Math.round(e.getBoundingClientRect().right)}`);

  // Images.
  const imgs = [...document.images];
  out.images = imgs.length;
  out.brokenImages = imgs
    .filter((i) => !(i.complete && i.naturalWidth > 0))
    .map((i) => i.currentSrc || i.src);
  out.missingAlt = imgs.filter((i) => !i.hasAttribute("alt")).map((i) => i.src);

  // Structure.
  out.title = document.title;
  out.h1Count = document.querySelectorAll("h1").length;

  // Small tap targets on touch-sized screens.
  if (innerWidth <= 768) {
    out.smallTargets = [...document.querySelectorAll("a, button, input, select, textarea, [role=button]")]
      .filter((e) => {
        const r = e.getBoundingClientRect();
        return r.width > 0 && (r.width < 44 || r.height < 44);
      })
      .slice(0, 15)
      .map((e) => `${e.tagName.toLowerCase()} "${(e.textContent || e.value || "").trim().slice(0, 30)}" ${Math.round(e.getBoundingClientRect().width)}x${Math.round(e.getBoundingClientRect().height)}`);
    out.smallInputs = [...document.querySelectorAll("input, select, textarea")]
      .filter((e) => e.getBoundingClientRect().width > 0 && parseFloat(getComputedStyle(e).fontSize) < 16)
      .map((e) => e.name || e.id || e.type);
  }

  // Contrast of common text against the nearest opaque background.
  const rgb = (c) => (c.match(/[\d.]+/g) || []).map(Number);
  const lum = ([r, g, b]) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const bgOf = (e) => {
    for (let n = e; n; n = n.parentElement) {
      const c = rgb(getComputedStyle(n).backgroundColor);
      if (c.length >= 3 && (c.length < 4 || c[3] > 0.9)) return c;
    }
    return [255, 255, 255];
  };
  out.lowContrast = [...document.querySelectorAll("p, li, a, button, label, h1, h2, h3, span")]
    .filter((e) => e.childElementCount === 0 && e.textContent.trim() && e.getBoundingClientRect().width > 0)
    .map((e) => {
      const s = getComputedStyle(e);
      const a = lum(rgb(s.color)), b = lum(bgOf(e));
      const ratio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
      const large = parseFloat(s.fontSize) >= 24 || (parseFloat(s.fontSize) >= 19 && Number(s.fontWeight) >= 700);
      return { text: e.textContent.trim().slice(0, 40), ratio: Math.round(ratio * 100) / 100, need: large ? 3 : 4.5 };
    })
    .filter((x) => x.ratio < x.need)
    .slice(0, 15);

  // Links to try: same-origin hrefs and anchors.
  const links = [...document.querySelectorAll("a[href]")].map((a) => a.getAttribute("href"));
  out.anchorsMissing = links
    .filter((h) => h.startsWith("#") && h.length > 1)
    .filter((h) => !document.getElementById(decodeURIComponent(h.slice(1))));
  out.linksToFetch = [...new Set(links.filter((h) => !h.startsWith("#") && !h.startsWith("mailto:") && !h.startsWith("tel:")))].slice(0, 50);

  return JSON.stringify(out, null, 1);
})();
