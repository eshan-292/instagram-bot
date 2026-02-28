SHELL := /bin/bash
VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: help init deps check run dry-run generate publish engage yt-auth yt-engage

help:
	@echo "  make init       - create virtualenv"
	@echo "  make deps       - install dependencies"
	@echo "  make check      - syntax check"
	@echo "  make run        - full pipeline (generate + images + promote + publish)"
	@echo "  make dry-run    - preview next eligible post"
	@echo "  make generate   - generate + fill images, no publish"
	@echo "  make publish    - publish next eligible post only"
	@echo "  make engage     - run engagement only (like/comment/follow)"
	@echo "  make yt-auth    - one-time YouTube OAuth2 setup"
	@echo "  make yt-engage  - run YouTube engagement only"

init:
	python3 -m venv $(VENV)

deps:
	$(PIP) install -r requirements.txt

check:
	$(PYTHON) -m py_compile instagram_influencer/config.py \
		instagram_influencer/post_queue.py \
		instagram_influencer/generator.py \
		instagram_influencer/image.py \
		instagram_influencer/audio.py \
		instagram_influencer/video.py \
		instagram_influencer/rate_limiter.py \
		instagram_influencer/engagement.py \
		instagram_influencer/publisher.py \
		instagram_influencer/youtube_publisher.py \
		instagram_influencer/youtube_engagement.py \
		instagram_influencer/orchestrator.py

run:
	$(PYTHON) instagram_influencer/orchestrator.py --verbose

dry-run:
	$(PYTHON) instagram_influencer/orchestrator.py --dry-run

generate:
	$(PYTHON) instagram_influencer/orchestrator.py --no-publish --verbose

publish:
	$(PYTHON) instagram_influencer/orchestrator.py --no-generate --verbose

engage:
	$(PYTHON) instagram_influencer/orchestrator.py --no-generate --no-publish --verbose

yt-auth:
	$(PYTHON) instagram_influencer/youtube_publisher.py --auth

yt-engage:
	$(PYTHON) instagram_influencer/orchestrator.py --no-generate --no-publish --session yt_full --verbose
