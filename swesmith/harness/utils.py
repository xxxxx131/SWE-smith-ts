import docker
import fnmatch
import re
import subprocess
import traceback
import uuid

from concurrent.futures import ThreadPoolExecutor, as_completed
from docker.models.containers import Container
from logging import Logger
from pathlib import Path
from urllib3.response import HTTPResponse as Urllib3HTTPResponse
from urllib.parse import urlparse, urlunparse
from swebench.harness.constants import (
    APPLY_PATCH_FAIL,
    APPLY_PATCH_PASS,
    DOCKER_PATCH,
    DOCKER_USER,
    DOCKER_WORKDIR,
    KEY_INSTANCE_ID,
    LOG_INSTANCE,
    LOG_TEST_OUTPUT,
    RUN_EVALUATION_LOG_DIR,
    TESTS_TIMEOUT,
    UTF8,
)
from swebench.harness.docker_build import setup_logger
from swebench.harness.docker_utils import (
    cleanup_container,
    copy_to_container,
    exec_run_with_timeout,
)
from swebench.harness.utils import EvaluationError
from swesmith.constants import (
    GIT_APPLY_CMDS,
    LOG_DIR_RUN_VALIDATION,
    TEST_OUTPUT_END,
    TEST_OUTPUT_START,
)
from swesmith.profiles import registry
from unidiff import PatchSet

SUBPROCESS_DEVNULL = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
_ORIG_URLLIB3_HTTPRESPONSE_CLOSE = Urllib3HTTPResponse.close
_URLLIB3_CLOSE_PATCHED = False


def _patch_urllib3_httpresponse_close() -> None:
    """
    Suppress urllib3/python3.13 double-close noise:
    ValueError: I/O operation on closed file.

    This happens in finalizers after response streams are already closed.
    We only swallow this specific benign ValueError.
    """
    global _URLLIB3_CLOSE_PATCHED
    if _URLLIB3_CLOSE_PATCHED:
        return

    def _safe_close(self):
        try:
            return _ORIG_URLLIB3_HTTPRESPONSE_CLOSE(self)
        except ValueError as exc:
            if "I/O operation on closed file" in str(exc):
                return None
            raise

    Urllib3HTTPResponse.close = _safe_close
    _URLLIB3_CLOSE_PATCHED = True


_patch_urllib3_httpresponse_close()


def matches_instance_filter(instance_id: str, instance_ids: list[str] | None) -> bool:
    """
    Check if an instance_id matches the filtering criteria.

    Args:
        instance_id: The instance ID to check
        instance_ids: List of instance IDs or patterns to match against

    Returns:
        True if the instance should be included, False otherwise
    """
    if instance_ids is None:
        return True

    for filter_item in instance_ids:
        # Check for exact match first
        if instance_id == filter_item:
            return True

        # Check for pattern match (supports * and ? wildcards)
        if fnmatch.fnmatch(instance_id, filter_item):
            return True

    return False


def _get_bridge_gateway(client: docker.DockerClient) -> str | None:
    """Return docker bridge gateway IP (e.g. 172.17.0.1) when available."""
    try:
        net = client.networks.get("bridge")
        ipam = net.attrs.get("IPAM", {}).get("Config", [])
        if ipam and isinstance(ipam, list):
            gateway = ipam[0].get("Gateway")
            if gateway:
                return str(gateway)
    except Exception:
        pass
    return None


def _rewrite_proxy_url_for_container(url: str, gateway_ip: str | None) -> str:
    """Rewrite localhost proxy URLs to docker bridge gateway for container reachability."""
    if not gateway_ip:
        return url
    try:
        parsed = urlparse(url)
    except Exception:
        return url

    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        return url

    auth = ""
    if parsed.username:
        auth = parsed.username
        if parsed.password:
            auth += f":{parsed.password}"
        auth += "@"
    port = f":{parsed.port}" if parsed.port else ""
    netloc = f"{auth}{gateway_ip}{port}"
    return urlunparse(parsed._replace(netloc=netloc))


def _build_container_proxy_env(client: docker.DockerClient) -> dict[str, str]:
    """Collect proxy env from host and adapt it for docker containers."""
    import os

    proxy_keys = [
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "NO_PROXY",
        "no_proxy",
    ]
    gateway_ip = _get_bridge_gateway(client)
    env = {}
    for key in proxy_keys:
        val = os.getenv(key)
        if not val:
            continue
        if key.lower().endswith("_proxy") and not key.lower().startswith("no_"):
            env[key] = _rewrite_proxy_url_for_container(val, gateway_ip)
        else:
            env[key] = val
    return env


