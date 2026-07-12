PORT ?= /dev/ttyUSB0

flash-01:
	cd firmware/01_blink && pio run --target upload --upload-port $(PORT)

flash-02:
	cd firmware/02_imu && pio run --target upload --upload-port $(PORT)

flash-03:
	cd firmware/03_sd && pio run --target upload --upload-port $(PORT)

flash-04:
	cd firmware/04_gps && pio run --target upload --upload-port $(PORT)

flash-05:
	cd firmware/05_full && pio run --target upload --upload-port $(PORT)

monitor:
	pio device monitor --port $(PORT) --baud 115200

clean:
	cd firmware/01_blink && pio run --target clean
	cd firmware/02_imu   && pio run --target clean
	cd firmware/03_sd    && pio run --target clean
	cd firmware/04_gps   && pio run --target clean
	cd firmware/05_full  && pio run --target clean

.PHONY: flash-01 flash-02 flash-03 flash-04 flash-05 monitor clean
