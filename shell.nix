{ pkgs ? import <nixpkgs> {} }:

pkgs.mkShell {
  buildInputs = with pkgs; [
    python3
    immich-cli
  ];

  shellHook = ''
    python wg.py
  '';
}
