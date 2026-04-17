# GPU Monitor

GPU Monitor is a small FastAPI app that serves a live GPU telemetry dashboard for the GPU already installed on your own machine.

It is designed to run locally, then expose a browser dashboard over HTTP so you can open it from the same machine or another system on your LAN.

## What it supports today

- Windows PCs with Intel, NVIDIA, or AMD GPUs through `dxdiag`, Windows GPU performance counters, and `nvidia-smi` when present
- Linux systems with NVIDIA GPUs through `nvidia-smi`
- Linux Intel integrated GPUs through `intel_gpu_top`
- Linux NVIDIA Jetson systems through `tegrastats`

Metric coverage varies by platform and driver. When a vendor API does not expose a field, the dashboard shows that gap instead of crashing.

For the backend design and why each telemetry command is used, see [BACKEND_TELEMETRY_CONCEPTS.md](BACKEND_TELEMETRY_CONCEPTS.md).

For details on what each **Essentials** value can mean, see [KEY_PROPERTIES_REFERENCE.md](KEY_PROPERTIES_REFERENCE.md).

## Quick start

### 1. Clone the repo

```bash
git clone <your-repo-url>
cd gpu_monitor
```

### 2. Create a virtual environment

Windows PowerShell:

```powershell
py -3.10 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

Linux:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
```

### 3. Install the app

```bash
python -m pip install --force-reinstall .
```

### 4. Start the dashboard

```bash
gpu-monitor --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.

To make it reachable from another machine on your network:

```bash
gpu-monitor --host 0.0.0.0 --port 8000
```

Then open `http://<hostname-or-ip>:8000`.

## Platform prerequisites

### Windows

Install Python 3.10+ and run:

```powershell
python -m pip install --force-reinstall .
gpu-monitor --host 127.0.0.1 --port 8000
```

Notes:

- Intel and AMD live metrics come from Windows GPU counters
- NVIDIA cards use `nvidia-smi` when available for richer telemetry
- Some integrated GPU fields like temperature, power, or per-process GPU% may not be available on Windows

### Ubuntu or other Linux with Intel iGPU

Install the Intel telemetry tool first:

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv intel-gpu-tools
```

If `intel_gpu_top` needs elevated access, run the service with sufficient permissions or add the account to the appropriate render or video groups.

If you update from an older local build, reinstall with `--force-reinstall` so the latest packaged dashboard HTML is used.

Then install and run:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --force-reinstall .
gpu-monitor --host 0.0.0.0 --port 8000
```

### Linux with NVIDIA GPU

Make sure the NVIDIA driver and `nvidia-smi` are installed and working:

```bash
nvidia-smi
```

Then install and run:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --force-reinstall .
gpu-monitor --host 0.0.0.0 --port 8000
```

### NVIDIA Jetson

The dashboard detects Jetson boards through `tegrastats`.

Install and run:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --force-reinstall .
gpu-monitor --host 0.0.0.0 --port 8000
```

## Build a distributable wheel

If you want other people to try it without cloning the repo, build a wheel and share the file:

```bash
python -m pip install --upgrade build
python -m build
```

That creates files in `dist/` such as:

```text
dist/gpu_monitor-0.1.2-py3-none-any.whl
```

Someone else can then install it with:

```bash
python -m pip install /path/to/dist/gpu_monitor-0.1.2-py3-none-any.whl
```

## Development run

You can still run it straight from a source checkout:

```bash
python main.py --host 127.0.0.1 --port 8000 --reload
```

## Publish options

If you want anyone to be able to install it without downloading the repository, the easiest next steps are:

1. Attach the built wheel to a GitHub Release
2. Publish the package to PyPI

## GitHub Actions release flow

This repo now includes a GitHub Actions workflow at [.github/workflows/package.yml](.github/workflows/package.yml).

It does two things:

1. On every push to `main` and every pull request, it builds the source distribution and wheel
2. When you push a tag like `v0.1.0`, it creates a GitHub Release and uploads the files from `dist/`

Example:

```bash
git tag v0.1.0
git push origin main --tags
```

After that, users can download the wheel from the GitHub Release page and install it with `pip`.

## Known limitations

- Linux Intel memory is reported as shared system RAM/UMA usage when dedicated VRAM is not exposed
- Jetson support depends on the exact `tegrastats` output format on the target device
- Per-process GPU attribution is not available on every vendor or OS path

For platform-specific telemetry errors and suggested fixes, see [TELEMETRY_TROUBLESHOOTING.md](TELEMETRY_TROUBLESHOOTING.md).
