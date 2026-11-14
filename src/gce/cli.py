from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TextIO

DEFAULT_FLAKE_ATTR = "gceImage"
DEFAULT_IMAGE_FAMILY = "gce-nixos"
DEFAULT_BUCKET_SUFFIX = "-gce-nixos-images"
DEFAULT_BUCKET_LOCATION = "us"
AUTHENTICATED_USERS_MEMBER = "allAuthenticatedUsers"
IMAGE_USER_ROLE = "roles/compute.imageUser"
PROJECT_ENV_VARS = (
    "GCE_PROJECT",
    "GOOGLE_CLOUD_PROJECT",
    "GCLOUD_PROJECT",
    "CLOUDSDK_CORE_PROJECT",
)
BUCKET_ENV_VARS = (
    "GCE_BUCKET",
    "GCE_IMAGE_BUCKET",
)
IMAGE_FAMILY_ENV_VARS = ("GCE_IMAGE_FAMILY",)
IMAGE_NAME_ENV_VARS = ("GCE_IMAGE_NAME",)
IMAGE_PROJECT_ENV_VARS = ("GCE_IMAGE_PROJECT",)
ZONE_ENV_VARS = ("GCE_DEFAULT_ZONE", "CLOUDSDK_COMPUTE_ZONE")
MACHINE_TYPE_ENV_VARS = ("GCE_DEFAULT_MACHINE_TYPE",)
NETWORK_ENV_VARS = ("GCE_DEFAULT_NETWORK",)
SERVICE_ACCOUNT_ENV_VARS = ("GCE_INSTANCE_SERVICE_ACCOUNT",)
INSTANCE_TAGS_ENV_VARS = ("GCE_INSTANCE_TAGS",)
INSTANCE_METADATA_ENV_VARS = ("GCE_INSTANCE_METADATA",)
DEFAULT_MACHINE_TYPE = "e2-micro"
DEFAULT_NETWORK = "default"
DEFAULT_INSTANCE_TAGS = ("http-server",)


class CliError(RuntimeError):
    """Raised when command execution or input validation fails."""


@dataclass(frozen=True)
class ExecResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class Runner(Protocol):
    def __call__(self, args: Sequence[str]) -> ExecResult: ...


@dataclass(frozen=True)
class Artifact:
    directory: Path
    tarball: Path


def default_runner(args: Sequence[str]) -> ExecResult:
    completed = subprocess.run(
        list(args),
        check=False,
        capture_output=True,
        text=True,
    )
    return ExecResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


class Shell:
    def __init__(
        self,
        *,
        runner: Runner,
        stdout: TextIO,
        dry_run: bool = False,
    ) -> None:
        self._runner = runner
        self._stdout = stdout
        self._dry_run = dry_run

    @property
    def dry_run(self) -> bool:
        return self._dry_run

    def run(self, args: Sequence[str], *, check: bool = True) -> ExecResult:
        print(f"$ {format_command(args)}", file=self._stdout)
        if self._dry_run:
            return ExecResult(returncode=0)

        result = self._runner(args)
        if check or result.returncode == 0:
            return ensure_success(args, result)
        return result


def ensure_success(args: Sequence[str], result: ExecResult) -> ExecResult:
    if result.returncode == 0:
        return result

    detail = result.stderr.strip() or result.stdout.strip() or "command failed"
    raise CliError(f"{format_command(args)}: {detail}")


