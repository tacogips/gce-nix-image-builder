{

  description = "Build and publish a NixOS image for Google Compute Engine";

  inputs = {
    nixpkgs.url = "github:tacogips/nixpkgs-security/51712f4618983456364dc94f66736f6a9f942f6c";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs {
          inherit system;
          config.allowUnfree = true;
        };
        python = pkgs.python312;
        imageSystem = "x86_64-linux";
        gceImageSystem = nixpkgs.lib.nixosSystem {
          system = imageSystem;
          modules = [
            ./nix/gce-image.nix
          ];
        };
      in
      {
        packages.gceImage = gceImageSystem.config.system.build.googleComputeImage;

        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            curl
            direnv
            python
            terraform
            ruff
            uv
            go-task
            gh
            fd
            gnused
            google-cloud-sdk
            jq
            openssh
            qemu
          ];

          shellHook = ''
            echo "Python development environment ready"
            echo "Python version: $(python --version)"
            echo "uv version: $(uv --version)"
            echo "Task version: $(task --version 2>/dev/null || echo 'not available')"
            echo "gcloud version: $(gcloud version 2>/dev/null | sed -n '1p' || echo 'not available')"
            echo "qemu-img version: $(qemu-img --version 2>/dev/null | sed -n '1p' || echo 'not available')"
          '';
        };
      }
    );
}
