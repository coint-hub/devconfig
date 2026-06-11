let
  pkgs = import <nixpkgs> { };

  # unstable @ 2026.06.06
  unstablePkgs = import (fetchTarball {
    url = "https://github.com/nixos/nixpkgs/archive/a799d3e3886da994fa307f817a6bc705ae538eeb.tar.gz";
    sha256 = "11mhk782xy1n58518f86k6fcvxjaaim3mk9nmhx68fg5i2jg9ayx";
  }) { };
in
pkgs.mkShellNoCC {
  packages = [
    # python
    unstablePkgs.python314
    unstablePkgs.basedpyright
    unstablePkgs.ruff
    unstablePkgs.ty
    unstablePkgs.uv
  ];
}