def format_command(args: Sequence[str]) -> str:
    return " ".join(shlex.quote(part) for part in args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gce",
        description="Build and publish a NixOS image for Google Compute Engine.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser_ = subparsers.add_parser(
        "build",
        help="Build the local GCE-compatible NixOS image tarball.",
    )
    add_common_build_args(build_parser_)
    build_parser_.set_defaults(handler=handle_build)

    publish_parser = subparsers.add_parser(
        "publish",
        help="Build, upload, create the GCE image, and share it with authenticated users.",
    )
    add_common_build_args(publish_parser)
    publish_parser.add_argument(
        "--artifact",
        type=Path,
        help="Path to an existing .raw.tar.gz artifact. Skips nix build when supplied.",
    )
    publish_parser.add_argument(
        "--project",
        help="Target Google Cloud project ID. Falls back to environment or gcloud config.",
    )
    publish_parser.add_argument(
        "--bucket",
        help=(
            "Cloud Storage bucket name. Defaults to " "<project-id>-gce-nixos-images if omitted."
        ),
    )
    publish_parser.add_argument(
        "--bucket-location",
        default=DEFAULT_BUCKET_LOCATION,
        help=f"Location used when creating the bucket. Default: {DEFAULT_BUCKET_LOCATION}.",
    )
    publish_parser.add_argument(
        "--image-name",
        help="Custom Compute Engine image name. Defaults to a sanitized artifact-derived name.",
    )
    publish_parser.add_argument(
        "--object-name",
        help="Cloud Storage object name. Defaults to the local tarball filename.",
    )
    publish_parser.add_argument(
        "--family",
        help=f"Compute Engine image family. Default: {DEFAULT_IMAGE_FAMILY}.",
    )
    publish_parser.add_argument(
        "--description",
        help="Optional image description passed to gcloud.",
    )
    publish_parser.add_argument(
        "--label",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Repeatable label assignment for the created image.",
    )
    publish_parser.add_argument(
        "--storage-location",
        help="Optional Compute Engine image storage location, such as us or us-central1.",
    )
    publish_parser.add_argument(
        "--replace-existing",
        action="store_true",
        help="Delete an existing image with the same name before re-creating it.",
    )
    publish_parser.add_argument(
        "--share-with-authenticated-users",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Grant roles/compute.imageUser to allAuthenticatedUsers after creation. "
            "Enabled by default."
        ),
    )
    publish_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the commands that would run without modifying local or cloud state.",
    )
    publish_parser.set_defaults(handler=handle_publish)

    create_instance_parser = subparsers.add_parser(
        "create-instance",
        help="Create a Compute Engine VM from the published image.",
    )
    create_instance_parser.add_argument("name", help="Compute Engine instance name.")
    create_instance_parser.add_argument(
        "--project",
        help=(
            "Target Google Cloud project ID for the instance. Falls back to "
            "GCE_PROJECT, GOOGLE_CLOUD_PROJECT, GCLOUD_PROJECT, "
            "CLOUDSDK_CORE_PROJECT, then gcloud config."
        ),
    )
    create_instance_parser.add_argument(
        "--zone",
        help=("Target zone. Defaults to GCE_DEFAULT_ZONE or CLOUDSDK_COMPUTE_ZONE."),
    )
    create_instance_parser.add_argument(
        "--machine-type",
        help=("Machine type. Defaults to GCE_DEFAULT_MACHINE_TYPE or " f"{DEFAULT_MACHINE_TYPE}."),
    )
    create_instance_parser.add_argument(
        "--image-project",
        help="Project that owns the source image. Defaults to GCE_IMAGE_PROJECT or --project.",
    )
    create_instance_parser.add_argument(
        "--image-family",
        help="Source image family. Defaults to GCE_IMAGE_FAMILY.",
    )
    create_instance_parser.add_argument(
        "--image-name",
        help="Exact source image name. Overrides --image-family. Defaults to GCE_IMAGE_NAME.",
    )
    create_instance_parser.add_argument(
        "--network",
        help=f"VPC network name. Defaults to GCE_DEFAULT_NETWORK or {DEFAULT_NETWORK}.",
    )
    create_instance_parser.add_argument(
        "--service-account",
        help="Service account email. Defaults to GCE_INSTANCE_SERVICE_ACCOUNT.",
    )
    create_instance_parser.add_argument(
        "--tags",
        help="Comma-separated network tags. Defaults to GCE_INSTANCE_TAGS or http-server.",
    )
    create_instance_parser.add_argument(
        "--metadata",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help=(
            "Repeatable metadata assignment. Defaults to "
            "enable-oslogin=TRUE plus values from GCE_INSTANCE_METADATA."
        ),
    )
    create_instance_parser.add_argument(
        "--replace-existing",
        action="store_true",
        help="Delete an existing instance with the same name first.",
    )
    create_instance_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the commands that would run without modifying cloud state.",
    )
    create_instance_parser.set_defaults(handler=handle_create_instance)

    return parser


