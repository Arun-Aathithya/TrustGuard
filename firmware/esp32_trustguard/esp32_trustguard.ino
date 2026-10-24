/*
 * TrustGuard AI - ESP32 sensor node
 * DS18B20 temperature + MPU6050 vibration + SSD1306 OLED status screen
 *
 * Libraries (Arduino Library Manager):
 *   PubSubClient, OneWire, DallasTemperature, Adafruit MPU6050,
 *   Adafruit Unified Sensor, Adafruit BusIO, Adafruit SSD1306, Adafruit GFX Library
 *
 * Wiring:
 *   DS18B20 DATA -> GPIO 4 (4.7k pull-up to 3V3), VCC -> 3V3, GND -> GND
 *   MPU6050 SDA  -> GPIO 21, SCL -> GPIO 22 (3V3, GND)
 *   OLED    SDA  -> GPIO 21, SCL -> GPIO 22 (shared I2C bus with the MPU6050; 3V3, GND)
 *
 * Publishes JSON every PUBLISH_MS to:
 *   Legacy topics (SENSOR_ID = 0):
 *     trustguard/sensors/<MACHINE_ID>/temperature
 *     trustguard/sensors/<MACHINE_ID>/vibration
 *   Per-sensor topics (SENSOR_ID > 0, for sensors added on the website):
 *     trustguard/sensors/<MACHINE_ID>/temperature/<TEMP_SENSOR_ID>
 *     trustguard/sensors/<MACHINE_ID>/vibration/<VIB_SENSOR_ID>
 *
 * Vibration = RMS of dynamic acceleration in m/s^2 (raw; the backend calibrates it).
 * A failed read is sent as "value": null so the backend counts it as missing data.
 * Open the Serial Monitor at 115200 baud to see WiFi / MQTT status.
 */
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <Wire.h>
#include <math.h>
#include <time.h>

// ======================= EDIT THESE =======================
const char* WIFI_SSID    = "OPPO K13 Turbo 5G";   // must be 2.4 GHz
const char* WIFI_PASS    = "22052007";
const char* MQTT_HOST    = "10.138.87.108";       // laptop IPv4 (run ipconfig) - changes if the hotspot changes!
const uint16_t MQTT_PORT = 1883;                  // 1883 = plain, 8883 = TLS
const bool USE_TLS       = false;                 // false for desk test, true + CA_CERT for real use
const char* MQTT_USER    = "esp32";
const char* MQTT_PASS    = "Arun2007";
const char* DEVICE_ID    = "ESP32-A1";            // must match the registered device_id exactly
const int   MACHINE_ID   = 1;                     // must match the machine in TrustGuard
const unsigned long PUBLISH_MS = 5000;

// 0 = legacy topic  trustguard/sensors/<machine>/<type>
// >0 = per-sensor   trustguard/sensors/<machine>/<type>/<sensor_id>  (use the ID shown on the website)
const int TEMP_SENSOR_ID = 1;
const int VIB_SENSOR_ID  = 3;

// OLED
const int  OLED_W    = 128;
const int  OLED_H    = 64;                        // 32 for a 128x32 screen
const byte OLED_ADDR = 0x3C;                      // some screens use 0x3D

// Pins
const int PIN_SDA = 21;
const int PIN_SCL = 22;
const int PIN_DS18B20 = 4;

// TLS only: paste the broker CA certificate (PEM) between the quotes.
const char* CA_CERT = "";
// Lab bench only: skip certificate verification. Never enable on a shared network.
const bool ALLOW_INSECURE_TLS = false;
// ==========================================================

WiFiClient plainClient;
WiFiClientSecure tlsClient;
PubSubClient mqtt;
OneWire oneWire(PIN_DS18B20);
DallasTemperature ds18b20(&oneWire);
Adafruit_MPU6050 mpu;
Adafruit_SSD1306 display(OLED_W, OLED_H, &Wire, -1);
bool mpuOk = false;
bool mpuRaw = false;        // true = talking to the chip registers directly (clone chips the Adafruit library rejects)
uint8_t mpuAddr = 0x68;
bool oledOk = false;
unsigned long lastPublish = 0;
unsigned long lastWifiTry = 0;

