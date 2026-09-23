#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <esp_now.h>
#include <Adafruit_BME280.h>
#include <Adafruit_VL53L0X.h>

#include "h_stage_1.h"
#include "scaler_stage_2.h"
#include "buffer_stage_3.h"
#include "lstm_inference.h"
#include "vae_inference.h"
#include "gru_inference.h"
#include "ml_xgb_inference.h"


// ============================================================
// MODEL CONTROL
// ============================================================

#define ENABLE_LSTM      1
#define ENABLE_VAE       1
#define ENABLE_GRU       1
#define ENABLE_XGB       1
#define ENABLE_STAT_XGB  1


// ============================================================
// I2C PINS
// ============================================================

#define SDA_PIN 8
#define SCL_PIN 9


// ============================================================
// ICM-20689
// ============================================================

#define ICM_ADDR 0x68

#define WHO_AM_I_REG     0x75
#define PWR_MGMT_1       0x6B

#define ACCEL_CONFIG     0x1C
#define GYRO_CONFIG      0x1B
#define ACCEL_CONFIG2    0x1D
#define CONFIG_REG       0x1A
#define SMPLRT_DIV       0x19

#define ACCEL_XOUT_H     0x3B
#define GYRO_XOUT_H      0x43
#define TEMP_OUT_H       0x41


// ============================================================
// SENSOR OBJECTS
// ============================================================

Adafruit_BME280 bme;
Adafruit_VL53L0X vl53;


// ============================================================
// SENSOR STATE
// ============================================================

SensorFrame previousFrame;

bool previousFrameValid = false;


// ============================================================
// FEATURE BUFFER
// ============================================================

FeatureBuffer featureBuffer;
// ============================================================
// ROOF REFERENCE
// ============================================================

const float ROOF_REFERENCE_CM = 300.0f;
// ============================================================
// STATISTICAL XGBOOST 2.0 BUFFER
// ============================================================

#define STAT_XGB_WINDOW 24

struct StatisticalSample
{
    float accelX;
    float accelY;
    float accelZ;
    float strain;
    float temperature;
    float roofDistance;
};

static StatisticalSample statBuffer[STAT_XGB_WINDOW];
static int statCount = 0;
static int statWriteIndex = 0;

// Final binary Deep-Learning state used by the demo fusion.
// 0 = normal, 1 = anomaly.
// This is derived from the already-trained LSTM/VAE flags.
// GRU remains a continuous trajectory-error signal and is not
// given an invented binary threshold here.
static int gDLState = 0;
static int gMLClass = 0;
static float gMLProbability[3] = {0.0f, 0.0f, 0.0f};
static int gFinalState = 0; // 0 normal, 1 warning, 2 critical

// ============================================================
// ESP-NOW CONFIGURATION
// ============================================================
#define ESPNOW_CHANNEL 1
#define NODE_ID 1

// CONFIRMED RECEIVER MAC: 30:30:F9:69:EF:28
uint8_t receiverMAC[] = {
    0x30, 0x30, 0xF9, 0x69, 0xEF, 0x28
};

// Latest AI values exported for ESP-NOW
static float gLstmMSE = 0.0f;
static float gVaeMSE = 0.0f;
static float gGruTrajectoryError = 0.0f;
static uint8_t gLstmFlag = 0;
static uint8_t gVaeFlag = 0;
static uint32_t gPacketSequence = 0;

typedef struct __attribute__((packed))
{
    uint8_t packetType;
    uint8_t nodeId;
    uint32_t sequence;
    uint32_t timestamp;

    float rotation_x;
    float rotation_y;
    float rotation_z;
    float acceleration_x;
    float acceleration_y;
    float acceleration_z;
    float temperature;
    float humidity;
    float roof_convergence_cm;
    float raindrop;
    float vibration;
    float soil20cm;
    float soil40cm;
    float soil60cm;
    float strain;

    float lstmMSE;
    float vaeMSE;
    float gruTrajectoryError;
    uint8_t lstmFlag;
    uint8_t vaeFlag;
    uint8_t dlState;
    uint8_t mlClass;
    float mlProbability[3];
    uint8_t finalState;
} TelemetryPacket;



// ============================================================
// LSTM RECONSTRUCTION BUFFER
// ============================================================

static float lstmReconstruction[24][27];

// ============================================================
// VAE RECONSTRUCTION BUFFER
// ============================================================

static float vaeReconstruction[24][27];


// ============================================================
// TRAINING-DOMAIN MEANS
// ============================================================

static constexpr float TRAIN_ROT_X_MEAN =
    1.52259477f;

static constexpr float TRAIN_ROT_Y_MEAN =
    5.92748742f;

static constexpr float TRAIN_ROT_Z_MEAN =
    76.3799514f;

static constexpr float TRAIN_ACC_X_MEAN =
    -4.74483835e-02f;

static constexpr float TRAIN_ACC_Y_MEAN =
    -4.58351528e-02f;

static constexpr float TRAIN_ACC_Z_MEAN =
    -4.26466457e-05f;

static constexpr float TRAIN_TEMP_MEAN =
    31.5543617f;

static constexpr float TRAIN_HUM_MEAN =
    71.8245008f;


// ============================================================
// PROXY VALUES
// ============================================================
// These are the same prototype values used by the existing
// feature-generation stage for unavailable channels.
// ============================================================

static constexpr float PROXY_RAINDROP =
    2.32127353e-01f;

static constexpr float PROXY_VIBRATION =
    2.17325519e-01f;

static constexpr float PROXY_SOIL20 =
    48.9207845f;

static constexpr float PROXY_SOIL40 =
    92.2472931f;

static constexpr float PROXY_SOIL60 =
    94.8240507f;

static constexpr float PROXY_STRAIN =
    110.0f;


// ============================================================
// DEMO ALIGNMENT
// ============================================================

#define DEMO_ALIGNMENT_MODE 1


// ============================================================
// STARTUP BASELINE
// ============================================================

static constexpr int BASELINE_SAMPLES =
    60;

static constexpr int BASELINE_DELAY_MS =
    50;


float baselineRoll = 0.0f;
float baselinePitch = 0.0f;

float baselineLinearX = 0.0f;
float baselineLinearY = 0.0f;
float baselineLinearZ = 0.0f;

float baselineTemperature = 25.0f;
float baselineHumidity = 50.0f;

float gyroZBias = 0.0f;

float yawDelta = 0.0f;

unsigned long previousIMUTime = 0;

bool deploymentBaselineReady = false;


// ============================================================
// YAW LIMIT
// ============================================================

static constexpr float YAW_DEMO_LIMIT_DEG =
    30.0f;


// ============================================================
// ACCELERATION NOISE FILTER
// ============================================================

static constexpr float ACCEL_NOISE_DEADBAND =
    0.015f;


