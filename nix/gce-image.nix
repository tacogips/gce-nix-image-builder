{ lib, modulesPath, pkgs, ... }:

let
  webRoot = pkgs.writeTextDir "index.html" ''
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8">
        <title>gce-nix-image-builder</title>
      </head>
      <body>
        <h1>gce-nix-image-builder</h1>
        <p>This instance was built from the repository image.</p>
        <p>Nix flakes are enabled by default.</p>
        <p>allowUnfree is enabled by default.</p>
        <p>Terraform is installed on the image.</p>
      </body>
    </html>
  '';
in

{
  imports = [
    "${modulesPath}/virtualisation/google-compute-image.nix"
  ];

  environment.systemPackages = with pkgs; [
    curl
    direnv
    git
    jq
    terraform
  ];

  services.nginx = {
    enable = true;
    recommendedGzipSettings = true;
    recommendedOptimisation = true;
    recommendedProxySettings = true;
    virtualHosts."_" = {
      default = true;
      root = webRoot;
      locations."/".tryFiles = "$uri /index.html";
    };
  };

  nix = {
    settings = {
      experimental-features = [
        "nix-command"
        "flakes"
      ];
      accept-flake-config = true;
    };
  };

  nixpkgs.config.allowUnfree = true;

  documentation = {
    doc.enable = false;
    info.enable = false;
    man.enable = false;
    nixos.enable = false;
  };

  system.stateVersion = lib.mkDefault "24.11";
}