// ---------- OLED helpers ----------
void showStatus(const String& l1, const String& l2 = "", const String& l3 = "") {
  if (!oledOk) return;
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);
  display.println("TrustGuard AI");
  display.println(l1);
  if (l2.length()) display.println(l2);
  if (l3.length()) display.println(l3);
  display.display();
}

void showReadings(bool tempOk, float tC, bool vibOk, float vib) {
  if (!oledOk) return;
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);
  display.println("TrustGuard AI");
  display.print("WiFi:"); display.print(WiFi.status() == WL_CONNECTED ? "OK " : "-- ");
  display.print("MQTT:"); display.println(mqtt.connected() ? "OK" : "--");
  display.print("Temp: ");
  if (tempOk) { display.print(tC, 1); display.println(" C"); } else display.println("--");
  display.print("Vib : ");
  if (vibOk) { display.print(vib, 2); display.println(" m/s2"); } else display.println("--");
  display.print("ID: "); display.println(DEVICE_ID);
  display.display();
}

// ---------- connectivity ----------
void syncClock() {
  configTime(0, 0, "pool.ntp.org", "time.google.com");  // UTC timestamps
  time_t t = 0; int tries = 0;
  while (t < 1700000000 && tries++ < 40) { delay(250); time(&t); }
}

void connectWifi() {
  Serial.print("Connecting to WiFi: "); Serial.println(WIFI_SSID);
  showStatus("WiFi connecting...", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  int dots = 0;
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
    if (++dots % 20 == 0) {
      Serial.println(" (still trying - check name/password, must be 2.4 GHz)");
      WiFi.disconnect();
      WiFi.begin(WIFI_SSID, WIFI_PASS);   // retry; fixes the occasional stuck connect
    }
  }
  Serial.println();
  Serial.print("WiFi connected, ESP32 IP: "); Serial.println(WiFi.localIP());
  showStatus("WiFi connected", WiFi.localIP().toString());
  syncClock();
}

void connectMqtt() {
  while (!mqtt.connected()) {
    if (WiFi.status() != WL_CONNECTED) connectWifi();
    Serial.print("Connecting to MQTT "); Serial.print(MQTT_HOST); Serial.print(":"); Serial.println(MQTT_PORT);
    showStatus("MQTT connecting...", String(MQTT_HOST) + ":" + String(MQTT_PORT));
    if (mqtt.connect(DEVICE_ID, MQTT_USER, MQTT_PASS)) {
      Serial.println("MQTT connected");
      showStatus("MQTT connected", DEVICE_ID);
    } else {
      int st = mqtt.state();
      Serial.print("MQTT failed, state="); Serial.print(st);
      Serial.println("  (-2 = cannot reach broker: check IP/firewall/listener, 4 = bad user/password, 5 = not authorised)");
      showStatus("MQTT failed", "state " + String(st), "retrying...");
      delay(3000);
    }
  }
}

// ---------- publishing ----------
String isoNow() {
  time_t t; time(&t);
  if (t < 1700000000) return "";  // clock not synced: omit timestamp, server uses receive time
  struct tm tm; gmtime_r(&t, &tm);
  char buf[25]; strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", &tm);
  return String(buf);
}

void publishValue(const char* sensorType, int sensorId, bool ok, float value) {
  char topic[96];
  if (sensorId > 0) snprintf(topic, sizeof(topic), "trustguard/sensors/%d/%s/%d", MACHINE_ID, sensorType, sensorId);
  else              snprintf(topic, sizeof(topic), "trustguard/sensors/%d/%s", MACHINE_ID, sensorType);
  String ts = isoNow();
  String payload = String("{\"device_id\":\"") + DEVICE_ID + "\",\"sensor_type\":\"" + sensorType + "\",\"value\":" +
                   (ok ? String(value, 3) : String("null")) + (ts.length() ? ",\"timestamp\":\"" + ts + "\"" : "") + "}";
  bool sent = mqtt.publish(topic, payload.c_str(), false);  // not retained
  Serial.print(sent ? "Published " : "PUBLISH FAILED ");
  Serial.print(topic); Serial.print(" -> "); Serial.println(payload);
}

