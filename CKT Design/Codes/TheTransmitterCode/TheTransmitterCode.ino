#include <Wire.h>
#include <Adafruit_BME280.h>
#include <Adafruit_VL53L0X.h>

// =====================================================
// PIN CONFIGURATION
// =====================================================

#define SDA_PIN 8
#define SCL_PIN 9

#define MQ4_D0_PIN 6
#define MQ4_A0_PIN 7

#define GREEN_LED_PIN 10
#define RED_LED_PIN 11
#define BUZZER_PIN 12

// =====================================================
// I2C ADDRESSES
// =====================================================

#define BME280_ADDRESS_1 0x76
#define BME280_ADDRESS_2 0x77

#define MPU6500_ADDRESS_1 0x68
#define MPU6500_ADDRESS_2 0x69

// =====================================================
// MPU6500 REGISTERS
// =====================================================

#define MPU6500_WHO_AM_I      0x75
#define MPU6500_PWR_MGMT_1    0x6B
#define MPU6500_CONFIG        0x1A
#define MPU6500_SMPLRT_DIV    0x19
#define MPU6500_GYRO_CONFIG   0x1B
#define MPU6500_ACCEL_CONFIG  0x1C
#define MPU6500_ACCEL_CONFIG2 0x1D
#define MPU6500_ACCEL_XOUT_H  0x3B

// =====================================================
// OBJECTS
// =====================================================

Adafruit_BME280 bme;
Adafruit_VL53L0X vl53l0x;

// =====================================================
// STATUS FLAGS
// =====================================================

bool bmeFound = false;
bool mpuFound = false;
bool vl53Found = false;

uint8_t mpuAddress = MPU6500_ADDRESS_1;

unsigned long lastReadTime = 0;
const unsigned long readInterval = 2000;

// Set this to true only after confirming MQ-4 operation
const bool ENABLE_MQ4_WARNING = false;

// =====================================================
// MPU6500 DATA
// =====================================================

struct MPU6500Data {
  int16_t accelX;
  int16_t accelY;
  int16_t accelZ;
  int16_t temperature;
  int16_t gyroX;
  int16_t gyroY;
  int16_t gyroZ;
};

MPU6500Data mpuRaw;

// =====================================================
// I2C SCANNER
// =====================================================

void scanI2CBus() {
  Serial.println();
  Serial.println("========== I2C BUS SCAN ==========");

  int count = 0;

  for (uint8_t address = 1; address < 127; address++) {
    Wire.beginTransmission(address);
    uint8_t error = Wire.endTransmission();

    if (error == 0) {
      Serial.print("Device found at 0x");

      if (address < 16) {
        Serial.print("0");
      }

      Serial.println(address, HEX);
      count++;
    }
  }

  Serial.print("Total devices found: ");
  Serial.println(count);
  Serial.println("==================================");
}

// =====================================================
// MPU6500 REGISTER WRITE
// =====================================================

void mpuWriteRegister(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(mpuAddress);
  Wire.write(reg);
  Wire.write(value);
  Wire.endTransmission();
}

// =====================================================
// MPU6500 REGISTER READ
// =====================================================

uint8_t mpuReadRegister(uint8_t reg) {
  Wire.beginTransmission(mpuAddress);
  Wire.write(reg);

  if (Wire.endTransmission(false) != 0) {
    return 0xFF;
  }

  uint8_t received = Wire.requestFrom(mpuAddress, (uint8_t)1);

  if (received == 1 && Wire.available()) {
    return Wire.read();
  }

  return 0xFF;
}

// =====================================================
// MPU6500 MULTIPLE REGISTER READ
// =====================================================

bool mpuReadRegisters(
  uint8_t reg,
  uint8_t *buffer,
  uint8_t length
) {
  Wire.beginTransmission(mpuAddress);
  Wire.write(reg);

  if (Wire.endTransmission(false) != 0) {
    return false;
  }

  uint8_t received = Wire.requestFrom(mpuAddress, length);

  if (received != length) {
    return false;
  }

  for (uint8_t i = 0; i < length; i++) {
    buffer[i] = Wire.read();
  }

  return true;
}

// =====================================================
// INITIALIZE MPU6500
// =====================================================

void initializeMPU6500() {
  Serial.println();
  Serial.println("Initializing MPU6500...");

  mpuAddress = MPU6500_ADDRESS_1;
  uint8_t whoAmI = mpuReadRegister(MPU6500_WHO_AM_I);

  if (whoAmI != 0x70) {
    mpuAddress = MPU6500_ADDRESS_2;
    whoAmI = mpuReadRegister(MPU6500_WHO_AM_I);
  }

  Serial.print("WHO_AM_I: 0x");
  Serial.println(whoAmI, HEX);

  if (whoAmI != 0x70) {
    mpuFound = false;
    Serial.println("MPU6500 not detected.");
    return;
  }

  mpuFound = true;

  Serial.print("MPU6500 detected at 0x");
  Serial.println(mpuAddress, HEX);

  // Wake up the sensor
  mpuWriteRegister(MPU6500_PWR_MGMT_1, 0x01);
  delay(100);

  // Low-pass filter
  mpuWriteRegister(MPU6500_CONFIG, 0x03);

  // Sample-rate divider
  mpuWriteRegister(MPU6500_SMPLRT_DIV, 0x04);

  // Gyroscope: ±500 dps
  mpuWriteRegister(MPU6500_GYRO_CONFIG, 0x08);

  // Accelerometer: ±8 g
  mpuWriteRegister(MPU6500_ACCEL_CONFIG, 0x10);

  // Accelerometer filter
  mpuWriteRegister(MPU6500_ACCEL_CONFIG2, 0x03);

  Serial.println("MPU6500 configured successfully.");
}

