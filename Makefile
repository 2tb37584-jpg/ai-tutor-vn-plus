.PHONY: up down logs test backend-shell frontend-shell

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f

test:
	docker compose run --rm backend pytest -q

backend-shell:
	docker compose exec backend sh

frontend-shell:
	docker compose exec frontend sh
