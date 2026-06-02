# CrossKart Firmware — Phase 1 IMU
# Usage:
#   make build      compile
#   make flash      compile + upload
#   make monitor    open serial monitor
#   make fm         flash + monitor (most common during dev)
#   make viz        run the host-side Python visualizer
#   make clean      clean build artifacts

PORT ?= $(shell python3 -c "\
import serial.tools.list_ports, sys; \
ports = [p.device for p in serial.tools.list_ports.comports() \
         if any(k in (p.description or '').lower() for k in \
                ['cp210','ch340','ch341','ftdi','uart'])]; \
print(ports[0] if ports else '')" 2>/dev/null)

.PHONY: build flash monitor fm viz clean

build:
	pio run

flash:
	pio run --target upload

monitor:
	pio device monitor --baud 115200

fm: flash monitor

viz:
	@echo "Starting visualizer (Ctrl-C to quit)..."
	python3 tools/visualizer.py $(PORT)

clean:
	pio run --target clean

# Print detected port
port:
	@echo "Detected port: $(PORT)"