def _looks_like_test_file(path: str) -> bool:
    """Heuristic for identifying test-related files in a commit diff."""
    normalized = "/" + path.replace("\\", "/").lower().strip("/")
    if any(
        marker in normalized
        for marker in ("/test/", "/tests/", "/spec/", "/specs/", "/__tests__/")
    ):
        return True
    return normalized.endswith(
        (
            ".test.js",
            ".test.jsx",
            ".test.ts",
            ".test.tsx",
            ".spec.js",
            ".spec.jsx",
            ".spec.ts",
            ".spec.tsx",
            "_test.py",
            "_test.go",
        )
    )


def _should_checkout_head_parent_for_eval(container: Container, logger: Logger) -> bool:
    """
    Decide whether eval should checkout HEAD~1.

    Legacy SWE-smith assumption: branch tip is a test-removal commit on top of the
    bug-introducing commit. For newer datasets this is not always true. We only
    checkout HEAD~1 when the top commit appears to be test-only changes.
    """
    import os

    force_setting = os.getenv("SWESMITH_EVAL_CHECKOUT_HEAD_PARENT", "").strip().lower()
    if force_setting in {"1", "true", "yes", "y"}:
        logger.info(
            "Forcing HEAD~1 checkout because SWESMITH_EVAL_CHECKOUT_HEAD_PARENT is enabled."
        )
        return True
    if force_setting in {"0", "false", "no", "n"}:
        logger.info(
            "Skipping HEAD~1 checkout because SWESMITH_EVAL_CHECKOUT_HEAD_PARENT is disabled."
        )
        return False

    has_parent = container.exec_run(
        "git rev-parse --verify HEAD~1", workdir=DOCKER_WORKDIR, user=DOCKER_USER
    )
    if has_parent.exit_code != 0:
        logger.info("Skipping HEAD~1 checkout: branch has no parent commit.")
        return False

    diff_val = container.exec_run(
        "git diff --name-only HEAD~1 HEAD",
        workdir=DOCKER_WORKDIR,
        user=DOCKER_USER,
    )
    if diff_val.exit_code != 0:
        logger.info(
            "Unable to inspect HEAD diff; falling back to legacy HEAD~1 checkout behavior."
        )
        return True

    changed_files = [
        line.strip()
        for line in diff_val.output.decode(UTF8, errors="ignore").splitlines()
        if line.strip()
    ]
    if not changed_files:
        logger.info("Skipping HEAD~1 checkout: top commit has no file changes.")
        return False

    test_like_files = [path for path in changed_files if _looks_like_test_file(path)]
    should_checkout = len(test_like_files) == len(changed_files)
    if should_checkout:
        logger.info(
            "Checking out HEAD~1 for eval: top commit appears to be test-only changes."
        )
    else:
        logger.info(
            "Skipping HEAD~1 checkout: top commit is not test-only "
            f"({len(test_like_files)}/{len(changed_files)} test-like files)."
        )
    return should_checkout


def _is_jest_oom_like_failure(output: str) -> bool:
    """Detect common Jest worker OOM/SIGKILL failures in test logs."""
    lower = output.lower()
    if "jest" not in lower:
        return False
    patterns = (
        "jest worker process",
        "signal=sigkill",
        "was terminated by another process",
        "javascript heap out of memory",
        "reached heap limit allocation failed",
        "allocation failed - javascript heap out of memory",
    )
    return any(p in lower for p in patterns)


def _is_test_wrapper_command(lower_segment: str) -> bool:
    """Detect common npm/yarn/pnpm test wrapper commands."""
    return bool(
        re.search(r"\b(?:npm|pnpm)\s+(?:run\s+)?test(?:\b|:)", lower_segment)
        or re.search(r"\byarn\s+(?:run\s+)?test(?:\b|:)", lower_segment)
    )


