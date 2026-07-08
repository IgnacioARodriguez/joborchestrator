import { MOCK_JOBS } from "./mock-data"

export const SAMPLE_IMPORT_JSON = JSON.stringify(
  MOCK_JOBS.slice(0, 2).map((job, index) => ({
    ...job,
    id: `sample_import_${index + 1}`,
    pipeline_status: "new",
    review: {
      ...job.review,
      applied_at: null,
    },
  })),
  null,
  2,
)
