# Security & child-data checklist

This is a starter, not a compliance certification.

## Before public launch
- Replace development secret.
- Use HTTPS everywhere.
- Move image upload to short-lived signed object-storage URLs.
- Add upload MIME/type inspection and size limits.
- Add rate limiting and abuse controls.
- Add account verification and secure recovery.
- Use Alembic migrations and restricted database roles.
- Add dependency/security scanning in CI.
- Define data retention and deletion behavior.
- Define guardian consent/age handling appropriate to launch jurisdictions.
- Review the model provider's current under-18 guidance and data controls.
- Conduct threat modeling for prompt injection through uploaded documents.

## Privacy design
Collect the minimum:
- display name can be a nickname
- grade
- learning interactions

Avoid by default:
- exact school
- home address
- sensitive family notes
- unnecessary date of birth

## LLM safety boundary
Never expose the OpenAI API key in the frontend.
Treat model output as untrusted application input:
- validate structured output
- escape UI rendering
- do not execute generated code
- verify math where possible
