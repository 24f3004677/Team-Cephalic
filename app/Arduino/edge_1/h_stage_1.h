#pragma once

#include <Arduino.h>

#define NUM_FEATURES 27

struct SensorFrame {
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
};

struct FeatureVector27 {
    float v[NUM_FEATURES];
};

void setDemoDefaults(SensorFrame &s);

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
);

void buildFeatureVector(
    const SensorFrame &current,
    const SensorFrame *previous,
    FeatureVector27 &features
);

void printSensorFrame(const SensorFrame &s);

void printFeatureVector(
    const FeatureVector27 &features
);
void resetFeatureState();