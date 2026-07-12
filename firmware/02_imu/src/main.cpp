// 02_imu — BNO085 via SPI using Adafruit BNO08x library
//
// GY-BNO08x wiring:
//   VCC -> 3.3V
//   GND -> GND
//   SCL -> P18  (SPI SCK)
//   SDA -> P13  (SPI MOSI — P23 has boot-time issues)
//   ADO -> P19  (SPI MISO)
//   CS  -> P5
//   INT -> P4
//   RST -> P25
//   PS0 -> GND
//   PS1 -> GND

#include <Arduino.h>
#include <SPI.h>
#include <Adafruit_BNO08x.h>

#define BNO_CS   5
#define BNO_INT  4
#define BNO_RST  25

#define SPI_SCK  18
#define SPI_MOSI 13
#define SPI_MISO 19

Adafruit_BNO08x imu(BNO_RST);
sh2_SensorValue_t sensorValue;

uint32_t sampleCount = 0;
uint32_t lastReportMs = 0;

void setReports() {
    if (!imu.enableReport(SH2_ROTATION_VECTOR))
        Serial.println("ERROR: could not enable rotation vector");
    if (!imu.enableReport(SH2_LINEAR_ACCELERATION))
        Serial.println("ERROR: could not enable linear acceleration");
}

void setup() {
    Serial.begin(115200);
    delay(1000);
    Serial.println();
    Serial.println("CrossKart 02_imu — starting");
    Serial.flush();

    Serial.println("Step 1: manual RST pulse");
    Serial.flush();
    pinMode(BNO_RST, OUTPUT);
    digitalWrite(BNO_RST, HIGH);
    delay(10);
    digitalWrite(BNO_RST, LOW);
    delay(10);
    digitalWrite(BNO_RST, HIGH);
    delay(500);

    pinMode(BNO_INT, INPUT);
    Serial.printf("INT after reset: %d\n", digitalRead(BNO_INT));
    Serial.flush();

    Serial.println("Step 2: SPI.begin()");
    Serial.flush();
    SPI.begin(SPI_SCK, SPI_MISO, SPI_MOSI);
    delay(100);

    Serial.println("Step 3: imu.begin_SPI()");
    Serial.flush();

    if (!imu.begin_SPI(BNO_CS, BNO_INT, &SPI)) {
        Serial.println("ERROR: BNO085 not found. Check wiring.");
        Serial.flush();
        while (1) delay(1000);
    }

    Serial.println("BNO085 found!");
    Serial.flush();

    setReports();
    Serial.println("Reports enabled — running");
    lastReportMs = millis();
}

void loop() {
    if (imu.wasReset()) {
        Serial.println("IMU reset — re-enabling reports");
        setReports();
    }

    if (!imu.getSensorEvent(&sensorValue)) return;

    switch (sensorValue.sensorId) {
        case SH2_ROTATION_VECTOR: {
            float qW = sensorValue.un.rotationVector.real;
            float qX = sensorValue.un.rotationVector.i;
            float qY = sensorValue.un.rotationVector.j;
            float qZ = sensorValue.un.rotationVector.k;
            sampleCount++;
            if (sampleCount <= 20) {
                Serial.printf("rot %lu: qW=%.3f qX=%.3f qY=%.3f qZ=%.3f  mag=%.4f\n",
                    sampleCount, qW, qX, qY, qZ,
                    sqrtf(qW*qW + qX*qX + qY*qY + qZ*qZ));
            }
            break;
        }
        case SH2_LINEAR_ACCELERATION: {
            float aX = sensorValue.un.linearAcceleration.x;
            float aY = sensorValue.un.linearAcceleration.y;
            float aZ = sensorValue.un.linearAcceleration.z;
            if (sampleCount <= 20) {
                Serial.printf("acc %lu: aX=%.2f aY=%.2f aZ=%.2f\n",
                    sampleCount, aX, aY, aZ);
            }
            break;
        }
        default:
            break;
    }

    uint32_t now = millis();
    if (now - lastReportMs >= 1000) {
        Serial.printf("[throughput] ~%lu events/sec | heap: %lu\n",
            sampleCount, ESP.getFreeHeap());
        sampleCount = 0;
        lastReportMs = now;
    }
}
