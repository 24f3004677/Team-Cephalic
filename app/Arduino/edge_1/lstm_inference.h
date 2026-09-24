#ifndef LSTM_INFERENCE_H
#define LSTM_INFERENCE_H

#include <Arduino.h>
#include "buffer_stage_3.h"
#include "lstm_weights.h"

#define LSTM_SEQ_LEN 24
#define LSTM_INPUT_SIZE 27

// ------------------------------------------------------------
// Run complete LSTM autoencoder
//
// Input:
//     FeatureBuffer containing 24 x 27 SCALED features
//
// Output:
//     reconstruction[24][27]
//
// Returns:
//     true if inference completed
// ------------------------------------------------------------

bool runLSTMAutoencoder(
    const FeatureBuffer &buffer,
    float reconstruction[LSTM_SEQ_LEN][LSTM_INPUT_SIZE]
);


// ------------------------------------------------------------
// Calculate reconstruction MSE
// ------------------------------------------------------------

float calculateLSTM_MSE(
    const FeatureBuffer &buffer,
    const float reconstruction[LSTM_SEQ_LEN][LSTM_INPUT_SIZE]
);


// ------------------------------------------------------------
// Convert MSE to anomaly flag
//
// Trained threshold:
//     0.62542055
// ------------------------------------------------------------

bool isLSTMAnomaly(float mse);


// ------------------------------------------------------------
// Print useful inference results
// ------------------------------------------------------------

void printLSTMResult(
    float mse,
    bool anomaly
);

#endif