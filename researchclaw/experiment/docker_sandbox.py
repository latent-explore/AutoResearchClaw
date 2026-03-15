"""Docker-based sandbox for experiment code execution with GPU passthrough."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from researchclaw.config import DockerSandboxConfig
from researchclaw.experiment.sandbox import SandboxResult, parse_metrics

logger = logging.getLogger(__name__)

_CONTAINER_COUNTER = 0


def _next_container_name() -> str:
    global _CONTAINER_COUNTER  # noqa: PLW0603
    _CONTAINER_COUNTER += 1
    return f"rc-exp-{_CONTAINER_COUNTER}-{os.getpid()}"


class DockerSandbox:
    """Execute experiment code inside a Docker container.

    Same public API as :class:`ExperimentSandbox` so the pipeline can use
    either backend transparently.
    """

    def __init__(self, config: DockerSandboxConfig, workdir: Path) -> None:
        self.config = config
        self.workdir = workdir.resolve()
        self.workdir.mkdir(parents=True, exist_ok=True)
        self._run_counter = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, code: str, *, timeout_sec: int = 300) -> SandboxResult:
        """Run a single Python code string inside a container."""
        self._run_counter += 1
        staging = self.workdir / f"_docker_run_{self._run_counter}"
        staging.mkdir(parents=True, exist_ok=True)

        script_path = staging / "main.py"
        script_path.write_text(code, encoding="utf-8")

        # Inject experiment harness
        self._inject_harness(staging)

        return self._execute(staging, entry_point="main.py", timeout_sec=timeout_sec)

    def run_project(
        self,
        project_dir: Path,
        *,
        entry_point: str = "main.py",
        timeout_sec: int = 300,
    ) -> SandboxResult:
        """Run a multi-file experiment project inside a container."""
        self._run_counter += 1
        staging = self.workdir / f"_docker_project_{self._run_counter}"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True, exist_ok=True)

        # Inject harness first (immutable)
        self._inject_harness(staging)

        # Copy project files (skip harness overwrite)
        for src_file in project_dir.iterdir():
            if src_file.is_file():
                dest = staging / src_file.name
                if dest.name == "experiment_harness.py":
                    logger.warning(
                        "Project contains experiment_harness.py — skipping (immutable)"
                    )
                    continue
                dest.write_bytes(src_file.read_bytes())

        entry = staging / entry_point
        if not entry.exists():
            return SandboxResult(
                returncode=-1,
                stdout="",
                stderr=f"Entry point {entry_point} not found in project",
                elapsed_sec=0.0,
                metrics={},
            )

        return self._execute(staging, entry_point=entry_point, timeout_sec=timeout_sec)

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def check_docker_available() -> bool:
        """Return True if the Docker daemon is reachable."""
        try:
            cp = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=10,
                check=False,
            )
            return cp.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    @staticmethod
    def check_nvidia_runtime() -> bool:
        """Return True if the NVIDIA Container Toolkit is available."""
        try:
            cp = subprocess.run(
                ["docker", "run", "--rm", "--gpus", "all",
                 "nvidia/cuda:12.4.1-cudnn-devel-ubuntu22.04",
                 "nvidia-smi"],
                capture_output=True,
                timeout=30,
                check=False,
            )
            return cp.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    @staticmethod
    def ensure_image(image: str) -> bool:
        """Return True if *image* exists locally (does NOT pull)."""
        try:
            cp = subprocess.run(
                ["docker", "image", "inspect", image],
                capture_output=True,
                timeout=10,
                check=False,
            )
            return cp.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    @staticmethod
    def _inject_harness(target_dir: Path) -> None:
        harness_src = Path(__file__).parent / "harness_template.py"
        if harness_src.exists():
            dest = target_dir / "experiment_harness.py"
            dest.write_text(harness_src.read_text(encoding="utf-8"), encoding="utf-8")
            logger.debug("Injected experiment harness into %s", target_dir)
        else:
            logger.warning("Harness template not found at %s", harness_src)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _execute(
        self, staging_dir: Path, *, entry_point: str, timeout_sec: int
    ) -> SandboxResult:
        """Core execution: build docker command, run, collect results."""
        cfg = self.config
        container_name = _next_container_name()

        # Phase 1: install pip dependencies (if pip_only network)
        if cfg.network_policy == "pip_only" and (
            cfg.pip_pre_install or cfg.auto_install_deps
        ):
            self._install_deps(staging_dir, container_name + "-deps")

        # Phase 2: run the experiment
        cmd = self._build_run_command(
            staging_dir,
            entry_point=entry_point,
            container_name=container_name,
            network_disabled=(cfg.network_policy != "full"),
        )

        start = time.monotonic()
        timed_out = False
        try:
            logger.debug("Docker run command: %s", cmd)
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                check=False,
            )
            stdout = completed.stdout
            stderr = completed.stderr
            returncode = completed.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            returncode = -1
            # Force-kill the container on timeout
            self._kill_container(container_name)
        except Exception as exc:  # noqa: BLE001
            elapsed = time.monotonic() - start
            return SandboxResult(
                returncode=-1,
                stdout="",
                stderr=f"Docker execution error: {exc}",
                elapsed_sec=elapsed,
                metrics={},
            )

        elapsed = time.monotonic() - start

        # Cleanup container (unless keep_containers is set)
        if not cfg.keep_containers:
            self._remove_container(container_name)

        # Parse metrics from stdout
        metrics = parse_metrics(stdout)

        # Try to read structured results.json from staging dir (volume-mounted)
        results_json_path = staging_dir / "results.json"
        if results_json_path.exists():
            try:
                structured = json.loads(
                    results_json_path.read_text(encoding="utf-8")
                )
                if isinstance(structured, dict):
                    for k, v in structured.items():
                        if k not in metrics:
                            try:
                                metrics[k] = float(v)
                            except (TypeError, ValueError):
                                pass
            except (json.JSONDecodeError, OSError):
                pass

        return SandboxResult(
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            elapsed_sec=elapsed,
            metrics=metrics,
            timed_out=timed_out,
        )

    def _build_run_command(
        self,
        staging_dir: Path,
        *,
        entry_point: str,
        container_name: str,
        network_disabled: bool,
    ) -> list[str]:
        """Build the ``docker run`` command list."""
        cfg = self.config
        cmd = [
            "docker", "run",
            "--name", container_name,
            "--rm",
            "--user", f"{os.getuid()}:{os.getgid()}",
            "-v", f"{staging_dir}:/workspace",
            "-w", "/workspace",
            f"--memory={cfg.memory_limit_mb}m",
            f"--shm-size={cfg.shm_size_mb}m",
        ]

        # Mount pre-cached datasets (read-only)
        datasets_host = Path("/opt/datasets")
        if datasets_host.is_dir():
            cmd.extend(["-v", "/opt/datasets:/workspace/data:ro"])

        # Mount HuggingFace model cache (read-write for downloading)
        hf_cache_host = Path.home() / ".cache" / "huggingface"
        if hf_cache_host.is_dir():
            cmd.extend(["-v", f"{hf_cache_host}:/home/researcher/.cache/huggingface"])
            cmd.extend(["-e", f"HF_HOME=/home/researcher/.cache/huggingface"])
        # Also check XDG cache
        xdg_hf = Path(os.environ.get("HF_HOME", ""))
        if xdg_hf.is_dir() and xdg_hf != hf_cache_host:
            cmd.extend(["-v", f"{xdg_hf}:/home/researcher/.cache/huggingface"])
            cmd.extend(["-e", f"HF_HOME=/home/researcher/.cache/huggingface"])

        # Pass HF token if available (for gated model downloads)
        hf_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
        if hf_token:
            cmd.extend(["-e", f"HF_TOKEN={hf_token}"])

        # GPU passthrough
        if cfg.gpu_enabled:
            if cfg.gpu_device_ids:
                device_spec = ",".join(str(d) for d in cfg.gpu_device_ids)
                cmd.extend(["--gpus", f'"device={device_spec}"'])
            else:
                cmd.extend(["--gpus", "all"])

        # Network isolation
        if network_disabled:
            cmd.extend(["--network", "none"])

        # Image and entry point script (ENTRYPOINT is "python3 -u")
        cmd.append(cfg.image)
        cmd.append(f"/workspace/{entry_point}")

        return cmd

    def _install_deps(self, staging_dir: Path, container_name: str) -> None:
        """Phase 1: install pip dependencies with network access."""
        cfg = self.config

        # Collect packages to install
        packages: list[str] = list(cfg.pip_pre_install)

        # Auto-detect imports from Python files
        if cfg.auto_install_deps:
            detected = self._detect_pip_packages(staging_dir)
            packages.extend(p for p in detected if p not in packages)

        if not packages:
            return

        pip_cmd = f"pip install --no-cache-dir --break-system-packages {' '.join(packages)}"
        cmd = [
            "docker", "run",
            "--name", container_name,
            "--rm",
            "-v", f"{staging_dir}:/workspace",
            "-w", "/workspace",
            f"--memory={cfg.memory_limit_mb}m",
        ]
        # GPU not needed for pip install; override ENTRYPOINT for shell command
        # Run as root for pip install, not host UID
        cmd.extend(["--entrypoint", "bash", cfg.image, "-c", pip_cmd])

        logger.info("Docker pip install: %s", packages)
        try:
            cp = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120, check=False
            )
            if cp.returncode != 0:
                logger.warning("pip install failed: %s", cp.stderr[:500])
        except subprocess.TimeoutExpired:
            logger.warning("pip install timed out")
            self._kill_container(container_name)

    @staticmethod
    def _detect_pip_packages(staging_dir: Path) -> list[str]:
        """Scan Python files for import statements and return pip package names."""
        # Map common import names to pip package names
        import_to_pip = {
            "torchdiffeq": "torchdiffeq",
            "torch_geometric": "torch-geometric",
            "torchvision": "torchvision",
            "torchaudio": "torchaudio",
            "cv2": "opencv-python",
            "PIL": "Pillow",
            "sklearn": "scikit-learn",
            "yaml": "PyYAML",
            "gym": "gymnasium",
        }
        # Packages already in the Docker image — skip these
        builtin = {
            "torch", "numpy", "scipy", "sklearn", "pandas", "matplotlib",
            "seaborn", "tqdm", "gymnasium", "networkx", "torchdiffeq",
            "torchvision", "torchaudio", "yaml",
            # stdlib
            "os", "sys", "math", "random", "json", "csv", "re", "time",
            "collections", "itertools", "functools", "pathlib", "typing",
            "dataclasses", "abc", "copy", "io", "logging", "argparse",
            "datetime", "hashlib", "pickle", "subprocess", "shutil",
            "tempfile", "warnings", "unittest", "contextlib", "operator",
            "string", "textwrap", "struct", "statistics",
        }

        import_re = re.compile(
            r"^\s*(?:import|from)\s+([\w.]+)", re.MULTILINE
        )
        detected: list[str] = []
        for pyf in staging_dir.glob("*.py"):
            text = pyf.read_text(encoding="utf-8", errors="replace")
            for m in import_re.finditer(text):
                top_module = m.group(1).split(".")[0]
                if top_module in builtin:
                    continue
                pip_name = import_to_pip.get(top_module, top_module)
                if pip_name not in detected:
                    detected.append(pip_name)

        return detected

    @staticmethod
    def _kill_container(name: str) -> None:
        try:
            subprocess.run(
                ["docker", "kill", name],
                capture_output=True,
                timeout=10,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    @staticmethod
    def _remove_container(name: str) -> None:
        try:
            subprocess.run(
                ["docker", "rm", "-f", name],
                capture_output=True,
                timeout=10,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
