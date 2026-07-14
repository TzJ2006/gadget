"""
Cross-platform hardware detection for CPU, GPU, and system information.
"""
import platform
import subprocess
import re
import os
from typing import Dict, List, Any, Optional


def get_cpu_info() -> Dict[str, Any]:
    """
    Detect CPU information across platforms.

    Returns:
        Dictionary with CPU model, cores, and frequency.
    """
    system = platform.system()
    info = {
        'model': 'Unknown CPU',
        'cores': os.cpu_count() or 1,
        'frequency': 'Unknown',
        'architecture': platform.machine(),
    }

    # Enhanced CPU detection per OS
    if system == 'Linux':
        try:
            with open('/proc/cpuinfo', 'r') as f:
                cpuinfo = f.read()
            # Extract model name
            model_match = re.search(r'model name\s*:\s*(.+)', cpuinfo)
            if model_match:
                info['model'] = model_match.group(1).strip()
            # Extract CPU frequency
            freq_match = re.search(r'cpu MHz\s*:\s*([\d.]+)', cpuinfo)
            if freq_match:
                info['frequency'] = f"{float(freq_match.group(1)) / 1000:.2f} GHz"
        except Exception:
            pass

    elif system == 'Windows':
        # Try multiple methods for Windows CPU detection
        cpu_name = None

        # Method 1: wmic (deprecated but still works on many systems)
        if not cpu_name:
            try:
                result = subprocess.run(
                    ['wmic', 'cpu', 'get', 'name', '/value'],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if line.startswith('Name='):
                            cpu_name = line.split('=', 1)[1].strip()
                            break
            except Exception:
                pass

        # Method 2: PowerShell (works on Windows 10/11)
        if not cpu_name:
            try:
                result = subprocess.run(
                    ['powershell', '-Command',
                     '(Get-CimInstance -ClassName Win32_Processor).Name'],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0 and result.stdout.strip():
                    cpu_name = result.stdout.strip()
            except Exception:
                pass

        # Method 3: registry query
        if not cpu_name:
            try:
                result = subprocess.run(
                    ['reg', 'query',
                     r'HKEY_LOCAL_MACHINE\HARDWARE\DESCRIPTION\System\CentralProcessor\0',
                     '/v', 'ProcessorNameString'],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if 'ProcessorNameString' in line and 'REG_SZ' in line:
                            parts = line.split('REG_SZ')
                            if len(parts) > 1:
                                cpu_name = parts[1].strip()
                                break
            except Exception:
                pass

        # Method 4: environment variable
        if not cpu_name:
            try:
                result = subprocess.run(
                    ['echo', '%PROCESSOR_IDENTIFIER%'],
                    capture_output=True, text=True, timeout=5, shell=True
                )
                if result.returncode == 0 and result.stdout.strip():
                    identifier = result.stdout.strip()
                    if identifier and identifier != '%PROCESSOR_IDENTIFIER%':
                        # Extract family/model info and format nicely
                        cpu_name = identifier
            except Exception:
                pass

        if cpu_name:
            info['model'] = cpu_name

    elif system == 'Darwin':  # macOS
        try:
            result = subprocess.run(
                ['sysctl', '-n', 'machdep.cpu.brand_string'],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                info['model'] = result.stdout.strip()

            # Get CPU frequency
            result = subprocess.run(
                ['sysctl', '-n', 'hw.cpufrequency'],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                freq_hz = int(result.stdout.strip())
                info['frequency'] = f"{freq_hz / 1e9:.2f} GHz"
        except Exception:
            pass

    return info


def get_gpu_info() -> List[Dict[str, Any]]:
    """
    Detect GPU information across vendors.

    Returns:
        List of GPU dictionaries with vendor, model, memory, etc.
    """
    gpus = []

    # Try PyTorch first
    try:
        import torch
        _detect_nvidia_gpus(torch, gpus)
        _detect_apple_gpus(torch, gpus)
        _detect_intel_xpu_gpus(torch, gpus)
    except ImportError:
        pass

    # Fallback to PyOpenCL for Intel/AMD GPUs
    if not gpus:
        try:
            import pyopencl as cl
            _detect_opencl_gpus(cl, gpus)
        except ImportError:
            pass

    return gpus


def _detect_nvidia_gpus(torch, gpus: List[Dict[str, Any]]):
    """Detect NVIDIA GPUs using PyTorch CUDA."""
    if not torch.cuda.is_available():
        return

    for i in range(torch.cuda.device_count()):
        props = torch.cuda.get_device_properties(i)
        gpus.append({
            'vendor': 'NVIDIA',
            'model': props.name,
            'memory_gb': round(props.total_memory / (1024 ** 3), 2),
            'compute_capability': f"{props.major}.{props.minor}",
            'backend': 'cuda',
            'device_index': i,
        })


def _detect_apple_gpus(torch, gpus: List[Dict[str, Any]]):
    """Detect Apple GPUs using PyTorch MPS."""
    if not (hasattr(torch.backends, 'mps') and torch.backends.mps.is_available()):
        return

    try:
        # Get Apple GPU name from system profiler
        result = subprocess.run(
            ['system_profiler', 'SPDisplaysDataType'],
            capture_output=True, text=True, timeout=10
        )
        gpu_name = 'Apple GPU (MPS)'
        for line in result.stdout.split('\n'):
            if 'Chipset Model:' in line:
                gpu_name = line.split(':', 1)[1].strip()
                break

        # Try to get memory (approximate for Apple Silicon)
        import sys
        try:
            import psutil
            memory_gb = round((psutil.virtual_memory().total / (1024 ** 3)) / 4, 2)  # Approx 1/4 of RAM
        except ImportError:
            memory_gb = 0

        gpus.append({
            'vendor': 'Apple',
            'model': gpu_name,
            'memory_gb': memory_gb,
            'compute_capability': 'MPS',
            'backend': 'mps',
            'device_index': 0,
        })
    except Exception:
        gpus.append({
            'vendor': 'Apple',
            'model': 'Apple GPU (MPS)',
            'memory_gb': 0,
            'compute_capability': 'MPS',
            'backend': 'mps',
            'device_index': 0,
        })


def _detect_intel_xpu_gpus(torch, gpus: List[Dict[str, Any]]):
    """Detect Intel GPUs using PyTorch XPU (oneAPI)."""
    try:
        if hasattr(torch, 'xpu') and torch.xpu.is_available():
            for i in range(torch.xpu.device_count()):
                props = torch.xpu.get_device_properties(i)
                gpus.append({
                    'vendor': 'Intel',
                    'model': getattr(props, 'name', f'Intel XPU {i}'),
                    'memory_gb': round(getattr(props, 'total_memory', 0) / (1024 ** 3), 2),
                    'compute_capability': 'XPU',
                    'backend': 'xpu',
                    'device_index': i,
                })
    except Exception:
        pass


def _detect_opencl_gpus(cl, gpus: List[Dict[str, Any]]):
    """Detect GPUs using PyOpenCL (fallback for Intel/AMD)."""
    try:
        platforms = cl.get_platforms()
        for platform in platforms:
            devices = platform.get_devices(device_type=cl.device_type.GPU)
            for device in devices:
                vendor = platform.name
                if 'Intel' in vendor:
                    vendor = 'Intel'
                elif 'AMD' in vendor or 'Advanced Micro' in vendor:
                    vendor = 'AMD'
                else:
                    vendor = vendor.split()[0]

                gpus.append({
                    'vendor': vendor,
                    'model': device.name,
                    'memory_gb': round(device.global_mem_size / (1024 ** 3), 2),
                    'compute_capability': 'OpenCL',
                    'backend': 'opencl',
                    'device_index': 0,  # OpenCL doesn't use device indices the same way
                })
    except Exception:
        pass


def get_system_info() -> Dict[str, Any]:
    """
    Get comprehensive system information.

    Returns:
        Dictionary with CPU, GPU, and software information.
    """
    cpu_info = get_cpu_info()
    gpu_info = get_gpu_info()

    software = {
        'os': f"{platform.system()} {platform.release()}",
        'python': platform.python_version(),
        'architecture': platform.machine(),
    }

    # Add PyTorch version if available
    try:
        import torch
        software['torch'] = torch.__version__
        if torch.cuda.is_available():
            software['cuda'] = torch.version.cuda
        else:
            software['cuda'] = 'N/A'
    except ImportError:
        software['torch'] = 'N/A'
        software['cuda'] = 'N/A'

    # Add other library versions
    try:
        import numpy
        software['numpy'] = numpy.__version__
    except ImportError:
        software['numpy'] = 'N/A'

    return {
        'cpu': cpu_info,
        'gpus': gpu_info,
        'software': software,
    }


def print_system_info(system_info: Dict[str, Any]):
    """Print system information in a formatted way."""
    print("\n" + "=" * 60)
    print("System Information")
    print("=" * 60)

    cpu = system_info['cpu']
    print(f"\nCPU: {cpu['model']}")
    print(f"  Cores: {cpu['cores']}")
    print(f"  Frequency: {cpu['frequency']}")
    print(f"  Architecture: {cpu['architecture']}")

    gpus = system_info['gpus']
    if gpus:
        print(f"\nGPU(s): {len(gpus)} detected")
        for i, gpu in enumerate(gpus):
            print(f"  [{i}] {gpu['vendor']} {gpu['model']}")
            if gpu['memory_gb'] > 0:
                print(f"      Memory: {gpu['memory_gb']} GB")
            print(f"      Backend: {gpu['backend']}")
            if gpu.get('compute_capability'):
                print(f"      Compute: {gpu['compute_capability']}")
    else:
        print("\nNo GPUs detected")

    software = system_info['software']
    print(f"\nSoftware:")
    print(f"  OS: {software['os']}")
    print(f"  Python: {software['python']}")
    if software.get('torch') != 'N/A':
        print(f"  PyTorch: {software['torch']}")
    if software.get('cuda') != 'N/A':
        print(f"  CUDA: {software['cuda']}")

    print("=" * 60 + "\n")
