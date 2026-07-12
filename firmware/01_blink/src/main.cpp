#include <Arduino.h>

#define LED_PIN 2

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("CrossKart 01_blink — board alive");
    Serial.printf("CPU freq: %d MHz\n", getCpuFrequencyMhz());
    Serial.printf("Free heap: %d bytes\n", ESP.getFreeHeap());
    pinMode(LED_PIN, OUTPUT);
}

void loop() {
    digitalWrite(LED_PIN, HIGH);
    Serial.println("LED ON");
    delay(500);
    digitalWrite(LED_PIN, LOW);
    Serial.println("LED OFF");
    delay(500);
}
