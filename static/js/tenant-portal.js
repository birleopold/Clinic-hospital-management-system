// Extra review for lifecycle changes. Server authorization and revision checks
// remain mandatory even if JavaScript is unavailable.
document.addEventListener('submit', event => {
  const button = event.submitter;
  if (event.defaultPrevented || !event.target.closest('.tenant-portal') || !button) return;
  const explanation = button.dataset.confirm;
  if (explanation && !window.confirm(explanation)) event.preventDefault();
});
