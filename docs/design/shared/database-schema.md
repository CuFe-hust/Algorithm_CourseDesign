# 当前数据库字段

实现版本：PostgreSQL迁移pg0007；30张业务表，另有alembic_version。由SQLAlchemy模型自动生成类型与外键。

时间戳均带时区，服务端按UTC输出；ID为有符号64位整数，API以字符串传输。JSON列使用JSONB。

## analysis_artifacts

| 字段 | PostgreSQL类型 | 可空 | 外键 |
|---|---|---|---|
| run_id | BIGINT | 否 | analysis_runs.id |
| attempt_no | INTEGER | 否 | — |
| output_hash | VARCHAR(64) | 否 | — |
| payload | JSONB | 否 | — |
| is_mock | BOOLEAN | 否 | — |
| id | BIGINT | 否 | — |
| created_at | TIMESTAMP WITH TIME ZONE | 否 | — |

## analysis_batches

| 字段 | PostgreSQL类型 | 可空 | 外键 |
|---|---|---|---|
| course_id | BIGINT | 否 | courses.id |
| assignment_id | BIGINT | 是 | assignments.id |
| created_by | BIGINT | 否 | users.id |
| mode | VARCHAR(16) | 否 | — |
| status | VARCHAR(16) | 否 | — |
| request_id | VARCHAR(64) | 否 | — |
| request_hash | VARCHAR(64) | 否 | — |
| seed | INTEGER | 否 | — |
| configuration | JSONB | 否 | — |
| events | JSONB | 否 | — |
| revision_no | INTEGER | 否 | — |
| updated_at | TIMESTAMP WITH TIME ZONE | 否 | — |
| id | BIGINT | 否 | — |
| created_at | TIMESTAMP WITH TIME ZONE | 否 | — |

## analysis_input_snapshots

| 字段 | PostgreSQL类型 | 可空 | 外键 |
|---|---|---|---|
| batch_id | BIGINT | 否 | analysis_batches.id |
| scope | VARCHAR(64) | 否 | — |
| input_hash | VARCHAR(64) | 否 | — |
| payload | JSONB | 否 | — |
| is_mock | BOOLEAN | 否 | — |
| id | BIGINT | 否 | — |
| created_at | TIMESTAMP WITH TIME ZONE | 否 | — |

## analysis_jobs

| 字段 | PostgreSQL类型 | 可空 | 外键 |
|---|---|---|---|
| submission_id | BIGINT | 否 | submissions.id |
| kind | VARCHAR(32) | 否 | — |
| status | VARCHAR(16) | 否 | — |
| parameters | JSONB | 否 | — |
| algorithm_name | VARCHAR(64) | 否 | — |
| algorithm_version | VARCHAR(32) | 否 | — |
| started_at | TIMESTAMP WITH TIME ZONE | 是 | — |
| finished_at | TIMESTAMP WITH TIME ZONE | 是 | — |
| error_message | TEXT | 是 | — |
| available_at | TIMESTAMP WITH TIME ZONE | 否 | — |
| phase | VARCHAR(16) | 否 | — |
| attempt_no | INTEGER | 否 | — |
| attempt_token | VARCHAR(64) | 是 | — |
| owner_id | VARCHAR(64) | 是 | — |
| heartbeat_at | TIMESTAMP WITH TIME ZONE | 是 | — |
| lease_expires_at | TIMESTAMP WITH TIME ZONE | 是 | — |
| recovery_cycle_no | INTEGER | 否 | — |
| automatic_retries_used | INTEGER | 否 | — |
| last_manual_retry_at | TIMESTAMP WITH TIME ZONE | 是 | — |
| updated_at | TIMESTAMP WITH TIME ZONE | 否 | — |
| id | BIGINT | 否 | — |
| created_at | TIMESTAMP WITH TIME ZONE | 否 | — |

## analysis_runs

