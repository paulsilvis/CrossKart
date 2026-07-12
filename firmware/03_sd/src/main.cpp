// 03_sd — SD card write throughput test
//
// Wiring:
//   SD MOSI -> P23
//   SD MISO -> P19
//   SD SCK  -> P18
//   SD CS   -> P15
//   SD VCC  -> 3.3V
//   SD GND  -> GND

#include <Arduino.h>
#include <SPI.h>
#include <SD.h>

#define SD_CS 15
#define TEST_ROWS     1000
#define TEST_FILENAME "/ck_sdtest.csv"

void runWriteTest();
void runReadTest();

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("CrossKart 03_sd — starting");

    SPI.begin();

    if (!SD.begin(SD_CS)) {
        Serial.println("ERROR: SD card not found. Check wiring.");
        while (1) delay(1000);
    }

    uint64_t cardSize = SD.cardSize() / (1024 * 1024);
    Serial.printf("SD card found. Size: %llu MB\n", cardSize);

    runWriteTest();
    runReadTest();
    Serial.println("SD test complete.");
}

void loop() {}

void runWriteTest() {
    Serial.printf("Writing %d rows to %s ...\n", TEST_ROWS, TEST_FILENAME);
    if (SD.exists(TEST_FILENAME)) SD.remove(TEST_FILENAME);

    File f = SD.open(TEST_FILENAME, FILE_WRITE);
    if (!f) { Serial.println("ERROR: could not open file for writing"); return; }

    f.println("seq,ts_ms,qW,qX,qY,qZ,aX,aY,aZ");

    uint32_t t0 = millis();
    uint32_t errors = 0;
    for (int i = 0; i < TEST_ROWS; i++) {
        size_t w = f.printf("%d,%lu,%.4f,%.4f,%.4f,%.4f,%.3f,%.3f,%.3f\n",
            i, millis(), 1.0f, 0.0f, 0.0f, 0.0f, 0.1f*i, 0.0f, 9.81f);
        if (w == 0) errors++;
    }
    f.close();
    uint32_t elapsed = millis() - t0;

    File check = SD.open(TEST_FILENAME, FILE_READ);
    size_t fileSize = check.size();
    check.close();

    Serial.printf("Write: %d rows in %lu ms (%.1f rows/sec, %.1f KB/sec)\n",
        TEST_ROWS, elapsed, TEST_ROWS*1000.0f/elapsed, fileSize/(float)elapsed);
    if (errors) Serial.printf("WARNING: %lu write errors\n", errors);
}

void runReadTest() {
    Serial.printf("Reading back %s ...\n", TEST_FILENAME);
    File f = SD.open(TEST_FILENAME, FILE_READ);
    if (!f) { Serial.println("ERROR: could not open file for reading"); return; }

    uint32_t t0 = millis();
    uint32_t lines = 0;
    while (f.available()) { f.readStringUntil('\n'); lines++; }
    f.close();
    uint32_t elapsed = millis() - t0;

    Serial.printf("Read: %lu lines in %lu ms\n", lines, elapsed);
    Serial.printf("Row count: %s\n", ((int)lines-1 == TEST_ROWS) ? "PASS" : "FAIL");
}
