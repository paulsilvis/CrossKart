// 05_full — CrossKart full telemetry logger
//
// IMU (BNO085) at 50Hz via SPI
// GPS (u-blox M10N) at 10Hz via UART2
// SD card logging via SPI
//
// Pin assignments:
//   SPI SCK=P18  MOSI=P23  MISO=P19
//   IMU CS=P5  INT=P4  RST=P25
//   SD  CS=P15
//   GPS RX=P16  TX=P17

#include <Arduino.h>
#include <SPI.h>
#include <SD.h>
#include <TinyGPSPlus.h>
#include <Adafruit_BNO08x.h>

#define BNO_CS   5
#define BNO_INT  4
#define BNO_RST  25
#define SD_CS    15
#define GPS_RX   16
#define GPS_TX   17

#define IMU_INTERVAL_US   20000   // 50Hz
#define GPS_BAUD          115200

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

Adafruit_BNO08x imu(BNO_RST);
sh2_SensorValue_t sensorValue;
HardwareSerial gpsSerial(2);
TinyGPSPlus gps;
File logFile;

struct GpsState {
    double lat=0, lon=0;
    float alt=0, speed_kmh=0, course=0;
    uint8_t sats=0;
    float hdop=99.9f;
    bool valid=false;
    uint32_t age_ms=0;
} gpsState;

uint32_t seqNum=0, imuSamples=0, gpsFixes=0, sdErrors=0, lastStatusMs=0;

void sendUBX(const uint8_t *cmd, size_t len) {
    gpsSerial.write(cmd, len); gpsSerial.flush();
}

void enableIMUReports() {
    imu.enableReport(SH2_ROTATION_VECTOR,    IMU_INTERVAL_US);
    imu.enableReport(SH2_LINEAR_ACCELERATION, IMU_INTERVAL_US);
    imu.enableReport(SH2_GYROSCOPE_CALIBRATED, IMU_INTERVAL_US);
}

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("CrossKart 05_full — starting");

    // GPS
    gpsSerial.begin(9600, SERIAL_8N1, GPS_RX, GPS_TX);
    delay(100);
    sendUBX(UBX_SET_BAUD, sizeof(UBX_SET_BAUD));
    delay(100);
    gpsSerial.end();
    gpsSerial.begin(GPS_BAUD, SERIAL_8N1, GPS_RX, GPS_TX);
    delay(100);
    sendUBX(UBX_SET_10HZ, sizeof(UBX_SET_10HZ));
    Serial.println("GPS configured");

    // IMU
    SPI.begin();
    if (!imu.begin_SPI(BNO_CS, BNO_INT, &SPI)) {
        Serial.println("FATAL: BNO085 not found");
        while (1) delay(1000);
    }
    enableIMUReports();
    Serial.println("IMU configured");

    // SD
    if (!SD.begin(SD_CS)) {
        Serial.println("FATAL: SD card not found");
        while (1) delay(1000);
    }
    if (!SD.exists("/data")) SD.mkdir("/data");
    char fname[40];
    snprintf(fname, sizeof(fname), "/data/session_%010lu.csv", millis()/1000);
    logFile = SD.open(fname, FILE_WRITE);
    if (!logFile) { Serial.println("FATAL: could not open log file"); while(1) delay(1000); }
    logFile.println("seq,ts_ms,imu_qW,imu_qX,imu_qY,imu_qZ,imu_aX,imu_aY,imu_aZ,imu_gX,imu_gY,imu_gZ,gps_valid,gps_lat,gps_lon,gps_alt_m,gps_speed_kmh,gps_course_deg,gps_sats,gps_hdop,gps_age_ms");
    logFile.flush();
    Serial.printf("Logging to: %s\n", fname);

    lastStatusMs = millis();
    Serial.println("All systems go. Logging...");
}

void loop() {
    // GPS
    while (gpsSerial.available()) {
        if (gps.encode(gpsSerial.read()) && gps.location.isUpdated()) {
            gpsState.valid=gps.location.isValid();
            gpsState.lat=gps.location.lat(); gpsState.lon=gps.location.lng();
            gpsState.alt=gps.altitude.meters(); gpsState.speed_kmh=gps.speed.kmph();
            gpsState.course=gps.course.deg(); gpsState.sats=gps.satellites.value();
            gpsState.hdop=gps.hdop.hdop(); gpsState.age_ms=millis();
            gpsFixes++;
        }
    }

    // IMU
    if (imu.wasReset()) enableIMUReports();
    if (!imu.getSensorEvent(&sensorValue)) return;

    static float qW=1,qX=0,qY=0,qZ=0;
    static float aX=0,aY=0,aZ=0;
    static float gX=0,gY=0,gZ=0;

    switch (sensorValue.sensorId) {
        case SH2_ROTATION_VECTOR:
            qW=sensorValue.un.rotationVector.real;
            qX=sensorValue.un.rotationVector.i;
            qY=sensorValue.un.rotationVector.j;
            qZ=sensorValue.un.rotationVector.k;
            return;
        case SH2_LINEAR_ACCELERATION:
            aX=sensorValue.un.linearAcceleration.x;
            aY=sensorValue.un.linearAcceleration.y;
            aZ=sensorValue.un.linearAcceleration.z;
            return;
        case SH2_GYROSCOPE_CALIBRATED:
            gX=sensorValue.un.gyroscope.x;
            gY=sensorValue.un.gyroscope.y;
            gZ=sensorValue.un.gyroscope.z;
            break;
        default: return;
    }

    uint32_t ts=millis();
    uint32_t gpsAge=(gpsState.age_ms>0)?(ts-gpsState.age_ms):99999;

    size_t n = logFile.printf(
        "%lu,%lu,%.4f,%.4f,%.4f,%.4f,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%d,%.6f,%.6f,%.1f,%.2f,%.1f,%d,%.2f,%lu\n",
        seqNum++,ts,qW,qX,qY,qZ,aX,aY,aZ,gX,gY,gZ,
        gpsState.valid?1:0,gpsState.lat,gpsState.lon,gpsState.alt,
        gpsState.speed_kmh,gpsState.course,gpsState.sats,gpsState.hdop,gpsAge);

    if (n==0) sdErrors++;
    imuSamples++;
    if (seqNum%50==0) logFile.flush();

    uint32_t now=millis();
    if (now-lastStatusMs>=5000) {
        Serial.printf("[status] IMU=%.1fHz GPS_fixes=%lu SD_errors=%lu heap=%lu fix=%s\n",
            imuSamples*1000.0f/(now-lastStatusMs),gpsFixes,sdErrors,ESP.getFreeHeap(),
            gpsState.valid?"YES":"no");
        imuSamples=0; gpsFixes=0; lastStatusMs=now;
    }
}