| 字段 | PostgreSQL类型 | 可空 | 外键 |
|---|---|---|---|
| batch_id | BIGINT | 否 | analysis_batches.id |
| step_key | VARCHAR(64) | 否 | — |
| algorithm_key | VARCHAR(64) | 是 | — |
| implementation_name | VARCHAR(64) | 是 | — |
| implementation_version | VARCHAR(32) | 否 | — |
| snapshot_id | BIGINT | 是 | analysis_input_snapshots.id |
| dependencies | JSONB | 否 | — |
| dependency_refs | JSONB | 否 | — |
| status | VARCHAR(24) | 否 | — |
| business_status | VARCHAR(32) | 是 | — |
| reason | JSONB | 否 | — |
| attempt_no | INTEGER | 否 | — |
| attempt_token | VARCHAR(64) | 是 | — |
| attempt_history | JSONB | 否 | — |
| lease_expires_at | TIMESTAMP WITH TIME ZONE | 是 | — |
| started_at | TIMESTAMP WITH TIME ZONE | 是 | — |
| finished_at | TIMESTAMP WITH TIME ZONE | 是 | — |
| updated_at | TIMESTAMP WITH TIME ZONE | 否 | — |
| id | BIGINT | 否 | — |
| created_at | TIMESTAMP WITH TIME ZONE | 否 | — |

## assignment_items

| 字段 | PostgreSQL类型 | 可空 | 外键 |
|---|---|---|---|
| assignment_id | BIGINT | 否 | assignments.id |
| problem_version_id | BIGINT | 否 | problem_versions.id |
| sort_order | INTEGER | 否 | — |
| max_score | NUMERIC(8, 2) | 否 | — |
| required_reviewers | SMALLINT | 否 | — |
| test_suite_id | BIGINT | 是 | test_suites.id |
| rubric_id | BIGINT | 是 | rubrics.id |
| updated_at | TIMESTAMP WITH TIME ZONE | 否 | — |
| id | BIGINT | 否 | — |
| created_at | TIMESTAMP WITH TIME ZONE | 否 | — |

## assignment_participants

| 字段 | PostgreSQL类型 | 可空 | 外键 |
|---|---|---|---|
| assignment_id | BIGINT | 否 | assignments.id |
| student_id | BIGINT | 否 | users.id |
| class_id_at_publish | BIGINT | 否 | classes.id |
| class_name_at_publish | VARCHAR(100) | 否 | — |
| id | BIGINT | 否 | — |
| created_at | TIMESTAMP WITH TIME ZONE | 否 | — |

## assignments

| 字段 | PostgreSQL类型 | 可空 | 外键 |
|---|---|---|---|
| course_id | BIGINT | 否 | courses.id |
| title | VARCHAR(200) | 否 | — |
| description_md | TEXT | 是 | — |
| created_by | BIGINT | 否 | users.id |
| submission_deadline | TIMESTAMP WITH TIME ZONE | 否 | — |
| review_deadline | TIMESTAMP WITH TIME ZONE | 是 | — |
| submission_status | VARCHAR(16) | 否 | — |
| published_by | BIGINT | 是 | users.id |
| published_at | TIMESTAMP WITH TIME ZONE | 是 | — |
| updated_at | TIMESTAMP WITH TIME ZONE | 否 | — |
| id | BIGINT | 否 | — |
| created_at | TIMESTAMP WITH TIME ZONE | 否 | — |

## auth_sessions

| 字段 | PostgreSQL类型 | 可空 | 外键 |
|---|---|---|---|
| user_id | BIGINT | 否 | users.id |
| token_hash | VARCHAR(64) | 否 | — |
| expires_at | TIMESTAMP WITH TIME ZONE | 否 | — |
| last_active_at | TIMESTAMP WITH TIME ZONE | 否 | — |
| absolute_expires_at | TIMESTAMP WITH TIME ZONE | 否 | — |
| id | BIGINT | 否 | — |
| created_at | TIMESTAMP WITH TIME ZONE | 否 | — |

## classes

| 字段 | PostgreSQL类型 | 可空 | 外键 |
|---|---|---|---|
| class_code | VARCHAR(64) | 否 | — |
| name | VARCHAR(100) | 否 | — |
| status | VARCHAR(16) | 否 | — |
| updated_at | TIMESTAMP WITH TIME ZONE | 否 | — |
| id | BIGINT | 否 | — |
| created_at | TIMESTAMP WITH TIME ZONE | 否 | — |

## complexity_reports

