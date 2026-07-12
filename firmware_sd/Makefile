PORT ?= /dev/ttyUSB0

.PHONY: build flash monitor clean

build:
	pio run

flash:
	pio run --target upload --upload-port $(PORT)

monitor:
	pio device monitor --port $(PORT) --baud 115200

clean:
	pio run --target clean