float suppressAccelerationNoise(float delta)
{
    if (fabsf(delta) < ACCEL_NOISE_DEADBAND)
    {
        return 0.0f;
    }

    return delta;
}


// ============================================================
// ICM WRITE
// ============================================================

void icmWriteByte(
    uint8_t reg,
    uint8_t value
)
{
    Wire.beginTransmission(ICM_ADDR);

    Wire.write(reg);
    Wire.write(value);

    Wire.endTransmission();
}


// ============================================================
// ICM READ BYTE
// ============================================================

uint8_t icmReadByte(
    uint8_t reg
)
{
    Wire.beginTransmission(ICM_ADDR);

    Wire.write(reg);

    Wire.endTransmission(false);

    Wire.requestFrom(
        ICM_ADDR,
        (uint8_t)1
    );

    if (Wire.available())
    {
        return Wire.read();
    }

    return 0;
}


// ============================================================
// ICM READ MULTIPLE BYTES
// ============================================================

void icmReadBytes(
    uint8_t reg,
    uint8_t *buffer,
    uint8_t length
)
{
    Wire.beginTransmission(ICM_ADDR);

    Wire.write(reg);

    Wire.endTransmission(false);

    Wire.requestFrom(
        ICM_ADDR,
        length
    );

    for (uint8_t i = 0; i < length; i++)
    {
        if (Wire.available())
        {
            buffer[i] = Wire.read();
        }
        else
        {
            buffer[i] = 0;
        }
    }
}


// ============================================================
// INITIALIZE ICM-20689
// ============================================================

bool initializeICM20689()
{
    Serial.println();
    Serial.println(
        "Initializing ICM-20689..."
    );


    uint8_t whoAmI =
        icmReadByte(
            WHO_AM_I_REG
        );


    Serial.print(
        "WHO_AM_I = 0x"
    );

    Serial.println(
        whoAmI,
        HEX
    );


    if (whoAmI != 0x98)
    {
        Serial.println(
            "WARNING: ICM-20689 WHO_AM_I mismatch."
        );

        Serial.println(
            "Expected 0x98."
        );

        Serial.println(
            "Continuing anyway..."
        );
    }


    // --------------------------------------------------------
    // Wake up
    // --------------------------------------------------------

    // Same wake-up command as the proven standalone ICM-20689 test.
    icmWriteByte(
        PWR_MGMT_1,
        0x00
    );

    delay(100);


    // --------------------------------------------------------
    // Accelerometer ±2g
    // Same configuration as the proven standalone test.
    // 0x00 -> ±2g -> 16384 LSB/g
    // --------------------------------------------------------

    icmWriteByte(
        ACCEL_CONFIG,
        0x00
    );


    // --------------------------------------------------------
    // Gyroscope ±250 dps
    // Same configuration as the proven standalone test.
    // 0x00 -> ±250 dps -> 131 LSB/dps
    // --------------------------------------------------------

    icmWriteByte(
        GYRO_CONFIG,
        0x00
    );


    // --------------------------------------------------------
    // Digital low-pass filter
    // --------------------------------------------------------

    icmWriteByte(
        CONFIG_REG,
        0x03
    );


    icmWriteByte(
        ACCEL_CONFIG2,
        0x03
    );


    // --------------------------------------------------------
    // Sample divider
    // --------------------------------------------------------

    icmWriteByte(
        SMPLRT_DIV,
        9
    );


    delay(100);


    Serial.println(
        "ICM-20689 initialized."
    );


    return true;
}


// ============================================================
// READ ACCELERATION
// ============================================================

void readICMAcceleration(
    float &ax,
    float &ay,
    float &az
)
{
    uint8_t data[6];


    icmReadBytes(
        ACCEL_XOUT_H,
        data,
        6
    );


    int16_t rawX =
        ((int16_t)data[0] << 8)
        |
        data[1];


    int16_t rawY =
        ((int16_t)data[2] << 8)
        |
        data[3];


    int16_t rawZ =
        ((int16_t)data[4] << 8)
        |
        data[5];


    // ±2g
    // 16384 LSB/g
    // This is exactly the scale used by the standalone
    // ICM-20689 test that produced the normal readings.

    const float ACCEL_SCALE =
        9.80665f / 16384.0f;


    ax =
        (float)rawX *
        ACCEL_SCALE;


    ay =
        (float)rawY *
        ACCEL_SCALE;


    az =
        (float)rawZ *
        ACCEL_SCALE;
}


// ============================================================
// READ GYROSCOPE
// ============================================================

void readICMGyroscope(
    float &gx,
    float &gy,
    float &gz
)
{
    uint8_t data[6];


    icmReadBytes(
        GYRO_XOUT_H,
        data,
        6
    );


    int16_t rawX =
        ((int16_t)data[0] << 8)
        |
        data[1];


    int16_t rawY =
        ((int16_t)data[2] << 8)
        |
        data[3];


    int16_t rawZ =
        ((int16_t)data[4] << 8)
        |
        data[5];


    // ±250 dps
    // 131 LSB/dps
    // This is exactly the scale used by the standalone
    // ICM-20689 test that produced the normal readings.

    const float GYRO_SCALE =
        1.0f / 131.0f;


    gx =
        (float)rawX *
        GYRO_SCALE;


    gy =
        (float)rawY *
        GYRO_SCALE;


    gz =
        (float)rawZ *
        GYRO_SCALE;
}


// ============================================================
// READ ICM TEMPERATURE
// ============================================================

float readICMTemperature()
{
    uint8_t data[2];


    icmReadBytes(
        TEMP_OUT_H,
        data,
        2
    );


    int16_t raw =
        ((int16_t)data[0] << 8)
        |
        data[1];


    // ICM-20689 temperature conversion used by the
    // proven standalone test program.
    float temperature =
        ((float)raw / 326.8f)
        +
        25.0f;


    return temperature;
}


// ============================================================
// CALCULATE ORIENTATION
// ============================================================

void calculateOrientation(
    float ax,
    float ay,
    float az,
    float &roll,
    float &pitch
)
{
    roll =
        atan2f(
            ay,
            az
        )
        *
        180.0f
        /
        PI;


    pitch =
        atan2f(
            -ax,
            sqrtf(
                ay * ay +
                az * az
            )
        )
        *
        180.0f
        /
        PI;
}


// ============================================================
// GRAVITY COMPENSATION
// ============================================================

void calculateLinearAcceleration(
    float ax,
    float ay,
    float az,
    float roll,
    float pitch,
    float &linearX,
    float &linearY,
    float &linearZ
)
{
    float rollRad =
        roll *
        PI /
        180.0f;


    float pitchRad =
        pitch *
        PI /
        180.0f;


    float gx =
        -sinf(pitchRad)
        *
        9.80665f;


    float gy =
        sinf(rollRad)
        *
        cosf(pitchRad)
        *
        9.80665f;


    float gz =
        cosf(rollRad)
        *
        cosf(pitchRad)
        *
        9.80665f;


    linearX =
        ax - gx;


    linearY =
        ay - gy;


    linearZ =
        az - gz;
}


