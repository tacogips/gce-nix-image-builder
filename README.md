# gce

Build and publish a bootable NixOS image for Google Compute Engine.

The generated Compute Engine image is intended to be shared with `allAuthenticatedUsers`
by default through the `roles/compute.imageUser` IAM binding so that any authenticated
Google user or service account can use it.

The currently published sandbox image lives in project `sandbox-taco` and is exposed via
image family `gce-nixos-sandbox`.

## Requirements

- Nix with flakes enabled
- Python 3.12 or newer
- `uv`
- `gcloud` authenticated for the target project

## Local Development

```bash
nix develop
uv sync --dev
uv run pytest
uv run ruff check .
uv run ruff format .
```

## Build The GCE Artifact

```bash
uv run python -m gce build
```

This builds the flake output `.#gceImage`, which resolves to
`config.system.build.googleComputeImage` from the pinned `nixpkgs`.

The resulting image boots with these defaults:

- `nix-command` and `flakes` enabled
- `nixpkgs.config.allowUnfree = true`
- `terraform`, `direnv`, `git`, `curl`, and `jq` installed
- `nginx` enabled on port `80` with a simple verification page

## Publish To Google Cloud

```bash
uv run python -m gce publish \
  --project YOUR_PROJECT_ID \
  --bucket YOUR_BUCKET_NAME
```

Useful flags:

- `--artifact /path/to/image.raw.tar.gz`: reuse an already-built tarball.
- `--replace-existing`: delete an existing image with the same name first.
- `--storage-location us`: pin the Compute Engine image storage location.
- `--family gce-nixos`: control the image family.
- `--no-share-with-authenticated-users`: opt out of the default public-to-authenticated-users image sharing.
- `--dry-run`: print the commands without changing local or cloud state.

If `--bucket` is omitted, the CLI defaults to `<project-id>-gce-nixos-images`.
If `--project` is omitted, the CLI tries `GCE_PROJECT`, `GOOGLE_CLOUD_PROJECT`,
`GCLOUD_PROJECT`, `CLOUDSDK_CORE_PROJECT`, then `gcloud config get-value project`.
If `--bucket`, `--family`, or `--image-name` are omitted, the CLI also checks
`GCE_BUCKET`, `GCE_IMAGE_BUCKET`, `GCE_IMAGE_FAMILY`, and `GCE_IMAGE_NAME`.

## Create A VM From The Published Image

```bash
uv run python -m gce create-instance my-vm
```

The `create-instance` subcommand uses repository defaults from environment variables when
flags are omitted:

- `GCE_PROJECT`: target project that will own the VM
- `GCE_IMAGE_PROJECT`: project that owns the shared image
- `GCE_IMAGE_FAMILY`: default image family
- `GCE_IMAGE_NAME`: optional exact image name override
- `GCE_DEFAULT_ZONE`: target zone
- `GCE_DEFAULT_MACHINE_TYPE`: machine type
- `GCE_DEFAULT_NETWORK`: VPC network name
- `GCE_INSTANCE_SERVICE_ACCOUNT`: service account attached to the VM
- `GCE_INSTANCE_TAGS`: default network tags
- `GCE_INSTANCE_METADATA`: additional comma-separated metadata assignments

Useful flags:

- `--image-name NAME`: pin to one exact image instead of the family.
- `--image-family FAMILY`: override the default family.
- `--image-project PROJECT`: override the image-owning project.
- `--project PROJECT`: create the VM in a different consumer project.
- `--zone ZONE`: place the VM in a different zone.
- `--machine-type TYPE`: override the low-cost default.
- `--network NETWORK`: select a different VPC.
- `--tags web,ssh`: override the default tags.
- `--metadata KEY=VALUE`: append additional instance metadata.
- `--replace-existing`: delete and recreate an existing VM with the same name.
- `--dry-run`: print the `gcloud` command without creating anything.

Equivalent direct `gcloud` usage:

```bash
gcloud compute instances create my-vm \
  --project YOUR_PROJECT_ID \
  --zone us-central1-a \
  --machine-type e2-micro \
  --image-family gce-nixos-sandbox \
  --image-project sandbox-taco \
  --network default \
  --metadata enable-oslogin=TRUE \
  --tags http-server
```

## Using The Shared Image From Another Account

Yes. The image is usable by people and service accounts that are not members of the
`sandbox-taco` project, because the image itself is granted
`roles/compute.imageUser` for `allAuthenticatedUsers`.

What this does mean:

- Any authenticated Google identity can reference the image when creating a VM.
- The consumer can do that from their own Google Cloud project.

What this does not mean:

- Anonymous users cannot use it.
- The image is not globally public without login.
- The consumer still needs their own Google Cloud project, billing, and permission to
  create instances there.

Typical cross-account usage looks like this:

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud compute instances create my-vm \
  --zone us-central1-a \
  --machine-type e2-micro \
  --image-family gce-nixos-sandbox \
  --image-project sandbox-taco \
  --metadata enable-oslogin=TRUE \
  --tags http-server
```

Or through this repository CLI after setting the repo-scoped defaults:

```bash
uv run python -m gce create-instance my-vm --project YOUR_PROJECT_ID
```

## Repository Defaults

This repository uses repo-scoped environment variables for the currently published sandbox image:

- `GCE_PROJECT`: target project for publish operations
- `GCE_IMAGE_PROJECT`: project that owns the published image
- `GCE_BUCKET`: Cloud Storage bucket for image tarballs
- `GCE_IMAGE_FAMILY`: published image family
- `GCE_IMAGE_NAME`: current published image name
- `GCE_DEFAULT_ZONE`: preferred zone for test instances
- `GCE_DEFAULT_MACHINE_TYPE`: preferred low-cost machine type
- `GCE_DEFAULT_NETWORK`: preferred VPC network name
- `GCE_INSTANCE_SERVICE_ACCOUNT`: service account used by sandbox instances
- `GCE_INSTANCE_TAGS`: default network tags for sandbox instances
- `GCE_INSTANCE_METADATA`: extra instance metadata appended during VM creation

The repository already loads repo-scoped `kinko` values from [`.envrc`](/g/gits/tacogips/gce-nix-image-builder/.envrc), so once those keys are stored in `kinko`, they become available automatically inside `direnv`.

## Boot Behavior

The image imports NixOS `google-compute-image.nix`, which already includes the GCE guest
configuration, OS Login support, and the raw tarball format expected by
`gcloud compute images create --source-uri=gs://...`.

To use OS Login on instances created from the image, set `enable-oslogin=TRUE` at the
instance or project metadata level in Google Cloud.

## Flake Development Shell

`flake.nix` includes the local tooling needed for this workflow, including:

- `terraform`
- `direnv`
- `google-cloud-sdk`
- `qemu`
- `ruff`
- `uv`

## Common Commands

```bash
task sync
task run
task image-build
task image-publish
task instance-create -- my-vm
task test
task lint
task fmt
task build
```
