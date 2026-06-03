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
 *
 * Serial output: 115200 baud
 * Designed to be read by tools/visualizer.py on the host PC.
 */

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_BNO08x.h>

// ── Pin / bus config ────────────────────────────────────────────────────────
#define I2C_SDA      21
#define I2C_SCL      22
#define BNO085_RESET -1   // not wired, pull high internally

// ── Output rate ─────────────────────────────────────────────────────────────
// 10 Hz matches our target CSV rate; fast enough to see live motion
#define REPORT_INTERVAL_US  100000   // 100 ms = 10 Hz

// ── Globals ─────────────────────────────────────────────────────────────────
Adafruit_BNO08x  imu(BNO085_RESET);
sh2_SensorValue_t sensorVal;

// Last known values (updated whenever the matching report arrives)
struct State {
  float qi, qj, qk, qr;          // rotation vector (quaternion)
  float ax, ay, az;               // linear accel m/s²  (gravity removed)
  float gx, gy, gz;               // gyro rad/s
  uint8_t cal_accel;              // 0–3
  uint8_t cal_gyro;
  uint8_t cal_mag;
  bool    valid_quat;
  bool    valid_accel;
  bool    valid_gyro;
} st = {};

// ── Helpers ─────────────────────────────────────────────────────────────────
static const char* calLabel(uint8_t c) {
  switch (c) {
    case 0: return "UNRELIABLE";
    case 1: return "LOW";
    case 2: return "MED";
    case 3: return "HIGH";
    default: return "?";
  }
}

// Enable the three reports we care about
static void enableReports() {
  // Rotation vector (fused quat + mag) — best absolute heading
  if (!imu.enableReport(SH2_ROTATION_VECTOR, REPORT_INTERVAL_US))
    Serial.println("# WARN: rotation vector report failed");

  // Linear acceleration (gravity subtracted by sensor)
  if (!imu.enableReport(SH2_LINEAR_ACCELERATION, REPORT_INTERVAL_US))
    Serial.println("# WARN: linear accel report failed");

  // Calibrated gyro
  if (!imu.enableReport(SH2_GYROSCOPE_CALIBRATED, REPORT_INTERVAL_US))
    Serial.println("# WARN: gyro report failed");
}

// ── Setup ───────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  while (!Serial) delay(10);

  Serial.println("# CrossKart IMU — Phase 1 verification");
  Serial.println("# BNO085 on I2C, 10 Hz");
  Serial.println("# Columns: ms,qi,qj,qk,qr,ax,ay,az,gx,gy,gz,cal_a,cal_g,cal_m");

  Wire.begin(I2C_SDA, I2C_SCL);
  Wire.setClock(400000);   // 400 kHz fast-mode

  // Try to init — retry loop so a cold board gets a few chances
  uint8_t attempts = 0;
  while (!imu.begin_I2C(0x4B)) {
    attempts++;
    Serial.printf("# BNO085 not found (attempt %u) — check wiring/PS0/PS1\n", attempts);
    if (attempts >= 5) {
      Serial.println("# No IMU found — retrying (wire it up and reset)...");
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
  Serial.println("# Reports enabled — streaming:");
}

// ── Loop ────────────────────────────────────────────────────────────────────
void loop() {
  // Drain all pending reports from the sensor FIFO
  while (imu.getSensorEvent(&sensorVal)) {
    switch (sensorVal.sensorId) {

      case SH2_ROTATION_VECTOR:
        st.qi = sensorVal.un.rotationVector.i;
        st.qj = sensorVal.un.rotationVector.j;
        st.qk = sensorVal.un.rotationVector.k;
        st.qr = sensorVal.un.rotationVector.real;
        st.cal_accel = sensorVal.un.rotationVector.accuracy;  // mag accuracy
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

  // Emit a CSV row once per REPORT_INTERVAL_US (approx — millis-gated)
  static uint32_t lastPrint = 0;
  uint32_t now = millis();
  if (now - lastPrint >= 100) {
    lastPrint = now;

    if (st.valid_quat && st.valid_accel && st.valid_gyro) {
      // Compact CSV row — host visualizer parses this
      Serial.printf("%lu,%.5f,%.5f,%.5f,%.5f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%u,%u,%u\n",
        now,
        st.qi, st.qj, st.qk, st.qr,
        st.ax, st.ay, st.az,
        st.gx, st.gy, st.gz,
        st.cal_accel, st.cal_gyro, st.cal_mag);
    } else {
      // Not all reports in yet — print a status line
      Serial.printf("# waiting: quat=%d accel=%d gyro=%d\n",
        st.valid_quat, st.valid_accel, st.valid_gyro);
    }
  }
}
