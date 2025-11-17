"""This module provides the graphical user interface used by the Mesoscope-VR data acquisition system to facilitate
data acquisition runtimes by allowing direct control over a subset of the system's runtime parameters and hardware.
"""

import sys
from enum import IntEnum
import contextlib
from multiprocessing import Process

import numpy as np
from PyQt6.QtGui import QFont, QCloseEvent
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QLabel,
    QWidget,
    QGroupBox,
    QHBoxLayout,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QApplication,
    QDoubleSpinBox,
)
from ataraxis_base_utilities import console
from ataraxis_data_structures import SharedMemoryArray


class _DataArrayIndex(IntEnum):
    """Defines the shared memory array indices for each runtime parameter and hardware component addressable from the
    user-facing GUI.
    """

    TERMINATION = 0
    EXIT_SIGNAL = 1
    REWARD_SIGNAL = 2
    SPEED_MODIFIER = 3
    DURATION_MODIFIER = 4
    PAUSE_STATE = 5
    OPEN_VALVE = 6
    CLOSE_VALVE = 7
    REWARD_VOLUME = 8
    GUIDANCE_ENABLED = 9
    SHOW_REWARD = 10


class RuntimeControlUI:
    """Provides the Graphical User Interface (GUI) that allows modifying certain Mesoscope-VR runtime parameters in real
    time.

    Notes:
        The UI runs in a parallel process and requires a single CPU core to support its runtime.

        Initializing the class does not start the UI process. Call the start() method before calling any other instance
        methods to start the UI process.

    Attributes:
        _data_array: The SharedMemoryArray instance used to bidirectionally transfer the data between the UI process
            and other runtime processes.
        _ui_process: The Process instance running the GUI cycle.
        _started: Tracks whether the UI process is running.
    """

    def __init__(self) -> None:
        # Defines the prototype array for the SharedMemoryArray initialization and sets the array elements to the
        # desired default state
        prototype = np.zeros(shape=11, dtype=np.uint32)
        prototype[_DataArrayIndex.PAUSE_STATE] = 1  # Ensures all runtimes start in a paused state
        prototype[_DataArrayIndex.GUIDANCE_ENABLED] = 0  # Initially disables guidance for all runtimes
        prototype[_DataArrayIndex.SHOW_REWARD] = 0  # Defaults to not showing reward collision boundary
        prototype[_DataArrayIndex.REWARD_VOLUME] = 5  # Preconfigures reward delivery to use 5 uL rewards

        # Initializes the SharedMemoryArray instance
        self._data_array = SharedMemoryArray.create_array(
            name="runtime_control_ui", prototype=prototype, exists_ok=True
        )

        # Defines but does not automatically start the UI process.
        self._ui_process = Process(target=self._run_ui_process, daemon=True)
        self._started = False

    def __del__(self) -> None:
        """Terminates the UI process and releases the instance's shared memory buffer when the instance is
        garbage-collected.
        """
        self.shutdown()

    def start(self) -> None:
        """Starts the remote UI process."""
        # If the instance is already started, aborts early
        if self._started:
            return

        # Starts the remote UI process.
        self._ui_process.start()

        # Connects to the shared memory array from the central runtime process and configures it to destroy the
        # shared memory buffer in case of an emergency (error) shutdown.
        self._data_array.connect()
        self._data_array.enable_buffer_destruction()

        # Marks the instance as started
        self._started = True

    def shutdown(self) -> None:
        """Shuts down the remote UI process and releases the instance's shared memory buffer."""
        # If the instance is already shut down, aborts early.
        if not self._started:
            return

        # Shuts down the remote UI process.
        if self._ui_process.is_alive():
            self._data_array[_DataArrayIndex.TERMINATION] = 1  # Sends the termination signal to the remote process
            self._ui_process.terminate()
            self._ui_process.join(timeout=2.0)

        # Terminates the shared memory array buffer.
        self._data_array.disconnect()
        self._data_array.destroy()

        # Marks the instance as shut down
        self._started = False

    def _run_ui_process(self) -> None:
        """Runs UI management cycle in a parallel process."""
        # Connects to the shared memory array from the remote process
        self._data_array.connect()

        # Creates and runs the Qt6 application in this process's main thread
        try:
            # Creates the GUI application
            app = QApplication(sys.argv)
            app.setApplicationName("Mesoscope-VR Control Panel")
            app.setOrganizationName("SunLab")

            # Sets Qt6 application-wide style
            app.setStyle("Fusion")

            # Creates the main application window
            window = _ControlUIWindow(self._data_array)
            window.show()

            # Runs the app
            app.exec()
        except Exception as e:
            message = (
                f"Unable to initialize the GUI application for the main runtime user interface. "
                f"Encountered the following error {e}."
            )
            console.error(message=message, error=RuntimeError)

        # Ensures proper UI shutdown when runtime encounters errors
        finally:
            self._data_array.disconnect()

    def set_pause_state(self, *, paused: bool) -> None:
        """Configures the GUI to reflect the current data acquisition session's runtime state.

        Args:
            paused: Determines whether the session is paused or running.
        """
        self._data_array[_DataArrayIndex.PAUSE_STATE] = 1 if paused else 0

    def set_guidance_state(self, *, enabled: bool) -> None:
        """Configures the GUI to reflect the data acquisition session's Virtual Reality task guidance state.

        Args:
            enabled: Determines whether the guidance mode is currently enabled.
        """
        self._data_array[_DataArrayIndex.GUIDANCE_ENABLED] = 1 if enabled else 0

    @property
    def exit_signal(self) -> bool:
        """Returns True if the user has requested the system to abort the data acquisition session's runtime."""
        exit_flag = bool(self._data_array[_DataArrayIndex.EXIT_SIGNAL])
        self._data_array[_DataArrayIndex.EXIT_SIGNAL] = 0
        return exit_flag

    @property
    def reward_signal(self) -> bool:
        """Returns True if the user has requested the system to deliver a water reward."""
        reward_flag = bool(self._data_array[_DataArrayIndex.REWARD_SIGNAL])
        self._data_array[_DataArrayIndex.REWARD_SIGNAL] = 0
        return reward_flag

    @property
    def speed_modifier(self) -> int:
        """Returns the current user-defined running speed threshold modifier."""
        return int(self._data_array[_DataArrayIndex.SPEED_MODIFIER])

    @property
    def duration_modifier(self) -> int:
        """Returns the current user-defined running epoch duration threshold modifier."""
        return int(self._data_array[_DataArrayIndex.DURATION_MODIFIER])

    @property
    def pause_runtime(self) -> bool:
        """Returns True if the user has requested the system to pause the data acquisition session's runtime."""
        return bool(self._data_array[_DataArrayIndex.PAUSE_STATE])

    @property
    def open_valve(self) -> bool:
        """Returns True if the user has requested the system to open the water delivery valve."""
        open_flag = bool(self._data_array[_DataArrayIndex.OPEN_VALVE])
        self._data_array[_DataArrayIndex.OPEN_VALVE] = 0
        return open_flag

    @property
    def close_valve(self) -> bool:
        """Returns True if the user has requested the system to close the water delivery valve."""
        close_flag = bool(self._data_array[_DataArrayIndex.CLOSE_VALVE])
        self._data_array[_DataArrayIndex.CLOSE_VALVE] = 0
        return close_flag

    @property
    def reward_volume(self) -> int:
        """Returns the current user-defined volume of water dispensed by the valve when delivering water rewards."""
        return int(self._data_array[_DataArrayIndex.REWARD_VOLUME])

    @property
    def enable_guidance(self) -> bool:
        """Returns True if the user has enabled the Virtual Reality task guidance mode."""
        return bool(self._data_array[_DataArrayIndex.GUIDANCE_ENABLED])

    @property
    def show_reward(self) -> bool:
        """Returns True if the user has enabled showing the Virtual Reality task guidance mode collision box to the
        animal.
        """
        return bool(self._data_array[_DataArrayIndex.SHOW_REWARD])