// ============================================================
// UPDATE YAW
// ============================================================

void updateYaw(
    float gyroZ
)
{
    unsigned long now =
        millis();


    if (previousIMUTime == 0)
    {
        previousIMUTime =
            now;

        return;
    }


    float dt =
        (now - previousIMUTime)
        /
        1000.0f;


    previousIMUTime =
        now;


    float correctedGyroZ =
        gyroZ -
        gyroZBias;


    if (
        fabsf(correctedGyroZ)
        <
        0.02f
    )
    {
        correctedGyroZ =
            0.0f;
    }


    yawDelta +=
        correctedGyroZ *
        dt;
}


// ============================================================
// BASELINE CALIBRATION
// ============================================================

void calibrateDeploymentBaseline()
{
    Serial.println();
    Serial.println(
        "=============================================="
    );

    Serial.println(
        "      SENSOR BASELINE CALIBRATION"
    );

    Serial.println(
        "      KEEP NODE COMPLETELY STILL"
    );

    Serial.println(
        "=============================================="
    );


    delay(1000);


    float sumRoll = 0.0f;
    float sumPitch = 0.0f;

    float sumLinearX = 0.0f;
    float sumLinearY = 0.0f;
    float sumLinearZ = 0.0f;

    float sumTemperature = 0.0f;
    float sumHumidity = 0.0f;

    float sumGyroZ = 0.0f;

    int validBME = 0;


    for (
        int i = 0;
        i < BASELINE_SAMPLES;
        i++
    )
    {
        float ax;
        float ay;
        float az;

        float gx;
        float gy;
        float gz;


        readICMAcceleration(
            ax,
            ay,
            az
        );


        readICMGyroscope(
            gx,
            gy,
            gz
        );


        float roll;
        float pitch;


        calculateOrientation(
            ax,
            ay,
            az,
            roll,
            pitch
        );


        float linearX;
        float linearY;
        float linearZ;


        calculateLinearAcceleration(
            ax,
            ay,
            az,
            roll,
            pitch,
            linearX,
            linearY,
            linearZ
        );


        sumRoll +=
            roll;

        sumPitch +=
            pitch;


        sumLinearX +=
            linearX;

        sumLinearY +=
            linearY;

        sumLinearZ +=
            linearZ;


        sumGyroZ +=
            gz;


        float temperature =
            bme.readTemperature();


        float humidity =
            bme.readHumidity();


        if (
            isfinite(temperature)
            &&
            isfinite(humidity)
        )
        {
            sumTemperature +=
                temperature;

            sumHumidity +=
                humidity;

            validBME++;
        }


        delay(
            BASELINE_DELAY_MS
        );
    }


    baselineRoll =
        sumRoll /
        BASELINE_SAMPLES;


    baselinePitch =
        sumPitch /
        BASELINE_SAMPLES;


    baselineLinearX =
        sumLinearX /
        BASELINE_SAMPLES;


    baselineLinearY =
        sumLinearY /
        BASELINE_SAMPLES;


    baselineLinearZ =
        sumLinearZ /
        BASELINE_SAMPLES;


    gyroZBias =
        sumGyroZ /
        BASELINE_SAMPLES;


    if (validBME > 0)
    {
        baselineTemperature =
            sumTemperature /
            validBME;


        baselineHumidity =
            sumHumidity /
            validBME;
    }


    yawDelta =
        0.0f;


    previousIMUTime =
        millis();


    deploymentBaselineReady =
        true;


    Serial.println();
    Serial.println(
        "------------ BASELINE RESULT ------------"
    );


    Serial.printf(
        "Roll baseline      : %.6f deg\n",
        baselineRoll
    );


    Serial.printf(
        "Pitch baseline     : %.6f deg\n",
        baselinePitch
    );


    Serial.printf(
        "Linear X baseline  : %.6f m/s^2\n",
        baselineLinearX
    );


    Serial.printf(
        "Linear Y baseline  : %.6f m/s^2\n",
        baselineLinearY
    );


    Serial.printf(
        "Linear Z baseline  : %.6f m/s^2\n",
        baselineLinearZ
    );


    Serial.printf(
        "Gyro Z bias        : %.6f deg/s\n",
        gyroZBias
    );


    Serial.printf(
        "Temperature        : %.6f C\n",
        baselineTemperature
    );


    Serial.printf(
        "Humidity           : %.6f %%\n",
        baselineHumidity
    );


    Serial.println(
        "------------------------------------------"
    );


    Serial.println(
        "Baseline calibration COMPLETE."
    );


    Serial.println(
        "=========================================="
    );
}


// ============================================================
// READ ROOF DISTANCE
// ============================================================

float readRoofDistanceCm()
{
    VL53L0X_RangingMeasurementData_t measure;


    vl53.rangingTest(
        &measure,
        false
    );


    if (
        measure.RangeStatus != 4
    )
    {
        return
            (float)measure.RangeMilliMeter
            /
            10.0f;
    }


    // Sensor invalid/out of range
    return 300.0f;
}


// ============================================================
// READ CURRENT SENSOR FRAME
// ============================================================

