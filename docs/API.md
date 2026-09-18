# API overview

Base URL: `/api/v1`

## Auth
- `POST /auth/register`
- `POST /auth/login`

Both return a bearer JWT.

## Students
- `GET /students`
- `POST /students`
- `GET /students/{student_id}/mastery`

## Tutor
### `POST /tutor/start`
```json
{
  "student_id": 1,
  "problem_text": "2x + 3 = 11",
  "image_data_url": null
}
```

Returns normalized problem analysis and the first Socratic tutor turn.

### `POST /tutor/reply`
```json
{
  "session_id": 1,
  "student_message": "Em nghĩ phải trừ 3 ở hai vế."
}
```

### `POST /tutor/attempt`
Records correctness and updates mastery.

```json
{
  "student_id": 1,
  "session_id": 1,
  "skill_code": "algebra.linear_equation",
  "correct": true,
  "hint_count": 1,
  "misconception": null
}
```

## Production additions
- idempotency keys on mutation endpoints
- pagination
- refresh tokens / stronger session management
- rate limits
- audit logs for guardian/teacher actions
- media upload via object storage rather than base64 bodies
