# firmware_sd — CrossKart SD Card Verification

Standalone PlatformIO sketch that verifies the Adafruit MicroSD breakout
(ADA254) is wired correctly and fast enough for 50 Hz logging.

## Wiring

| ADA254 Pin | ESP32 GPIO | Notes                        |
|------------|------------|------------------------------|
| VCC        | 3V3        | **NOT 5V** — board is 3V only |
| GND        | GND        |                              |
| CLK        | GPIO 14    | HSPI SCK                     |
| SO (MISO)  | GPIO 12    | HSPI MISO (see note below)   |
| SI (MOSI)  | GPIO 13    | HSPI MOSI                    |
| CS         | GPIO 15    | HSPI SS                      |
| CD         | —          | Leave unconnected             |

**GPIO 12 note:** This is a strapping pin on ESP32-WROOM. If the board
fails to boot after wiring, move MISO to GPIO 19 and update `PIN_MISO`
in `src/main.cpp`.

## Test stages

| Stage | What it checks |
|-------|----------------|
| 1 | Card mounts, reports type and size |
| 2 | Write → read → delete roundtrip |
| 3 | 1000 CSV rows; must complete in <20 s for ≥50 Hz logging |

## Usage

```bash
make flash PORT=/dev/ttyUSB0
make monitor PORT=/dev/ttyUSB0
```

Expected output on success:

```
========================================
 CrossKart SD Verification
========================================

== Stage 1: Mount ==
  Card type : SDHC
  Card size : 15193 MB
  [PASS] Card mounted

== Stage 2: Write / Read / Delete ==
  [PASS] Write OK
  [PASS] Read / verify OK
  [PASS] Delete OK

== Stage 3: Throughput ==
  Writing 1000 CSV rows (need <20000 ms for 50 Hz)...
  Elapsed   : NNN ms
  Throughput: NNN.N rows/sec
  [PASS] Throughput OK — fast enough for 50 Hz logging

========================================
 ALL STAGES PASSED — SD card is ready
========================================
```
