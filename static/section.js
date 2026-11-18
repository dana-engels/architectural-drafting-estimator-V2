const projectType = document.querySelector('#project-type');
const scopeGroups = document.querySelectorAll('[data-projects]');
const result = document.getElementById('estimate-result');
const areaChecks = document.querySelectorAll('[data-area-input]');

function updateScopeFields() {
  for (const group of scopeGroups) {
    group.hidden = !group.dataset.projects.split(' ').includes(projectType.value);
  }
  for (const checkbox of areaChecks) {
    const input = checkbox.form.elements.namedItem(checkbox.dataset.areaInput);
    input.closest('label').hidden = !checkbox.checked;
  }
  for (const group of scopeGroups) {
    for (const input of group.querySelectorAll('input, select, textarea')) {
      input.disabled = Boolean(input.closest('[hidden]'));
    }
  }
}

updateScopeFields();
projectType.addEventListener('change', updateScopeFields);
for (const checkbox of areaChecks) checkbox.addEventListener('change', updateScopeFields);
projectType.form.addEventListener('input', () => {
  if (result) result.hidden = true;
});
const nextStep = document.getElementById('next-step');
const demoInquiry = document.getElementById('demo-inquiry');
nextStep?.addEventListener('click', () => {
  nextStep.hidden = true;
  document.getElementById('inquiry-step').hidden = false;
  document.getElementById('inquiry-name').focus();
});
demoInquiry?.addEventListener('submit', event => {
  event.preventDefault();
  demoInquiry.reset();
  demoInquiry.hidden = true;
  const confirmation = document.getElementById('inquiry-confirmation');
  confirmation.hidden = false;
  confirmation.focus();
});
