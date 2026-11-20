/* Resize sandboxed HTML reports to avoid a nested scroll bar.
   The report stays in an iframe with scripts, forms and navigation disabled.
   allow-same-origin permits the parent page to measure its content height,
   but DOES NOT permit the report to execute scripts. */
(() => {
  'use strict';
  const attached = new WeakSet();
  function attach(frame) {
    if (!frame || attached.has(frame)) return;
    attached.add(frame);
    frame.setAttribute('sandbox', 'allow-same-origin');
    frame.setAttribute('scrolling', 'no');
    frame.style.overflow = 'hidden';
    let observer = null;
    let observedDocument = null;
    const measure = () => {
      try {
        const doc = frame.contentDocument;
        if (!doc || !doc.body || !doc.documentElement) return;
        if (doc !== observedDocument) {
          observer?.disconnect();
          observedDocument = doc;
          doc.body.style.overflow = 'hidden';
          doc.documentElement.style.overflow = 'hidden';
          if (typeof ResizeObserver !== 'undefined') {
            observer = new ResizeObserver(() => requestAnimationFrame(measure));
            observer.observe(doc.documentElement);
            observer.observe(doc.body);
          }
          doc.addEventListener('toggle', () => requestAnimationFrame(measure), true);
          for (const img of doc.images) img.addEventListener('load', measure, { once: true });
        }
        const height = Math.max(
          doc.documentElement.scrollHeight, doc.body.scrollHeight,
          doc.documentElement.offsetHeight, doc.body.offsetHeight,
          320
        );
        if (Number.isFinite(height) && height < 120000) {
          frame.style.height = Math.ceil(height + 8) + 'px';
        }
      } catch (_) {
        // The parent cannot measure an inaccessible document; keep fallback.
      }
    };
    frame.addEventListener('load', () => {
      observedDocument = null;
      requestAnimationFrame(measure);
    });
    frame.style.height = '720px'; // Fallback if a browser blocks measurement.
  }
  window.StrokeSenseAutoReportFrame = { attach };
})();
