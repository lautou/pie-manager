DB_URL = postgresql://pie:pie_password@localhost:5432/pie_db

.PHONY: up down logs migrate seed-prices

up:
	podman compose up -d

down:
	podman compose down

logs:
	podman compose logs -f backend worker

# Run DB migrations inside the backend container
migrate:
	podman compose exec backend alembic upgrade head

# Seed historical prices from yfinance (run once after fresh DB setup)
seed-prices:
	cd backend && python scripts/seed_prices.py --db-url "$(DB_URL)"
