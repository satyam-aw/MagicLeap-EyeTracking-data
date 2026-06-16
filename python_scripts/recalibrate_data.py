"""
Post-Hoc Spatial Eye-Tracking Recalibration and Error Metrics Pipeline

This script automates the correction of systematic tracking drift and offset errors 
in raw eye-tracking datasets. It fits individualised linear regression models for 
each participant based on a dedicated calibration task, applies high-speed matrix 
vectorization to correct gaze coordinates across all experimental tasks (e.g., w1, 
w2, w3, s4, b5), and logs spatial error performance metrics to a central summary file.

Usage:
  python recalibrate_data.py --type moving
  python recalibrate_data.py --type static --with w1

Pipeline Processing Logic:
  0. Early Skip: Skips processing if the participant already exists in the central error log.
  1. File-by-File Verification: Evaluates required calibrated files one by one.
  2. On-Demand Recalibration: Invokes a vectorized matrix generator function if a file is missing.
  3. Metric Extraction: Computes spatial Euclidean and vector errors for verified files.
  4. Logging: Appends and preserves a consolidated data record in 'error_df.csv'.

Requirements:
  - Input Directory: './participant-data/' (containing individual participant subfolders)
  - Output Directory: 
        './recalibrated_data/moving_target/' (for type 'moving' and calibrated with task 'cal')
        './recalibrated_data_others/<calibration_task>/moving_target/' (for type 'moving' and calibrated with task other than'cal')
  - Custom Module: 'utils.util' (containing clean_df, shifted_df, regression_models, etc.)

Author: Satyam Awasthi
"""
import os
import pathlib
import itertools
import numpy as np
import pandas as pd
from tqdm import tqdm
import argparse
from util import *

# ---------------------------------------------------------------------------
# Command-Line Argument Parsing
# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser(description="Run Eye-Tracking Recalibration Pipeline.")
parser.add_argument(
    '--type', 
    type=str, 
    required=True, 
    choices=['moving', 'static'], 
    help="Specify the paradigm structure type: 'moving' or 'static'."
)
parser.add_argument(
    '--with', 
    type=str,
    dest='with_val', # Using 'dest' because 'args.with' is a reserved keyword in Python
    default='cal',
    choices=['cal', 'w1', 'w2', 'w3', 's4', 'b5'],
    help="Specify the calibration task, to calibrate all the other tasks with using linear regression (default: 'cal')."
)
args = parser.parse_args()
target_type = args.type.strip()
is_moving = True if target_type == "moving" else False
calibrate_with = args.with_val

# ---------------------------------------------------------------------------
# Setup directories
# ---------------------------------------------------------------------------
raw_data_dir = get_raw_data_directory()
recalibrated_data_dir = f'../recalibrated_data/{target_type}_target' if calibrate_with == "cal" else f'../recalibrated_data_others/{calibrate_with}/{target_type}_target'
os.makedirs(recalibrated_data_dir, exist_ok=True)

# Initialize Error DataFrame Schema
cols = [
    'Name', 'w1_euc', 'w1_vec', 'w1_index', 'w2_euc', 'w2_vec', 'w2_index',
    'w3_euc', 'w3_vec', 'w3_index', 's4_euc', 's4_vec', 's4_index',
    'b5_euc', 'b5_vec', 'b5_index', 'callibrate_euc', 'callibrate_vec',
    'callibrate_index', 'callibrate_pearsonr', 'callibrate_pearsonr_recal'
]
error_df_path = os.path.join(recalibrated_data_dir, 'error_df.csv')
error_df = pd.read_csv(error_df_path) if os.path.exists(error_df_path) else pd.DataFrame(columns=cols)

active_folders = get_all_participants()
print(f"Starting execution. Total participants to process: {len(active_folders)}")

# ---------------------------------------------------------------------------
# Main Progress Bar (Outer Loop)
# ---------------------------------------------------------------------------
for participant in tqdm(active_folders, desc="Overall Progress", unit="participant"):

    # 0. Skip if the central error_df_csv already contains the entry for the current participant
    if participant in error_df['Name'].values:
        continue

    desktop_path = pathlib.Path(os.path.join(raw_data_dir, participant))
    if not desktop_path.exists():
        raise FileNotFoundError(f"The directory '{desktop_path}' does not exist.")

    all_eye_tracking_task_csvs = [f.name for f in desktop_path.iterdir() if f.is_file()]
    raw_data_files = []
    participant_calibration_csv = 'not_found'

    for file_name in all_eye_tracking_task_csvs:
        full_path = os.path.join(raw_data_dir, participant, file_name)
        if calibrate_with in file_name:
            participant_calibration_csv = full_path
        elif "csv" in file_name:
            raw_data_files.append(full_path)

    if participant_calibration_csv == 'not_found':
        print(f"\nCalibration Task not found for '{participant}', skipping.")
        continue

    # Instantiate base data metrics and linear calculation limits
    data_frame = clean_df(pd.read_csv(participant_calibration_csv), remove_static=True) # Calibration data has always positive PathIDX though the target was static
    shif_df, idx = shifted_df(data_frame)
    x_regr, y_regr = regression_models(shif_df)

    errors_for_task = {}
    all_task_paths = itertools.chain(raw_data_files, [participant_calibration_csv])

    # ---------------------------------------------------------------------------
    # Nested Progress Bar (Inner Loop)
    # ---------------------------------------------------------------------------
    for file_path in tqdm(all_task_paths, desc=f" └─ Files ({participant})", unit="file"):
        base_name = os.path.basename(file_path)
        task_prefix = base_name.split('_')[0]
        calibrated_task_csv_path = os.path.join(recalibrated_data_dir, f"{participant}_{task_prefix}_recal.csv")

        # 1. Check for each calibrated file one by one. 
        if not os.path.exists(calibrated_task_csv_path):
            generate_recalibrated_file(file_path, calibrated_task_csv_path, x_regr, y_regr, remove_static=(is_moving or 'cal' in file_path))

        # 2. Get error_for_task if the particular calibrated_task_csv file exists
        if os.path.exists(calibrated_task_csv_path):
            errors_for_task = compute_task_errors(calibrated_task_csv_path, errors_for_task, base_name)


    # 3. Add participant's entry to central error_df_csv once all the tasks have been analyzed and errors_for_task is complete
    error_df.loc[len(error_df.index)] = [
        participant,
        errors_for_task.get('w1_euc', np.nan), errors_for_task.get('w1_vec', np.nan), errors_for_task.get('w1_index', np.nan),
        errors_for_task.get('w2_euc', np.nan), errors_for_task.get('w2_vec', np.nan), errors_for_task.get('w2_index', np.nan),
        errors_for_task.get('w3_euc', np.nan), errors_for_task.get('w3_vec', np.nan), errors_for_task.get('w3_index', np.nan),
        errors_for_task.get('s4_euc', np.nan), errors_for_task.get('s4_vec', np.nan), errors_for_task.get('s4_index', np.nan),
        errors_for_task.get('b5_euc', np.nan), errors_for_task.get('b5_vec', np.nan), errors_for_task.get('b5_index', np.nan),
        errors_for_task.get('callibrate_euc', np.nan), errors_for_task.get('callibrate_vec', np.nan), errors_for_task.get('callibrate_index', np.nan),
        errors_for_task.get('callibrate_pearsonr', np.nan), errors_for_task.get('callibrate_pearsonr_recal', np.nan)
    ]
    error_df.to_csv(error_df_path, index=False)

print("\nScript execution completed successfully!")