def add_common_build_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--flake-root",
        type=Path,
        help=(
            "Repository root containing flake.nix. Defaults to the current "
            "directory or its parents."
        ),
    )
    parser.add_argument(
        "--flake-attr",
        default=DEFAULT_FLAKE_ATTR,
        help=f"Flake package attribute to build. Default: {DEFAULT_FLAKE_ATTR}.",
    )


def handle_build(args: argparse.Namespace, *, runner: Runner, stdout: TextIO) -> int:
    shell = Shell(runner=runner, stdout=stdout)
    artifact = build_artifact(
        shell=shell,
        flake_root=resolve_flake_root(args.flake_root),
        flake_attr=args.flake_attr,
    )
    print(artifact.tarball, file=stdout)
    return 0


def handle_publish(args: argparse.Namespace, *, runner: Runner, stdout: TextIO) -> int:
    shell = Shell(runner=runner, stdout=stdout, dry_run=args.dry_run)
    flake_root = resolve_flake_root(args.flake_root)

    project = resolve_project(args.project, shell=shell)
    bucket = args.bucket or first_environment_value(BUCKET_ENV_VARS) or default_bucket_name(project)

    if args.artifact is not None:
        tarball = args.artifact.resolve()
        if not tarball.is_file():
            raise CliError(f"artifact does not exist: {tarball}")
        artifact = Artifact(directory=tarball.parent, tarball=tarball)
    else:
        artifact = build_artifact(
            shell=shell,
            flake_root=flake_root,
            flake_attr=args.flake_attr,
        )

    validate_labels(args.label)

    image_name = (
        args.image_name
        or first_environment_value(IMAGE_NAME_ENV_VARS)
        or derive_image_name(artifact.tarball.name)
    )
    object_name = args.object_name or artifact.tarball.name
    family = args.family or first_environment_value(IMAGE_FAMILY_ENV_VARS) or DEFAULT_IMAGE_FAMILY

    if not args.dry_run:
        ensure_bucket(
            shell=shell,
            project=project,
            bucket=bucket,
            location=args.bucket_location,
        )

    upload_artifact(
        shell=shell,
        project=project,
        bucket=bucket,
        tarball=artifact.tarball,
        object_name=object_name,
    )
    create_image(
        shell=shell,
        project=project,
        image_name=image_name,
        family=family,
        source_uri=f"gs://{bucket}/{object_name}",
        storage_location=args.storage_location,
        description=args.description,
        labels=args.label,
        replace_existing=args.replace_existing,
    )

    if args.share_with_authenticated_users:
        share_image_with_authenticated_users(
            shell=shell,
            project=project,
            image_name=image_name,
        )

    print(f"Published image: {image_name}", file=stdout)
    print(f"Source artifact: {artifact.tarball}", file=stdout)
    print(f"Cloud Storage URI: gs://{bucket}/{object_name}", file=stdout)
    return 0


