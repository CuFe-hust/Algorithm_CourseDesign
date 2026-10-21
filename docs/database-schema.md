# 数据库实际结构（自动从SQLAlchemy模型生成）

实现版本：迁移0002；共21张业务表，另有alembic_version。

业务含义与数据流见contracts/foundation-v1.md。此表为实际实现快照；后续修改模型后需新增迁移并重新生成。

## classes

| 字段 | MySQL类型 | 可空 | 外键 |
|---|---|---|---|
| class_code | VARCHAR(64) | 否 |  |
| name | VARCHAR(100) | 否 |  |
| status | VARCHAR(16) | 否 |  |
| updated_at | DATETIME(6) | 否 |  |
| id | BIGINT UNSIGNED | 否 |  |
| created_at | DATETIME(6) | 否 |  |

约束：uq_classes_class_code；pk_classes

## users

| 字段 | MySQL类型 | 可空 | 外键 |
|---|---|---|---|
| login_name | VARCHAR(64) | 否 |  |
| student_no | VARCHAR(32) | 是 |  |
| full_name | VARCHAR(100) | 否 |  |
| password_hash | VARCHAR(255) | 是 |  |
| status | VARCHAR(16) | 否 |  |
| updated_at | DATETIME(6) | 否 |  |
| id | BIGINT UNSIGNED | 否 |  |
| created_at | DATETIME(6) | 否 |  |

约束：pk_users；uq_users_login_name；uq_users_student_no；ck_user_status

## auth_sessions

| 字段 | MySQL类型 | 可空 | 外键 |
|---|---|---|---|
| user_id | BIGINT UNSIGNED | 否 | users.id |
| token_hash | VARCHAR(64) | 否 |  |
| expires_at | DATETIME(6) | 否 |  |
| id | BIGINT UNSIGNED | 否 |  |
| created_at | DATETIME(6) | 否 |  |

约束：pk_auth_sessions；uq_auth_sessions_token_hash；fk_auth_sessions_user_id_users

## courses

| 字段 | MySQL类型 | 可空 | 外键 |
|---|---|---|---|
| code | VARCHAR(64) | 否 |  |
| name | VARCHAR(100) | 否 |  |
| term | VARCHAR(32) | 否 |  |
| created_by | BIGINT UNSIGNED | 否 | users.id |
| status | VARCHAR(16) | 否 |  |
| updated_at | DATETIME(6) | 否 |  |
| id | BIGINT UNSIGNED | 否 |  |
| created_at | DATETIME(6) | 否 |  |

约束：uq_courses_code；fk_courses_created_by_users；pk_courses

## student_profiles

| 字段 | MySQL类型 | 可空 | 外键 |
|---|---|---|---|
| user_id | BIGINT UNSIGNED | 否 | users.id |
| class_id | BIGINT UNSIGNED | 否 | classes.id |
| updated_at | DATETIME(6) | 否 |  |
| id | BIGINT UNSIGNED | 否 |  |
| created_at | DATETIME(6) | 否 |  |

约束：fk_student_profiles_class_id_classes；fk_student_profiles_user_id_users；pk_student_profiles；uq_student_profiles_user_id

## assignments

| 字段 | MySQL类型 | 可空 | 外键 |
|---|---|---|---|
| course_id | BIGINT UNSIGNED | 否 | courses.id |
| title | VARCHAR(200) | 否 |  |
| description_md | TEXT | 是 |  |
| created_by | BIGINT UNSIGNED | 否 | users.id |
| submission_deadline | DATETIME(6) | 否 |  |
| review_deadline | DATETIME(6) | 是 |  |
| submission_status | VARCHAR(16) | 否 |  |
| published_by | BIGINT UNSIGNED | 是 | users.id |
| published_at | DATETIME(6) | 是 |  |
| updated_at | DATETIME(6) | 否 |  |
| id | BIGINT UNSIGNED | 否 |  |
| created_at | DATETIME(6) | 否 |  |

约束：ck_assignment_deadlines；pk_assignments；fk_assignments_created_by_users；ck_assignment_status；ck_assignment_published；fk_assignments_published_by_users；fk_assignments_course_id_courses

## course_members

