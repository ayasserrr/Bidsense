import { describe, expect, it } from "vitest"
import type { Job } from "../api/jobApi"
import { queueWait } from "./queueWait"

function job(overrides: Partial<Job>): Job {
  return {
    job_id: "11111111-1111-1111-1111-111111111111",
    kind: "offer_pipeline",
    status: "queued",
    offer_id: 7,
    stages: [],
    current_stage: null,
    progress_percent: 0,
    error_stage: null,
    error_message: null,
    cancel_requested: false,
    queue_position: null,
    created_at: "2026-09-18T09:00:00Z",
    enqueued_at: "2026-09-18T09:00:00Z",
    started_at: null,
    updated_at: "2026-09-18T09:00:00Z",
    finished_at: null,
    offer_persisted: false,
    ...overrides,
  } as Job
}

describe("queueWait", () => {
  it("says nothing for a job that is actually reading", () => {
    expect(queueWait(job({ status: "running", queue_position: null }))).toBeNull()
  })

  it("says nothing for a finished job", () => {
    expect(queueWait(job({ status: "succeeded" }))).toBeNull()
    expect(queueWait(job({ status: "failed" }))).toBeNull()
    expect(queueWait(job({ status: "cancelled" }))).toBeNull()
  })

  it("says nothing when there is no job yet", () => {
    expect(queueWait(null)).toBeNull()
    expect(queueWait(undefined)).toBeNull()
  })

  it("tells a waiting job it is next", () => {
    const wait = queueWait(job({ status: "queued", queue_position: 1 }))
    expect(wait?.headline).toBe("Waiting to start")
    expect(wait?.body).toContain("next")
    expect(wait?.barLabel).toBe("Waiting in the queue")
  })

  it("gives a waiting job its place in the queue", () => {
    expect(queueWait(job({ status: "queued", queue_position: 4 }))?.body).toContain("number 4")
  })

  it("still reassures when the position is not known", () => {
    const wait = queueWait(job({ status: "queued", queue_position: null }))
    expect(wait?.body).toContain("safely uploaded")
    expect(wait?.body).not.toContain("number")
  })
})