void readCurrentSensorFrame(
    SensorFrame &frame
)
{
    // --------------------------------------------------------
    // IMU
    // --------------------------------------------------------

    float ax;
    float ay;
    float az;

    float gx;
    float gy;
    float gz;


    readICMAcceleration(
        ax,
        ay,
        az
    );


    readICMGyroscope(
        gx,
        gy,
        gz
    );


    // --------------------------------------------------------
    // Orientation
    // --------------------------------------------------------

    float roll;
    float pitch;


    calculateOrientation(
        ax,
        ay,
        az,
        roll,
        pitch
    );


    updateYaw(
        gz
    );


    // --------------------------------------------------------
    // Linear acceleration
    // --------------------------------------------------------

    float linearX;
    float linearY;
    float linearZ;


    calculateLinearAcceleration(
        ax,
        ay,
        az,
        roll,
        pitch,
        linearX,
        linearY,
        linearZ
    );


    // --------------------------------------------------------
    // BME280
    // --------------------------------------------------------

    float temperature =
        bme.readTemperature();


    float humidity =
        bme.readHumidity();


   // --------------------------------------------------------
    // Roof distance
    // --------------------------------------------------------

    float roofDistance = readRoofDistanceCm();

    // Convert physical sensor distance into the model's
    // reference-based roof convergence value.
    float roofConvergence =
        ROOF_REFERENCE_CM - roofDistance;

    // ========================================================
    // TRAINING-DOMAIN ALIGNMENT
    // ========================================================

#if DEMO_ALIGNMENT_MODE

    float modelRotationX =
        TRAIN_ROT_X_MEAN
        +
        (roll - baselineRoll);


    float modelRotationY =
        TRAIN_ROT_Y_MEAN
        +
        (pitch - baselinePitch);


    float limitedYawDelta =
        yawDelta;


    if (
        limitedYawDelta >
        YAW_DEMO_LIMIT_DEG
    )
    {
        limitedYawDelta =
            YAW_DEMO_LIMIT_DEG;
    }


    if (
        limitedYawDelta <
        -YAW_DEMO_LIMIT_DEG
    )
    {
        limitedYawDelta =
            -YAW_DEMO_LIMIT_DEG;
    }


    float modelRotationZ =
        TRAIN_ROT_Z_MEAN
        +
        limitedYawDelta;


    // --------------------------------------------------------
    // Acceleration changes
    // --------------------------------------------------------

    float deltaAccelerationX =
        linearX -
        baselineLinearX;


    float deltaAccelerationY =
        linearY -
        baselineLinearY;


    float deltaAccelerationZ =
        linearZ -
        baselineLinearZ;


    deltaAccelerationX =
        suppressAccelerationNoise(
            deltaAccelerationX
        );


    deltaAccelerationY =
        suppressAccelerationNoise(
            deltaAccelerationY
        );


    deltaAccelerationZ =
        suppressAccelerationNoise(
            deltaAccelerationZ
        );


    float modelAccelerationX =
        TRAIN_ACC_X_MEAN
        +
        deltaAccelerationX;


    float modelAccelerationY =
        TRAIN_ACC_Y_MEAN
        +
        deltaAccelerationY;


    float modelAccelerationZ =
        TRAIN_ACC_Z_MEAN
        +
        deltaAccelerationZ;


    // --------------------------------------------------------
    // Temperature / humidity
    // --------------------------------------------------------

    float modelTemperature =
        TRAIN_TEMP_MEAN
        +
        (
            temperature -
            baselineTemperature
        );


    float modelHumidity =
        TRAIN_HUM_MEAN
        +
        (
            humidity -
            baselineHumidity
        );


    // --------------------------------------------------------
    // Create frame
    // --------------------------------------------------------

    frame.rotation_x =
        modelRotationX;


    frame.rotation_y =
        modelRotationY;


    frame.rotation_z =
        modelRotationZ;


    frame.acceleration_x =
        modelAccelerationX;


    frame.acceleration_y =
        modelAccelerationY;


    frame.acceleration_z =
        modelAccelerationZ;


    frame.temperature =
        modelTemperature;


    frame.humidity =
        modelHumidity;


    frame.roof_convergence_cm =
    roofConvergence;


    // --------------------------------------------------------
    // Proxy channels
    // --------------------------------------------------------

    frame.raindrop =
        PROXY_RAINDROP;


    frame.vibration =
        PROXY_VIBRATION;


    frame.soil20cm =
        PROXY_SOIL20;


    frame.soil40cm =
        PROXY_SOIL40;


    frame.soil60cm =
        PROXY_SOIL60;


    frame.strain =
        PROXY_STRAIN;

#else

    // --------------------------------------------------------
    // Raw physical values
    // --------------------------------------------------------

    frame.rotation_x =
        roll;


    frame.rotation_y =
        pitch;


    frame.rotation_z =
        yawDelta;


    frame.acceleration_x =
        linearX;


    frame.acceleration_y =
        linearY;


    frame.acceleration_z =
        linearZ;


    frame.temperature =
        temperature;


    frame.humidity =
        humidity;


    frame.roof_convergence_cm =
    roofConvergence;


    frame.raindrop =
        PROXY_RAINDROP;


    frame.vibration =
        PROXY_VIBRATION;


    frame.soil20cm =
        PROXY_SOIL20;


    frame.soil40cm =
        PROXY_SOIL40;


    frame.soil60cm =
        PROXY_SOIL60;


    frame.strain =
        PROXY_STRAIN;

#endif
}


// ============================================================
// PRINT SENSOR FRAME
// ============================================================

void printCurrentSensorFrame(
    const SensorFrame &frame
)
{
    Serial.println();
    Serial.println(
        "------------- SENSOR DATA -------------"
    );


    Serial.print(
        "Rotation X : "
    );

    Serial.print(
        frame.rotation_x,
        3
    );

    Serial.println(
        " deg"
    );


    Serial.print(
        "Rotation Y : "
    );

    Serial.print(
        frame.rotation_y,
        3
    );

    Serial.println(
        " deg"
    );


    Serial.print(
        "Rotation Z : "
    );

    Serial.print(
        frame.rotation_z,
        3
    );

    Serial.println(
        " deg"
    );


    Serial.print(
        "Accel X    : "
    );

    Serial.print(
        frame.acceleration_x,
        4
    );

    Serial.println(
        " m/s^2"
    );


    Serial.print(
        "Accel Y    : "
    );

    Serial.print(
        frame.acceleration_y,
        4
    );

    Serial.println(
        " m/s^2"
    );


    Serial.print(
        "Accel Z    : "
    );

    Serial.print(
        frame.acceleration_z,
        4
    );

    Serial.println(
        " m/s^2"
    );


    Serial.print(
        "Temperature: "
    );

    Serial.print(
        frame.temperature,
        2
    );

    Serial.println(
        " C"
    );


    Serial.print(
        "Humidity   : "
    );

    Serial.print(
        frame.humidity,
        2
    );

    Serial.println(
        " %"
    );


    Serial.print(
        "Roof Dist. : "
    );

    Serial.print(
        frame.roof_convergence_cm,
        2
    );

    Serial.println(
        " cm"
    );


    Serial.println(
        "----------------------------------------"
    );
}


// ============================================================
// PRINT 27 FEATURE AUDIT
// ============================================================

void printFeatureAudit()
{
    Serial.println();
    Serial.println(
        "========== LSTM INPUT AUDIT =========="
    );


    for (int j = 0; j < 27; j++)
    {
        float minVal =
            featureBuffer.data[0][j];


        float maxVal =
            featureBuffer.data[0][j];


        float sumVal =
            0.0f;


        for (int i = 0; i < 24; i++)
        {
            float v =
                featureBuffer.data[i][j];


            if (v < minVal)
            {
                minVal =
                    v;
            }


            if (v > maxVal)
            {
                maxVal =
                    v;
            }


            sumVal +=
                v;
        }


        float meanVal =
            sumVal /
            24.0f;


        Serial.print(
            "Feature["
        );


        if (j < 10)
        {
            Serial.print(
                "0"
            );
        }


        Serial.print(
            j
        );


        Serial.print(
            "] mean="
        );


        Serial.print(
            meanVal,
            5
        );


        Serial.print(
            " min="
        );


        Serial.print(
            minVal,
            5
        );


        Serial.print(
            " max="
        );


        Serial.println(
            maxVal,
            5
        );
    }


    Serial.println(
        "======================================"
    );
}



