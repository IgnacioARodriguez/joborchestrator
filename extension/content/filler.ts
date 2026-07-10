import type { AutofillPlan } from "../shared/types"

const REVIEW_CLASS = "job-orchestrator-needs-review"

export function applyAutofillPlan(plan: AutofillPlan): void {
  injectStyles()
  for (const answer of plan.answers) {
    const control = findControl(answer.field_id)
    if (!control) continue
    if (answer.confidence === "high" && !answer.needs_review && answer.value) {
      fillControl(control, answer.value)
    } else {
      control.classList.add(REVIEW_CLASS)
      control.setAttribute("data-job-orchestrator-review", "true")
    }
  }
}

function findControl(fieldId: string): HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement | null {
  return document.querySelector(`[name="${CSS.escape(fieldId)}"], #${CSS.escape(fieldId)}`)
}

function fillControl(control: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement, value: string): void {
  if (control instanceof HTMLSelectElement) {
    const option = [...control.options].find((item) => item.value === value || item.textContent?.trim() === value)
    if (option) control.value = option.value
  } else if (control instanceof HTMLInputElement && control.type === "checkbox") {
    control.checked = ["true", "yes", "1", control.value].includes(value.toLowerCase())
  } else if (control instanceof HTMLInputElement && control.type === "radio") {
    if (control.value === value) control.checked = true
  } else if (!(control instanceof HTMLInputElement && control.type === "file")) {
    control.value = value
  }
  control.dispatchEvent(new Event("input", { bubbles: true }))
  control.dispatchEvent(new Event("change", { bubbles: true }))
}

function injectStyles(): void {
  if (document.getElementById("job-orchestrator-extension-styles")) return
  const style = document.createElement("style")
  style.id = "job-orchestrator-extension-styles"
  style.textContent = `
    .${REVIEW_CLASS} {
      outline: 2px solid #f59e0b !important;
      outline-offset: 2px !important;
      background: #fffbeb !important;
    }
  `
  document.head.appendChild(style)
}
