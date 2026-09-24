#include "h_stage_1.h"
#include <math.h>

// ============================================================
// FEATURE ENGINEERING STATE
// ============================================================

static float previousFilteredX = 0.0f;
static float previousFilteredY = 0.0f;
static float previousFilteredZ = 0.0f;

static bool filterInitialized = false;


// ============================================================
// RESET FEATURE STATE
// ============================================================

void resetFeatureState()
{
    previousFilteredX = 0.0f;
    previousFilteredY = 0.0f;
    previousFilteredZ = 0.0f;

    filterInitialized = false;
}


// ============================================================
// EWMA FILTER
//
// Training:
// pandas ewm(span=5, adjust=False)
//
// alpha = 2 / (5 + 1)
//       = 1/3
// ============================================================

static float ewmaUpdate(
    float input,
    float &previous,
    bool initialize
) {
    if (initialize) {
        previous = input;
        return input;
    }

    const float alpha = 1.0f / 3.0f;

    float output =
        alpha * input +
        (1.0f - alpha) * previous;

    previous = output;

    return output;
}


// ============================================================
// ANGULAR DIFFERENCE
//
// Exact Python equivalent:
//
// (a - b + 180) % 360 - 180
//
// Result range:
// [-180, 180)
//
// ============================================================

static float angularDifference(float a, float b)
{
    float diff = a - b;

    while (diff >= 180.0f) {
        diff -= 360.0f;
    }

    while (diff < -180.0f) {
        diff += 360.0f;
    }

    return diff;
}


// ============================================================
// DEMO DEFAULTS
//
// These values are deliberately chosen near the training
// distribution rather than arbitrary 0/100 values.
//
// IMPORTANT:
// These are PROTOTYPE PROXY values for unavailable sensors.
// They are not physical measurements.
// ============================================================

void setDemoDefaults(SensorFrame &s)
{
    s.rotation_x = 1.52259477f;
    s.rotation_y = 5.92748742f;
    s.rotation_z = 76.3799514f;

    s.acceleration_x = -0.0474483835f;
    s.acceleration_y = -0.0458351528f;
    s.acceleration_z = -0.0000426466f;

    s.temperature = 31.5543617f;
    s.humidity = 71.8245008f;

    s.roof_convergence_cm = 300.0f;

    // Training means for unavailable channels
    s.raindrop = 0.232127353f;
    s.vibration = 0.217325519f;

    // Correct soil proxy values
    s.soil20cm = 48.9207845f;
    s.soil40cm = 92.2472931f;
    s.soil60cm = 94.8240507f;

    s.strain = 110.0f;
}


// ============================================================
// MAKE SENSOR FRAME
// ============================================================

void makeSensorFrame(
    SensorFrame &s,
    float rotation_x,
    float rotation_y,
    float rotation_z,
    float acceleration_x,
    float acceleration_y,
    float acceleration_z,
    float temperature,
    float humidity,
    float roof_convergence_cm
)
{
    s.rotation_x = rotation_x;
    s.rotation_y = rotation_y;
    s.rotation_z = rotation_z;

    s.acceleration_x = acceleration_x;
    s.acceleration_y = acceleration_y;
    s.acceleration_z = acceleration_z;

    s.temperature = temperature;
    s.humidity = humidity;

    s.roof_convergence_cm = roof_convergence_cm;

    // --------------------------------------------------------
    // UNAVAILABLE SENSOR PROXIES
    // --------------------------------------------------------

    s.raindrop = 0.232127353f;
    s.vibration = 0.217325519f;

    s.soil20cm = 48.9207845f;
    s.soil40cm = 92.2472931f;
    s.soil60cm = 94.8240507f;

    s.strain = 110.0f;
}


// ============================================================
// BUILD 27 FEATURES
//
// EXACT FEATURE ORDER:
//
// 0  rotation_x
// 1  rotation_y
// 2  rotation_z
// 3  acceleration_x
// 4  acceleration_y
// 5  acceleration_z
// 6  raindrop
// 7  vibration
// 8  soil20cm
// 9  soil40cm
// 10 soil60cm
// 11 temperature
// 12 humidity
// 13 acceleration_x_filtered
// 14 acceleration_y_filtered
// 15 acceleration_z_filtered
// 16 acceleration_magnitude
// 17 rotation_x_change
// 18 rotation_y_change
// 19 rotation_z_change
// 20 soil_mean
// 21 soil_gradient
// 22 soil_change
// 23 acceleration_magnitude_change
// 24 soil_mean_change
// 25 temperature_change
// 26 humidity_change
// ============================================================