// ============================================================
// STATISTICAL XGB BUFFER HELPERS
// ============================================================

void addStatisticalSample(const SensorFrame &frame)
{
    statBuffer[statWriteIndex].accelX = frame.acceleration_x;
    statBuffer[statWriteIndex].accelY = frame.acceleration_y;
    statBuffer[statWriteIndex].accelZ = frame.acceleration_z;
    statBuffer[statWriteIndex].strain = frame.strain;
    statBuffer[statWriteIndex].temperature = frame.temperature;
    statBuffer[statWriteIndex].roofDistance = frame.roof_convergence_cm;

    statWriteIndex++;
    if (statWriteIndex >= STAT_XGB_WINDOW)
        statWriteIndex = 0;

    if (statCount < STAT_XGB_WINDOW)
        statCount++;
}

float statMean(int field)
{
    if (statCount == 0) return 0.0f;

    float sum = 0.0f;
    for (int i = 0; i < statCount; ++i)
    {
        float v = 0.0f;
        switch (field)
        {
            case 0: v = statBuffer[i].accelX; break;
            case 1: v = statBuffer[i].accelY; break;
            case 2: v = statBuffer[i].accelZ; break;
            case 3: v = statBuffer[i].strain; break;
            case 4: v = statBuffer[i].temperature; break;
            case 5: v = statBuffer[i].roofDistance; break;
        }
        sum += v;
    }
    return sum / (float)statCount;
}

float statStd(int field)
{
    if (statCount <= 1) return 0.0f;

    float mean = statMean(field);
    float sum = 0.0f;

    for (int i = 0; i < statCount; ++i)
    {
        float v = 0.0f;
        switch (field)
        {
            case 0: v = statBuffer[i].accelX; break;
            case 1: v = statBuffer[i].accelY; break;
            case 2: v = statBuffer[i].accelZ; break;
            case 3: v = statBuffer[i].strain; break;
            case 4: v = statBuffer[i].temperature; break;
            case 5: v = statBuffer[i].roofDistance; break;
        }

        float d = v - mean;
        sum += d * d;
    }

    return sqrtf(sum / (float)statCount);
}

float statMax(int field)
{
    if (statCount == 0) return 0.0f;

    float maximum = -3.4028235e38f;

    for (int i = 0; i < statCount; ++i)
    {
        float v = 0.0f;
        switch (field)
        {
            case 0: v = statBuffer[i].accelX; break;
            case 1: v = statBuffer[i].accelY; break;
            case 2: v = statBuffer[i].accelZ; break;
            case 3: v = statBuffer[i].strain; break;
            case 4: v = statBuffer[i].temperature; break;
            case 5: v = statBuffer[i].roofDistance; break;
        }

        if (v > maximum) maximum = v;
    }

    return maximum;
}

void buildStatXGBFeatures(
    const SensorFrame &currentFrame,
    float features[ML_XGB_FEATURES]
)
{
    // Exact model order:
    // 0-3   Accel X live/mean/std/max
    // 4-7   Accel Y live/mean/std/max
    // 8-11  Accel Z live/mean/std/max
    // 12-15 Strain live/mean/std/max
    // 16-19 Temp live/mean/std/max
    // 20-23 Roof convergence live/mean/std/max

    features[0] = currentFrame.acceleration_x;
    features[1] = statMean(0);
    features[2] = statStd(0);
    features[3] = statMax(0);

    features[4] = currentFrame.acceleration_y;
    features[5] = statMean(1);
    features[6] = statStd(1);
    features[7] = statMax(1);

    features[8] = currentFrame.acceleration_z;
    features[9] = statMean(2);
    features[10] = statStd(2);
    features[11] = statMax(2);

    features[12] = currentFrame.strain;
    features[13] = statMean(3);
    features[14] = statStd(3);
    features[15] = statMax(3);

    features[16] = currentFrame.temperature;
    features[17] = statMean(4);
    features[18] = statStd(4);
    features[19] = statMax(4);

    features[20] = currentFrame.roof_convergence_cm;
    features[21] = statMean(5);
    features[22] = statStd(5);
    features[23] = statMax(5);
}

// ============================================================
// DEMO FUSION LOGIC
//
// ML class:
//   0 = model class 0
//   1 = model class 1
//   2 = model class 2
//
// DL state:
//   0 = LSTM/VAE normal
//   1 = LSTM or VAE anomaly
//
// Priority:
//   ML 2  -> CRITICAL immediately
//   else DL 1 OR ML 1 -> WARNING
//   else -> NORMAL
// ============================================================

int calculateFinalState(int dlState, int mlClass)
{
    if (mlClass == 2)
        return 2; // CRITICAL

    if (dlState == 1 || mlClass == 1)
        return 1; // WARNING

    return 0;     // NORMAL
}

void printFinalFusionState(
    int dlState,
    int mlClass,
    int finalState
)
{
    Serial.println();
    Serial.println("================================================");
    Serial.println("              FINAL AI FUSION");
    Serial.println("================================================");

    Serial.print("DL STATE        : ");
    Serial.println(dlState);

    Serial.print("ML CLASS        : ");
    Serial.println(mlClass);

    Serial.print("ML PROB CLASS 0 : ");
    Serial.println(gMLProbability[0], 6);

    Serial.print("ML PROB CLASS 1 : ");
    Serial.println(gMLProbability[1], 6);

    Serial.print("ML PROB CLASS 2 : ");
    Serial.println(gMLProbability[2], 6);

    Serial.println();

    Serial.print("FINAL STATE     : ");

    if (finalState == 2)
    {
        Serial.println("CRITICAL");
        Serial.println("!!! IMMEDIATE ALERT !!!");
    }
    else if (finalState == 1)
    {
        Serial.println("WARNING");
        Serial.println("!! WARNING CONDITION !!");
    }
    else
    {
        Serial.println("NORMAL");
        Serial.println("SYSTEM NORMAL");
    }

    Serial.println("================================================");
}

// ============================================================
// STATISTICAL XGB INFERENCE
// ============================================================