class _ControlUIWindow(QMainWindow):
    """Generates, renders, and maintains the Mesoscope-VR acquisition system's runtime GUI application window.

    Attributes:
        _data_array: The SharedMemoryArray instance used to bidirectionally transfer the data between the UI process
            and other runtime processes.
        _is_paused: Tracks whether the runtime is paused.
        _guidance_enabled: Tracks whether the Virtual Reality task guidance mode is enabled.
        _show_reward: Tracks whether the Virtual Reality guidance mode collision box is visible to the animal.
    """

    def __init__(self, data_array: SharedMemoryArray) -> None:
        super().__init__()  # Initializes the main window superclass

        # Defines internal attributes.
        self._data_array: SharedMemoryArray = data_array
        self._is_paused: bool = True
        self._guidance_enabled: bool = False
        self._show_reward: bool = False

        # Configures the window title
        self.setWindowTitle("Mesoscope-VR Control Panel")

        # Uses fixed size
        self.setFixedSize(450, 550)

        # Sets up the interactive UI
        self._setup_ui()
        self._setup_monitoring()

        # Applies Qt6-optimized styling and scaling parameters
        self._apply_qt6_styles()

    def _setup_ui(self) -> None:
        """Creates and arranges all UI elements."""
        # Initializes the main widget container
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Generates the central bounding box (the bounding box around all UI elements)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(15, 15, 15, 15)

        # Runtime Control Group
        runtime_control_group = QGroupBox("Runtime Control")
        runtime_control_layout = QVBoxLayout(runtime_control_group)
        runtime_control_layout.setSpacing(6)

        # Runtime termination (exit) button
        self.exit_btn = QPushButton("✖ Terminate Runtime")
        self.exit_btn.setToolTip("Gracefully ends the runtime and initiates the shutdown procedure.")
        # noinspection PyUnresolvedReferences
        self.exit_btn.clicked.connect(self._exit_runtime)
        self.exit_btn.setObjectName("exitButton")

        # Runtime Pause / Unpause (resume) button
        self.pause_btn = QPushButton("▶️ Resume Runtime")
        self.pause_btn.setToolTip("Pauses or resumes the runtime.")
        # noinspection PyUnresolvedReferences
        self.pause_btn.clicked.connect(self._toggle_pause)
        self.pause_btn.setObjectName("resumeButton")

        # Lick Guidance
        # Ensures the array is also set to the default value
        self.guidance_btn = QPushButton("🎯 Enable Guidance")
        self.guidance_btn.setToolTip("Toggles lick guidance mode on or off.")
        # noinspection PyUnresolvedReferences
        self.guidance_btn.clicked.connect(self._toggle_guidance)
        self.guidance_btn.setObjectName("guidanceButton")

        # Show / Hide Reward Collision Boundary
        self.reward_visibility_btn = QPushButton("👁️ Show Reward")
        self.reward_visibility_btn.setToolTip("Toggles reward collision boundary visibility on or off.")
        # noinspection PyUnresolvedReferences
        self.reward_visibility_btn.clicked.connect(self._toggle_reward_visibility)
        self.reward_visibility_btn.setObjectName("showRewardButton")

        # Configures the buttons to expand when the UI is resized, but use a fixed height of 35 points
        for btn in [self.exit_btn, self.pause_btn, self.guidance_btn, self.reward_visibility_btn]:
            btn.setMinimumHeight(35)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            runtime_control_layout.addWidget(btn)

        # Adds runtime status tracker to the same box
        self.runtime_status_label = QLabel("Runtime Status: ⏸️ Paused")
        self.runtime_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        runtime_status_font = QFont()
        runtime_status_font.setPointSize(35)
        runtime_status_font.setBold(True)
        self.runtime_status_label.setFont(runtime_status_font)
        self.runtime_status_label.setStyleSheet("QLabel { color: #f39c12; font-weight: bold; }")
        runtime_control_layout.addWidget(self.runtime_status_label)

        # Adds the runtime control box to the UI widget
        main_layout.addWidget(runtime_control_group)

        # Valve Control Group
        valve_group = QGroupBox("Valve Control")
        valve_layout = QVBoxLayout(valve_group)
        valve_layout.setSpacing(6)

        # Arranges valve control buttons in a horizontal layout
        valve_buttons_layout = QHBoxLayout()

        # Valve open
        self.valve_open_btn = QPushButton("🔓 Open")
        self.valve_open_btn.setToolTip("Opens the solenoid valve.")
        # noinspection PyUnresolvedReferences
        self.valve_open_btn.clicked.connect(self._open_valve)
        self.valve_open_btn.setObjectName("valveOpenButton")

        # Valve close
        self.valve_close_btn = QPushButton("🔒 Close")
        self.valve_close_btn.setToolTip("Closes the solenoid valve.")
        # noinspection PyUnresolvedReferences
        self.valve_close_btn.clicked.connect(self._close_valve)
        self.valve_close_btn.setObjectName("valveCloseButton")

        # Reward button
        self.reward_btn = QPushButton("● Reward")
        self.reward_btn.setToolTip("Delivers 5 uL of water through the solenoid valve.")
        # noinspection PyUnresolvedReferences
        self.reward_btn.clicked.connect(self._deliver_reward)
        self.reward_btn.setObjectName("rewardButton")

        # Configures the buttons to expand when the UI is resized, but use a fixed height of 35 points
        for btn in [self.valve_open_btn, self.valve_close_btn, self.reward_btn]:
            btn.setMinimumHeight(35)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            valve_buttons_layout.addWidget(btn)

        valve_layout.addLayout(valve_buttons_layout)

        # Valve status and volume control section - horizontal layout
        valve_status_layout = QHBoxLayout()
        valve_status_layout.setSpacing(6)

        # Volume control on the left
        volume_label = QLabel("Reward volume:")
        volume_label.setObjectName("volumeLabel")

        self.volume_spinbox = QDoubleSpinBox()
        self.volume_spinbox.setRange(1, 20)  # Ranges from 1 to 20
        self.volume_spinbox.setValue(5)  # Default value
        self.volume_spinbox.setDecimals(0)  # Integer precision
        self.volume_spinbox.setSuffix(" μL")  # Adds units suffix
        self.volume_spinbox.setToolTip("Sets water reward volume. Accepts values between 1 and 2 μL.")
        self.volume_spinbox.setMinimumHeight(30)
        # noinspection PyUnresolvedReferences
        self.volume_spinbox.valueChanged.connect(self._update_reward_volume)

        # Adds volume controls to the left side
        valve_status_layout.addWidget(volume_label)
        valve_status_layout.addWidget(self.volume_spinbox)

        # Adds the valve status tracker on the right
        self.valve_status_label = QLabel("Valve: 🔒 Closed")
        self.valve_status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        valve_status_font = QFont()
        valve_status_font.setPointSize(35)
        valve_status_font.setBold(True)
        self.valve_status_label.setFont(valve_status_font)
        self.valve_status_label.setStyleSheet("QLabel { color: #e67e22; font-weight: bold; }")
        valve_status_layout.addWidget(self.valve_status_label)

        # Add the horizontal status layout to the main valve layout
        valve_layout.addLayout(valve_status_layout)

        # Adds the valve control box to the UI widget
        main_layout.addWidget(valve_group)

        # Adds Run Training controls in a horizontal layout
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(6)

        # Running Speed Threshold Control Group
        speed_group = QGroupBox("Speed Threshold")
        speed_layout = QVBoxLayout(speed_group)

        # Speed Modifier
        speed_status_label = QLabel("Current Modifier:")
        speed_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        speed_status_label.setStyleSheet("QLabel { font-weight: bold; color: #34495e; }")
        speed_layout.addWidget(speed_status_label)
        self.speed_spinbox = QDoubleSpinBox()
        self.speed_spinbox.setRange(-1000, 1000)  # Factoring in the step of 0.01, this allows -20 to +20 cm/s
        self.speed_spinbox.setValue(0)  # Default value
        self.speed_spinbox.setDecimals(0)  # Integer precision
        self.speed_spinbox.setToolTip("Sets the running speed threshold modifier value.")
        self.speed_spinbox.setMinimumHeight(30)
        # noinspection PyUnresolvedReferences
        self.speed_spinbox.valueChanged.connect(self._update_speed_modifier)
        speed_layout.addWidget(self.speed_spinbox)

        # Running Duration Threshold Control Group
        duration_group = QGroupBox("Duration Threshold")
        duration_layout = QVBoxLayout(duration_group)

        # Duration modifier
        duration_status_label = QLabel("Current Modifier:")
        duration_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        duration_status_label.setStyleSheet("QLabel { font-weight: bold; color: #34495e; }")
        duration_layout.addWidget(duration_status_label)
        self.duration_spinbox = QDoubleSpinBox()
        self.duration_spinbox.setRange(-1000, 1000)  # Factoring in the step of 0.01, this allows -20 to +20 s
        self.duration_spinbox.setValue(0)  # Default value
        self.duration_spinbox.setDecimals(0)  # Integer precision
        self.duration_spinbox.setToolTip("Sets the running duration threshold modifier value.")
        # noinspection PyUnresolvedReferences
        self.duration_spinbox.valueChanged.connect(self._update_duration_modifier)
        duration_layout.addWidget(self.duration_spinbox)

        # Adds speed and duration threshold modifiers to the main UI widget
        controls_layout.addWidget(speed_group)
        controls_layout.addWidget(duration_group)
        main_layout.addLayout(controls_layout)

    def _apply_qt6_styles(self) -> None:
        """Applies optimized styling to all UI elements managed by this instance."""
        self.setStyleSheet("""
                    QMainWindow {
                        background-color: #ecf0f1;
                    }

                    QGroupBox {
                        font-weight: bold;
                        font-size: 14pt;
                        border: 2px solid #bdc3c7;
                        border-radius: 8px;
                        margin: 25px 6px 6px 6px;
                        padding-top: 10px;
                        background-color: #ffffff;
                    }

                    QGroupBox::title {
                        subcontrol-origin: margin;
                        subcontrol-position: top center;
                        left: 0px;
                        right: 0px;
                        padding: 0 8px 0 8px;
                        color: #2c3e50;
                        background-color: transparent;
                        border: none;
                    }

                    QPushButton {
                        background-color: #ffffff;
                        border: 2px solid #bdc3c7;
                        border-radius: 6px;
                        padding: 6px 8px;
                        font-size: 12pt;
                        font-weight: 500;
                        color: #2c3e50;
                        min-height: 20px;
                    }

                    QPushButton:hover {
                        background-color: #f8f9fa;
                        border-color: #3498db;
                        color: #2980b9;
                    }

                    QPushButton:pressed {
                        background-color: #e9ecef;
                        border-color: #2980b9;
                    }

                    QPushButton#exitButton {
                        background-color: #e74c3c;
                        color: white;
                        border-color: #c0392b;
                        font-weight: bold;
                    }

                    QPushButton#exitButton:hover {
                        background-color: #c0392b;
                        border-color: #a93226;
                    }

                    QPushButton#pauseButton {
                        background-color: #f39c12;
                        color: white;
                        border-color: #e67e22;
                        font-weight: bold;
                    }

                    QPushButton#pauseButton:hover {
                        background-color: #e67e22;
                        border-color: #d35400;
                    }

                    QPushButton#resumeButton {
                        background-color: #27ae60;
                        color: white;
                        border-color: #229954;
                        font-weight: bold;
                    }

                    QPushButton#resumeButton:hover {
                        background-color: #229954;
                        border-color: #1e8449;
                    }

                    QPushButton#valveOpenButton {
                        background-color: #27ae60;
                        color: white;
                        border-color: #229954;
                        font-weight: bold;
                    }

                    QPushButton#valveOpenButton:hover {
                        background-color: #229954;
                        border-color: #1e8449;
                    }

                    QPushButton#valveCloseButton {
                        background-color: #e67e22;
                        color: white;
                        border-color: #d35400;
                        font-weight: bold;
                    }

                    QPushButton#valveCloseButton:hover {
                        background-color: #d35400;
                        border-color: #ba4a00;
                    }

                    QPushButton#rewardButton {
                        background-color: #3498db;
                        color: white;
                        border-color: #2980b9;
                        font-weight: bold;
                    }

                    QPushButton#rewardButton:hover {
                        background-color: #2980b9;
                        border-color: #21618c;
                    }

                    QLabel {
                        color: #2c3e50;
                        font-size: 12pt;
                    }

                    QLabel#volumeLabel {
                        color: #2c3e50;
                        font-size: 12pt;
                        font-weight: bold;
                    }

                    QDoubleSpinBox {
                        border: 2px solid #bdc3c7;
                        border-radius: 4px;
                        padding: 4px 8px;
                        font-weight: bold;
                        font-size: 12pt;
                        background-color: white;
                        color: #2c3e50;
                        min-height: 20px;
                    }

                    QDoubleSpinBox:focus {
                        border-color: #3498db;
                    }

                    QDoubleSpinBox::up-button {
                        subcontrol-origin: border;
                        subcontrol-position: top right;
                        width: 20px;
                        background-color: #f8f9fa;
                        border: 1px solid #bdc3c7;
                        border-top-right-radius: 4px;
                        border-bottom: none;
                    }

                    QDoubleSpinBox::up-button:hover {
                        background-color: #e9ecef;
                        border-color: #3498db;
                    }

                    QDoubleSpinBox::up-button:pressed {
                        background-color: #dee2e6;
                    }

                    QDoubleSpinBox::up-arrow {
                        image: none;
                        border-left: 4px solid transparent;
                        border-right: 4px solid transparent;
                        border-bottom: 6px solid #2c3e50;
                        width: 0px;
                        height: 0px;
                    }

                    QDoubleSpinBox::down-button {
                        subcontrol-origin: border;
                        subcontrol-position: bottom right;
                        width: 20px;
                        background-color: #f8f9fa;
                        border: 1px solid #bdc3c7;
                        border-bottom-right-radius: 4px;
                        border-top: none;
                    }

                    QDoubleSpinBox::down-button:hover {
                        background-color: #e9ecef;
                        border-color: #3498db;
                    }

                    QDoubleSpinBox::down-button:pressed {
                        background-color: #dee2e6;
                    }

                    QDoubleSpinBox::down-arrow {
                        image: none;
                        border-left: 4px solid transparent;
                        border-right: 4px solid transparent;
                        border-top: 6px solid #2c3e50;
                        width: 0px;
                        height: 0px;
                    }

                    QSlider::groove:horizontal {
                        border: 1px solid #bdc3c7;
                        height: 8px;
                        background: #ecf0f1;
                        margin: 2px 0;
                        border-radius: 4px;
                    }

                    QSlider::handle:horizontal {
                        background: #3498db;
                        border: 2px solid #2980b9;
                        width: 20px;
                        margin: -6px 0;
                        border-radius: 10px;
                    }

                    QSlider::handle:horizontal:hover {
                        background: #2980b9;
                        border-color: #21618c;
                    }

                    QSlider::handle:horizontal:pressed {
                        background: #21618c;
                    }

                    QSlider::sub-page:horizontal {
                        background: #3498db;
                        border: 1px solid #2980b9;
                        height: 8px;
                        border-radius: 4px;
                    }

                    QSlider::add-page:horizontal {
                        background: #ecf0f1;
                        border: 1px solid #bdc3c7;
                        height: 8px;
                        border-radius: 4px;
                    }

                    QSlider::groove:vertical {
                        border: 1px solid #bdc3c7;
                        width: 8px;
                        background: #ecf0f1;
                        margin: 0 2px;
                        border-radius: 4px;
                    }

                    QSlider::handle:vertical {
                        background: #3498db;
                        border: 2px solid #2980b9;
                        height: 20px;
                        margin: 0 -6px;
                        border-radius: 10px;
                    }

                    QSlider::handle:vertical:hover {
                        background: #2980b9;
                        border-color: #21618c;
                    }

                    QSlider::handle:vertical:pressed {
                        background: #21618c;
                    }

                    QSlider::sub-page:vertical {
                        background: #ecf0f1;
                        border: 1px solid #bdc3c7;
                        width: 8px;
                        border-radius: 4px;
                    }

                    QSlider::add-page:vertical {
                        background: #3498db;
                        border: 1px solid #2980b9;
                        width: 8px;
                        border-radius: 4px;
                    }

                    QPushButton#guidanceButton {
                    background-color: #9b59b6;
                    color: white;
                    border-color: #8e44ad;
                    font-weight: bold;
                    }

                    QPushButton#guidanceButton:hover {
                        background-color: #8e44ad;
                        border-color: #7d3c98;
                    }

                    QPushButton#guidanceDisableButton {
                        background-color: #95a5a6;
                        color: white;
                        border-color: #7f8c8d;
                        font-weight: bold;
                    }

                    QPushButton#guidanceDisableButton:hover {
                        background-color: #7f8c8d;
                        border-color: #6c7b7d;
                    }
                    QPushButton#hideRewardButton {
                        background-color: #e74c3c;
                        color: white;
                        border-color: #c0392b;
                        font-weight: bold;
                    }

                    QPushButton#hideRewardButton:hover {
                        background-color: #c0392b;
                        border-color: #a93226;
                    }

                    QPushButton#showRewardButton {
                        background-color: #27ae60;
                        color: white;
                        border-color: #229954;
                        font-weight: bold;
                    }

                    QPushButton#showRewardButton:hover {
                        background-color: #229954;
                        border-color: #1e8449;
                    }
                """)

    def _setup_monitoring(self) -> None:
        """Sets up a QTimer to monitor the runtime termination status."""
        self.monitor_timer = QTimer(self)
        # noinspection PyUnresolvedReferences
        self.monitor_timer.timeout.connect(self._check_external_state)
        self.monitor_timer.start(100)  # Checks every 100 ms

    def _check_external_state(self) -> None:
        """Checks the state of externally addressable UI elements and updates the managed GUI to reflect the
        externally driven changes.
        """
        # noinspection PyBroadException
        try:
            # If the termination flag has been set to 1, terminates the GUI process
            if self._data_array[_DataArrayIndex.TERMINATION] == 1:
                self.close()

            # Checks for external pause state changes and, if necessary, updates the GUI to reflect the current
            # runtime state (running or paused).
            external_pause_state = bool(self._data_array[_DataArrayIndex.PAUSE_STATE])
            if external_pause_state != self._is_paused:
                # External pause state changed, update UI accordingly
                self._is_paused = external_pause_state
                self._update_pause_ui()

            # Checks for external guidance state changes and, if necessary, updates the GUI to reflect the current
            # guidance state (enabled or disabled).
            external_guidance_state = bool(self._data_array[_DataArrayIndex.GUIDANCE_ENABLED])
            if external_guidance_state != self._guidance_enabled:
                # External guidance state changed, update UI accordingly
                self._guidance_enabled = external_guidance_state
                self._update_guidance_ui()
        except Exception:
            self.close()

    def closeEvent(self, event: QCloseEvent | None) -> None:  # noqa: N802
        """Handles GUI window close events.

        Args:
            event: The Qt-generated window shutdown event instance.
        """
        # Sends a runtime termination signal via the SharedMemoryArray before accepting the close event.
        # noinspection PyBroadException
        with contextlib.suppress(Exception):
            self._data_array[_DataArrayIndex.TERMINATION] = 1
        if event is not None:
            event.accept()

    def _exit_runtime(self) -> None:
        """Instructs the system to terminate the runtime."""
        previous_status = self.runtime_status_label.text()
        style = self.runtime_status_label.styleSheet()
        self._data_array[_DataArrayIndex.EXIT_SIGNAL] = 1
        self.runtime_status_label.setText("✖ Exit signal sent")
        self.runtime_status_label.setStyleSheet("QLabel { color: #e74c3c; font-weight: bold; }")
        self.exit_btn.setText("✖ Exit Requested")
        self.exit_btn.setEnabled(False)

        # Resets the button after 2 seconds
        QTimer.singleShot(2000, lambda: self.exit_btn.setText("✖ Terminate Runtime"))
        QTimer.singleShot(2000, lambda: self.exit_btn.setStyleSheet("QLabel { color: #c0392b; font-weight: bold; }"))
        QTimer.singleShot(2000, lambda: self.exit_btn.setEnabled(True))

        # Restores the status back to the previous state
        QTimer.singleShot(2000, lambda: self.runtime_status_label.setText(previous_status))
        QTimer.singleShot(2000, lambda: self.runtime_status_label.setStyleSheet(style))

    def _deliver_reward(self) -> None:
        """Instructs the system to deliver a water reward to the animal."""
        # Sends the reward command via the SharedMemoryArray and temporarily sets the statsu to indicate that the
        # reward is sent.
        self._data_array[_DataArrayIndex.REWARD_SIGNAL] = 1
        self.valve_status_label.setText("Reward: 🟢 Sent")
        self.valve_status_label.setStyleSheet("QLabel { color: #3498db; font-weight: bold; }")

        # Resets the status to 'closed' after 1 second using the Qt6 single shot timer. This is realistically the
        # longest time the system would take to start and finish delivering the reward
        QTimer.singleShot(2000, lambda: self.valve_status_label.setText("Valve: 🔒 Closed"))
        QTimer.singleShot(
            2000, lambda: self.valve_status_label.setStyleSheet("QLabel { color: #e67e22; font-weight: bold; }")
        )

    def _open_valve(self) -> None:
        """Instructs the system to open the water delivery valve."""
        self._data_array[_DataArrayIndex.OPEN_VALVE] = 1
        self.valve_status_label.setText("Valve: 🔓 Opened")
        self.valve_status_label.setStyleSheet("QLabel { color: #27ae60; font-weight: bold; }")

    def _close_valve(self) -> None:
        """Instructs the system to close the water delivery valve."""
        self._data_array[_DataArrayIndex.CLOSE_VALVE] = 1
        self.valve_status_label.setText("Valve: 🔒 Closed")
        self.valve_status_label.setStyleSheet("QLabel { color: #e67e22; font-weight: bold; }")

    def _toggle_pause(self) -> None:
        """Instructs the system to pause or resume the data acquisition session's runtime."""
        self._is_paused = not self._is_paused
        self._data_array[_DataArrayIndex.PAUSE_STATE] = 1 if self._is_paused else 0
        self._update_pause_ui()

    def _update_reward_volume(self) -> None:
        """Updates the volume used by the system when delivering water rewards to match the current GUI
        configuration.
        """
        self._data_array[_DataArrayIndex.REWARD_VOLUME] = int(self.volume_spinbox.value())

    def _update_speed_modifier(self) -> None:
        """Updates the running speed threshold modifier to match the current GUI configuration."""
        self._data_array[_DataArrayIndex.SPEED_MODIFIER] = int(self.speed_spinbox.value())

    def _update_duration_modifier(self) -> None:
        """Updates the running epoch duration modifier to match the current GUI configuration."""
        self._data_array[_DataArrayIndex.DURATION_MODIFIER] = int(self.duration_spinbox.value())

    @staticmethod
    def _refresh_button_style(button: QPushButton) -> None:
        """Refreshes button styles after object name change."""
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()

    def _update_guidance_ui(self) -> None:
        """Updates the GUI to reflect the current Virtual Reality task guidance state."""
        if self._guidance_enabled:
            self.guidance_btn.setText("🚫 Disable Guidance")
            self.guidance_btn.setObjectName("guidanceDisableButton")
        else:
            self.guidance_btn.setText("🎯 Enable Guidance")
            self.guidance_btn.setObjectName("guidanceButton")

        # Refreshes styles after object name change
        self._refresh_button_style(button=self.guidance_btn)

    def _toggle_guidance(self) -> None:
        """Instructs the system to enable or disable the Virtual Reality task guidance mode."""
        self._guidance_enabled = not self._guidance_enabled
        self._data_array[_DataArrayIndex.GUIDANCE_ENABLED] = 1 if self._guidance_enabled else 0
        self._update_guidance_ui()

    def _update_pause_ui(self) -> None:
        """Updates the GUI to reflect the current data acquisition runtime pause state."""
        if self._is_paused:
            self.pause_btn.setText("▶️ Resume Runtime")
            self.pause_btn.setObjectName("resumeButton")
            self.runtime_status_label.setText("Runtime Status: ⏸️ Paused")
            self.runtime_status_label.setStyleSheet("QLabel { color: #f39c12; font-weight: bold; }")
        else:
            self.pause_btn.setText("⏸️ Pause Runtime")
            self.pause_btn.setObjectName("pauseButton")
            self.runtime_status_label.setText("Runtime Status: 🟢 Running")
            self.runtime_status_label.setStyleSheet("QLabel { color: #27ae60; font-weight: bold; }")

        # Refresh styles after object name change
        self._refresh_button_style(button=self.pause_btn)

    def _toggle_reward_visibility(self) -> None:
        """Instructs the system to show or hide the Virtual Reality guidance mode collision box."""
        self._show_reward = not self._show_reward
        if self._show_reward:
            self._data_array[_DataArrayIndex.SHOW_REWARD] = 1
            self.reward_visibility_btn.setText("🙈 Hide Reward")
            self.reward_visibility_btn.setObjectName("hideRewardButton")
        else:
            self._data_array[_DataArrayIndex.SHOW_REWARD] = 0
            self.reward_visibility_btn.setText("👁️ Show Reward")
            self.reward_visibility_btn.setObjectName("showRewardButton")

        # Refreshes styles after object name change
        self._refresh_button_style(button=self.reward_visibility_btn)
