from __future__ import annotations

import io
from collections.abc import Sequence
from pathlib import Path

from gce.cli import ExecResult, main


class FakeRunner:
    def __init__(self, responses: dict[tuple[str, ...], ExecResult]) -> None:
        self._responses = responses
        self.commands: list[tuple[str, ...]] = []

    def __call__(self, args: Sequence[str]) -> ExecResult:
        command = tuple(args)
        self.commands.append(command)
        try:
            return self._responses[command]
        except KeyError as error:
            raise AssertionError(f"unexpected command: {command}") from error


def create_artifact(tmp_path: Path) -> Path:
    artifact = tmp_path / "nixos-image-24.11.1-x86_64-linux.raw.tar.gz"
    artifact.write_text("artifact")
    return artifact


def test_build_command_prints_generated_tarball(tmp_path: Path) -> None:
    flake_root = tmp_path / "repo"
    flake_root.mkdir()
    (flake_root / "flake.nix").write_text("{ }")

    output_directory = tmp_path / "out"
    output_directory.mkdir()
    tarball = output_directory / "nixos-image-24.11.1-x86_64-linux.raw.tar.gz"
    tarball.write_text("artifact")

    runner = FakeRunner(
        {
            (
                "nix",
                "build",
                f"path:{flake_root}#gceImage",
                "--no-link",
                "--print-out-paths",
            ): ExecResult(returncode=0, stdout=f"{output_directory}\n"),
        }
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        ["build", "--flake-root", str(flake_root)],
        runner=runner,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert str(tarball) in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_publish_creates_bucket_image_and_authenticated_users_binding(tmp_path: Path) -> None:
    artifact = create_artifact(tmp_path)
    runner = FakeRunner(
        {
            (
                "gcloud",
                "storage",
                "buckets",
                "describe",
                "gs://custom-bucket",
                "--project",
                "demo-project",
            ): ExecResult(returncode=1, stderr="not found"),
            (
                "gcloud",
                "storage",
                "buckets",
                "create",
                "gs://custom-bucket",
                "--project",
                "demo-project",
                "--location",
                "us",
                "--uniform-bucket-level-access",
            ): ExecResult(returncode=0),
            (
                "gcloud",
                "storage",
                "cp",
                str(artifact),
                "gs://custom-bucket/nixos-image-24.11.1-x86_64-linux.raw.tar.gz",
                "--project",
                "demo-project",
            ): ExecResult(returncode=0),
            (
                "gcloud",
                "compute",
                "images",
                "create",
                "nixos-image-24-11-1-x86-64-linux",
                "--project",
                "demo-project",
                "--source-uri",
                "gs://custom-bucket/nixos-image-24.11.1-x86_64-linux.raw.tar.gz",
                "--family",
                "gce-nixos",
            ): ExecResult(returncode=0),
            (
                "gcloud",
                "compute",
                "images",
                "add-iam-policy-binding",
                "nixos-image-24-11-1-x86-64-linux",
                "--project",
                "demo-project",
                "--member",
                "allAuthenticatedUsers",
                "--role",
                "roles/compute.imageUser",
            ): ExecResult(returncode=0),
        }
    )
    stdout = io.StringIO()

    exit_code = main(
        [
            "publish",
            "--project",
            "demo-project",
            "--bucket",
            "custom-bucket",
            "--artifact",
            str(artifact),
        ],
        runner=runner,
        stdout=stdout,
        stderr=io.StringIO(),
    )

    assert exit_code == 0
    assert "Published image: nixos-image-24-11-1-x86-64-linux" in stdout.getvalue()


def test_publish_uses_gcloud_config_project_when_flag_is_missing(tmp_path: Path) -> None:
    artifact = create_artifact(tmp_path)
    bucket_name = "resolved-project-gce-nixos-images"
    runner = FakeRunner(
        {
            ("gcloud", "config", "get-value", "project"): ExecResult(
                returncode=0,
                stdout="resolved-project\n",
            ),
            (
                "gcloud",
                "storage",
                "buckets",
                "describe",
                f"gs://{bucket_name}",
                "--project",
                "resolved-project",
            ): ExecResult(returncode=0),
            (
                "gcloud",
                "storage",
                "cp",
                str(artifact),
                f"gs://{bucket_name}/nixos-image-24.11.1-x86_64-linux.raw.tar.gz",
                "--project",
                "resolved-project",
            ): ExecResult(returncode=0),
            (
                "gcloud",
                "compute",
                "images",
                "create",
                "nixos-image-24-11-1-x86-64-linux",
                "--project",
                "resolved-project",
                "--source-uri",
                f"gs://{bucket_name}/nixos-image-24.11.1-x86_64-linux.raw.tar.gz",
                "--family",
                "gce-nixos",
            ): ExecResult(returncode=0),
            (
                "gcloud",
                "compute",
                "images",
                "add-iam-policy-binding",
                "nixos-image-24-11-1-x86-64-linux",
                "--project",
                "resolved-project",
                "--member",
                "allAuthenticatedUsers",
                "--role",
                "roles/compute.imageUser",
            ): ExecResult(returncode=0),
        }
    )

    exit_code = main(
        ["publish", "--artifact", str(artifact)],
        runner=runner,
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert exit_code == 0


def test_create_instance_uses_repository_defaults_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("GCE_PROJECT", "consumer-project")
    monkeypatch.setenv("GCE_IMAGE_PROJECT", "sandbox-taco")
    monkeypatch.setenv("GCE_IMAGE_FAMILY", "gce-nixos-sandbox")
    monkeypatch.setenv("GCE_DEFAULT_ZONE", "us-central1-a")
    monkeypatch.setenv("GCE_DEFAULT_MACHINE_TYPE", "e2-micro")
    monkeypatch.setenv("GCE_DEFAULT_NETWORK", "default")
    monkeypatch.setenv(
        "GCE_INSTANCE_SERVICE_ACCOUNT",
        "sa-gce-sandbox@sandbox-taco.iam.gserviceaccount.com",
    )
    monkeypatch.setenv("GCE_INSTANCE_TAGS", "http-server")
    monkeypatch.setenv("GCE_INSTANCE_METADATA", "startup-script-url=gs://bucket/script.sh")

    runner = FakeRunner(
        {
            (
                "gcloud",
                "compute",
                "instances",
                "create",
                "demo-vm",
                "--project",
                "consumer-project",
                "--zone",
                "us-central1-a",
                "--machine-type",
                "e2-micro",
                "--network",
                "default",
                "--metadata",
                "enable-oslogin=TRUE,startup-script-url=gs://bucket/script.sh",
                "--tags",
                "http-server",
                "--service-account",
                "sa-gce-sandbox@sandbox-taco.iam.gserviceaccount.com",
                "--scopes",
                "https://www.googleapis.com/auth/cloud-platform",
                "--image-family",
                "gce-nixos-sandbox",
                "--image-project",
                "sandbox-taco",
            ): ExecResult(returncode=0),
        }
    )
    stdout = io.StringIO()

    exit_code = main(
        ["create-instance", "demo-vm"],
        runner=runner,
        stdout=stdout,
        stderr=io.StringIO(),
    )

    assert exit_code == 0
    assert "Created instance: demo-vm" in stdout.getvalue()


def test_create_instance_cli_flags_override_environment_defaults(monkeypatch) -> None:
    monkeypatch.setenv("GCE_PROJECT", "consumer-project")
    monkeypatch.setenv("GCE_IMAGE_PROJECT", "sandbox-taco")
    monkeypatch.setenv("GCE_IMAGE_FAMILY", "gce-nixos-sandbox")
    monkeypatch.setenv("GCE_DEFAULT_ZONE", "us-central1-a")
    monkeypatch.setenv("GCE_DEFAULT_MACHINE_TYPE", "e2-micro")
    monkeypatch.setenv("GCE_DEFAULT_NETWORK", "default")
    monkeypatch.setenv("GCE_INSTANCE_TAGS", "http-server")

    runner = FakeRunner(
        {
            (
                "gcloud",
                "compute",
                "instances",
                "create",
                "demo-vm",
                "--project",
                "alt-project",
                "--zone",
                "asia-northeast1-a",
                "--machine-type",
                "e2-small",
                "--network",
                "custom-network",
                "--metadata",
                "enable-oslogin=TRUE",
                "--tags",
                "web,ssh",
                "--image",
                "custom-image",
                "--image-project",
                "image-project",
            ): ExecResult(returncode=0),
        }
    )

    exit_code = main(
        [
            "create-instance",
            "demo-vm",
            "--project",
            "alt-project",
            "--zone",
            "asia-northeast1-a",
            "--machine-type",
            "e2-small",
            "--network",
            "custom-network",
            "--tags",
            "web,ssh",
            "--image-name",
            "custom-image",
            "--image-project",
            "image-project",
        ],
        runner=runner,
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert exit_code == 0
