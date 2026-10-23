(function () {
  const apiMeta = document.querySelector('meta[name="scholarship-api-base-url"]');
  const configuredBase = (apiMeta && apiMeta.content) || window.SCHOLARSHIP_API_BASE_URL || "";
  window.SCHOLARSHIP_API_BASE_URL = configuredBase;
})();