def _add_jest_safety_flags(segment: str, *, force_for_test_wrappers: bool = False) -> str:
    """
    Add safer Jest settings to a shell segment.

    - Force single-worker execution: --runInBand --maxWorkers=1
    - Add Node memory cap when NODE_OPTIONS is not set.
    """
    seg = segment.strip()
    lower = seg.lower()
    is_jest_like = "jest" in lower or (
        force_for_test_wrappers and _is_test_wrapper_command(lower)
    )
    if not is_jest_like:
        return seg

    # Add memory guard only when command does not already define NODE_OPTIONS.
    if "node_options=" not in lower:
        seg = f"NODE_OPTIONS=--max-old-space-size=4096 {seg}"
        lower = seg.lower()

    extras: list[str] = []
    if "--runinband" not in lower:
        extras.append("--runInBand")
    if "--maxworkers" not in lower:
        extras.append("--maxWorkers=1")
    if not extras:
        return seg

    # npm/pnpm need `--` to pass args to underlying script when not already present.
    if re.search(r"\b(?:npm|pnpm)\s+run\s+\S+", seg):
        if " -- " in seg or seg.endswith(" --"):
            return f"{seg} {' '.join(extras)}"
        return f"{seg} -- {' '.join(extras)}"
    return f"{seg} {' '.join(extras)}"


def _build_jest_safe_retry_command(test_command: str) -> str | None:
    """Build a safer retry command for Jest-heavy test runs."""
    # Preserve chaining operators while patching each command segment independently.
    parts = re.split(r"(\s*(?:&&|\|\||;)\s*)", test_command)
    changed = False
    for i in range(0, len(parts), 2):
        original = parts[i]
        updated = _add_jest_safety_flags(original, force_for_test_wrappers=True)
        if updated != original.strip():
            changed = True
        parts[i] = updated

    if not changed:
        return None
    return "".join(parts).strip()


def _apply_patch(
    instance_id: str, container: Container, logger: Logger, is_gold: bool = False
):
    """
    Apply a patch to a container's codebase
    """
    apply_succeeded = False
    for git_apply_cmd in GIT_APPLY_CMDS:
        # Because gold patches = bug patches, so fix = revert
        git_apply_cmd = (
            f"{git_apply_cmd} {DOCKER_PATCH}"
            if not is_gold
            else f"{git_apply_cmd} --reverse {DOCKER_PATCH}"
        )
        val = container.exec_run(
            git_apply_cmd, workdir=DOCKER_WORKDIR, user=DOCKER_USER
        )
        if val.exit_code == 0:
            apply_succeeded = True
            logger.info(f"{APPLY_PATCH_PASS}:\n{val.output.decode(UTF8)}")
            break
        logger.info(
            f"Failed to apply patch to container with {git_apply_cmd}.\n"
            + f"Error Message: {val.output.decode(UTF8)}\nTrying again..."
        )
    if not apply_succeeded:
        apply_failed_msg = f"{APPLY_PATCH_FAIL}:\n{val.output.decode(UTF8)}"
        logger.info(apply_failed_msg)
        raise EvaluationError(instance_id, apply_failed_msg, logger)


def _pull_image_name(image_name: str, logger: Logger | None) -> None:
    """Ensure docker image is available locally, pulling if needed."""
    if not image_name:
        raise RuntimeError("No docker image name provided for validation.")

    inspected = subprocess.run(
        ["docker", "image", "inspect", image_name],
        check=False,
        **SUBPROCESS_DEVNULL,
    )
    if inspected.returncode == 0:
        return

    pull = subprocess.run(
        ["docker", "pull", image_name],
        check=False,
        capture_output=True,
        text=True,
    )
    if pull.returncode != 0:
        hint = (
            "If this image is in a custom Docker org, ensure patches JSON has `image_name` "
            "or export SWESMITH_ORG_DH before running validation."
        )
        message = (
            f"Failed to pull Docker image {image_name}: "
            f"{pull.stderr.strip() or pull.stdout.strip()}\n{hint}"
        )
        if logger is not None:
            logger.info(message)
        raise RuntimeError(message)


