SHELL:=bash
.ONESHELL:
.SHELLFLAGS:=-eu -o pipefail -c
.DELETE_ON_ERROR:
MAKEFLAGS += --warn-undefined-variables
MAKEFLAGS += --no-builtin-rules

DRY_RUN?=
YARN=yarn
YARN_RUN=$(YARN) run
NODE_BIN=node_modules/.bin
WEBPACK=$(NODE_BIN)/webpack
NODE_ENV_VALUE?=development
CACHE_DIR=.cache
SENTINEL_DIR=$(CACHE_DIR)/sentinels

DOCKER=docker
DOCKER_COMPOSE=docker-compose
CONTAINER_NAME?=hold

GFIND=$(shell command -v gfind)
FIND=$(or $(GFIND),$(GFIND),find)
LS_FILES=$(shell git ls-files) $(shell git ls-files --others --exclude-standard)
LS_PYTHON=$(filter %.py,$(sort $(LS_FILES)))
SENTINEL_FILE=$(SENTINEL_DIR)/$(1).last-run

ISORT_SENTINEL=$(call SENTINEL_FILE,isort)
FLAKE8_SENTINEL=$(call SENTINEL_FILE,flake8)

VERSION_FILE=holdmypics/__version__.py
VERSION_FILE_CTS=$(file < $(VERSION_FILE))
VERSION=$(shell echo $(lastword $(VERSION_FILE_CTS)))
VERSION_TAG=v$(VERSION)

MODE?=dev
CONFIG_DIR=config
DOCKERFILE=$(CONFIG_DIR)/$(MODE)/Dockerfile
DOCKER_TAG=holdmypics-$(MODE):$(VERSION_TAG)
BUILD_CPU_SHARES?=512
COMPILE_OPTS?=--port 8080 -y

TEMPLATE=$(CONFIG_DIR)/Dockerfile.template
COMPILE_OUT=$(CONFIG_DIR)/dev/Dockerfile $(CONFIG_DIR)/prod/Dockerfile

.PHONY: compile compose dbuilddev dbuildprod docker docker-build run stop version-tag \
	lint isort flake8 clean

compile: $(COMPILE_OUT)

$(COMPILE_OUT): $(TEMPLATE)
	flask generate-dockerfiles $(COMPILE_OPTS)

dbuilddev: MODE=dev
dbuilddev: docker-build

dbuildprod: MODE=prod
dbuildprod: docker-build

docker-build: DOCKER_ARGS=build -f $(DOCKERFILE) -c $(BUILD_CPU_SHARES) --tag=$(DOCKER_TAG) -o out .
docker-build: compile docker

rundev: MODE=dev
rundev: DOCKER_ARGS=run --publish 8080:8080 --detach --name=$(CONTAINER_NAME) $(DOCKER_TAG)
rundev: docker

stop: MODE=dev
stop: DOCKER_ARGS=stop $(CONTAINER_NAME)

docker:
	$(DOCKER) $(DOCKER_ARGS)

compose:
	$(DOCKER_COMPOSE) $(COMPOSE_ARGS)

dev: NODE_ENV_VALUE=development
dev: webpack

prod: NODE_ENV_VALUE=production
prod: webpack

webpack: export NODE_ENV=$(NODE_ENV_VALUE)
webpack:
	@$(WEBPACK) --config webpack.config.ts --progress

version-tag:
ifeq ($(strip $(DRY_RUN)),)
	@git tag $(VERSION_TAG) -m $(VERSION_TAG)
else
	@echo $(VERSION_TAG)
endif

lint: isort flake8

isort: $(SENTINEL_DIR) $(ISORT_SENTINEL)
flake8: $(SENTINEL_DIR) $(FLAKE8_SENTINEL)

$(ISORT_SENTINEL): $(LS_PYTHON)
	@echo "Running isort on $(words $?) file(s)"
	isort --check-only $?
	date > $@

$(FLAKE8_SENTINEL): $(LS_PYTHON)
	@echo "Running flake8 on $(words $?) file(s)"
	flake8 $?
	date > $@


$(SENTINEL_DIR):
	mkdir $@

clean:
	-rm -rf $(SENTINEL_DIR)
