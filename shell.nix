{ pkgs ? import <nixpkgs> {} }:

pkgs.mkShell {
  buildInputs = with pkgs; [
    # Python with tkinter
    python3
  ];

  shellHook = ''
  '';
}