void buildFeatureVector(
    const SensorFrame &current,
    const SensorFrame *previous,
    FeatureVector27 &features
)
{
    // ========================================================
    // RAW FEATURES
    // ========================================================

    features.v[0] = current.rotation_x;
    features.v[1] = current.rotation_y;
    features.v[2] = current.rotation_z;

    features.v[3] = current.acceleration_x;
    features.v[4] = current.acceleration_y;
    features.v[5] = current.acceleration_z;

    features.v[6] = current.raindrop;
    features.v[7] = current.vibration;

    features.v[8]  = current.soil20cm;
    features.v[9]  = current.soil40cm;
    features.v[10] = current.soil60cm;

    features.v[11] = current.temperature;
    features.v[12] = current.humidity;


    // ========================================================
    // EWMA FILTERED ACCELERATION
    // ========================================================

    bool initializeFilter = !filterInitialized;

    features.v[13] = ewmaUpdate(
        current.acceleration_x,
        previousFilteredX,
        initializeFilter
    );

    features.v[14] = ewmaUpdate(
        current.acceleration_y,
        previousFilteredY,
        initializeFilter
    );

    features.v[15] = ewmaUpdate(
        current.acceleration_z,
        previousFilteredZ,
        initializeFilter
    );

    filterInitialized = true;


    // ========================================================
    // ACCELERATION MAGNITUDE
    // ========================================================

    features.v[16] = sqrtf(
        current.acceleration_x * current.acceleration_x +
        current.acceleration_y * current.acceleration_y +
        current.acceleration_z * current.acceleration_z
    );


    // ========================================================
    // ROTATION CHANGES
    // ========================================================

    if (previous != nullptr) {

        features.v[17] = angularDifference(
            current.rotation_x,
            previous->rotation_x
        );

        features.v[18] = angularDifference(
            current.rotation_y,
            previous->rotation_y
        );

        features.v[19] = angularDifference(
            current.rotation_z,
            previous->rotation_z
        );

    } else {

        features.v[17] = 0.0f;
        features.v[18] = 0.0f;
        features.v[19] = 0.0f;
    }


    // ========================================================
    // SOIL MEAN
    // ========================================================

    features.v[20] =
        (
            current.soil20cm +
            current.soil40cm +
            current.soil60cm
        ) / 3.0f;


    // ========================================================
    // SOIL GRADIENT
    // ========================================================

    features.v[21] =
    current.soil60cm -
    current.soil20cm;

    // ========================================================
    // SOIL CHANGE
    // ========================================================

    if (previous != nullptr) {

        float previousSoilMean =
            (
                previous->soil20cm +
                previous->soil40cm +
                previous->soil60cm
            ) / 3.0f;

        features.v[22] =
            features.v[20] -
            previousSoilMean;

    } else {

        features.v[22] = 0.0f;
    }


    // ========================================================
    // ACCELERATION MAGNITUDE CHANGE
    // ========================================================

    if (previous != nullptr) {

        float previousMagnitude =
            sqrtf(
                previous->acceleration_x *
                    previous->acceleration_x +

                previous->acceleration_y *
                    previous->acceleration_y +

                previous->acceleration_z *
                    previous->acceleration_z
            );

        features.v[23] =
            features.v[16] -
            previousMagnitude;

    } else {

        features.v[23] = 0.0f;
    }


    // ========================================================
    // SOIL MEAN CHANGE
    // ========================================================

    features.v[24] = features.v[22];


    // ========================================================
    // TEMPERATURE CHANGE
    // ========================================================

    if (previous != nullptr) {

        features.v[25] =
            current.temperature -
            previous->temperature;

    } else {

        features.v[25] = 0.0f;
    }


    // ========================================================
    // HUMIDITY CHANGE
    // ========================================================

    if (previous != nullptr) {

        features.v[26] =
            current.humidity -
            previous->humidity;

    } else {

        features.v[26] = 0.0f;
    }
}


// ============================================================
// PRINT SENSOR FRAME
// ============================================================

void printSensorFrame(const SensorFrame &s)
{
    Serial.println();
    Serial.println("==============================================");
    Serial.println("             SENSOR FRAME");
    Serial.println("==============================================");

    Serial.printf("rotation_x       = %.6f\n", s.rotation_x);
    Serial.printf("rotation_y       = %.6f\n", s.rotation_y);
    Serial.printf("rotation_z       = %.6f\n", s.rotation_z);

    Serial.printf("acceleration_x   = %.6f\n", s.acceleration_x);
    Serial.printf("acceleration_y   = %.6f\n", s.acceleration_y);
    Serial.printf("acceleration_z   = %.6f\n", s.acceleration_z);

    Serial.printf("temperature      = %.6f\n", s.temperature);
    Serial.printf("humidity         = %.6f\n", s.humidity);

    Serial.printf("raindrop         = %.6f\n", s.raindrop);
    Serial.printf("vibration        = %.6f\n", s.vibration);

    Serial.printf("soil20cm         = %.6f\n", s.soil20cm);
    Serial.printf("soil40cm         = %.6f\n", s.soil40cm);
    Serial.printf("soil60cm         = %.6f\n", s.soil60cm);

    Serial.printf("roof_distance    = %.6f cm\n",
                  s.roof_convergence_cm);

    Serial.println("==============================================");
}


// ============================================================
// PRINT 27 FEATURES
// ============================================================

void printFeatureVector(
    const FeatureVector27 &features
)
{
    Serial.println();
    Serial.println("==============================================");
    Serial.println("             27 FEATURES");
    Serial.println("==============================================");

    for (int i = 0; i < NUM_FEATURES; i++) {

        Serial.printf(
            "[%02d] = %.8f\n",
            i,
            features.v[i]
        );
    }

    Serial.println("==============================================");
}