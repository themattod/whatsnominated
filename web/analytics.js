(function initAnalytics() {
  const id = String(window.GA_MEASUREMENT_ID || '').trim();
  if (!id) {
    return;
  }

  const tagScript = document.createElement('script');
  tagScript.async = true;
  tagScript.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(id)}`;
  document.head.appendChild(tagScript);

  window.dataLayer = window.dataLayer || [];
  window.gtag = function gtag() {
    window.dataLayer.push(arguments);
  };

  window.gtag('js', new Date());
  window.gtag('config', id, {
    anonymize_ip: true,
  });
})();