// ---------- sensors ----------
// DS18B20 read with up to 4 attempts. A failed CRC returns DEVICE_DISCONNECTED_C (-127);
// exactly 85.0 is the sensor's power-on default, not a measurement. Neither is ever reported as real.
float readTemperature(bool &ok) {
  for (int i = 0; i < 4; i++) {
    ds18b20.requestTemperatures();
    float t = ds18b20.getTempCByIndex(0);
    if (t != DEVICE_DISCONNECTED_C && !isnan(t) && t != 85.0f) { ok = true; return t; }
    delay(150);
  }
  ok = false;
  return NAN;
}

bool mpuWriteReg(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(mpuAddr);
  Wire.write(reg); Wire.write(val);
  return Wire.endTransmission() == 0;
}

// Fallback for MPU6050-compatible chips (MPU6500/9250 clones) that the Adafruit library refuses.
bool rawMpuInit() {
  const uint8_t addrs[2] = {0x68, 0x69};
  for (int i = 0; i < 2; i++) {
    mpuAddr = addrs[i];
    Wire.beginTransmission(mpuAddr);
    if (Wire.endTransmission() != 0) continue;
    if (!mpuWriteReg(0x6B, 0x00)) continue;   // wake up
    delay(50);
    mpuWriteReg(0x1C, 0x10);                  // accel range +/-8 g (4096 LSB/g)
    mpuWriteReg(0x1A, 0x03);                  // low-pass filter ~44 Hz
    Wire.beginTransmission(mpuAddr); Wire.write(0x75); Wire.endTransmission(false);
    Wire.requestFrom((int)mpuAddr, 1);
    if (Wire.available()) { Serial.print("MPU WHO_AM_I = 0x"); Serial.println(Wire.read(), HEX); }
    return true;
  }
  return false;
}

bool readAccel(float &x, float &y, float &z) {   // m/s^2
  if (!mpuRaw) {
    sensors_event_t a, g, t; mpu.getEvent(&a, &g, &t);
    x = a.acceleration.x; y = a.acceleration.y; z = a.acceleration.z;
    return true;
  }
  Wire.beginTransmission(mpuAddr); Wire.write(0x3B);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom((int)mpuAddr, 6) != 6) return false;
  uint8_t b[6];
  for (int i = 0; i < 6; i++) b[i] = Wire.read();
  const float k = 9.80665f / 4096.0f;
  x = (int16_t)((b[0] << 8) | b[1]) * k;
  y = (int16_t)((b[2] << 8) | b[3]) * k;
  z = (int16_t)((b[4] << 8) | b[5]) * k;
  return true;
}

float readVibrationRms() {  // RMS of acceleration magnitude minus gravity over ~200 ms
  double sumSq = 0; int n = 0, bad = 0;
  unsigned long start = millis();
  while (millis() - start < 200) {
    float ax = 0, ay = 0, az = 0;
    readAccel(ax, ay, az);   // on failure stays 0 -> counted as a bad sample below
    double mag = sqrt((double)ax * ax + (double)ay * ay + (double)az * az);
    if (isnan(mag) || mag < 3.0) bad++;   // a working sensor at rest reads ~9.8; ~0 means the I2C read failed
    double dyn = mag - 9.80665;
    sumSq += dyn * dyn; n++;
    delay(5);
  }
  if (n == 0 || bad > n / 2) return NAN;  // sensor not answering: report missing, never a fake number
  return (float)sqrt(sumSq / n);
}

void haltWithError(const char* msg) {  // refuse to run in an unsafe / unconfigured state
  while (true) { Serial.println(msg); showStatus("CONFIG ERROR", msg); delay(5000); }
}