| 字段 | PostgreSQL类型 | 可空 | 外键 |
|---|---|---|---|
| submission_id | BIGINT | 否 | submissions.id |
| assignment_item_id | BIGINT | 否 | assignment_items.id |
| student_id | BIGINT | 否 | users.id |
| status | VARCHAR(16) | 否 | — |
| time_class | VARCHAR(16) | 是 | — |
| space_class | VARCHAR(16) | 是 | — |
| time_confidence | VARCHAR(8) | 是 | — |
| space_confidence | VARCHAR(8) | 是 | — |
| time_source | VARCHAR(8) | 是 | — |
| language | VARCHAR(32) | 是 | — |
| static_analysis | JSONB | 否 | — |
| growth | JSONB | 否 | — |
| summary | JSONB | 否 | — |
| limitations | JSONB | 否 | — |
| implementation_name | VARCHAR(64) | 否 | — |
| implementation_version | VARCHAR(32) | 否 | — |
| requested_by | BIGINT | 否 | users.id |
| requested_at | TIMESTAMP WITH TIME ZONE | 否 | — |
| attempt_no | INTEGER | 否 | — |
| lease_expires_at | TIMESTAMP WITH TIME ZONE | 是 | — |
| started_at | TIMESTAMP WITH TIME ZONE | 是 | — |
| finished_at | TIMESTAMP WITH TIME ZONE | 是 | — |
| error_message | TEXT | 是 | — |
| updated_at | TIMESTAMP WITH TIME ZONE | 否 | — |
| id | BIGINT | 否 | — |
| created_at | TIMESTAMP WITH TIME ZONE | 否 | — |

## course_members

| 字段 | PostgreSQL类型 | 可空 | 外键 |
|---|---|---|---|
| course_id | BIGINT | 否 | courses.id |
| user_id | BIGINT | 否 | users.id |
| role | VARCHAR(16) | 否 | — |
| status | VARCHAR(16) | 否 | — |
| updated_at | TIMESTAMP WITH TIME ZONE | 否 | — |
| id | BIGINT | 否 | — |
| created_at | TIMESTAMP WITH TIME ZONE | 否 | — |

## courses

| 字段 | PostgreSQL类型 | 可空 | 外键 |
|---|---|---|---|
| code | VARCHAR(64) | 否 | — |
| name | VARCHAR(100) | 否 | — |
| term | VARCHAR(32) | 否 | — |
| created_by | BIGINT | 否 | users.id |
| status | VARCHAR(16) | 否 | — |
| updated_at | TIMESTAMP WITH TIME ZONE | 否 | — |
| id | BIGINT | 否 | — |
| created_at | TIMESTAMP WITH TIME ZONE | 否 | — |

## judge_attempts

| 字段 | PostgreSQL类型 | 可空 | 外键 |
|---|---|---|---|
| job_id | BIGINT | 否 | analysis_jobs.id |
| attempt_no | INTEGER | 否 | — |
| status | VARCHAR(16) | 否 | — |
| execution_mode | VARCHAR(16) | 是 | — |
| sandbox_ref | VARCHAR(128) | 是 | — |
| started_at | TIMESTAMP WITH TIME ZONE | 是 | — |
| finished_at | TIMESTAMP WITH TIME ZONE | 是 | — |
| failure_code | VARCHAR(32) | 是 | — |
| message | TEXT | 是 | — |
| id | BIGINT | 否 | — |
| created_at | TIMESTAMP WITH TIME ZONE | 否 | — |

## judge_results

| 字段 | PostgreSQL类型 | 可空 | 外键 |
|---|---|---|---|
| job_id | BIGINT | 否 | analysis_jobs.id |
| submission_id | BIGINT | 否 | submissions.id |
| verdict | VARCHAR(32) | 否 | — |
| is_mock | BOOLEAN | 否 | — |
| algorithm_name | VARCHAR(64) | 否 | — |
| algorithm_version | VARCHAR(32) | 否 | — |
| cpu_time_ms | INTEGER | 是 | — |
| memory_kib | INTEGER | 是 | — |
| message | TEXT | 否 | — |
| passed_cases | INTEGER | 是 | — |
| executed_cases | INTEGER | 是 | — |
| total_cases | INTEGER | 是 | — |
| attempt_id | BIGINT | 是 | judge_attempts.id |
| execution_mode | VARCHAR(16) | 是 | — |
| runtime_profile | VARCHAR(32) | 是 | — |
| measurement_status | VARCHAR(24) | 是 | — |
| compiler_message | TEXT | 是 | — |
| diagnostics_expired_at | TIMESTAMP WITH TIME ZONE | 是 | — |
| id | BIGINT | 否 | — |
| created_at | TIMESTAMP WITH TIME ZONE | 否 | — |

## judge_retry_requests

