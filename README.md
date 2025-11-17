# sl-experiment

A Python library that provides tools to acquire, manage, and preprocess scientific data in the Sun (NeuroAI) lab.

![PyPI - Version](https://img.shields.io/pypi/v/sl-experiment)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/sl-experiment)
[![uv](https://tinyurl.com/uvbadge)](https://github.com/astral-sh/uv)
[![Ruff](https://tinyurl.com/ruffbadge)](https://github.com/astral-sh/ruff)
![type-checked: mypy](https://img.shields.io/badge/type--checked-mypy-blue?style=flat-square&logo=python)
![PyPI - License](https://img.shields.io/pypi/l/sl-experiment)
![PyPI - Status](https://img.shields.io/pypi/status/sl-experiment)
![PyPI - Wheel](https://img.shields.io/pypi/wheel/sl-experiment)

___

## Detailed Description

This library functions as the central hub for collecting and preprocessing the data for all current and future projects 
in the Sun lab. To do so, it exposes the API to interface with all data acquisition systems in the lab. Primarily, this 
relies on specializing various general-purpose libraries released as part of the 'Ataraxis' science-automation project
to work within the specific hardware implementations available in the lab.

This library is explicitly designed to work with the specific hardware and data handling strategies used in the Sun lab 
and will likely not work in other contexts without extensive modification. The library broadly consists of two 
parts: the shared assets and the acquisition-system-specific bindings. The shared assets are reused by all acquisition 
systems and are mostly inherited from the [sl-shared-assets](https://github.com/Sun-Lab-NBB/sl-shared-assets) library. 
The acquisition-system-specific code is tightly integrated with the hardware used in the lab and is generally not 
designed to be reused in any other context. See the [data acquisition systems](#data-acquisition-systems) section for 
more details on currently supported acquisition systems.

Note, the rest of this ReadMe assumes familiarity with the procedures, experiments, and tools used in the Sun lab
to acquire scientific data. See our [publications](https://neuroai.github.io/sunlab/publications) before reading 
further, if you are not familiar with the work done in the lab.

___

## Table of Contents
- [Installation](#installation)
- [Data Acquisition Systems](#data-acquisition-systems)
- [Mesoscope-VR System](#Mesoscope-vr-data-acquisition-system)
- [Acquired Data Structure and Management](#acquired-data-structure-and-management)
- [Acquiring Data in the Sun Lab](#acquiring-data-in-the-sun-lab)
- [API Documentation](#api-documentation)
- [Recovering from Interruptions](#recovering-from-interruptions)
- [Versioning](#versioning)
- [Authors](#authors)
- [License](#license)
- [Acknowledgements](#Acknowledgments)

---

## Installation

### Source

Note, installation from source is ***highly discouraged*** for anyone who is not an active project developer.

1. Download this repository to your local machine using your preferred method, such as Git-cloning. Use one
   of the stable releases from [GitHub](https://github.com/Sun-Lab-NBB/sl-experiment/releases).
2. Unpack the downloaded zip and note the path to the binary wheel (`.whl`) file contained in the archive.
3. Run ```python -m pip install WHEEL_PATH```, replacing 'WHEEL_PATH' with the path to the wheel file, to install the 
   wheel into the active python environment.

### pip
Use the following command to install the library using pip: ```pip install sl-experiment```.

___

## Data Acquisition Systems

A data acquisition (and runtime control) system can be broadly defined as a collection of hardware and software tools 
used to conduct training or experiment sessions that acquire scientific data. Each data acquisition system can use one 
or more machines (PCs) to acquire the data, with this library (sl-experiment) typically running on the **main** data 
acquisition machine. Additionally, each system typically uses a Network Attached Storage (NAS), a remote storage server,
or both to store the data after the acquisition safely (with redundancy and parity).

In the Sun lab, each data acquisition system is built around the main tool used to acquire the brain activity data. For
example, the main system in the Sun lab is the [Mesoscope-VR](#Mesoscope-vr-data-acquisition-system) system, which uses 
the [2-Photon Random Access Mesoscope (2P-RAM)](https://elifesciences.org/articles/14472). All other components of that 
system are built around the Mesoscope to facilitate the acquisition of the brain activity data. Due to this inherent 
specialization, each data acquisition system in the lab is treated as an independent unit that requires custom software
to acquire, preprocess, and process the resultant data.

***Note!*** Since each data acquisition system is unique, the section below will be iteratively expanded to include 
system-specific assembly instructions for **each supported acquisition system**. Commonly, updates to this section 
coincide with major or minor library version updates.

---

## Mesoscope-VR Data Acquisition System

This is the main data acquisition system currently used in the Sun lab. The system broadly consists of four major 
parts: 
1. The [2-Photon Random Access Mesoscope (2P-RAM)](https://elifesciences.org/articles/14472), assembled by 
   [Thor Labs](https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=10646) and controlled by 
   [ScanImage](https://www.mbfbioscience.com/products/scanimage/) software. The Mesoscope control and data acquisition 
   are performed by a dedicated computer referred to as the **'ScanImagePC'** or, (less frequently) the
   **'Mesoscope PC'**. This PC is assembled and configured by the [MBF Bioscience](https://www.mbfbioscience.com/). The
   only modification carried out by the Sun lab during assembly was the configuration of a Server Message Block (SMB)
   protocol access to the root folder used by the ScanImage software to save the Mesoscope data.
2. The [Unity game engine](https://unity.com/products/unity-engine) running the Virtual Reality game world used in all 
   experiments to control the task environment and resolve the task logic. The virtual environment runs on the main data
   acquisition computer referred to as the **'VRPC'** and relies on the [MQTT](https://mqtt.org/) communication protocol
   and the [Sun lab implementation of the GIMBL package](https://github.com/Sun-Lab-NBB/Unity-tasks) to bidirectionally 
   interface with the virtual task environment.
3. The [microcontroller-powered hardware](https://github.com/Sun-Lab-NBB/sl-micro-controllers) that allows the animal 
   to bidirectionally interface with various physical components (modules) of the Mesoscope-VR systems.
4. A set of visual and IR-range cameras, used to acquire behavior video data.

### Main Dependency
- ***Linux*** operating system. While the library *may* also work on Windows and (less likely) macOS, it has been 
  explicitly written for and tested on the mainline [6.11 kernel](https://kernelnewbies.org/Linux_6.11) and 
  Ubuntu 24.10 distribution of the GNU Linux operating system using [Wayland](https://wayland.freedesktop.org/) window
  system architecture.

### Software Dependencies
***Note!*** This list only includes *external dependencies*, which are installed *in addition* to all 
dependencies automatically installed from pip / conda as part of library installation. The dependencies below have to
be installed and configured on the **VRPC** before calling runtime commands via the command line interface (CLI) exposed
by this library.

- [MQTT broker](https://mosquitto.org/) version **2.0.21**. The broker should be running locally and can use 
  the **default** IP (27.0.0.1) and Port (1883) configuration.
- [FFMPEG](https://www.ffmpeg.org/download.html). As a minimum, the version of FFMPEG should support H265 and H264 
  codecs with hardware acceleration (Nvidia GPU). This library was tested with the version **7.1.1-1ubuntu1.1**.
- [MvImpactAcquire](https://assets-2.balluff.com/mvIMPACT_Acquire/). This library is tested with version **2.9.2**, 
  which is freely distributed. Higher GenTL producer versions will likely work too, but they require purchasing a 
  license.
- [Zaber Launcher](https://software.zaber.com/zaber-launcher/download) version **2025.6.2-1**.
- [Unity Game Engine](https://unity.com/products/unity-engine) version **6000.1.12f1**.

### Hardware Dependencies

**Note!** These dependencies only apply to the **VRPC**. Hardware dependencies for the **ScanImagePC** are determined 
and controlled by MBF and ThorLabs. This library benefits from the **ScanImagePC** being outfitted with a 10-GB network 
card, but this is not a strict requirement. 

- [Nvidia GPU](https://www.nvidia.com/en-us/). This library uses GPU hardware acceleration to encode acquired video 
  data. Any Nvidia GPU with hardware encoding chip(s) should work as expected. The library was tested with **RTX 4090**.
- A CPU with at least 12, preferably 16, physical cores. This library has been tested with 
  [AMD Ryzen 7950X CPU](https://www.amd.com/en/products/processors/desktops/ryzen/7000-series/amd-ryzen-9-7950x.html). 
  It is recommended to use CPUs with 'full' cores, instead of the modern Intel’s design of 'e' and 'p' cores 
  for predictable performance of all library components.
- A 10-Gigabit capable motherboard or Ethernet adapter, such as [X550-T2](https://shorturl.at/fLLe9). Primarily, this is
  required for the high-quality machine vision camera used to record videos of the animal’s face. The 10-Gigabit lines
  are also used for transferring the data between the PCs used in the data acquisition process and destination machines 
  used for long-term data storage (see [acquired data management section](#acquired-data-structure-and-management) for 
  more details).

### System Assembly

The Mesoscope-VR system consists of multiple interdependent components. We are constantly making minor changes to the 
system to optimize its performance and facilitate novel experiments and projects carried out in the lab. Treat this 
section as a general system composition guide, but consult lab publications over this section for instructions on 
building specific system implementations used to acquire the data featured in different publications.

Physical assembly and mounting of ***all*** hardware components mentioned in the specific subsections below is discussed
in the [main Mesoscope-VR assembly section](#Mesoscope-vr-assembly).

### Zaber Motors
All brain activity recordings with the Mesoscope require the animal to be head-fixed. To orient head-fixed animals on 
the Virtual Reality treadmill (running wheel) and promote task performance, the system uses three groups of motors 
controlled through Zaber motor controllers. The first group, the **HeadBar**, is used to position the animal’s head in 
Z, Pitch, and Roll axes. Together with the movement axes of the Mesoscope, this allows for a wide range of 
motions necessary to align the Mesoscope objective with the brain imaging plane. The second group of 
motors, the **LickPort**, controls the position of the water delivery port (tube) (and sensor) in X, Y, and Z axes. This
is used to ensure all animals have comfortable access to the water delivery tube, regardless of their head position.
The third group of motors, the **Wheel**, controls the position of the running wheel in the X-axis relative to the 
head-fixed animal’s body and is used to position the animal on the running wheel to promote good running behavior.

The current snapshot of Zaber motor configurations used in the lab, alongside the motor parts list and electrical wiring
instructions is available 
[here](https://drive.google.com/drive/folders/1SL75KE3S2vuR9TTkxe6N4wvrYdK-Zmxn?usp=drive_link).

**Warning!** Zaber motors have to be configured correctly to work with this library. To (re)configure the motors to work
with the library, apply the setting snapshots from the link above via the 
[Zaber Launcher](https://software.zaber.com/zaber-launcher/download) software. Make sure you read the instructions in 
the 'Applying Zaber Configuration' document for the correct application procedure.

**Although this is highly discouraged, you can also edit the motor settings manually**. To configure the motors
to work with this library, you need to overwrite the non-volatile User Data of each motor device (controller) with
the data expected by this library:
1. **User Data 0**: Device CRC Code. This variable should store the CRC32-XFER checksum of the device’s name 
   (user-defined name). During runtime, the library generates the CRC32-XFER checksum of each device’s name and compares
   it against the value stored inside the User Data 0 variable to ensure that each device is configured appropriately to
   work with the sl-experiment library. **Hint!** Use the `sl-crc` console command to generate the CRC32-XFER checksum 
   for each device during manual configuration, as it uses the same code as used during runtime and, therefore, 
   guarantees that the checksums will match.
2. **User Data 1**: Device ShutDown Flag. This variable is used as a secondary safety measure to ensure each device has 
   been properly shut down during previous runtimes. As part of the manual device configuration, make sure that this 
   variable is set to **1**. Otherwise, the library will not start any runtime that involves that Zaber motor. During 
   runtime, the library sets this variable to 0, making it impossible to use the motor without manual intervention again
   if the runtime interrupts without executing the proper shut down sequence that sets the variable back to 1.
   **Warning!** It is imperative to ensure that all motors are parked at positions where they are **guaranteed** to 
   successfully home after power cycling before setting this to 1. Otherwise, it is possible for some motors to collide
   with other system components and damage the acquisition system.
3. **User Data 10**: Device Axis Type Flag. This variable should be set to **1** for motors that move on a linear axis 
   and **0** for motors that move on a rotary axis. This static flag is primarily used to support proper unit 
   conversions and motor positioning logic during runtimes.
4. **User Data 11**: Device Park Position. This variable should be set to the position, in native motor units, where 
   the device should be moved as part of the 'park' command and the shut-down sequence. This is used to position all 
   motors in a way that guarantees they can be safely 'homed' at the beginning of the next runtime. Therefore, each
   park position has to be selected so that each motor can move to their 'home' sensor without colliding with any other
   motor **simultaneously** moving towards their 'home' position. **Note!** The lick-port uses the 'park' position as 
   the **default** imaging position. During runtime, it will move to the 'park' position if it has no animal-specific 
   position to use during imaging. Therefore, make sure that the park position for the lick-port is always set so that 
   it cannot harm the animal mounted in the Mesoscope enclosure while moving to the park position from any other 
   position.
5. **User Data 12** Device Maintenance Position. This variable should be set to the position, in native motor units, 
   where the device should be moved as part of the 'maintain' command. Primarily, this position is used during water 
   delivery system calibration and the running-wheel surface maintenance. Typically, this position is calibrated to
   provide easy access to all hardware components of the system by moving all motors as far away from each other as 
   reasonable.
6. **User Data 13**: Device Mount Position. This variable should be set to the position, in native motor units, where 
   the device should be moved as part of the 'mount' command. For the lick-port, this position is usually far away from 
   the animal, which facilitates mounting and unmounting the animal from the rig. For the head-bar and the wheel motor 
   groups, this position is used as the **default** imaging position. Therefore, set the head-bar and the wheel 'mount'
   positions so that any (new) animal can be comfortably and safely mounted in the Mesoscope enclosure.

### Behavior Cameras
To record the animal’s behavior, the system uses a group of three cameras. The **face_camera** is a high-end
machine-vision camera used to record the animal’s face with approximately 3-MegaPixel resolution. The **left-camera** 
and the **right_camera** are 1080P security cameras used to record the body of the animal. Only the data recorded by the
**face_camera** is currently used during data processing and analysis, but the data from all available cameras is saved 
during acquisition. To interface with the cameras, the system leverages customized
[ataraxis-video-system](https://github.com/Sun-Lab-NBB/ataraxis-video-system) bindings.

Specific information about the cameras and related imaging hardware, as well as the snapshot of the configuration 
parameters used by the **face_camera**, is available 
[here]https://drive.google.com/drive/folders/1l9dLT2s1ysdA3lLpYfLT1gQlTXotq79l?usp=sharing).

### MicroControllers
To interface with all other hardware components **other** than cameras and Zaber motors, the Mesoscope-VR system uses 
Teensy 4.1 microcontrollers with specialized 
[ataraxis-micro-controller](https://github.com/Sun-Lab-NBB/ataraxis-micro-controller) code. Currently, The system 
uses three isolated microcontroller subsystems: **Actor**, **Sensor**, and **Encoder**.

For instructions on assembling and wiring the electronic components used in each microcontroller system, as well as the 
code running on each microcontroller, see the 
[microcontroller repository](https://github.com/Sun-Lab-NBB/sl-micro-controllers).

### Virtual Reality Task Environment (Unity)
The task environment used in all Mesoscope-VR experiments is rendered and controlled by the Unity game engine. To make 
Unity work with this library, each project-specific Unity task must use the bindings and assets released as part of the 
[Unity-tasks repository](https://github.com/Sun-Lab-NBB/Unity-tasks). Follow the instructions from that repository to 
set up Unity Game engine to interface with this library and to create new virtual task environments.

**Note!** This library does not contain tools to initialize Unity Game engine. The desired Virtual Reality task
has to be started ('armed') ***manually*** before entering the main runtime (data acquisition session) cycle. The main 
Unity repository contains more details about starting the virtual reality tasks when running experiments. During 
CLI-driven experiment runtimes, the library instructs the user when to 'arm' the Unity game engine.

### Google Sheets API Integration

This library interacts with the shared Google Sheet files used in the Sun lab to track and communicate certain 
information about the animals that participate in all projects. Currently, this includes two files: the **surgery log** 
and the **water restriction log**. Primarily, this integration is used to ensure that all information about each 
experiment subject (animal) is stored in the same location (on the long-term storage machine(s)). Additionally, it is 
used in the lab to automate certain data logging tasks.

#### Setting up Google Sheets API Access

**If you already have a service Google Sheets API account, skip to the next section.** Most lab members can safely 
ignore this section, as all service accounts are managed at the acquisition-system level, rather than individual lab 
members.

1. Log into the [Google Cloud Console](https://console.cloud.google.com/welcome). 
2. Create a new project.
3. Navigate to APIs & Services → Library and enable the Google Sheets API for the project. 
4. Under IAM & Admin → Service Accounts, create a service account. This will generate a service account ID in the format
   of `your-service-account@gserviceaccount.com`.
5. Use Actions → Manage Keys and, if a key does not already exist, create a new key and download it in JSON format. 
   This key is then used to access the Google Sheets.

#### Adding Google Sheets Access to the Service Account
To access the **surgery log** and the **water restriction log** Google Sheets as part of this library runtime, create 
and share these log files with the email of the service account created above. The service account requires **Editor** 
access to both files.

**Note!** This feature requires that both log files are formatted according to the available Sun lab templates. 
Otherwise, the parsing algorithm will not behave as expected, leading to runtime failures. Additionally, both log files 
have to be pre-filled in advance, as the processing code is not allowed to automatically generate new table (log) rows.
**Hint!** Currently, it is advised to pre-fill the data a month in advance. Since most experiments last for at most a 
month, this usually covers the entire experiment period for any animal.

### ScanImage PC Assets
As mentioned above, the ScanImagePC is largely assembled and configured by external contractors. However, the PC 
requires additional assets and configuration post-assembly to make it compatible with sl-experiment-managed runtimes.

#### File System Access
To support the sl-experiment runtime, the ScanImagePC’s filesystem must be accessible to the **VRPC** via the Server 
Message Block version 3 (SMB3) or equivalent protocol. Since ScanImagePC uses Windows, it is advised to use the SMB3 
protocol, as all Windows machines support it natively with minimal configuration. As a minimum, the ScanImagePC must be 
configured to share the root Mesoscope output folder with the VRPC over the local network. This is required to both 
fetch the data acquired by the Mesoscope during preprocessing and to control the Mesoscope during runtime.

#### Default Screenshot Directory
During runtime, the sl-experiment library prompts the user to generate a screenshot of the ScanImagePC desktop and 
place it in the network-shared mesoscope data folder (see above). The screenshot is used to store the information about
the red-dot alignment, the acquisition parameters, and the state of the imaging plane at the beginning of each session. 
The library is statically configured to fetch the screenshot from the shared folder and will not look in any other 
directories. Therefore, it is advised to reconfigure the default output directory used by the 'Win + PrntSc' command on 
the ScanImagePC to save the screenshots into the shared Mesoscope output directory.

#### MATLAB Assets
ScanImage software is written in MATLAB and controls all aspects of Mesoscope data acquisition. While each runtime 
requires the experimenter to manually interface with the ScanImage GUI during Mesoscope preparation, all data 
acquisition runtimes using the sl-experiment library require the user to call the **setupAcquisition** MATLAB function
available from [mesoscope assets repository](https://github.com/Sun-Lab-NBB/sl-mesoscope-assets). This function carries
out multiple runtime-critical tasks, including setting up the acquisition, generating and applying the online motion 
correction algorithm, and allowing the VRPC to control the Mesoscope via creating or removing binary marker files.

To configure MATLAB to access the mesoscope assets, git-clone the entire repository to the ScanImagePC. Then, follow the
tutorials [here](https://www.mathworks.com/help/matlab/matlab_env/add-remove-or-reorder-folders-on-the-search-path.html)
and add the path to the root mesoscope assets folder to MATLAB’s search path. MATLAB will then be able to use all 
functions from that repository, including the setupAcquisition function. The repository also contains the online 
motion estimation and correction assets developed in the [Pachitariu and Stringer lab](https://mouseland.github.io/), 
which are required for the setupAcquisition function to work as expected.

### Mesoscope-VR Assembly
***This section is currently a placeholder. Since the final Mesoscope-VR system design is still a work in progress, it 
will be populated once the final design implementation is constructed and tested in the lab.***

The Mesoscope-VR assembly mostly consists of two types of components. First, it includes custom components manufactured 
via 3D-printing or machining (for metalwork). Second, it consists of generic components available from vendors such as 
ThorLabs, which are altered in workshops to fit the specific requirements of the Mesoscope-VR system. The blueprints and
CAD files for all components of the Mesoscope-VR systems, including CAD renders of the assembled system, are available 
[here](https://drive.google.com/drive/folders/1Oz2qWAg3HkMqw6VXKlY_c3clcz-rDBgi?usp=sharing).

___

## Acquired Data Structure and Management

The library defines a fixed structure for storing all acquired data which uses a 4-level directory tree hierarchy: 
**root** (volume), **project**, **animal**, and **session**. This structure is reused by all acquisition systems, and 
it is maintained across all long-term storage destinations. After each data acquisition runtime (session), all 
raw data is stored under the **root/project/animal/session/raw_data** directory stored on one or more machines mentioned
below. After each data processing pipeline runtime, all processed data generated by that pipeline is stored under the 
**root/project/animal/session/processed_data**.

Currently, each data acquisition system in the lab uses at least three machines: 
1. The **main data acquisition PC** is used to acquire and preprocess the data. For example, the *VRPC* of the 
   *Mesoscope-VR* system is the main data acquisition PC for that system. This PC is used to both **acquire** the data 
   and, critically, to **preprocess** the data before it is moved to the long-term storage destinations.
2. The **BioHPC compute server** is the main long-term storage destination and the machine used to process and 
   analyze the data. This is a high-performance computing server owned by the lab that can be optionally extended by 
   renting additional nodes from Cornell’s BioHPC cluster. The BioHPC server stores both the raw data and the processed 
   data generated by all Sun lab processing pipelines.
3. The **Synology NAS** is the back-up 'cold' long-term storage destination. It only stores the raw data and is 
   physically located in a different building from the main BioHPC compute server to provide data storage redundancy. It
   is only used to back up raw data and is generally not intended to be accessed unless the main data storage becomes 
   compromised for any reason.

***Critical!*** Each data acquisition system is designed to **mount the BioHPC and the NAS to the main acquisition PC 
filesystem using the Server Message Block 3 (SMB3) protocol**. Therefore, each data acquisition system operates on the 
assumption that all storage component filesystems are used contiguously and can be freely accessed by the main 
acquisition PC OS.

***Note!*** The library tries to maintain at least two copies of data for long-term storage: one on the NAS and the 
other on the BioHPC server. It is configured to purge redundant data from the data acquisition system machines if
the data has been **safely** moved to the long-term storage destinations. The integrity of the moved data is verified
using xxHash-128 checksum before the data is removed from the data-acquisition system.

### Root Directory (Volume)
All data acquisition systems, the Synology NAS and the BioHPC server keep **ALL** Sun lab projects in the same **root** 
directory. The BioHPC server uses **two roots**, one for the raw data and the other for the processed data. This 
separation is due to the BioHPC server using a combination of fast NVME drives and slow HDD drives to optimize storage 
cost and data processing performance. The exact location and name of the root directory on each machine is arbitrary  
but should generally remain fixed (unchanging) over the entire lifetime of that specific machine. 

### Project Directory
When a new project is created, a **project** directory **named after the project** is created under the **root** 
directory of the main data acquisition machine, the Synology NAS, and both the raw and processed data BioHPC volumes. 
Depending on the host machine, this project directory may contain further subdirectories.

All data acquisition systems also create a **configuration** subdirectory under the root project directory. This 
directory stores all supported experiment configurations for the project. Each 'sl-experiment' CLI command call 
searches the configuration directory for the .yaml file with the name of the target experiment to load the experiment
data.

### Animal Directory
When the library is used to acquire data for a new animal, it generates a new **animal** directory under the **root** 
and **project** directory combination. The directory uses the ID of the animal, as its name. Depending on the host
machine, this animal directory may contain further subdirectories. 

All data acquisition systems also create a **persistent_data** subdirectory under the root animal directory, which is 
used to store data that is reused between data acquisition sessions.

***Critical!*** The current Sun lab convention stipulates that all animal IDs should be numeric. While some library 
components do accept strings as inputs, it is expected that all animal IDs only consist of positive integers. Failure to
adhere to this naming convention can lead to runtime errors and unexpected behavior of all library components!

### Session Directory
Each time the library is used to acquire data, a new session directory is created under the **root**, **project** and 
**animal** directory combination. The session name is derived from the current ***UTC*** timestamp at the time of the 
session directory creation, accurate to ***microseconds***. Primarily, this naming format was chosen to make all 
sessions acquired by the same acquisition system have unique and chronologically sortable names. The session name format
follows the order of **YYYY-MM-DD-HH-MM-SS-US**.

### Raw Data and Processed Data:
All data acquired by this library is stored under the **raw_data** subdirectory, generated for each session. Overall, 
an example path to the acquired (raw) data can therefore look like this: 
`/media/Data/Experiments/Template/666/2025-11-11-05-03-234123/raw_data/`. 

Similarly, all Sun lab data processing pipelines generate new files and subdirectories under the **processed_data** 
subdirectory for each session. An example path to the processed_data directory can therefore look like this: 
`/server/sun_data/Template/666/2025-11-11-05-03-234123/processed_data`.

***Note!*** This library treats **both** newly acquired and preprocessed data as **raw**. This is because preprocessing 
**does not change the content of the data**. Instead, preprocessing uses lossless compression to more efficiently 
package the data for transmission and can at any time be converted back to the original format. Processing the data, on 
the other hand, generates additional data and / or modifies the processed data values in ways that may not necessarily 
be reversible.

### Shared Raw Data

The section below briefly lists the data acquired by **all** Sun lab data acquisition systems. Note, each acquisition 
system also generates **system-specific** data, which is listed under acquisition-system-specific sections available 
after this section.

**Note!** For information about the **processed** data, see the 
[main data processing library](https://github.com/Sun-Lab-NBB/sl-forgery).

After acquisition and preprocessing, the **raw_data** folder of each acquisition system will, as a minimum, contain the 
following files and subdirectories:
1. **ax_checksum.txt**: Stores the xxHash-128 checksum used to verify data integrity when it is transferred to the 
   long-term storage destination. The checksum is generated before the data leaves the main data acquisition system PC
   and, therefore, accurately captures the final state of the raw data before it enters storage.
2. **hardware_state.yaml**: Stores the snapshot of the dynamically calculated parameters used by the data acquisition 
   system modules during runtime. These parameters are recalculated at the beginning of each data acquisition 
   session and are rounded and stored using the appropriate floating point type (usually fp64) to minimize floating 
   point rounding errors. This improves the quality of processed data by ensuring that the processing and the 
   acquisition pipelines use the same floating-point parameter values. This file is also used to determine which modules
   were used during runtime and, consequently, which data can be parsed from the .npz log files generated at runtime
   (see below).
3. **session_data.yaml**: Stores information necessary to maintain the same session data structure across all machines 
   used during data acquisition and long-term storage. This file is used by all Sun lab libraries as an entry point for 
   working with session’s data. The file also includes all available information about the identity and purpose of the 
   session and can be used by human experimenters to identify the session. Since version 3.0.0, the file also stores 
   the version of the sl-experiment and Python that were used to acquire the data.
4. **session_descriptor.yaml**: Stores session-type-specific information, such as the task parameters and experimenter 
   notes. The contents of the file are overall different for each session type, although some fields are reused by all 
   sessions. The contents for this file are partially written by the library (automatically) and, partially, by the
   experimenter (manually, at the end of each session). At the end of each runtime, a copy of the descriptor file is 
   cached inside the *persistent_data* directory of the animal, replacing any already existing copy. This is used to 
   optionally restore certain runtime configuration parameters between session types that support this functionality.
5. **surgery_metadata.yaml**: Stores the data on the surgical intervention(s) performed on the animal that participated 
   in the session. This data is extracted from the **surgery log** Google Sheet and, for most animals, should be the 
   same across all sessions.
6. **system_configuration.yaml**: Stores the configuration parameters of the data acquisition system that generated the
   session data. This is a snapshot of **all** dynamically addressable configuration parameters used by the system. 
   When combined with the assembly instructions and the appropriate sl-experiment library version, it allows completely 
   replicating the data acquisition system used to acquire the session data.
7. **behavior_data**: Stores compressed .npz log files that contain all non-video behavior data acquired by the system. 
   This includes all messages sent or received by each microcontroller, the timestamps for the frames acquired by 
   each camera and (if applicable) the main brain activity recording device (e.g.: Mesoscope). These logs also include 
   session metadata, such as trials, task conditions, and system and runtime state transitions. Although the exact 
   content of the behavior data folder can differ between acquisition systems, all systems used in the lab generate some
   form of non-video behavior data.
8. **camera_data**: Stores the behavior videos recorded by video cameras used by the acquisition system. While not 
   technically required for every system, all current Sun lab data acquisition systems use one or more cameras to 
   acquire behavior videos.
9. **experiment_configuration.yaml**: This file is only created for **experiment** sessions. It stores the 
   configuration of the experiment task performed by the animal during runtime. The contents of the file differ for each
   data acquisition system, but each system generates a version of this file. The file contains enough information to 
   fully replicate the experiment runtime on the same acquisition system and to process and analyze the acquired data.
10. **telomere.bin**: This marker is used to communicate whether the session data is **complete**. Incomplete sessions
   appear due to session acquisition runtime being unexpectedly interrupted. This is rare and is typically the result of
   major emergencies, such as sudden power loss or other unforeseen events. Incomplete sessions are automatically 
   excluded from automated data processing and require manual user intervention to assess the usability of the session 
   for analysis. This marker file is created **exclusively** as part of session data preprocessing, based on the value 
   of the **session_descriptor.yaml** file 'incomplete' field.
11. **integrity_verification_tracker.yaml**: This tracker file is used internally to run and track the outcome of the 
   remote data verification procedure. This procedure runs as part of moving the data to the long-term storage 
   destinations to ensure the data is transferred intact. Users can optionally check the status of the verification by 
   accessing the data stored inside the file. **Note!** This file is added **only!** to the raw_data folder stored on
   the BioHPC server.

### Shared Temporary Data
The sl-experiment library additionally uses the following temporary marker files and directories which are cleared 
before the raw data is transmitted to the long-term storage destinations:
1. **nk.bin**: This marker is automatically cached to disk as part of creating a new session data hierarchy. Each 
   runtime removes this marker file when it successfully completes its runtime preparation (the main start() method call
   of the runtime management class). If this marker exists when the runtime enters the shutdown cycle, this indicates 
   that the runtime encountered a fatal error during startup and had to be terminated early. In this case, the session’s
   data is silently deleted, as uninitialized runtime necessarily does not contain any valid data. This is used to 
   automatically declutter the data acquisition and long-term storage PCs to only keep valid sessions.
2. **behavior_data_log**: All behavior log entries are initially saved as individual .npy files. Each .npy file stores 
   a serialized log message in the form of an uint8 (byte) NumPy array. Since messages are cached to disk as soon as 
   they are received by the DataLogger to minimize data loss in case of emergency shutdowns, the temporary 
   behavior_data_log directory is used to store these messages during runtime. Frequently, the directory accumulates 
   millions of .npy files at runtime, making it challenging for human operators to work with the data. During 
   preprocessing, individual .npy files are grouped by their source (what made the log entry, e.g.: VideoSystem, 
   MicroController, Data Acquisition System, etc.) and are compressed into .npz archives, one for each source. The 
   .npz archives are then moved to the *behavior_Data* folder, and the *behavior_data_log* with the individual 
   .npy files is deleted to conserve disk space.
3. **ubiquitin.bin**: This marker file is created during *preprocessing* runtime to mark directories that
   are no longer needed for deletion. Specifically, when preprocessing safely moves the acquired data to long-term 
   storage destinations, it marks all now-redundant raw data from all acquisition system machines (PCs) for removal to 
   optimize disk usage. At the end of preprocessing, a specialized *purge* runtime is executed to discover and remove 
   all directories marked for deletion with the ubiquitin.bin marker files.

### Mesoscope-VR System Data

The Mesoscope-VR system instantiates a directory hierarchy both on the VRPC and the ScanImagePC. Below is the list of 
files and directories found on each of these machines.

#### Raw Data

The Mesoscope-VR system generates the following files and directories, in addition to those discussed in the shared 
raw data section on the VRPC:
1. **mesoscope_data**: Stores all Mesoscope-acquired data (frames, motion estimation files, etc.). Since Mesoscope data
   is only acquired for **experiment** sessions, this directory is kept empty for all other session types. During 
   preprocessing, the folder contents are organized in a way to automatically work with 
   [sl-suite2p](https://github.com/Sun-Lab-NBB/suite2p) single-day processing pipeline. All Mesoscope data is intended 
   to be processed with the sl-suite2p library.
2. **zaber_positions.yaml**: Stores the snapshot of the positions used by the HeadBar, LickPort, and Wheel Zaber motor 
   groups, taken at the end of the session’s data acquisition. All positions are stored in native motor units. This 
   file is created for all session types supported by the Mesoscope-VR system. As a backup, a copy of this file is also
   generated at the beginning of each session runtime. This allows recovering from critical runtime failures, where the
   runtime may not be able to generate this snapshot. During both snapshot generation timepoints, a copy of the 
   generated snapshot file is also cached inside the *persistent_data* directory of the animal to support restoring the
   motors to the same position during the next session.
3. **mesoscope_positions.yaml**: Stores the snapshot of the physical Mesoscope objective position in X, Y, Z, and Roll 
   axes, the virtual ScanImage axes (Fast Z, Tip, Tilt), and the laser power at the sample, taken at the end of the 
   session’s data acquisition. **Note!** This file relies on the experimenter updating the stored positions if they are
   changed during runtime. It is only created for window checking and experiment sessions. A copy of this snapshot file
   is also saved to the *persistent_data* directory of the animal to support restoring the Mesoscope to the same imaging
   field during the next session.
4. **window_screenshot.png**: Stores the screenshot of the ScanImagePC screen. The screenshot should contain the image
   of the red-dot alignment, the view of the target cell layer, the Mesoscope position information, and the data 
   acquisition parameters. Primarily, the screenshot is used by experimenters to quickly reference the imaging quality 
   from each experiment session. This file is only created for window checking and experiment sessions. A copy of this 
   file is saved to the *persistent_data* directory of the animal to help the user to realign the red-dot to a similar 
   position during the next session.

### ScanImagePC

All Mesoscope-VR system data on the ScanImagePC is stored under the user-defined ScanImagePC root directory, which is 
expected to be mounted to the VRPC via the SMB or similar protocol. Under that root directory, the system creates the 
following directories and files:
1. **mesoscope_data**: This directory stores all Mesoscope-acquired data for the currently running session. The 
   *setupAcquisition* MATLAB function configures ScanImage software to output all data to the mesoscope_data directory, 
   which is shared by all sessions, animals, and projects. This allows using the same static output path for all 
   ScanImage acquisitions.
2. **session-specific mesoscope_data**: At the end of each runtime, the Mesoscope-VR system ***renames*** the 
   mesoscope_data directory to include the session name (id). Then, it generates an empty mesoscope_data directory for
   the next runtime. This way, all data of each completed session is stored under a unique directory named after that 
   session. This step is crucial for data preprocessing, which identifies the session data directory and pulls it over
   to the VRPC based on the session name (id).
3. **persistent_data**. This directory is created for each unique **project** and **animal** combination, 
   similar to the data structure created by sl-experiment on the main acquisition system PC. This directory contains 
   the **first day** MotionEstimator.me and fov.roi files. These files are typically reused by all following data 
   acquisition sessions to restore the imaging field to the same location as used on the first day. The full path to 
   the persistent_data directory would typically look like **root/project/animal/persistent_data**.

#### Mesoscope-VR Temporary Data

The Mesoscope-VR system also generates the following temporary files and directories during runtime:
1. **raw_mesoscope_data**: Stores uncompressed .TIFF stacks fetched by the VRPC from the ScanImagePC. This is done 
   as part of data preprocessing to collect all data on the VRPC before executing individual preprocessing subroutines.
   The .TIFF stacks are then re-compressed using the Limited Error Raster Compression (LERC) scheme and are saved to the
   *mesoscope_data* folder. Once this process completes successfully, the *raw_mesoscope_data* with all raw files is 
   deleted to conserve disk space.
2. **kinase.bin**: This marker is created in the *mesoscope_data* ScanImagePC directory. During runtime, the 
   *setupAcquisition* MATLAB function monitors the *mesoscope_data* directory for the presence of this marker file. If 
   the file is present, the function triggers the Mesoscope data acquisition. If the file is absent, the function stops
   the Mesoscope data acquisition until the file is re-created. As such, the VRPC uses this marker file to start 
   and stop the Mesoscope data acquisition during normal operation.
3. **phosphatase.bin**: This marker works similar to the *kinase.bin* marker, but is used by the VRPC to abort the 
   ScanImagePC runtime at any point. When ScanImagePC is waiting for the *kinase.bin* marker to be created for the first
   time, stopping the Mesoscope acquisition necessarily requires the kinase marker to be first created and then removed,
   triggering a brief Mesoscope frame acquisition. Creating the *phosphatase.bin* marker instead triggers the 
   ScanImagePC to end the runtime without waiting for the *kinase.bin* marker, effectively aborting the runtime without
   acquiring any frames.

--- 

## Acquiring Data in the Sun Lab

All user-facing library functionality is realized through a set of Command Line Interface (CLI) commands automatically 
exposed when the library is pip-installed into a python environment. Some of these commands take additional arguments 
that allow further configuring their runtime. Use `--help` argument when calling any of the commands described below to
see the list of supported arguments together with their descriptions and default values.

To use any of the commands described below, activate the python environment where the libray is installed, e.g., with 
`conda activate MYENV` and type one of the commands described below.

***Warning!*** Most commands described below use the terminal to communicate important runtime information to the user 
or request user feedback. **Make sure you carefully read every message printed to the terminal during runtime**. 
Failure to do so may damage the equipment or harm the animal!

### Step 0: Configuring the Data Acquisition System

Before acquiring data, each acquisition system has to be configured. This step is done in addition to assembling 
the system and installing the required hardware components. Typically, this only needs to be done when the acquisition 
system configuration or hardware changes, so most lab members can safely skip this step.

Use `sl-create-system-config` command to generate the system configuration file. As part of its runtime, the command 
configures the host machine to remember the path to the generated configuration file, so all future sl-experiment 
runtimes on that machine will automatically load and use the appropriate acquisition-system configuration parameters.

***Note!*** Each acquisition system uses unique configuration parameters. Additionally, the sl-experiment library always
assumes that any machine (PC) can only be used by a single data-acquisition system (is permanently a part of that 
acquisition system). Only the **main** PC of the data acquisition system (e.g.: the VRPC of the Mesoscope-VR system) 
that runs the sl-experiment library should be configured via this command.

For information about the available system configuration parameters, read the *API documentation* of the appropriate 
data-acquisition system available from the [sl-shared-assets](https://github.com/Sun-Lab-NBB/sl-shared-assets) library.
Specifically, all data acquisition system configuration parameters are defined in the *SystemConfiguration* class named
after that system.

Additionally, since every data acquisition system requires access to the BioHPC server for long-term data storage, it 
needs to be provided with server access credentials. The credentials are stored inside the 'server_credentials.yaml'
file, which is generated by using the `sl-create-server-credentials` command. **Note!** The path to the generated and
filled credential file has to be provided to the acquisition system before runtime by editing the acquisition-system 
configuration file created via the command discussed above.

### Step 1: Creating a Project

All data acquisition sessions require a valid project to run. To create a new project, use the `sl-create-project`
command. This command can only be called on the main PC of a properly configured data-acquisition system (see Step 0 
above). As part of its runtime, this command generates the root project directory on all machines that make up the 
data acquisition systems and long-term storage destinations.

### Step 2: Creating an Experiment

All projects that involve scientific experiments also need to define at least one **experiment configuration**. 
Experiment configurations are unique for each data acquisition system and are stored inside .yaml files named after the
experiment. To generate a new experiment configuration file, use the `sl-create-experiment` command. This command 
generates a **precursor** experiment configuration file inside the **configuration** subdirectory, stored under the root
project directory on the main PC of the data acquisition system.

For information about the available experiment configuration parameters in the precursor file, read the 
*API documentation* of the appropriate data-acquisition system available from the 
[sl-shared-assets](https://github.com/Sun-Lab-NBB/sl-shared-assets) library.

### Step 3: Maintaining the Acquisition System

All acquisition systems contain modules that require frequent maintenance. Most of these modules are unique to each 
acquisition system. Therefore, this section is further broken into acquisition-system-specific subsections.

#### Mesoscope-VR

The Mesoscope-VR system contains two modules that require frequent maintenance: the **water delivery system** and the 
**running wheel**. To facilitate the maintenance of these modules, the sl-experiment library exposes the `sl-maintain`
command.

This command is typically called at least twice during each day the system is used to acquire data. First, it is used 
at the beginning of the day to prepare the Mesoscope-VR system for runtime by filling the water delivery system. Second,
it is used at the end of each day to empty the water delivery system.

Less frequently, this command is used to re-calibrate the water delivery system, typically, as a result of replacing 
system components, such as tubing or the valve itself. The command is also occasionally used to replace the 
surface material of the running wheel, which slowly deteriorates as the wheel is used.

This command can also facilitate cleaning the wheel, which is typically done before and after each runtime to remove 
any biological contaminants left by each animal participating in experiment or training runtimes.

***Note!*** Since this runtime fulfills multiple functions, it uses an 'input'-based terminal interface to accept 
further commands during runtime. To prevent visual bugs, the input does not print anything to the terminal and appears 
as a blank new line. If you see a blank new line with no terminal activity, this indicates that the system is ready 
to accept one of the supported commands. All supported commands are printed to the terminal as part of the runtime 
initialization.

Supported vr-maintenance commands:
1.  `open`. Opens the water delivery valve.
2.  `close`. Closes the water delivery valve.
3.  `close_10`. Closes the water delivery valve after a 10-second delay.
4.  `reference`. Triggers 200 valve pulses with each pulse calibrated to deliver 5 uL of water. This command is used to
    check whether the valve calibration data stored in the system_configuration.yaml file is accurate. This should
    be done at the beginning of each day the system is used to acquire data. The reference runtime should overall 
    dispense ~ 1 ml of water. If the reference procedure does not dispense the expected volume of water, the system 
    needs to be recalibrated.
5.  `calibrate_15`. Runs 200 valve pulses, keeping the valve open for 15 milliseconds at each pulse. This is used to 
    generate valve calibration data.
6.  `calibarte_30`. Same as above, but uses 30-millisecond pulses.
7.  `calibrate_45`. Same as above, but uses 45-millisecond pulses.
8.  `calibrate_60`. Same as above, but uses 60-millisecond pulses.
9.  `lock`. Locks the running wheel (engages running-wheel break).
10. `unlock`. Unlocks the running wheel (disengages running wheel break).

### Step 4: Acquiring Data

Each acquisition system supports one or more distinct types of data-acquisition sessions (runtimes). As a minimum, this
includes an 'experiment' session type, which is the primary use case for all acquisition systems in the lab. Some 
systems may also support one or more training session types, which often do not acquire any brain activity data, but 
otherwise behave similar to experiment sessions.

#### Mesoscope-VR

The Mesoscope-VR system supports four types of runtime sessions, each associated with a unique runtime command exposed
by the sl-experiment library:
1. **Window Checking**: This session is executed by calling the `sl-check-window` command. It guides the user through 
finding the imaging plane and generating the reference MotionEstimator.me and zstack.tiff files for the checked 
animal. This session is typically used ~2–3 weeks after the surgical intervention and before any training or experiment 
sessions to assess the quality of the intervention and the suitability of including the animal in experiment cohorts.
2. **Lick Training**: This session is executed by calling the `sl-lick-train` command. All animals that participate in 
Mesoscope-VR experiments undergo a two-stage training protocol, with lick training being the first stage. During this
runtime, the animals are head fixed in the Mesoscope enclosure for ~ 20 minutes. The primary goal of the runtime is 
to teach the animals to lick at the water tube to consume water rewards and associate the sound tone emitted at reward 
delivery with water coming out of the tube. During runtime, the running wheel is locked, so the animals cannot run.
3. **Run Training**: This session is executed by calling the `sl-run-train` command. This is the second stage of the 
mandatory two-stage Mesoscope-VR training protocol. During this runtime, the animals are head fixed in the Mesoscope 
enclosure for ~ 40 minutes. The primary goal of the runtime is to teach the animals to run on the wheel while head-fixed
and to associate running with receiving water rewards. During runtime, the running wheel is unlocked, but the Virtual 
Reality screens are kept off, ensuring that the animal is not exposed to any visual cues until the first experiment day.
4. **Mesoscope Experiment**: This session is executed by calling the `sl-experiment` command. This type of session is 
designed to execute the experiment specified in the target *experiment_configuration.yaml* file (see above). The system
supports varying experiment configurations and Virtual Reality environments, offering experimenters the flexibility to 
run different projects using the same set of APIs and system hardware.

### Step 5: Preprocessing and Managing Data

All acquisition systems support two major ways of handling the session data acquired at runtime. For most runtimes, the 
choice of how to handle the data is made as part of the acquisition system shutdown sequence. However, in the case of 
unexpected runtime terminations, all data preprocessing steps can also be executed manually by calling the appropriate
CLI command.

The first and most commonly used way is to **preprocess** the acquired data. This can be done manually by calling the 
`sl-preprocess` command. Preprocessing consists of two major steps. The first step pulls all available data to the 
main data acquisition system machine (PC) and re-packages (re-compresses) the data to reduce its size without loss. The 
second step distributes (pushes) the data to **multiple** long-term storage destinations, such as the NAS and the 
BioHPC server.

**Critical!** It is imperative that **all** valid data acquired in the lab undergoes preprocessing 
**as soon as possible**. Only preprocessed data is stored in a way that maximizes its safety by using both 
redundancy and parity. Data that is not preprocessed may be **lost** in the case of emergency, which is considerably 
less likely for the preprocessed data.

When preprocessed data is successfully and safely pushed to long-term storage destinations, the preprocessing runtime 
marks all raw data directories for that session stored on any acquisition system machine for deletion by creating the 
*ubiquitin.bin* marker files. It then calls a function that finds and removes marked directories for **all available
projects and animals**. This final step can be triggered manually by calling the `sl-purge` CLI command. To optimize
disk space usage on acquisition system machines, it is recommended to call this command at least daily.

The second way of managing the data is primarily used during testing and when handling interrupted sessions that did 
not generate any valid data. This involves removing all session data from **both** the data acquisition system and all 
long-term storage destinations. This runtime is extremely dangerous and, if not used carefully, can 
***permanently delete valid data***. This processing mode can be triggered using the `sl-delete-session-data` CLI 
command, although it is not recommended for most users.

---

## API Documentation

See the [API documentation](https://sl-experiment-api-docs.netlify.app/) for the
detailed description of the methods and classes exposed by components of this library, as well as all available 
CLI commands with their arguments

___

## Recovering from Interruptions
While it is not typical for the data acquisition or preprocessing pipelines to fail during runtime, it is possible. The 
library can recover or gracefully terminate the runtime for most code-generated errors, so this is usually not a
concern. However, if a major interruption (i.e., power outage) occurs or one of the hardware assets malfunctions during
runtime, manual intervention is typically required to recover the session data and reset the acquisition system.

### Data acquisition interruption

Data acquisition can be interrupted in two main ways, the first being due to an external asset failure, for example, if 
the ScanImagePC unexpectedly shuts down during Mesoscope-VR system runtime. In this case, the runtime pauses and 
instructs the user to troubleshoot the issue and then resume the runtime. This type of *soft* interruption is handled 
gracefully during runtime, data processing, and analysis to exclude the data collected during the interruption from the 
output dataset. Generally, soft interruptions are supported for most external assets, which includes anything not 
managed directly by the sl-experiment library and the main data acquisition system PC. While inconvenient, these 
interruptions do not typically require specialized handling other than recovering and restoring the failed asset.

**Note!** While most soft interruptions typically entail resuming the interrupted runtime, it is also possible to
instead terminate the runtime. To do so, execute the `termiante` command via the GUI instead of trying to resume 
the runtime. In this case, the system attempts to execute a graceful shutdown procedure, saving all valid data in the 
process.

The second way involves interruption due to sl-experiment runtime failures or unexpected shut-downs of the main 
acquisition system PC. In these cases, manual user intervention is typically required to recover the useful data and 
reset the system before the acquisition can be restarted. The handling of such cases often consists of specific steps
or each supported acquisition system. Typically, these *hard* interruptions are related to major issues, such as 
global facility power loss or severe malfunction of sensitive acquisition system components, such as microcontrollers 
and communication cables.

#### Mesoscope-VR
If the VRPC runtime unexpectedly interrupts at any point without executing the graceful shutdown, follow these 
instructions:
1. If the session involved Mesoscope imaging, shut down the Mesoscope acquisition process and make sure all required 
   files (frame stacks, motion estimator data, cranial window screenshot) have been generated and saved to the 
   **mesoscope_data** folder.
2. If necessary, **manually** edit the session_descriptor.yaml, the mesoscope_positions.yaml, and the 
   zaber_positions.yaml files to include actual runtime information. Estimate the volume of water delivered at runtime 
   by manually reading the water tank level gauge. 
3. Remove the animal from the Mesoscope enclosure. If necessary, use the *Zaber Launcher* app to directly interface with
   Zaber motors and move them in a way that allows the animal to be recovered from the enclosure.
4. Use Zaber Launcher to **manually move the HeadBarRoll axis to have a positive angle** (> 0 degrees). This is 
   critical! If this is not done, the motor will not be able to home during the next session and will instead collide 
   with the movement guard, at best damaging the motor and, at worst, the Mesoscope.
5. Go into the 'Device Settings' tab of the Zaber Launcher, click on each Device tab (NOT motor!) and navigate to its 
   User Data section. Then **flip Setting 1 from 0 to 1**. Without this, the library will refuse to operate the Zaber 
   Motors during all future runtimes.
6. If the session involved Mesoscope imaging, **rename the mesoscope_data folder to prepend the session name, using an
   underscore to separate the folder name from the session name**. For example, from mesoscope_data → 
   2025-11-11-05-03-234123_mesoscope_data. **Critical!** if this is not done, the library may **delete** any leftover 
   Mesoscope files during the next runtime and will not be able to properly preprocess the frames for the interrupted
   session during the next step.
7. Call the `sl-process` command and provide it with the path to the session directory of the interrupted session. This
   will preprocess and transfer all collected data to the long-term storage destinations. This way, you can preserve 
   any data acquired before the interruption and prepare the system for running the next session.

### Data preprocessing interruption
To recover from an error encountered during preprocessing, call the `sl-process` command and provide it with the path 
to the session directory of the interrupted session. The preprocessing pipeline should automatically resume an 
interrupted runtime from the nearest checkpoint.

---

## Versioning

This project uses [semantic versioning](https://semver.org/). For the versions available, see the 
[tags on this repository](https://github.com/Sun-Lab-NBB/sl-experiment/tags).

---

## Authors

- Ivan Kondratyev ([Inkaros](https://github.com/Inkaros))
- Kushaan Gupta ([kushaangupta](https://github.com/kushaangupta))
- Natalie Yeung
- Katlynn Ryu ([katlynn-ryu](https://github.com/KatlynnRyu))
- Jasmine Si

___

## License

This project is licensed under the GPL3 License: see the [LICENSE](LICENSE) file for details.

___

## Acknowledgments

- All Sun lab [members](https://neuroai.github.io/sunlab/people) for providing the inspiration and comments during the
  development of this library.
- The creators of all other projects used in our development automation pipelines and source code 
  [see pyproject.toml](pyproject.toml).

---