void runStatisticalXGB(
    const SensorFrame &currentFrame,
    int dlState
)
{
#if ENABLE_STAT_XGB

    if (statCount < STAT_XGB_WINDOW)
    {
        Serial.print("STAT XGB BUFFER: ");
        Serial.print(statCount);
        Serial.print(" / ");
        Serial.println(STAT_XGB_WINDOW);
        return;
    }

    float mlFeatures[ML_XGB_FEATURES];

    buildStatXGBFeatures(
        currentFrame,
        mlFeatures
    );

    MLXGBResult mlResult;

    unsigned long start = micros();

    bool ok = runMLXGB(
        mlFeatures,
        mlResult
    );

    unsigned long elapsed = micros() - start;

    if (!ok)
    {
        Serial.println("STATISTICAL XGB INFERENCE FAILED.");
        return;
    }

    gMLClass = mlResult.predictionClass;

    gMLProbability[0] = mlResult.probability[0];
    gMLProbability[1] = mlResult.probability[1];
    gMLProbability[2] = mlResult.probability[2];

    gDLState = dlState;

    gFinalState =
        calculateFinalState(
            gDLState,
            gMLClass
        );

    Serial.println();
    Serial.println("------------- STATISTICAL XGB -------------");

    Serial.print("Roof live       : ");
    Serial.print(mlFeatures[20], 2);
    Serial.println(" cm");

    Serial.print("Roof mean       : ");
    Serial.print(mlFeatures[21], 2);
    Serial.println(" cm");

    Serial.print("Roof std        : ");
    Serial.print(mlFeatures[22], 4);
    Serial.println(" cm");

    Serial.print("Roof max        : ");
    Serial.print(mlFeatures[23], 2);
    Serial.println(" cm");

    Serial.println();

    Serial.print("Class 0         : ");
    Serial.println(mlResult.probability[0], 6);

    Serial.print("Class 1         : ");
    Serial.println(mlResult.probability[1], 6);

    Serial.print("Class 2         : ");
    Serial.println(mlResult.probability[2], 6);

    Serial.print("ML PREDICTED    : ");
    Serial.println(mlResult.predictionClass);

    Serial.print("Inference Time  : ");
    Serial.print(elapsed / 1000.0f, 3);
    Serial.println(" ms");

    printFinalFusionState(
        gDLState,
        gMLClass,
        gFinalState
    );

#endif
}

// ============================================================
// LSTM INFERENCE
// ============================================================

void runAIInference(const SensorFrame &currentFrame)
{
    if (!bufferReady(featureBuffer))
    {
        Serial.println("ERROR: AI buffer not ready.");
        return;
    }

    Serial.println();
    Serial.println("========================================");
    Serial.println("       EDGE AI FUSION PIPELINE");
    Serial.println("========================================");
    Serial.println("24 samples available.");
    Serial.println("27 features/sample.");

    // --------------------------------------------------------
    // Outputs that will be joined into the XGBoost fusion input
    // --------------------------------------------------------
    float lstmMSE = 0.0f;
    float vaeMSE  = 0.0f;
    int lstmFlag  = 0;
    int vaeFlag   = 0;

    // GRU trajectory prediction error.
    // The production XGBoost fusion model expects this exact feature.
    float gruTrajectoryError = 0.0f;
    float gruPredictionScaled[GRU_OUTPUTS] = {0.0f, 0.0f, 0.0f};

    // ========================================================
    // LSTM AUTOENCODER
    // ========================================================
#if ENABLE_LSTM
    Serial.println();
    Serial.println("------------- LSTM-AE ------------------");

    unsigned long lstmStart = micros();
    bool lstmOK = runLSTMAutoencoder(
        featureBuffer,
        lstmReconstruction
    );
    unsigned long lstmTime = micros() - lstmStart;

    constexpr float LSTM_THRESHOLD = 0.62542055f;

    if (lstmOK)
    {
        lstmMSE = calculateLSTM_MSE(
            featureBuffer,
            lstmReconstruction
        );

        lstmFlag = (lstmMSE >= LSTM_THRESHOLD) ? 1 : 0;

        Serial.print("LSTM MSE       : ");
        Serial.println(lstmMSE, 8);
        Serial.print("LSTM Threshold : ");
        Serial.println(LSTM_THRESHOLD, 8);
        Serial.print("Inference Time : ");
        Serial.print(lstmTime / 1000.0f, 2);
        Serial.println(" ms");
        Serial.print("LSTM FLAG      : ");
        Serial.println(lstmFlag);
        Serial.print("LSTM STATUS    : ");
        Serial.println(lstmFlag ? "ANOMALY" : "NORMAL");
    }
    else
    {
        Serial.println("LSTM inference FAILED.");
    }
#else
    Serial.println("LSTM DISABLED");
#endif

    // ========================================================
    // VAE
    // ========================================================
#if ENABLE_VAE
    Serial.println();
    Serial.println("------------- VAE ----------------------");

    unsigned long vaeStart = micros();
    bool vaeOK = runVAE(
        featureBuffer,
        vaeReconstruction
    );
    unsigned long vaeTime = micros() - vaeStart;

    constexpr float VAE_THRESHOLD = 0.55071914f;

    if (vaeOK)
    {
        vaeMSE = calculateVAE_MSE(
            featureBuffer,
            vaeReconstruction
        );

        vaeFlag = (vaeMSE >= VAE_THRESHOLD) ? 1 : 0;

        Serial.print("VAE MSE        : ");
        Serial.println(vaeMSE, 8);
        Serial.print("VAE Threshold  : ");
        Serial.println(VAE_THRESHOLD, 8);
        Serial.print("Inference Time : ");
        Serial.print(vaeTime / 1000.0f, 2);
        Serial.println(" ms");
        Serial.print("VAE FLAG       : ");
        Serial.println(vaeFlag);
        Serial.print("VAE STATUS     : ");
        Serial.println(vaeFlag ? "ANOMALY" : "NORMAL");
    }
    else
    {
        Serial.println("VAE inference FAILED.");
    }
#else
    Serial.println("VAE DISABLED");
#endif

    // ========================================================
    // BINARY DL STATE FOR DEMO FUSION
    // LSTM/VAE are binary anomaly detectors.
    // GRU is retained as a continuous forecast error.
    // ========================================================

    int dlState = (lstmFlag == 1 || vaeFlag == 1) ? 1 : 0;

    Serial.println();
    Serial.println("------------- DL SUMMARY ----------------");
    Serial.print("DL STATE = ");
    Serial.println(dlState);
    Serial.println(
        dlState ? "DL STATUS = ANOMALY" : "DL STATUS = NORMAL"
    );

    // ========================================================
    // GRU FORECASTER
    // ========================================================
#if ENABLE_GRU
    Serial.println();
    Serial.println("------------- GRU FORECASTER -------------");

    // IMPORTANT:
    // featureBuffer stores the 27-feature vector AFTER the LSTM/VAE
    // scaler has been applied. The GRU inference function performs
    // ITS OWN scaler internally. Passing featureBuffer directly
    // would therefore scale the data twice and create a huge GRU error.
    //
    // Undo the LSTM/VAE scaling for the first six features, recovering
    // the original training-domain values. runGRUForecast() then applies
    // the GRU scaler exactly once.

    static constexpr float LSTM_INPUT_MEAN[6] =
    {
        1.52259477f,
        5.92748742f,
        76.3799514f,
        -0.0474483835f,
        -0.0458351528f,
        -0.0000426466457f
    };

    static constexpr float LSTM_INPUT_SCALE[6] =
    {
        0.884871150f,
        0.993920567f,
        6.73084209f,
        0.0113465097f,
        0.0115597561f,
        0.00241708584f
    };

    float gruInput[GRU_SEQ][GRU_INPUT_FEATURES];

    for (int t = 0; t < GRU_SEQ; ++t)
    {
        for (int f = 0; f < GRU_INPUT_FEATURES; ++f)
        {
            gruInput[t][f] =
                featureBuffer.data[t][f] * LSTM_INPUT_SCALE[f]
                + LSTM_INPUT_MEAN[f];
        }
    }

    // --------------------------------------------------------
    // GRU INPUT AUDIT
    // --------------------------------------------------------
    Serial.println();
    Serial.println("========== GRU INPUT AUDIT =============");

    for (int t = 0; t < GRU_SEQ; ++t)
    {
        Serial.printf(
            "%02d | %.6f | %.6f | %.6f | %.6f | %.6f | %.6f\\n",
            t,
            gruInput[t][0],
            gruInput[t][1],
            gruInput[t][2],
            gruInput[t][3],
            gruInput[t][4],
            gruInput[t][5]
        );
    }

    Serial.println("-----------------------------------------");
    Serial.printf(
        "GRU LAST SAMPLE | X=%.6f | Y=%.6f | Z=%.6f\\n",
        gruInput[GRU_SEQ - 1][0],
        gruInput[GRU_SEQ - 1][1],
        gruInput[GRU_SEQ - 1][2]
    );
    Serial.println("=========================================");

    unsigned long gruStart = micros();

    bool gruOK =
        (runGRUForecast(
            gruInput,
            gruPredictionScaled
        ) == 0);

    if (gruOK)
    {
        float lastRotationRaw[GRU_OUTPUTS] = {
            gruInput[GRU_SEQ - 1][0],
            gruInput[GRU_SEQ - 1][1],
            gruInput[GRU_SEQ - 1][2]
        };

        gruTrajectoryError =
            calculateGRUTrajectoryError(
                gruPredictionScaled,
                lastRotationRaw
            );
    }

    unsigned long gruTime = micros() - gruStart;

    if (gruOK)
    {
        Serial.print("GRU Prediction X : ");
        Serial.println(gruPredictionScaled[0], 6);

        Serial.print("GRU Prediction Y : ");
        Serial.println(gruPredictionScaled[1], 6);

        Serial.print("GRU Prediction Z : ");
        Serial.println(gruPredictionScaled[2], 6);

        Serial.print("GRU Error        : ");
        Serial.println(gruTrajectoryError, 6);

        Serial.print("Inference Time   : ");
        Serial.print(gruTime / 1000.0f, 2);
        Serial.println(" ms");
    }
    else
    {
        Serial.println("GRU inference FAILED.");
    }
#else
    Serial.println("GRU DISABLED");
#endif

    // Export the latest AI values for ESP-NOW regardless of whether
    // GRU is enabled. This must run with ENABLE_GRU=1 as well.
    gLstmMSE = lstmMSE;
    gVaeMSE = vaeMSE;
    gGruTrajectoryError = gruTrajectoryError;
    gLstmFlag = (uint8_t)lstmFlag;
    gVaeFlag = (uint8_t)vaeFlag;

    // ========================================================
    // NEW STATISTICAL XGBOOST + DL FUSION
    // ========================================================
    // The old 14-feature XGB ensemble is intentionally NOT used here.
    // This demo uses the new 24-feature, 3-class statistical XGBoost.

    runStatisticalXGB(currentFrame, dlState);

    // ========================================================
    // FUSION INPUT AUDIT
    // ========================================================
    Serial.println();
    Serial.println("----------- FUSION INPUT AUDIT ---------");
    Serial.print("LSTM MSE             = "); Serial.println(lstmMSE, 6);
    Serial.print("LSTM FLAG            = "); Serial.println(lstmFlag);
    Serial.print("VAE MSE              = "); Serial.println(vaeMSE, 6);
    Serial.print("VAE FLAG             = "); Serial.println(vaeFlag);
    Serial.print("GRU TRAJECTORY ERROR = "); Serial.println(gruTrajectoryError, 6);
    Serial.println("----------------------------------------");

    Serial.print("Free Heap            = ");
    Serial.print(ESP.getFreeHeap());
    Serial.println(" bytes");

    Serial.println("========================================");

    // ========================================================
    // NEW STATISTICAL XGBOOST + DL FUSION
    // ========================================================
}