// =====================================================
// READ MPU6500
// =====================================================

bool readMPU6500() {
  uint8_t buffer[14];

  if (!mpuReadRegisters(
        MPU6500_ACCEL_XOUT_H,
        buffer,
        14
      )) {
    return false;
  }

  mpuRaw.accelX = ((int16_t)buffer[0] << 8) | buffer[1];
  mpuRaw.accelY = ((int16_t)buffer[2] << 8) | buffer[3];
  mpuRaw.accelZ = ((int16_t)buffer[4] << 8) | buffer[5];

  mpuRaw.temperature = ((int16_t)buffer[6] << 8) | buffer[7];

  mpuRaw.gyroX = ((int16_t)buffer[8] << 8) | buffer[9];
  mpuRaw.gyroY = ((int16_t)buffer[10] << 8) | buffer[11];
  mpuRaw.gyroZ = ((int16_t)buffer[12] << 8) | buffer[13];

  return true;
}

// =====================================================
// PRINT MPU6500 DATA
// =====================================================

void printMPU6500Data() {
  Serial.println();
  Serial.println("------------- MPU6500 -------------");

  if (!mpuFound) {
    Serial.println("MPU6500 not available.");
    return;
  }

  if (!readMPU6500()) {
    Serial.println("MPU6500 reading failed.");
    return;
  }

  const float accelScale = 4096.0;
  const float gyroScale = 65.5;

  float accelX = mpuRaw.accelX / accelScale;
  float accelY = mpuRaw.accelY / accelScale;
  float accelZ = mpuRaw.accelZ / accelScale;

  float gyroX = mpuRaw.gyroX / gyroScale;
  float gyroY = mpuRaw.gyroY / gyroScale;
  float gyroZ = mpuRaw.gyroZ / gyroScale;

  float temperature =
    (mpuRaw.temperature / 333.87) + 21.0;

  Serial.print("Acceleration X: ");
  Serial.print(accelX, 3);
  Serial.println(" g");

  Serial.print("Acceleration Y: ");
  Serial.print(accelY, 3);
  Serial.println(" g");

  Serial.print("Acceleration Z: ");
  Serial.print(accelZ, 3);
  Serial.println(" g");

  Serial.print("Gyroscope X: ");
  Serial.print(gyroX, 3);
  Serial.println(" dps");

  Serial.print("Gyroscope Y: ");
  Serial.print(gyroY, 3);
  Serial.println(" dps");

  Serial.print("Gyroscope Z: ");
  Serial.print(gyroZ, 3);
  Serial.println(" dps");

  Serial.print("MPU6500 Temperature: ");
  Serial.print(temperature, 2);
  Serial.println(" °C");
}

// =====================================================
// INITIALIZE BME280
// =====================================================

void initializeBME280() {
  Serial.println();
  Serial.println("Initializing BME280...");

  if (bme.begin(BME280_ADDRESS_1, &Wire)) {
    bmeFound = true;
    Serial.println("BME280 found at 0x76");
  } else if (bme.begin(BME280_ADDRESS_2, &Wire)) {
    bmeFound = true;
    Serial.println("BME280 found at 0x77");
  } else {
    bmeFound = false;
    Serial.println("BME280 not found.");
  }
}

// =====================================================
// PRINT BME280 DATA
// =====================================================

void printBME280Data() {
  Serial.println();
  Serial.println("------------- BME280 -------------");

  if (!bmeFound) {
    Serial.println("BME280 not available.");
    return;
  }

  Serial.println("Reading temperature...");

  float temperature = bme.readTemperature();

  Serial.println("Reading humidity...");

  float humidity = bme.readHumidity();

  Serial.println("Reading pressure...");

  float pressure = bme.readPressure() / 100.0F;

  if (isnan(temperature) ||
      isnan(humidity) ||
      isnan(pressure)) {
    Serial.println("BME280 returned invalid data.");
    return;
  }

  Serial.print("Temperature: ");
  Serial.print(temperature, 2);
  Serial.println(" °C");

  Serial.print("Humidity: ");
  Serial.print(humidity, 2);
  Serial.println(" %");

  Serial.print("Pressure: ");
  Serial.print(pressure, 2);
  Serial.println(" hPa");
}

// =====================================================
// INITIALIZE VL53L0X
// =====================================================

void initializeVL53L0X() {
  Serial.println();
  Serial.println("Initializing VL53L0X...");

  if (vl53l0x.begin()) {
    vl53Found = true;
    Serial.println("VL53L0X found at 0x29");
  } else {
    vl53Found = false;
    Serial.println("VL53L0X not found.");
  }
}

