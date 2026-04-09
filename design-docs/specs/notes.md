# Design Notes

## Research Findings

### Upstream NixOS Build Target

The pinned `nixpkgs` revision already exposes `config.system.build.googleComputeImage`
through `nixos/modules/virtualisation/google-compute-image.nix`. That module produces a
gzip-compressed raw disk tarball named like:

`nixos-image-<label>-x86_64-linux.raw.tar.gz`

This repository uses that upstream target directly instead of creating a custom disk-image
pipeline.

### Google Cloud Publication Flow

The publication workflow implemented in this repository follows the current Google Cloud CLI
shape:

1. Upload the `.raw.tar.gz` artifact to Cloud Storage.
2. Create a Compute Engine image from `--source-uri=gs://...`.
3. Grant `roles/compute.imageUser` to `allAuthenticatedUsers` on the created image.

### Access Model

Sharing the image with `allAuthenticatedUsers` makes the Compute Engine image usable by any
authenticated Google user or service account. This is broader than project-local sharing and
should remain the default only because it is an explicit repository requirement.
