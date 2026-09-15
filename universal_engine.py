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
import seaborn as sns
import matplotlib.gridspec as gridspec
import warnings

warnings.filterwarnings('ignore')
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'


class Sampling(keras.layers.Layer):
    def call(self, inputs):
        z_mean, z_log_var = inputs
        batch = tf.shape(z_mean)[0]
        dim   = tf.shape(z_mean)[1]
        dtype = z_mean.dtype
        epsilon = tf.random.normal(
            shape=(batch, dim), mean=0.0, stddev=1.0, dtype=dtype,
        )
        return z_mean + tf.exp(0.5 * z_log_var) * epsilon

    def compute_output_shape(self, input_shape):
        return input_shape[0]

    def compute_output_spec(self, inputs):
        z_mean, _ = inputs
        return tf.TensorSpec(shape=z_mean.shape, dtype=z_mean.dtype)

    def get_config(self):
        return super().get_config()


class StructuralAnomalyEngine:
    """Universal Master Pipeline for Structural Anomaly Detection.
       Now keeps one rolling buffer per node id."""

    MAX_HISTORY = 1000

    def __init__(
        self,
        model_dir='models',
        log_file='public/telemetry_log.csv',
        dashboard_file='public/scientific_dashboard.png',
    ):
        print("[INIT] Booting Universal Structural Anomaly Engine...")
        self.model_dir = model_dir
        self.log_file = log_file
        self.dashboard_file = dashboard_file

        self.has_vae = True
        self.dl_window = 24
        self.ml_window = 10

        # ---- per-node state ----
        # node_id -> {'buffer': DataFrame, 'history': {...}, 'step_counter': int}
        self.node_state = {}

        self._ensure_parent(self.log_file)
        self._ensure_parent(self.dashboard_file)

        self._load_models()
        print("[INIT] Engine Ready. Awaiting telemetry stream.")

    # -------------------------------------------------------------
    # Per-node state helpers
    # -------------------------------------------------------------
    def _new_node_state(self):
        return {
            'buffer': pd.DataFrame(),
            'step_counter': 0,
            'history': {
                'step': [], 'tilt_x': [], 'roof_dist': [],
                'lstm_mse': [], 'gru_error': [], 'risk_score': [],
            },
        }

    def get_node_state(self, node_id):
        if node_id not in self.node_state:
            self.node_state[node_id] = self._new_node_state()
        return self.node_state[node_id]

    def get_node_history(self, node_id):
        return self.get_node_state(node_id)['history']

    @staticmethod
    def _ensure_parent(path):
        if not path:
            return
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)

    def _trim_history(self, history):
        if len(history['step']) <= self.MAX_HISTORY:
            return
        excess = len(history['step']) - self.MAX_HISTORY
        for key in history:
            del history[key][:excess]

    # -------------------------------------------------------------
    # Model loading
    # -------------------------------------------------------------
    def _load_models(self):
        try:
            self.lstm = keras.models.load_model(
                f'{self.model_dir}/lstm_autoencoder_final.keras'
            )
            self.lstm_meta = joblib.load(f'{self.model_dir}/anomaly_metadata.pkl')
        except Exception:
            print("[CRITICAL ERROR] Failed to load LSTM.")
            print(traceback.format_exc())
            raise

        try:
            self.vae = keras.models.load_model(
                f'{self.model_dir}/vae_final.keras',
                custom_objects={'Sampling': Sampling},
                compile=False,
                safe_mode=False,
            )
            self.vae_meta = joblib.load(f'{self.model_dir}/vae_metadata.pkl')
            self.has_vae = True
        except Exception as vae_exc:
            print(f"[WARN] VAE failed to load — continuing without VAE. Reason: {vae_exc}")
            self.vae = None
            self.vae_meta = {'selected_threshold': float('inf')}
            self.has_vae = False

        try:
            self.gru = keras.models.load_model(
                f'{self.model_dir}/gru_forecaster.keras',
                compile=False,
            )
            self.gru_meta = joblib.load(f'{self.model_dir}/gru_metadata.pkl')
        except Exception:
            print("[CRITICAL ERROR] Failed to load GRU.")
            print(traceback.format_exc())
            raise

        try:
            self.dl_fusion_xgb = xgb.XGBClassifier()
            self.dl_fusion_xgb.load_model(
                f'{self.model_dir}/xgboost_production_ensemble.json'
            )
            self.ml_detector_xgb = xgb.XGBClassifier()
            self.ml_detector_xgb.load_model(
                f'{self.model_dir}/xgboost_statistical_detector_2.0.json'
            )
        except Exception:
            print("[CRITICAL ERROR] Failed to load XGBoost models.")
            print(traceback.format_exc())
            raise

    # -------------------------------------------------------------
    # Feature engineering
    # -------------------------------------------------------------
    def _validate_and_fill_inputs(self, raw_data):
        required_keys = {
            'rotation_x': 1.1, 'rotation_y': 5.5, 'rotation_z': 77.7,
            'acceleration_x': 0.01, 'acceleration_y': 0.01, 'acceleration_z': 0.06,
            'raindrop': 0.0, 'vibration': 0.0,
            'soil20cm': 100.0, 'soil40cm': 100.0, 'soil60cm': 100.0,
            'temperature': 25.0, 'humidity': 70.0,
            'Accel_X (m/s^2)': 0.1, 'Accel_Y (m/s^2)': 0.0, 'Accel_Z (m/s^2)': 9.8,
            'Strain (με)': 110.0, 'Temp (°C)': 25.0,
            'roof_convergence_cm': 300.0,
        }
        safe_data = {}
        for key, default_val in required_keys.items():
            val = raw_data.get(key, default_val)
            try:
                safe_data[key] = float(val) if val is not None else float(default_val)
            except (TypeError, ValueError):
                safe_data[key] = float(default_val)
        return safe_data

    def _calculate_dl_features(self, current_tick, previous_tick):
        tick = current_tick.copy()

        tick['acceleration_x_filtered'] = tick['acceleration_x'] * 0.9
        tick['acceleration_y_filtered'] = tick['acceleration_y'] * 0.9
        tick['acceleration_z_filtered'] = tick['acceleration_z'] * 0.9
        tick['acceleration_magnitude'] = float(np.sqrt(
            tick['acceleration_x'] ** 2
            + tick['acceleration_y'] ** 2
            + tick['acceleration_z'] ** 2
        ))
        tick['soil_mean'] = (
            tick['soil20cm'] + tick['soil40cm'] + tick['soil60cm']
        ) / 3.0
        tick['soil_gradient'] = 0.0

        if previous_tick is None:
            for diff_key in (
                'rotation_x_change', 'rotation_y_change', 'rotation_z_change',
                'acceleration_magnitude_change', 'soil_change', 'soil_mean_change',
                'temperature_change', 'humidity_change',
            ):
                tick[diff_key] = 0.0
        else:
            tick['rotation_x_change'] = tick['rotation_x'] - previous_tick['rotation_x']
            tick['rotation_y_change'] = tick['rotation_y'] - previous_tick['rotation_y']
            tick['rotation_z_change'] = tick['rotation_z'] - previous_tick['rotation_z']

            prev_mag = float(np.sqrt(
                previous_tick['acceleration_x'] ** 2
                + previous_tick['acceleration_y'] ** 2
                + previous_tick['acceleration_z'] ** 2
            ))
            tick['acceleration_magnitude_change'] = tick['acceleration_magnitude'] - prev_mag
            tick['soil_change'] = tick['soil20cm'] - previous_tick['soil20cm']

            prev_soil_mean = (
                previous_tick['soil20cm']
                + previous_tick['soil40cm']
                + previous_tick['soil60cm']
            ) / 3.0
            tick['soil_mean_change'] = tick['soil_mean'] - prev_soil_mean
            tick['temperature_change'] = tick['temperature'] - previous_tick['temperature']
            tick['humidity_change'] = tick['humidity'] - previous_tick['humidity']

        return tick

    # -------------------------------------------------------------
    # Main loop (per node)
    # -------------------------------------------------------------
    def process_tick(self, raw_sensor_data, node_id='default', auto_render_graph=False):
        try:
            state = self.get_node_state(node_id)
            state['step_counter'] += 1
            step = state['step_counter']

            validated_data = self._validate_and_fill_inputs(raw_sensor_data)

            previous_tick = (
                state['buffer'].iloc[-1].to_dict()
                if not state['buffer'].empty
                else None
            )
            processed_tick = self._calculate_dl_features(validated_data, previous_tick)

            state['buffer'] = pd.concat(
                [state['buffer'], pd.DataFrame([processed_tick])],
                ignore_index=True,
            )
            if len(state['buffer']) > self.dl_window:
                state['buffer'] = (
                    state['buffer'].iloc[-self.dl_window:].reset_index(drop=True)
                )

            if len(state['buffer']) < self.dl_window:
                return {
                    "status": "BUFFERING",
                    "ready_pct": round((len(state['buffer']) / self.dl_window) * 100),
                }

            # ==========================================
            # 1. DEEP LEARNING TRACK
            # ==========================================
            ae_cols = [
                'rotation_x', 'rotation_y', 'rotation_z',
                'acceleration_x', 'acceleration_y', 'acceleration_z',
                'raindrop', 'vibration',
                'soil20cm', 'soil40cm', 'soil60cm',
                'temperature', 'humidity',
                'acceleration_x_filtered', 'acceleration_y_filtered',
                'acceleration_z_filtered', 'acceleration_magnitude',
                'rotation_x_change', 'rotation_y_change', 'rotation_z_change',
                'soil_mean', 'soil_gradient', 'soil_change',
                'acceleration_magnitude_change', 'soil_mean_change',
                'temperature_change', 'humidity_change',
            ]

            X_ae_seq = np.expand_dims(
                self.lstm_meta['scaler'].transform(
                    state['buffer'][ae_cols].values
                ),
                axis=0,
            ).astype(np.float32)

            lstm_recon = self.lstm.predict(X_ae_seq, verbose=0)
            lstm_mse = float(np.mean(np.square(X_ae_seq - lstm_recon)))

            if self.has_vae:
                vae_recon = self.vae.predict(X_ae_seq, verbose=0)
                vae_mse = float(np.mean(np.square(X_ae_seq - vae_recon)))
            else:
                vae_mse = 0.0

            gru_cols = [
                'rotation_x', 'rotation_y', 'rotation_z',
                'acceleration_x', 'acceleration_y', 'acceleration_z',
            ]
            X_gru_raw = state['buffer'][gru_cols].values
            X_gru_seq = np.expand_dims(
                self.gru_meta['scaler_X'].transform(X_gru_raw), axis=0
            ).astype(np.float32)
            gru_pred = self.gru.predict(X_gru_seq, verbose=0)
            y_true = self.gru_meta['scaler_y'].transform([X_gru_raw[-1, :3]])
            gru_error = float(np.mean(np.abs(y_true - gru_pred)))

            ctx = X_ae_seq[:, -1, :9][0]
            fusion_df = pd.DataFrame(
                [ctx],
                columns=[
                    'rotation_x', 'rotation_y', 'rotation_z',
                    'acceleration_x', 'acceleration_y', 'acceleration_z',
                    'raindrop', 'vibration', 'soil20cm',
                ],
            )
            fusion_df['lstm_mse'] = lstm_mse
            fusion_df['lstm_flag'] = int(
                lstm_mse > self.lstm_meta['selected_threshold']
            )
            fusion_df['vae_mse'] = vae_mse
            fusion_df['vae_flag'] = int(
                vae_mse > self.vae_meta['selected_threshold']
            ) if self.has_vae else 0
            fusion_df['gru_trajectory_error'] = gru_error
            dl_risk = int(self.dl_fusion_xgb.predict(fusion_df)[0])

            # ==========================================
            # 2. MACHINE LEARNING TRACK
            # ==========================================
            ml_buffer = state['buffer'].iloc[-self.ml_window:]
            ml_cols = [
                'Accel_X (m/s^2)', 'Accel_Y (m/s^2)', 'Accel_Z (m/s^2)',
                'Strain (με)', 'Temp (°C)', 'roof_convergence_cm',
            ]
            ml_features = {}
            for col in ml_cols:
                ml_features[f'{col}_live'] = float(ml_buffer[col].iloc[-1])
                ml_features[f'{col}_mean'] = float(ml_buffer[col].mean())
                ml_features[f'{col}_std']  = float(ml_buffer[col].std())
                ml_features[f'{col}_max']  = float(ml_buffer[col].max())

            ml_risk = int(
                self.ml_detector_xgb.predict(pd.DataFrame([ml_features]))[0]
            )

            # ==========================================
            # 3. DECISION MATRIX
            # ==========================================
            if ml_risk == 2 or (dl_risk == 1 and ml_risk == 1):
                ultimate_score = 2
            elif dl_risk == 1 or ml_risk == 1:
                ultimate_score = 1
            else:
                ultimate_score = 0

            status_text = (
                "CRITICAL COLLAPSE" if ultimate_score == 2
                else "WARNING" if ultimate_score == 1
                else "SAFE"
            )

            tilt_val = float(processed_tick['rotation_x'])
            roof_val = ml_features['roof_convergence_cm_live']

            state['history']['step'].append(step)
            state['history']['tilt_x'].append(tilt_val)
            state['history']['roof_dist'].append(roof_val)
            state['history']['lstm_mse'].append(lstm_mse)
            state['history']['gru_error'].append(gru_error)
            state['history']['risk_score'].append(ultimate_score)
            self._trim_history(state['history'])

            try:
                log_data = pd.DataFrame([{
                    'step': step,
                    'status': status_text,
                    'tilt_x': tilt_val,
                    'roof_convergence': roof_val,
                    'lstm_mse': lstm_mse,
                    'gru_error': gru_error,
                }])
                log_data.to_csv(
                    self.log_file,
                    mode='a',
                    header=not os.path.exists(self.log_file),
                    index=False,
                )
            except Exception as log_exc:
                print(f"[CSV WARN] {log_exc}")

            if auto_render_graph and len(state['history']['step']) > 1:
                self.generate_dashboard(
                    save_path=self.dashboard_file,
                    node_id=node_id,
                )

            return {
                "status": "ACTIVE",
                "ultimate_decision": {
                    "score": ultimate_score,
                    "status_text": status_text,
                },
                "telemetry": {
                    "lstm_mse": round(lstm_mse, 4),
                    "vae_mse": round(vae_mse, 4),
                    "gru_error": round(gru_error, 4),
                    "tilt_x": round(tilt_val, 2),
                    "roof_convergence": round(roof_val, 1),
                },
            }

        except Exception as e:
            print(f"[PIPELINE ERROR] {str(e)}")
            traceback.print_exc()
            return {"status": "ERROR", "message": str(e)}

    # -------------------------------------------------------------
    # Dashboard rendering (per node)
    # -------------------------------------------------------------
    def generate_dashboard(self, save_path=None, node_id=None):
        save_path = save_path or self.dashboard_file

        if node_id is None:
            for nid, st in self.node_state.items():
                if len(st['history']['step']) >= 2:
                    node_id = nid
                    break
        if node_id is None:
            return False

        hist = self.get_node_history(node_id)
        if len(hist['step']) < 2:
            return False

        try:
            df_hist = pd.DataFrame(hist)

            try:
                plt.style.use('seaborn-v0_8-whitegrid')
            except Exception:
                try:
                    plt.style.use('seaborn-whitegrid')
                except Exception:
                    plt.style.use('ggplot')

            fig = plt.figure(figsize=(16, 10))
            gs = gridspec.GridSpec(2, 3, height_ratios=[1, 1])

            colors = {0: '#2ca02c', 1: '#ff7f0e', 2: '#d62728'}
            scatter_colors = df_hist['risk_score'].map(colors)

            ax1 = plt.subplot(gs[0, 0])
            ax1.plot(df_hist['step'], df_hist['tilt_x'], color='#1f77b4', lw=2)
            ax1.scatter(df_hist['step'], df_hist['tilt_x'], c=scatter_colors, zorder=5)
            ax1.set_title('Structural Tilt Kinematics (Rotation X)', fontweight='bold')
            ax1.set_ylabel('Degrees')

            ax2 = plt.subplot(gs[0, 1])
            ax2.plot(df_hist['step'], df_hist['roof_dist'], color='#8c564b', lw=2)
            ax2.scatter(df_hist['step'], df_hist['roof_dist'], c=scatter_colors, zorder=5)
            ax2.axhline(300, color='gray', ls='--', alpha=0.5, label='Nominal')
            ax2.axhline(285, color='#ff7f0e', ls='--', alpha=0.5, label='Sag Limit')
            ax2.axhline(250, color='#d62728', ls='--', alpha=0.5, label='Critical Floor')
            ax2.set_title('Roof Convergence (ToF Displacement)', fontweight='bold')
            ax2.set_ylabel('Centimeters')
            ax2.legend(loc='lower left', fontsize='small')

            ax3 = plt.subplot(gs[1, 0])
            ax3.plot(df_hist['step'], df_hist['lstm_mse'], color='#ff7f0e', lw=2)
            ax3.set_yscale('log')
            ax3.set_title('LSTM-AE Reconstruction Error', fontweight='bold')
            ax3.set_ylabel('MSE (Log Scale)')
            ax3.set_xlabel('Time (Ticks)')

            ax4 = plt.subplot(gs[1, 1])
            ax4.plot(df_hist['step'], df_hist['gru_error'], color='#d62728', lw=2)
            ax4.set_title('GRU Prediction Deviation', fontweight='bold')
            ax4.set_ylabel('Absolute Error')
            ax4.set_xlabel('Time (Ticks)')

            ax5 = plt.subplot(gs[:, 2])
            safe_data = df_hist[df_hist['risk_score'] == 0]['lstm_mse']
            crit_data = df_hist[df_hist['risk_score'] == 2]['lstm_mse']
            if not safe_data.empty:
                sns.kdeplot(safe_data, fill=True, color='#2ca02c', ax=ax5, label='Safe State')
            if not crit_data.empty:
                sns.kdeplot(crit_data, fill=True, color='#d62728', ax=ax5, label='Critical State')
            ax5.set_title('Density Distribution Analysis', fontweight='bold')
            ax5.set_xlabel('LSTM MSE Density')
            ax5.legend()

            plt.tight_layout()
            self._ensure_parent(save_path)
            plt.savefig(save_path, dpi=150)
            plt.close(fig)
            return True

        except Exception as e:
            print(f"[GRAPHICS ERROR] {str(e)}")
            traceback.print_exc()
            try:
                plt.close('all')
            except Exception:
                pass
            return False


if __name__ == "__main__":
    engine = StructuralAnomalyEngine()