// =====================================================
// PRINT VL53L0X DATA
// =====================================================

void printVL53L0XData() {
  Serial.println();
  Serial.println("------------ VL53L0X ------------");

  if (!vl53Found) {
    Serial.println("VL53L0X not available.");
    return;
  }

  VL53L0X_RangingMeasurementData_t measure;

  vl53l0x.rangingTest(&measure, false);

  if (measure.RangeStatus == 4) {
    Serial.println("Distance out of range.");
    return;
  }

  float distanceMM = measure.RangeMilliMeter;
  float distanceCM = distanceMM / 10.0;

  Serial.print("Distance: ");
  Serial.print(distanceMM);
  Serial.println(" mm");

  Serial.print("Distance: ");
  Serial.print(distanceCM, 2);
  Serial.println(" cm");
}

// =====================================================
// PRINT MQ-4 DATA
// =====================================================

void printMQ4Data() {
  int analogValue = analogRead(MQ4_A0_PIN);
  int digitalValue = digitalRead(MQ4_D0_PIN);

  Serial.println();
  Serial.println("-------------- MQ-4 --------------");

  Serial.print("Analog value: ");
  Serial.println(analogValue);

  Serial.print("Digital value: ");
  Serial.println(digitalValue);

  if (digitalValue == LOW) {
    Serial.println("MQ-4 digital status: LOW");
  } else {
    Serial.println("MQ-4 digital status: HIGH");
  }

  Serial.println("Note: MQ-4 requires warm-up time.");
}

// =====================================================
// UPDATE LED AND BUZZER
// =====================================================

void updateWarningStatus() {
  int digitalValue = digitalRead(MQ4_D0_PIN);

  bool gasWarning = false;

  if (ENABLE_MQ4_WARNING) {
    gasWarning = (digitalValue == LOW);
  }

  if (gasWarning) {
    digitalWrite(GREEN_LED_PIN, LOW);
    digitalWrite(RED_LED_PIN, HIGH);
    digitalWrite(BUZZER_PIN, HIGH);

    Serial.println();
    Serial.println("WARNING: MQ-4 threshold reached");
    Serial.println("Red LED: ON");
    Serial.println("Green LED: OFF");
    Serial.println("Buzzer: ON");
  } else {
    digitalWrite(GREEN_LED_PIN, HIGH);
    digitalWrite(RED_LED_PIN, LOW);
    digitalWrite(BUZZER_PIN, LOW);

    Serial.println();
    Serial.println("System status: NORMAL");
    Serial.println("Red LED: OFF");
    Serial.println("Green LED: ON");
    Serial.println("Buzzer: OFF");
  }

  Serial.println("----------------------------------");
}

// =====================================================
// SETUP
// =====================================================

void setup() {
  Serial.begin(115200);
  delay(1500);

  Serial.println();
  Serial.println("==========================================");
  Serial.println("ESP32-S3 COMPLETE SENSOR MONITOR");
  Serial.println("BME280 + MPU6500 + VL53L0X + MQ-4");
  Serial.println("==========================================");

  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(100000);

  // I2C timeout to prevent indefinite waiting
  Wire.setTimeOut(100);

  Serial.println("I2C initialized.");
  Serial.print("SDA: GPIO ");
  Serial.println(SDA_PIN);
  Serial.print("SCL: GPIO ");
  Serial.println(SCL_PIN);

  pinMode(MQ4_D0_PIN, INPUT);
  analogReadResolution(12);

  pinMode(GREEN_LED_PIN, OUTPUT);
  pinMode(RED_LED_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);

  digitalWrite(GREEN_LED_PIN, LOW);
  digitalWrite(RED_LED_PIN, LOW);
  digitalWrite(BUZZER_PIN, LOW);

  scanI2CBus();

  initializeBME280();
  initializeMPU6500();
  initializeVL53L0X();

  Serial.println();
  Serial.println("==========================================");
  Serial.println("INITIALIZATION SUMMARY");

  Serial.print("BME280: ");
  Serial.println(bmeFound ? "READY" : "NOT FOUND");

  Serial.print("MPU6500: ");
  Serial.println(mpuFound ? "READY" : "NOT FOUND");

  Serial.print("VL53L0X: ");
  Serial.println(vl53Found ? "READY" : "NOT FOUND");

  Serial.println("MQ-4: READY");
  Serial.println("MQ-4 warning mode: DISABLED");
  Serial.println("==========================================");

  digitalWrite(GREEN_LED_PIN, HIGH);

  Serial.println("Starting sensor readings...");
}

// =====================================================
// LOOP
// =====================================================

void loop() {
  if (millis() - lastReadTime >= readInterval) {
    lastReadTime = millis();

    Serial.println();
    Serial.println();
    Serial.println("==========================================");
    Serial.print("TIME: ");
    Serial.print(millis());
    Serial.println(" ms");
    Serial.println("==========================================");

    printBME280Data();
    printMPU6500Data();
    printVL53L0XData();
    printMQ4Data();
    updateWarningStatus();

    Serial.println();
    Serial.println("End of reading cycle.");
    Serial.println("==========================================");
  }
}