| 字段 | PostgreSQL类型 | 可空 | 外键 |
|---|---|---|---|
| submission_id | BIGINT | 否 | submissions.id |
| job_id | BIGINT | 否 | analysis_jobs.id |
| requested_by | BIGINT | 否 | users.id |
| client_request_id | VARCHAR(64) | 否 | — |
| recovery_cycle_no | INTEGER | 否 | — |
| accepted_at | TIMESTAMP WITH TIME ZONE | 否 | — |
| id | BIGINT | 否 | — |
| created_at | TIMESTAMP WITH TIME ZONE | 否 | — |

## knowledge_points

| 字段 | PostgreSQL类型 | 可空 | 外键 |
|---|---|---|---|
| course_id | BIGINT | 否 | courses.id |
| code | VARCHAR(64) | 否 | — |
| name | VARCHAR(100) | 否 | — |
| status | VARCHAR(16) | 否 | — |
| updated_at | TIMESTAMP WITH TIME ZONE | 否 | — |
| id | BIGINT | 否 | — |
| created_at | TIMESTAMP WITH TIME ZONE | 否 | — |

## problem_complexity_profiles

| 字段 | PostgreSQL类型 | 可空 | 外键 |
|---|---|---|---|
| problem_version_id | BIGINT | 否 | problem_versions.id |
| family | VARCHAR(32) | 否 | — |
| spec | JSONB | 否 | — |
| source | VARCHAR(16) | 否 | — |
| created_by | BIGINT | 是 | users.id |
| version_no | INTEGER | 否 | — |
| updated_at | TIMESTAMP WITH TIME ZONE | 否 | — |
| id | BIGINT | 否 | — |
| created_at | TIMESTAMP WITH TIME ZONE | 否 | — |

## problem_version_tags

| 字段 | PostgreSQL类型 | 可空 | 外键 |
|---|---|---|---|
| problem_version_id | BIGINT | 否 | problem_versions.id |
| knowledge_point_id | BIGINT | 否 | knowledge_points.id |
| mastery_weight | NUMERIC(8, 6) | 否 | — |
| id | BIGINT | 否 | — |
| created_at | TIMESTAMP WITH TIME ZONE | 否 | — |

## problem_versions

| 字段 | PostgreSQL类型 | 可空 | 外键 |
|---|---|---|---|
| problem_id | BIGINT | 否 | problems.id |
| version_no | INTEGER | 否 | — |
| title | VARCHAR(200) | 否 | — |
| statement_md | TEXT | 否 | — |
| answer_requirements_md | TEXT | 是 | — |
| input_spec_md | TEXT | 是 | — |
| output_spec_md | TEXT | 是 | — |
| data_constraints_md | TEXT | 是 | — |
| public_examples_md | TEXT | 是 | — |
| difficulty_level | SMALLINT | 否 | — |
| source_reference | TEXT | 是 | — |
| created_by | BIGINT | 否 | users.id |
| status | VARCHAR(16) | 否 | — |
| frozen_at | TIMESTAMP WITH TIME ZONE | 是 | — |
| updated_at | TIMESTAMP WITH TIME ZONE | 否 | — |
| id | BIGINT | 否 | — |
| created_at | TIMESTAMP WITH TIME ZONE | 否 | — |

## problems

| 字段 | PostgreSQL类型 | 可空 | 外键 |
|---|---|---|---|
| course_id | BIGINT | 否 | courses.id |
| code | VARCHAR(32) | 否 | — |
| question_type | VARCHAR(32) | 否 | — |
| created_by | BIGINT | 否 | users.id |
| status | VARCHAR(16) | 否 | — |
| updated_at | TIMESTAMP WITH TIME ZONE | 否 | — |
| id | BIGINT | 否 | — |
| created_at | TIMESTAMP WITH TIME ZONE | 否 | — |

## reference_solutions

| 字段 | PostgreSQL类型 | 可空 | 外键 |
|---|---|---|---|
| problem_version_id | BIGINT | 否 | problem_versions.id |
| language | VARCHAR(32) | 是 | — |
| content | TEXT | 否 | — |
| created_by | BIGINT | 否 | users.id |
| id | BIGINT | 否 | — |
| created_at | TIMESTAMP WITH TIME ZONE | 否 | — |

## request_rate_limits

| 字段 | PostgreSQL类型 | 可空 | 外键 |
|---|---|---|---|
| bucket | VARCHAR(32) | 否 | — |
| subject_hash | VARCHAR(64) | 否 | — |
| window_start | TIMESTAMP WITH TIME ZONE | 否 | — |
| window_seconds | INTEGER | 否 | — |
| counter | INTEGER | 否 | — |
| expires_at | TIMESTAMP WITH TIME ZONE | 否 | — |
| id | BIGINT | 否 | — |
| created_at | TIMESTAMP WITH TIME ZONE | 否 | — |

