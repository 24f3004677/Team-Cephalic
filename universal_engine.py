import os
import json
import time
import traceback

import numpy as np
import pandas as pd
import xgboost as xgb
import tensorflow as tf

keras = tf.keras
import joblib

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import warnings

warnings.filterwarnings("ignore")
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"


class Sampling(keras.layers.Layer):
    def call(self, inputs):
        z_mean, z_log_var = inputs

        batch = tf.shape(z_mean)[0]
        dim = tf.shape(z_mean)[1]

        epsilon = tf.random.normal(
            shape=(batch, dim),
            mean=0.0,
            stddev=1.0,
            dtype=z_mean.dtype
        )

        return z_mean + tf.exp(0.5 * z_log_var) * epsilon

    def get_config(self):
        return super().get_config()


class StructuralAnomalyEngine:
    """
    Bhu-Rakshak Universal Structural Anomaly Engine.

    LIVE SENSOR PIPELINE:

        ESP32
          |
          v
        ESP-NOW
          |
          v
        ESP32-S3 Gateway
          |
          v
        JSON / Serial
          |
          v
        Python Backend
          |
          v
        Feature Adapter
          |
          v
        24 x 27 sequence
          |
          +-------- LSTM Autoencoder
          |
          +-------- VAE
          |
          +-------- GRU
          |
          +-------- XGBoost Fusion
          |
          +-------- Statistical XGBoost
          |
          v
        Final Risk Decision

    IMPORTANT:

    The historical training dataset uses rotation-like angle values,
    whereas the current ESP32 MPU6500 sends gyro rates in deg/s.

    Therefore live gyro rates are integrated into an angle-like stream
    before entering the historical LSTM/VAE feature pipeline.

    The historical acceleration values are also much smaller than the
    physical ESP32 acceleration values in m/s^2. Therefore the live
    acceleration is converted to a dynamic signal around its startup
    baseline and mapped into the historical acceleration domain.

    This is a prototype compatibility/calibration layer.
    It does NOT claim that the proxy training dataset is a perfect
    physical representation of an actual mine.
    """

    MAX_HISTORY = 1000

    # LSTM training uses 24 timestep sequences.
    DL_WINDOW = 24

    # Statistical ML model uses the most recent 10 samples.
    ML_WINDOW = 10

    # Dataset preparation used EWM span=5.
    FILTER_SPAN = 5

    # Historical acceleration values are roughly ~0.01 to 0.08,
    # while ESP32 acceleration is in m/s^2.
    #
    # We map only the CHANGE from the startup physical baseline
    # into the historical domain.
    ACCEL_DOMAIN_SCALE = 0.01

    # Prevent ridiculous integration after a long serial delay.
    MAX_DT = 2.0
    MIN_DT = 0.05

    # EXACT 27 features used by the LSTM notebook.
    AE_COLS = [
        "rotation_x",
        "rotation_y",
        "rotation_z",

        "acceleration_x",
        "acceleration_y",
        "acceleration_z",

        "raindrop",
        "vibration",

        "soil20cm",
        "soil40cm",
        "soil60cm",

        "temperature",
        "humidity",

        "acceleration_x_filtered",
        "acceleration_y_filtered",
        "acceleration_z_filtered",

        "acceleration_magnitude",

        "rotation_x_change",
        "rotation_y_change",
        "rotation_z_change",

        "soil_mean",
        "soil_gradient",
        "soil_change",

        "acceleration_magnitude_change",
        "soil_mean_change",

        "temperature_change",
        "humidity_change",
    ]

    # GRU feature contract from the existing engine.
    GRU_COLS = [
        "rotation_x",
        "rotation_y",
        "rotation_z",
        "acceleration_x",
        "acceleration_y",
        "acceleration_z",
    ]

    # Statistical XGBoost feature contract.
    ML_COLS = [
        "Accel_X (m/s^2)",
        "Accel_Y (m/s^2)",
        "Accel_Z (m/s^2)",
        "Strain (με)",
        "Temp (°C)",
        "roof_convergence_cm",
    ]

    def __init__(
        self,
        model_dir="models",
        log_file="public/telemetry_log.csv",
        dashboard_file="public/scientific_dashboard.png",
    ):

        print(
            "[INIT] Booting Bhu-Rakshak "
            "Universal Structural Anomaly Engine..."
        )

        self.model_dir = model_dir
        self.log_file = log_file
        self.dashboard_file = dashboard_file

        self.has_vae = False

        # Every physical node gets its own state.
        self.node_state = {}

        self._ensure_parent(self.log_file)
        self._ensure_parent(self.dashboard_file)

        self._load_models()

        print(
            f"[INIT] LSTM input contract: "
            f"{len(self.AE_COLS)} features x "
            f"{self.DL_WINDOW} steps"
        )

        print("[INIT] Engine Ready. Awaiting telemetry stream.")

    # =========================================================
    # FILE / DIRECTORY HELPERS
    # =========================================================

    @staticmethod
    def _ensure_parent(path):

        parent = os.path.dirname(
            os.path.abspath(path)
        )

        if parent:
            os.makedirs(
                parent,
                exist_ok=True
            )

    # =========================================================
    # NODE STATE
    # =========================================================

    def _new_node_state(self):

        return {

            "buffer": pd.DataFrame(),

            "step_counter": 0,

            # ESP32 timestamp in milliseconds.
            "last_ts_ms": None,

            # Python receive timestamp.
            "last_receive_time": None,

            # Physical acceleration at startup.
            "startup_accel": None,

            # Calibrated angle-like rotation.
            "live_angles": None,

            # EMA filtered acceleration.
            "filtered_accel": None,

            # REAL or SYNTHETIC.
            "data_source": "REAL",

            # Prevent duplicate packets.
            "last_packet_signature": None,

            "history": {

                "step": [],

                "tilt_x": [],

                "roof_dist": [],

                "lstm_mse": [],

                "gru_error": [],

                "risk_score": [],
            },
        }

    def get_node_state(self, node_id):

        if node_id not in self.node_state:

            self.node_state[node_id] = (
                self._new_node_state()
            )

        return self.node_state[node_id]

    def get_node_history(self, node_id):

        return self.get_node_state(
            node_id
        )["history"]

    def _trim_history(self, history):

        if len(history["step"]) <= self.MAX_HISTORY:
            return

        excess = (
            len(history["step"])
            - self.MAX_HISTORY
        )

        for key in history:

            del history[key][:excess]

    # =========================================================
    # MODEL LOADING
    # =========================================================

    def _load_models(self):

        # -----------------------------------------------------
        # LSTM
        # -----------------------------------------------------

        try:

            lstm_path = os.path.join(
                self.model_dir,
                "lstm_autoencoder_final.keras"
            )

            lstm_meta_path = os.path.join(
                self.model_dir,
                "anomaly_metadata.pkl"
            )

            self.lstm = keras.models.load_model(
                lstm_path,
                compile=False
            )

            self.lstm_meta = joblib.load(
                lstm_meta_path
            )

            self.lstm_scaler = (
                self.lstm_meta["scaler"]
            )

            self.lstm_threshold = float(
                self.lstm_meta[
                    "selected_threshold"
                ]
            )

            print(
                "[MODEL] LSTM loaded."
            )

            print(
                f"[MODEL] LSTM threshold = "
                f"{self.lstm_threshold:.6f}"
            )

        except Exception:

            print(
                "[CRITICAL ERROR] "
                "Failed to load LSTM."
            )

            print(
                traceback.format_exc()
            )

            raise

        # -----------------------------------------------------
        # VAE
        # -----------------------------------------------------

        try:

            vae_path = os.path.join(
                self.model_dir,
                "vae_final.keras"
            )

            vae_meta_path = os.path.join(
                self.model_dir,
                "vae_metadata.pkl"
            )

            self.vae = keras.models.load_model(
                vae_path,
                custom_objects={
                    "Sampling": Sampling
                },
                compile=False,
                safe_mode=False,
            )

            self.vae_meta = joblib.load(
                vae_meta_path
            )

            self.vae_threshold = float(
                self.vae_meta.get(
                    "selected_threshold",
                    np.inf
                )
            )

            self.has_vae = True

            print(
                "[MODEL] VAE loaded."
            )

            print(
                f"[MODEL] VAE threshold = "
                f"{self.vae_threshold:.6f}"
            )

        except Exception as exc:

            print(
                "[WARN] VAE unavailable."
            )

            print(
                f"[WARN] Reason: {exc}"
            )

            self.vae = None

            self.vae_meta = {
                "selected_threshold": np.inf
            }

            self.vae_threshold = np.inf

            self.has_vae = False

        # -----------------------------------------------------
        # GRU
        # -----------------------------------------------------

        try:

            gru_path = os.path.join(
                self.model_dir,
                "gru_forecaster.keras"
            )

            gru_meta_path = os.path.join(
                self.model_dir,
                "gru_metadata.pkl"
            )

            self.gru = keras.models.load_model(
                gru_path,
                compile=False
            )

            self.gru_meta = joblib.load(
                gru_meta_path
            )

            print(
                "[MODEL] GRU loaded."
            )

        except Exception:

            print(
                "[CRITICAL ERROR] "
                "Failed to load GRU."
            )

            print(
                traceback.format_exc()
            )

            raise

        # -----------------------------------------------------
        # XGBOOST
        # -----------------------------------------------------

        try:

            fusion_path = os.path.join(
                self.model_dir,
                "xgboost_production_ensemble.json"
            )

            statistical_path = os.path.join(
                self.model_dir,
                "xgboost_statistical_detector_2.0.json"
            )

            self.dl_fusion_xgb = (
                xgb.XGBClassifier()
            )

            self.dl_fusion_xgb.load_model(
                fusion_path
            )

            self.ml_detector_xgb = (
                xgb.XGBClassifier()
            )

            self.ml_detector_xgb.load_model(
                statistical_path
            )

            print(
                "[MODEL] XGBoost ensemble "
                "+ statistical detector loaded."
            )

        except Exception:

            print(
                "[CRITICAL ERROR] "
                "Failed to load XGBoost models."
            )

            print(
                traceback.format_exc()
            )

            raise

    # =========================================================
    # TRAINING DOMAIN
    # =========================================================

    def _scaler_mean(
        self,
        feature_name,
        fallback=0.0
    ):

        try:

            index = self.AE_COLS.index(
                feature_name
            )

            return float(
                self.lstm_scaler.mean_[index]
            )

        except Exception:

            return float(fallback)

    def _training_baseline(self):

        """
        Obtain safe baseline values from
        the actual LSTM training scaler.

        This is much better than forcing missing
        environmental features to arbitrary 100/0
        values.
        """

        return {

            "rotation_x":
                self._scaler_mean(
                    "rotation_x",
                    0.735
                ),

            "rotation_y":
                self._scaler_mean(
                    "rotation_y",
                    5.692
                ),

            "rotation_z":
                self._scaler_mean(
                    "rotation_z",
                    83.221
                ),

            "acceleration_x":
                self._scaler_mean(
                    "acceleration_x",
                    -0.0315
                ),

            "acceleration_y":
                self._scaler_mean(
                    "acceleration_y",
                    -0.0274
                ),

            "acceleration_z":
                self._scaler_mean(
                    "acceleration_z",
                    0.00055
                ),

            "raindrop":
                self._scaler_mean(
                    "raindrop",
                    2.55
                ),

            "vibration":
                self._scaler_mean(
                    "vibration",
                    0.10
                ),

            "soil20cm":
                self._scaler_mean(
                    "soil20cm",
                    72.09
                ),

            "soil40cm":
                self._scaler_mean(
                    "soil40cm",
                    82.24
                ),

            "soil60cm":
                self._scaler_mean(
                    "soil60cm",
                    87.70
                ),

            "temperature":
                self._scaler_mean(
                    "temperature",
                    30.53
                ),

            "humidity":
                self._scaler_mean(
                    "humidity",
                    71.87
                ),
        }

    # =========================================================
    # INPUT VALIDATION
    # =========================================================

    def _validate_and_fill_inputs(
        self,
        raw_data,
        state
    ):

        raw = raw_data or {}

        baseline = (
            self._training_baseline()
        )

        def number(
            key,
            default
        ):

            value = raw.get(
                key,
                default
            )

            try:

                value = float(value)

                if not np.isfinite(value):

                    return float(default)

                return value

            except (
                TypeError,
                ValueError
            ):

                return float(default)

        # -----------------------------------------------------
        # REAL ESP32 ACCELERATION
        # -----------------------------------------------------

        ax_live = number(
            "Accel_X (m/s^2)",
            number(
                "accel_x",
                0.0
            )
        )

        ay_live = number(
            "Accel_Y (m/s^2)",
            number(
                "accel_y",
                0.0
            )
        )

        az_live = number(
            "Accel_Z (m/s^2)",
            number(
                "accel_z",
                9.8
            )
        )

        # -----------------------------------------------------
        # MPU6500 GYRO
        # -----------------------------------------------------

        gx = number(
            "rotation_x",
            0.0
        )

        gy = number(
            "rotation_y",
            0.0
        )

        gz = number(
            "rotation_z",
            0.0
        )

        # -----------------------------------------------------
        # ENVIRONMENT
        # -----------------------------------------------------

        temperature = number(
            "temperature",
            number(
                "Temp (°C)",
                baseline["temperature"]
            )
        )

        humidity = number(
            "humidity",
            baseline["humidity"]
        )

        roof = number(
            "roof_convergence_cm",
            300.0
        )

        # -----------------------------------------------------
        # FEATURES NOT CURRENTLY PRESENT
        # ON THE PHYSICAL NODE
        # -----------------------------------------------------

        raindrop = number(
            "raindrop",
            baseline["raindrop"]
        )

        vibration = number(
            "vibration",
            baseline["vibration"]
        )

        soil20 = number(
            "soil20cm",
            baseline["soil20cm"]
        )

        soil40 = number(
            "soil40cm",
            baseline["soil40cm"]
        )

        soil60 = number(
            "soil60cm",
            baseline["soil60cm"]
        )

        strain = number(
            "Strain (με)",
            110.0
        )

        # -----------------------------------------------------
        # DATA SOURCE
        # -----------------------------------------------------

        source = str(
            raw.get(
                "data_source",
                raw.get(
                    "source",
                    "REAL"
                )
            )
        ).upper()

        if source == "SYNTHETIC":

            state["data_source"] = (
                "SYNTHETIC"
            )

        else:

            state["data_source"] = (
                "REAL"
            )

        return {

            "gyro_x": gx,
            "gyro_y": gy,
            "gyro_z": gz,

            "live_ax": ax_live,
            "live_ay": ay_live,
            "live_az": az_live,

            "temperature": temperature,
            "humidity": humidity,

            "roof_convergence_cm": roof,

            "raindrop": raindrop,
            "vibration": vibration,

            "soil20cm": soil20,
            "soil40cm": soil40,
            "soil60cm": soil60,

            "strain": strain,
        }

    # =========================================================
    # TIME DIFFERENCE
    # =========================================================

    def _get_dt(
        self,
        raw_data,
        state
    ):

        now = time.time()

        ts_ms = None

        if isinstance(
            raw_data,
            dict
        ):

            ts_ms = raw_data.get(
                "ts_ms"
            )

        dt = None

        # -----------------------------------------------------
        # Prefer ESP32 timestamp
        # -----------------------------------------------------

        if ts_ms is not None:

            try:

                ts_ms = int(
                    float(ts_ms)
                )

                if (
                    state["last_ts_ms"]
                    is not None
                ):

                    raw_dt = (
                        ts_ms
                        - state["last_ts_ms"]
                    ) / 1000.0

                    if (
                        self.MIN_DT
                        <= raw_dt
                        <= self.MAX_DT
                    ):

                        dt = raw_dt

                state["last_ts_ms"] = ts_ms

            except (
                TypeError,
                ValueError
            ):

                pass

        # -----------------------------------------------------
        # Fallback to Python receive time
        # -----------------------------------------------------

        if (
            dt is None
            and
            state["last_receive_time"]
            is not None
        ):

            raw_dt = (
                now
                - state["last_receive_time"]
            )

            if (
                self.MIN_DT
                <= raw_dt
                <= self.MAX_DT
            ):

                dt = raw_dt

        state["last_receive_time"] = now

        # ESP32 sends approximately every 0.5 sec.
        return float(
            dt if dt is not None
            else 0.5
        )

    # =========================================================
    # LIVE SENSOR CALIBRATION
    # =========================================================

    def _calibrate_live_domain(
        self,
        sensor,
        state,
        dt
    ):

        baseline = (
            self._training_baseline()
        )

        # -----------------------------------------------------
        # PHYSICAL ACCELERATION
        # -----------------------------------------------------

        live_acc = np.array(
            [
                sensor["live_ax"],
                sensor["live_ay"],
                sensor["live_az"],
            ],
            dtype=float
        )

        # First physical measurement becomes
        # the gravity/orientation reference.
        if state["startup_accel"] is None:

            state["startup_accel"] = (
                live_acc.copy()
            )

        dynamic_acc = (
            live_acc
            - state["startup_accel"]
        )

        # Map only dynamic change into historical
        # acceleration domain.
        train_acc = (
            np.array(
                [
                    baseline[
                        "acceleration_x"
                    ],

                    baseline[
                        "acceleration_y"
                    ],

                    baseline[
                        "acceleration_z"
                    ],
                ]
            )
            +
            dynamic_acc
            * self.ACCEL_DOMAIN_SCALE
        )

        # -----------------------------------------------------
        # GYRO -> ANGLE
        # -----------------------------------------------------

        if state["live_angles"] is None:

            state["live_angles"] = (
                np.array(
                    [
                        baseline[
                            "rotation_x"
                        ],

                        baseline[
                            "rotation_y"
                        ],

                        baseline[
                            "rotation_z"
                        ],
                    ],
                    dtype=float
                )
            )

        else:

            state["live_angles"] += (

                np.array(
                    [
                        sensor["gyro_x"],
                        sensor["gyro_y"],
                        sensor["gyro_z"],
                    ]
                )
                * dt
            )

        # -----------------------------------------------------
        # LIMIT ONE BAD PACKET
        # -----------------------------------------------------

        for i, name in enumerate(
            [
                "rotation_x",
                "rotation_y",
                "rotation_z",
            ]
        ):

            idx = self.AE_COLS.index(
                name
            )

            mean = float(
                self.lstm_scaler.mean_[
                    idx
                ]
            )

            std = max(
                float(
                    self.lstm_scaler.scale_[
                        idx
                    ]
                ),
                1e-6
            )

            state["live_angles"][i] = (
                np.clip(
                    state["live_angles"][i],

                    mean - 5.0 * std,

                    mean + 5.0 * std
                )
            )

        # -----------------------------------------------------
        # EMA FILTER
        # -----------------------------------------------------

        alpha = (
            2.0
            /
            (
                self.FILTER_SPAN
                + 1.0
            )
        )

        if state["filtered_accel"] is None:

            state["filtered_accel"] = (
                train_acc.copy()
            )

        else:

            state["filtered_accel"] = (

                alpha
                * train_acc

                +

                (
                    1.0 - alpha
                )
                * state["filtered_accel"]
            )

        return (
            train_acc,
            state["filtered_accel"].copy()
        )

    # =========================================================
    # 27 FEATURE CREATION
    # =========================================================

    def _calculate_dl_features(
        self,
        sensor,
        state,
        previous_tick,
        dt
    ):

        train_acc, filtered_acc = (
            self._calibrate_live_domain(
                sensor,
                state,
                dt
            )
        )

        # -----------------------------------------------------
        # ANGLE VALUES
        # -----------------------------------------------------

        rotation = (
            state["live_angles"].copy()
        )

        # -----------------------------------------------------
        # ACCELERATION MAGNITUDE
        # -----------------------------------------------------

        magnitude = float(
            np.linalg.norm(
                train_acc
            )
        )

        # -----------------------------------------------------
        # SOIL
        # -----------------------------------------------------

        soil_mean = (
            sensor["soil20cm"]
            +
            sensor["soil40cm"]
            +
            sensor["soil60cm"]
        ) / 3.0

        soil_gradient = (
            sensor["soil60cm"]
            -
            sensor["soil20cm"]
        )

        # -----------------------------------------------------
        # BASIC FEATURES
        # -----------------------------------------------------

        tick = {

            "rotation_x":
                float(rotation[0]),

            "rotation_y":
                float(rotation[1]),

            "rotation_z":
                float(rotation[2]),

            "acceleration_x":
                float(train_acc[0]),

            "acceleration_y":
                float(train_acc[1]),

            "acceleration_z":
                float(train_acc[2]),

            "raindrop":
                float(sensor["raindrop"]),

            "vibration":
                float(sensor["vibration"]),

            "soil20cm":
                float(sensor["soil20cm"]),

            "soil40cm":
                float(sensor["soil40cm"]),

            "soil60cm":
                float(sensor["soil60cm"]),

            "temperature":
                float(sensor["temperature"]),

            "humidity":
                float(sensor["humidity"]),

            "acceleration_x_filtered":
                float(filtered_acc[0]),

            "acceleration_y_filtered":
                float(filtered_acc[1]),

            "acceleration_z_filtered":
                float(filtered_acc[2]),

            "acceleration_magnitude":
                magnitude,

            "soil_mean":
                float(soil_mean),

            "soil_gradient":
                float(soil_gradient),
        }

        # -----------------------------------------------------
        # CHANGE FEATURES
        # -----------------------------------------------------

        if previous_tick is None:

            tick["rotation_x_change"] = 0.0
            tick["rotation_y_change"] = 0.0
            tick["rotation_z_change"] = 0.0

            tick["soil_change"] = 0.0

            tick[
                "acceleration_magnitude_change"
            ] = 0.0

            tick[
                "soil_mean_change"
            ] = 0.0

            tick[
                "temperature_change"
            ] = 0.0

            tick[
                "humidity_change"
            ] = 0.0

        else:

            tick[
                "rotation_x_change"
            ] = (
                tick["rotation_x"]
                -
                previous_tick["rotation_x"]
            )

            tick[
                "rotation_y_change"
            ] = (
                tick["rotation_y"]
                -
                previous_tick["rotation_y"]
            )

            tick[
                "rotation_z_change"
            ] = (
                tick["rotation_z"]
                -
                previous_tick["rotation_z"]
            )

            # IMPORTANT:
            # Dataset preparation defines soil_change
            # as change in soil_mean.
            tick[
                "soil_change"
            ] = (
                tick["soil_mean"]
                -
                previous_tick["soil_mean"]
            )

            tick[
                "acceleration_magnitude_change"
            ] = (
                tick[
                    "acceleration_magnitude"
                ]
                -
                previous_tick[
                    "acceleration_magnitude"
                ]
            )

            tick[
                "soil_mean_change"
            ] = (
                tick["soil_mean"]
                -
                previous_tick["soil_mean"]
            )

            tick[
                "temperature_change"
            ] = (
                tick["temperature"]
                -
                previous_tick["temperature"]
            )

            tick[
                "humidity_change"
            ] = (
                tick["humidity"]
                -
                previous_tick["humidity"]
            )

        # -----------------------------------------------------
        # FINAL NUMERICAL SAFETY
        # -----------------------------------------------------

        for col in self.AE_COLS:

            try:

                value = float(
                    tick[col]
                )

                if not np.isfinite(
                    value
                ):

                    tick[col] = 0.0

            except Exception:

                tick[col] = 0.0

        return tick

    # =========================================================
    # LSTM
    # =========================================================

    def _predict_lstm(
        self,
        buffer
    ):

        X_raw = (
            buffer[
                self.AE_COLS
            ]
            .values
            .astype(
                np.float32
            )
        )

        # EXACTLY the StandardScaler used
        # during LSTM training.
        X_scaled = (
            self.lstm_scaler
            .transform(
                X_raw
            )
            .astype(
                np.float32
            )
        )

        X_seq = np.expand_dims(
            X_scaled,
            axis=0
        )

        reconstruction = (
            self.lstm.predict(
                X_seq,
                verbose=0
            )
        )

        mse = float(
            np.mean(
                np.square(
                    X_seq
                    -
                    reconstruction
                )
            )
        )

        flag = int(
            mse
            >
            self.lstm_threshold
        )

        return (
            mse,
            flag,
            X_seq
        )

    # =========================================================
    # VAE
    # =========================================================

    def _predict_vae(
        self,
        X_seq
    ):

        if not self.has_vae:

            return (
                0.0,
                0
            )

        reconstruction = (
            self.vae.predict(
                X_seq,
                verbose=0
            )
        )

        # Some VAE architectures return
        # multiple outputs.
        if isinstance(
            reconstruction,
            (
                list,
                tuple
            )
        ):

            reconstruction = (
                reconstruction[-1]
            )

        reconstruction = np.asarray(
            reconstruction
        )

        if (
            reconstruction.shape
            !=
            X_seq.shape
        ):

            print(
                "[VAE WARN] "
                "Output shape does not match "
                "input sequence."
            )

            return (
                0.0,
                0
            )

        mse = float(
            np.mean(
                np.square(
                    X_seq
                    -
                    reconstruction
                )
            )
        )

        flag = int(
            mse
            >
            self.vae_threshold
        )

        return (
            mse,
            flag
        )

    # =========================================================
    # GRU
    # =========================================================

    def _predict_gru(
        self,
        buffer
    ):

        X_raw = (
            buffer[
                self.GRU_COLS
            ]
            .values
            .astype(
                np.float32
            )
        )

        scaler_x = (
            self.gru_meta[
                "scaler_X"
            ]
        )

        X_scaled = (
            scaler_x
            .transform(
                X_raw
            )
            .astype(
                np.float32
            )
        )

        X_seq = np.expand_dims(
            X_scaled,
            axis=0
        )

        prediction = (
            self.gru.predict(
                X_seq,
                verbose=0
            )
        )

        # Preserve existing GRU contract.
        target = (
            self.gru_meta[
                "scaler_y"
            ]
            .transform(
                [
                    X_raw[
                        -1,
                        :3
                    ]
                ]
            )
        )

        prediction = np.asarray(
            prediction
        )

        target = np.asarray(
            target
        )

        if (
            prediction.shape
            !=
            target.shape
        ):

            prediction = (
                prediction.reshape(
                    target.shape
                )
            )

        error = float(
            np.mean(
                np.abs(
                    target
                    -
                    prediction
                )
            )
        )

        return error

    # =========================================================
    # XGBOOST SAFE PREDICTION
    # =========================================================

    def _predict_xgb(
        self,
        model,
        frame,
        default=0
    ):

        try:

            result = model.predict(
                frame
            )

            return int(
                result[0]
            )

        except Exception as exc:

            print(
                f"[XGB WARN] {exc}"
            )

            return int(
                default
            )

    # =========================================================
    # MAIN PROCESSING
    # =========================================================

    def process_tick(
        self,
        raw_sensor_data,
        node_id="default",
        auto_render_graph=False
    ):

        try:

            state = (
                self.get_node_state(
                    node_id
                )
            )

            state[
                "step_counter"
            ] += 1

            step = (
                state[
                    "step_counter"
                ]
            )

            # -------------------------------------------------
            # DUPLICATE PACKET PROTECTION
            # -------------------------------------------------

            signature = None

            if (
                isinstance(
                    raw_sensor_data,
                    dict
                )
                and
                raw_sensor_data.get(
                    "ts_ms"
                )
                is not None
            ):

                signature = (

                    raw_sensor_data.get(
                        "ts_ms"
                    ),

                    raw_sensor_data.get(
                        "node_id",
                        node_id
                    ),
                )

                if (
                    signature
                    ==
                    state[
                        "last_packet_signature"
                    ]
                ):

                    return {

                        "status":
                            "DUPLICATE",

                        "step":
                            step,
                    }

                state[
                    "last_packet_signature"
                ] = signature

            # -------------------------------------------------
            # VALIDATE INPUT
            # -------------------------------------------------

            sensor = (
                self._validate_and_fill_inputs(
                    raw_sensor_data,
                    state
                )
            )

            # -------------------------------------------------
            # TIME STEP
            # -------------------------------------------------

            dt = (
                self._get_dt(
                    raw_sensor_data,
                    state
                )
            )

            # -------------------------------------------------
            # PREVIOUS FEATURE ROW
            # -------------------------------------------------

            previous_tick = (

                state[
                    "buffer"
                ]
                .iloc[
                    -1
                ]
                .to_dict()

                if not state[
                    "buffer"
                ].empty

                else None
            )

            # -------------------------------------------------
            # FEATURE ENGINEERING
            # -------------------------------------------------

            processed = (
                self._calculate_dl_features(
                    sensor,
                    state,
                    previous_tick,
                    dt
                )
            )

            # -------------------------------------------------
            # APPEND TO ROLLING BUFFER
            # -------------------------------------------------

            state[
                "buffer"
            ] = pd.concat(

                [
                    state[
                        "buffer"
                    ],

                    pd.DataFrame(
                        [
                            processed
                        ]
                    ),
                ],

                ignore_index=True
            )

            # Keep only last 24.
            if (
                len(
                    state[
                        "buffer"
                    ]
                )
                >
                self.DL_WINDOW
            ):

                state[
                    "buffer"
                ] = (

                    state[
                        "buffer"
                    ]
                    .iloc[
                        -self.DL_WINDOW:
                    ]
                    .reset_index(
                        drop=True
                    )
                )

            # -------------------------------------------------
            # BUFFERING
            # -------------------------------------------------

            if (
                len(
                    state[
                        "buffer"
                    ]
                )
                <
                self.DL_WINDOW
            ):

                return {

                    "status":
                        "BUFFERING",

                    "buffer_size":
                        len(
                            state[
                                "buffer"
                            ]
                        ),

                    "required":
                        self.DL_WINDOW,

                    "data_source":
                        state[
                            "data_source"
                        ],
                }

            # =================================================
            # 1. DEEP LEARNING
            # =================================================

            (
                lstm_mse,
                lstm_flag,
                X_ae_seq
            ) = self._predict_lstm(
                state[
                    "buffer"
                ]
            )

            (
                vae_mse,
                vae_flag
            ) = self._predict_vae(
                X_ae_seq
            )

            gru_error = (
                self._predict_gru(
                    state[
                        "buffer"
                    ]
                )
            )

            # -------------------------------------------------
            # XGBOOST DEEP LEARNING FUSION
            # -------------------------------------------------

            ctx = (
                X_ae_seq[
                    :,
                    -1,
                    :9
                ][0]
            )

            fusion_df = (
                pd.DataFrame(

                    [
                        ctx
                    ],

                    columns=[
                        "rotation_x",
                        "rotation_y",
                        "rotation_z",

                        "acceleration_x",
                        "acceleration_y",
                        "acceleration_z",

                        "raindrop",
                        "vibration",
                        "soil20cm",
                    ]
                )
            )

            fusion_df[
                "lstm_mse"
            ] = lstm_mse

            fusion_df[
                "lstm_flag"
            ] = lstm_flag

            fusion_df[
                "vae_mse"
            ] = vae_mse

            fusion_df[
                "vae_flag"
            ] = vae_flag

            fusion_df[
                "gru_trajectory_error"
            ] = gru_error

            dl_risk = (
                self._predict_xgb(
                    self.dl_fusion_xgb,
                    fusion_df,
                    default=lstm_flag
                )
            )

            # =================================================
            # 2. STATISTICAL / PHYSICAL ML TRACK
            # =================================================

            recent = (
                state[
                    "buffer"
                ]
                .tail(
                    self.ML_WINDOW
                )
            )

            ml_rows = []

            for _, row in recent.iterrows():

                ml_rows.append(

                    {

                        "Accel_X (m/s^2)":
                            float(
                                row[
                                    "acceleration_x"
                                ]
                                /
                                self.ACCEL_DOMAIN_SCALE
                            ),

                        "Accel_Y (m/s^2)":
                            float(
                                row[
                                    "acceleration_y"
                                ]
                                /
                                self.ACCEL_DOMAIN_SCALE
                            ),

                        "Accel_Z (m/s^2)":
                            float(
                                row[
                                    "acceleration_z"
                                ]
                                /
                                self.ACCEL_DOMAIN_SCALE
                            ),

                        "Strain (με)":
                            float(
                                sensor[
                                    "strain"
                                ]
                            ),

                        "Temp (°C)":
                            float(
                                row[
                                    "temperature"
                                ]
                            ),

                        "roof_convergence_cm":
                            float(
                                sensor[
                                    "roof_convergence_cm"
                                ]
                            ),
                    }
                )

            ml_buffer = (
                pd.DataFrame(
                    ml_rows
                )
            )

            ml_features = {}

            for col in self.ML_COLS:

                values = (
                    ml_buffer[
                        col
                    ]
                    .astype(
                        float
                    )
                )

                ml_features[
                    f"{col}_live"
                ] = float(
                    values.iloc[-1]
                )

                ml_features[
                    f"{col}_mean"
                ] = float(
                    values.mean()
                )

                ml_features[
                    f"{col}_std"
                ] = float(
                    values.std(
                        ddof=0
                    )
                )

                ml_features[
                    f"{col}_max"
                ] = float(
                    values.max()
                )

            ml_frame = (
                pd.DataFrame(
                    [
                        ml_features
                    ]
                )
            )

            ml_risk = (
                self._predict_xgb(
                    self.ml_detector_xgb,
                    ml_frame,
                    default=0
                )
            )

            # =================================================
            # 3. FINAL DECISION
            # =================================================

            if (

                ml_risk >= 2

                or

                (
                    dl_risk >= 1
                    and
                    ml_risk >= 1
                )

            ):

                ultimate_score = 2

            elif (

                dl_risk >= 1

                or

                ml_risk >= 1

            ):

                ultimate_score = 1

            else:

                ultimate_score = 0

            # -------------------------------------------------
            # STATUS
            # -------------------------------------------------

            if ultimate_score == 2:

                status_text = (
                    "CRITICAL COLLAPSE"
                )

            elif ultimate_score == 1:

                status_text = (
                    "WARNING"
                )

            else:

                status_text = (
                    "SAFE"
                )

            # -------------------------------------------------
            # TELEMETRY
            # -------------------------------------------------

            tilt_val = float(
                processed[
                    "rotation_x"
                ]
            )

            roof_val = float(
                sensor[
                    "roof_convergence_cm"
                ]
            )

            # -------------------------------------------------
            # HISTORY
            # -------------------------------------------------

            history = (
                state[
                    "history"
                ]
            )

            history[
                "step"
            ].append(
                step
            )

            history[
                "tilt_x"
            ].append(
                tilt_val
            )

            history[
                "roof_dist"
            ].append(
                roof_val
            )

            history[
                "lstm_mse"
            ].append(
                lstm_mse
            )

            history[
                "gru_error"
            ].append(
                gru_error
            )

            history[
                "risk_score"
            ].append(
                ultimate_score
            )

            self._trim_history(
                history
            )

            # -------------------------------------------------
            # LOGGING
            # -------------------------------------------------

            self._write_log(

                {

                    "step":
                        step,

                    "node_id":
                        node_id,

                    "data_source":
                        state[
                            "data_source"
                        ],

                    "status":
                        status_text,

                    "dl_risk":
                        dl_risk,

                    "ml_risk":
                        ml_risk,

                    "tilt_x":
                        tilt_val,

                    "roof_convergence":
                        roof_val,

                    "lstm_mse":
                        lstm_mse,

                    "vae_mse":
                        vae_mse,

                    "gru_error":
                        gru_error,
                }
            )

            # -------------------------------------------------
            # DASHBOARD
            # -------------------------------------------------

            if (

                auto_render_graph

                and

                len(
                    history[
                        "step"
                    ]
                )
                > 1

            ):

                self.generate_dashboard(

                    self.dashboard_file,

                    node_id=node_id
                )

            # =================================================
            # TERMINAL DIAGNOSTIC
            # =================================================

            print(

                f"[ML] "

                f"node={node_id} "

                f"source="
                f"{state['data_source']} "

                f"LSTM="
                f"{lstm_mse:.4f} "

                f"(thr="
                f"{self.lstm_threshold:.4f}) "

                f"VAE="
                f"{vae_mse:.4f} "

                f"GRU="
                f"{gru_error:.4f} "

                f"DL="
                f"{dl_risk} "

                f"ML="
                f"{ml_risk} "

                f"=> "
                f"{status_text}"
            )

            # =================================================
            # API RESPONSE
            # =================================================

            return {

                "status":
                    "ACTIVE",

                "data_source":
                    state[
                        "data_source"
                    ],

                "ultimate_decision":
                    {

                        "score":
                            ultimate_score,

                        "status_text":
                            status_text,
                    },

                "telemetry":
                    {

                        "lstm_mse":
                            round(
                                lstm_mse,
                                4
                            ),

                        "lstm_threshold":
                            round(
                                self.lstm_threshold,
                                4
                            ),

                        "vae_mse":
                            round(
                                vae_mse,
                                4
                            ),

                        "gru_error":
                            round(
                                gru_error,
                                4
                            ),

                        "tilt_x":
                            round(
                                tilt_val,
                                2
                            ),

                        "roof_convergence":
                            round(
                                roof_val,
                                1
                            ),

                        "dl_risk":
                            dl_risk,

                        "ml_risk":
                            ml_risk,
                    },
            }

        except Exception as exc:

            print(
                f"[PIPELINE ERROR] "
                f"{exc}"
            )

            traceback.print_exc()

            return {

                "status":
                    "ERROR",

                "message":
                    str(exc)
            }

    # =========================================================
    # LOGGING
    # =========================================================

    def _write_log(
        self,
        data
    ):

        try:

            pd.DataFrame(
                [data]
            ).to_csv(

                self.log_file,

                mode="a",

                header=not os.path.exists(
                    self.log_file
                ),

                index=False
            )

        except Exception as exc:

            print(
                f"[CSV WARN] {exc}"
            )

    # =========================================================
    # DASHBOARD
    # =========================================================

    def generate_dashboard(
        self,
        save_path=None,
        node_id=None
    ):

        save_path = (
            save_path
            or
            self.dashboard_file
        )

        # -----------------------------------------------------
        # Find node
        # -----------------------------------------------------

        if node_id is None:

            for nid, state in (
                self.node_state.items()
            ):

                if (
                    len(
                        state[
                            "history"
                        ][
                            "step"
                        ]
                    )
                    >= 2
                ):

                    node_id = nid

                    break

        if node_id is None:

            return False

        history = (
            self.get_node_history(
                node_id
            )
        )

        if (
            len(
                history[
                    "step"
                ]
            )
            < 2
        ):

            return False

        try:

            df = pd.DataFrame(
                history
            )

            # -------------------------------------------------
            # FIGURE
            # -------------------------------------------------

            fig, axes = plt.subplots(
                2,
                2,
                figsize=(
                    15,
                    9
                )
            )

            # -------------------------------------------------
            # TILT
            # -------------------------------------------------

            axes[
                0,
                0
            ].plot(

                df[
                    "step"
                ],

                df[
                    "tilt_x"
                ]
            )

            axes[
                0,
                0
            ].set_title(
                "Structural Tilt / Rotation X"
            )

            axes[
                0,
                0
            ].set_xlabel(
                "Time Tick"
            )

            axes[
                0,
                0
            ].set_ylabel(
                "Degrees"
            )

            axes[
                0,
                0
            ].grid(
                True,
                alpha=0.3
            )

            # -------------------------------------------------
            # ROOF CONVERGENCE
            # -------------------------------------------------

            axes[
                0,
                1
            ].plot(

                df[
                    "step"
                ],

                df[
                    "roof_dist"
                ]
            )

            axes[
                0,
                1
            ].axhline(
                300,
                linestyle="--",
                label="Nominal"
            )

            axes[
                0,
                1
            ].axhline(
                285,
                linestyle="--",
                label="Sag Limit"
            )

            axes[
                0,
                1
            ].axhline(
                250,
                linestyle="--",
                label="Critical"
            )

            axes[
                0,
                1
            ].set_title(
                "Roof Convergence"
            )

            axes[
                0,
                1
            ].set_xlabel(
                "Time Tick"
            )

            axes[
                0,
                1
            ].set_ylabel(
                "Centimeters"
            )

            axes[
                0,
                1
            ].legend(
                fontsize="small"
            )

            axes[
                0,
                1
            ].grid(
                True,
                alpha=0.3
            )

            # -------------------------------------------------
            # LSTM
            # -------------------------------------------------

            axes[
                1,
                0
            ].plot(

                df[
                    "step"
                ],

                df[
                    "lstm_mse"
                ]
            )

            axes[
                1,
                0
            ].axhline(

                self.lstm_threshold,

                linestyle="--",

                label="LSTM Threshold"
            )

            axes[
                1,
                0
            ].set_yscale(
                "log"
            )

            axes[
                1,
                0
            ].set_title(
                "LSTM-AE Reconstruction Error"
            )

            axes[
                1,
                0
            ].set_xlabel(
                "Time Tick"
            )

            axes[
                1,
                0
            ].set_ylabel(
                "MSE (Log)"
            )

            axes[
                1,
                0
            ].legend(
                fontsize="small"
            )

            axes[
                1,
                0
            ].grid(
                True,
                alpha=0.3
            )

            # -------------------------------------------------
            # GRU
            # -------------------------------------------------

            axes[
                1,
                1
            ].plot(

                df[
                    "step"
                ],

                df[
                    "gru_error"
                ]
            )

            axes[
                1,
                1
            ].set_title(
                "GRU Prediction Deviation"
            )

            axes[
                1,
                1
            ].set_xlabel(
                "Time Tick"
            )

            axes[
                1,
                1
            ].set_ylabel(
                "Absolute Error"
            )

            axes[
                1,
                1
            ].grid(
                True,
                alpha=0.3
            )

            # -------------------------------------------------
            # TITLE
            # -------------------------------------------------

            fig.suptitle(

                f"Bhu-Rakshak Structural Monitoring "
                f"— Node {node_id}",

                fontsize=16
            )

            plt.tight_layout()

            self._ensure_parent(
                save_path
            )

            fig.savefig(

                save_path,

                dpi=150,

                bbox_inches="tight"
            )

            plt.close(
                fig
            )

            return True

        except Exception as exc:

            print(
                f"[GRAPHICS ERROR] "
                f"{exc}"
            )

            traceback.print_exc()

            plt.close(
                "all"
            )

            return False


# =============================================================
# DIRECT TEST
# =============================================================

if __name__ == "__main__":

    print(
        "=" * 70
    )

    print(
        "BHURAKSHAK UNIVERSAL ENGINE"
    )

    print(
        "=" * 70
    )

    engine = (
        StructuralAnomalyEngine()
    )

    print(
        "[INIT] Engine started successfully."
    )