def handle_create_instance(args: argparse.Namespace, *, runner: Runner, stdout: TextIO) -> int:
    shell = Shell(runner=runner, stdout=stdout, dry_run=args.dry_run)
    project = resolve_project(args.project, shell=shell)
    zone = (
        args.zone
        or first_environment_value(ZONE_ENV_VARS)
        or raise_cli_error("no zone configured; pass --zone or set GCE_DEFAULT_ZONE")
    )
    machine_type = (
        args.machine_type or first_environment_value(MACHINE_TYPE_ENV_VARS) or DEFAULT_MACHINE_TYPE
    )
    network = args.network or first_environment_value(NETWORK_ENV_VARS) or DEFAULT_NETWORK
    image_project = (
        args.image_project
        or first_environment_value(IMAGE_PROJECT_ENV_VARS)
        or first_environment_value(PROJECT_ENV_VARS)
        or project
    )
    image_name = args.image_name or first_environment_value(IMAGE_NAME_ENV_VARS)
    image_family = args.image_family or first_environment_value(IMAGE_FAMILY_ENV_VARS)
    if not image_name and not image_family:
        raise CliError("no image configured; pass --image-name/--image-family or set GCE_IMAGE_*")

    service_account = args.service_account or first_environment_value(SERVICE_ACCOUNT_ENV_VARS)
    tags = parse_csv(args.tags) or list(default_instance_tags_from_env())
    metadata = default_instance_metadata_from_env()
    metadata.extend(args.metadata)
    metadata = deduplicate_assignments(["enable-oslogin=TRUE", *metadata])
    validate_assignments(metadata, kind="metadata")

    if args.replace_existing and instance_exists(
        shell=shell,
        project=project,
        zone=zone,
        instance_name=args.name,
    ):
        shell.run(
            [
                "gcloud",
                "compute",
                "instances",
                "delete",
                args.name,
                "--project",
                project,
                "--zone",
                zone,
                "--quiet",
            ]
        )

    command = [
        "gcloud",
        "compute",
        "instances",
        "create",
        args.name,
        "--project",
        project,
        "--zone",
        zone,
        "--machine-type",
        machine_type,
        "--network",
        network,
        "--metadata",
        ",".join(metadata),
    ]
    if tags:
        command.extend(["--tags", ",".join(tags)])
    if service_account:
        command.extend(["--service-account", service_account])
        command.extend(["--scopes", "https://www.googleapis.com/auth/cloud-platform"])
    if image_name:
        command.extend(["--image", image_name])
    else:
        command.extend(["--image-family", image_family or DEFAULT_IMAGE_FAMILY])
    command.extend(["--image-project", image_project])

    shell.run(command)

    print(f"Created instance: {args.name}", file=stdout)
    print(f"Project: {project}", file=stdout)
    print(f"Zone: {zone}", file=stdout)
    print(f"Machine type: {machine_type}", file=stdout)
    print(f"Image project: {image_project}", file=stdout)
    return 0


def resolve_flake_root(candidate: Path | None) -> Path:
    if candidate is not None:
        flake_root = candidate.resolve()
        if not (flake_root / "flake.nix").is_file():
            raise CliError(f"flake.nix was not found under {flake_root}")
        return flake_root

    for directory in (Path.cwd(), *Path.cwd().parents):
        if (directory / "flake.nix").is_file():
            return directory
    raise CliError("could not locate flake.nix from the current directory")


def build_artifact(*, shell: Shell, flake_root: Path, flake_attr: str) -> Artifact:
    flake_ref = f"path:{flake_root}#{flake_attr}"
    result = shell.run(
        [
            "nix",
            "build",
            flake_ref,
            "--no-link",
            "--print-out-paths",
        ]
    )
    output_directory = Path(result.stdout.strip()).resolve() if result.stdout.strip() else Path()
    if shell.dry_run:
        return Artifact(directory=flake_root, tarball=flake_root / "dry-run.raw.tar.gz")

    if not output_directory.is_dir():
        raise CliError(f"nix build did not return a build directory: {output_directory}")

    tarballs = sorted(output_directory.glob("*.tar.gz"))
    if not tarballs:
        raise CliError(f"no .tar.gz artifact found in {output_directory}")
    if len(tarballs) != 1:
        raise CliError(
            f"expected one .tar.gz artifact in {output_directory}, found {len(tarballs)}"
        )

    return Artifact(directory=output_directory, tarball=tarballs[0].resolve())


def resolve_project(explicit_project: str | None, *, shell: Shell) -> str:
    if explicit_project:
        return explicit_project

    for variable in PROJECT_ENV_VARS:
        value = os.getenv(variable)
        if value:
            return value

    result = shell.run(["gcloud", "config", "get-value", "project"])
    project = result.stdout.strip()
    if not project or project == "(unset)":
        raise CliError(
            "no Google Cloud project is configured; pass --project or set GOOGLE_CLOUD_PROJECT"
        )
    return project


def default_bucket_name(project: str) -> str:
    return f"{project}{DEFAULT_BUCKET_SUFFIX}"


def first_environment_value(variable_names: Sequence[str]) -> str | None:
    for variable in variable_names:
        value = os.getenv(variable)
        if value:
            return value
    return None


def default_instance_tags_from_env() -> tuple[str, ...]:
    configured = first_environment_value(INSTANCE_TAGS_ENV_VARS)
    if configured:
        return tuple(parse_csv(configured))
    return DEFAULT_INSTANCE_TAGS


def default_instance_metadata_from_env() -> list[str]:
    configured = first_environment_value(INSTANCE_METADATA_ENV_VARS)
    return parse_csv(configured)


def parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def raise_cli_error(message: str) -> str:
    raise CliError(message)


def ensure_bucket(*, shell: Shell, project: str, bucket: str, location: str) -> None:
    describe = shell.run(
        [
            "gcloud",
            "storage",
            "buckets",
            "describe",
            f"gs://{bucket}",
            "--project",
            project,
        ],
        check=False,
    )
    if describe.returncode == 0:
        return

    shell.run(
        [
            "gcloud",
            "storage",
            "buckets",
            "create",
            f"gs://{bucket}",
            "--project",
            project,
            "--location",
            location,
            "--uniform-bucket-level-access",
        ]
    )


def upload_artifact(
    *,
    shell: Shell,
    project: str,
    bucket: str,
    tarball: Path,
    object_name: str,
) -> None:
    shell.run(
        [
            "gcloud",
            "storage",
            "cp",
            str(tarball),
            f"gs://{bucket}/{object_name}",
            "--project",
            project,
        ]
    )


def create_image(
    *,
    shell: Shell,
    project: str,
    image_name: str,
    family: str | None,
    source_uri: str,
    storage_location: str | None,
    description: str | None,
    labels: Sequence[str],
    replace_existing: bool,
) -> None:
    if replace_existing and image_exists(shell=shell, project=project, image_name=image_name):
        shell.run(
            [
                "gcloud",
                "compute",
                "images",
                "delete",
                image_name,
                "--project",
                project,
                "--quiet",
            ]
        )

    command = [
        "gcloud",
        "compute",
        "images",
        "create",
        image_name,
        "--project",
        project,
        "--source-uri",
        source_uri,
    ]

    if family:
        command.extend(["--family", family])
    if storage_location:
        command.extend(["--storage-location", storage_location])
    if description:
        command.extend(["--description", description])
    if labels:
        command.extend(["--labels", ",".join(labels)])

    shell.run(command)


def image_exists(*, shell: Shell, project: str, image_name: str) -> bool:
    result = shell.run(
        [
            "gcloud",
            "compute",
            "images",
            "describe",
            image_name,
            "--project",
            project,
        ],
        check=False,
    )
    return result.returncode == 0


def instance_exists(*, shell: Shell, project: str, zone: str, instance_name: str) -> bool:
    result = shell.run(
        [
            "gcloud",
            "compute",
            "instances",
            "describe",
            instance_name,
            "--project",
            project,
            "--zone",
            zone,
        ],
        check=False,
    )
    return result.returncode == 0


def share_image_with_authenticated_users(*, shell: Shell, project: str, image_name: str) -> None:
    shell.run(
        [
            "gcloud",
            "compute",
            "images",
            "add-iam-policy-binding",
            image_name,
            "--project",
            project,
            "--member",
            AUTHENTICATED_USERS_MEMBER,
            "--role",
            IMAGE_USER_ROLE,
        ]
    )


def derive_image_name(filename: str) -> str:
    image_name = filename
    if image_name.endswith(".raw.tar.gz"):
        image_name = image_name[: -len(".raw.tar.gz")]

    image_name = image_name.lower()
    image_name = re.sub(r"[^a-z0-9-]+", "-", image_name)
    image_name = re.sub(r"-{2,}", "-", image_name).strip("-")
    if not image_name:
        raise CliError("could not derive an image name from the artifact filename")
    if not image_name[0].isalpha():
        image_name = f"nixos-{image_name}"

    return image_name[:63].rstrip("-")


def validate_assignments(values: Sequence[str], *, kind: str) -> None:
    for value in values:
        if "=" not in value:
            raise CliError(f"{kind} must be KEY=VALUE: {value}")


def validate_labels(labels: Sequence[str]) -> None:
    validate_assignments(labels, kind="label")


def deduplicate_assignments(values: Sequence[str]) -> list[str]:
    resolved: dict[str, str] = {}
    order: list[str] = []
    for value in values:
        key, assigned_value = value.split("=", 1)
        if key not in resolved:
            order.append(key)
        resolved[key] = assigned_value
    return [f"{key}={resolved[key]}" for key in order]


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Runner = default_runner,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        return args.handler(args, runner=runner, stdout=stdout)
    except CliError as error:
        print(f"error: {error}", file=stderr)
        return 1
