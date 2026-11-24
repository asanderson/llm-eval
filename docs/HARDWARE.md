# Hardware configurations

A hardware configuration is one machine, one operating system and the settings the measurements ran under. Its id is the `hardware_config_id` of campaign inventories and the hardware column of the [results](results/README.md). All three configurations below run on the same laptop, one physical host (`physical_host_id` `raider`), so the harness never runs two isolated measurements of them at the same time; see [hardware and isolation](CAMPAIGNS.md#hardware-and-isolation).

| Configuration | Operating system (`os_id`) | Walkthrough | Example inventory | Published results | Recommended setups |
|---|---|---|---|---|---|
| [raider-windows](#raider-windows) | Windows 11 Pro, native (`windows-11-native`) | [Native Windows 11](WINDOWS_RAIDER_WALKTHROUGH.md) | [inventory](../configs/examples/raider-windows/inventory.json) | [results](results/index/hardware/raider-windows.md) | [model offloading](results/index/recommended/raider-windows/model-offloading.md) · [decision models](results/index/recommended/raider-windows/decision-models.md) · [legal models](results/index/recommended/raider-windows/legal-models.md) |
| [raider-wsl](#raider-wsl) | WSL2 with Ubuntu 26.04 on that Windows host (`windows-11-wsl2-ubuntu-26.04`) | [WSL2 / Ubuntu 26.04](WSL_RAIDER_WALKTHROUGH.md) | [inventory](../configs/examples/raider-wsl/inventory.json) | [results](results/index/hardware/raider-wsl.md) | [hardware fit](results/index/recommended/raider-wsl/hardware-fit.md) · [model offloading](results/index/recommended/raider-wsl/model-offloading.md) · [decision models](results/index/recommended/raider-wsl/decision-models.md) · [legal models](results/index/recommended/raider-wsl/legal-models.md) |
| [raider-ubuntu](#raider-ubuntu) | Ubuntu 26.04, native (`ubuntu-26.04-native`) | [Native Ubuntu 26.04](UBUNTU_RAIDER_WALKTHROUGH.md) | [inventory](../configs/examples/raider-ubuntu/inventory.json) | [results](results/index/hardware/raider-ubuntu.md) | [decision models](results/index/recommended/raider-ubuntu/decision-models.md) |

## The machine

All three use the hardware profile [`msi-raider-18-hx-ai`](../configs/hardware/msi-raider-18-hx-ai.json): an MSI Raider 18 HX AI A2XWJG-069US with an Intel Core Ultra 9 285HX (Arrow Lake-HX, 8 P-cores and 16 E-cores, 24 threads, AVX2 without AVX-512 or AMX), an NVIDIA GeForce RTX 5090 Laptop GPU (Blackwell, compute capability 12.0, 24 GiB), 64 GiB of DDR5-6400 in two channels, the factory 2 TB NVMe drive and a 4 TB WD_BLACK SN7100. The profile lists what every run must record (BIOS version, NVIDIA driver, GPU power limit, AC state, MSI power profile, MUX setting and more); the published reports state the values each run recorded.

## raider-windows

Native Windows 11 Pro 10.0.26300. As recorded by the published runs: NVIDIA driver 610.74 with 24,463 MiB of VRAM, 63.4 GiB of usable RAM, the Phison 2 TB NVMe drive with NTFS, AC power, MSI Center "Best Performance" and the MUX in MSHybrid mode. Measured experiments: model offloading, decision models and legal models. The [conclusions for this configuration](results/README.md#raider-windows) describe the conditions of each campaign, including the background programs that were running.

## raider-wsl

WSL2 with Ubuntu 26.04 on the Windows host of `raider-windows`. As recorded by the published runs: WSL 2.7.12.0, kernel 6.18.33.2-microsoft-standard-WSL2 and NVIDIA driver 610.74 as read in the guest. Most jobs ran with a guest memory limit of 52 GB (`.wslconfig` `memory=52GB`, 51.0 GiB `MemTotal`) and no swap; the [WSL2 results](results/README.md#raider-wsl) state the limit of each group of jobs. Model files and the Ollama and KoboldCpp runtimes live on the ext4 virtual disk of the guest, on the same NVMe volume; LM Studio runs from the vendor AppImage installed in the guest. The hardware-fit runs of 2026-11-23 on KoboldCpp and LM Studio loaded the model from the Windows volume (`/mnt/c`), which the WSL profile otherwise avoids; those reports say so. Measured experiments: hardware fit, model offloading, decision models and legal models.

## raider-ubuntu

Native Ubuntu 26.04 on the same laptop. Only a synthetic fixture run of the decision-models experiment has been published, which measures no model, so there are no conclusions for this configuration yet.

## Adding a configuration

A new machine gets its own hardware profile under `configs/hardware/`, an inventory entry with its target and `os_id`, and its own walkthrough or notes. [Campaigns](CAMPAIGNS.md) describes inventories, execution targets and SSH hosts; [methodology](METHODOLOGY.md#hardware-and-os-controls) lists the controls every configuration records.