def run_patch_in_container(
    instance: dict,
    run_id: str,
    log_dir: Path,
    timeout: int,
    patch: str | None = None,
    commit: str | None = None,
    f2p_only: bool = False,
    is_gold: bool = False,
) -> tuple[Logger, bool] | None:
    """
    Run a patch in a container. The general logical flow is as follows:
    1. Setup logging directory
    2. Start docker container
    3. Copy patch to container, if provided
        a. Apply patch to codebase
    4. Copy eval script to container
    5. Run eval script, write outputs to logs

    Returns:
        tuple[Logger, bool]: logger and whether the container timed out or None if an error occurred
    """
    container = None
    logger: Logger | None = None
    client = docker.from_env()
    proxy_env = _build_container_proxy_env(client)
    instance_id = instance[KEY_INSTANCE_ID]
    rp = registry.get_from_inst(instance)
    image_name = instance.get("image_name") or rp.image_name
    is_eval = log_dir == RUN_EVALUATION_LOG_DIR
    try:
        container_type = None
        if is_eval:
            container_type = "eval"
        elif log_dir == LOG_DIR_RUN_VALIDATION:
            container_type = "val"

        # Setup logging directory
        log_dir = log_dir / run_id / instance_id
        log_dir.mkdir(parents=True, exist_ok=True)
        test_output_path = log_dir / LOG_TEST_OUTPUT
        # Avoid stale outputs from previous runs causing false-positive grading.
        if test_output_path.exists():
            test_output_path.unlink()
        # Add a short random suffix to avoid name collisions when rerunning
        # the same run_id after interrupted/failed evaluations.
        container_name = f"swesmith.{container_type}.{run_id}.{instance_id}.{uuid.uuid4().hex[:8]}"
        log_file = log_dir / LOG_INSTANCE
        logger = setup_logger(container_name, log_file)

        # Start docker container
        _pull_image_name(image_name, logger)
        container = client.containers.create(
            image=image_name,
            name=container_name,
            user=DOCKER_USER,
            detach=True,
            command="tail -f /dev/null",
            platform="linux/x86_64",
            mem_limit="10g",
            environment=proxy_env if proxy_env else None,
        )
        container.start()

        # If provided, checkout commit in container
        if commit is not None:
            logger.info(f"Checking out commit {commit}")
            val_fetch = container.exec_run("git fetch", workdir=DOCKER_WORKDIR, user=DOCKER_USER)
            if val_fetch.exit_code != 0:
                logger.info(f"FETCH FAILED: {val_fetch.output.decode(UTF8)}")
                return logger, False
            val = container.exec_run(
                f"git checkout {commit}", workdir=DOCKER_WORKDIR, user=DOCKER_USER
            )
            if val.exit_code != 0:
                logger.info(f"CHECKOUT FAILED: {val.output.decode(UTF8)}")
                return logger, False
            if is_eval:
                if _should_checkout_head_parent_for_eval(container, logger):
                    val = container.exec_run(
                        "git checkout HEAD~1", workdir=DOCKER_WORKDIR, user=DOCKER_USER
                    )
                    if val.exit_code != 0:
                        logger.info(
                            f"CHECKOUT TO BUG STAGE FAILED: {val.output.decode(UTF8)}"
                        )
                        return logger, False

        # If provided, copy patch to container and apply it to codebase
        if patch is not None and len(patch) >= 1:
            logger.info("Applying patch to container...")

            # Revert any changes to those files in the container to ensure a clean state
            changed_files = " ".join([x.path for x in PatchSet(patch)])
            container.exec_run(
                f"git checkout -- {changed_files}",
                workdir=DOCKER_WORKDIR,
                user=DOCKER_USER,
            )

            # Apply the patch inside the container
            patch_file = Path(log_dir / "patch.diff")
            patch_file.write_text(patch)
            logger.info(f"Patch written to {patch_file}, now applying to container...")
            copy_to_container(container, patch_file, Path(DOCKER_PATCH))
            _apply_patch(instance_id, container, logger, is_gold)

            if is_eval:
                # For evaluation, removes any changes to test related files.
                f2p_files, p2p_files = rp.get_test_files(instance)
                test_files = " ".join(f2p_files + p2p_files)
                if test_files:
                    container.exec_run(
                        f"git checkout -- {test_files}",
                        workdir=DOCKER_WORKDIR,
                        user=DOCKER_USER,
                    )
                    logger.info(
                        f"Reverted changes to test files in container: {test_files}"
                    )

        # Copy eval script to container
        eval_file = Path(log_dir / "eval.sh")
        test_command, _ = rp.get_test_cmd(instance, f2p_only=f2p_only)
        eval_file.write_text(
            "\n".join(
                [
                    "#!/bin/bash",
                    "set -uxo pipefail",
                    f"cd {DOCKER_WORKDIR}",
                    f": '{TEST_OUTPUT_START}'",
                    test_command,
                    f": '{TEST_OUTPUT_END}'",
                ]
            )
            + "\n"
        )
        copy_to_container(container, eval_file, Path("/eval.sh"))

        # Run eval script, write outputs to logs
        test_output, timed_out, total_runtime = exec_run_with_timeout(
            container, "/bin/bash /eval.sh", timeout=timeout
        )
        final_timeout = timeout

        # Generic safeguard: if Jest workers are OOM-killed, retry once with
        # serial worker mode and a Node heap cap to avoid repeated SIGKILL.
        if not timed_out and _is_jest_oom_like_failure(test_output):
            retry_command = _build_jest_safe_retry_command(test_command)
            if retry_command and retry_command != test_command:
                logger.info(
                    "Detected Jest OOM/SIGKILL pattern. Retrying once with safer Jest settings."
                )
                retry_file = Path(log_dir / "eval.retry_jest_safe.sh")
                retry_file.write_text(
                    "\n".join(
                        [
                            "#!/bin/bash",
                            "set -uxo pipefail",
                            f"cd {DOCKER_WORKDIR}",
                            f": '{TEST_OUTPUT_START}'",
                            retry_command,
                            f": '{TEST_OUTPUT_END}'",
                        ]
                    )
                    + "\n"
                )
                copy_to_container(container, retry_file, Path("/eval.retry_jest_safe.sh"))
                retry_timeout = max(timeout, int(timeout * 2))
                retry_output, retry_timed_out, retry_runtime = exec_run_with_timeout(
                    container,
                    "/bin/bash /eval.retry_jest_safe.sh",
                    timeout=retry_timeout,
                )
                logger.info(
                    f"Jest-safe retry runtime: {retry_runtime:_.2f} seconds "
                    f"(timeout={retry_timeout}s)"
                )
                test_output = (
                    test_output
                    + "\n\n[SWESMITH RETRY] Detected Jest worker OOM/SIGKILL. "
                    + "Re-ran tests with NODE_OPTIONS=--max-old-space-size=4096 "
                    + "and Jest single-worker flags.\n\n"
                    + retry_output
                )
                timed_out = retry_timed_out
                total_runtime += retry_runtime
                final_timeout = retry_timeout

        test_output_path = log_dir / LOG_TEST_OUTPUT
        logger.info(f"Test Runtime: {total_runtime:_.2f} seconds")
        with open(test_output_path, "w") as f:
            f.write(test_output)
            if timed_out:
                timeout_error = f"{TESTS_TIMEOUT}: {final_timeout} seconds exceeded"
                f.write(f"\n\n{timeout_error}")

        logger.info(f"Test output for {instance_id} written to {test_output_path}")
        return logger, timed_out
    except Exception as e:
        log_file_hint = getattr(logger, "log_file", "unknown")
        error_msg = (
            f"Error validating {instance_id}: {e}\n"
            f"{traceback.format_exc()}\n"
            f"Check ({log_file_hint}) for more information."
        )
        if logger is not None:
            logger.info(error_msg)
        print(f"Error validating {instance_id}: {e}")
        return logger, False
    finally:
        # Always attempt cleanup and close docker client/session handles.
        cleanup_container(client, container, logger)
        try:
            client.close()
        except Exception:
            pass


def run_threadpool(func, payloads, max_workers):
    """
    Run a function with a list of payloads using ThreadPoolExecutor.

    Args:
        func: Function to run for each payload
        payloads: List of payloads to process
        max_workers: Maximum number of worker threads

    Returns:
        tuple: (succeeded, failed) lists of payloads
    """
    if max_workers <= 0:
        return run_sequential(func, payloads)

    succeeded, failed = [], []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Create a future for running each instance
        futures = {executor.submit(func, *payload): payload for payload in payloads}
        # Wait for each future to complete
        for future in as_completed(futures):
            try:
                # Check if instance ran successfully
                future.result()
                succeeded.append(futures[future])
            except Exception as e:
                print(f"{type(e)}: {e}")
                traceback.print_exc()
                failed.append(futures[future])

    return succeeded, failed


def run_sequential(func, payloads):
    """
    Run a function with a list of payloads sequentially.

    Args:
        func: Function to run for each payload
        payloads: List of payloads to process

    Returns:
        tuple: (succeeded, failed) lists of payloads
    """
    succeeded, failed = [], []
    for payload in payloads:
        try:
            func(*payload)
            succeeded.append(payload)
        except Exception:
            traceback.print_exc()
            failed.append(payload)

    return succeeded, failed