| 字段 | MySQL类型 | 可空 | 外键 |
|---|---|---|---|
| course_id | BIGINT UNSIGNED | 否 | courses.id |
| user_id | BIGINT UNSIGNED | 否 | users.id |
| role | VARCHAR(16) | 否 |  |
| status | VARCHAR(16) | 否 |  |
| updated_at | DATETIME(6) | 否 |  |
| id | BIGINT UNSIGNED | 否 |  |
| created_at | DATETIME(6) | 否 |  |

约束：ck_member_role；uq_course_members_course_id_user_id；pk_course_members；fk_course_members_user_id_users；fk_course_members_course_id_courses

## knowledge_points

| 字段 | MySQL类型 | 可空 | 外键 |
|---|---|---|---|
| course_id | BIGINT UNSIGNED | 否 | courses.id |
| code | VARCHAR(64) | 否 |  |
| name | VARCHAR(100) | 否 |  |
| status | VARCHAR(16) | 否 |  |
| updated_at | DATETIME(6) | 否 |  |
| id | BIGINT UNSIGNED | 否 |  |
| created_at | DATETIME(6) | 否 |  |

约束：uq_knowledge_points_course_id_code；pk_knowledge_points；fk_knowledge_points_course_id_courses

## problems

| 字段 | MySQL类型 | 可空 | 外键 |
|---|---|---|---|
| course_id | BIGINT UNSIGNED | 否 | courses.id |
| code | VARCHAR(32) | 否 |  |
| question_type | VARCHAR(32) | 否 |  |
| created_by | BIGINT UNSIGNED | 否 | users.id |
| status | VARCHAR(16) | 否 |  |
| updated_at | DATETIME(6) | 否 |  |
| id | BIGINT UNSIGNED | 否 |  |
| created_at | DATETIME(6) | 否 |  |

约束：uq_problems_course_id_code；pk_problems；fk_problems_created_by_users；ck_problem_type；fk_problems_course_id_courses

## assignment_participants

| 字段 | MySQL类型 | 可空 | 外键 |
|---|---|---|---|
| assignment_id | BIGINT UNSIGNED | 否 | assignments.id |
| student_id | BIGINT UNSIGNED | 否 | users.id |
| class_id_at_publish | BIGINT UNSIGNED | 否 | classes.id |
| class_name_at_publish | VARCHAR(100) | 否 |  |
| id | BIGINT UNSIGNED | 否 |  |
| created_at | DATETIME(6) | 否 |  |

约束：fk_assignment_participants_class_id_at_publish_classes；uq_assignment_participants_assignment_id_student_id；fk_assignment_participants_assignment_id_assignments；pk_assignment_participants；fk_assignment_participants_student_id_users

## problem_versions

| 字段 | MySQL类型 | 可空 | 外键 |
|---|---|---|---|
| problem_id | BIGINT UNSIGNED | 否 | problems.id |
| version_no | INTEGER UNSIGNED | 否 |  |
| title | VARCHAR(200) | 否 |  |
| statement_md | LONGTEXT | 否 |  |
| answer_requirements_md | TEXT | 是 |  |
| input_spec_md | TEXT | 是 |  |
| output_spec_md | TEXT | 是 |  |
| data_constraints_md | TEXT | 是 |  |
| public_examples_md | TEXT | 是 |  |
| difficulty_level | TINYINT UNSIGNED | 否 |  |
| source_reference | TEXT | 是 |  |
| created_by | BIGINT UNSIGNED | 否 | users.id |
| status | VARCHAR(16) | 否 |  |
| frozen_at | DATETIME(6) | 是 |  |
| updated_at | DATETIME(6) | 否 |  |
| id | BIGINT UNSIGNED | 否 |  |
| created_at | DATETIME(6) | 否 |  |

约束：ck_problem_difficulty；fk_problem_versions_created_by_users；ck_problem_frozen；uq_problem_versions_problem_id_version_no；fk_problem_versions_problem_id_problems；ck_problem_version_positive；pk_problem_versions

## problem_version_tags

