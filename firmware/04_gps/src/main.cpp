// 04_gps — u-blox M10N GPS via UART at 10Hz
//
// Wiring:
//   GPS TX -> P16  (ESP32 RX2)
//   GPS RX -> P17  (ESP32 TX2)
//   GPS VCC -> 3.3V
//   GPS GND -> GND

#include <Arduino.h>
#include <TinyGPSPlus.h>

#define GPS_RX_PIN 16
#define GPS_TX_PIN 17
#define GPS_BAUD   115200

HardwareSerial gpsSerial(2);
TinyGPSPlus gps;

static const uint8_t UBX_SET_BAUD[] = {
    0xB5,0x62,0x06,0x00,0x14,0x00,
    0x01,0x00,0x00,0x00,0xD0,0x08,0x00,0x00,
    0x00,0xC2,0x01,0x00,0x07,0x00,0x07,0x00,
    0x00,0x00,0x00,0x00,0xC4,0x96
};
static const uint8_t UBX_SET_10HZ[] = {
    0xB5,0x62,0x06,0x08,0x06,0x00,
    0x64,0x00,0x01,0x00,0x01,0x00,0x7A,0x12
};

void sendUBX(const uint8_t *cmd, size_t len) {
    gpsSerial.write(cmd, len);
    gpsSerial.flush();
}

uint32_t sentenceCount = 0;
uint32_t fixCount = 0;
uint32_t lastReportMs = 0;

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("CrossKart 04_gps — starting");

    gpsSerial.begin(9600, SERIAL_8N1, GPS_RX_PIN, GPS_TX_PIN);
    delay(100);
    sendUBX(UBX_SET_BAUD, sizeof(UBX_SET_BAUD));
    delay(100);
    gpsSerial.end();
    gpsSerial.begin(GPS_BAUD, SERIAL_8N1, GPS_RX_PIN, GPS_TX_PIN);
    delay(100);
    sendUBX(UBX_SET_10HZ, sizeof(UBX_SET_10HZ));

    Serial.println("GPS configured. Waiting for fix...");
    lastReportMs = millis();
}

void loop() {
    while (gpsSerial.available()) {
        if (gps.encode(gpsSerial.read()) && gps.location.isUpdated()) {
            fixCount++;
            Serial.printf("FIX %lu: lat=%.6f lon=%.6f alt=%.1fm spd=%.1fkmh sats=%d\n",
                fixCount,
                gps.location.lat(), gps.location.lng(),
                gps.altitude.meters(), gps.speed.kmph(),
                gps.satellites.value());
        }
    }

    uint32_t now = millis();
    if (now - lastReportMs >= 5000) {
        Serial.printf("[status] chars=%lu fixes=%lu\n",
            gps.charsProcessed(), fixCount);
        if (gps.charsProcessed() < 10 && now > 5000)
            Serial.println("WARNING: no data from GPS — check wiring");
        lastReportMs = now;
    }
}
