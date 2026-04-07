{

  description = "A Python project";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/release-24.11";
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
        pkgs = import nixpkgs { inherit system; };
        python = pkgs.python312;
      in
      {
        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            python
            uv
            go-task
            gh
            fd
            gnused
          ];

          shellHook = ''
            echo "Python development environment ready"
            echo "Python version: $(python --version)"
            echo "uv version: $(uv --version)"
            echo "Task version: $(task --version 2>/dev/null || echo 'not available')"
          '';
        };
      }
    );
}