// ---------- sensor init (safe to call repeatedly) ----------
bool dsOk = false;

void initSensors() {
  if (!dsOk) {
    pinMode(PIN_DS18B20, INPUT_PULLUP);  // weak internal pull-up; a real 4.7k resistor to 3V3 is still best
    ds18b20.begin();
    dsOk = ds18b20.getDeviceCount() > 0;
  }
  if (!mpuOk) {
    mpuRaw = false;
    mpuOk = mpu.begin(0x68, &Wire);
    if (!mpuOk) mpuOk = mpu.begin(0x69, &Wire);   // AD0 pin high
    if (mpuOk) {
      mpu.setAccelerometerRange(MPU6050_RANGE_8_G);
      mpu.setFilterBandwidth(MPU6050_BAND_44_HZ);
    } else if (rawMpuInit()) {                    // library rejected the chip: read it directly
      mpuRaw = true; mpuOk = true;
    }
  }
}

// ---------- setup / loop ----------
void setup() {
  Serial.begin(115200);
  delay(500);
  Wire.begin(PIN_SDA, PIN_SCL);  // shared by MPU6050 and OLED

  oledOk = display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR);
  Serial.println(oledOk ? "OLED found" : "OLED NOT found (check wiring / address 0x3C or 0x3D)");
  showStatus("Starting...");

  if (strcmp(MQTT_PASS, "CHANGE_ME") == 0) haltWithError("Set MQTT_PASS and WIFI_* before flashing.");
  if (USE_TLS && strlen(CA_CERT) == 0 && !ALLOW_INSECURE_TLS) haltWithError("TLS on but CA_CERT empty.");

  delay(1000);  // let the sensors power up before the first check
  for (int i = 0; i < 5 && !(mpuOk && dsOk); i++) {   // retry: sensors can be slow right after power-on
    initSensors();
    if (!(mpuOk && dsOk)) delay(500);
  }
  Serial.println(dsOk ? "DS18B20 found" : "DS18B20 NOT found (check data wire on GPIO 4 + 4.7k pull-up)");
  Serial.println(mpuOk ? (mpuRaw ? "MPU6050 found (direct register mode)" : "MPU6050 found") : "MPU6050 NOT found (check SDA/SCL/power)");
  showStatus(oledOk ? "OLED ok" : "OLED missing", mpuOk ? "MPU6050 ok" : "MPU6050 missing", dsOk ? "DS18B20 ok" : "DS18B20 missing");
  delay(800);

  connectWifi();
  if (USE_TLS) {
    if (strlen(CA_CERT)) tlsClient.setCACert(CA_CERT);
    else { Serial.println("WARNING: TLS certificate verification DISABLED (ALLOW_INSECURE_TLS)"); tlsClient.setInsecure(); }
    mqtt.setClient(tlsClient);
  } else {
    mqtt.setClient(plainClient);
  }
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setBufferSize(512);
  mqtt.setKeepAlive(30);
}

void loop() {
  connectMqtt();
  mqtt.loop();
  if (millis() - lastPublish < PUBLISH_MS) return;
  lastPublish = millis();

  if (!mpuOk || !dsOk) {   // a sensor was missing at boot: try again
    initSensors();
    if (mpuOk) Serial.println("MPU6050 found (late)");
    if (dsOk) Serial.println("DS18B20 found (late)");
  }

  bool tempOk = false;
  float tC = readTemperature(tempOk);   // always try, with retries (the bus can glitch for a moment)
  publishValue("temperature", TEMP_SENSOR_ID, tempOk, tC);

  float vib = mpuOk ? readVibrationRms() : NAN;
  bool vibOk = mpuOk && !isnan(vib);
  if (!vibOk) mpuOk = false;      // force a re-init on the next cycle
  publishValue("vibration", VIB_SENSOR_ID, vibOk, vib);

  showReadings(tempOk, tC, vibOk, vib);
}