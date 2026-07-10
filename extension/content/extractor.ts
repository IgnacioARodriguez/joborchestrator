import { extractGreenhouseFields } from "../adapters/greenhouse"
import type { ExtractedField } from "../shared/types"

export function extractFields(): ExtractedField[] {
  return extractGreenhouseFields(document)
}
