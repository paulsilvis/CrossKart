# CrossKart Wiring Reference

## ESP32 DevKitC 38-pin — Pin Labels
Left side (top=away from USB):
3.3V, EN, SVP(36), SVN(39), P34, P35, P32, P33, P25, P26, P27, P14, P12, GND, P13, SD2*, SD3*, GND, 5V

Right side (top=away from USB):
GND, P23, P22, TX(1), RX(3), P21, GND, P19, P18, P5, P17, P16, P4, P0, P2, P15, SD1*, SD0*, CLK*

*Do not use SD1, SD0, CLK, SD2, SD3 — internal flash pins.

## GY-BNO08x -> ESP32
| BNO08x Pin | ESP32 Label | GPIO |
|------------|------------|------|
| VCC        | 3.3V       | —    |
| GND        | GND        | —    |
| SCL        | P18        | 18   |
| SDA        | P23        | 23   |
| ADO        | P19        | 19   |
| CS         | P5         | 5    |
| INT        | P4         | 4    |
| RST        | P25        | 25   |
| PS0        | GND        | —    |
| PS1        | GND        | —    |

## SD Card -> ESP32
| SD Pin | ESP32 Label | GPIO |
|--------|------------|------|
| VCC    | 3.3V       | —    |
| GND    | GND        | —    |
| MOSI   | P23        | 23   |
| MISO   | P19        | 19   |
| SCK    | P18        | 18   |
| CS     | P15        | 15   |

## GPS (u-blox M10N) -> ESP32
| GPS Pin | ESP32 Label | GPIO |
|---------|------------|------|
| VCC     | 3.3V       | —    |
| GND     | GND        | —    |
| TX      | P16        | 16   |
| RX      | P17        | 17   |
