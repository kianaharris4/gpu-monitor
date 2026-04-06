# GPU Monitor

GPU Monitor is a small FastAPI app that serves a live GPU telemetry dashboard.

## What changed

This project can now be packaged as a wheel and installed with a `gpu-monitor` command, so another machine does not need a full repository checkout.

## Best distribution options

1. Build a wheel once and copy that file to any target machine.
2. Publish the wheel to PyPI or attach it to a GitHub Release.

For an Ubuntu Intel NUC, the wheel approach is the most practical because the host still needs Intel GPU telemetry tools and access to `/dev/dri`.

## Local build

From the repository root:

```bash
python -m pip install --upgrade build
python -m build
```

That creates a wheel in `dist/`, for example:

```bash
dist/gpu_monitor-0.1.0-py3-none-any.whl
```

## Install on Ubuntu

Install system prerequisites first:

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv intel-gpu-tools
```

If `intel_gpu_top` needs elevated access on that machine, run the service with sufficient permissions or add the account to the appropriate render/video groups.

Install the wheel:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install /path/to/dist/gpu_monitor-0.1.0-py3-none-any.whl
```

Start the dashboard so it is reachable from another machine on your LAN:

```bash
gpu-monitor --host 0.0.0.0 --port 8000
```

Open:

```text
http://<ubuntu-hostname-or-ip>:8000
```

## Development run

From a source checkout, the old workflow still works:

```bash
python main.py --host 127.0.0.1 --port 8000 --reload
```

## Publish for anyone to use

If you want anyone to install it without downloading the repository, publish one of these:

1. A wheel file in GitHub Releases.
2. A package to PyPI, so users can run `pip install gpu-monitor`.

## Ubuntu notes

Intel integrated GPUs on Ubuntu usually expose telemetry through `intel_gpu_top` from `intel-gpu-tools`.

This means:

1. The host must have the Intel tooling installed.
2. The process must be able to read GPU telemetry.
3. A Python wheel is a better default than a container for this target, unless you explicitly want to manage `/dev/dri` passthrough.