## rubric_items

| 字段 | PostgreSQL类型 | 可空 | 外键 |
|---|---|---|---|
| rubric_id | BIGINT | 否 | rubrics.id |
| name | VARCHAR(100) | 否 | — |
| description | TEXT | 否 | — |
| max_score | NUMERIC(8, 2) | 否 | — |
| sort_order | INTEGER | 否 | — |
| id | BIGINT | 否 | — |
| created_at | TIMESTAMP WITH TIME ZONE | 否 | — |

## rubrics

| 字段 | PostgreSQL类型 | 可空 | 外键 |
|---|---|---|---|
| problem_version_id | BIGINT | 否 | problem_versions.id |
| version_no | INTEGER | 否 | — |
| name | VARCHAR(100) | 否 | — |
| status | VARCHAR(16) | 否 | — |
| frozen_at | TIMESTAMP WITH TIME ZONE | 否 | — |
| id | BIGINT | 否 | — |
| created_at | TIMESTAMP WITH TIME ZONE | 否 | — |

## student_profiles

| 字段 | PostgreSQL类型 | 可空 | 外键 |
|---|---|---|---|
| user_id | BIGINT | 否 | users.id |
| class_id | BIGINT | 否 | classes.id |
| updated_at | TIMESTAMP WITH TIME ZONE | 否 | — |
| id | BIGINT | 否 | — |
| created_at | TIMESTAMP WITH TIME ZONE | 否 | — |

## submissions

| 字段 | PostgreSQL类型 | 可空 | 外键 |
|---|---|---|---|
| assignment_item_id | BIGINT | 否 | assignment_items.id |
| student_id | BIGINT | 否 | users.id |
| version_no | INTEGER | 否 | — |
| content | TEXT | 否 | — |
| language | VARCHAR(32) | 是 | — |
| submitted_at | TIMESTAMP WITH TIME ZONE | 否 | — |
| status | VARCHAR(16) | 否 | — |
| withdrawn_at | TIMESTAMP WITH TIME ZONE | 是 | — |
| client_request_id | VARCHAR(64) | 否 | — |
| id | BIGINT | 否 | — |
| created_at | TIMESTAMP WITH TIME ZONE | 否 | — |

## test_cases

| 字段 | PostgreSQL类型 | 可空 | 外键 |
|---|---|---|---|
| test_suite_id | BIGINT | 否 | test_suites.id |
| sort_order | INTEGER | 否 | — |
| input_text | TEXT | 否 | — |
| expected_output | TEXT | 否 | — |
| weight | NUMERIC(8, 6) | 否 | — |
| is_public | BOOLEAN | 否 | — |
| id | BIGINT | 否 | — |
| created_at | TIMESTAMP WITH TIME ZONE | 否 | — |

## test_suites

| 字段 | PostgreSQL类型 | 可空 | 外键 |
|---|---|---|---|
| problem_version_id | BIGINT | 否 | problem_versions.id |
| version_no | INTEGER | 否 | — |
| cpu_limit_ms | INTEGER | 否 | — |
| memory_limit_kib | INTEGER | 否 | — |
| allowed_languages | JSONB | 否 | — |
| checker | VARCHAR(32) | 否 | — |
| total_budget_ms | INTEGER | 是 | — |
| status | VARCHAR(16) | 否 | — |
| frozen_at | TIMESTAMP WITH TIME ZONE | 否 | — |
| id | BIGINT | 否 | — |
| created_at | TIMESTAMP WITH TIME ZONE | 否 | — |

## users

| 字段 | PostgreSQL类型 | 可空 | 外键 |
|---|---|---|---|
| login_name | VARCHAR(64) | 否 | — |
| student_no | VARCHAR(32) | 是 | — |
| full_name | VARCHAR(100) | 否 | — |
| password_hash | VARCHAR(255) | 是 | — |
| status | VARCHAR(16) | 否 | — |
| must_change_password | BOOLEAN | 否 | — |
| password_updated_at | TIMESTAMP WITH TIME ZONE | 是 | — |
| updated_at | TIMESTAMP WITH TIME ZONE | 否 | — |
| id | BIGINT | 否 | — |
| created_at | TIMESTAMP WITH TIME ZONE | 否 | — |
