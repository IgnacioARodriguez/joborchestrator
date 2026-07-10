export type FieldType = "text" | "textarea" | "select" | "checkbox" | "radio" | "file" | "unknown"

export interface ExtractedField {
  field_id: string
  label: string
  type: FieldType
  required: boolean
  options: string[]
  section?: string
}

export interface ResolvedAnswer {
  field_id: string
  value?: string
  confidence: "high" | "medium" | "low" | "missing"
  needs_review: boolean
}

export interface AutofillPlan {
  job_id?: number
  fields: ExtractedField[]
  answers: ResolvedAnswer[]
  resume_variant_id?: number
}