// ============================================================
// SETUP
// ============================================================

void setup()
{
    Serial.begin(
        115200
    );


    delay(
        2000
    );


    Serial.println();
    Serial.println(
        "========================================"
    );


    Serial.println(
        "   ESP32-S3 STRUCTURAL AI EDGE NODE"
    );


    Serial.println(
        "      LSTM + VAE + GRU + STAT-XGB"
    );


    Serial.println(
        "========================================"
    );


    // ========================================================
    // I2C
    // ========================================================

    Serial.println();
    Serial.println(
        "Initializing I2C..."
    );


    Wire.begin(
        SDA_PIN,
        SCL_PIN
    );


    Wire.setClock(
        400000
    );


    delay(
        100
    );


    Serial.println(
        "I2C initialized."
    );


    // ========================================================
    // ICM-20689
    // ========================================================

    if (
        !initializeICM20689()
    )
    {
        Serial.println(
            "ERROR: ICM initialization failed."
        );
    }


    // ========================================================
    // BME280
    // ========================================================

    Serial.println();
    Serial.println(
        "Initializing BME280..."
    );


    if (
        !bme.begin(0x76)
    )
    {
        Serial.println(
            "ERROR: BME280 not found!"
        );


        while (true)
        {
            delay(1000);
        }
    }


    Serial.println(
        "BME280 OK"
    );


    // ========================================================
    // VL53L0X
    // ========================================================

    Serial.println();
    Serial.println(
        "Initializing VL53L0X..."
    );


    if (
        !vl53.begin()
    )
    {
        Serial.println(
            "ERROR: VL53L0X not found!"
        );


        while (true)
        {
            delay(1000);
        }
    }


    Serial.println(
        "VL53L0X OK"
    );


    // ========================================================
    // BASELINE CALIBRATION
    // ========================================================

    calibrateDeploymentBaseline();


    // ========================================================
    // RESET FEATURE STATE
    // ========================================================

    resetFeatureState();


    featureBuffer.count =
        0;

    statCount = 0;
    statWriteIndex = 0;


    previousFrameValid =
        false;


    previousIMUTime =
        millis();


    yawDelta =
        0.0f;


    // ========================================================
    // ESP-NOW
    // ========================================================
    setupEspNow();


    // ========================================================
    // READY
    // ========================================================

    Serial.println();
    Serial.println(
        "========================================"
    );


    Serial.println(
        "          ALL SYSTEMS READY"
    );


    Serial.println(
        "          LSTM MODEL ENABLED"
    );


    Serial.println(
        "          VAE MODEL ENABLED"
    );


    Serial.println(
        "          GRU MODEL ENABLED"
    );


    Serial.println(
        "          XGB FUSION ENABLED"
    );


    Serial.println(
        "========================================"
    );
}


