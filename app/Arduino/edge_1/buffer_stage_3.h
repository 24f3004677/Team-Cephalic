#ifndef BUFFER_STAGE_3_H
#define BUFFER_STAGE_3_H

#include <Arduino.h>

#define BUFFER_SIZE 24
#define FEATURE_COUNT 27


// ============================================================
// 24-SAMPLE ROLLING BUFFER
// ============================================================

struct FeatureBuffer {

    // buffer[sample][feature]
    float data[BUFFER_SIZE][FEATURE_COUNT];

    // Number of valid samples currently stored
    int count;
};


// ============================================================
// INITIALIZE BUFFER
// ============================================================

inline void initFeatureBuffer(FeatureBuffer &buffer) {

    buffer.count = 0;

    for (int i = 0; i < BUFFER_SIZE; i++) {

        for (int j = 0; j < FEATURE_COUNT; j++) {

            buffer.data[i][j] = 0.0f;
        }
    }
}


// ============================================================
// ADD ONE 27-FEATURE SAMPLE
// ============================================================

inline void addFeatureSample(
    FeatureBuffer &buffer,
    const float features[FEATURE_COUNT]
) {

    // --------------------------------------------------------
    // If buffer is already full:
    // Shift samples left by one position.
    //
    // Sample 1 is removed.
    // Sample 2 becomes Sample 1.
    // ...
    // Sample 24 becomes Sample 23.
    //
    // New sample goes into position 23.
    // --------------------------------------------------------

    if (buffer.count >= BUFFER_SIZE) {

        for (int i = 1; i < BUFFER_SIZE; i++) {

            for (int j = 0; j < FEATURE_COUNT; j++) {

                buffer.data[i - 1][j] =
                    buffer.data[i][j];
            }
        }

        buffer.count = BUFFER_SIZE - 1;
    }


    // --------------------------------------------------------
    // Add new sample
    // --------------------------------------------------------

    for (int j = 0; j < FEATURE_COUNT; j++) {

        buffer.data[buffer.count][j] =
            features[j];
    }

    buffer.count++;
}


// ============================================================
// CHECK WHETHER 24 SAMPLES ARE AVAILABLE
// ============================================================

inline bool bufferReady(
    const FeatureBuffer &buffer
) {

    return buffer.count >= BUFFER_SIZE;
}


// ============================================================
// PRINT BUFFER STATUS
// ============================================================

inline void printBufferStatus(
    const FeatureBuffer &buffer
) {

    Serial.println();
    Serial.println("----------------------------------------------");
    Serial.print("BUFFER: ");
    Serial.print(buffer.count);
    Serial.print(" / ");
    Serial.println(BUFFER_SIZE);

    if (bufferReady(buffer)) {

        Serial.println("STATUS: READY");

    } else {

        Serial.print("STATUS: BUFFERING - ");
        Serial.print(
            (buffer.count * 100) / BUFFER_SIZE
        );
        Serial.println("%");
    }

    Serial.println("----------------------------------------------");
}


// ============================================================
// PRINT COMPLETE 24 × 27 BUFFER
// ============================================================

inline void printFeatureBuffer(
    const FeatureBuffer &buffer
) {

    Serial.println();
    Serial.println("======================================================");
    Serial.println("              24 x 27 FEATURE BUFFER");
    Serial.println("======================================================");

    for (int i = 0; i < buffer.count; i++) {

        Serial.print("Sample ");
        Serial.print(i + 1);
        Serial.print(": ");

        for (int j = 0; j < FEATURE_COUNT; j++) {

            Serial.print(buffer.data[i][j], 4);

            if (j < FEATURE_COUNT - 1) {
                Serial.print(", ");
            }
        }

        Serial.println();
    }

    Serial.println("======================================================");
}

#endif