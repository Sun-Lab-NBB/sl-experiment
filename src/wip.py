from pathlib import Path

import numpy as np
import polars as pl
from ataraxis_base_utilities import console

from sl_experiment.data_processing import _pull_mesoscope_data, _preprocess_mesoscope_directory, _resolve_ubiquitin_markers

if __name__ == "__main__":
    console.enable()
    rdd = Path("/media/Data/vrpc/test/1/2022_01_25/raw_data")
    mrd = Path("/media/Data/scaniamgepc")
    _pull_mesoscope_data(raw_data_directory=rdd, mesoscope_root_directory=mrd, num_threads=120, remove_sources=True)
    _preprocess_mesoscope_directory(raw_data_directory=rdd, num_processes=67, batch_size=1)
    _resolve_ubiquitin_markers(mesoscope_root_path=mrd)

# root = Path("/media/Data/Experiments/Template/666/2025-03-18-18-52-54-948030/raw_data/behavior_data")
# x = root.joinpath("break_data.feather")
# y = pl.read_ipc(x, use_pyarrow=True)
# print(y)
#
import sys

# # Load data
# distance = Path("/media/Data/Experiments/TestMice/666/2025-03-10-16-15-25-577230/raw_data/behavior_data/encoder_data.feather")
# reward = Path("/media/Data/Experiments/TestMice/666/2025-03-10-16-15-25-577230/raw_data/behavior_data/valve_data.feather")
# distance_data = pl.read_ipc(source=distance, use_pyarrow=True)
# reward_data = pl.read_ipc(source=reward, use_pyarrow=True)
#
# # Extract relevant columns
# time_d = distance_data["time_us"]
# distance_cm = distance_data["traveled_distance_cm"]
# time_r = reward_data["time_us"]
# tone_r = reward_data["dispensed_water_volume_uL"]
#
# # Identify indices where the delivered volume increases
# volume_changes = np.where(np.diff(tone_r) > 0)[0] + 1
# tone_times = time_r[volume_changes]
#
# def f(distance_cm):
#     return (distance_cm / 10.0) % 24
#
# # Interpolate reward distances
# reward_distances = _interpolate_data(time_d, distance_cm, tone_times, is_discrete=False)
# for num, distance in enumerate(reward_distances):
#     reward_distances[num] = f(distance)
#
# print(reward_distances)
# print(distance_cm[-1]/240)