// ============================================================
// ESP-NOW SEND
// ============================================================
void sendTelemetry(const SensorFrame &frame)
{
    TelemetryPacket packet = {};

    packet.packetType = 1;
    packet.nodeId = NODE_ID;
    packet.sequence = gPacketSequence++;
    packet.timestamp = millis();

    packet.rotation_x = frame.rotation_x;
    packet.rotation_y = frame.rotation_y;
    packet.rotation_z = frame.rotation_z;
    packet.acceleration_x = frame.acceleration_x;
    packet.acceleration_y = frame.acceleration_y;
    packet.acceleration_z = frame.acceleration_z;
    packet.temperature = frame.temperature;
    packet.humidity = frame.humidity;
    packet.roof_convergence_cm = frame.roof_convergence_cm;
    packet.raindrop = frame.raindrop;
    packet.vibration = frame.vibration;
    packet.soil20cm = frame.soil20cm;
    packet.soil40cm = frame.soil40cm;
    packet.soil60cm = frame.soil60cm;
    packet.strain = frame.strain;

    packet.lstmMSE = gLstmMSE;
    packet.vaeMSE = gVaeMSE;
    packet.gruTrajectoryError = gGruTrajectoryError;
    packet.lstmFlag = gLstmFlag;
    packet.vaeFlag = gVaeFlag;
    packet.dlState = (uint8_t)gDLState;
    packet.mlClass = (uint8_t)gMLClass;
    packet.mlProbability[0] = gMLProbability[0];
    packet.mlProbability[1] = gMLProbability[1];
    packet.mlProbability[2] = gMLProbability[2];
    packet.finalState = (uint8_t)gFinalState;

    esp_err_t result = esp_now_send(
        receiverMAC,
        (const uint8_t *)&packet,
        sizeof(packet)
    );

    Serial.print("ESP-NOW SEND: ");
    Serial.println(result == ESP_OK ? "QUEUED" : "FAILED");
}

void setupEspNow()
{
    WiFi.mode(WIFI_STA);
    WiFi.setChannel(ESPNOW_CHANNEL);
    delay(100);

    Serial.print("Transmitter MAC: ");
    Serial.println(WiFi.macAddress());

    if (esp_now_init() != ESP_OK)
    {
        Serial.println("ERROR: ESP-NOW initialization failed!");
        return;
    }

    esp_now_peer_info_t peerInfo = {};
    memcpy(peerInfo.peer_addr, receiverMAC, 6);
    peerInfo.channel = ESPNOW_CHANNEL;
    peerInfo.encrypt = false;

    if (esp_now_is_peer_exist(receiverMAC))
    {
        Serial.println("ESP-NOW receiver peer already exists.");
    }
    else if (esp_now_add_peer(&peerInfo) == ESP_OK)
    {
        Serial.println("ESP-NOW receiver peer added.");
    }
    else
    {
        Serial.println("ERROR: Failed to add ESP-NOW receiver peer!");
    }
}

// ============================================================
// LOOP
// ============================================================

void loop()
{
    // --------------------------------------------------------
    // Read sensors
    // --------------------------------------------------------

    SensorFrame currentFrame;


    readCurrentSensorFrame(
        currentFrame
    );

    // Feed the real physical values into the statistical XGB rolling window.
    addStatisticalSample(currentFrame);


    // --------------------------------------------------------
    // Print physical sensor data
    // --------------------------------------------------------

    printCurrentSensorFrame(
        currentFrame
    );

    // --------------------------------------------------------
    // DIRECT ICM-20689 DIAGNOSTIC
    // Uses the same ±2g / ±250 dps conversion as the
    // standalone test program supplied by the user.
    // This is diagnostic only; the ML pipeline remains unchanged.
    // --------------------------------------------------------

    float rawAx, rawAy, rawAz;
    float rawGx, rawGy, rawGz;

    readICMAcceleration(
        rawAx,
        rawAy,
        rawAz
    );

    readICMGyroscope(
        rawGx,
        rawGy,
        rawGz
    );

    Serial.println();
    Serial.println("--------- ICM-20689 LIVE CHECK ---------");

    Serial.print("ACCEL X: ");
    Serial.print(rawAx / 9.80665f, 3);
    Serial.println(" g");

    Serial.print("ACCEL Y: ");
    Serial.print(rawAy / 9.80665f, 3);
    Serial.println(" g");

    Serial.print("ACCEL Z: ");
    Serial.print(rawAz / 9.80665f, 3);
    Serial.println(" g");

    Serial.println();

    Serial.print("GYRO X: ");
    Serial.print(rawGx, 2);
    Serial.println(" deg/s");

    Serial.print("GYRO Y: ");
    Serial.print(rawGy, 2);
    Serial.println(" deg/s");

    Serial.print("GYRO Z: ");
    Serial.print(rawGz, 2);
    Serial.println(" deg/s");

    Serial.println("----------------------------------------");


    // --------------------------------------------------------
    // Build 27 features
    // --------------------------------------------------------

    FeatureVector27 features;


    if (
        previousFrameValid
    )
    {
        buildFeatureVector(
            currentFrame,
            &previousFrame,
            features
        );
    }
    else
    {
        buildFeatureVector(
            currentFrame,
            nullptr,
            features
        );
    }


    // --------------------------------------------------------
    // Scale
    // --------------------------------------------------------

    float scaledFeatures[27];


    scaleFeatures(
        features.v,
        scaledFeatures
    );


    // --------------------------------------------------------
    // Add to rolling buffer
    // --------------------------------------------------------

    addFeatureSample(
        featureBuffer,
        scaledFeatures
    );


    // --------------------------------------------------------
    // Save previous frame
    // --------------------------------------------------------

    previousFrame =
        currentFrame;


    previousFrameValid =
        true;


    // --------------------------------------------------------
    // Buffer status
    // --------------------------------------------------------

    Serial.print(
        "LSTM BUFFER: "
    );


    Serial.print(
        featureBuffer.count
    );


    Serial.println(
        " / 24"
    );


    // --------------------------------------------------------
    // Run LSTM
    // --------------------------------------------------------

    if (
        bufferReady(
            featureBuffer
        )
    )
    {
        runAIInference(currentFrame);
    }
    else
    {
        Serial.print(
            "Buffering... "
        );


        Serial.print(
            (
                featureBuffer.count *
                100
            )
            /
            24
        );


        Serial.println(
            "%"
        );
    }


    // --------------------------------------------------------
    // Send live telemetry + latest AI result over ESP-NOW
    // --------------------------------------------------------
    sendTelemetry(currentFrame);


    // --------------------------------------------------------
    // Sampling period
    // --------------------------------------------------------

    delay(
        1000
    );
}