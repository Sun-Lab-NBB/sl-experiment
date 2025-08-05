 .. This file provides the instructions for how to display the API documentation generated using sphinx autodoc
   extension. Use it to declare Python documentation sub-directories via appropriate modules (autodoc, etc.).

Command Line Interfaces
=======================

.. automodule:: sl_experiment.cli
   :members:
   :undoc-members:
   :show-inheritance:

.. click:: sl_experiment.cli:calculate_crc
   :prog: sl-crc
   :nested: full

.. click:: sl_experiment.cli:list_devices
   :prog: sl-devices
   :nested: full

.. click:: sl_experiment.cli:generate_system_configuration_file
   :prog: sl-create-system-config
   :nested: full

.. click:: sl_experiment.cli:generate_project_data_structure
   :prog: sl-create-project
   :nested: full

.. click:: sl_experiment.cli:generate_experiment_configuration_file
   :prog: sl-create-experiment
   :nested: full

.. click:: sl_experiment.cli:maintain_acquisition_system
   :prog: sl-maintain
   :nested: full

.. click:: sl_experiment.cli:lick_training
   :prog: sl-lick-train
   :nested: full

.. click:: sl_experiment.cli:run_training
   :prog: sl-run-train
   :nested: full

.. click:: sl_experiment.cli:run_experiment
   :prog: sl-experiment
   :nested: full

.. click:: sl_experiment.cli:check_window
   :prog: sl-check-window
   :nested: full

.. click:: sl_experiment.cli:preprocess_session
   :prog: sl-preprocess
   :nested: full

.. click:: sl_experiment.cli:purge_data
   :prog: sl-purge
   :nested: full

.. click:: sl_experiment.cli:delete_session
   :prog: sl-delete-session-data
   :nested: full

.. click:: sl_experiment.cli:list_projects
   :prog: sl-projects
   :nested: full

Mesoscope-VR Acquisition System
===============================
.. automodule:: sl_experiment.mesoscope_vr
   :members:
   :undoc-members:
   :show-inheritance:

Shared Acquisition Tools And Assets
===================================
.. automodule:: sl_experiment.shared_components
   :members:
   :undoc-members:
   :show-inheritance:
