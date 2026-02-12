(function () {
  const TEXT_PATTERNS = [
    "built with chainlit",
    "chainlit"
  ];

  const SELECTORS = [
    "footer",
    ".cl-footer",
    ".cl-powered-by",
    ".cl-branding",
    ".cl-logo-footer",
    "[data-testid='footer']",
    "[data-testid='watermark']",
    "[class*='watermark']",
    "[class*='footer']"
  ];

  function hideElement(el) {
    if (!el || el.dataset && el.dataset.brandingHidden === "true") {
      return;
    }
    el.dataset.brandingHidden = "true";
    el.style.display = "none";
    el.style.visibility = "hidden";
    el.style.opacity = "0";
    el.style.height = "0";
    el.style.width = "0";
    el.style.maxHeight = "0";
    el.style.overflow = "hidden";
    el.style.position = "absolute";
    el.style.left = "-9999px";
  }

  function hideBySelectors() {
    for (const selector of SELECTORS) {
      document.querySelectorAll(selector).forEach((el) => {
        hideElement(el);
      });
    }
  }

  function hasBrandingText(text) {
    if (!text) return false;
    const lower = text.toLowerCase();
    return TEXT_PATTERNS.some((pattern) => lower.includes(pattern));
  }

  function hideBrandingLinks() {
    const links = Array.from(document.querySelectorAll("a"));
    for (const link of links) {
      const href = (link.getAttribute("href") || "").toLowerCase();
      const text = (link.textContent || "").trim();
      if (href.includes("chainlit") || hasBrandingText(text)) {
        let target = link;
        for (let i = 0; i < 4 && target && target.parentElement; i += 1) {
          if (target.tagName.toLowerCase() === "footer") {
            break;
          }
          if ((target.className || "").toLowerCase().includes("footer")) {
            break;
          }
          if ((target.className || "").toLowerCase().includes("watermark")) {
            break;
          }
          target = target.parentElement;
        }
        hideElement(target);
      }
    }
  }

  function hideBrandingTextNodes() {
    const candidates = Array.from(document.querySelectorAll("div, span, p"));
    for (const el of candidates) {
      const text = (el.textContent || "").trim();
      if (hasBrandingText(text) && text.length <= 80) {
        hideElement(el);
      }
    }
  }

  function scrubBranding() {
    hideBySelectors();
    hideBrandingLinks();
    hideBrandingTextNodes();
  }

  function observe() {
    const observer = new MutationObserver(() => {
      scrubBranding();
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      scrubBranding();
      observe();
    });
  } else {
    scrubBranding();
    observe();
  }
})();
