#include "lstm_inference.h"
#include <math.h>

// ============================================================
// LSTM CONFIG
// ============================================================

#define LSTM1_UNITS 16
#define LSTM2_UNITS 8
#define LSTM3_UNITS 8
#define LSTM4_UNITS 16

#define EPSILON 0.001f

// ============================================================
// STATIC WORKING MEMORY
// These are NOT placed on the loopTask stack.
// ============================================================

static float lstm1_out[24][16];

static float lstm2_out[24][8];

static float repeat_out[24][8];

static float lstm3_out[24][8];

static float lstm4_out[24][16];

static float bn_temp[24][16];

static float lstm_h[16];
static float lstm_c[16];
static float lstm_z[64];


// ============================================================
// SIGMOID
// ============================================================

static inline float sigmoidf_fast(float x)
{
    if (x >= 8.0f)
        return 1.0f;

    if (x <= -8.0f)
        return 0.0f;

    return 1.0f / (1.0f + expf(-x));
}


// ============================================================
// BATCH NORMALIZATION
// ============================================================

static void batchNorm(
    float data[][16],
    int timesteps,
    int features,
    const float *gamma,
    const float *beta,
    const float *mean,
    const float *var
)
{
    for (int t = 0; t < timesteps; t++)
    {
        for (int j = 0; j < features; j++)
        {
            float x = data[t][j];

            data[t][j] =
                gamma[j] *
                ((x - mean[j]) /
                 sqrtf(var[j] + EPSILON))
                + beta[j];
        }
    }
}


// ============================================================
// BATCH NORMALIZATION FOR 8 FEATURES
// ============================================================

static void batchNorm8(
    float data[][8],
    int timesteps,
    const float *gamma,
    const float *beta,
    const float *mean,
    const float *var
)
{
    for (int t = 0; t < timesteps; t++)
    {
        for (int j = 0; j < 8; j++)
        {
            float x = data[t][j];

            data[t][j] =
                gamma[j] *
                ((x - mean[j]) /
                 sqrtf(var[j] + EPSILON))
                + beta[j];
        }
    }
}


// ============================================================
// LSTM CORE
//
// Input:
//   input[t][input_size]
//
// Output:
//   output[t][units]
//
// For return_sequences = true
// ============================================================

static void runLSTMSequence(
    const float *input,
    int timesteps,
    int input_size,
    int units,

    const float *W,
    const float *U,
    const float *B,

    float *output
)
{
    // Clear states
    for (int i = 0; i < units; i++)
    {
        lstm_h[i] = 0.0f;
        lstm_c[i] = 0.0f;
    }

    for (int t = 0; t < timesteps; t++)
    {
        const float *x = &input[t * input_size];
        float *y = &output[t * units];

        // ----------------------------------------------------
        // Dense calculation:
        //
        // z = xW + hU + b
        //
        // Keras gate order:
        // [input, forget, cell, output]
        // ----------------------------------------------------

        for (int g = 0; g < 4; g++)
        {
            for (int j = 0; j < units; j++)
            {
                float value = B[g * units + j];

                // x * W
                for (int k = 0; k < input_size; k++)
                {
                    value +=
                        x[k] *
                        W[k * (units * 4) +
                          g * units +
                          j];
                }

                // h * U
                for (int k = 0; k < units; k++)
                {
                    value +=
                        lstm_h[k] *
                        U[k * (units * 4) +
                          g * units +
                          j];
                }

                lstm_z[g * units + j] = value;
            }
        }

        // ----------------------------------------------------
        // LSTM equations
        // ----------------------------------------------------

        for (int j = 0; j < units; j++)
        {
            float i_gate =
                sigmoidf_fast(
                    lstm_z[j]
                );

            float f_gate =
                sigmoidf_fast(
                    lstm_z[units + j]
                );

            float g_gate =
                tanhf(
                    lstm_z[2 * units + j]
                );

            float o_gate =
                sigmoidf_fast(
                    lstm_z[3 * units + j]
                );

            lstm_c[j] =
                f_gate * lstm_c[j]
                +
                i_gate * g_gate;

            lstm_h[j] =
                o_gate *
                tanhf(lstm_c[j]);

            y[j] = lstm_h[j];
        }
    }
}


// ============================================================
// LSTM 2
// Returns ONLY final timestep
// ============================================================

static void runLSTMFinal(
    const float *input,
    int timesteps,
    int input_size,
    int units,

    const float *W,
    const float *U,
    const float *B,

    float *final_output
)
{
    for (int i = 0; i < units; i++)
    {
        lstm_h[i] = 0.0f;
        lstm_c[i] = 0.0f;
    }

    for (int t = 0; t < timesteps; t++)
    {
        const float *x =
            &input[t * input_size];

        for (int g = 0; g < 4; g++)
        {
            for (int j = 0; j < units; j++)
            {
                float value =
                    B[g * units + j];

                for (int k = 0; k < input_size; k++)
                {
                    value +=
                        x[k] *
                        W[k * (units * 4) +
                          g * units +
                          j];
                }

                for (int k = 0; k < units; k++)
                {
                    value +=
                        lstm_h[k] *
                        U[k * (units * 4) +
                          g * units +
                          j];
                }

                lstm_z[g * units + j] = value;
            }
        }

        for (int j = 0; j < units; j++)
        {
            float i_gate =
                sigmoidf_fast(
                    lstm_z[j]
                );

            float f_gate =
                sigmoidf_fast(
                    lstm_z[units + j]
                );

            float g_gate =
                tanhf(
                    lstm_z[2 * units + j]
                );

            float o_gate =
                sigmoidf_fast(
                    lstm_z[3 * units + j]
                );

            lstm_c[j] =
                f_gate * lstm_c[j]
                +
                i_gate * g_gate;

            lstm_h[j] =
                o_gate *
                tanhf(lstm_c[j]);
        }
    }

    for (int j = 0; j < units; j++)
    {
        final_output[j] = lstm_h[j];
    }
}


