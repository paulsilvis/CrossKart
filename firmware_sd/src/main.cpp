/*
 * CrossKart Telemetry — SD Card Verification
 * Hardware: ESP32-WROOM-32 + Adafruit MicroSD Breakout (#ADA254)
 * Interface: SPI (HSPI)
 *
 * Wiring:
 *   ADA254 VCC → ESP32 3V3   *** NOT 5V — board is 3.3V only ***
 *   ADA254 GND → ESP32 GND
 *   ADA254 CLK → ESP32 GPIO 14  (HSPI SCK)
 *   ADA254 SO  → ESP32 GPIO 12  (HSPI MISO)
 *   ADA254 SI  → ESP32 GPIO 13  (HSPI MOSI)
 *   ADA254 CS  → ESP32 GPIO 15  (HSPI SS)
 *   ADA254 CD  → leave unconnected
 *
 * GPIO 12 note: strapping pin on ESP32-WROOM. If you experience boot
 * failures, swap MISO to GPIO 19 and update PIN_MISO below.
 *
 * Test stages (run automatically on boot):
 *   Stage 1 — Mount check
 *   Stage 2 — Write / read / delete roundtrip
 *   Stage 3 — Sustained write throughput (1000 CSV rows)
 *
 * Serial output: 115200 baud
 */

#include <Arduino.h>
#include <SPI.h>
#include <SD.h>

// ── Pin assignments ────────────────────────────────────────────────────────
static constexpr int PIN_CS   = 15;
static constexpr int PIN_MOSI = 13;
static constexpr int PIN_MISO = 12;
static constexpr int PIN_SCK  = 14;

// ── Test parameters ────────────────────────────────────────────────────────
static constexpr int  THROUGHPUT_ROWS  = 1000;
static constexpr long TARGET_RATE_HZ   = 50;          // rows/sec we need
static constexpr long TARGET_MS        = (THROUGHPUT_ROWS * 1000L) / TARGET_RATE_HZ;

static const char* TEST_FILE = "/ck_test.txt";

// ── Helpers ────────────────────────────────────────────────────────────────
static void pass(const char* msg) {
    Serial.print("  [PASS] ");
    Serial.println(msg);
}

static void fail(const char* msg) {
    Serial.print("  [FAIL] ");
    Serial.println(msg);
}

// ── Stage 1: mount ─────────────────────────────────────────────────────────
static bool stage1_mount() {
    Serial.println("\n== Stage 1: Mount ==");
    SPIClass spi(HSPI);
    spi.begin(PIN_SCK, PIN_MISO, PIN_MOSI, PIN_CS);

    if (!SD.begin(PIN_CS, spi, 4000000)) {
        fail("SD.begin() returned false — check wiring and VCC=3V3");
        return false;
    }

    uint8_t cardType = SD.cardType();
    const char* typeStr = "UNKNOWN";
    switch (cardType) {
        case CARD_MMC:  typeStr = "MMC";   break;
        case CARD_SD:   typeStr = "SD";    break;
        case CARD_SDHC: typeStr = "SDHC";  break;
        default: break;
    }

    uint64_t cardMB = SD.cardSize() / (1024ULL * 1024ULL);
    Serial.printf("  Card type : %s\n", typeStr);
    Serial.printf("  Card size : %llu MB\n", cardMB);

    pass("Card mounted");
    return true;
}

// ── Stage 2: write / read / delete roundtrip ──────────────────────────────
static bool stage2_roundtrip() {
    Serial.println("\n== Stage 2: Write / Read / Delete ==");

    const char* CONTENT = "CrossKart SD test — write/read/delete OK\n";

    // Write
    File f = SD.open(TEST_FILE, FILE_WRITE);
    if (!f) {
        fail("Could not open test file for writing");
        return false;
    }
    f.print(CONTENT);
    f.close();
    pass("Write OK");

    // Read back
    f = SD.open(TEST_FILE, FILE_READ);
    if (!f) {
        fail("Could not open test file for reading");
        return false;
    }
    String readback = f.readString();
    f.close();

    if (readback != String(CONTENT)) {
        fail("Readback mismatch");
        Serial.printf("  Expected : %s", CONTENT);
        Serial.printf("  Got      : %s\n", readback.c_str());
        return false;
    }
    pass("Read / verify OK");

    // Delete
    if (!SD.remove(TEST_FILE)) {
        fail("Could not delete test file");
        return false;
    }
    pass("Delete OK");
    return true;
}

// ── Stage 3: sustained write throughput ───────────────────────────────────
static bool stage3_throughput() {
    Serial.println("\n== Stage 3: Throughput ==");
    Serial.printf("  Writing %d CSV rows (need <%ld ms for %ld Hz)...\n",
                  THROUGHPUT_ROWS, TARGET_MS, TARGET_RATE_HZ);

    const char* THROUGHPUT_FILE = "/ck_bench.csv";

    File f = SD.open(THROUGHPUT_FILE, FILE_WRITE);
    if (!f) {
        fail("Could not open benchmark file");
        return false;
    }

    // Write header
    f.println("ms,ax,ay,az,gx,gy,gz,lat,lon,speed_kmh");

    uint32_t t0 = millis();
    for (int i = 0; i < THROUGHPUT_ROWS; i++) {
        // Fake but realistic CSV row — matches CrossKart schema v2 width
        f.printf("%lu,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.7f,%.7f,%.2f\n",
                 millis(),
                 (float)random(-100, 100) / 100.0f,
                 (float)random(-100, 100) / 100.0f,
                 (float)random(900, 1100) / 1000.0f,
                 (float)random(-500, 500) / 100.0f,
                 (float)random(-500, 500) / 100.0f,
                 (float)random(-500, 500) / 100.0f,
                 39.9 + (float)random(0, 1000) / 100000.0f,
                 -83.0 + (float)random(0, 1000) / 100000.0f,
                 (float)random(0, 5000) / 100.0f);
    }
    f.close();
    uint32_t elapsed = millis() - t0;

    float rowsPerSec = (THROUGHPUT_ROWS * 1000.0f) / elapsed;
    Serial.printf("  Elapsed   : %lu ms\n", elapsed);
    Serial.printf("  Throughput: %.1f rows/sec\n", rowsPerSec);

    SD.remove(THROUGHPUT_FILE);

    if (elapsed > TARGET_MS) {
        fail("Too slow — may drop rows at 50 Hz");
        Serial.printf("  Need <%ld ms, got %lu ms\n", TARGET_MS, elapsed);
        return false;
    }
    pass("Throughput OK — fast enough for 50 Hz logging");
    return true;
}

// ── Entry points ───────────────────────────────────────────────────────────
void setup() {
    Serial.begin(115200);
    delay(500);

    Serial.println("\n========================================");
    Serial.println(" CrossKart SD Verification");
    Serial.println("========================================");

    bool ok = true;
    ok = stage1_mount()     && ok;
    ok = stage2_roundtrip() && ok;
    ok = stage3_throughput() && ok;

    Serial.println("\n========================================");
    if (ok) {
        Serial.println(" ALL STAGES PASSED — SD card is ready");
    } else {
        Serial.println(" ONE OR MORE STAGES FAILED — see above");
    }
    Serial.println("========================================\n");
}

void loop() {
    // Nothing — all work done in setup()
    delay(10000);
}
