import type { ExtractedField, FieldType } from "../shared/types"

export function isGreenhouseApplicationPage(documentRef: Document = document): boolean {
  const host = window.location.hostname.toLowerCase()
  return (
    host.includes("greenhouse.io") ||
    host.includes("greenhouse.com") ||
    Boolean(documentRef.querySelector("form[action*='greenhouse'], #application_form, form#application_form"))
  )
}

export function extractGreenhouseFields(documentRef: Document = document): ExtractedField[] {
  const controls = [
    ...documentRef.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>(
      "input, textarea, select",
    ),
  ].filter((control) => {
    const input = control as HTMLInputElement
    return !["hidden", "submit", "button"].includes(input.type)
  })

  return controls.map((control, index) => {
    const input = control as HTMLInputElement
    return {
      field_id: input.name || input.id || `field-${index}`,
      label: labelFor(control, documentRef),
      type: fieldType(control),
      required: control.required || control.getAttribute("aria-required") === "true",
      options: optionsFor(control),
      section: nearestSection(control),
    }
  })
}

function labelFor(control: HTMLElement, documentRef: Document): string {
  const id = control.getAttribute("id")
  if (id) {
    const explicit = documentRef.querySelector(`label[for="${CSS.escape(id)}"]`)
    if (explicit?.textContent?.trim()) return explicit.textContent.trim()
  }
  const wrapped = control.closest("label")
  if (wrapped?.textContent?.trim()) return wrapped.textContent.trim()
  const container = control.closest(".field, .application-question, .form-group, div")
  return container?.querySelector("label")?.textContent?.trim() || control.getAttribute("name") || "Unknown field"
}

function fieldType(control: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement): FieldType {
  if (control instanceof HTMLTextAreaElement) return "textarea"
  if (control instanceof HTMLSelectElement) return "select"
  const type = control.type
  if (type === "checkbox" || type === "radio" || type === "file") return type
  if (["text", "email", "tel", "url", "number"].includes(type)) return "text"
  return "unknown"
}

function optionsFor(control: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement): string[] {
  if (control instanceof HTMLSelectElement) {
    return [...control.options].map((option) => option.textContent?.trim() || option.value).filter(Boolean)
  }
  if (control instanceof HTMLInputElement && (control.type === "radio" || control.type === "checkbox")) {
    return [control.value].filter(Boolean)
  }
  return []
}

function nearestSection(control: HTMLElement): string | undefined {
  const section = control.closest("section, fieldset")
  return section?.querySelector("h2, h3, legend")?.textContent?.trim() || undefined
}