// ============================================================
// MAIN LSTM AUTOENCODER
// ============================================================

bool runLSTMAutoencoder(
    const FeatureBuffer &buffer,
    float reconstruction[24][27]
)
{
    if (!bufferReady(buffer))
    {
        return false;
    }

    Serial.println();
    Serial.println("LSTM inference started...");

    // ========================================================
    // STEP 1
    // LSTM 1
    // 24 x 27 -> 24 x 16
    // ========================================================

    runLSTMSequence(
        &buffer.data[0][0],
        24,
        27,
        16,

        LSTM1_W,
        LSTM1_U,
        LSTM1_B,

        &lstm1_out[0][0]
    );

    // BN1
    batchNorm(
        lstm1_out,
        24,
        16,

        BN1_GAMMA,
        BN1_BETA,
        BN1_MEAN,
        BN1_VAR
    );

    Serial.println("  LSTM 1 complete");


    // ========================================================
    // STEP 2
    // LSTM 2
    // 24 x 16 -> final 8
    // ========================================================

    float encoded[8];

    runLSTMFinal(
        &lstm1_out[0][0],
        24,
        16,
        8,

        LSTM2_W,
        LSTM2_U,
        LSTM2_B,

        encoded
    );

    // BN2
    for (int j = 0; j < 8; j++)
    {
        encoded[j] =
            BN2_GAMMA[j] *
            ((encoded[j] - BN2_MEAN[j]) /
             sqrtf(BN2_VAR[j] + EPSILON))
            +
            BN2_BETA[j];
    }

    Serial.println("  LSTM 2 complete");


    // ========================================================
    // STEP 3
    // RepeatVector(24)
    // 8 -> 24 x 8
    // ========================================================

    for (int t = 0; t < 24; t++)
    {
        for (int j = 0; j < 8; j++)
        {
            repeat_out[t][j] = encoded[j];
        }
    }

    Serial.println("  RepeatVector complete");


    // ========================================================
    // STEP 4
    // LSTM 3
    // 24 x 8 -> 24 x 8
    // ========================================================

    runLSTMSequence(
        &repeat_out[0][0],
        24,
        8,
        8,

        LSTM3_W,
        LSTM3_U,
        LSTM3_B,

        &lstm3_out[0][0]
    );

    // BN3
    batchNorm8(
        lstm3_out,
        24,

        BN3_GAMMA,
        BN3_BETA,
        BN3_MEAN,
        BN3_VAR
    );

    Serial.println("  LSTM 3 complete");


    // ========================================================
    // STEP 5
    // LSTM 4
    // 24 x 8 -> 24 x 16
    // ========================================================

    runLSTMSequence(
        &lstm3_out[0][0],
        24,
        8,
        16,

        LSTM4_W,
        LSTM4_U,
        LSTM4_B,

        &lstm4_out[0][0]
    );

    // BN4
    batchNorm(
        lstm4_out,
        24,
        16,

        BN4_GAMMA,
        BN4_BETA,
        BN4_MEAN,
        BN4_VAR
    );

    Serial.println("  LSTM 4 complete");


    // ========================================================
    // STEP 6
    // TimeDistributed(Dense(27))
    // 24 x 16 -> 24 x 27
    // ========================================================

    for (int t = 0; t < 24; t++)
    {
        for (int j = 0; j < 27; j++)
        {
            float value =
                DENSE_B[j];

            for (int k = 0; k < 16; k++)
            {
                value +=
                    lstm4_out[t][k] *
                    DENSE_W[k * 27 + j];
            }

            reconstruction[t][j] = value;
        }
    }

    Serial.println("  Dense reconstruction complete");

    return true;
}


// ============================================================
// MSE
// ============================================================

float calculateLSTM_MSE(
    const FeatureBuffer &buffer,
    const float reconstruction[24][27]
)
{
    float sum = 0.0f;

    for (int t = 0; t < 24; t++)
    {
        for (int j = 0; j < 27; j++)
        {
            float diff =
                buffer.data[t][j]
                -
                reconstruction[t][j];

            sum += diff * diff;
        }
    }

    return sum / (24.0f * 27.0f);
}


// ============================================================
// ANOMALY
// ============================================================

bool isLSTMAnomaly(float mse)
{
    return mse >= 0.62542055f;
}


// ============================================================
// PRINT RESULT
// ============================================================

void printLSTMResult(
    float mse,
    bool anomaly
)
{
    Serial.println();
    Serial.println("==============================================");
    Serial.println("          LSTM AUTOENCODER RESULT");
    Serial.println("==============================================");

    Serial.print("Reconstruction MSE : ");
    Serial.println(mse, 8);

    Serial.print("Threshold          : ");
    Serial.println(0.62542055f, 8);

    Serial.print("Status             : ");

    if (anomaly)
        Serial.println("ANOMALY");
    else
        Serial.println("NORMAL");

    Serial.println("==============================================");
}