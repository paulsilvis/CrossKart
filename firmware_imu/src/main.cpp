/*
 * CrossKart Telemetry — Phase 1: IMU Verification
 * Hardware: ESP32-WROOM-32U + Adafruit BNO085 (#4754)
 * Interface: I2C (PS0=GND, PS1=GND)
 *
 * Wiring:
 *   BNO085 VIN  → ESP32 3V3
 *   BNO085 GND  → ESP32 GND
 *   BNO085 SDA  → ESP32 GPIO 21
 *   BNO085 SCL  → ESP32 GPIO 22
 *   BNO085 PS0  → GND   (selects I2C mode)
 *   BNO085 PS1  → GND   (selects I2C mode)
 *   BNO085 RST  → ESP32 GPIO 4  (driven manually)
 *
 * Serial output: 115200 baud
 * Columns: ms,qi,qj,qk,qr,ax,ay,az,gx,gy,gz,cal_a,cal_g,cal_m,resets
 */

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_BNO08x.h>

// ── Pin / bus config ─────────────────────────────────────────────────────────
#define I2C_SDA      21
#define I2C_SCL      22
#define BNO085_RST    4   // driven manually via digitalWrite

// ── Timing ───────────────────────────────────────────────────────────────────
#define REPORT_INTERVAL_US  100000   // 100 ms = 10 Hz
#define WATCHDOG_MS         150      // reset if no event in 150ms (after first event)

// ── Globals ───────────────────────────────────────────────────────────────────
Adafruit_BNO08x   imu(-1);          // -1 = library does not touch RST pin
sh2_SensorValue_t sensorVal;

struct State {
  float qi, qj, qk, qr;
  float ax, ay, az;
  float gx, gy, gz;
  uint8_t cal_accel;
  uint8_t cal_gyro;
  uint8_t cal_mag;
  bool    valid_quat;
  bool    valid_accel;
  bool    valid_gyro;
} st = {};

uint32_t lastEventMs    = 0;
uint32_t resetCount     = 0;
bool     firstEventSeen = false;

// ── Hard reset the BNO085 via RST pin ────────────────────────────────────────
static void hardResetBNO() {
  digitalWrite(BNO085_RST, LOW);
  delay(10);
  digitalWrite(BNO085_RST, HIGH);
  delay(100);  // wait for BNO085 to boot
}

// ── Enable reports ────────────────────────────────────────────────────────────
static void enableReports() {
  if (!imu.enableReport(SH2_ROTATION_VECTOR, REPORT_INTERVAL_US))
    Serial.println("# WARN: rotation vector report failed");
  if (!imu.enableReport(SH2_LINEAR_ACCELERATION, REPORT_INTERVAL_US))
    Serial.println("# WARN: linear accel report failed");
  if (!imu.enableReport(SH2_GYROSCOPE_CALIBRATED, REPORT_INTERVAL_US))
    Serial.println("# WARN: gyro report failed");
}

// ── Watchdog reset + reinit ───────────────────────────────────────────────────
static void resetIMU() {
  resetCount++;
  Serial.printf("# WATCHDOG: no event for %ums — reset #%lu\n",
                WATCHDOG_MS, resetCount);

  hardResetBNO();

  Wire.end();
  delay(50);
  Wire.begin(I2C_SDA, I2C_SCL);
  Wire.setClock(400000);

  uint8_t attempts = 0;
  while (!imu.begin_I2C(0x4B)) {
    attempts++;
    Serial.printf("# RST attempt %u...\n", attempts);
    if (attempts >= 10) {
      Serial.println("# FATAL: IMU not responding after reset. Halting.");
      while (true) delay(1000);
    }
    delay(200);
  }

  enableReports();
  lastEventMs    = millis();
  firstEventSeen = false;
  Serial.printf("# IMU recovered OK (total resets: %lu)\n", resetCount);
}

// ── Setup ─────────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  while (!Serial) delay(10);

  // RST pin — drive high (inactive) to start
  pinMode(BNO085_RST, OUTPUT);
  digitalWrite(BNO085_RST, HIGH);

  Serial.println("# CrossKart IMU — Phase 1 verification");
  Serial.println("# BNO085 on I2C @ 0x4B, 10 Hz, watchdog 150ms");
  Serial.println("# Columns: ms,qi,qj,qk,qr,ax,ay,az,gx,gy,gz,cal_a,cal_g,cal_m,resets");

  Wire.begin(I2C_SDA, I2C_SCL);
  Wire.setClock(400000);

  uint8_t attempts = 0;
  while (!imu.begin_I2C(0x4B)) {
    attempts++;
    Serial.printf("# BNO085 not found (attempt %u)\n", attempts);
    if (attempts >= 5) {
      Serial.println("# Retrying...");
      attempts = 0;
    }
    delay(1000);
  }

  Serial.println("# BNO085 found OK");
  Serial.printf("# Firmware version: %u.%u.%u\n",
    imu.prodIds.entry[0].swVersionMajor,
    imu.prodIds.entry[0].swVersionMinor,
    imu.prodIds.entry[0].swVersionPatch);

  enableReports();
  lastEventMs = millis();
  Serial.println("# Reports enabled — streaming:");
}

// ── Loop ──────────────────────────────────────────────────────────────────────
void loop() {
  // Drain all pending sensor events
  while (imu.getSensorEvent(&sensorVal)) {
    if (!firstEventSeen) {
      firstEventSeen = true;
      Serial.println("# First event received — watchdog armed");
    }
    lastEventMs = millis();

    switch (sensorVal.sensorId) {
      case SH2_ROTATION_VECTOR:
        st.qi = sensorVal.un.rotationVector.i;
        st.qj = sensorVal.un.rotationVector.j;
        st.qk = sensorVal.un.rotationVector.k;
        st.qr = sensorVal.un.rotationVector.real;
        st.cal_mag = sensorVal.un.rotationVector.accuracy;
        st.valid_quat = true;
        break;

      case SH2_LINEAR_ACCELERATION:
        st.ax = sensorVal.un.linearAcceleration.x;
        st.ay = sensorVal.un.linearAcceleration.y;
        st.az = sensorVal.un.linearAcceleration.z;
        st.cal_accel = sensorVal.status & 0x03;
        st.valid_accel = true;
        break;

      case SH2_GYROSCOPE_CALIBRATED:
        st.gx = sensorVal.un.gyroscope.x;
        st.gy = sensorVal.un.gyroscope.y;
        st.gz = sensorVal.un.gyroscope.z;
        st.cal_gyro = sensorVal.status & 0x03;
        st.valid_gyro = true;
        break;
    }
  }

  // Watchdog — only active after first event received
  if (firstEventSeen && (millis() - lastEventMs > WATCHDOG_MS)) {
    resetIMU();
    return;
  }

  // Emit CSV row at 10 Hz
  static uint32_t lastPrint = 0;
  uint32_t now = millis();
  if (now - lastPrint >= 100) {
    lastPrint = now;

    if (st.valid_quat && st.valid_accel && st.valid_gyro) {
      Serial.printf("%lu,%.5f,%.5f,%.5f,%.5f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%u,%u,%u,%lu\n",
        now,
        st.qi, st.qj, st.qk, st.qr,
        st.ax, st.ay, st.az,
        st.gx, st.gy, st.gz,
        st.cal_accel, st.cal_gyro, st.cal_mag,
        resetCount);
    } else {
      Serial.printf("# waiting: quat=%d accel=%d gyro=%d\n",
        st.valid_quat, st.valid_accel, st.valid_gyro);
    }
  }
}
