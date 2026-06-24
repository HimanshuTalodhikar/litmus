.PHONY: build local test clean

build:
	docker build -t product-copilot-backend:latest .

local:
	docker compose up --build

test:
	pytest tests/ -v

clean:
	docker compose down -v --remove-orphans