| 字段 | MySQL类型 | 可空 | 外键 |
|---|---|---|---|
| problem_version_id | BIGINT UNSIGNED | 否 | problem_versions.id |
| knowledge_point_id | BIGINT UNSIGNED | 否 | knowledge_points.id |
| mastery_weight | NUMERIC(8, 6) | 否 |  |
| id | BIGINT UNSIGNED | 否 |  |
| created_at | DATETIME(6) | 否 |  |

约束：fk_problem_version_tags_knowledge_point_id_knowledge_points；pk_problem_version_tags；uq_problem_version_tags_problem_version_id_knowledge_point_id；ck_tag_weight；fk_problem_version_tags_problem_version_id_problem_versions

## reference_solutions

| 字段 | MySQL类型 | 可空 | 外键 |
|---|---|---|---|
| problem_version_id | BIGINT UNSIGNED | 否 | problem_versions.id |
| language | VARCHAR(32) | 是 |  |
| content | LONGTEXT | 否 |  |
| created_by | BIGINT UNSIGNED | 否 | users.id |
| id | BIGINT UNSIGNED | 否 |  |
| created_at | DATETIME(6) | 否 |  |

约束：fk_reference_solutions_created_by_users；pk_reference_solutions；fk_reference_solutions_problem_version_id_problem_versions

## rubrics

| 字段 | MySQL类型 | 可空 | 外键 |
|---|---|---|---|
| problem_version_id | BIGINT UNSIGNED | 否 | problem_versions.id |
| version_no | INTEGER UNSIGNED | 否 |  |
| name | VARCHAR(100) | 否 |  |
| status | VARCHAR(16) | 否 |  |
| frozen_at | DATETIME(6) | 否 |  |
| id | BIGINT UNSIGNED | 否 |  |
| created_at | DATETIME(6) | 否 |  |

约束：ck_rubric_frozen；uq_rubrics_problem_version_id_version_no；fk_rubrics_problem_version_id_problem_versions；pk_rubrics

## test_suites

| 字段 | MySQL类型 | 可空 | 外键 |
|---|---|---|---|
| problem_version_id | BIGINT UNSIGNED | 否 | problem_versions.id |
| version_no | INTEGER UNSIGNED | 否 |  |
| cpu_limit_ms | INTEGER UNSIGNED | 否 |  |
| memory_limit_kib | INTEGER UNSIGNED | 否 |  |
| allowed_languages | JSON | 否 |  |
| checker | VARCHAR(32) | 否 |  |
| status | VARCHAR(16) | 否 |  |
| frozen_at | DATETIME(6) | 否 |  |
| id | BIGINT UNSIGNED | 否 |  |
| created_at | DATETIME(6) | 否 |  |

约束：fk_test_suites_problem_version_id_problem_versions；ck_suite_resources；ck_suite_frozen；pk_test_suites；ck_suite_version_positive；uq_test_suites_problem_version_id_version_no

## assignment_items

| 字段 | MySQL类型 | 可空 | 外键 |
|---|---|---|---|
| assignment_id | BIGINT UNSIGNED | 否 | assignments.id |
| problem_version_id | BIGINT UNSIGNED | 否 | problem_versions.id |
| sort_order | INTEGER UNSIGNED | 否 |  |
| max_score | NUMERIC(8, 2) | 否 |  |
| score_weight | NUMERIC(8, 6) | 否 |  |
| required_reviewers | SMALLINT UNSIGNED | 否 |  |
| test_suite_id | BIGINT UNSIGNED | 是 | test_suites.id |
| rubric_id | BIGINT UNSIGNED | 是 | rubrics.id |
| updated_at | DATETIME(6) | 否 |  |
| id | BIGINT UNSIGNED | 否 |  |
| created_at | DATETIME(6) | 否 |  |

约束：ck_item_scores；pk_assignment_items；uq_assignment_items_assignment_id_problem_version_id；fk_assignment_items_test_suite_id_test_suites；fk_assignment_items_assignment_id_assignments；ck_item_config；uq_assignment_items_assignment_id_sort_order；fk_assignment_items_rubric_id_rubrics；fk_assignment_items_problem_version_id_problem_versions

## rubric_items

