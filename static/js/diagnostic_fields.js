(() => {
  const button = document.getElementById('diagnostic-add-field');
  if (!button) return;
  button.addEventListener('click', () => {
    const count = document.getElementById('id_fields-TOTAL_FORMS');
    const index = Number(count.value);
    if (index >= 60) { button.disabled = true; return; }
    const template = document.getElementById('diagnostic-empty-field');
    const wrapper = document.createElement('div');
    wrapper.innerHTML = template.innerHTML.replaceAll('__prefix__', String(index));
    document.getElementById('diagnostic-fields').appendChild(wrapper);
    count.value = String(index + 1);
    wrapper.querySelector('input')?.focus();
  });
})();
