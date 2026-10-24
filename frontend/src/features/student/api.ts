import { post, query, request } from "../../shared/api";
import type {
  AssignmentDetail,
  AssignmentSummary,
  BatchStatusEntry,
  HistoryEntry,
  ItemDetail,
  Page,
  ProgressResponse,
  Receipt,
  SubmissionDetail,
} from "./types";

export function listAssignments(courseId: string) {
  return request<{ items: AssignmentSummary[] }>(
    `/courses/${courseId}/assignments`,
  );
}
export function getAssignment(assignmentId: string) {
  return request<AssignmentDetail>(`/assignments/${assignmentId}`);
}
export function getItem(itemId: string) {
  return request<ItemDetail>(`/assignment-items/${itemId}`);
}
export function submitAnswer(
  itemId: string,
  body: { content: string; language: string | null; client_request_id: string },
) {
  return post<Receipt>(`/assignment-items/${itemId}/submissions`, body);
}
export function getSubmission(submissionId: string) {
  return request<SubmissionDetail>(`/submissions/${submissionId}`);
}
export function withdrawSubmission(submissionId: string) {
  return post<Receipt>(`/submissions/${submissionId}/withdraw`);
}
export function rejudgeSubmission(
  submissionId: string,
  client_request_id: string,
) {
  return post<{ submission_id: string; job_status: string; replayed: boolean }>(
    `/submissions/${submissionId}/rejudge`,
    { client_request_id },
  );
}
export function mySubmissions(filters: {
  course_id?: string;
  assignment_id?: string;
  assignment_item_id?: string;
  language?: string;
  status?: string;
  limit?: number;
  offset?: number;
}) {
  return request<Page<HistoryEntry>>(
    `/me/submissions?${query({ ...filters })}`,
  );
}
export function myProgress(courseId: string, assignmentId?: string) {
  return request<ProgressResponse>(
    `/courses/${courseId}/my-progress?${query({ assignment_id: assignmentId })}`,
  );
}
export function batchStatus(submissionIds: string[]) {
  return post<{ items: BatchStatusEntry[] }>("/me/judge-jobs/status", {
    submission_ids: submissionIds,
  });
}
export function discoverJobs(courseId?: string, cursor?: string, limit = 100) {
  return request<{
    items: {
      submission_id: string;
      job: {
        status: string;
        phase: string;
        queue_reason: string | null;
      };
    }[];
    next_cursor: string | null;
    has_more: boolean;
    scan_high_watermark: number;
  }>(
    `/me/judge-jobs?${query({ course_id: courseId, filter: "DISCOVERY", cursor, limit })}`,
  );
}
export function activeJobs(courseId?: string, limit = 20, offset = 0) {
  return request<Page<{ submission_id: string; job: { status: string } }>>(
    `/me/judge-jobs?${query({ course_id: courseId, filter: "ACTIVE", limit, offset })}`,
  );
}