| 字段 | MySQL类型 | 可空 | 外键 |
|---|---|---|---|
| rubric_id | BIGINT UNSIGNED | 否 | rubrics.id |
| name | VARCHAR(100) | 否 |  |
| description | TEXT | 否 |  |
| max_score | NUMERIC(8, 2) | 否 |  |
| sort_order | INTEGER UNSIGNED | 否 |  |
| id | BIGINT UNSIGNED | 否 |  |
| created_at | DATETIME(6) | 否 |  |

约束：pk_rubric_items；ck_rubric_score；uq_rubric_items_rubric_id_sort_order；fk_rubric_items_rubric_id_rubrics

## test_cases

| 字段 | MySQL类型 | 可空 | 外键 |
|---|---|---|---|
| test_suite_id | BIGINT UNSIGNED | 否 | test_suites.id |
| sort_order | INTEGER UNSIGNED | 否 |  |
| input_text | LONGTEXT | 否 |  |
| expected_output | LONGTEXT | 否 |  |
| weight | NUMERIC(8, 6) | 否 |  |
| is_public | BOOL | 否 |  |
| id | BIGINT UNSIGNED | 否 |  |
| created_at | DATETIME(6) | 否 |  |

约束：pk_test_cases；uq_test_cases_test_suite_id_sort_order；ck_case_weight；fk_test_cases_test_suite_id_test_suites

## submissions

| 字段 | MySQL类型 | 可空 | 外键 |
|---|---|---|---|
| assignment_item_id | BIGINT UNSIGNED | 否 | assignment_items.id |
| student_id | BIGINT UNSIGNED | 否 | users.id |
| version_no | INTEGER UNSIGNED | 否 |  |
| content | LONGTEXT | 否 |  |
| language | VARCHAR(32) | 是 |  |
| submitted_at | DATETIME(6) | 否 |  |
| status | VARCHAR(16) | 否 |  |
| withdrawn_at | DATETIME(6) | 是 |  |
| client_request_id | VARCHAR(64) COLLATE utf8mb4_bin | 否 |  |
| id | BIGINT UNSIGNED | 否 |  |
| created_at | DATETIME(6) | 否 |  |

约束：ck_submission_version；fk_submissions_assignment_item_id_assignment_items；ck_submission_status；uq_submissions_assignment_item_id_student_id_version_no；pk_submissions；fk_submissions_student_id_users；uq_submissions_student_id_client_request_id

## analysis_jobs

| 字段 | MySQL类型 | 可空 | 外键 |
|---|---|---|---|
| submission_id | BIGINT UNSIGNED | 否 | submissions.id |
| kind | VARCHAR(32) | 否 |  |
| status | VARCHAR(16) | 否 |  |
| parameters | JSON | 否 |  |
| algorithm_name | VARCHAR(64) | 否 |  |
| algorithm_version | VARCHAR(32) | 否 |  |
| started_at | DATETIME(6) | 是 |  |
| finished_at | DATETIME(6) | 是 |  |
| error_message | TEXT | 是 |  |
| updated_at | DATETIME(6) | 否 |  |
| id | BIGINT UNSIGNED | 否 |  |
| created_at | DATETIME(6) | 否 |  |

约束：ck_job_status；uq_analysis_jobs_submission_id_kind；fk_analysis_jobs_submission_id_submissions；pk_analysis_jobs

## judge_results

| 字段 | MySQL类型 | 可空 | 外键 |
|---|---|---|---|
| job_id | BIGINT UNSIGNED | 否 | analysis_jobs.id |
| submission_id | BIGINT UNSIGNED | 否 | submissions.id |
| verdict | VARCHAR(32) | 否 |  |
| is_mock | BOOL | 否 |  |
| algorithm_name | VARCHAR(64) | 否 |  |
| algorithm_version | VARCHAR(32) | 否 |  |
| cpu_time_ms | INTEGER UNSIGNED | 是 |  |
| memory_kib | INTEGER UNSIGNED | 是 |  |
| message | TEXT | 否 |  |
| id | BIGINT UNSIGNED | 否 |  |
| created_at | DATETIME(6) | 否 |  |

约束：fk_judge_results_submission_id_submissions；uq_judge_results_submission_id；ck_mock_resources；uq_judge_results_job_id；fk_judge_results_job_id_analysis_jobs；pk_judge_results
