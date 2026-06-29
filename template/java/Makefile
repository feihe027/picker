CURRENT_DIR := $(shell pwd)
NPROC := $(shell (nproc 2>/dev/null || sysctl -n hw.ncpu) 2>/dev/null)
JAVAC := $(shell command -v javac 2>/dev/null)
JAVA_BIN_DIR := $(if $(JAVAC),$(shell dirname "$(shell readlink -f $(JAVAC))"),)
JAVA_HOME ?= $(if $(JAVA_BIN_DIR),$(shell dirname "$(JAVA_BIN_DIR)"),)
JAVA := $(if $(JAVA_HOME),$(JAVA_HOME)/bin/java,$(shell command -v java 2>/dev/null))

ifneq ($(JAVA_BIN_DIR),)
export JAVA_HOME
export PATH := $(JAVA_BIN_DIR):$(PATH)
endif

.PHONY: all test compile clean purge copy_xspcomm

all: test clean
	@echo "All complete"

test: compile
	@echo "--------------Compile Success Test Step DUT--------------------"
	@$(JAVA) -cp {{__XSPCOMM_JAR__}}:${TARGET}-java.jar -ea com.ut.example
	@echo "--------------------------------------------------------------"

# copy xspcomm lib
copy_xspcomm_lib={{__COPY_XSPCOMM_LIB__}}
ifneq ($(copy_xspcomm_lib), true)
copy_xspcomm:
	@echo "Ignore copy xspcomm-java.jar"
else
copy_xspcomm:
	@echo "Try copy xspcomm-java.jar"
	@cp {{__XSPCOMM_JAR__}} ./
endif

compile: copy_xspcomm
	cmake . -Bbuild
	cmake --build build --config Debug --parallel $(NPROC)
	
clean:
	@rm -rf *.fst *.vcd *.fsdb *.log *.key *.a build

purge: clean
	@find . -mindepth 1 -maxdepth 1 -not -name "*.jar" -exec rm -rf {} +
	@mv ./* ../ || true
	@echo "purge complete"
	@rm -rf $(CURRENT_DIR)
